"""TDD-Tests fuer scripts/page_offset.py.

5 Testfaelle mit synthetischen PDFs (tests/fixtures/page_offset/).
Konvention: Seitenzahl steht als isolierte Zahl als erste Zeile des
extrahierten Textes (reportlab: y=40 = unten, aber pypdf liest
aufsteigend nach y, also erscheint y=40 zuerst).
"""

from pathlib import Path

import pytest

# scripts/ zum Python-Pfad hinzufuegen

FIXTURES = Path(__file__).parent / "fixtures" / "page_offset"


def _require_fixture(name: str) -> Path:
    p = FIXTURES / name
    if not p.exists():
        pytest.skip(
            f"Fixture fehlt: {p}. Aufruf: python tests/fixtures/page_offset/create_fixtures.py"
        )
    return p


# ---------------------------------------------------------------------------
# detect_page_offset Tests
# ---------------------------------------------------------------------------


def test_no_preface_offset_zero():
    """Buch ohne Vorwort: offset soll 0 sein (erste PDF-Seite traegt '1')."""
    from page_offset import detect_page_offset

    pdf = _require_fixture("no_preface.pdf")
    offset = detect_page_offset(str(pdf))
    assert offset == 0, f"Erwartet offset=0, erhalten {offset}"


def test_ten_prefaces_offset_ten():
    """10 Vorseiten: erste arabische '1' auf PDF-Seite 11 (1-basiert) -> offset=10."""
    from page_offset import detect_page_offset

    pdf = _require_fixture("ten_prefaces.pdf")
    offset = detect_page_offset(str(pdf))
    assert offset == 10, f"Erwartet offset=10, erhalten {offset}"


def test_roman_numerals_offset_six():
    """6 roemische Seiten, dann arabisch ab 1 auf PDF-Seite 7 -> offset=6."""
    from page_offset import detect_page_offset

    pdf = _require_fixture("roman_numerals.pdf")
    offset = detect_page_offset(str(pdf))
    assert offset == 6, f"Erwartet offset=6, erhalten {offset}"


def test_double_pagination_offset_five():
    """5 unnummerierte Seiten, arabisch ab 1 auf PDF-Seite 6 -> offset=5."""
    from page_offset import detect_page_offset

    pdf = _require_fixture("double_pagination.pdf")
    offset = detect_page_offset(str(pdf))
    assert offset == 5, f"Erwartet offset=5, erhalten {offset}"


def test_large_offset_twenty_five():
    """25 Vorseiten, arabisch ab 1 auf PDF-Seite 26 -> offset=25."""
    from page_offset import detect_page_offset

    pdf = _require_fixture("large_offset.pdf")
    offset = detect_page_offset(str(pdf))
    assert offset == 25, f"Erwartet offset=25, erhalten {offset}"


# ---------------------------------------------------------------------------
# /PageLabels-Baum Tests (#384)
# ---------------------------------------------------------------------------


def test_page_labels_arabic_start_offset():
    """PDF mit /PageLabels-Baum (3 Roemisch-Vorseiten + Decimal ab Index 3,
    Start 1) und OHNE extrahierbaren Seiten-Text: offset=3 muss direkt aus
    dem Label-Baum kommen, ein Test-Erfolg ueber die Text-Heuristik ist
    ausgeschlossen, da die Seiten keinen Text enthalten (AC1)."""
    from page_offset import detect_page_offset

    pdf = _require_fixture("page_labels.pdf")
    offset = detect_page_offset(str(pdf))
    assert offset == 3, f"Erwartet offset=3 aus /PageLabels-Baum, erhalten {offset}"


def test_detect_offset_from_page_labels_direct():
    """_detect_offset_from_page_labels() liefert den Offset direkt (ohne
    Umweg ueber detect_page_offset) fuer ein PDF mit Label-Baum."""
    from page_offset import _detect_offset_from_page_labels

    pdf = _require_fixture("page_labels.pdf")
    result = _detect_offset_from_page_labels(str(pdf))
    assert result == 3, f"Erwartet 3, erhalten {result}"


def test_no_page_labels_falls_back_without_error():
    """PDF ohne /PageLabels-Baum: _detect_offset_from_page_labels() liefert
    None (kein Fehler), detect_page_offset() faellt auf die bestehende
    Text-Heuristik zurueck (AC2)."""
    from page_offset import _detect_offset_from_page_labels, detect_page_offset

    pdf = _require_fixture("no_preface.pdf")
    assert _detect_offset_from_page_labels(str(pdf)) is None
    offset = detect_page_offset(str(pdf))
    assert offset == 0, f"Erwartet offset=0 (Fallback-Heuristik), erhalten {offset}"


