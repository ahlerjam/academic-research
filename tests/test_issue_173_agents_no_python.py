"""Regressionstest fuer Issue #173.

`agents/` darf ausschliesslich Sub-Agent-`.md`-Dateien enthalten, damit die
Claude-Code-Auto-Discovery fuer `agents/` nicht mit Python-Files vermischt wird.

Akzeptanzkriterien:
- `find agents -name '*.py'` ist leer (kein Python in `agents/`).
- `agents/__init__.py` existiert nicht mehr.

(Die urspruenglich hier ebenfalls getesteten Importierbarkeits-Checks fuer das
Auth-Helper-Modul unter `scripts/` entfielen mit Issue #377, das Modul wurde
als tote Parallellogik entfernt.)
"""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
AGENTS_DIR = REPO_ROOT / "agents"


def test_agents_dir_contains_no_python_files():
    """`agents/` enthaelt keine `.py`-Dateien mehr (Smoke-Test aus dem Issue)."""
    py_files = sorted(p.name for p in AGENTS_DIR.rglob("*.py"))
    assert py_files == [], f"agents/ enthaelt noch Python-Files: {py_files}"


def test_agents_init_py_removed():
    """`agents/__init__.py` wurde geloescht."""
    assert not (AGENTS_DIR / "__init__.py").exists()
