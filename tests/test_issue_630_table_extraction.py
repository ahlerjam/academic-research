"""Tests fuer Issue #630 — Tabellen strukturerhaltend extrahieren.

Der einzige Volltextpfad des Vaults (``academic_vault/fulltext.py``) kollabiert
jede Whitespace-Folge zu einem Leerzeichen. Fuer den FTS5-Index ist das richtig,
fuer eine Ergebnistabelle vernichtet es die Struktur — und damit die Grundlage
von ``skills/extraction-matrix`` und ``agents/meta-analysis``.

Diese Suite deckt die sechs Akzeptanzkriterien ab:

  AC1  Zellen einer mehrspaltigen Ergebnistabelle mit erhaltener
       Zeilen-/Spaltenzuordnung.
  AC2  Zu einer Zahl sind Paper, Seite und Zelle feststellbar.
  AC3  Zweispaltiges Layout und verbundene Kopfzellen sind als Fixture
       abgedeckt; das Ergebnis ist festgeschrieben, auch wo es misslingt.
  AC4  ``extraction-matrix`` fuellt eine Zahlen-Spalte aus dieser Quelle.
  AC5  Ohne Backend laeuft der Volltextpfad weiter, der Grund ist sichtbar.
  AC6  Der FTS5-Volltext ist byteweise unveraendert.

Die Fixture-PDFs entstehen aus ``tests/fixtures/tables/create_fixtures.py``
(reine Standardbibliothek, kein reportlab). Sie zeichnen ihr Tabellengitter als
echte Stroke-Pfade, weil pdfplumber per Default ueber Linien erkennt.
"""

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from academic_vault import fulltext as fulltext_mod
from academic_vault import migrate
from academic_vault import tables as tables_mod
from academic_vault.db import VaultDB, VaultLockedError
from academic_vault.server import (
    add_paper as server_add_paper,
)
from academic_vault.server import (
    extract_fulltext_for_paper,
    extract_tables_for_paper,
    get_table_cell,
    list_paper_tables,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tables"
RESULTS_PDF = FIXTURE_DIR / "results_table.pdf"
TWO_COLUMN_PDF = FIXTURE_DIR / "two_column_layout.pdf"
MERGED_HEADER_PDF = FIXTURE_DIR / "merged_header.pdf"
NO_TABLE_PDF = FIXTURE_DIR / "no_table.pdf"
SCAN_PDF = FIXTURE_DIR / "scan_no_textlayer.pdf"

VAULT_DOC = REPO_ROOT / "docs" / "reference" / "vault.md"
MATRIX_SKILL = REPO_ROOT / "skills" / "extraction-matrix" / "SKILL.md"
META_AGENT = REPO_ROOT / "agents" / "meta-analysis.md"

#: pdfplumber ist seit Issue #723 Pflicht-Dependency, kein optionales Extra
#: mehr (vorher: `uv sync --extra tables`). Dieser Skip bleibt trotzdem als
#: Sicherheitsnetz bestehen -- er greift nach dem Fix praktisch nie mehr,
#: schuetzt aber weiterhin gegen eine reale Installation, in der das Paket
#: dennoch fehlt (Degradationspfad, siehe test_issue_723_...). Bewusst KEIN
#: modulweites ``importorskip``: die Zusicherung aus AC5 — ohne Backend laeuft
#: der Volltextpfad weiter und der Grund ist sichtbar — muss gerade auf einer
#: Maschine ohne das Paket geprueft werden. Uebersprungen wird nur, was echte
#: Extraktion braucht.
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


def _make_paper(tmp_path: Path, pdf: Path, paper_id: str = "smith2020") -> tuple[str, str]:
    """Legt eine frische Vault-DB mit einem Paper samt ``pdf_path`` an."""
    db_path = str(tmp_path / "vault.db")
    server_add_paper(db_path, paper_id, CSL, pdf_path=str(pdf))
    return db_path, paper_id


# ---------------------------------------------------------------------------
# AC1 — Zeilen-/Spaltenzuordnung bleibt erhalten
# ---------------------------------------------------------------------------


@requires_backend
def test_results_table_preserves_row_and_column_assignment():
    result = tables_mod.extract_tables(str(RESULTS_PDF))

    assert result["status"] == tables_mod.STATUS_OK
    assert result["backend"] == "pdfplumber"
    assert len(result["tables"]) == 1

    table = result["tables"][0]
    assert table["page"] == 1
    assert table["table_index"] == 0
    assert table["rows"] == [
        ["Studie", "N", "d", "95%-CI"],
        ["Smith 2020", "120", "0.42", "0.18 bis 0.66"],
        ["Jones 2021", "84", "0.31", "0.05 bis 0.57"],
        ["Lee 2019", "210", "0.55", "0.34 bis 0.76"],
    ]
    assert table["n_rows"] == 4
    assert table["n_cols"] == 4


@requires_backend
def test_every_cell_carries_its_own_bounding_box():
    table = tables_mod.extract_tables(str(RESULTS_PDF))["tables"][0]

    by_position = {(cell["row"], cell["col"]): cell for cell in table["cells"]}
    assert len(by_position) == 16

    n_cell = by_position[(1, 1)]
    assert n_cell["value"] == "120"
    assert len(n_cell["bbox"]) == 4
    # bbox = (x0, top, x1, bottom) in pdfplumber-Koordinaten (Ursprung oben links).
    assert n_cell["bbox"][0] < n_cell["bbox"][2]
    assert n_cell["bbox"][1] < n_cell["bbox"][3]


def test_cell_values_keep_their_own_normalisation_not_the_fulltext_one():
    """Zellwerte werden getrimmt und intern geglaettet, aber nie zusammengelegt."""
    assert tables_mod.normalize_cell_value("  0.42\n ") == "0.42"
    assert tables_mod.normalize_cell_value("Smith\n2020") == "Smith 2020"
    assert tables_mod.normalize_cell_value(None) is None
    assert tables_mod.normalize_cell_value("   ") == ""


# ---------------------------------------------------------------------------
# AC2 — Paper, Seite und Zelle sind feststellbar
# ---------------------------------------------------------------------------


@requires_backend
def test_cell_is_traceable_to_paper_page_and_cell(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    report = extract_tables_for_paper(db_path, paper_id)
    assert report["status"] == tables_mod.STATUS_OK
    assert report["tables"] == 1
    assert report["cells"] == 16

    cell = get_table_cell(db_path, paper_id, page=1, table_index=0, row=1, col=1)
    assert cell is not None
    assert cell["value"] == "120"
    assert cell["paper_id"] == paper_id
    assert cell["page"] == 1
    assert cell["table_index"] == 0
    assert cell["row"] == 1
    assert cell["col"] == 1
    assert cell["backend"] == "pdfplumber"
    assert len(cell["bbox"]) == 4


@requires_backend
def test_unknown_cell_returns_none_instead_of_a_guess(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    extract_tables_for_paper(db_path, paper_id)

    assert get_table_cell(db_path, paper_id, page=1, table_index=0, row=99, col=0) is None
    assert get_table_cell(db_path, paper_id, page=9, table_index=0, row=0, col=0) is None


@requires_backend
def test_cell_carries_a_ready_made_evidence_string(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    extract_tables_for_paper(db_path, paper_id)

    cell = get_table_cell(db_path, paper_id, page=1, table_index=0, row=1, col=1)
    assert cell is not None
    # 1-basiert fuer den Leser, 0-basiert im Datensatz.
    assert cell["evidence"] == "smith2020, S. 1, Tabelle 1, Zeile 2, Spalte 2"


@requires_backend
def test_list_paper_tables_returns_the_persisted_structure(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    extract_tables_for_paper(db_path, paper_id)

    listed = list_paper_tables(db_path, paper_id)
    assert len(listed) == 1
    assert listed[0]["rows"][1] == ["Smith 2020", "120", "0.42", "0.18 bis 0.66"]
    assert listed[0]["page"] == 1
    assert listed[0]["backend"] == "pdfplumber"


@requires_backend
def test_re_extraction_replaces_instead_of_duplicating(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    extract_tables_for_paper(db_path, paper_id)
    extract_tables_for_paper(db_path, paper_id)

    assert len(list_paper_tables(db_path, paper_id)) == 1


@requires_backend
def test_writing_tables_into_a_locked_vault_is_refused(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    VaultDB(db_path).lock_vault(slug="testprojekt")

    with pytest.raises(VaultLockedError):
        extract_tables_for_paper(db_path, paper_id)


# ---------------------------------------------------------------------------
# AC3 — Schwierige Layouts sind abgedeckt und festgeschrieben
# ---------------------------------------------------------------------------


@requires_backend
def test_two_column_layout_fixture_result_is_pinned():
    """Zweispaltiges Layout: die Tabelle in der linken Spalte wird gefunden.

    Festgeschriebener Ist-Zustand — der rechte Textblock darf nicht in die
    Tabelle geraten.
    """
    result = tables_mod.extract_tables(str(TWO_COLUMN_PDF))

    assert result["status"] == tables_mod.STATUS_OK
    assert len(result["tables"]) == 1
    assert result["tables"][0]["rows"] == [
        ["Studie", "N"],
        ["Smith 2020", "120"],
    ]


@requires_backend
def test_merged_header_fixture_result_is_pinned():
    """Verbundene Kopfzelle: pdfplumber liefert dort eine ``None``-Zelle.

    Das ist der dokumentierte Teilmisserfolg (AC3): die Kopfzeile hat nur zwei
    reale Zellen, die dritte Position bleibt ``None``. Der Test friert diesen
    Ist-Zustand ein, statt ihn schoenzufaerben — die Datenzeilen darunter
    bleiben davon unberuehrt und korrekt zugeordnet.
    """
    result = tables_mod.extract_tables(str(MERGED_HEADER_PDF))

    assert result["status"] == tables_mod.STATUS_OK
    table = result["tables"][0]
    assert table["rows"] == [
        ["Studie", "Effekt", None],
        ["", "d", "SE"],
        ["Smith 2020", "0.42", "0.12"],
        ["Jones 2021", "0.31", "0.13"],
    ]

    header_cells = [c for c in table["cells"] if c["row"] == 0]
    assert [c["col"] for c in header_cells] == [0, 1]
    merged = header_cells[1]
    assert merged["value"] == "Effekt"
    # Die verbundene Kopfzelle ist doppelt so breit wie eine Datenzelle darunter.
    data_cell = next(c for c in table["cells"] if c["row"] == 2 and c["col"] == 1)
    assert (merged["bbox"][2] - merged["bbox"][0]) > (data_cell["bbox"][2] - data_cell["bbox"][0])


def test_docs_document_known_table_limits():
    doc = VAULT_DOC.read_text(encoding="utf-8")
    assert "## Tabellenextraktion" in doc
    assert "Bekannte Grenzen" in doc
    assert "verbundene" in doc.lower()
    assert "zweispaltig" in doc.lower()
    # Der Backend-Vergleich ist belegt, nicht behauptet.
    for candidate in ("pdfplumber", "camelot", "Docling", "Marker"):
        assert candidate in doc, f"Backend-Vergleich nennt {candidate} nicht"


# ---------------------------------------------------------------------------
# „keine Tabelle erkannt" ist ein sichtbares Ergebnis
# ---------------------------------------------------------------------------


@requires_backend
def test_pdf_without_table_reports_no_tables_status():
    result = tables_mod.extract_tables(str(NO_TABLE_PDF))

    assert result["status"] == tables_mod.STATUS_NO_TABLES
    assert result["tables"] == []
    assert result["message"], "Ein leeres Ergebnis ohne Klartextmeldung ist unsichtbar"
    assert "keine Tabelle" in result["message"].lower() or "tabelle" in result["message"].lower()


@requires_backend
def test_scan_pdf_reports_no_textlayer():
    result = tables_mod.extract_tables(str(SCAN_PDF))

    assert result["status"] == tables_mod.STATUS_NO_TEXTLAYER
    assert result["tables"] == []
    assert "ocr" in result["message"].lower()


@requires_backend
def test_no_tables_status_survives_into_the_server_report(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, NO_TABLE_PDF)
    report = extract_tables_for_paper(db_path, paper_id)

    assert report["status"] == tables_mod.STATUS_NO_TABLES
    assert report["tables"] == 0
    assert report["message"]
    assert list_paper_tables(db_path, paper_id) == []


# ---------------------------------------------------------------------------
# AC5 — ohne Backend bleibt der Volltextpfad unberuehrt
# ---------------------------------------------------------------------------


def test_missing_backend_returns_visible_status(monkeypatch):
    monkeypatch.setattr(tables_mod, "_import_pdfplumber", _raise_import_error)

    result = tables_mod.extract_tables(str(RESULTS_PDF))

    assert result["status"] == tables_mod.STATUS_BACKEND_MISSING
    assert result["tables"] == []
    assert result["backend"] == ""
    assert "pip install" in result["message"]
    assert "pdfplumber" in result["message"]


def _raise_import_error():
    raise ImportError("pdfplumber ist in diesem Lauf absichtlich nicht importierbar")


def test_fulltext_path_unaffected_without_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(tables_mod, "_import_pdfplumber", _raise_import_error)
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)

    table_report = extract_tables_for_paper(db_path, paper_id)
    assert table_report["status"] == tables_mod.STATUS_BACKEND_MISSING

    fulltext_report = extract_fulltext_for_paper(db_path, paper_id)
    assert fulltext_report["indexed"] is True
    assert fulltext_report["chars"] > 0
    assert "Smith 2020" in (VaultDB(db_path).get_fulltext(paper_id) or "")


# ---------------------------------------------------------------------------
# AC6 — der FTS5-Volltext bleibt byteweise unveraendert
# ---------------------------------------------------------------------------


def _fulltext_digest(db_path: str, paper_id: str) -> tuple[str, str]:
    conn = sqlite3.connect(db_path)
    try:
        stored = conn.execute(
            "SELECT text FROM paper_fulltext WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        indexed = conn.execute(
            "SELECT fulltext FROM papers_fts WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()

    def digest(row) -> str:
        value = "" if row is None or row[0] is None else row[0]
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    return digest(stored), digest(indexed)


@requires_backend
def test_fts5_fulltext_is_byte_identical_after_table_extraction(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    extract_fulltext_for_paper(db_path, paper_id)

    before = _fulltext_digest(db_path, paper_id)
    extract_tables_for_paper(db_path, paper_id)
    after = _fulltext_digest(db_path, paper_id)

    assert before == after
    assert before[0] != hashlib.sha256(b"").hexdigest(), "Vorbedingung: Volltext ist nicht leer"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a  b", "a b"),
        ("a\nb", "a b"),
        ("  a\t\tb  ", "a b"),
        ("", ""),
        ("\n\n", ""),
    ],
)
def test_normalize_whitespace_behaviour_unchanged(raw, expected):
    """``fulltext.normalize_whitespace`` wird durch #630 nicht aufgeweicht."""
    assert fulltext_mod.normalize_whitespace(raw) == expected


def test_tables_module_does_not_use_normalize_whitespace():
    source = (REPO_ROOT / "academic_vault" / "tables.py").read_text(encoding="utf-8")
    assert "normalize_whitespace" not in source
    assert "from .fulltext" not in source
    assert "from academic_vault.fulltext" not in source


# ---------------------------------------------------------------------------
# AC4 — extraction-matrix fuellt eine Zahlen-Spalte aus dieser Quelle
# ---------------------------------------------------------------------------

MISSING_MARKER = "— fehlend —"


@requires_backend
def test_extraction_matrix_fills_number_column_from_table_source(tmp_path):
    """Durchgespieltes Beispiel: Spalte „Stichprobe" kommt aus der Tabellenzelle.

    Bildet den in ``skills/extraction-matrix/SKILL.md`` beschriebenen Ablauf
    nach: Tabellen extrahieren, Kopfzeile nach der gesuchten Spalte durchsuchen,
    Zeile der Studie finden, Zelle mit Beleg abrufen.
    """
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    extract_tables_for_paper(db_path, paper_id)

    cell_value = None
    evidence = None
    for table in list_paper_tables(db_path, paper_id):
        header = table["rows"][0]
        if "N" not in header:
            continue
        col = header.index("N")
        for row_index, row in enumerate(table["rows"][1:], start=1):
            if row[0] != "Smith 2020":
                continue
            found = get_table_cell(
                db_path,
                paper_id,
                page=table["page"],
                table_index=table["table_index"],
                row=row_index,
                col=col,
            )
            assert found is not None
            cell_value = found["value"]
            evidence = found["evidence"]

    assert cell_value == "120"
    matrix_cell = f"{cell_value} ({evidence})"
    assert matrix_cell != MISSING_MARKER
    assert matrix_cell == "120 (smith2020, S. 1, Tabelle 1, Zeile 2, Spalte 2)"


def test_size_baseline_stays_bound_to_the_actual_growth():
    """Die skill_sizes.json-Anhebung folgt dem Netto-Zuwachs, statt ihn freizugeben.

    Etabliertes Repo-Muster (vgl. #538/#540): ``test_token_reduction`` verlangt
    dauerhaft mindestens 1400 Zeichen Abstand zur Baseline. Wird die Baseline
    mit einer echten Erweiterung angehoben, muss der Abstand derselbe bleiben —
    sonst ist die Anhebung ein Freibrief.
    """
    sizes = json.loads((REPO_ROOT / "tests" / "baselines" / "skill_sizes.json").read_text())
    baseline = sizes["extraction-matrix"]
    current = len(MATRIX_SKILL.read_text(encoding="utf-8"))
    delta = baseline - current
    assert delta >= 1400, f"Guard-Marge zu klein: {delta} (Baseline {baseline}, aktuell {current})"
    assert delta < 1600, (
        f"Baseline {baseline} liegt {delta} Zeichen ueber der Datei — mehr als der "
        "Netto-Zuwachs, die Anhebung waere damit ein Freibrief statt einer Korrektur"
    )


def test_token_baseline_is_the_measured_value_not_a_head_start():
    tokens = json.loads((REPO_ROOT / "tests" / "baselines" / "tokens.json").read_text())
    baseline = tokens["extraction-matrix"]
    # cl100k-Proxy wie in tests/test_skills_manifest.py.
    current = -(-len(MATRIX_SKILL.read_text(encoding="utf-8")) // 4)
    assert current <= baseline * 1.20, (
        f"Token-Drift {current} > {baseline} * 1.20 — Baseline nicht angehoben"
    )
    assert baseline <= current, (
        f"tokens.json-Baseline {baseline} liegt ueber dem Ist-Wert {current}; "
        "die Baseline ist der gemessene Stand, kein Vorschuss"
    )


def test_extraction_matrix_skill_documents_table_source():
    skill = MATRIX_SKILL.read_text(encoding="utf-8")
    assert "vault.list_tables(" in skill
    assert "vault.get_table_cell(" in skill
    assert "evidence" in skill
    assert MISSING_MARKER in skill, "Die Fehlend-Regel bleibt bestehen"


def test_meta_analysis_agent_uses_table_source_without_auto_filling(tmp_path):
    agent = META_AGENT.read_text(encoding="utf-8")
    assert "vault.list_tables(" in agent
    assert "mcp__academic-vault__vault_list_tables" in agent
    assert "mcp__academic-vault__vault_get_table_cell" in agent
    # Kein automatisches Uebernehmen von yi/vi ohne Bestaetigung.
    lowered = agent.lower()
    assert "vorschlag" in lowered
    assert "bestätigung" in lowered or "bestaetigung" in lowered


# ---------------------------------------------------------------------------
# Bestands-DBs: Migration ist idempotent und liest ohne Absturz
# ---------------------------------------------------------------------------


def test_legacy_db_gets_paper_tables_via_migration(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    VaultDB(db_path).init_schema()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS paper_tables")
        conn.commit()
    finally:
        conn.close()

    migrate.add_paper_tables_table(db_path)
    migrate.add_paper_tables_table(db_path)  # idempotent

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_tables'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_listing_tables_on_a_legacy_db_returns_empty_instead_of_raising(tmp_path):
    db_path, paper_id = _make_paper(tmp_path, RESULTS_PDF)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS paper_tables")
        conn.commit()
    finally:
        conn.close()

    assert list_paper_tables(db_path, paper_id) == []
