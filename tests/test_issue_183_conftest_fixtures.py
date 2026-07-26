"""Regressionstest fuer Issue #183: zentrale pytest-Fixtures in tests/conftest.py.

Prueft Existenz, Importierbarkeit und korrektes Verhalten der vier zentralen
Fixtures, die laut Akzeptanzkriterien in conftest.py definiert sein muessen:
  - temp_vault_db       (Tempdir + sqlite-Setup via VaultDB)
  - mock_browser_use    (MagicMock fuer browser-use-Interaktionen)
  - sample_pdf          (Pfad auf eine echte PDF-Beispieldatei)
  - library_profile_tum (geparstes TUM-Bibliotheksprofil)

Diese Datei darf KEINE eigenen Fixtures definieren -- sie konsumiert nur die
zentralen conftest-Fixtures, um die Akzeptanzkriterien konkret zu belegen.
"""

import sqlite3
from pathlib import Path

CONFTEST_PATH = Path(__file__).parent / "conftest.py"


# ---------------------------------------------------------------------------
# Existenz / Importierbarkeit
# ---------------------------------------------------------------------------


def test_conftest_file_exists():
    """tests/conftest.py muss existieren und nicht leer sein."""
    assert CONFTEST_PATH.is_file(), "tests/conftest.py fehlt"
    assert CONFTEST_PATH.read_text(encoding="utf-8").strip(), "conftest.py ist leer"


def test_conftest_defines_required_fixtures():
    """Alle vier zentralen Fixtures muessen via conftest registriert sein."""
    expected = {
        "temp_vault_db",
        "mock_browser_use",
        "sample_pdf",
        "library_profile_tum",
    }
    text = CONFTEST_PATH.read_text(encoding="utf-8")
    missing = {name for name in expected if f"def {name}" not in text}
    assert not missing, f"Fixtures fehlen in conftest.py: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Verhalten der einzelnen Fixtures
# ---------------------------------------------------------------------------


def test_temp_vault_db_is_initialized(temp_vault_db):
    """temp_vault_db liefert einen DB-Pfad mit initialisiertem Schema."""
    db_path = str(temp_vault_db)
    assert Path(db_path).exists(), "temp_vault_db-Pfad existiert nicht"

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
        }
    finally:
        conn.close()
    # Kern-Tabellen aus schema.sql muessen vorhanden sein
    assert "papers" in tables, f"Tabelle 'papers' fehlt; vorhanden: {sorted(tables)}"
    assert "quotes" in tables, f"Tabelle 'quotes' fehlt; vorhanden: {sorted(tables)}"


def test_mock_browser_use_is_mock(mock_browser_use):
    """mock_browser_use ist ein aufrufbarer Mock fuer browser-use."""
    result = mock_browser_use.run("https://example.org")
    assert result is not None
    assert mock_browser_use.run.called


def test_sample_pdf_exists(sample_pdf):
    """sample_pdf zeigt auf eine echte, lesbare PDF-Datei."""
    pdf_path = Path(sample_pdf)
    assert pdf_path.is_file(), f"sample_pdf existiert nicht: {pdf_path}"
    assert pdf_path.suffix == ".pdf"
    assert pdf_path.read_bytes()[:4] == b"%PDF", "Datei ist keine gueltige PDF"


def test_library_profile_tum_shape(library_profile_tum):
    """library_profile_tum liefert das geparste TUM-Profil als dict."""
    assert isinstance(library_profile_tum, dict)
    assert library_profile_tum.get("uni") == "tum"
    assert "licensed_sites" in library_profile_tum
    assert isinstance(library_profile_tum["licensed_sites"], list)


# ---------------------------------------------------------------------------
# AC2: keine Repo-Root-sys.path-Boilerplate mehr außerhalb von conftest.py
# ---------------------------------------------------------------------------


# Dateien mit skill-spezifischem scripts/-Pfad (skills/<name>/scripts) -- das
# sind KEINE Duplikate der generischen Repo-Root/scripts-Boilerplate (jede
# zeigt auf ein anderes Skill-Verzeichnis) und bleiben bewusst unangetastet.
_SKILL_SPECIFIC_SYS_PATH_FILES = {
    "test_cluster_visualizer.py",
    "test_csl_import.py",
    "test_latex_export.py",
    "test_notebook_bundle.py",
    "test_prisma_flow.py",
    "test_reading_list_import.py",
    "test_zotero_import.py",
}


def test_no_duplicated_repo_root_sys_path_boilerplate():
    """Reine Repo-Root-/scripts-sys.path.insert-Boilerplate darf nur noch in
    conftest.py stehen -- test_*.py-Dateien beziehen das ueber die zentrale
    Fixture-Datei (pytest laedt conftest.py vor jedem Testmodul).
    """
    tests_dir = Path(__file__).parent
    offenders = []
    for path in sorted(tests_dir.glob("test_*.py")):
        if path.name == "test_issue_183_conftest_fixtures.py":
            continue
        if path.name in _SKILL_SPECIFIC_SYS_PATH_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        if "sys.path.insert" in text:
            offenders.append(path.name)
    assert not offenders, (
        "Dateien mit verbliebener Repo-Root/scripts-sys.path-Boilerplate "
        f"(sollte via conftest.py entfallen): {offenders}"
    )


# Dateien mit bestaetigt bytegleicher lokaler VaultDB-Fixture (kein
# Zusatz-Setup wie Paper-/Figure-Vorbefuellung), die auf `temp_vault_db`
# umgestellt wurden. Fixtures MIT Zusatz-Setup (z.B. test_ocr_detection.py::
# tmp_db, test_verbatim_figure_guard.py::vault_with_figure) sind bewusst NICHT
# migriert, da sie funktional mehr leisten als die generische Fixture.
_MIGRATED_VAULT_DB_FIXTURES = {
    "test_figure_verifier.py": "db_path",
    "test_history_restore.py": "vault_db",
    "test_risk_of_bias_agent.py": "db_path",
}


def test_bytegleiche_vault_db_fixtures_migrated_to_temp_vault_db():
    """Die bestaetigt bytegleichen lokalen VaultDB-Fixtures duerfen nicht mehr
    lokal definiert sein -- die betroffenen Dateien nutzen stattdessen die
    zentrale `temp_vault_db`-Fixture aus conftest.py.
    """
    tests_dir = Path(__file__).parent
    offenders = []
    for filename, fixture_name in _MIGRATED_VAULT_DB_FIXTURES.items():
        text = (tests_dir / filename).read_text(encoding="utf-8")
        if f"def {fixture_name}(" in text:
            offenders.append(f"{filename}::{fixture_name}")
        if "temp_vault_db" not in text:
            offenders.append(f"{filename}: nutzt temp_vault_db nicht")
    assert not offenders, f"Bytegleiche VaultDB-Fixtures nicht wie erwartet migriert: {offenders}"
