"""Akzeptanz-Guards fuer Issue #453 — Manifest- und Doku-Ehrlichkeit.

Jeder Test bildet ein Akzeptanzkriterium aus dem Issue ab:

AC1  `plugin.json` / `marketplace.json` nennen nur Quellen und Zahlen, die im
     Code belegbar sind (API-Quellen-Zahl gegen `scripts/search.py::MODULES`,
     Google Scholar nicht als API-Quelle mitgezaehlt, Book-Fetcher-Subagenten-
     Zahl gegen `agents/book-fetcher.md`-Frontmatter).
AC2  Derselbe Test schlaegt fehl, sobald eine dieser Zahlen von der
     tatsaechlichen Registrierung abweicht (parametrisiert ueber beide
     Manifeste).
AC3  Die Agent-Uebersicht (`docs/reference/agents.md`) weist pro Agent aus,
     ob er automatisch dispatcht wird oder nur manuell aufrufbar ist.
AC4  Kein Dokument (inkl. CHANGELOG.md) nennt mehr das nie existierende
     `--migrate-v5`-Flag.
"""

import json
import re
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
MANIFEST_PATHS = (PLUGIN_JSON, MARKETPLACE_JSON)

BOOK_FETCHER_AGENT = REPO_ROOT / "agents" / "book-fetcher.md"
SEARCH_SCRIPT = REPO_ROOT / "scripts" / "search.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _all_description_strings(data: object) -> list[str]:
    """Sammelt alle Werte unter dem Schluessel 'description' rekursiv."""
    found: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "description" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_all_description_strings(value))
    elif isinstance(data, list):
        for item in data:
            found.extend(_all_description_strings(item))
    return found


def _api_module_count() -> int:
    """Anzahl der in scripts/search.py registrierten API-Suchmodule."""
    src = _read(SEARCH_SCRIPT)
    m = re.search(r"^MODULES\s*[:=][^{]*\{(.*?)^\}", src, re.S | re.M)
    assert m, "MODULES-Dispatch in scripts/search.py nicht gefunden"
    return len(re.findall(r'^\s*"([a-z_]+)":', m.group(1), re.M))


def _book_fetcher_subagent_count() -> int:
    """Anzahl dispatchbarer Fetcher-Subagenten in agents/book-fetcher.md.

    `auth-helper` zaehlt nicht mit -- er ist kein eigener Fetcher-Versuch,
    sondern ein Login-Helfer, den book-fetcher bei Bedarf dazwischenschaltet.
    """
    text = _read(BOOK_FETCHER_AGENT)
    frontmatter = text.split("---", 2)[1]
    agents = re.findall(r'"Agent\(([a-z-]+)\)"', frontmatter)
    assert agents, "Keine Agent(...)-Tools im book-fetcher-Frontmatter gefunden"
    return len([a for a in agents if a != "auth-helper"])


# ---------------------------------------------------------------------------
# AC1 + AC2 -- Zahlen in den Manifesten sind belegbar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", MANIFEST_PATHS, ids=lambda p: p.name)
def test_manifest_is_valid_json(path: Path) -> None:
    assert isinstance(json.loads(_read(path)), dict)


@pytest.mark.parametrize("path", MANIFEST_PATHS, ids=lambda p: p.name)
def test_manifest_api_source_count_matches_modules_registry(path: Path) -> None:
    """Wird eine 'X API-Quellen'-Zahl behauptet, muss sie zu MODULES passen."""
    actual = _api_module_count()
    data = json.loads(_read(path))
    wrong = []
    for desc in _all_description_strings(data):
        for m in re.finditer(r"(\d+)\s+API-Quellen\b", desc):
            if int(m.group(1)) != actual:
                wrong.append(f"{m.group(0)!r} != {actual}")
    assert not wrong, f"{path.name}: API-Quellen-Zahl weicht vom Code ab: {wrong}"


@pytest.mark.parametrize("path", MANIFEST_PATHS, ids=lambda p: p.name)
def test_manifest_google_scholar_not_counted_as_api_source(path: Path) -> None:
    """Google Scholar ist ein Browser-Modul, keine API-Quelle (#453)."""
    data = json.loads(_read(path))
    offenders = []
    for desc in _all_description_strings(data):
        for sentence in desc.split("."):
            if "API-Quellen" in sentence and "Google Scholar" in sentence:
                offenders.append(sentence.strip())
    assert not offenders, (
        f"{path.name}: Google Scholar wird als API-Quelle mitgezaehlt: {offenders}"
    )


@pytest.mark.parametrize("path", MANIFEST_PATHS, ids=lambda p: p.name)
def test_manifest_book_fetcher_subagent_count_matches_frontmatter(path: Path) -> None:
    """Wird eine Fetcher-Subagenten-Zahl fuer den Book Fetcher behauptet, muss
    sie zur tools:-Frontmatter von agents/book-fetcher.md passen (#453: die
    vorherige '8-Tier'-Behauptung hatte keinen Code-Bezug)."""
    actual = _book_fetcher_subagent_count()
    data = json.loads(_read(path))
    wrong = []
    for desc in _all_description_strings(data):
        for m in re.finditer(r"Book Fetcher \((\d+)\s+Fetcher-Subagenten", desc):
            if int(m.group(1)) != actual:
                wrong.append(f"{m.group(0)!r} != {actual}")
    assert not wrong, f"{path.name}: Book-Fetcher-Subagentenzahl weicht ab: {wrong}"


