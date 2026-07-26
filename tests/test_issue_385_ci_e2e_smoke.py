"""Regressionstest fuer Issue #385 — E2E-Smoke-Journey in CI ausfuehren.

Befund: tests/test_smoke_e2e.py skippt sich modulweit (pytest.skip mit
allow_module_level=True), weil ``~/.academic-research/venv/bin/python``
(smoke_core.VENV_PYTHON) im CI-Runner nie existiert — scripts/setup.sh wird
im python-tests-Job nie aufgerufen.

Dieser Test prueft strukturell (Text-/YAML-Ebene, kein echter CI-Lauf noetig),
dass der python-tests-Job in .github/workflows/ci.yml die harte Voraussetzung
(venv unter $HOME/.academic-research/venv mit installiertem mcp-SDK) herstellt,
BEVOR ``pytest tests/`` laeuft, und dass node weiterhin vor pytest im PATH ist.

4 Test-Cases (kein LLM-Call, keine Netzwerk-/Browser-Automation):
1. ci.yml ist valides YAML mit einem python-tests-Job.
2. Der python-tests-Job enthaelt einen Step, der ein venv unter
   $HOME/.academic-research/venv per uv anlegt und dort das mcp-SDK
   installiert (Pfad + Paketname konsistent zu smoke_core.VENV_PYTHON /
   pyproject.toml).
3. Dieser Setup-Step steht TEXTUELL/STRUKTURELL vor dem pytest-Step
   ("pytest mit Coverage").
4. Der bestehende actions/setup-node-Step bleibt vor dem pytest-Step
   erhalten (AC3 — node muss fuer die Hook-Subprozess-Checks im PATH sein).
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Konsistent mit tests/helpers/smoke_core.py:53
EXPECTED_VENV_PATH_FRAGMENT = ".academic-research/venv"


def _load_ci_workflow() -> dict:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    # YAML-Key "on" wird von PyYAML sonst zu bool True normalisiert; hier
    # irrelevant, da wir nur auf "jobs" zugreifen.
    return yaml.safe_load(text)


def _python_tests_job() -> dict:
    data = _load_ci_workflow()
    jobs = data.get("jobs", {})
    assert "python-tests" in jobs, "ci.yml hat keinen python-tests-Job mehr."
    return jobs["python-tests"]


def _step_index(steps: list[dict], predicate) -> int:
    for i, step in enumerate(steps):
        name = str(step.get("name", ""))
        run = str(step.get("run", ""))
        uses = str(step.get("uses", ""))
        if predicate(name, run, uses):
            return i
    return -1


# --------------------------------------------------------------------------- #
# 1. ci.yml ist valides YAML mit python-tests-Job
# --------------------------------------------------------------------------- #
def test_ci_workflow_is_valid_yaml_with_python_tests_job():
    assert CI_WORKFLOW.is_file(), "ci.yml fehlt."
    job = _python_tests_job()
    assert "steps" in job, "python-tests-Job hat keine steps."


# --------------------------------------------------------------------------- #
# 2. venv-Setup-Step vorhanden: uv venv unter $HOME/.academic-research/venv
#    + mcp-Install in genau dieses venv.
# --------------------------------------------------------------------------- #
def test_python_tests_job_creates_academic_research_venv_with_mcp():
    job = _python_tests_job()
    steps = job["steps"]

    idx = _step_index(
        steps,
        lambda name, run, uses: EXPECTED_VENV_PATH_FRAGMENT in run and "uv venv" in run,
    )
    assert idx != -1, (
        f"Kein CI-Step legt ein venv unter $HOME/{EXPECTED_VENV_PATH_FRAGMENT} per 'uv venv' an."
    )

    venv_step_run = str(steps[idx].get("run", ""))
    assert "mcp" in venv_step_run, (
        "Der venv-Setup-Step installiert das mcp-SDK nicht erkennbar "
        "(erwartet z.B. 'uv pip install --python <venv>/bin/python \"mcp>=1.0\"')."
    )


# --------------------------------------------------------------------------- #
# 3. venv-Setup-Step steht vor dem pytest-Step ("pytest mit Coverage").
# --------------------------------------------------------------------------- #
def test_venv_setup_step_runs_before_pytest_step():
    job = _python_tests_job()
    steps = job["steps"]

    venv_idx = _step_index(
        steps,
        lambda name, run, uses: EXPECTED_VENV_PATH_FRAGMENT in run and "uv venv" in run,
    )
    pytest_idx = _step_index(
        steps,
        lambda name, run, uses: "pytest tests/" in run,
    )
    assert venv_idx != -1, "venv-Setup-Step fehlt (siehe Test 2)."
    assert pytest_idx != -1, "Kein Step ruft 'pytest tests/' auf."
    assert venv_idx < pytest_idx, (
        "Der venv-Setup-Step muss VOR dem pytest-Step stehen, sonst skippt "
        "test_smoke_e2e.py weiterhin modulweit."
    )


# --------------------------------------------------------------------------- #
# 4. node bleibt vor pytest im PATH (AC3 — bestehender Step darf nicht
#    verschoben/entfernt werden).
# --------------------------------------------------------------------------- #
def test_setup_node_step_still_precedes_pytest_step():
    job = _python_tests_job()
    steps = job["steps"]

    node_idx = _step_index(
        steps,
        lambda name, run, uses: "setup-node" in uses,
    )
    pytest_idx = _step_index(
        steps,
        lambda name, run, uses: "pytest tests/" in run,
    )
    assert node_idx != -1, "actions/setup-node-Step fehlt im python-tests-Job."
    assert pytest_idx != -1, "Kein Step ruft 'pytest tests/' auf."
    assert node_idx < pytest_idx, (
        "actions/setup-node muss weiterhin vor dem pytest-Step stehen (AC3)."
    )
