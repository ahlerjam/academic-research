"""Smoke-Tests fuer den academic_vault MCP-Server (TDD-First Skelett)."""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from academic_vault.db import VaultDB
from academic_vault.files_api import FilesAPIClient

# Worktree-Root zum PYTHONPATH hinzufuegen damit academic_vault importierbar ist
_WORKTREE_ROOT = Path(__file__).parent.parent

_SERVER_AVAILABLE = importlib.util.find_spec("academic_vault.server") is not None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def make_temp_db() -> tuple[str, "VaultDB"]:
    """Erstellt eine temporaere In-Memory-DB oder Datei-DB."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = VaultDB(tmp.name)
    db.init_schema()
    return tmp.name, db


# ---------------------------------------------------------------------------
# Task 2 aktiviert: test_schema_creates_tables
# ---------------------------------------------------------------------------


def test_schema_creates_tables():
    """Alle 5 Tabellen + papers_fts existieren nach init_schema()."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','trigger') ORDER BY name"
        )
        names = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "papers" in names
        assert "quotes" in names
        assert "decisions" in names
        assert "notes" in names
        assert "papers_fts" in names
        assert "papers_ai" in names
        assert "papers_ad" in names
        assert "papers_au" in names
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 4 aktiviert: test_add_paper_and_get
# ---------------------------------------------------------------------------


