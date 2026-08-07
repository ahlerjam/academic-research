"""Tests fuer Issue #741 -- Kennzahlen aus Tabellen belegen statt abtippen.

Deckt die sechs Akzeptanzkriterien ab:

  AC1  Ein Zahlenwert laesst sich mit Paper, Seite und Tabellenposition
       erfassen und wird dabei gegen die Zelle im PDF geprueft.
  AC2  Steht der Wert dort nicht, wird nichts gespeichert und die Meldung
       nennt den gefundenen gegen den behaupteten Wert.
  AC3  Uebliche Schreibweisenunterschiede blockieren nicht (Dezimalkomma vs.
       -punkt, Tausendertrennzeichen, fuehrende Nullen, Prozentzeichen).
  AC4  Erfasste Kennzahlen erscheinen in der Pruefbilanz aus #737 als eigene
       Kategorie.
  AC5  Fehlt das Tabellen-Backend, wird das als solches gemeldet statt eine
       Ausnahme zu werfen.
  AC6  Die Doku sagt ausdruecklich, dass Zahlen im Fliesstext ohne diesen Weg
       ungeprueft bleiben.
"""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from academic_vault import migrate
from academic_vault import tables as tables_mod
from academic_vault.db import VaultDB, VaultLockedError
from academic_vault.numbers import normalize_number, numbers_equivalent
from academic_vault.server import (
    add_paper as server_add_paper,
)
from academic_vault.server import (
    add_table_value,
    chapter_quote_balance,
    extract_tables_for_paper,
    list_table_values,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tables"
RESULTS_PDF = FIXTURE_DIR / "results_table.pdf"
VAULT_DOC = REPO_ROOT / "docs" / "reference" / "vault.md"

requires_backend = pytest.mark.skipif(
    importlib.util.find_spec("pdfplumber") is None,
    reason="pdfplumber fehlt trotz Pflicht-Dependency (#723) im Environment",
)

CSL = json.dumps(
    {
        "type": "article-journal",
        "title": "Eine Studie mit Ergebnistabelle",
        "abstract": "Der Abstract nennt keine Zahlen aus der Tabelle.",
    }
)


def _make_paper(tmp_path: Path, paper_id: str = "smith2020") -> str:
    db_path = str(tmp_path / "vault.db")
    server_add_paper(db_path, paper_id, CSL, pdf_path=str(RESULTS_PDF))
    return db_path


# ---------------------------------------------------------------------------
# AC1 -- Erfassen mit Pruefung gegen die Zelle
# ---------------------------------------------------------------------------


@requires_backend
def test_add_table_value_matching_cell_stores_record(tmp_path):
    db_path = _make_paper(tmp_path)
    extract_tables_for_paper(db_path, "smith2020")

    table_value_id = add_table_value(
        db_path,
        paper_id="smith2020",
        page=1,
        table_index=0,
        row=1,
        col=1,
        claimed_value="120",
    )

    assert table_value_id
    stored = list_table_values(db_path, paper_id="smith2020")
    assert len(stored) == 1
    record = stored[0]
    assert record["claimed_value"] == "120"
    assert record["cell_value"] == "120"
    assert record["paper_id"] == "smith2020"
    assert record["page"] == 1
    assert record["table_index"] == 0
    assert record["row"] == 1
    assert record["col"] == 1
    assert record["evidence"] == "smith2020, S. 1, Tabelle 1, Zeile 2, Spalte 2"


@requires_backend
def test_add_table_value_extracts_automatically_when_not_yet_extracted(tmp_path):
    """Vor jeder Erfassung muss `vault.extract_tables` NICHT manuell gelaufen sein."""
    db_path = _make_paper(tmp_path)

    table_value_id = add_table_value(
        db_path,
        paper_id="smith2020",
        page=1,
        table_index=0,
        row=1,
        col=1,
        claimed_value="120",
    )

    assert table_value_id
    assert len(list_table_values(db_path)) == 1


@requires_backend
def test_add_table_value_refuses_on_locked_vault(tmp_path):
    db_path = _make_paper(tmp_path)
    extract_tables_for_paper(db_path, "smith2020")
    VaultDB(db_path).lock_vault(slug="testprojekt")

    with pytest.raises(VaultLockedError):
        add_table_value(
            db_path,
            paper_id="smith2020",
            page=1,
            table_index=0,
            row=1,
            col=1,
            claimed_value="120",
        )


def test_add_table_value_rejects_unknown_paper(tmp_path):
    db_path = str(tmp_path / "vault.db")
    VaultDB(db_path).init_schema()

    with pytest.raises(ValueError, match="Paper unbekannt"):
        add_table_value(
            db_path,
            paper_id="does-not-exist",
            page=1,
            table_index=0,
            row=0,
            col=0,
            claimed_value="1",
        )


# ---------------------------------------------------------------------------
# AC2 -- Ablehnung mit Ist/Soll-Meldung, nichts gespeichert
# ---------------------------------------------------------------------------


@requires_backend
def test_add_table_value_mismatch_raises_with_found_and_claimed(tmp_path):
    db_path = _make_paper(tmp_path)
    extract_tables_for_paper(db_path, "smith2020")

    with pytest.raises(ValueError) as excinfo:
        add_table_value(
            db_path,
            paper_id="smith2020",
            page=1,
            table_index=0,
            row=1,
            col=1,
            claimed_value="99",
        )

    message = str(excinfo.value)
    assert "120" in message
    assert "99" in message
    assert list_table_values(db_path) == []


@requires_backend
def test_add_table_value_unknown_cell_raises_without_storing(tmp_path):
    db_path = _make_paper(tmp_path)
    extract_tables_for_paper(db_path, "smith2020")

    with pytest.raises(ValueError):
        add_table_value(
            db_path,
            paper_id="smith2020",
            page=1,
            table_index=0,
            row=99,
            col=0,
            claimed_value="1",
        )
    assert list_table_values(db_path) == []


# ---------------------------------------------------------------------------
# AC3 -- Schreibweisenunterschiede blockieren nicht
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claimed,actual",
    [
        ("45,8", "45.8"),  # Dezimalkomma vs. -punkt
        ("1.234,56", "1234.56"),  # deutsches Tausendertrennzeichen + Dezimalkomma
        ("1,234.56", "1234.56"),  # englisches Tausendertrennzeichen + Dezimalpunkt
        ("046", "46"),  # fuehrende Null
        ("46 %", "46"),  # Prozentzeichen mit Leerzeichen
        ("46%", "46"),  # Prozentzeichen ohne Leerzeichen
    ],
)
def test_normalize_number_accepts_locale_variants(claimed, actual):
    assert numbers_equivalent(claimed, actual)
    assert normalize_number(claimed) == normalize_number(actual)


