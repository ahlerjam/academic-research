"""Seitenbewusstes generisches Chunking-Modul (Issue #374).

Zerlegt beliebige Paper/PDFs (kein Buch-Anwendungsfall wie ``scripts/chunk_pdf.py``,
das bewusst unveraendert bleibt) in einheitliche Retrieval-Chunks:

    Seitenweiser Text -> Wortstrom mit Seiten-/Section-Tracking
        -> Sliding-Window (~512 Tokens, 10-15% Overlap)
        -> Kontextsatz voranstellen (Anthropic-Contextual-Retrieval-Pattern)

Kernfunktion ist :func:`chunk_pages`, die eine Liste seitenweiser Texte
entgegennimmt (``[(page_number, text), ...]``, 1-indexed). :func:`chunk_pdf`
ist eine duenne Ingestion-Huelle, die ein PDF via pypdf seitenweise einliest
und direkt an :func:`chunk_pages` weiterreicht -- sie dupliziert NICHT die
eigentliche Volltext-Extraktion (#373, ``academic_vault/fulltext.py``), die
Seiten zu einem einzigen Fliesstext zusammenfasst und die Seitengrenzen damit
absichtlich aufgibt.

Token-Naeherung: im Projekt ist kein echter Tokenizer (z.B. ``tiktoken``)
vorhanden. :func:`count_tokens` zaehlt daher Woerter statt BPE-Tokens -- eine
transparente Naeherung, keine exakte Zaehlung. Der Zielkorridor um 512 Tokens
ist als 512-Wort-Fenster umgesetzt.
"""

from __future__ import annotations

import logging
import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass

from .embeddings import build_contextual_embedding_text

logger = logging.getLogger(__name__)

# ~512 Tokens (wortbasierte Naeherung, siehe Modul-Docstring).
TARGET_TOKENS = 512
# 10-15%-Korridor aus dem Issue; 0.125 liegt exakt in der Mitte.
OVERLAP_RATIO = 0.125

# Fallback, falls die Section-Heading-Heuristik keine Ueberschrift vor einem
# Chunk findet. AC1 verlangt nur "befuellt", nicht "inhaltlich korrekt".
DEFAULT_SECTION_TITLE = "Unbenannter Abschnitt"

# Section-Heading-Heuristik: eine Zeile gilt als Ueberschrift, wenn sie
# (a) optional mit einer Nummerierung ("1", "2.3", "1.") beginnt und
# (b) danach ausschliesslich aus 1-7 Woertern besteht, die jeweils mit einem
#     Grossbuchstaben starten (Title Case) -- normale Fliesstext-Saetze
#     beginnen zwar auch grossgeschrieben, aber nicht mehrere Woerter in
#     Folge. Kein Satzzeichen am Ende (Ueberschriften enden selten mit ".").
_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?"
    r"[A-ZÄÖÜ][\w\-]*(?:\s+[A-ZÄÖÜ][\w\-]*){0,6}$"
)
_MAX_HEADING_LEN = 80


def count_tokens(text: str) -> int:
    """Wortbasierte Tokennaeherung (kein BPE-Tokenizer im Projekt vorhanden).

    Siehe Modul-Docstring: das ist eine bewusst transparente Heuristik, keine
    exakte Zaehlung von Modell-Tokens.
    """
    return len(text.split())


def _detect_heading(line: str) -> str | None:
    """Erkennt eine Section-Ueberschrift per Regex-Heuristik. ``None`` sonst."""
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return None
    if _HEADING_RE.match(stripped):
        return stripped
    return None


@dataclass
class Chunk:
    """Ein einzelner Retrieval-Chunk mit Audit-Trail-Feldern."""

    chunk_index: int
    chunk_text: str
    context_sentence: str
    embedding_text: str
    page_start: int
    page_end: int
    section_title: str


ContextProvider = Callable[[str, str, int, int, int], str]


def default_context_sentence(
    section_title: str, chunk_index: int, page_start: int, page_end: int
) -> str:
    """Deterministischer Offline-Default fuer den Kontextsatz.

    Macht KEINEN API-Call -- notwendig, damit Tests/CI ohne ANTHROPIC_API_KEY
    gruen bleiben (siehe :func:`anthropic_context_provider` fuer die optionale
    Anbindung an die echte Kontextsatz-Generierung aus #109).
    """
    return (
        f'Dieser Abschnitt stammt aus "{section_title}" '
        f"(Seite {page_start}-{page_end}, Chunk {chunk_index})."
    )


def anthropic_context_provider(
    paper_title: str,
    paper_abstract: str,
    paper_id: str,
    api_key: str | None = None,
) -> ContextProvider:
    """Baut einen ``context_provider``, der die echte Anthropic-API nutzt (#109).

    Macht bei jedem Chunk einen echten API-Call -- nur fuer den produktiven
    Einsatz gedacht, niemals als Default in Tests/CI (kein ANTHROPIC_API_KEY
    dort verfuegbar bzw. gewuenscht).
    """
    from .embeddings import generate_context_sentence

    def _provider(
        chunk_text: str, section_title: str, chunk_index: int, page_start: int, page_end: int
    ) -> str:
        sentence = generate_context_sentence(
            chunk_text=chunk_text,
            paper_title=paper_title,
            paper_abstract=paper_abstract,
            paper_id=paper_id,
            api_key=api_key,
        )
        return sentence or default_context_sentence(
            section_title, chunk_index, page_start, page_end
        )

    return _provider