def test_page_labels_to_vault_get_printed_page():
    """Label-Fixture end-to-end: detect_page_offset() -> add_paper() ->
    server.set_page_offset() -> server.get_printed_page() liefert die
    korrekte gedruckte Seite (AC3)."""
    import json
    import tempfile

    from academic_vault.server import add_paper, get_printed_page
    from academic_vault.server import set_page_offset as srv_set_offset

    from page_offset import detect_page_offset

    pdf = _require_fixture("page_labels.pdf")
    offset = detect_page_offset(str(pdf))
    assert offset == 3

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    csl = json.dumps({"type": "book", "title": "PageLabels Test"})
    add_paper(db_path, "page_labels_test_2024", csl)
    srv_set_offset(db_path, "page_labels_test_2024", offset)

    # pdf_page=6 (1-basiert) -> printed_page = 6 - 3 = 3
    result = get_printed_page(db_path, "page_labels_test_2024", pdf_page=6)
    assert result == 3, f"Erwartet 3, erhalten {result}"


# ---------------------------------------------------------------------------
# validate_offset Tests
# ---------------------------------------------------------------------------


def test_validate_offset_stable():
    """validate_offset gibt True zurueck wenn Stichproben konsistent sind."""
    from page_offset import validate_offset

    pdf = _require_fixture("ten_prefaces.pdf")
    # offset=10: PDF-Seite 11 (0-basiert: 10) soll '1' zeigen
    # Stichproben bei PDF-Seiten 11 und 12 (0-basiert: gedruckt 2 und 3)
    result = validate_offset(str(pdf), offset=10, check_pages=[11, 12])
    assert result is True, "validate_offset soll True fuer stabilen Offset zurueckgeben"


def test_validate_offset_wrong_rejects():
    """validate_offset gibt False zurueck wenn Offset falsch ist."""
    from page_offset import validate_offset

    pdf = _require_fixture("ten_prefaces.pdf")
    result = validate_offset(str(pdf), offset=0, check_pages=[11, 12])
    assert result is False, "validate_offset soll False fuer falschen Offset zurueckgeben"


# ---------------------------------------------------------------------------
# Vault-DB Tests
# ---------------------------------------------------------------------------


def test_vault_db_set_get_page_offset():
    """set_page_offset und get_page_offset runden-trip im Vault."""
    import json
    import tempfile

    from academic_vault.db import VaultDB

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    db = VaultDB(db_path)
    db.init_schema()
    csl = json.dumps({"type": "book", "title": "Test"})
    db.add_paper("buch_test_2024", csl)

    db.set_page_offset("buch_test_2024", 12)
    result = db.get_page_offset("buch_test_2024")
    assert result == 12, f"Erwartet 12, erhalten {result}"


def test_vault_db_get_page_offset_missing_returns_zero():
    """get_page_offset gibt 0 zurueck fuer unbekanntes paper_id."""
    import tempfile

    from academic_vault.db import VaultDB

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    db = VaultDB(db_path)
    db.init_schema()
    result = db.get_page_offset("nonexistent_paper")
    assert result == 0, f"Erwartet 0, erhalten {result}"


# ---------------------------------------------------------------------------
# Server-Funktionen Tests
# ---------------------------------------------------------------------------


def test_server_set_and_get_printed_page():
    """set_page_offset + get_printed_page runden-trip via server.py."""
    import json
    import tempfile

    from academic_vault.server import (
        add_paper,
        get_printed_page,
    )
    from academic_vault.server import (
        set_page_offset as srv_set_offset,
    )

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    csl = json.dumps({"type": "book", "title": "Server Test"})
    add_paper(db_path, "server_test_2024", csl)
    srv_set_offset(db_path, "server_test_2024", 10)

    # pdf_page=15 (1-basiert) -> printed_page = 15 - 10 = 5
    result = get_printed_page(db_path, "server_test_2024", pdf_page=15)
    assert result == 5, f"Erwartet 5, erhalten {result}"


def test_server_get_printed_page_zero_offset():
    """get_printed_page mit offset=0 gibt pdf_page unveraendert zurueck."""
    import json
    import tempfile

    from academic_vault.server import add_paper, get_printed_page

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    csl = json.dumps({"type": "book", "title": "Zero Offset Test"})
    add_paper(db_path, "zero_offset_2024", csl)
    # Kein set_page_offset -> offset=0

    result = get_printed_page(db_path, "zero_offset_2024", pdf_page=42)
    assert result == 42, f"Erwartet 42 (kein Offset), erhalten {result}"
