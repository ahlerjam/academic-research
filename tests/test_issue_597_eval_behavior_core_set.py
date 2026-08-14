"""Regressionstest fuer Issue #597 -- Verhaltens-Evals woechentlich ueber ein
Kern-Set laufen lassen, statt den Vollauf nur manuell auslösbar zu belassen.

Deckt die sechs Akzeptanzkriterien strukturell ab (kein echter CI-Lauf, kein
API-Call noetig):

1. ``eval-behavior.yml`` hat neben ``workflow_dispatch`` einen woechentlichen
   ``schedule``-Trigger.
2. Der geplante Lauf fuehrt genau das Kern-Set aus (``-m eval_core_set``),
   nicht alle Verhaltens-Evals; das Kern-Set steht an einer einzigen Stelle
   (siehe tests/evals/test_eval_strategy.py::test_eval_core_set_matches_documented_files
   fuer den Datei-Abgleich).
3. Ein manueller Lauf kann weiterhin die volle Menge anfordern.
4. Ein Fehlschlag des geplanten Laufs erzeugt ein Issue mit der gerissenen
   Suite im Titel; ein zweiter Fehlschlag derselben Suite legt kein
   Duplikat an.
5. Die bestehende Secret-Vorbedingung bleibt ungated vor jedem Trigger-Typ.
6. ``docs/evals/STRATEGY.md`` nennt Rhythmus und Umfang (separater Guard in
   tests/evals/test_eval_strategy.py).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "eval-behavior.yml"
REPORT_SCRIPT = ROOT / "scripts" / "ci" / "report_eval_behavior_failure.sh"
LIB_SCRIPT = ROOT / "scripts" / "ci" / "lib" / "report_pytest_failure.sh"


def _load_workflow() -> dict:
    assert WORKFLOW.is_file(), f"{WORKFLOW} fehlt."
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _trigger(data: dict) -> dict:
    # PyYAML normalisiert den bareword-Key "on" zu bool True -- konsistent mit
    # tests/test_issue_470_eval_behavior_workflow.py und
    # tests/test_issue_603_live_fetch_weekly_workflow.py.
    return data.get("on") or data.get(True, {})


def _job(data: dict) -> dict:
    jobs = data.get("jobs", {})
    assert jobs, "eval-behavior.yml hat keine jobs."
    return next(iter(jobs.values()))


def _steps() -> list[dict]:
    return _job(_load_workflow()).get("steps", [])


def _pytest_step() -> dict:
    for step in _steps():
        if "tests/evals/" in str(step.get("run", "")):
            return step
    raise AssertionError("Kein Step ruft pytest gegen tests/evals/ auf.")


# --------------------------------------------------------------------------- #
# AC1 -- schedule-Trigger neben workflow_dispatch, woechentlich
# --------------------------------------------------------------------------- #


def test_workflow_has_weekly_schedule_trigger_alongside_workflow_dispatch():
    """AC1: mindestens EIN woechentlicher Cron neben workflow_dispatch.

    Seit Issue #848 kann ein zweiter, taeglicher Smoke-Cron danebenstehen
    (dow == '*', s. test_workflow_has_daily_smoke_schedule_trigger unten) --
    dieser Guard sucht darum gezielt nach einem woechentlichen Eintrag
    (fixer Wochentag) statt anzunehmen, dass genau ein Cron existiert."""
    trigger = _trigger(_load_workflow())
    assert "workflow_dispatch" in trigger, (
        "eval-behavior.yml muss workflow_dispatch behalten (Issue #597, AC1/AC3)."
    )
    assert "schedule" in trigger, "eval-behavior.yml braucht einen schedule-Trigger (AC1)."
    crons = [entry.get("cron") for entry in trigger["schedule"]]
    assert crons, "eval-behavior.yml braucht mindestens einen Cron-Eintrag (Issue #597 AC1)."
    weekly_crons = []
    for cron in crons:
        fields = cron.split()
        assert len(fields) == 5, f"Kein gueltiger 5-Felder-Cron-Ausdruck: {cron!r}."
        minute, hour, dom, month, dow = fields
        assert minute != "*" and hour != "*", f"Uhrzeit muss fixiert sein: {cron!r}."
        if dow != "*":
            weekly_crons.append(cron)
    assert len(weekly_crons) == 1, (
        f"Erwartet genau einen woechentlichen Cron-Eintrag (fixer Wochentag), gefunden: "
        f"{weekly_crons!r} von insgesamt {crons!r} (Issue #597 AC1)."
    )


def test_workflow_has_daily_smoke_schedule_trigger():
    """Issue #848 AC1: zusaetzlich zum woechentlichen Cron ein taeglicher
    Smoke-Cron (dow == '*', jeden Tag)."""
    trigger = _trigger(_load_workflow())
    crons = [entry.get("cron") for entry in trigger.get("schedule", [])]
    daily_crons = [c for c in crons if c.split()[4] == "*"]
    assert len(daily_crons) == 1, (
        f"Erwartet genau einen taeglichen Cron-Eintrag (Wochentag '*'), gefunden: "
        f"{daily_crons!r} von insgesamt {crons!r} (Issue #848 AC1)."
    )


# --------------------------------------------------------------------------- #
# AC2 -- geplanter Lauf fuehrt exakt das Kern-Set aus
# --------------------------------------------------------------------------- #


def test_scheduled_run_uses_eval_core_set_marker():
    step = _pytest_step()
    run_text = str(step.get("run", ""))
    assert "-m eval_core_set" in run_text, (
        "Kein pytest-Aufruf mit '-m eval_core_set' im Workflow -- der geplante "
        "Lauf muss das Kern-Set ueber den Marker auswaehlen (Issue #597, AC2)."
    )
    env = step.get("env", {}) or {}
    assert any("event_name" in str(v) and "schedule" in str(v) for v in env.values()), (
        "Der pytest-Step muss ueber github.event_name zwischen geplantem und "
        "manuellem Lauf unterscheiden (AC2/AC3)."
    )


def test_eval_core_set_marker_is_registered_in_pyproject():
    """AC2: das Kern-Set steht an EINER Stelle -- dem registrierten Marker."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "eval_core_set" in pyproject, (
        "pyproject.toml registriert den Marker eval_core_set nicht (Issue #597, AC2)."
    )


