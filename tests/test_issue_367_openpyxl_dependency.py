"""Regressionstest fuer Issue #367 — openpyxl fehlte als Dependency.

`openpyxl` ist Pflicht-Dependency des vendorierten xlsx-Skills
(`skills/xlsx/scripts/recalc.py`, genutzt von den Slash-Commands `/excel`
und `/pickup`), stand aber weder in `scripts/requirements.txt` noch in
`pyproject.toml` — ein frisches Setup ueber den dokumentierten Weg
(`commands/setup.md`, `scripts/setup.sh`) liess `/excel`/`/pickup` mit
`ModuleNotFoundError: No module named 'openpyxl'` scheitern.

Hinweis: Issue #235 hatte `openpyxl` zuvor bewusst aus
`scripts/requirements.txt` entfernt, weil kein `scripts/*.py`-Modul es
importiert — der damalige Scan sah den Konsumenten in `skills/xlsx/`
nicht. `tests/test_issue_235_unused_deps.py` prueft seit #367 nur noch
`pandas`.
"""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).parent.parent
REQUIREMENTS = REPO_ROOT / "scripts" / "requirements.txt"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _parse_requirements() -> dict[str, Requirement]:
    parsed: dict[str, Requirement] = {}
    for raw in REQUIREMENTS.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line)
        parsed[req.name.lower()] = req
    return parsed


def test_openpyxl_listed_in_requirements_txt():
    """AC #1 (Teil 1): openpyxl steht in scripts/requirements.txt."""
    reqs = _parse_requirements()
    assert "openpyxl" in reqs, (
        "openpyxl fehlt in scripts/requirements.txt — /excel und /pickup "
        "brechen nach frischem Setup mit ModuleNotFoundError ab (Issue #367)."
    )


def test_openpyxl_listed_in_pyproject_dependencies():
    """AC #1 (Teil 2): openpyxl steht in pyproject.toml [project.dependencies]."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {Requirement(d).name.lower() for d in deps}
    assert "openpyxl" in names, (
        "openpyxl fehlt in pyproject.toml [project.dependencies] (Issue #367)."
    )


def test_openpyxl_importable():
    """AC #2: openpyxl ist im aktiven Environment tatsaechlich installiert.

    Nur eine Zeile in requirements.txt zu haben genuegt nicht (siehe #367-
    Reproduktion) — massgeblich ist, dass das Paket auch installiert ist.
    """
    import openpyxl  # noqa: F401 — reiner Importierbarkeits-Check
