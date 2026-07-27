"""Regressionstest fuer Issue #235: pandas ungenutzt.

`pandas` und `openpyxl` standen in `scripts/requirements.txt`, wurden aber
von keinem `scripts/*.py` importiert. Issue #235 entfernte beide.

Fuer `openpyxl` war das zu kurz gegriffen: der vendorierte Skill
`skills/xlsx/scripts/recalc.py` (genutzt vom Slash-Command `/excel`, siehe
`commands/excel.md: allowed-tools: ... Skill(xlsx)`) braucht `openpyxl`
zwingend, importiert es aber ausserhalb von `scripts/` — der damalige Scan
sah diesen Konsumenten nicht. Ohne die Dependency ist `/excel` in jeder
Installation ueber den dokumentierten Setup-Weg (`scripts/requirements.txt`)
defekt (`ModuleNotFoundError`). Issue #367 hat `openpyxl` deshalb wieder
aufgenommen; dieser Test prueft ab jetzt nur noch `pandas`.

Hinweis: `/pickup` ist davon NICHT betroffen — es nutzt laut eigener Doku
(`commands/pickup.md`) ausschliesslich das externe `document-skills:xlsx`-
Plugin (kein openpyxl/pandas). Die urspruengliche PR #428 zu #367 hatte
`/pickup` faelschlich als Mit-Betroffenen genannt; siehe
`tests/test_issue_367_openpyxl_dependency.py` fuer den Regressions-Guard.

Dieser Test sichert ab, dass

1. `scripts/requirements.txt` kein `pandas` listet, und
2. kein `scripts/`-Code `pandas` importiert,

sodass nur tatsaechlich genutzte Pakete im Top-Level-Requirements stehen.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
REQUIREMENTS = REPO_ROOT / "scripts" / "requirements.txt"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Pakete, die laut Akzeptanzkriterien NICHT im Top-Level-Requirements stehen
# duerfen, weil sie von scripts/ nicht importiert werden. `openpyxl` ist seit
# Issue #367 bewusst ausgenommen (Konsument: skills/xlsx/, siehe Docstring).
UNUSED_PACKAGES = ("pandas",)


def _listed_packages() -> set[str]:
    """Liefert die in requirements.txt gelisteten Paketnamen (lowercase)."""
    packages: set[str] = set()
    for raw in REQUIREMENTS.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Paketname = alles vor Version-Specifier / Extras / Whitespace.
        name = re.split(r"[<>=!~\[ ;]", line, maxsplit=1)[0].strip().lower()
        if name:
            packages.add(name)
    return packages


@pytest.mark.parametrize("package", UNUSED_PACKAGES)
def test_unused_package_not_in_requirements(package: str) -> None:
    """`pandas`/`openpyxl` duerfen nicht in scripts/requirements.txt stehen."""
    assert package not in _listed_packages(), (
        f"{package!r} steht in scripts/requirements.txt, wird aber von "
        f"scripts/ nicht importiert (siehe Issue #235)."
    )


@pytest.mark.parametrize("package", UNUSED_PACKAGES)
def test_unused_package_not_imported_in_scripts(package: str) -> None:
    """Kein scripts/*.py darf pandas/openpyxl importieren (Regression-Guard)."""
    import_pattern = re.compile(
        rf"^\s*(?:import\s+{re.escape(package)}\b|from\s+{re.escape(package)}\b)",
        re.MULTILINE,
    )
    offenders = []
    for py_file in SCRIPTS_DIR.rglob("*.py"):
        if import_pattern.search(py_file.read_text()):
            offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"{package!r} wird in scripts/ importiert ({offenders}); Entfernen aus "
        f"requirements.txt waere falsch."
    )
