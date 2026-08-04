"""Guard fuer das Eval-Strategiedokument (Issue #390).

``docs/evals/STRATEGY.md`` legt fuer JEDE Komponente unter ``evals/`` offen,
woran sie tatsaechlich gemessen wird. Ohne diesen Guard waere das Dokument
Prosa, die beim naechsten neuen Eval-Verzeichnis still veraltet — genau die
Sorte stillschweigender Luecke, die Issue #390 beseitigt.

Geprueft wird deshalb die Tabelle gegen das Dateisystem, nicht nur ihre Existenz:
Vollstaendigkeit in beide Richtungen, Status-Vokabular, Pflicht-Begruendung,
Existenz der genannten Runner — plus, dass kein neuer Runner API-Budget kostet.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.evals.eval_runner import claude_cli_available

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STRATEGY_PATH = REPO_ROOT / "docs" / "evals" / "STRATEGY.md"
EVALS_ROOT = REPO_ROOT / "evals"

VALID_STATUS = {"metric", "structural", "removed"}
MIN_REASON_CHARS = 20


def eval_dirs() -> set[str]:
    """Alle Komponenten-Verzeichnisse unter evals/ (Datenbasis der Tabelle)."""
    return {
        p.name for p in EVALS_ROOT.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
    }


def _strategy_text() -> str:
    assert STRATEGY_PATH.exists(), f"Strategiedokument fehlt: {STRATEGY_PATH} (Issue #390, AC1)."
    return STRATEGY_PATH.read_text(encoding="utf-8")


def parse_rows(text: str) -> dict[str, dict[str, str]]:
    """Parst die Statustabelle: ``| `komponente` | status | pfad | begruendung |``.

    Bewusst strikt — eine Zeile, die das Format verletzt, wird nicht erkannt und
    faellt damit im Vollstaendigkeits-Test auf, statt still durchzurutschen.
    """
    row_re = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([a-z]+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", re.M)
    rows: dict[str, dict[str, str]] = {}
    for name, status, path, reason in row_re.findall(text):
        assert name not in rows, f"Doppelte Tabellenzeile fuer '{name}' in STRATEGY.md."
        rows[name] = {"status": status, "path": path, "reason": reason}
    return rows


@pytest.fixture(scope="module")
def strategy_text() -> str:
    return _strategy_text()


@pytest.fixture(scope="module")
def rows(strategy_text: str) -> dict[str, dict[str, str]]:
    return parse_rows(strategy_text)


# ---------------------------------------------------------------------------
# AC1: Fuer jede evals/-Komponente ist ein Zustand benannt.
# ---------------------------------------------------------------------------


def test_every_eval_dir_has_exactly_one_status(rows):
    """Set-Gleichheit: evals/-Verzeichnisse <-> Tabellenzeilen (ohne ``removed``)."""
    documented = {name for name, row in rows.items() if row["status"] != "removed"}
    on_disk = eval_dirs()
    missing = on_disk - documented
    stale = documented - on_disk
    assert not missing, (
        f"Ohne Eintrag in docs/evals/STRATEGY.md: {sorted(missing)} — jede "
        f"evals/-Komponente braucht einen benannten Zustand (Issue #390, AC1)."
    )
    assert not stale, (
        f"STRATEGY.md nennt Komponenten, die es unter evals/ nicht (mehr) gibt: "
        f"{sorted(stale)}. Status auf 'removed' setzen oder Zeile streichen."
    )


def test_all_37_components_are_covered(rows):
    """Die Tabelle deckt den vollstaendigen Bestand ab — keine stille Teilmenge."""
    active = [name for name, row in rows.items() if row["status"] != "removed"]
    assert len(active) == len(eval_dirs()), (
        f"{len(active)} aktive Tabellenzeilen vs. {len(eval_dirs())} evals/-Verzeichnisse."
    )


def test_status_vocabulary_is_closed(rows):
    """Nur ``metric`` / ``structural`` / ``removed`` — kein schwammiges Zwischenwort."""
    for name, row in rows.items():
        assert row["status"] in VALID_STATUS, (
            f"{name}: ungueltiger Status {row['status']!r}; erlaubt: {sorted(VALID_STATUS)}."
        )


def test_structural_rows_carry_a_reason(rows):
    """``structural`` ist nur mit Begruendung zulaessig — sonst ist es ein stiller Schema-Check."""
    for name, row in rows.items():
        if row["status"] != "structural":
            continue
        assert len(row["reason"]) >= MIN_REASON_CHARS, (
            f"{name}: Status 'structural' ohne belastbare Begruendung "
            f"(>= {MIN_REASON_CHARS} Zeichen), gefunden: {row['reason']!r}."
        )


def test_metric_rows_point_to_existing_runner(rows):
    """``metric`` verlangt einen real existierenden Ausfuehrungspfad im Repo."""
    for name, row in rows.items():
        if row["status"] != "metric":
            continue
        referenced = re.findall(r"`([^`]+)`", row["path"])
        assert referenced, f"{name}: Status 'metric' ohne genannten Ausfuehrungspfad."
        for rel in referenced:
            assert (REPO_ROOT / rel).exists(), (
                f"{name}: genannter Ausfuehrungspfad '{rel}' existiert nicht."
            )


def test_removed_components_are_absent_from_disk(rows):
    """Als ``removed`` gefuehrte Komponenten duerfen nicht mehr unter evals/ liegen."""
    for name, row in rows.items():
        if row["status"] != "removed":
            continue
        assert not (EVALS_ROOT / name).exists(), (
            f"{name}: als 'removed' dokumentiert, liegt aber noch unter evals/."
        )


def test_no_eval_dir_lacks_both_metric_and_reason(rows):
    """Querschnitt: keine Komponente ohne Ausfuehrungspfad UND ohne Begruendung."""
    for name in sorted(eval_dirs()):
        row = rows[name]
        has_path = bool(re.findall(r"`([^`]+)`", row["path"]))
        has_reason = len(row["reason"]) >= MIN_REASON_CHARS
        assert has_path or has_reason, (
            f"{name}: weder Ausfuehrungspfad noch Begruendung — genau die Luecke, "
            f"die Issue #390 schliesst."
        )


# ---------------------------------------------------------------------------
# AC2: Die beiden vormals toten Definitionen haben einen echten Runner.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("component", ["auto-download", "humanizer-de-pipeline"])
def test_formerly_dead_definitions_are_wired_or_removed(component, rows):
    """auto-download und humanizer-de-pipeline: entweder ``metric`` oder ``removed``."""
    row = rows[component]
    assert row["status"] in {"metric", "removed"}, (
        f"{component}: Status {row['status']!r} — AC2 verlangt einen echten "
        f"Ausfuehrungspfad ('metric') oder die Entfernung ('removed')."
    )


# ---------------------------------------------------------------------------
# AC3 / AC4: Pflichtabschnitte des Dokuments.
# ---------------------------------------------------------------------------


def test_strategy_documents_issue_55(strategy_text):
    """AC3: Das Dokument haelt fest, dass Alt-Issue #55 von #390 absorbiert wurde."""
    assert "## Alt-Issue #55" in strategy_text, (
        "STRATEGY.md braucht einen Abschnitt '## Alt-Issue #55' (Issue #390, AC3)."
    )
    section = strategy_text.split("## Alt-Issue #55", 1)[1].split("\n## ", 1)[0]
    assert "#390" in section, "Der #55-Abschnitt muss auf #390 verweisen."
    assert "geschlossen" in section.lower(), "Der #55-Abschnitt muss den Schliess-Status benennen."


