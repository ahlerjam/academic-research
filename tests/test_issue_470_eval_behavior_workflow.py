"""Regressionstest fuer Issue #470 -- Verhaltens-Evals real ausfuehren statt

dauerhaft zu ueberspringen.

Deckt die vier Akzeptanzkriterien strukturell ab (kein echter CI-Lauf, kein
API-Call noetig):

1. Ein separat auslösbarer Workflow (``workflow_dispatch``) fuehrt
   ``tests/evals/`` real aus und macht Erfolg/Fehlschlag ueber
   ``$GITHUB_STEP_SUMMARY`` + Artefakt-Upload sichtbar.
2. Das Budget ist begrenzt (``timeout-minutes``) und in
   ``docs/evals/STRATEGY.md`` (Abschnitt "API-Budget") dokumentiert.
3. ``docs/SKIP_REASONS.md`` enthaelt keine erledigten ``todo:*``-Zeilen mehr.
4. ``ci.yml`` ist von alledem unberuehrt (Diff gegen ``origin/main`` leer).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "eval-behavior.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
STRATEGY = ROOT / "docs" / "evals" / "STRATEGY.md"
SKIP_REASONS = ROOT / "docs" / "SKIP_REASONS.md"


def _load_workflow() -> dict:
    assert WORKFLOW.is_file(), f"{WORKFLOW} fehlt (Issue #470, AC1)."
    # PyYAML normalisiert den bareword-Key "on" zu bool True -- konsistent mit
    # tests/test_issue_385_ci_e2e_smoke.py, hier ueber _trigger() abgefangen.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _trigger(data: dict) -> dict:
    return data.get("on") or data.get(True, {})


def _job(data: dict) -> dict:
    jobs = data.get("jobs", {})
    assert jobs, "eval-behavior.yml hat keine jobs."
    # Genau ein Job -- name egal, aber deterministisch der erste/einzige.
    return next(iter(jobs.values()))


# --------------------------------------------------------------------------- #
# AC1 -- separat auslösbar, fuehrt tests/evals/ real aus, macht Ergebnis sichtbar
# --------------------------------------------------------------------------- #


def test_workflow_is_manual_only():
    """workflow_dispatch als einziger Trigger -- kein push/pull_request (Scope: 'Out')."""
    trigger = _trigger(_load_workflow())
    assert "workflow_dispatch" in trigger, (
        "eval-behavior.yml muss per workflow_dispatch auslösbar sein (Issue #470, AC1)."
    )
    assert "push" not in trigger, "eval-behavior.yml darf nicht bei jedem push laufen (Scope: Out)."
    assert "pull_request" not in trigger, (
        "eval-behavior.yml darf nicht bei jedem PR laufen (Scope: Out)."
    )


def test_workflow_runs_pytest_scoped_to_evals_dir_only():
    """Ruft ausschliesslich tests/evals/ auf -- nicht den vollen tests/-Baum."""
    job = _job(_load_workflow())
    steps = job.get("steps", [])
    run_text = " ".join(str(s.get("run", "")) for s in steps)
    assert "tests/evals/" in run_text, "Workflow ruft pytest nicht gegen tests/evals/ auf."
    assert "pytest tests/ " not in run_text and not run_text.rstrip().endswith("pytest tests/"), (
        "Workflow darf nicht den vollen tests/-Baum aufrufen (Budget-Scope, Issue #470 AC2)."
    )


def test_workflow_sets_anthropic_api_key_from_secrets():
    """Der pytest-Step bekommt ANTHROPIC_API_KEY aus secrets, sonst bleibt es ein Skip-Lauf."""
    job = _job(_load_workflow())
    steps = job.get("steps", [])
    envs = [s.get("env", {}) for s in steps]
    assert any("ANTHROPIC_API_KEY" in env for env in envs), (
        "Kein Step setzt ANTHROPIC_API_KEY -- der Lauf wuerde nur skippen, nicht real ausfuehren."
    )
    key_env = next(v for env in envs for k, v in env.items() if k == "ANTHROPIC_API_KEY")
    assert "secrets.ANTHROPIC_API_KEY" in str(key_env)


def test_workflow_aborts_hard_when_secret_missing():
    """Vorbedingung: ohne Secret bricht der Job ab statt taeuschend gruen zu skippen."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "::error::" in text, (
        "Workflow muss bei fehlendem ANTHROPIC_API_KEY hart mit ::error:: abbrechen "
        "(kein taeuschend gruener All-Skip-Lauf, Issue #470)."
    )
    assert "exit 1" in text


