"""Tests fuer das lokale Verbatim-Verifikationsmodul (Issue #511).

Fixtures: tests/fixtures/verbatim/ (siehe create_fixtures.py fuer die exakte
Kontrolle des von pypdf extrahierten Unicode-Texts ueber eine /ToUnicode-CMap).

AC -> Testfall (siehe Issue #511):
  - Exakter Treffer nach Normalisierung -> status=exact, korrekte Seite,
    char_start: test_exact_match_after_normalization (Anfuehrungszeichen-
    Variante), plus Regressionsfaelle fuer die einzelnen Normalisierungsschritte
    (Ligatur, Zeilenend-Trennstrich).
  - Leicht abweichender Kandidat -> status=snapped, Wortlaut AUS DER QUELLE:
    test_snapped_returns_source_wording_not_candidate.
  - Kandidat ohne Entsprechung -> no-match; PDF ohne Textlayer -> no-textlayer,
    nie durchgewunken: test_unrelated_candidate_returns_no_match,
    test_scan_pdf_without_text_layer_returns_no_textlayer.

DESIGN-ENTSCHEIDUNG (Abweichung von der Wortwahl des Issue-Body-ACs): die
"Ligatur"/"Trennstrich"-Beispiele im AC-Text sind illustrativ gemeint. Die
"What"-Sektion des Issues listet Ligatur-Aufloesung UND Trennstrich-Join
explizit als Teil der DETERMINISTISCHEN Normalisierung -- ein Kandidat, der
sich nur darin vom Quelltext unterscheidet, landet also konsequent bei
`exact`, nicht bei `snapped` (sonst waere die deterministische Normalisierung
wirkungslos). `snapped` ist reserviert fuer Abweichungen, die NICHT durch die
Normalisierung aufgeloest werden (z. B. echte Tippfehler).
"""

import os

from academic_vault.verbatim import (
    SNAP_RATIO_THRESHOLD,
    normalize_text,
    verify_verbatim,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "verbatim")
SOURCE_PDF = os.path.join(FIXTURES, "verbatim_source.pdf")
SCAN_PDF = os.path.join(FIXTURES, "scan_no_text.pdf")


def _assert_char_start_consistent(pdf_path: str, page: int, result) -> None:
    """Bestaetigt, dass ``char_start`` wirklich auf ``verbatim`` zeigt.

    Rekonstruiert den normalisierten Seitentext unabhaengig ueber
    :func:`normalize_text` und prueft den Slice an ``char_start`` -- robuster
    als ein hartkodierter Index, der bei jeder Fixture-Aenderung bricht.
    """
    from academic_vault.chunking import extract_pages

    pages = dict(extract_pages(pdf_path))
    normalized_page = normalize_text(pages[page])
    end = result.char_start + len(result.verbatim)
    assert normalized_page[result.char_start : end] == result.verbatim


def test_exact_match_after_normalization():
    """Krumme Anfuehrungszeichen im Kandidaten vs. Quelltext -> exact."""
    candidate = 'Die Teilnehmenden beschrieben "implizites Wissen" als zentralen Faktor.'
    result = verify_verbatim(SOURCE_PDF, candidate)

    assert result.status == "exact"
    assert result.pdf_page == 2
    assert result.ratio == 1.0
    assert result.verbatim == normalize_text(candidate)
    _assert_char_start_consistent(SOURCE_PDF, 2, result)


def test_ligature_normalization_returns_exact():
    """Kandidat mit 'fi' statt Ligatur ﬁ -> nach Normalisierung exact."""
    candidate = "Die Wirksamkeit der Konfiguration wurde nachgewiesen."
    result = verify_verbatim(SOURCE_PDF, candidate)

    assert result.status == "exact"
    assert result.pdf_page == 1
    assert result.ratio == 1.0
    assert "fi" in result.verbatim
    assert "ﬁ" not in result.verbatim
    _assert_char_start_consistent(SOURCE_PDF, 1, result)


def test_hyphenated_linebreak_normalization_returns_exact():
    """Kandidat ohne Trennstrich-Zeilenumbruch -> nach Join exact."""
    candidate = (
        "Diese Studie belegt eine gesteigerte innovationsfaehigkeit "
        "in den befragten Organisationen."
    )
    result = verify_verbatim(SOURCE_PDF, candidate)

    assert result.status == "exact"
    assert result.pdf_page == 1
    assert result.ratio == 1.0
    assert "innovationsfaehigkeit" in result.verbatim
    _assert_char_start_consistent(SOURCE_PDF, 1, result)


def test_snapped_returns_source_wording_not_candidate():
    """Echter Tippfehler (nicht normalisierbar) -> snapped mit Quellwortlaut."""
    candidate = "Der Interviewpartner betonto die Bedeutung von Vertrauen im Team."
    result = verify_verbatim(SOURCE_PDF, candidate)

    assert result.status == "snapped"
    assert result.pdf_page == 1
    assert result.ratio < 1.0
    assert result.ratio >= SNAP_RATIO_THRESHOLD
    # Der Wortlaut kommt aus der Quelle, nicht vom Kandidaten.
    assert result.verbatim != normalize_text(candidate)
    assert "betonte" in result.verbatim
    assert "betonto" not in result.verbatim
    _assert_char_start_consistent(SOURCE_PDF, 1, result)


def test_unrelated_candidate_returns_no_match():
    """Kandidat aus komplett anderem Kontext -> no-match, nie durchgewunken."""
    candidate = "Die Wallfahrt nach Santiago de Compostela ist unabhaengig vom Studienthema."
    result = verify_verbatim(SOURCE_PDF, candidate)

    assert result.status == "no-match"
    assert result.status not in ("exact", "snapped")
    assert result.pdf_page is None
    assert result.char_start is None
    assert result.verbatim == ""
    assert result.ratio < SNAP_RATIO_THRESHOLD


def test_scan_pdf_without_text_layer_returns_no_textlayer():
    """PDF ohne Text-Layer -> no-textlayer, unabhaengig vom Kandidaten."""
    candidate = "Ein beliebiger Kandidat."
    result = verify_verbatim(SCAN_PDF, candidate)

    assert result.status == "no-textlayer"
    assert result.status not in ("exact", "snapped")
    assert result.pdf_page is None
    assert result.char_start is None
    assert result.verbatim == ""


def test_empty_candidate_returns_no_match():
    """Leerer Kandidat wird nie faelschlich als Treffer durchgewunken."""
    result = verify_verbatim(SOURCE_PDF, "   ")

    assert result.status == "no-match"
