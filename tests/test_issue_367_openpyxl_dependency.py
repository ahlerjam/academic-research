"""Regressionstest fuer Issue #367 — openpyxl fehlte als Dependency.

`openpyxl` ist Pflicht-Dependency des xlsx-Excel-Backends (genutzt von den
Slash-Commands `/excel` und `/pickup`), stand aber weder in
`scripts/requirements.txt` noch in `pyproject.toml` — ein frisches Setup
ueber den dokumentierten Weg (`commands/setup.md`, `scripts/setup.sh`) liess
die Excel-Erzeugung mit `ModuleNotFoundError: No module named 'openpyxl'`
scheitern.

Hinweis: Issue #235 hatte `openpyxl` zuvor bewusst aus
`scripts/requirements.txt` entfernt, weil kein `scripts/*.py`-Modul es
importiert — der damalige Scan sah den Konsumenten ausserhalb von
`scripts/` nicht. `tests/test_issue_235_unused_deps.py` prueft seit #367
nur noch `pandas`.

Praemissen-Korrektur (Issue #445): Die Fassung aus der Fix-Runde zu PR #428
nahm `/pickup` von der `openpyxl`-Pflicht aus, weil `commands/pickup.md`
woertlich "kein openpyxl/pandas" behauptete. Diese Behauptung war falsch —
beide Commands rufen dasselbe Backend `document-skills:xlsx` auf, das laut
eigener SKILL.md `pandas`/`openpyxl` im lokalen Environment ausfuehrt. Seit
#445 liegt das Backend als Plugin-Dependency vor statt als Vendor-Kopie im
Repo; an der `openpyxl`-Pflicht aendert das nichts. Siehe
`test_pickup_command_doc_names_openpyxl_backed_skill` und
`test_openpyxl_dependency_comments_name_the_shared_backend` unten.
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


def test_pickup_command_doc_names_openpyxl_backed_skill():
    """Praemissen-Korrektur (Issue #445): `/pickup` braucht `openpyxl` sehr wohl.

    Die Vorfassung dieses Tests erzwang in `commands/pickup.md` den String
    "kein openpyxl/pandas". Diese Aussage war sachlich falsch: `/pickup` und
    `/excel` nutzen dasselbe Backend `document-skills:xlsx`, und dessen
    SKILL.md schreibt "pandas for data, openpyxl for formulas/formatting" und
    importiert `from openpyxl import Workbook`. Der Skill laeuft im lokalen
    Python-Environment des Nutzers — ohne `openpyxl` scheitert auch `/pickup`
    mit `ModuleNotFoundError`. Die Assertion ist deshalb umgedreht.
    """
    pickup_doc = (REPO_ROOT / "commands" / "pickup.md").read_text()
    assert "document-skills:xlsx" in pickup_doc, (
        "commands/pickup.md nennt nicht mehr document-skills:xlsx als "
        "Excel-Backend — Praemisse dieses Tests veraltet, Test ueberpruefen."
    )
    assert "kein openpyxl" not in pickup_doc, (
        "commands/pickup.md behauptet wieder, /pickup komme ohne openpyxl aus — "
        "das Backend document-skills:xlsx nutzt openpyxl und pandas."
    )


def test_openpyxl_dependency_comments_name_the_shared_backend():
    """Die Begruendungs-Kommentare muessen BEIDE Konsumenten nennen.

    `openpyxl` haengt nicht an einem einzelnen Command, sondern am
    gemeinsamen Excel-Backend `document-skills:xlsx`, das `/excel` UND
    `/pickup` aufrufen. Nennt der Kommentar nur einen der beiden, laedt er
    zur naechsten Fehlannahme ein — genau die hatte Issue #367 / PR #428
    produziert (damals in die andere Richtung).
    """
    for path in (REQUIREMENTS, PYPROJECT):
        lines = path.read_text().splitlines()
        dep_line_idx = next(i for i, line in enumerate(lines) if "openpyxl>=" in line)
        comment = _leading_comment_block(lines, dep_line_idx)
        for consumer in ("/excel", "/pickup"):
            assert consumer in comment, (
                f"{path.relative_to(REPO_ROOT)}: Kommentar ueber der openpyxl-"
                f"Dependency nennt '{consumer}' nicht als Konsumenten. "
                f"Kommentar:\n{comment}"
            )
        assert "document-skills:xlsx" in comment, (
            f"{path.relative_to(REPO_ROOT)}: Kommentar benennt das Backend "
            f"'document-skills:xlsx' nicht. Kommentar:\n{comment}"
        )