def _split_words_with_metadata(
    pages: list[tuple[int, str]],
) -> tuple[list[str], list[int], list[tuple[int, str]]]:
    """Baut den globalen Wortstrom samt Seiten- und Heading-Metadaten.

    Returns:
        ``(words, word_pages, headings)`` -- ``word_pages[i]`` ist die
        Seitenzahl von ``words[i]``; ``headings`` ist eine aufsteigend nach
        Wortindex sortierte Liste ``(word_index, title)`` fuer jede erkannte
        Ueberschrift (Ueberschriftenzeilen selbst zaehlen NICHT als Body-Wort).
    """
    words: list[str] = []
    word_pages: list[int] = []
    headings: list[tuple[int, str]] = []

    for page_number, text in pages:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading = _detect_heading(line)
            if heading is not None:
                headings.append((len(words), heading))
                continue
            line_words = line.split()
            words.extend(line_words)
            word_pages.extend([page_number] * len(line_words))

    return words, word_pages, headings


def _section_title_at(headings: list[tuple[int, str]], word_index: int) -> str:
    """Section-Titel der zuletzt vor/an ``word_index`` erkannten Ueberschrift."""
    if not headings:
        return DEFAULT_SECTION_TITLE
    indices = [h[0] for h in headings]
    pos = bisect_right(indices, word_index) - 1
    if pos < 0:
        return DEFAULT_SECTION_TITLE
    return headings[pos][1]


def chunk_pages(
    pages: list[tuple[int, str]],
    target_tokens: int = TARGET_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
    context_provider: ContextProvider | None = None,
) -> list[Chunk]:
    """Zerlegt seitenweisen Text in ueberlappende, seitenbewusste Chunks.

    Args:
        pages: Liste ``(page_number, text)``, 1-indexed, in Lesereihenfolge.
        target_tokens: Zielgroesse je Chunk in wortbasierten Token-Naeherung.
        overlap_ratio: Ueberlappungsanteil benachbarter Chunks (0.10-0.15).
        context_provider: Optionale Funktion
            ``(chunk_text, section_title, chunk_index, page_start, page_end) -> str``.
            ``None`` = :func:`default_context_sentence` (deterministisch, offline).

    Returns:
        Liste von :class:`Chunk` in Dokumentreihenfolge. Leer, wenn ``pages``
        keinen Body-Text enthaelt.
    """
    words, word_pages, headings = _split_words_with_metadata(pages)
    if not words:
        return []

    n = len(words)
    overlap_tokens = max(1, round(target_tokens * overlap_ratio)) if target_tokens > 0 else 0
    step = max(1, target_tokens - overlap_tokens)

    chunks: list[Chunk] = []
    start = 0
    chunk_index = 0
    while start < n:
        end = min(start + target_tokens, n)
        chunk_words = words[start:end]
        chunk_text = " ".join(chunk_words)
        page_start = word_pages[start]
        page_end = word_pages[end - 1]
        section_title = _section_title_at(headings, start)

        if context_provider is not None:
            context_sentence = context_provider(
                chunk_text, section_title, chunk_index, page_start, page_end
            )
        else:
            context_sentence = default_context_sentence(
                section_title, chunk_index, page_start, page_end
            )
        embedding_text = build_contextual_embedding_text(context_sentence, chunk_text)

        chunks.append(
            Chunk(
                chunk_index=chunk_index,
                chunk_text=chunk_text,
                context_sentence=context_sentence,
                embedding_text=embedding_text,
                page_start=page_start,
                page_end=page_end,
                section_title=section_title,
            )
        )

        if end >= n:
            break
        start += step
        chunk_index += 1

    return chunks


def extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    """Liest ein PDF seitenweise via pypdf ein (1-indexed Seitennummern).

    Duenne Ingestion-Huelle fuer :func:`chunk_pdf` -- KEIN Ersatz fuer die
    Volltext-Extraktion aus #373 (``academic_vault/fulltext.py``): jene
    funktioniert seitenuebergreifend und mit optionalem GROBID-Backend, gibt
    dafuer aber bewusst keine Seitenzuordnung mehr zurueck. Hier zaehlt genau
    die Seitenzuordnung, also ein eigener, minimaler Pfad.
    """
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            logger.warning("Seite %d in %s nicht extrahierbar", i, pdf_path, exc_info=True)
            text = ""
        pages.append((i, text))
    return pages


def chunk_pdf(
    pdf_path: str,
    target_tokens: int = TARGET_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
    context_provider: ContextProvider | None = None,
) -> list[Chunk]:
    """Liest ein PDF seitenweise ein und zerlegt es in Retrieval-Chunks.

    Kombiniert :func:`extract_pages` und :func:`chunk_pages`.
    """
    pages = extract_pages(pdf_path)
    return chunk_pages(
        pages,
        target_tokens=target_tokens,
        overlap_ratio=overlap_ratio,
        context_provider=context_provider,
    )
