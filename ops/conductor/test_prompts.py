"""Tests of the lead and watchdog prompts and of the cloud runtime rules in every saved workflow and ar-* agent."""

from __future__ import annotations

import glob
import json
import os
import re
import unittest

import gh_ops

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
GRAPHQL_COMMANDS = re.compile(r"gh (issue|pr) (create|list|view|comment|edit|close|merge|reopen)\b|gh run (view|rerun)\b")
ISSUE_ONLY = ("ar-plan.js", "ar-judge.js", "ar-critic.js", "ar-triage.js")
CHANGES_FILES = ("ar-unit.js", "ar-team.js", "ar-fix.js", "ar-spike.js", "ar-release.js")


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


def workflows() -> dict:
    """Return every saved workflow script by file name."""
    return {os.path.basename(p): read(os.path.relpath(p, ROOT))
            for p in sorted(glob.glob(os.path.join(ROOT, ".claude", "workflows", "*.js")))}


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
                       "--limit-stop", "exits 3", "at most 2 units", "make setup", "apply-actions"):
            self.assertIn(needle, self.goal)

    def test_procedure_covers_pause_compaction_and_usage_limit(self) -> None:
        for needle in ("conductor:pause", "Compaction", "Usage limit", "Nicht verifiziert", "team_requested",
                       "clear-needs-operator", "op:external", "release_ready", "apply-actions --file",
                       "--issue inbox", "dry_run_red", "ar-release", "release-check.log", "make setup"):
            self.assertIn(needle, self.text)


class Watchdog(unittest.TestCase):
    """The routine prompt only refreshes the forecast while a lease is fresh and takes over when stale."""

    def test_prompt(self) -> None:
        prompt = fenced(read("docs/autonomy/watchdog-routine.md"))[0]
        for needle in ("heartbeat.py status", '"fresh"', '"stale"', '"done"', "2 hours", "update-status-issue",
                       "docs/autonomy/lead-goal.md", "Do not take the lease", "exits 3", "make setup", '"goal_met"'):
            self.assertIn(needle, prompt)


class Workflows(unittest.TestCase):
    """No station pushes, mutates GitHub or uses the GraphQL-only gh subcommands; the lead files every action."""

    def test_every_workflow_reads_github_by_rest_only(self) -> None:
        found = workflows()
        self.assertTrue(set(ISSUE_ONLY + CHANGES_FILES) <= set(found), sorted(found))
        for name, text in found.items():
            code = code_of(text)
            with self.subTest(name=name):
                self.assertIsNone(GRAPHQL_COMMANDS.search(code))
                self.assertNotRegex(code, r"`git push")
                self.assertNotIn("python3 -I ops/conductor/gh_ops.py", code)
                self.assertNotIn("isolation: 'worktree'", code)
                self.assertNotRegex(code, r"Date\.now\(|Math\.random\(|new Date\(\)")

    def test_agents_use_no_graphql_commands(self) -> None:
        for path in sorted(glob.glob(os.path.join(ROOT, ".claude", "agents", "*.md"))):
            with self.subTest(agent=os.path.basename(path)):
                self.assertIsNone(GRAPHQL_COMMANDS.search(read(os.path.relpath(path, ROOT))))

    def test_issue_only_workflows_return_actions_the_lead_files(self) -> None:
        for name in ISSUE_ONLY:
            code = code_of(workflows()[name])
            with self.subTest(name=name):
                self.assertIn("actions", code[code.rfind("return {"):])
                self.assertIn("close-issue", code)

    def test_action_rows_use_gh_ops_verbs_and_catalogued_labels(self) -> None:
        with open(os.path.join(HERE, "labels.json"), encoding="utf-8") as handle:
            catalogue = {row["name"] for row in json.load(handle)}
        for name, text in workflows().items():
            code = code_of(text)
            with self.subTest(name=name):
                for verb in re.findall(r"verb: '([a-z-]+)'", code):
                    self.assertIn(verb, gh_ops.ACTION_VERBS)
                for group in re.findall(r"\b(?:labels|add|remove): \[([^\]]*)\]", code):
                    for label in re.findall(r"(?<![=!]== )'([a-z]+(?:[:-][A-Za-z0-9]+)*)'", group):
                        self.assertIn(label, catalogue)

    def test_file_changing_workflows_take_a_worktree_and_return_evidence(self) -> None:
        for name in CHANGES_FILES:
            code = code_of(workflows()[name])
            with self.subTest(name=name):
                self.assertIn("args.worktree", code)
                self.assertIn("evidence_log", code)
        self.assertIn("args.worktree", code_of(workflows()["ar-triage.js"]))

    def test_ar_unit_and_ar_team_read_the_issue_by_rest(self) -> None:
        for name in ("ar-unit.js", "ar-team.js"):
            self.assertIn("gh api repos/${REPO}/issues/${issue}", code_of(workflows()[name]))

    def test_ar_team_requests_the_team_from_the_lead(self) -> None:
        text = read(".claude/workflows/ar-team.js")
        self.assertIn("status: 'team_requested'", text)
        self.assertIn("after_team", text)
        self.assertIn("unavailable", text)
        self.assertIn("Nicht verifiziert", text)

    def test_judge_panel_rules_on_the_taste_items(self) -> None:
        for rel in (".claude/agents/ar-judge.md", ".claude/workflows/ar-judge.js"):
            text = read(rel)
            with self.subTest(rel=rel):
                self.assertNotIn("never scored as passed", text)
                self.assertIn("charter", text)


if __name__ == "__main__":
    unittest.main()
