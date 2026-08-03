"""Regressionstest fuer Issue #603 -- Live-Fetch-Tests woechentlich gegen die
echten Verlagsseiten laufen lassen statt sie dauerhaft im Opt-in-Skip zu
belassen.

Deckt die sechs Akzeptanzkriterien strukturell ab (kein echter CI-Lauf, kein
Netzzugriff auf fremde Verlags-/Archivseiten noetig):

1. Ein woechentlich geplanter Lauf fuehrt beide Live-Suiten mit gesetzten
   Env-Schaltern aus.
2. Der Lauf ist von ``ci.yml`` getrennt; ein Fehlschlag blockiert keinen PR.
3. ``RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK`` ist im geplanten Lauf nicht
   gesetzt.
4. Ein Fehlschlag erzeugt ein Issue, das den betroffenen Fetcher benennt;
   wiederholte Fehlschlaege desselben Fetchers erzeugen kein Duplikat.
5. Der Lauf ist manuell ausloesbar.
6. Ein lokaler ``pytest``-Lauf ohne Schalter ueberspringt die Live-Tests
   weiterhin wie bisher.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "live-fetch-weekly.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REPORT_SCRIPT = ROOT / "scripts" / "ci" / "report_live_fetch_failure.sh"


def _load_workflow() -> dict:
    assert WORKFLOW.is_file(), f"{WORKFLOW} fehlt (Issue #603)."
    # PyYAML normalisiert den bareword-Key "on" zu bool True -- konsistent
    # mit tests/test_issue_470_eval_behavior_workflow.py, hier ueber
    # _trigger() abgefangen.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _trigger(data: dict) -> dict:
    return data.get("on") or data.get(True, {})


def _job(data: dict) -> dict:
    jobs = data.get("jobs", {})
    assert jobs, "live-fetch-weekly.yml hat keine jobs."
    return next(iter(jobs.values()))


def _steps() -> list[dict]:
    return _job(_load_workflow()).get("steps", [])


def _run_text() -> str:
    return " ".join(str(s.get("run", "")) for s in _steps())


# --------------------------------------------------------------------------- #
# AC1 -- woechentlich geplanter Lauf, beide Suiten mit Schaltern
# --------------------------------------------------------------------------- #


def test_workflow_has_weekly_schedule_trigger():
    trigger = _trigger(_load_workflow())
    assert "schedule" in trigger, (
        "live-fetch-weekly.yml braucht einen schedule-Trigger (Issue #603, AC1)."
    )
    crons = [entry.get("cron") for entry in trigger["schedule"]]
    assert len(crons) == 1, f"Erwartet genau einen Cron-Eintrag, bekam {crons!r}."
    fields = crons[0].split()
    assert len(fields) == 5, f"Kein gueltiger 5-Felder-Cron-Ausdruck: {crons[0]!r}."
    # Woechentlich heisst: Wochentag-Feld (Index 4) ist auf genau einen Tag
    # fixiert, Monat/Tag-des-Monats/Stunde/Minute duerfen nicht '*' sein
    # (sonst laeuft der Cron taeglich statt woechentlich).
    minute, hour, dom, month, dow = fields
    assert dow != "*", f"Wochentag-Feld darf nicht '*' sein (waere taeglich): {crons[0]!r}."
    assert minute != "*" and hour != "*", f"Uhrzeit muss fixiert sein: {crons[0]!r}."


def test_workflow_runs_both_live_suites_with_switches_enabled():
    run_text = _run_text()
    assert "tests/test_issue_449_live_fetch.py" in run_text, (
        "Workflow ruft die Publisher-Live-Suite (#449) nicht auf."
    )
    assert "tests/test_issue_450_live_fetch.py" in run_text, (
        "Workflow ruft die Archiv-Live-Suite (#450) nicht auf."
    )
    envs = [s.get("env", {}) or {} for s in _steps()]
    assert any(str(env.get("RUN_LIVE_PUBLISHER_FETCH")) == "1" for env in envs), (
        "Kein Step setzt RUN_LIVE_PUBLISHER_FETCH=1 -- die Publisher-Suite wuerde nur skippen."
    )
    assert any(str(env.get("RUN_LIVE_FREE_ARCHIVE_FETCH")) == "1" for env in envs), (
        "Kein Step setzt RUN_LIVE_FREE_ARCHIVE_FETCH=1 -- die Archiv-Suite wuerde nur skippen."
    )


# --------------------------------------------------------------------------- #
# AC2 -- getrennt von ci.yml, blockiert keinen PR
# --------------------------------------------------------------------------- #


def test_workflow_trigger_excludes_push_and_pull_request():
    trigger = _trigger(_load_workflow())
    assert "push" not in trigger, (
        "live-fetch-weekly.yml darf nicht bei jedem push laufen (Scope: Out)."
    )
    assert "pull_request" not in trigger, (
        "live-fetch-weekly.yml darf nicht bei jedem PR laufen (Scope: Out)."
    )


def test_ci_yml_still_does_not_set_run_live_switches():
    """Dauerhafte Invariante: kein Step in ci.yml aktiviert die Live-Schalter --
    sie bleiben exklusiv ueber live-fetch-weekly.yml real ausfuehrbar."""
    assert CI_WORKFLOW.is_file(), f"{CI_WORKFLOW} fehlt."
    data = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    switches = {
        "RUN_LIVE_PUBLISHER_FETCH",
        "RUN_LIVE_FREE_ARCHIVE_FETCH",
        "RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK",
    }
    for job_name, job in (data.get("jobs") or {}).items():
        for step in job.get("steps", []):
            env = step.get("env", {}) or {}
            hit = switches & set(env)
            assert not hit, (
                f"ci.yml-Job {job_name!r}, Step {step.get('name')!r} setzt {hit} -- "
                "die Live-Schalter duerfen nur ueber live-fetch-weekly.yml real laufen (AC2)."
            )


# --------------------------------------------------------------------------- #
# AC3 -- RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK bleibt aus
# --------------------------------------------------------------------------- #


def test_workflow_never_sets_whole_work_switch():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK" not in text, (
        "live-fetch-weekly.yml darf RUN_LIVE_FREE_ARCHIVE_FETCH_WHOLE_WORK nicht "
        "setzen -- der schonende Standardweg (Seitenbereich statt Gesamtwerk) "
        "muss auch im geplanten Lauf gelten (Issue #603, Scope 'In')."
    )


# --------------------------------------------------------------------------- #
# AC4 -- Fehlschlag erzeugt benanntes Issue, kein Duplikat bei Wiederholung
# --------------------------------------------------------------------------- #


def test_workflow_calls_report_script_on_failure():
    steps = _steps()
    report_steps = [s for s in steps if "report_live_fetch_failure.sh" in str(s.get("run", ""))]
    assert report_steps, "Kein Step ruft scripts/ci/report_live_fetch_failure.sh auf."
    assert any(s.get("if") == "failure()" for s in report_steps), (
        "Der Report-Step muss nur bei Fehlschlag laufen (if: failure())."
    )


def test_report_script_exists_and_is_executable():
    assert REPORT_SCRIPT.is_file(), f"{REPORT_SCRIPT} fehlt (Issue #603, AC4)."
    import os

    assert os.access(REPORT_SCRIPT, os.X_OK), (
        f"{REPORT_SCRIPT} ist nicht ausfuehrbar (chmod +x fehlt)."
    )


def test_report_script_dedup_and_creation_behavior():
    """Fuehrt den dedizierten Shell-Harness aus (Stub-gh, echte JUnit-Fixtures) --
    prueft Neu-Anlage, Dedup und Nicht-Buendelung mehrerer Fetcher (AC4)."""
    harness = ROOT / "scripts" / "dev" / "test-report-live-fetch-failure.sh"
    assert harness.is_file(), f"{harness} fehlt."
    result = subprocess.run(
        ["bash", str(harness)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Harness fuer report_live_fetch_failure.sh schlaegt fehl:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_workflow_permissions_include_issues_write():
    data = _load_workflow()
    assert data.get("permissions", {}).get("issues") == "write", (
        "live-fetch-weekly.yml braucht 'issues: write', sonst kann der Report-Step "
        "kein Issue anlegen (AC4)."
    )


# --------------------------------------------------------------------------- #
# AC5 -- manuell ausloesbar
# --------------------------------------------------------------------------- #


def test_workflow_has_workflow_dispatch_trigger():
    trigger = _trigger(_load_workflow())
    assert "workflow_dispatch" in trigger, (
        "live-fetch-weekly.yml muss per workflow_dispatch ausloesbar sein (Issue #603, AC5)."
    )


# --------------------------------------------------------------------------- #
# AC6 -- lokaler Lauf ohne Schalter skippt weiterhin
# --------------------------------------------------------------------------- #


def test_local_pytest_without_switches_still_skips_live_tests():
    # Env explizit ohne die RUN_LIVE_*-Schalter bauen -- robust gegen einen
    # zufaellig verunreinigten Testlauf-Prozess (statt sich blind auf ein
    # "die sind schon nicht gesetzt" zu verlassen).
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("RUN_LIVE_PUBLISHER_FETCH", "RUN_LIVE_FREE_ARCHIVE_FETCH"))
    }
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_issue_449_live_fetch.py",
            "tests/test_issue_450_live_fetch.py",
            "-rs",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=clean_env,
    )
    assert result.returncode == 0, (
        f"Lokaler Lauf ohne Schalter soll gruen bleiben (nur Skips):\n{result.stdout}\n{result.stderr}"
    )
    assert "failed" not in result.stdout, f"Unerwarteter Fehlschlag ohne Schalter:\n{result.stdout}"
    assert "skipped" in result.stdout, (
        f"Erwartet Skips ohne RUN_LIVE_*-Schalter, bekam:\n{result.stdout}"
    )
