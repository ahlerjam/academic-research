"""Tests of gh_ops label removal, CI re-runs (with the state.py step that names them) and the label catalogue."""

from __future__ import annotations

import contextlib
import io
import re
import unittest

import gh_ops
import state
from fake_github import FakeGitHub
from test_state import NOW, pr, unit, world

CFG = state.load_config()
REPO = "ahlerjam/academic-research"


def run(g: FakeGitHub, *argv: str) -> int:
    """Run one verb against the fake, silencing its output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return gh_ops.run(list(argv), t=g, cfg=CFG)


def ci_run(branch: str = "claude/unit-3-x", status: str = "completed", conclusion: str = "cancelled") -> dict:
    """Build an Actions run object."""
    return {"id": 77, "head_branch": branch, "status": status, "conclusion": conclusion}


class Labels(unittest.TestCase):
    """Removing a label that is not there is no error; other GitHub errors stay errors."""

    def test_absent_label_is_reported_not_failed(self) -> None:
        g = FakeGitHub()
        g.fail("DELETE", "issues/3/labels/state%3Aready", 404)
        self.assertEqual(run(g, "label", "--issue", "3", "--add", "state:building", "--remove", "state:ready"), 0)

    def test_server_error_on_removal_is_exit_1(self) -> None:
        g = FakeGitHub()
        g.fail("DELETE", "issues/3/labels/state%3Aready", 500)
        self.assertEqual(run(g, "label", "--issue", "3", "--remove", "state:ready"), 1)

    def test_catalogue_is_valid_for_github(self) -> None:
        labels = gh_ops.load_labels()
        for name, row in labels.items():
            with self.subTest(name=name):
                self.assertRegex(row["color"], r"^[0-9a-f]{6}$")
                self.assertLessEqual(len(row["description"]), 100)
                self.assertLessEqual(len(name), 50)
        for needed in ("unit", "state:building", "state:pr", "state:ready", "needs-operator", "op:external",
                       "op:kernel", "conductor", "conductor:pause"):
            self.assertIn(needed, labels)
        self.assertTrue(all(re.match(r"^[a-z]", n) for n in labels))


class Reruns(unittest.TestCase):
    """Only completed, cancelled or failed runs of claude/* branches are re-run."""

    def test_refused_runs(self) -> None:
        for run_obj in (ci_run(branch="main"), ci_run(status="in_progress", conclusion=None),
                        ci_run(conclusion="success"), ci_run(branch="conductor/state")):
            with self.subTest(run=run_obj):
                g = FakeGitHub()
                g.set("actions/runs/77", run_obj)
                self.assertEqual(run(g, "rerun-failed", "--run", "77"), 2)
                self.assertEqual(g.mutations(), [])
        self.assertEqual(run(FakeGitHub(), "rerun-failed", "--run", "78"), 2)
        self.assertEqual(run(FakeGitHub(), "rerun-failed", "--run", "x"), 2)

    def test_cancelled_unit_run_is_rerun(self) -> None:
        g = FakeGitHub()
        g.set("actions/runs/77", ci_run())
        self.assertEqual(run(g, "rerun-failed", "--run", "77"), 0)
        self.assertEqual(g.mutations(), [("POST", f"repos/{REPO}/actions/runs/77/rerun-failed-jobs", {})])

    def test_state_names_the_cancelled_runs(self) -> None:
        checks = {"check_runs": [
            {"name": "gate", "status": "completed", "conclusion": "cancelled",
             "details_url": f"https://github.com/{REPO}/actions/runs/55/job/1"},
            {"name": "protect", "status": "completed", "conclusion": "success"}]}
        g = world([unit(1)], prs=[(pr(31, "claude/unit-1-a", "s1"), checks)])
        steps = state.compute(g, CFG, NOW)["next"]
        self.assertEqual(steps[0], {"do": "rerun", "pr": 31, "unit": 1, "runs": ["55"]})


if __name__ == "__main__":
    unittest.main()