def test_normalize_number_rejects_real_value_differences():
    """Eine Rundungsdifferenz ist eine echte Abweichung, keine Schreibweise (#741 Risiko)."""
    assert not numbers_equivalent("46", "45.8")
    assert not numbers_equivalent("99", "120")


def test_normalize_number_none_and_empty_and_garbage():
    assert normalize_number(None) is None
    assert normalize_number("") is None
    assert normalize_number("   ") is None
    assert normalize_number("keine Zahl") is None


@requires_backend
@pytest.mark.parametrize(
    "claimed",
    ["120", "120,0", "120.0", "0120"],
)
def test_add_table_value_accepts_writing_variants_of_the_real_cell(tmp_path, claimed):
    db_path = _make_paper(tmp_path)
    extract_tables_for_paper(db_path, "smith2020")

    table_value_id = add_table_value(
        db_path,
        paper_id="smith2020",
        page=1,
        table_index=0,
        row=1,
        col=1,
        claimed_value=claimed,
    )
    assert table_value_id


# ---------------------------------------------------------------------------
# AC4 -- eigene Kategorie in der Pruefbilanz aus #737
# ---------------------------------------------------------------------------


@requires_backend
def test_chapter_quote_balance_lists_captured_table_values(tmp_path):
    from academic_vault.server import add_quote

    db_path = _make_paper(tmp_path)
    extract_tables_for_paper(db_path, "smith2020")
    add_quote(
        db_path=db_path,
        paper_id="smith2020",
        verbatim="Ein ausreichend langes Zitat fuer den Kapitel-Scan von #737.",
        extraction_method="manual",
    )
    add_table_value(
        db_path,
        paper_id="smith2020",
        page=1,
        table_index=0,
        row=1,
        col=1,
        claimed_value="120",
    )

    chapter_file = tmp_path / "kapitel.md"
    chapter_file.write_text(
        'Beleg: "Ein ausreichend langes Zitat fuer den Kapitel-Scan von #737." -- so die Quelle.',
        encoding="utf-8",
    )

    balance = chapter_quote_balance(db_path=db_path, chapter_path=str(chapter_file))

    assert balance["erfasste_kennzahlen"] == 1
    assert len(balance["table_values"]) == 1
    assert balance["table_values"][0]["paper_id"] == "smith2020"
    assert balance["table_values"][0]["evidence"]
    # Summeninvariante aus #737 (AC1) bleibt unberuehrt.
    assert balance["total_quotes"] == 1


