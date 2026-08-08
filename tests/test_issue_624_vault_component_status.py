"""Tests fuer die Zustandsausgabe optionaler Vault-Bestandteile (Issue #624).

AC -> Testfall (siehe Issue #624 / Plan-Kommentar):
  - "nennt fuer Embedding-Modell, sqlite-vec und FTS5 je, ob geladen" ->
    :func:`test_component_status_reports_all_three_components`
  - "zu jedem nicht geladenen Bestandteil steht, welche Funktion fehlt,
    laienverstaendlich" -> :func:`test_missing_embedding_model_names_functional_impact`,
    :func:`test_missing_sqlite_vec_names_functional_impact`
  - "nennt Python-Interpreter und DB-Pfad" ->
    :func:`test_component_status_includes_interpreter_and_db_path`
  - "Test deckt fehlenden Bestandteil ab" -> s.o.; Kontrastfall (nicht nur
    Negativpfad) -> :func:`test_component_status_all_loaded_when_available`
  - "README-Formulierung entspricht tatsaechlichem Verhalten" ->
    :func:`test_readme_model_not_marked_pflicht`

Rot->Gruen-Beweis: Diese Testdatei importiert ``get_component_status`` aus
``academic_vault.health`` -- vor #624 existiert weder das Modul noch die
Funktion, der Import schlaegt mit ``ModuleNotFoundError`` fehl; auf diesem
Branch gruen.
"""

import sqlite3
import sys
from pathlib import Path

import pytest
from academic_vault import health
from academic_vault.db import VaultDB
from academic_vault.health import get_component_status

REPO_ROOT = Path(__file__).parent.parent
README = REPO_ROOT / "README.md"


def _vec_extension_loadable() -> bool:
    """Probe: kann diese Python-Runtime ueberhaupt SQLite-Extensions laden?

    Duplikat von ``tests/test_vault_skeleton.py::_vec_extension_loadable`` --
    manche Python-Builds (z.B. macOS-System-Python, actions/setup-python auf
    macOS) sind ohne ``--enable-loadable-sqlite-extensions`` gebaut. Der
    Kontrastfall "alles geladen" (:func:`test_component_status_all_loaded_when_available`)
    darf dort nicht failen, sondern muss skippen (Plan-Risikonotiz #624:
    CI-Umgebungsabhaengigkeit).
    """
    conn = sqlite3.connect(":memory:")
    try:
        if not hasattr(conn, "enable_load_extension"):
            return False
        conn.enable_load_extension(True)
        conn.enable_load_extension(False)
        return True
    except (AttributeError, sqlite3.OperationalError, sqlite3.NotSupportedError):
        return False
    finally:
        conn.close()


def _fresh_db_path(tmp_path) -> str:
    return str(tmp_path / "vault.db")


def test_component_status_reports_all_three_components(tmp_path):
    """AC1: Embedding-Modell, sqlite-vec, FTS5 -- je ein bool ``loaded``."""
    status = get_component_status(_fresh_db_path(tmp_path))

    for component in ("embedding_model", "sqlite_vec", "fts5"):
        assert component in status, f"Komponente '{component}' fehlt in der Zustandsausgabe"
        assert isinstance(status[component]["loaded"], bool), (
            f"{component}.loaded ist kein bool: {status[component]['loaded']!r}"
        )


def test_missing_embedding_model_names_functional_impact(tmp_path):
    """AC2: Fehlendes Embedding-Modell -> Klartext-Funktionsverlust, nicht nur der Name.

    Nutzt die autouse-Fixture ``block_real_embedding_backend`` aus
    tests/conftest.py, die ``get_embedder()`` bereits realistisch auf
    ``None`` degradieren laesst -- kein zusaetzliches Mocking noetig.
    """
    status = get_component_status(_fresh_db_path(tmp_path))
    embedding_status = status["embedding_model"]

    assert embedding_status["loaded"] is False
    impact = embedding_status["impact"]
    assert "semantische Suche" in impact.lower() or "stichwortsuche" in impact.lower(), (
        f"impact-Text ist nicht laienverstaendlich formuliert: {impact!r}"
    )
    assert embedding_status["reason"], "reason sollte bei bekanntem Fehler gesetzt sein"