def test_strategy_names_api_budget_as_operator_decision(strategy_text):
    """AC4: Budgetbedarf ist beziffert und ausdruecklich als Operator-Entscheid markiert."""
    assert "## API-Budget" in strategy_text, (
        "STRATEGY.md braucht einen Abschnitt '## API-Budget' (Issue #390, AC4)."
    )
    section = strategy_text.split("## API-Budget", 1)[1].split("\n## ", 1)[0]
    assert "Operator" in section, (
        "Der API-Budget-Abschnitt muss die Entscheidung ausdruecklich dem Operator zuordnen."
    )
    assert re.search(r"\d", section), (
        "Der API-Budget-Abschnitt muss eine Groessenordnung beziffern (Calls/Kosten)."
    )
    assert "ANTHROPIC_API_KEY" in section, (
        "Der API-Budget-Abschnitt muss benennen, woran die realen Laeufe haengen."
    )


def test_strategy_states_the_skip_count_honestly(strategy_text):
    """Ehrlichkeitsfalle: ``structural`` darf nicht als 'gruen' verkauft werden."""
    assert "skip" in strategy_text.lower(), (
        "STRATEGY.md muss offenlegen, dass die API-gateten Evals weiterhin skippen."
    )


# ---------------------------------------------------------------------------
# Issue #619: Die Bilanzzeile und die Skip-Zahl sind Prosa ueber pruefbare
# Zahlen — der Guard muss sie gegen die Tabelle bzw. einen echten Lauf halten,
# statt sie nur auf das Wort "skip" zu pruefen (das faengt keine veraltete
# Zahl).
# ---------------------------------------------------------------------------


