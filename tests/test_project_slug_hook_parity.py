"""Tests fuer Issue #365 -- Paritaet project_slug() (Python) vs. verbatim-guard.mjs (Node).

academic_vault/db.py:project_slug() und die SLUG-Berechnung in
hooks/verbatim-guard.mjs (`basename(process.env.CLAUDE_PROJECT_DIR ||
process.cwd()) || 'default'`) muessen bei identischem Environment denselben
Projekt-Slug liefern. Sonst schreiben Hook und MCP-Server gegen
unterschiedliche vault.db-Dateien (siehe Issue #190 und #365).

TDD: Schlaegt gegen den Ausgangszustand von db.py fehl, weil
project_slug() dort CLAUDE_PROJECT_DIR noch nicht beruecksichtigt
(nur Path.cwd()).
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_NODE_AVAILABLE = shutil.which("node") is not None

# Exakter Node-Ausdruck aus hooks/verbatim-guard.mjs:34. Bewusst als
# Literal dupliziert (nicht aus der Datei geparst), um den Paritaets-Test
# unabhaengig von Refactorings innerhalb des Hooks zu halten -- die
# Referenz-Formel selbst ist per Docstring/Kommentar an beiden Stellen
# verankert.
_NODE_SLUG_SCRIPT = (
    "import { basename } from 'node:path';"
    "const slug = basename(process.env.CLAUDE_PROJECT_DIR || process.cwd()) || 'default';"
    "process.stdout.write(slug);"
)


def _node_slug(env: dict[str, str], cwd: str) -> str:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", _NODE_SLUG_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=True,
    )
    return result.stdout


@pytest.mark.skipif(not _NODE_AVAILABLE, reason="node nicht verfuegbar")
def test_parity_only_claude_project_dir_set(monkeypatch, tmp_path):
    """CLAUDE_PROJECT_DIR gesetzt, CWD zeigt woanders hin -- beide muessen
    den Slug aus CLAUDE_PROJECT_DIR liefern."""
    from academic_vault import db

    project_dir = tmp_path / "projekt-a"
    project_dir.mkdir()
    other_cwd = tmp_path / "anderswo"
    other_cwd.mkdir()

    monkeypatch.chdir(other_cwd)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))

    python_slug = db.project_slug()
    node_slug = _node_slug(dict(os.environ), str(other_cwd))

    assert python_slug == node_slug == "projekt-a"


@pytest.mark.skipif(not _NODE_AVAILABLE, reason="node nicht verfuegbar")
def test_parity_only_cwd_set(monkeypatch, tmp_path):
    """Ohne CLAUDE_PROJECT_DIR muessen beide Implementierungen auf
    basename(CWD) zurueckfallen."""
    from academic_vault import db

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    workdir = tmp_path / "projekt-b"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    python_slug = db.project_slug()
    node_slug = _node_slug(dict(os.environ), str(workdir))

    assert python_slug == node_slug == "projekt-b"


@pytest.mark.skipif(not _NODE_AVAILABLE, reason="node nicht verfuegbar")
def test_parity_diverging_env_and_cwd(monkeypatch, tmp_path):
    """CLAUDE_PROJECT_DIR und CWD zeigen auf unterschiedliche Projekte --
    beide Implementierungen muessen CLAUDE_PROJECT_DIR bevorzugen und
    duerfen NICHT den CWD-Slug liefern."""
    from academic_vault import db

    project_dir = tmp_path / "projekt-c-env"
    project_dir.mkdir()
    workdir = tmp_path / "projekt-c-cwd"
    workdir.mkdir()

    monkeypatch.chdir(workdir)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))

    python_slug = db.project_slug()
    node_slug = _node_slug(dict(os.environ), str(workdir))

    assert python_slug == node_slug == "projekt-c-env"
    assert python_slug != "projekt-c-cwd"
