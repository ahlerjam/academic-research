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

Tokenbudget (WICHTIG): die Zielgroesse ist in **Modell-Tokens** definiert, nicht
in Woertern. Das Embedding-Backend ``intfloat/multilingual-e5-small`` hat ein
hartes Kontextfenster von ``max_seq_length=512``; ``SentenceTransformer.encode``
schneidet laengere Eingaben STILLSCHWEIGEND ab -- ohne Log, ohne Exception. Ein
zu grosser Chunk verliert seinen Schwanz also ersatzlos aus dem Vektor, und zwar
unbemerkt. Eine wortbasierte Zaehlung kann diese Grenze prinzipiell nicht
einhalten, weil der XLM-R-SentencePiece-Tokenizer je nach Textsorte stark
unterschiedlich viele Tokens pro Wort erzeugt (gemessen an e5-small):

===================== ==============
Textsorte             Tokens / Wort
===================== ==============
englische Prosa                 1.67
deutsche Prosa                  2.47
Literaturverzeichnis            4.06
CJK                             6.00
Summenformeln                   7.60
deutsche Komposita             10.67
URLs                           38.00
===================== ==============

Deshalb wird die Fenstergroesse ueber einen :data:`TokenCounter` bestimmt:
:func:`resolve_token_counter` nimmt bevorzugt den ECHTEN Tokenizer des
konfigurierten Embedding-Modells und faellt nur dann auf die Zeichen-Naeherung
:func:`approximate_token_count` zurueck, wenn der Tokenizer nicht ladbar ist
(offline CI, Backend deinstalliert) -- dann mit Warnung im Log.
"""

from __future__ import annotations

import logging
import math
import os
import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .embedding_model import DEFAULT_MODEL_ID, ENV_MODEL_ID
from .embeddings import build_contextual_embedding_text

logger = logging.getLogger(__name__)

# Hartes Kontextfenster von intfloat/multilingual-e5-small
# (== SentenceTransformer.max_seq_length == tokenizer.model_max_length).
# Alles darueber wird vom Backend stillschweigend abgeschnitten.
MODEL_MAX_TOKENS = 512

# Reserve fuer alles, was neben dem Chunk-Text im Modell-Input landet:
# Kontextsatz (gemessen 17 Tokens bei kurzem, 28 bei langem Section-Titel),
# e5-Praefix "passage: " (2) und die Sondertokens <s>/</s> (2). 64 laesst
# genug Luft fuer einen laengeren, per Anthropic-API generierten Kontextsatz.
CONTEXT_TOKEN_RESERVE = 64

# Tokenbudget fuer den reinen Chunk-Text. Der VOLLSTAENDIGE Embedding-Input
# (Kontextsatz + Chunk) zielt damit auf MODEL_MAX_TOKENS.
TARGET_TOKENS = MODEL_MAX_TOKENS - CONTEXT_TOKEN_RESERVE

# "passage: " + <s>/</s>: der Aufschlag, den E5SmallEmbedder.embed_documents
# zusaetzlich zum embedding_text an das Modell gibt.
MODEL_INPUT_OVERHEAD_TOKENS = 4

# 10-15%-Korridor aus dem Issue; 0.125 liegt exakt in der Mitte.
OVERLAP_RATIO = 0.125

# Zeichen je Token fuer die Fallback-Naeherung (siehe approximate_token_count).
CHARS_PER_TOKEN = 2.5

# Fallback, falls die Section-Heading-Heuristik keine Ueberschrift vor einem
# Chunk findet. AC1 verlangt nur "befuellt", nicht "inhaltlich korrekt".
DEFAULT_SECTION_TITLE = "Unbenannter Abschnitt"

# Section-Heading-Heuristik: eine Zeile gilt als Ueberschrift, wenn sie
# (a) optional mit einer Nummerierung ("1", "2.3", "1.") beginnt und
# (b) danach ausschliesslich aus 1-7 Woertern besteht, die jeweils mit einem
#     Grossbuchstaben starten (Title Case), ohne Satzzeichen am Ende.
# Bekannte False Positives: PDF-Textextraktion bricht Zeilen nach Layout um,
# daher passen auch Fliesstext-Reste auf dieses Muster ("Smith", "However",
# "Deep Learning" -- Absatzende, umbrochener Eigenname, Literaturliste).
# Das ist akzeptiert, weil die Erkennung folgenlos fuer den Inhalt ist: sie
# vergibt nur ein Label, siehe :func:`_split_words_with_metadata`.
_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?"
    r"[A-ZÄÖÜ][\w\-]*(?:\s+[A-ZÄÖÜ][\w\-]*){0,6}$"
)
_MAX_HEADING_LEN = 80


# ``token_counter``-Vertrag: gibt die Tokenanzahl von ``text`` zurueck (ohne
# Sondertokens) und ist MONOTON -- das Anhaengen weiterer Woerter darf das
# Ergebnis nie verkleinern. Die Fenstersuche in :func:`_window_end` setzt genau
# diese Monotonie voraus (Subword-Tokenizer, Wort- und Zeichenzaehlung erfuellen
# sie alle).
TokenCounter = Callable[[str], int]


def approximate_token_count(text: str) -> int:
    """Zeichenbasierte Tokennaeherung -- Fallback OHNE echten Tokenizer.

    Subword-Tokens skalieren primaer mit der Zeichenzahl, nicht mit der
    Wortzahl: ein deutsches Kompositum ist EIN Wort, aber ein gutes Dutzend
    Tokens. Daher ``max(Wortzahl, Zeichen / CHARS_PER_TOKEN)``.

    EHRLICHE GRENZE: die Naeherung ist auf Fliesstext kalibriert (dort
    ueberschaetzt sie um Faktor ~1.6, liegt also auf der sicheren Seite). Bei
    zeichen-dichtem Sonderfall-Material -- Summenformeln, Formelsatz, CJK --
    UNTERschaetzt sie den echten e5-Tokenizer um bis zu ~40%. Eine Garantie fuer
    das Kontextfenster ist ausschliesslich der echte Tokenizer
    (:func:`model_token_counter`); dieser Fallback existiert, damit die Suite
    hermetisch offline laufen kann, und meldet sich beim Einsatz im Log.
    """
    words = text.split()
    if not words:
        return 0
    chars = sum(len(word) for word in words)
    return max(len(words), math.ceil(chars / CHARS_PER_TOKEN))


def _load_tokenizer(model_id: str) -> Any:
    """Laedt den Tokenizer des Embedding-Modells.

    Eigene Funktion, damit tests/conftest.py sie -- analog zu
    ``embedding_model._load_backend_model`` -- blockieren kann: sonst zoege
    jeder ``chunk_pages``-Aufruf der Suite Tokenizer-Dateien von HuggingFace
    und die CI waere netzabhaengig.
    """
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_id)


# ``None`` bedeutet "Tokenizer nicht ladbar" und wird bewusst mitgecacht, damit
# nicht jeder chunk_pages-Aufruf einen teuren Ladeversuch neu startet.
_TOKENIZER_CACHE: dict[str, Any | None] = {}


def reset_token_counter_cache() -> None:
    """Leert den Tokenizer-Cache (Tests, Modellwechsel zur Laufzeit)."""
    _TOKENIZER_CACHE.clear()


def model_token_counter(model_id: str | None = None) -> TokenCounter | None:
    """Exakter Tokenzaehler des Embedding-Modells, oder ``None``.

    ``None`` ist ein Degradations-, kein Absturzpfad (analog zu
    ``embedding_model.get_embedder``): ohne Tokenizer chunkt das Modul mit
    :func:`approximate_token_count` weiter.
    """
    key = model_id or os.environ.get(ENV_MODEL_ID) or DEFAULT_MODEL_ID
    if key not in _TOKENIZER_CACHE:
        try:
            _TOKENIZER_CACHE[key] = _load_tokenizer(key)
        except Exception as exc:
            logger.warning(
                "Tokenizer '%s' nicht ladbar (%s: %s) — Chunk-Groessen werden "
                "genaehert (approximate_token_count), nicht exakt gemessen.",
                key,
                type(exc).__name__,
                exc,
            )
            _TOKENIZER_CACHE[key] = None

    tokenizer = _TOKENIZER_CACHE[key]
    if tokenizer is None:
        return None

    def _count(text: str) -> int:
        # .tokenize() statt .encode(): zaehlt die Stuecke OHNE Sondertokens
        # (encode wuerde <s>/</s> mitzaehlen, die MODEL_INPUT_OVERHEAD_TOKENS
        # bereits abdeckt). verbose=False unterdrueckt die
        # "sequence length is longer than..."-Warnung von transformers, die
        # bei der Fenstersuche zwangslaeufig auftritt und nur Rauschen ist --
        # ueber das Budget wacht _warn_if_over_context_window.
        return len(tokenizer.tokenize(text, verbose=False))

    return _count


def resolve_token_counter(token_counter: TokenCounter | None = None) -> TokenCounter:
    """Waehlt den Tokenzaehler: injiziert > echter Tokenizer > Naeherung."""
    if token_counter is not None:
        return token_counter
    counter = model_token_counter()
    if counter is not None:
        return counter
    return approximate_token_count


def count_tokens(text: str) -> int:
    """Tokenanzahl von ``text`` mit dem Standard-Zaehler des Moduls.

    Nutzt den echten Tokenizer des Embedding-Modells, sofern ladbar, sonst
    :func:`approximate_token_count`.
    """
    return resolve_token_counter()(text)


def _detect_heading(line: str) -> str | None:
    """Erkennt eine Section-Ueberschrift per Regex-Heuristik. ``None`` sonst.

    Reine Label-Vergabe: der Rueckgabewert entscheidet NICHT darueber, ob die
    Zeile in den Wortstrom aufgenommen wird (das tut sie immer).
    """
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

    Macht KEINEN API-Call und ist seit #632 der einzige Kontextsatz-Weg:
    keine Plugin-Funktion darf einen eigenen Modellzugang voraussetzen. Ein
    abweichender ``context_provider`` bleibt ueber :func:`chunk_pages`
    injizierbar.
    """
    return (
        f'Dieser Abschnitt stammt aus "{section_title}" '
        f"(Seite {page_start}-{page_end}, Chunk {chunk_index})."
    )