def _parse_balance_line(text: str) -> tuple[int, int, int]:
    match = re.search(
        r"\*\*Bilanz:\*\*\s*(\d+)\s*×\s*`metric`,\s*(\d+)\s*×\s*`structural`,"
        r"\s*(\d+)\s*×\s*`removed`",
        text,
    )
    assert match, "STRATEGY.md: Bilanzzeile nicht im erwarteten Format gefunden (Issue #619)."
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def test_balance_line_matches_table_counts(strategy_text, rows):
    """Die Bilanzzeile muss der tatsaechlichen Tabelle entsprechen (Issue #619)."""
    doc_metric, doc_structural, doc_removed = _parse_balance_line(strategy_text)
    counts = Counter(row["status"] for row in rows.values())
    assert doc_metric == counts.get("metric", 0), (
        f"Bilanzzeile nennt {doc_metric} × metric, Tabelle hat "
        f"{counts.get('metric', 0)} (Issue #619)."
    )
    assert doc_structural == counts.get("structural", 0), (
        f"Bilanzzeile nennt {doc_structural} × structural, Tabelle hat "
        f"{counts.get('structural', 0)} (Issue #619)."
    )
    assert doc_removed == counts.get("removed", 0), (
        f"Bilanzzeile nennt {doc_removed} × removed, Tabelle hat "
        f"{counts.get('removed', 0)} (Issue #619)."
    )


def _current_skip_sentence(text: str) -> str:
    marker = "Heutiger Stand"
    idx = text.find(marker)
    assert idx != -1, (
        "STRATEGY.md braucht einen als 'Heutiger Stand' markierten Satz mit der "
        "aktuellen passed/skipped-Zahl (Issue #619)."
    )
    return text[idx : idx + 400]


def test_skip_count_matches_real_pytest_run(strategy_text):
    """Die dokumentierte Skip-Zahl muss zu einem echten Lauf passen (Issue #619)."""
    if os.environ.get("ANTHROPIC_API_KEY") or claude_cli_available():
        pytest.skip(
            "Mit gesetztem ANTHROPIC_API_KEY oder installierter claude-CLI (Issue "
            "#631, CLI-Rueckfallpfad in eval_runner.call_claude) laufen deutlich "
            "weniger Tests still durch/echt statt zu skippen; die dokumentierte "
            "Zahl gilt nur fuer den Lauf ohne beides."
        )
    sentence = _current_skip_sentence(strategy_text)
    match = re.search(r"(\d+)\s*passed,\s*(\d+)\s*skipped", sentence)
    assert match, (
        f"Keine 'N passed, M skipped'-Angabe im 'Heutiger Stand'-Satz gefunden: {sentence!r}"
    )
    doc_passed, doc_skipped = int(match.group(1)), int(match.group(2))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/evals/",
            "--deselect",
            "tests/evals/test_eval_strategy.py::test_skip_count_matches_real_pytest_run",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    summary_match = re.search(r"(\d+) passed(?:, (\d+) skipped)?", result.stdout)
    assert summary_match, f"Konnte Summary-Zeile nicht parsen:\n{result.stdout}"
    inner_passed = int(summary_match.group(1))
    inner_skipped = int(summary_match.group(2) or 0)

    assert inner_passed + 1 == doc_passed, (
        f"Dokumentiert: {doc_passed} passed. Realer Lauf (ohne diesen Test): "
        f"{inner_passed} passed (+1 fuer diesen Test = {inner_passed + 1}). Issue #619."
    )
    assert inner_skipped == doc_skipped, (
        f"Dokumentiert: {doc_skipped} skipped. Realer Lauf: {inner_skipped} skipped (Issue #619)."
    )


# ---------------------------------------------------------------------------
# AC4: Kein neuer Runner verbrennt Budget.
# ---------------------------------------------------------------------------


def test_no_eval_runner_requires_api_key():
    """Alle Runner unter evals/ laufen offline — kein anthropic-Client, kein API-Key."""
    for runner in sorted(EVALS_ROOT.glob("*/runner.py")):
        source = runner.read_text(encoding="utf-8")
        assert "anthropic" not in source, (
            f"{runner.relative_to(REPO_ROOT)} wuerde API-Budget verbrauchen (Issue #390, AC4)."
        )
        assert "require_api_key" not in source, (
            f"{runner.relative_to(REPO_ROOT)} haengt an require_api_key() und wuerde skippen."
        )
