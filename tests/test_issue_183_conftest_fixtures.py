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

import ast
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
#
# Fix-Runde PR #359 (Issue #183): die urspruengliche Fassung dieses Guards
# hat ganze Dateien mit legitimem skill-spezifischem scripts/-Pfad
# (skills/<name>/scripts, z.B. test_latex_export.py) komplett von der Pruefung
# ausgenommen. Das hat NICHT nur die legitime Zeile verdeckt, sondern JEDE
# weitere sys.path.insert-Zeile in derselben Datei -- inklusive liegen
# gebliebener Repo-Root-Boilerplate (test_latex_export.py:412, per
# WORKTREE-Variable, inhaltlich identisch zur Boilerplate, die conftest.py
# zentralisiert). Der Guard prueft daher jetzt pro sys.path.insert-Aufruf
# (call-/zeilenweise) statt pro Datei: legitim ist ein Aufruf nur, wenn sein
# Ziel -- direkt oder ueber eine referenzierte Variablenzuweisung -- eine
# "skills"-Pfadkomponente enthaelt.


def _sys_path_insert_offenders(path: Path) -> list[int]:
    """Zeilennummern von sys.path.insert(...)-Aufrufen in `path`, die NICHT auf
    einen skill-spezifischen scripts/-Pfad (".../skills/<name>/scripts") zeigen.

    Prueft pro Aufruf (nicht pro Datei): eine Datei darf sowohl eine legitime
    skill-spezifische Zeile als auch -- separat zu erkennende -- liegen
    gebliebene Repo-Root-Boilerplate enthalten.
    """
    text = path.read_text(encoding="utf-8")
    if "sys.path.insert" not in text:
        return []

    tree = ast.parse(text, filename=str(path))
    assigns = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]

    def _is_skill_specific(call: ast.Call) -> bool:
        call_src = ast.get_source_segment(text, call) or ""
        if "skills" in call_src:
            return True
        referenced = {n.id for arg in call.args for n in ast.walk(arg) if isinstance(n, ast.Name)}
        if not referenced:
            return False
        for assign in assigns:
            targets = {t.id for t in assign.targets if isinstance(t, ast.Name)}
            if targets & referenced:
                assign_src = ast.get_source_segment(text, assign) or ""
                if "skills" in assign_src:
                    return True
        return False

    offenders = []
    for node in ast.walk(tree):
        is_sys_path_insert = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "insert"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "sys"
        )
        if is_sys_path_insert and not _is_skill_specific(node):
            offenders.append(node.lineno)
    return offenders


def test_sys_path_boilerplate_guard_is_call_wise_not_file_wise(tmp_path):
    """Regression fuer die Fix-Runde zu PR #359: eine Datei mit legitimer
    skill-spezifischer sys.path.insert-Zeile UND einer liegengebliebenen
    Repo-Root-Zeile (per Variable, wie in test_latex_export.py:412 vor dem
    Fix) muss die Repo-Root-Zeile weiterhin melden -- eine dateiweite
    Ausnahme wuerde beide gleichermassen ausblenden."""
    sample = tmp_path / "test_sample_mixed.py"
    sample.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "WORKTREE = Path(__file__).parent.parent\n"
        "SCRIPTS_DIR = WORKTREE / 'skills' / 'sample-skill' / 'scripts'\n"
        "sys.path.insert(0, str(SCRIPTS_DIR))\n"
        "\n"
        "\n"
        "def test_something():\n"
        "    sys.path.insert(0, str(WORKTREE))\n"
        "    assert True\n",
        encoding="utf-8",
    )
    offenders = _sys_path_insert_offenders(sample)
    assert offenders == [10], (
        f"Erwartet genau die Repo-Root-Zeile (10) als Offender, erhalten: {offenders}"
    )


def test_no_duplicated_repo_root_sys_path_boilerplate():
    """Reine Repo-Root-/scripts-sys.path.insert-Boilerplate darf nur noch in
    conftest.py stehen -- test_*.py-Dateien beziehen das ueber die zentrale
    Fixture-Datei (pytest laedt conftest.py vor jedem Testmodul). Prueft
    zeilenweise (siehe _sys_path_insert_offenders), damit Dateien mit
    legitimem skill-spezifischem Pfad nicht komplett ausgenommen werden.
    """
    tests_dir = Path(__file__).parent
    offenders = []
    for path in sorted(tests_dir.glob("test_*.py")):
        if path.name == "test_issue_183_conftest_fixtures.py":
            continue
        for lineno in _sys_path_insert_offenders(path):
            offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        "Dateien mit verbliebener Repo-Root/scripts-sys.path-Boilerplate "
        f"(sollte via conftest.py entfallen, zeilenweise geprueft): {offenders}"
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