# --------------------------------------------------------------------------- #
# AC3 -- manueller Lauf kann weiterhin die volle Menge anfordern
# --------------------------------------------------------------------------- #


def test_manual_dispatch_path_retains_full_or_filtered_run():
    """Der Nicht-schedule-Zweig im pytest-Step darf NICHT auf -m eval_core_set
    beschraenkt sein -- sonst koennte workflow_dispatch nie mehr die volle
    Menge anfordern (Issue #597, AC3)."""
    run_text = str(_pytest_step().get("run", ""))
    # Es muss einen Zweig geben, der ohne -m eval_core_set pytest auf
    # tests/evals/ aufruft (der bestehende FILTER/vollstaendige Pfad).
    lines_without_marker = [
        line
        for line in run_text.splitlines()
        if "pytest tests/evals/" in line and "-m eval_core_set" not in line
    ]
    assert lines_without_marker, (
        "Kein pytest-Aufruf ohne '-m eval_core_set' gefunden -- der manuelle Lauf "
        "kann die volle Menge nicht mehr anfordern (Issue #597, AC3)."
    )


def test_component_input_still_documented_for_manual_dispatch():
    data = _load_workflow()
    trigger = _trigger(data)
    inputs = trigger.get("workflow_dispatch", {}).get("inputs", {})
    assert "component" in inputs, (
        "workflow_dispatch verliert den component-Filter-Input (Issue #597, AC3)."
    )


# --------------------------------------------------------------------------- #
# AC4 -- Fehlschlag des geplanten Laufs erzeugt Issue, kein Duplikat
# --------------------------------------------------------------------------- #


def test_workflow_calls_report_script_only_on_scheduled_failure():
    report_steps = [
        s for s in _steps() if "report_eval_behavior_failure.sh" in str(s.get("run", ""))
    ]
    assert report_steps, "Kein Step ruft scripts/ci/report_eval_behavior_failure.sh auf."
    conditions = [str(s.get("if", "")) for s in report_steps]
    assert any("failure()" in c for c in conditions), (
        "Der Report-Step muss nur bei Fehlschlag laufen (if: failure())."
    )
    assert any("schedule" in c for c in conditions), (
        "Der Report-Step soll nur den geplanten Lauf melden, nicht jeden manuellen "
        "workflow_dispatch-Fehlschlag (Issue #597, AC4)."
    )


def test_workflow_permissions_include_issues_write():
    data = _load_workflow()
    assert data.get("permissions", {}).get("issues") == "write", (
        "eval-behavior.yml braucht 'issues: write', sonst kann der Report-Step "
        "kein Issue anlegen (Issue #597, AC4)."
    )


def test_report_script_exists_and_is_executable():
    assert REPORT_SCRIPT.is_file(), f"{REPORT_SCRIPT} fehlt (Issue #597, AC4)."
    assert os.access(REPORT_SCRIPT, os.X_OK), f"{REPORT_SCRIPT} ist nicht ausfuehrbar."
    assert LIB_SCRIPT.is_file(), f"{LIB_SCRIPT} fehlt (gemeinsame Report-Bibliothek)."


def test_report_script_dedup_and_creation_behavior():
    """Fuehrt den dedizierten Shell-Harness aus (Stub-gh, echte JUnit-Fixtures) --
    prueft Neu-Anlage, Dedup und Nicht-Buendelung mehrerer Faelle (AC4)."""
    harness = ROOT / "scripts" / "dev" / "test-report-eval-behavior-failure.sh"
    assert harness.is_file(), f"{harness} fehlt."
    result = subprocess.run(
        ["bash", str(harness)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Harness fuer report_eval_behavior_failure.sh schlaegt fehl:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# --------------------------------------------------------------------------- #
# AC5 -- Secret-Vorbedingung bleibt ungated vor jedem Trigger-Typ
# --------------------------------------------------------------------------- #


def test_precondition_step_is_not_gated_behind_a_trigger_type():
    for step in _steps():
        text = str(step.get("run", ""))
        if "::error::" in text and "exit 1" in text:
            assert "if" not in step, (
                f"Der Vorbedingungs-Step ({step.get('name')!r}) darf nicht hinter "
                "ein if: gestellt sein -- sonst greift AC5 nicht fuer jeden "
                "Trigger-Typ (Issue #597, AC5)."
            )
            return
    raise AssertionError("Kein Vorbedingungs-Step mit ::error::/exit 1 gefunden.")
