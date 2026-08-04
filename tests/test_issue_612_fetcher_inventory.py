"""Fetcher-Inventar und Live-Test-Kennzeichnung (Issue #612, Teil A).

Die Vorbedingung des Issues ("mehrere Live-Laeufe liegen vor") ist noch nicht
erfuellt (``.github/workflows/live-fetch-weekly.yml`` hat 0 Runs, siehe
Plan-Kommentar). Reparatur/Ausbau (AC1-3, AC6) bleiben deshalb explizit offen.
Dieser Test deckt den Teil, der ohne Live-Daten machbar ist (AC4): jeder
Site-Agent in der Buchbeschaffungs-Tabelle traegt eine Live-Test-Kennzeichnung,
und die Agent-Zaehlung in README/AGENTS.md ist konsistent (AC5-Vorarbeit aus
dem Plan-Kommentar).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
AGENTS_DOC = REPO_ROOT / "docs" / "reference" / "agents.md"
README = REPO_ROOT / "README.md"
LIVE_FETCH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-fetch-weekly.yml"

#: Site-Agents, die book-fetcher als Fallback-Kette anspielt (Issue #612
#: Gegenpruefung-Kommentar: 16 echte Fetcher + auth-helper als Grenzfall;
#: book-fetcher selbst ist Dispatcher, kein Fetcher gegen fremde Seiten).
FETCHER_AGENTS = {
    "tib-fetcher",
    "springer-book",
    "oapen-fetcher",
    "doabooks-fetcher",
    "degruyter",
    "nationallizenzen",
    "ebook-central",
    "cambridge-core",
    "oxford-academic",
    "jstor",
    "kvk-fetcher",
    "hathitrust-fetcher",
    "internetarchive-fetcher",
    "mdz-fetcher",
    "generic-fetcher",
    "scihub-fetcher",
}
AUTH_HELPER = "auth-helper"
DISPATCHER = "book-fetcher"

#: Erlaubte Live-Test-Kennzeichnungen (Issue #612 Plan-Kommentar, Schritt 2-4).
ALLOWED_STATUS_MARKERS = (
    "getestet (`test_issue_449_live_fetch.py`)",
    "getestet (`test_issue_450_live_fetch.py`)",
    "ungeprüft",
    "n/a — kein Volltext-Host",
    "n/a — Dispatcher",
    "bewusst ungetestet (Opt-in)",
)


def _buchbeschaffung_table_lines() -> list[str]:
    text = AGENTS_DOC.read_text(encoding="utf-8")
    section = text.split("## Buchbeschaffung", 1)[1].split("\n## ", 1)[0]
    return [
        line
        for line in section.splitlines()
        if line.startswith("| `") and not line.startswith("| Agent")
    ]


def test_every_fetcher_agent_file_exists_on_disk():
    """Das Inventar im Test muss zum tatsaechlichen agents/-Verzeichnis passen."""
    all_agents = {p.stem for p in AGENTS_DIR.glob("*.md")}
    inventory = FETCHER_AGENTS | {AUTH_HELPER, DISPATCHER}
    missing = inventory - all_agents
    assert not missing, f"Agents im Inventar fehlen als Datei: {sorted(missing)}"


def test_buchbeschaffung_table_lists_every_fetcher_exactly_once():
    lines = _buchbeschaffung_table_lines()
    table_agents = [line.split("|")[1].strip().strip("`") for line in lines]
    expected = FETCHER_AGENTS | {AUTH_HELPER, DISPATCHER}
    assert set(table_agents) == expected, (
        f"Buchbeschaffungs-Tabelle weicht vom Fetcher-Inventar ab: "
        f"fehlt={expected - set(table_agents)}, "
        f"zusaetzlich={set(table_agents) - expected}"
    )
    assert len(table_agents) == len(set(table_agents)), "Duplikate in der Tabelle"


def test_buchbeschaffung_table_has_live_test_column_with_allowed_value():
    lines = _buchbeschaffung_table_lines()
    assert lines, "Buchbeschaffungs-Tabelle ist leer oder wurde nicht gefunden"
    violations = []
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Agent | Model | Genutzt von | Dispatch | Aufgabe | Live-Test  -> 6 Spalten
        if len(cells) < 6:
            violations.append(f"keine Live-Test-Spalte: {line}")
            continue
        status = cells[5]
        if not any(status.startswith(marker) for marker in ALLOWED_STATUS_MARKERS):
            violations.append(f"unbekannter Live-Test-Status {status!r}: {line}")
    assert not violations, "\n".join(violations)


def test_scihub_fetcher_marked_deliberately_untested_not_plain_unproven():
    lines = _buchbeschaffung_table_lines()
    scihub_line = next(line for line in lines if line.startswith("| `scihub-fetcher`"))
    assert "bewusst ungetestet (Opt-in)" in scihub_line, (
        "scihub-fetcher braucht laut Scope-Out (#603) die Opt-in-Begruendung, "
        "nicht ein einfaches 'ungeprüft'"
    )


def test_kvk_fetcher_marked_not_applicable_not_plain_unproven():
    lines = _buchbeschaffung_table_lines()
    kvk_line = next(line for line in lines if line.startswith("| `kvk-fetcher`"))
    assert "n/a — kein Volltext-Host" in kvk_line, (
        "kvk-fetcher ist Meta-Suche ohne eigenen Volltext-Host (agents/kvk-fetcher.md) "
        "und kann das PDF-Ebenen-Falsch-Negativ aus Issue #603 nicht erzeugen"
    )


def test_readme_agent_count_matches_actual_agent_files():
    actual_count = len(list(AGENTS_DIR.glob("*.md")))
    text = README.read_text(encoding="utf-8")
    mentions = re.findall(r"\b(\d+)\s+(?:Agents|Subagents)\b", text)
    assert mentions, "README nennt keine Agent-Zaehlung"
    for mention in mentions:
        assert int(mention) == actual_count, (
            f"README nennt {mention} Agents/Subagents, tatsaechlich sind es "
            f"{actual_count} Dateien unter agents/*.md"
        )


def test_live_fetch_workflow_comment_uses_corrected_fetcher_count():
    text = LIVE_FETCH_WORKFLOW.read_text(encoding="utf-8")
    assert "17 der 28 Agents" not in text, (
        "Falsche Mengenangabe aus Issue #603 (book-fetcher faelschlich als Fetcher "
        "mitgezaehlt) noch im Kommentarblock des Workflows"
    )
    assert "16 Fetcher" in text and "auth-helper" in text
