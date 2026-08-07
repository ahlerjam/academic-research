"""Regressionstest fuer Issue #723 — pdfplumber wird Kern-Dependency.

`pdfplumber` war seit #630 ein optionales Extra (`uv sync --extra tables`).
Tabellenextraktion funktionierte damit nur, wenn man dieses Extra kannte —
nach einer normalen Installation (`uv sync --extra dev`, bzw.
`scripts/setup.sh` fuer Endnutzer) meldete `vault.extract_tables` immer den
Status `backend-missing`, obwohl `pdfplumber` ein reines Python-Paket ohne
Versionskonflikt mit dem restlichen Bestand ist (anders als `FlagEmbedding`
beim lokalen Reranker, #376/#422). Dieser Test verhindert eine Rueckkehr zum
Extra-Modell. Muster analog `tests/test_issue_367_openpyxl_dependency.py`.
"""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).parent.parent
REQUIREMENTS = REPO_ROOT / "scripts" / "requirements.txt"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _parse_requirements() -> dict[str, Requirement]:
    parsed: dict[str, Requirement] = {}
    for raw in REQUIREMENTS.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line)
        parsed[req.name.lower()] = req
    return parsed


def test_pdfplumber_listed_in_requirements_txt():
    """pdfplumber steht aktiv (nicht auskommentiert) in scripts/requirements.txt."""
    reqs = _parse_requirements()
    assert "pdfplumber" in reqs, (
        "pdfplumber fehlt in scripts/requirements.txt (nicht auskommentiert) — "
        "Endnutzer-Installation liefert dann keine Tabellenextraktion (Issue #723)."
    )


def test_pdfplumber_listed_in_pyproject_dependencies():
    """AC #1/#2: pdfplumber steht in [project.dependencies], nicht mehr im Extra."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    names = {Requirement(d).name.lower() for d in deps}
    assert "pdfplumber" in names, (
        "pdfplumber fehlt in pyproject.toml [project.dependencies] (Issue #723)."
    )


def test_tables_extra_is_absent_or_empty():
    """AC #2: Das tables-Extra entfaellt oder bleibt ein leerer Alias.

    Ein leerer Alias erlaubt `uv sync --extra tables` aus Alt-Anleitungen
    weiterhin als No-op (exit 0), statt mit "extra tables is not defined" zu
    scheitern — die im Plan gewaehlte, guenstigere Variante fuer AC2.
    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    optional = data["project"].get("optional-dependencies", {})
    if "tables" in optional:
        assert optional["tables"] == [], (
            "pyproject.toml [project.optional-dependencies].tables ist weder "
            "abwesend noch leer — pdfplumber duerfte hier nicht mehr doppelt "
            "auftauchen (Issue #723)."
        )


def test_pdfplumber_importable():
    """AC #1: pdfplumber ist im aktiven Environment tatsaechlich installiert.

    `uv sync --extra dev` (ohne `--extra tables`) muss das Paket liefern —
    genau das ist der Kern von Issue #723.
    """
    import pdfplumber  # noqa: F401 — reiner Importierbarkeits-Check


def test_ci_workflow_no_longer_has_redundant_tables_extra_sync():
    """Der frueher noetige zweite `uv sync --extra tables`-Schritt entfaellt in CI.

    `uv sync --extra dev` installiert pdfplumber jetzt automatisch mit; ein
    zweiter, expliziter Sync fuer das (jetzt leere) tables-Extra waere
    redundant.
    """
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "--extra tables" not in workflow, (
        "ci.yml referenziert noch das tables-Extra — nach Issue #723 ist "
        "pdfplumber schon per --extra dev installiert."
    )


def test_limits_doc_no_longer_frames_pdfplumber_as_optional_extra():
    """AC #4: docs/guide/limits.md beschreibt die Grenze nicht mehr als Paketierungslueke."""
    limits = (REPO_ROOT / "docs" / "guide" / "limits.md").read_text(encoding="utf-8")
    assert "extra tables" not in limits, (
        "docs/guide/limits.md nennt noch 'uv sync --extra tables' — pdfplumber "
        "ist seit Issue #723 Pflicht-Dependency, die Grenze ist jetzt strukturell."
    )


def test_installation_doc_names_the_added_scope():
    """AC #5: Der zusaetzliche Installationsumfang ist in der Setup-Doku benannt."""
    installation = (REPO_ROOT / "docs" / "guide" / "installation.md").read_text(encoding="utf-8")
    assert "pdfplumber" in installation, (
        "docs/guide/installation.md nennt pdfplumber nicht — der neue "
        "Installationsumfang (Issue #723, AC5) ist damit nicht dokumentiert."
    )