def test_manifest_no_dangling_tier_pipeline_claim() -> None:
    """Die alte '8-Tier-Pipeline'-Formulierung (ohne Code-Bezug) darf nicht

    zurueckkehren -- weder mit der alten noch mit einer neuen Zahl, weil
    'Tier' im Repo bereits fuer ein anderes Feature reserviert ist
    (scripts/pdf.py::resolve_pdf_url, generische OA-PDF-Aufloesung)."""
    offenders = []
    for path in MANIFEST_PATHS:
        data = json.loads(_read(path))
        for desc in _all_description_strings(data):
            if re.search(r"\d+-Tier-Pipeline", desc):
                offenders.append(f"{path.name}: {desc!r}")
    assert not offenders, f"Tier-Pipeline-Behauptung ohne Code-Bezug: {offenders}"


# ---------------------------------------------------------------------------
# AC3 -- Dispatch-Spalte in docs/reference/agents.md
# ---------------------------------------------------------------------------


def _agent_dispatch_values(text: str) -> dict[str, str]:
    """Liest pro Markdown-Tabellenzeile (Agent, Dispatch) aus agents.md."""
    result: dict[str, str] = {}
    header_idx: int | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        if set("".join(cells)) <= {"-", ":", ""}:
            continue  # Trennzeile
        # Kopfzeile: erste Zelle ohne Backticks. Datenzeilen fuehren immer einen
        # `code`-Bezeichner. Seit #840 steht in agents.md eine zweite Tabelle
        # (Site-Configs des Ultimate Fetchers) ohne Dispatch-Spalte -- ohne
        # diesen Reset zoege sie den Index der vorherigen Tabelle mit.
        if not cells[0].startswith("`"):
            header_idx = cells.index("Dispatch") if "Dispatch" in cells else None
            continue
        if header_idx is None or header_idx >= len(cells):
            continue
        name = cells[0].strip("`")
        result[name] = cells[header_idx]
    return result


def test_agents_doc_has_dispatch_column() -> None:
    text = _read(D.AGENTS_DOC)
    assert "Dispatch" in text, "docs/reference/agents.md hat keine Dispatch-Spalte."


def test_agents_doc_dispatch_column_uses_allowed_values() -> None:
    """Jeder Dispatch-Wert ist 'manuell' oder beginnt mit 'automatisch'."""
    dispatch = _agent_dispatch_values(_read(D.AGENTS_DOC))
    assert dispatch, "Keine Dispatch-Werte in agents.md gefunden."
    bad = {
        name: value
        for name, value in dispatch.items()
        if value != "manuell" and not value.startswith("automatisch")
    }
    assert not bad, f"Unzulaessige Dispatch-Werte: {bad}"


def test_agents_doc_dispatch_column_covers_every_agent_file() -> None:
    dispatch = _agent_dispatch_values(_read(D.AGENTS_DOC))
    agent_files = {p.stem for p in (REPO_ROOT / "agents").glob("*.md")}
    missing = agent_files - set(dispatch)
    assert not missing, f"agents.md fehlt eine Dispatch-Zeile fuer: {sorted(missing)}"


def test_figure_verifier_has_no_automatic_caller_in_code() -> None:
    """Befund #453: `chapter-writer` ruft `figure-verifier` nirgends auf --

    die Agent-Tabelle darf figure-verifier daher nicht als automatisch von
    chapter-writer dispatcht ausweisen."""
    callers = [
        p
        for p in (
            *(REPO_ROOT / "skills").rglob("SKILL.md"),
            *(REPO_ROOT / "commands").glob("*.md"),
        )
        if "figure-verifier" in _read(p)
    ]
    assert not callers, (
        f"figure-verifier hat jetzt einen echten Aufrufer ({callers}) -- "
        "agents.md und dieser Test muessen auf 'automatisch' aktualisiert werden."
    )
    dispatch = _agent_dispatch_values(_read(D.AGENTS_DOC))
    assert dispatch.get("figure-verifier") == "manuell", (
        "figure-verifier hat keinen Aufrufer im Code -- agents.md muss 'manuell' zeigen."
    )


def test_risk_of_bias_caller_matches_parallel_screening_not_prisma_flow() -> None:
    """Befund #453: risk-of-bias wird von `parallel-screening` dispatcht

    (Task-Aufruf, SKILL.md-Zeile ~168ff.), nicht von `prisma-flow` -- prisma-flow
    liest nur die resultierenden Zaehler."""
    skill_text = _read(REPO_ROOT / "skills" / "parallel-screening" / "SKILL.md")
    assert "risk-of-bias" in skill_text, (
        "Vorbedingung geaendert: parallel-screening ruft risk-of-bias nicht mehr auf."
    )
    text = _read(D.AGENTS_DOC)
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("| `risk-of-bias`")]
    assert rows, "Keine Tabellenzeile fuer risk-of-bias in agents.md gefunden."
    assert "parallel-screening" in rows[0], (
        f"agents.md nennt fuer risk-of-bias nicht parallel-screening als Aufrufer: {rows[0]!r}"
    )
    assert "prisma-flow" not in rows[0], (
        f"agents.md nennt fuer risk-of-bias noch faelschlich prisma-flow: {rows[0]!r}"
    )


# ---------------------------------------------------------------------------
# AC4 -- kein totes --migrate-v5-Flag mehr
# ---------------------------------------------------------------------------


def test_no_migrate_v5_flag_anywhere() -> None:
    """`--migrate-v5` existiert in keinem Command (verifiziert: commands/setup.md

    kennt es weder in argument-hint noch im Body). Guard ueber doc_surface()
    UND CHANGELOG.md (nicht Teil von doc_surface(), siehe tests/helpers/docs.py)."""
    offenders = []
    for path in (*D.doc_surface(), CHANGELOG):
        if not path.exists():
            continue
        text = _read(path)
        for i, line in enumerate(text.splitlines(), 1):
            if "--migrate-v5" in line:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}")
    assert not offenders, f"Tote Referenz auf --migrate-v5 gefunden: {offenders}"