def test_chapter_quote_balance_without_captured_values_returns_zero(tmp_path):
    db_path = str(tmp_path / "vault.db")
    VaultDB(db_path).init_schema()
    chapter_file = tmp_path / "leer.md"
    chapter_file.write_text("Kein Zitat hier.", encoding="utf-8")

    balance = chapter_quote_balance(db_path=db_path, chapter_path=str(chapter_file))

    assert balance["erfasste_kennzahlen"] == 0
    assert balance["table_values"] == []


# ---------------------------------------------------------------------------
# AC5 -- fehlendes Backend wird gemeldet, keine Exception
# ---------------------------------------------------------------------------


def _raise_import_error():
    raise ImportError("pdfplumber ist in diesem Lauf absichtlich nicht importierbar")


def test_add_table_value_backend_missing_reports_status(tmp_path, monkeypatch):
    monkeypatch.setattr(tables_mod, "_import_pdfplumber", _raise_import_error)
    db_path = _make_paper(tmp_path)

    with pytest.raises(ValueError) as excinfo:
        add_table_value(
            db_path,
            paper_id="smith2020",
            page=1,
            table_index=0,
            row=1,
            col=1,
            claimed_value="120",
        )

    message = str(excinfo.value)
    assert "backend-missing" in message
    assert "pdfplumber" in message
    assert list_table_values(db_path) == []


# ---------------------------------------------------------------------------
# AC6 -- Doku benennt den ungeprueften Fliesstext-Weg
# ---------------------------------------------------------------------------


def test_docs_state_freitext_numbers_stay_unchecked():
    doc = VAULT_DOC.read_text(encoding="utf-8")
    assert "vault.add_table_value" in doc
    lowered = doc.lower()
    assert "fließtext" in lowered or "fliesstext" in lowered
    assert "ungeprüft" in lowered or "ungepr" in lowered


def test_mcp_tool_is_registered():
    content = (REPO_ROOT / "academic_vault" / "server.py").read_text(encoding="utf-8")
    assert '@mcp.tool(name="vault.add_table_value")' in content


# ---------------------------------------------------------------------------
# Bestands-DBs: Migration ist idempotent und liest ohne Absturz
# ---------------------------------------------------------------------------


def test_legacy_db_gets_table_values_via_migration(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    VaultDB(db_path).init_schema()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS table_values")
        conn.commit()
    finally:
        conn.close()

    migrate.add_table_values_table(db_path)
    migrate.add_table_values_table(db_path)  # idempotent

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='table_values'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_listing_table_values_on_a_legacy_db_returns_empty_instead_of_raising(tmp_path):
    db_path = _make_paper(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS table_values")
        conn.commit()
    finally:
        conn.close()

    assert list_table_values(db_path) == []