def test_missing_sqlite_vec_names_functional_impact(tmp_path, monkeypatch):
    """AC2: Fehlendes sqlite-vec -> Klartext-Funktionsverlust, nicht nur 'sqlite-vec'."""

    def _fail_load_vec_extension(self, conn=None):
        self.vec_available = False
        self.vec_unavailable_reason = "sqlite-vec-Extension nicht ladbar (simuliert, Test #624)"
        return False

    monkeypatch.setattr(VaultDB, "load_vec_extension", _fail_load_vec_extension)

    status = get_component_status(_fresh_db_path(tmp_path))
    vec_status = status["sqlite_vec"]

    assert vec_status["loaded"] is False
    impact = vec_status["impact"]
    assert "stichwortsuche" in impact.lower(), (
        f"impact-Text nennt keinen laienverstaendlichen Funktionsverlust: {impact!r}"
    )
    assert vec_status["reason"] == "sqlite-vec-Extension nicht ladbar (simuliert, Test #624)"


def test_component_status_includes_interpreter_and_db_path(tmp_path):
    """AC3: Python-Interpreter und DB-Pfad stehen in der Ausgabe."""
    db_path = _fresh_db_path(tmp_path)
    status = get_component_status(db_path)

    assert status["python_executable"] == sys.executable
    assert status["db_path"] == db_path


def test_component_status_all_loaded_when_available(tmp_path, fake_embedder, monkeypatch):
    """Kontrastfall: alle drei Bestandteile geladen -> ``loaded`` je True.

    Embedding-Modell wird per ``fake_embedder``-Injektion erzwungen (die
    autouse-Guard-Fixture blockt sonst jedes echte Backend). sqlite-vec und
    FTS5 laufen real -- geskippt, wenn diese Python-Runtime keine ladbaren
    SQLite-Extensions unterstuetzt (Plan-Risikonotiz #624).
    """
    if not _vec_extension_loadable():
        pytest.skip("Python-Build ohne --enable-loadable-sqlite-extensions (z.B. macOS-CI)")

    monkeypatch.setattr(health, "get_embedder", lambda *a, **kw: fake_embedder)

    status = get_component_status(_fresh_db_path(tmp_path))

    assert status["embedding_model"]["loaded"] is True
    assert status["embedding_model"]["reason"] is None
    assert status["sqlite_vec"]["loaded"] is True
    assert status["fts5"]["loaded"] is True


def test_fts5_missing_names_functional_impact(monkeypatch, tmp_path):
    """AC2 fuer FTS5: simuliert per Monkeypatch, s. Plan-Risikonotiz #624 --

    ``init_schema()`` laesst einen fehlenden FTS5-Modul-Support in der Praxis
    kaum kontrolliert beobachten (ungefangenes ``executescript`` wuerde den
    Serverstart abbrechen). Der Check selbst (``_fts5_loaded``) wird deshalb
    direkt gemockt statt real herbeigefuehrt.
    """
    monkeypatch.setattr(health, "_fts5_loaded", lambda conn: False)

    status = get_component_status(_fresh_db_path(tmp_path))
    fts5_status = status["fts5"]

    assert fts5_status["loaded"] is False
    assert (
        "teilstring" in fts5_status["impact"].lower() or "volltext" in fts5_status["impact"].lower()
    )


def test_readme_model_not_marked_pflicht():
    """AC5: Die README-Zeile zum Embedding-Modell behauptet nicht mehr 'Pflicht'.

    Der Code degradiert bei fehlendem Backend sauber auf FTS5-only (s.
    ``embedding_model.get_embedder()``) -- ein Bestandteil, dessen Fehlen der
    Code auffaengt, ist keine Pflicht (Issue #624 Scope).
    """
    readme = README.read_text(encoding="utf-8")
    lines = [line for line in readme.splitlines() if "bge-m3" in line and "Embedding" in line]
    assert lines, "README-Quickstart-Zeile zum Embedding-Modell nicht gefunden"
    for line in lines:
        assert "| Pflicht" not in line and "Pflicht," not in line, (
            f"README fuehrt das Embedding-Modell weiterhin als Pflicht: {line!r}"
        )
        assert "Optional" in line, f"README-Zeile sollte 'Optional' nennen: {line!r}"