def test_workflow_uploads_result_artifact_and_writes_summary():
    """Erfolg/Fehlschlag muss sichtbar gemacht werden: Step-Summary + Artefakt."""
    job = _job(_load_workflow())
    steps = job.get("steps", [])
    uses_text = " ".join(str(s.get("uses", "")) for s in steps)
    run_text = " ".join(str(s.get("run", "")) for s in steps)
    assert "upload-artifact" in uses_text, (
        "Kein Artefakt-Upload -- Ergebnis waere nach dem Lauf weg."
    )
    assert "GITHUB_STEP_SUMMARY" in run_text, "Kein Schreiben nach GITHUB_STEP_SUMMARY."


# --------------------------------------------------------------------------- #
# AC2 -- Budget begrenzt und dokumentiert
# --------------------------------------------------------------------------- #


def test_workflow_has_timeout_cap():
    job = _job(_load_workflow())
    assert isinstance(job.get("timeout-minutes"), int) and job["timeout-minutes"] > 0, (
        "eval-behavior.yml braucht einen positiven timeout-minutes-Deckel (Issue #470, AC2)."
    )


def test_strategy_doc_references_the_real_workflow():
    """docs/evals/STRATEGY.md verankert die ~400-Aufrufe-Bezifferung am realen Workflow."""
    section = STRATEGY.read_text(encoding="utf-8").split("## API-Budget", 1)[1]
    assert "eval-behavior" in section, (
        "STRATEGY.md, Abschnitt API-Budget, referenziert den neuen Workflow nicht (Issue #470)."
    )


# --------------------------------------------------------------------------- #
# AC3 -- Übersprungsgründe-Dokumentation enthält nur noch geltende Einträge
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "stale_marker",
    [
        "todo:ocr",
        "todo:publisher-evals",
        "todo:page-offset-fixture",
        "Keine Token-Baseline erfasst",
    ],
)
def test_skip_reasons_has_no_stale_todo_rows(stale_marker):
    text = SKIP_REASONS.read_text(encoding="utf-8")
    assert stale_marker not in text, (
        f"docs/SKIP_REASONS.md enthaelt noch die erledigte Zeile {stale_marker!r} "
        "(Issue #470, AC3)."
    )


@pytest.mark.parametrize(
    "test_path",
    [
        "tests/test_ocr_detection.py",
        "tests/test_publisher_fetchers.py",
        "tests/evals/test_token_regression.py",
    ],
)
def test_formerly_stale_rows_correspond_to_zero_skips(test_path):
    """Die entfernten Zeilen beschreiben tatsaechlich nichts mehr Reales (0 Skips)."""
    result = subprocess.run(
        ["uv", "run", "pytest", test_path, "-rs", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "skipped" not in result.stdout, (
        f"{test_path} skippt noch etwas -- die entfernte SKIP_REASONS.md-Zeile war doch "
        f"noch gueltig:\n{result.stdout}"
    )


# --------------------------------------------------------------------------- #
# AC4 -- Regulärer Testlauf bleibt unberührt
# --------------------------------------------------------------------------- #


def test_ci_workflow_is_untouched_by_this_issue():
    """ci.yml bleibt gegenueber origin/main unveraendert (AC4)."""
    result = subprocess.run(
        ["git", "diff", "origin/main", "--", str(CI_WORKFLOW.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git diff schlug fehl: {result.stderr}"
    assert result.stdout == "", (
        f"ci.yml weicht von origin/main ab -- AC4 verlangt Unveraendertheit:\n{result.stdout}"
    )