def _split_words_with_metadata(
    pages: list[tuple[int, str]],
) -> tuple[list[str], list[int], list[tuple[int, str]]]:
    """Baut den globalen Wortstrom samt Seiten- und Heading-Metadaten.

    Der Wortstrom ist VERLUSTFREI: jede nicht-leere Zeile landet vollstaendig
    in ``words`` -- auch eine als Ueberschrift erkannte. Die Heading-Erkennung
    ist bewusst nur eine additive Annotation (sie merkt sich den Wortindex),
    kein Filter. Grund: die Heuristik ist zwangslaeufig unscharf, weil
    PDF-Textextraktion Zeilen nach Layout umbricht und dabei ganz normale
    Fliesstext-Zeilen aus ein bis zwei grossgeschriebenen Woertern ohne
    Satzzeichen entstehen ("Smith", "However", "Deep Learning"). Wuerde eine
    solche Zeile aus dem Wortstrom fallen, waere der Text in keinem spaeteren
    Schritt rekonstruierbar -- stiller Inhaltsverlust. So kostet ein False
    Positive hoechstens ein falsches ``section_title``-Label.

    Returns:
        ``(words, word_pages, headings)`` -- ``word_pages[i]`` ist die
        Seitenzahl von ``words[i]``; ``headings`` ist eine aufsteigend nach
        Wortindex sortierte Liste ``(word_index, title)``, wobei
        ``word_index`` auf das ERSTE Wort der Ueberschrift zeigt (die
        Ueberschrift gehoert damit selbst zu ihrem Abschnitt).
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


def _window_end(words: list[str], start: int, budget: int, counter: TokenCounter) -> int:
    """Groesster Index ``end``, fuer den ``words[start:end]`` ins Budget passt.

    Exponentielles Vortasten + Binaersuche: O(log k) Zaehler-Aufrufe je Chunk
    statt einer Zaehlung pro Wort. Korrekt fuer jeden monotonen ``counter``
    (siehe :data:`TokenCounter`).

    Gibt IMMER mindestens ``start + 1`` zurueck -- auch wenn schon ein einzelnes
    Wort das Budget sprengt (ueberlange URL, Summenformel). Sonst entstuende
    entweder eine Endlosschleife oder ein stillschweigend verschlucktes Wort.
    """
    n = len(words)
    span = 1
    best = start + 1
    while start + span <= n:
        end = start + span
        if counter(" ".join(words[start:end])) > budget:
            break
        best = end
        if end == n:
            return n
        span *= 2

    low, high = best, min(start + span, n)
    while low < high:
        mid = (low + high + 1) // 2
        if counter(" ".join(words[start:mid])) <= budget:
            low = mid
        else:
            high = mid - 1
    return max(low, start + 1)


def chunk_pages(
    pages: list[tuple[int, str]],
    target_tokens: int = TARGET_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
    context_provider: ContextProvider | None = None,
    token_counter: TokenCounter | None = None,
) -> list[Chunk]:
    """Zerlegt seitenweisen Text in ueberlappende, seitenbewusste Chunks.

    Die Fenstergroesse wird in MODELL-Tokens bestimmt (siehe Modul-Docstring),
    nicht in Woertern: jeder Chunk ist der laengste Wortlauf, der noch in
    ``target_tokens`` passt.

    Args:
        pages: Liste ``(page_number, text)``, 1-indexed, in Lesereihenfolge.
        target_tokens: Tokenbudget je Chunk-Text (ohne Kontextsatz).
        overlap_ratio: Ueberlappungsanteil benachbarter Chunks (0.10-0.15),
            bezogen auf die Wortzahl des jeweils vorangehenden Chunks.
        context_provider: Optionale Funktion
            ``(chunk_text, section_title, chunk_index, page_start, page_end) -> str``.
            ``None`` = :func:`default_context_sentence` (deterministisch, offline).
        token_counter: Optionaler Tokenzaehler. ``None`` = echter Tokenizer des
            Embedding-Modells, ersatzweise :func:`approximate_token_count`.

    Returns:
        Liste von :class:`Chunk` in Dokumentreihenfolge. Leer, wenn ``pages``
        keinen Body-Text enthaelt.
    """
    words, word_pages, headings = _split_words_with_metadata(pages)
    if not words:
        return []

    counter = resolve_token_counter(token_counter)
    budget = max(1, target_tokens)
    n = len(words)

    chunks: list[Chunk] = []
    start = 0
    chunk_index = 0
    while start < n:
        end = _window_end(words, start, budget, counter)
        chunk_text = " ".join(words[start:end])
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
        _warn_if_over_context_window(chunk_index, embedding_text, counter)

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
        window = end - start
        # min(window - 1, ...) garantiert Fortschritt auch bei window == 1.
        overlap_words = min(window - 1, max(1, round(window * overlap_ratio)))
        start += max(1, window - overlap_words)
        chunk_index += 1

    return chunks


def _warn_if_over_context_window(
    chunk_index: int, embedding_text: str, counter: TokenCounter
) -> None:
    """Macht die sonst STILLE Kuerzung durch das Embedding-Backend sichtbar.

    ``SentenceTransformer.encode`` kuerzt auf ``max_seq_length`` ohne jedes
    Signal -- zwei Passagen, die sich erst nach Token 512 unterscheiden,
    ergeben denselben Vektor. Unvermeidbar bleibt das nur bei einem einzelnen
    ueberlangen Wort; alles andere ist ein Konfigurationsfehler und gehoert ins
    Log statt in eine stille Qualitaetsminderung.
    """
    total = counter(embedding_text) + MODEL_INPUT_OVERHEAD_TOKENS
    if total > MODEL_MAX_TOKENS:
        logger.warning(
            "Chunk %d sprengt das Kontextfenster des Embedding-Modells "
            "(%d > %d Tokens) — das Backend schneidet den Rest stillschweigend ab.",
            chunk_index,
            total,
            MODEL_MAX_TOKENS,
        )


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
    token_counter: TokenCounter | None = None,
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
        token_counter=token_counter,
    )