def test_add_paper_and_get():
    """add_paper + get_paper Round-Trip."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        csl = '{"title": "Test Paper", "abstract": "An abstract."}'
        db.add_paper("p1", csl, doi="10.1234/test")
        paper = db.get_paper("p1")
        assert paper is not None
        assert paper["paper_id"] == "p1"
        assert paper["doi"] == "10.1234/test"
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 7 aktiviert: test_search_returns_results
# ---------------------------------------------------------------------------


def test_search_returns_results():
    """vault.search(query) gibt >= 1 Ergebnis zurueck und liegt unter 500ms (AC #62)."""
    import time

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        # Seed 50 Papers fuer realistische FTS5-Bedingungen (AC: <500ms bei >=50)
        for i in range(50):
            csl = (
                f'{{"title": "DevOps Governance Study {i}",'
                f' "abstract": "Paper {i} about DevOps in enterprise."}}'
            )
            db.add_paper(f"p-search-{i}", csl)

        from academic_vault.server import search_papers

        start = time.perf_counter()
        results = search_papers(db_path, "DevOps Governance", k=5)
        elapsed = time.perf_counter() - start

        assert len(results) >= 1
        assert "paper_id" in results[0]
        # AC #62: Performance-Ziel <500ms bei mind. 50 Papers
        assert elapsed < 0.5, f"search took {elapsed:.3f}s, expected <0.5s"
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 6 aktiviert: test_add_quote_requires_api_response_id
# ---------------------------------------------------------------------------


def test_add_quote_requires_api_response_id():
    """vault.add_quote mit citations-api + kein api_response_id wirft ValueError."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        csl = '{"title": "Test Paper"}'
        db.add_paper("p-quote", csl)

        from academic_vault.server import add_quote

        with pytest.raises(ValueError, match="api_response_id"):
            add_quote(
                db_path=db_path,
                paper_id="p-quote",
                verbatim="Exact text from the paper.",
                extraction_method="citations-api",
                api_response_id=None,
            )
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 6 aktiviert: test_add_quote_manual_no_api_id
# ---------------------------------------------------------------------------


def test_add_quote_manual_no_api_id():
    """vault.add_quote mit manual + kein api_response_id ist OK."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        csl = '{"title": "Test Paper"}'
        db.add_paper("p-manual", csl)

        from academic_vault.server import add_quote

        quote_id = add_quote(
            db_path=db_path,
            paper_id="p-manual",
            verbatim="Manually noted text.",
            extraction_method="manual",
            api_response_id=None,
        )
        assert quote_id is not None
        assert len(quote_id) > 0
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 5 aktiviert: test_ensure_file_caches
# ---------------------------------------------------------------------------


def test_ensure_file_caches():
    """Zweiter Aufruf von ensure_file triggert kein Re-Upload."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    # Minimales temporaeres PDF-Dummy
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_f:
        pdf_path = pdf_f.name
        pdf_f.write(b"%PDF-1.4 fake content")
    try:
        db = VaultDB(db_path)
        db.init_schema()
        db.add_paper("p-file", '{"title": "File Paper"}', pdf_path=pdf_path)

        mock_upload = MagicMock()
        mock_upload.return_value = "file-abc123"

        client = FilesAPIClient(anthropic_api_key="test-key", cache_db_path=db_path)

        with patch.object(client, "_upload_file", mock_upload):
            fid1 = client.ensure_file(pdf_path)
            fid2 = client.ensure_file(pdf_path)

        assert fid1 == fid2 == "file-abc123"
        mock_upload.assert_called_once()
    finally:
        os.unlink(db_path)
        os.unlink(pdf_path)


# ---------------------------------------------------------------------------
# Task 8 aktiviert: test_find_quotes
# ---------------------------------------------------------------------------


def test_find_quotes():
    """find_quotes(paper_id) gibt vorher eingefuegte Quotes zurueck."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        db.add_paper("p-fq", '{"title": "Find Quotes Paper"}')

        from academic_vault.server import add_quote, find_quotes

        add_quote(
            db_path=db_path,
            paper_id="p-fq",
            verbatim="An important verbatim quote.",
            extraction_method="manual",
        )
        results = find_quotes(db_path, paper_id="p-fq")
        assert len(results) >= 1
        assert results[0]["paper_id"] == "p-fq"
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 8 aktiviert: test_get_quote
# ---------------------------------------------------------------------------


def test_get_quote():
    """get_quote(quote_id) gibt vollstaendigen Record zurueck."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        db.add_paper("p-gq", '{"title": "Get Quote Paper"}')

        from academic_vault.server import add_quote, get_quote

        quote_id = add_quote(
            db_path=db_path,
            paper_id="p-gq",
            verbatim="The verbatim text to retrieve.",
            extraction_method="manual",
        )
        record = get_quote(db_path, quote_id)
        assert record is not None
        assert record["quote_id"] == quote_id
        assert record["verbatim"] == "The verbatim text to retrieve."
        assert record["paper_id"] == "p-gq"
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 9 aktiviert: test_stats
# ---------------------------------------------------------------------------


def test_stats():
    """vault.stats() gibt korrekte Counts + token_savings_estimate > 0 bei >=1 file_id."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = VaultDB(db_path)
        db.init_schema()
        db.add_paper("p-stats", '{"title": "Stats Paper"}')
        # file_id manuell setzen (wie nach ensure_file)
        db.set_file_id("p-stats", "file-xyz", expires_at=int(time.time()) + 3600)

        from academic_vault.server import add_quote

        add_quote(
            db_path=db_path,
            paper_id="p-stats",
            verbatim="A test quote for stats.",
            extraction_method="manual",
        )

        from academic_vault.files_api import FilesAPIClient

        stats = FilesAPIClient.get_stats(db_path)

        assert "paper_count" in stats
        assert "quote_count" in stats
        assert "cached_files" in stats
        assert "token_savings_estimate" in stats
        assert stats["paper_count"] >= 1
        assert stats["quote_count"] >= 1
        assert stats["cached_files"] >= 1
        assert stats["token_savings_estimate"] > 0
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Task 3 aktiviert: test_vec_fallback
# ---------------------------------------------------------------------------


def _vec_extension_loadable() -> bool:
    """Probe: kann diese Python-Runtime ueberhaupt SQLite-Extensions laden?

    Manche Python-Builds (z.B. macOS-System-Python, actions/setup-python auf
    macOS) sind ohne ``--enable-loadable-sqlite-extensions`` gebaut. Dort ist
    ``enable_load_extension`` entweder nicht vorhanden oder wirft beim Aufruf
    -- die Vektor-Suche ist dann strukturell nicht verfuegbar (Issue #371,
    Risiko 1), unabhaengig vom Bugfix. Tests, die eine ladbare Extension
    voraussetzen, muessen dort skippen statt failen.
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


@pytest.mark.skipif(
    not _vec_extension_loadable(),
    reason="Python-Build ohne --enable-loadable-sqlite-extensions (z.B. macOS-CI)",
)
def test_vec_extension_loads_by_default():
    """AC1: load_vec_extension() liefert ohne SQLITE_VEC_PATH True (frische DB).

    Regression fuer Issue #371: der Bare-Name-Load ``load_extension("sqlite_vec")``
    findet die pip-installierte Dylib nie. Der Default muss stattdessen
    ``sqlite_vec.loadable_path()`` verwenden.
    """
    env_backup = os.environ.pop("SQLITE_VEC_PATH", None)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        with VaultDB(tmp.name) as db:
            result = db.load_vec_extension()
        assert result is True
    finally:
        if env_backup is not None:
            os.environ["SQLITE_VEC_PATH"] = env_backup
        os.unlink(tmp.name)


def test_vec_fallback():
    """Wenn sqlite-vec nicht ladbar ist (kaputter Override) -> vec_available=False,
    FTS5 funktioniert trotzdem.

    Simuliert ueber einen bewusst kaputten ``SQLITE_VEC_PATH``-Override eine
    Umgebung ohne ladbare Extension (statt "kein Env gesetzt" -- das liefert
    nach Fix #371 i.d.R. True, siehe test_vec_extension_loads_by_default).
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        env_backup = os.environ.get("SQLITE_VEC_PATH")
        os.environ["SQLITE_VEC_PATH"] = "/nonexistent/path/to/sqlite_vec_override.so"
        try:
            db = VaultDB(db_path)
            db.init_schema()
            # vec_available muss False sein (Override zeigt auf nichts Ladbares)
            assert db.vec_available is False
            # FTS5 muss trotzdem funktionieren
            csl = '{"title": "Fallback Test Paper", "abstract": "Testing FTS5 fallback."}'
            db.add_paper("p-fallback", csl)
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT paper_id FROM papers_fts WHERE papers_fts MATCH 'Fallback'"
            ).fetchall()
            conn.close()
            assert len(rows) >= 1
        finally:
            if env_backup is not None:
                os.environ["SQLITE_VEC_PATH"] = env_backup
            else:
                os.environ.pop("SQLITE_VEC_PATH", None)
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Issue #371: sqlite-vec-Pin-Drift + .mcp.json-Default
# ---------------------------------------------------------------------------


def _sqlite_vec_pin_from_pyproject() -> str:
    data = tomllib.loads((_WORKTREE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for dep in data["project"]["dependencies"]:
        if dep.startswith("sqlite-vec"):
            return dep
    raise AssertionError("sqlite-vec nicht in pyproject.toml[project.dependencies] gefunden")


def _sqlite_vec_pin_from_requirements() -> str:
    text = (_WORKTREE_ROOT / "academic_vault" / "requirements.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("sqlite-vec"):
            return stripped
    raise AssertionError("sqlite-vec nicht in academic_vault/requirements.txt gefunden")


def test_sqlite_vec_pin_matches_across_pyproject_and_requirements():
    """AC2: pyproject.toml und academic_vault/requirements.txt duerfen bei der
    sqlite-vec-Version nicht driften; die Version muss exakt gepinnt sein
    (kein Range mehr wie ``>=0.1.0``)."""
    pyproject_pin = _sqlite_vec_pin_from_pyproject()
    requirements_pin = _sqlite_vec_pin_from_requirements()
    assert pyproject_pin == requirements_pin
    assert "==" in pyproject_pin


def test_mcp_json_has_no_empty_sqlite_vec_path():
    """AC3: .mcp.json darf SQLITE_VEC_PATH nicht leer vorbelegen -- ein leerer
    String verhindert den neuen Default-Ladepfad ueber
    sqlite_vec.loadable_path()."""
    data = json.loads((_WORKTREE_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    env = data["mcpServers"]["academic-vault"].get("env", {})
    assert env.get("SQLITE_VEC_PATH", "not-empty-if-absent") != ""


# ---------------------------------------------------------------------------
# Task 10 aktiviert: test_migrate_help
# ---------------------------------------------------------------------------


def test_migrate_help():
    """migrate.py --help muss mit exit 0 laufen."""
    import subprocess

    migrate_path = str(_WORKTREE_ROOT / "academic_vault" / "migrate.py")
    result = subprocess.run(
        [sys.executable, migrate_path, "--help"],
        capture_output=True,
        timeout=10,
        cwd=str(_WORKTREE_ROOT),
    )
    assert result.returncode == 0
    assert b"--db" in result.stdout or b"--state" in result.stdout
