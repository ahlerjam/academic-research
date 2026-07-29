"""Regressionstest fuer Issue #340 -- ruff check blockierend machen.

Nach den Stufe-0-Auto-Fixes (#342) verblieben 60 ruff-Findings, weshalb der
`ruff check`-Step in ci.yml mit `continue-on-error: true` non-blocking geschaltet
wurde. Dieser Test stellt sicher, dass:

- AC1: `ruff check .` real 0 Findings liefert (Exit-Code 0), nicht nur behauptet wird.
- AC2: der `ruff check`-Step im Job `lint-types` in ci.yml kein
  `continue-on-error: true` mehr traegt, also das CI-Signal vollstaendig ist.
"""

import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent


def test_ruff_check_no_findings():
    """AC1: `ruff check .` liefert 0 Findings (real ausgefuehrt, nicht behauptet)."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff check . liefert noch Findings (Exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_ci_ruff_check_step_blocking():
    """AC2: ruff-check-Step im Job lint-types in ci.yml ohne continue-on-error."""
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    data = yaml.safe_load(ci.read_text(encoding="utf-8"))
    jobs = data["jobs"]
    assert "lint-types" in jobs, "Job 'lint-types' fehlt in ci.yml"
    steps = jobs["lint-types"]["steps"]
    ruff_steps = [s for s in steps if s.get("name") == "ruff check"]
    assert ruff_steps, "Kein Step 'ruff check' im Job 'lint-types' gefunden"
    ruff_step = ruff_steps[0]
    assert ruff_step.get("continue-on-error") is not True, (
        "ruff-check-Step traegt weiterhin 'continue-on-error: true' -- "
        "Signal ist nicht vollstaendig (#340)"
    )
