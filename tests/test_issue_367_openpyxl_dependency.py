"""Regressionstest fuer Issue #367 — openpyxl fehlte als Dependency.

`openpyxl` ist Pflicht-Dependency des vendorierten xlsx-Skills
(`skills/xlsx/scripts/recalc.py`, genutzt vom Slash-Command `/excel`, siehe
`commands/excel.md: allowed-tools: ... Skill(xlsx)`), stand aber weder in
`scripts/requirements.txt` noch in `pyproject.toml` — ein frisches Setup
ueber den dokumentierten Weg (`commands/setup.md`, `scripts/setup.sh`) liess
`/excel` mit `ModuleNotFoundError: No module named 'openpyxl'` scheitern.

Hinweis: Issue #235 hatte `openpyxl` zuvor bewusst aus
`scripts/requirements.txt` entfernt, weil kein `scripts/*.py`-Modul es
importiert — der damalige Scan sah den Konsumenten in `skills/xlsx/`
nicht. `tests/test_issue_235_unused_deps.py` prueft seit #367 nur noch
`pandas`.

Korrektur (Fix-Runde zu PR #428): Der urspruengliche Issue-Text und die
erste Fassung dieses Tests hatten `/pickup` faelschlich als zweiten
Betroffenen genannt. `/pickup` nutzt laut eigener Doku
(`commands/pickup.md`) ausschliesslich das externe `document-skills:xlsx`-
Plugin und dokumentiert woertlich "kein openpyxl/pandas" — es konnte nie
durch fehlendes `openpyxl` scheitern. Siehe
`test_pickup_command_doc_does_not_claim_openpyxl_dependency` und
`test_openpyxl_dependency_comments_not_scoped_to_pickup` unten fuer den
Regressions-Guard gegen diese falsche Praemisse.
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
        "openpyxl fehlt in scripts/requirements.txt — /excel bricht nach "
        "frischem Setup mit ModuleNotFoundError ab (Issue #367)."
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


def _leading_comment_block(lines: list[str], dependency_line_index: int) -> str:
    """Sammelt den zusammenhaengenden '#'-Kommentarblock direkt vor einer Zeile."""
    comment_lines: list[str] = []
    i = dependency_line_index - 1
    while i >= 0 and lines[i].strip().startswith("#"):
        comment_lines.insert(0, lines[i])
        i -= 1
    return "\n".join(comment_lines)


def test_pickup_command_doc_does_not_claim_openpyxl_dependency():
    """Gegenprobe zur Praemisse dieses Issues: `/pickup` erzeugt sein Workbook
    laut eigener Dokumentation (`commands/pickup.md`) ausschliesslich ueber
    das EXTERNE `document-skills:xlsx`-Plugin, nicht ueber den vendorierten
    `skills/xlsx`-Skill (der `openpyxl` nutzt). `commands/pickup.md` sagt das
    woertlich ("kein openpyxl/pandas") und ist seit PR #141 (18.05.2026) --
    lange vor Issue #367 -- unveraendert. `/pickup` kann daher nie durch
    fehlendes `openpyxl` mit `ModuleNotFoundError` scheitern; nur `/excel`
    (siehe `commands/excel.md`, `allowed-tools: ... Skill(xlsx)`) haengt am
    vendorierten Skill.
    """
    pickup_doc = (REPO_ROOT / "commands" / "pickup.md").read_text()
    assert "document-skills:xlsx" in pickup_doc, (
        "commands/pickup.md nennt nicht mehr document-skills:xlsx als "
        "Excel-Backend — Praemisse dieses Tests veraltet, Test ueberpruefen."
    )
    assert "kein openpyxl" in pickup_doc, (
        "commands/pickup.md dokumentiert nicht mehr explizit, dass /pickup ohne openpyxl auskommt."
    )


def test_openpyxl_dependency_comments_not_scoped_to_pickup():
    """`openpyxl` ist Pflicht-Dependency von `/excel`, NICHT von `/pickup`
    (siehe `test_pickup_command_doc_does_not_claim_openpyxl_dependency`
    oben). Die Kommentare, die die neue `openpyxl`-Zeile in
    `scripts/requirements.txt` und `pyproject.toml` begruenden, duerfen
    `/pickup` deshalb nicht als (Mit-)Konsumenten nennen — das war die
    falsche Praemisse aus Issue #367 / PR #428.
    """
    for path in (REQUIREMENTS, PYPROJECT):
        lines = path.read_text().splitlines()
        dep_line_idx = next(i for i, line in enumerate(lines) if "openpyxl>=" in line)
        comment = _leading_comment_block(lines, dep_line_idx)
        assert "/pickup" not in comment, (
            f"{path.relative_to(REPO_ROOT)}: Kommentar ueber der openpyxl-"
            f"Dependency behauptet faelschlich, dass /pickup openpyxl "
            f"braucht — siehe commands/pickup.md ('kein openpyxl/pandas'). "
            f"Kommentar:\n{comment}"
        )
