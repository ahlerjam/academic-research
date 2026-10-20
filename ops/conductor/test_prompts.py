"""Tests of the lead and watchdog prompts and of the cloud runtime rules in ar-unit.js and ar-team.js."""

from __future__ import annotations

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def read(rel: str) -> str:
    """Read a repository file."""
    with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
        return handle.read()


def fenced(text: str) -> list:
    """Return the bodies of all fenced text blocks."""
    return re.findall(r"```text\n(.*?)\n```", text, re.S)


def code_of(js: str) -> str:
    """Return a workflow script without its line comments."""
    return re.sub(r"(^|\s)//[^\n]*", r"\1", js)


class LeadGoal(unittest.TestCase):
    """The pasted message is one /goal command within the documented 4,000 characters."""

    def setUp(self) -> None:
        self.text = read("docs/autonomy/lead-goal.md")
        self.goal = fenced(self.text)[0]

    def test_goal_block_is_one_goal_command(self) -> None:
        self.assertTrue(self.goal.startswith("/goal "))
        self.assertEqual(self.goal.count("/goal"), 1)
        self.assertLessEqual(len(self.goal[len("/goal "):]), 4000)

    def test_goal_names_the_stop_condition(self) -> None:
        for needle in ("release.yml", "v0.1.0", "every milestone proof", "green on main", '"goal_met": true'):
            self.assertIn(needle, self.goal)

    def test_goal_names_the_tools_and_limits(self) -> None:
        for needle in ("ops/conductor/state.py", "ops/conductor/gh_ops.py", "ops/conductor/heartbeat.py",
                       "docs/autonomy/lead-goal.md", "ar-unit", "ar-team", "gh pr", "gh issue", "--admin",
                       "--limit-stop", "exits 3", "at most 2 units"):
            self.assertIn(needle, self.goal)

    def test_procedure_covers_pause_compaction_and_usage_limit(self) -> None:
        for needle in ("conductor:pause", "Compaction", "Usage limit", "Nicht verifiziert", "team_requested",
                       "clear-needs-operator", "op:external", "release_ready"):
            self.assertIn(needle, self.text)


class Watchdog(unittest.TestCase):
    """The routine prompt only refreshes the forecast while a lease is fresh and takes over when stale."""

    def test_prompt(self) -> None:
        prompt = fenced(read("docs/autonomy/watchdog-routine.md"))[0]
        for needle in ("heartbeat.py status", '"fresh"', '"stale"', '"done"', "2 hours", "update-status-issue",
                       "docs/autonomy/lead-goal.md", "Do not take the lease", "exits 3"):
            self.assertIn(needle, prompt)


class Workflows(unittest.TestCase):
    """No station pushes, opens PRs or uses the GraphQL-only gh subcommands; ar-team hands the team to the lead."""

    def test_no_push_or_graphql_commands(self) -> None:
        for name in ("ar-unit.js", "ar-team.js"):
            text = read(f".claude/workflows/{name}")
            code = code_of(text)
            with self.subTest(name=name):
                self.assertNotRegex(code, r"`gh (issue|pr) ")
                self.assertNotRegex(code, r"`git push")
                self.assertNotIn("isolation: 'worktree'", code)
                self.assertNotRegex(code, r"Date\.now\(|Math\.random\(|new Date\(\)")
                self.assertIn("gh api repos/${REPO}/issues/${issue}", code)
                self.assertIn("evidence_log", code)

    def test_ar_team_requests_the_team_from_the_lead(self) -> None:
        text = read(".claude/workflows/ar-team.js")
        self.assertIn("status: 'team_requested'", text)
        self.assertIn("after_team", text)
        self.assertIn("unavailable", text)
        self.assertIn("Nicht verifiziert", text)


if __name__ == "__main__":
    unittest.main()
