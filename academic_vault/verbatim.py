"""Lokales Verbatim-Verifikationsmodul fuer Zitat-Kandidaten (Issue #511).

Prueft einen Zitat-Kandidaten deterministisch gegen den seitengenauen
lokalen PDF-Volltext (:func:`academic_vault.chunking.extract_pages`, NICHT
:func:`academic_vault.fulltext.extract_fulltext` -- jene funktioniert
seitenuebergreifend und gibt die Seitengrenzen bewusst auf, hier zaehlt
genau die Seitenzuordnung). Fundament fuer API-freien Halluzinationsschutz
nach dem Prinzip "Vektoren finden, Text beweist".

Ablauf von :func:`verify_verbatim`:

1. Kein Text-Layer auf keiner Seite -> ``status="no-textlayer"``, Kurzschluss
   VOR jeder Normalisierung/jedem Vergleich.
2. Kandidat und Seitentexte werden SCHWACH normalisiert (nur
   Anfuehrungszeichen-/Apostroph-Varianten auf ASCII, Whitespace kollabiert --
   siehe :func:`_normalize_weak`). ``exact`` bleibt damit reserviert fuer
   reine Darstellungsvarianten, die den Wortlaut nicht veraendern. Exakter
   Substring-Treffer auf irgendeiner Seite (erste Seite mit Treffer gewinnt,
   deterministisch bei Mehrfachvorkommen) -> ``status="exact"``.
3. Kein exakter Treffer -> Kandidat und Seitentexte werden VOLL normalisiert
   (zusaetzlich NFKC -- loest u.a. Ligaturen wie ﬁ/ﬂ gemaess
   Unicode-Kompatibilitaetszerlegung auf --, sowie Zeilenend-Trennstriche
   zusammengefuehrt; siehe :func:`normalize_text`). Fuzzy-Suche mit rapidfuzz
   ueber ein kandidatlanges Sliding-Window je Seite auf diesem voll
   normalisierten Text. Bester Treffer >= :data:`SNAP_RATIO_THRESHOLD` ->
   ``status="snapped"``, ``verbatim`` ist der NORMALISIERTE QUELLTEXT an der
   Fundstelle -- NIE der Kandidat. Ligatur-/Trennstrich-Abweichungen vom
   Kandidaten landen damit AC-konform bei ``snapped``, nicht bei ``exact``.
4. Sonst -> ``status="no-match"``.

DESIGN-ENTSCHEIDUNG (``verbatim``-Feld): der zurueckgegebene Wortlaut ist der
normalisierte Quelltext (glatte Anfuehrungszeichen, bei ``snapped``
zusaetzlich aufgeloeste Ligaturen/zusammengefuehrte Trennstriche) -- nicht
der rohe PDF-Bytestream. Das ist exakt die Textform, gegen die verglichen
wird, bleibt fuer Weiterverarbeitung (Zitat-Einfuegen) typografisch sauber
und ist ohne verlustbehaftete Rueck-Projektion auf den Rohtext eindeutig
herleitbar (Normalisierung veraendert die Zeichenlaenge, z. B. durch
Trennstrich-Join -- eine 1:1-Rueckabbildung auf Roh-Byte-Positionen waere
nicht robust herleitbar).

Scope-Grenze (aus dem Issue-Body): ``add_quote``-Integration und MCP-Tool
sind explizit spaetere Issues -- dieses Modul ist reine Pruefung, keine
Anbindung an ``server.py``/``db.py``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from .chunking import extract_pages

VerbatimStatus = Literal["exact", "snapped", "no-match", "no-textlayer"]

# Ab diesem rapidfuzz-Score (0.0-1.0) gilt ein Fuzzy-Treffer als "snapped"
# statt "no-match". Vorschlag aus der Planung: 90 % -- niedrig genug fuer
# legitime Tippfehler-Varianten, hoch genug, dass unterschiedliche Saetze
# nicht faelschlich zugeordnet werden (Halluzinationsschutz ist genau das
# Gegenteil sonst). Bleibt als benannte Modul-Konstante aenderbar.
SNAP_RATIO_THRESHOLD = 0.90

# Anfuehrungszeichen-/Apostroph-Varianten -> ASCII-Aequivalent.
_QUOTE_MAP = {
    "“": '"',  # LEFT DOUBLE QUOTATION MARK "
    "”": '"',  # RIGHT DOUBLE QUOTATION MARK "
    "„": '"',  # DOUBLE LOW-9 QUOTATION MARK „
    "«": '"',  # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK «
    "»": '"',  # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK »
    "‘": "'",  # LEFT SINGLE QUOTATION MARK '
    "’": "'",  # RIGHT SINGLE QUOTATION MARK '
    "‚": "'",  # SINGLE LOW-9 QUOTATION MARK ‚
    "´": "'",  # ACUTE ACCENT ´ (haeufige Apostroph-Ersatzdarstellung)
    "`": "'",  # GRAVE ACCENT `
}
_QUOTE_TRANSLATION = str.maketrans(_QUOTE_MAP)

# Zeilenend-Trennstrich: <Wortzeichen>-<Zeilenumbruch><Kleinbuchstabe> wird zu
# <Wortzeichen><Kleinbuchstabe> zusammengefuehrt (Hyphen + Newline entfallen).
# Die Kleinbuchstaben-Bedingung auf der Folgezeile grenzt echte
# Trennstrich-Zeilenumbrueche von zufaelligen Zeilenenden auf "-" vor
# Aufzaehlungen/Grossschreibung ab.
_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\n([a-zà-öø-ÿ])")


def _join_hyphenated_linebreaks(text: str) -> str:
    return _HYPHEN_LINEBREAK_RE.sub(r"\1\2", text)


def normalize_text(text: str) -> str:
    """Normalisiert Text fuer den ``snapped``-Vergleich (siehe Modul-Docstring).

    "Volle" Normalisierung, Reihenfolge: NFKC (u. a. Ligatur-Aufloesung) ->
    Anfuehrungszeichen-/Apostroph-Mapping -> Trennstrich-Zeilenumbruch-Join ->
    Whitespace-Kollaps. Idempotent:
    ``normalize_text(normalize_text(x)) == normalize_text(x)``.

    Fuer den ``exact``-Vergleich wird bewusst NICHT diese Funktion verwendet,
    sondern die schwaechere :func:`_normalize_weak` (siehe dort) -- damit
    Ligatur-/Trennstrich-Abweichungen laut AC #511 als ``snapped`` erkannt
    werden statt als ``exact`` durchzugehen.
    """
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(_QUOTE_TRANSLATION)
    normalized = _join_hyphenated_linebreaks(normalized)
    return " ".join(normalized.split())


def _normalize_weak(text: str) -> str:
    """Normalisiert Text fuer den ``exact``-Vergleich (siehe Modul-Docstring).

    Nur Anfuehrungszeichen-/Apostroph-Mapping und Whitespace-Kollaps -- OHNE
    NFKC (Ligatur-Aufloesung) und OHNE Trennstrich-Zeilenumbruch-Join. Diese
    beiden Normalisierungsschritte zaehlen laut AC-Wortlaut in Issue #511
    explizit als "leicht abweichender Kandidat" und muessen ueber den
    Fuzzy-Pfad (:func:`normalize_text` + rapidfuzz) als ``snapped`` erkannt
    werden, nicht bereits hier als ``exact`` durchgewunken werden.
    Idempotent, analog zu :func:`normalize_text`.
    """
    normalized = text.translate(_QUOTE_TRANSLATION)
    return " ".join(normalized.split())


#: Oeffentlicher Alias fuer :func:`_normalize_weak` (Issue #846).
#: :mod:`academic_vault.quote_match` braucht dieselbe schwache Normalisierung
#: fuer den Wortlaut-Abgleich im Guard-Pfad. Ein Zugriff auf den
#: unterstrichenen Namen aus einem anderen Modul waere die Falle aus #501
#: (privater Zugriff von aussen), ein zweiter Normalisierer waere schlimmer:
#: zwei Definitionen von "gleich bis auf Darstellung" liefen auseinander.
normalize_weak = _normalize_weak


@dataclass
class VerbatimResult:
    """Ergebnis von :func:`verify_verbatim`.

    Attributes:
        status: ``exact`` | ``snapped`` | ``no-match`` | ``no-textlayer``.
        verbatim: Wortlaut AUS DER QUELLE (normalisiert). Bei ``status=exact``
            schwach normalisiert (Anfuehrungszeichen/Whitespace), bei
            ``status=snapped`` voll normalisiert (zusaetzlich NFKC/Trennstrich-Join).
            NIE der Kandidat. Leerer String bei ``no-match``/``no-textlayer``.
        pdf_page: 1-indexierte Seitenzahl des Treffers, ``None`` ohne Treffer.
        char_start: Zeichenoffset des Treffers. Semantik haengt vom Status ab:
            - Bei ``status=exact``: Offset im SCHWACH normalisierten Seitentext
              (siehe :func:`_normalize_weak`).
            - Bei ``status=snapped``: Offset im VOLL normalisierten Seitentext
              (siehe :func:`normalize_text`).
            - ``None`` bei ``no-match``/``no-textlayer``.
        ratio: rapidfuzz-Aehnlichkeit 0.0-1.0 (``1.0`` bei ``exact``; bei
            ``no-match`` der beste ueber alle Seiten gefundene, unter
            :data:`SNAP_RATIO_THRESHOLD` liegende Wert -- diagnostisch,
            ``0.0`` bei ``no-textlayer``).
    """

    status: VerbatimStatus
    verbatim: str
    pdf_page: int | None
    char_start: int | None
    ratio: float


def _has_text_layer(pages: list[tuple[int, str]]) -> bool:
    return any(text.strip() for _, text in pages)


def _find_exact(
    normalized_candidate: str, normalized_pages: list[tuple[int, str]]
) -> VerbatimResult | None:
    for page_number, page_text in normalized_pages:
        idx = page_text.find(normalized_candidate)
        if idx != -1:
            return VerbatimResult(
                status="exact",
                verbatim=normalized_candidate,
                pdf_page=page_number,
                char_start=idx,
                ratio=1.0,
            )
    return None


def _best_fuzzy_window(candidate: str, page_text: str) -> tuple[int, float]:
    """Bester Fenster-Treffer fuer ``candidate`` in ``page_text``.

    Sliding-Window fester Laenge ``len(candidate)`` -- korrekt und einfach
    fuer Abweichungen gleicher Laenge (Zeichen-Substitutionen); bei
    Wort-Einfuegungen/-Loeschungen im Kandidaten ist der Alignment nur
    naeherungsweise. Fuer Papierseiten (wenige Tausend Zeichen) ist die
    O(Seitenlaenge)-Fenstersuche performant genug (siehe Planungs-Notiz zu
    Issue #511) -- keine Optimierung in diesem Issue noetig.

    Returns:
        ``(start_index, ratio)`` des besten Fensters. ``ratio`` ist 0.0, wenn
        ``page_text`` leer ist.
    """
    # Lazy import (#846-Folgefix): normalize_text/normalize_weak in diesem
    # Modul sind reine String-Funktionen ohne rapidfuzz-Bedarf --
    # quote_match.py importiert NUR die beiden fuer den billigen
    # Substring-/Ellipsis-Pfad (kein rapidfuzz noetig). Ein Modulkopf-Import
    # haette rapidfuzz zur harten Voraussetzung des GESAMTEN Moduls gemacht,
    # inkl. fuer Aufrufer, die nie fuzzy matchen.
    from rapidfuzz import fuzz

    window_len = len(candidate)
    if window_len == 0 or not page_text:
        return 0, 0.0
    if window_len >= len(page_text):
        return 0, fuzz.ratio(candidate, page_text) / 100.0

    best_start = 0
    best_ratio = -1.0
    last_start = len(page_text) - window_len
    for start in range(last_start + 1):
        window = page_text[start : start + window_len]
        score = fuzz.ratio(candidate, window) / 100.0
        if score > best_ratio:
            best_ratio = score
            best_start = start
    return best_start, best_ratio


def verify_verbatim_with_pages(pages: list[tuple[int, str]], candidate: str) -> VerbatimResult:
    """Prueft ``candidate`` gegen vorab extrahierte Seitentexte.

    Siehe Modul-Docstring fuer den vollstaendigen Ablauf. Diese Variante
    erlaubt es, die PDF-Extraktion einmal pro PDF durchzufuehren und dann
    mehrere Kandidaten zu verifiziieren, ohne die Seiten erneut zu parsen.

    Args:
        pages: Liste aus ``(page_number: int, text: str)`` Tuples, z. B. von
            :func:`academic_vault.chunking.extract_pages`.
        candidate: Der zu verifizierende Zitat-Kandidat.

    Returns:
        :class:`VerbatimResult`.
    """
    if not _has_text_layer(pages):
        return VerbatimResult(
            status="no-textlayer", verbatim="", pdf_page=None, char_start=None, ratio=0.0
        )

    weak_candidate = _normalize_weak(candidate)
    if not weak_candidate:
        return VerbatimResult(
            status="no-match", verbatim="", pdf_page=None, char_start=None, ratio=0.0
        )

    weak_pages = [(page_number, _normalize_weak(text)) for page_number, text in pages]

    exact = _find_exact(weak_candidate, weak_pages)
    if exact is not None:
        return exact

    # Kein exakter Treffer unter schwacher Normalisierung -> jetzt voll
    # normalisieren (NFKC/Ligaturen, Trennstrich-Join) und fuzzy vergleichen.
    normalized_candidate = normalize_text(candidate)
    normalized_pages = [(page_number, normalize_text(text)) for page_number, text in pages]

    best_ratio = 0.0
    best_start = 0
    best_page = normalized_pages[0][0] if normalized_pages else None
    for page_number, page_text in normalized_pages:
        start, ratio = _best_fuzzy_window(normalized_candidate, page_text)
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = start
            best_page = page_number

    if best_ratio >= SNAP_RATIO_THRESHOLD and best_page is not None:
        page_text = dict(normalized_pages)[best_page]
        window_len = len(normalized_candidate)
        verbatim = page_text[best_start : best_start + window_len]
        return VerbatimResult(
            status="snapped",
            verbatim=verbatim,
            pdf_page=best_page,
            char_start=best_start,
            ratio=best_ratio,
        )

    return VerbatimResult(
        status="no-match", verbatim="", pdf_page=None, char_start=None, ratio=best_ratio
    )


def verify_verbatim(pdf_path: str, candidate: str) -> VerbatimResult:
    """Prueft ``candidate`` deterministisch gegen den Volltext von ``pdf_path``.

    Siehe Modul-Docstring fuer den vollstaendigen Ablauf. Wirft KEINE
    Exception fuer "Kandidat nicht gefunden" -- das ist der Normalfall
    ``no-match``/``no-textlayer``, kein Fehlerzustand.

    Args:
        pdf_path: Pfad zur PDF-Datei (an :func:`academic_vault.chunking.extract_pages`
            weitergereicht).
        candidate: Der zu verifizierende Zitat-Kandidat.

    Returns:
        :class:`VerbatimResult`.
    """
    pages = extract_pages(pdf_path)
    return verify_verbatim_with_pages(pages, candidate)
