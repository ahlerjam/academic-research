"""New Bash rules: claude bypass, direct release, tag push, fetch into remote refs, push targets, gh api GET fields."""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import support  # noqa: E402

from lib import cmdnorm, hooks  # noqa: E402

RULE_CASES = (
    ("claude -p hi --dangerously-skip-permissions", "BASH-CLAUDE-BYPASS"),
    ("claude --allow-dangerously-skip-permissions -p hi", "BASH-CLAUDE-BYPASS"),
    ("claude -p hi --permission-mode bypassPermissions", "BASH-CLAUDE-BYPASS"),
    ("claude -p hi --permission-mode=bypassPermissions", "BASH-CLAUDE-BYPASS"),
    ("npx @anthropic-ai/claude-code --dangerously-skip-permissions", "BASH-CLAUDE-BYPASS"),
    ("/usr/local/bin/claude -p hi --settings '{\"permissions\":{\"defaultMode\":\"bypassPermissions\"}}'", "BASH-CLAUDE-BYPASS"),
    ("env FOO=1 claude --dangerously-skip-permissions", "BASH-CLAUDE-BYPASS"),
    ("gh workflow run release.yml", "BASH-RELEASE-DIRECT"),
    ("gh workflow run release.yml -f dry_run=true -f version=0.1.0", "BASH-RELEASE-DIRECT"),
    ("gh workflow run .github/workflows/release.yml -f dry_run=false", "BASH-RELEASE-DIRECT"),
    ("gh workflow run Release --ref main", "BASH-RELEASE-DIRECT"),
    ("gh workflow run 123456 -f dry_run=true", "BASH-RELEASE-DIRECT"),
    ("gh release create v0.1.0 dist/x.zip", "BASH-RELEASE-DIRECT"),
    ("gh release upload v0.1.0 dist/x.zip", "BASH-RELEASE-DIRECT"),
    ("git push origin v0.1.0", "BASH-TAG-PUSH"),
    ("git push origin --tags", "BASH-TAG-PUSH"),
    ("git push --follow-tags origin claude/x", "BASH-TAG-PUSH"),
    ("git push origin tag v1", "BASH-TAG-PUSH"),
    ("git push origin HEAD:refs/tags/v0.1.0", "BASH-TAG-PUSH"),
    ("git push origin :refs/tags/v0.1.0", "BASH-TAG-PUSH"),
    ("git -c push.followTags=true push origin claude/x", "BASH-TAG-PUSH"),
    ("git fetch https://example.org/o/r.git +main:refs/remotes/origin/main", "BASH-FETCH-REF"),
    ("git fetch origin main:remotes/origin/main", "BASH-FETCH-REF"),
    ("git fetch origin +HEAD:refs/gates/baseline", "BASH-FETCH-REF"),
    ("git -c remote.origin.fetch=+refs/heads/x:refs/heads/y fetch origin", "BASH-FETCH-REF"),
    ("gh api repos/o/r/issues -f title=x", "BASH-GH-API-MUTATION"),
    ("gh api repos/o/r/issues -ftitle=x", "BASH-GH-API-MUTATION"),
    ("gh api repos/o/r/issues --raw-field=title=x", "BASH-GH-API-MUTATION"),
    ("gh api -X get repos/o/r/issues -f title=x", "BASH-GH-API-MUTATION"),
    ("gh api -X POST repos/o/r/issues -X GET -f title=x", "BASH-GH-API-MUTATION"),
    ("gh api -X GET repos/o/r/issues --input body.json", "BASH-GH-API-MUTATION"),
    ("gh api --method GET repos/o/r/issues --input=body.json", "BASH-GH-API-MUTATION"),
    ("gh api graphql -X GET -f query=x", "BASH-GH-API-MUTATION"),
    ("gh api -X patch repos/o/r", "BASH-GH-API-MUTATION"),
    ("gh api -X PUT repos/o/r/pulls/3/ccr/auto_merge", "BASH-GH-API-MUTATION"),
    ("gh api -X DELETE repos/o/r/git/refs/heads/x", "BASH-GH-API-MUTATION"),
)
ALLOWED = (
    "claude -p hi --permission-mode dontAsk",
    "grep -rn bypassPermissions docs",
    "gh workflow run proof.yml -f stage=1",
    "gh workflow list",
    "gh release view v0.1.0",
    "gh release list",
    "python3 -I ops/conductor/gh_ops.py dispatch-release --version 0.1.0 --dry-run true",
    "git fetch origin",
    "git fetch --prune origin",
    "git fetch origin conductor/state",
    "git tag -l",
    "gh api -X GET repos/o/r/issues -f state=open",
    "gh api --method GET search/issues -F q=repo:o/r",
    "gh api --method=GET repos/o/r/pulls -f per_page=5",
    "gh api -XGET repos/o/r/issues -f state=open",
    "gh api repos/o/r/pulls",
    "gh api repos/o/r/pulls/3/ccr/auto_merge",
)


def load_rules() -> list:
    """Return the rules of the source tree's gates/bash_rules.json."""
    with open(os.path.join(support.SOURCE, "gates", "bash_rules.json"), encoding="utf-8") as handle:
        return json.load(handle)["rules"]


class RuleIds(unittest.TestCase):
    """Each bad command breaks the named rule; each good command breaks none."""

    def test_bad_commands_hit_their_rule(self) -> None:
        rules = load_rules()
        wrong = [f"{c!r} misses {rid}" for c, rid in RULE_CASES if rid not in [h[0] for h in cmdnorm.match(c, rules)]]
        self.assertEqual(wrong, [])

    def test_good_commands_hit_no_rule(self) -> None:
        rules = load_rules()
        wrong = [f"{c!r}: {cmdnorm.match(c, rules)}" for c in ALLOWED if cmdnorm.match(c, rules)]
        self.assertEqual(wrong, [])

    def test_good_commands_pass_the_whole_hook(self) -> None:
        root = support.make_tree()
        try:
            support.git(root, "checkout", "-q", "-b", "claude/work")
            for command in ALLOWED:
                proc = support.gate(root, ["hook", "pre-bash"], {"tool_input": {"command": command}, "cwd": root})
                self.assertEqual(proc.returncode, 0, f"{command}: {proc.stderr}")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class PushTargets(unittest.TestCase):
    """Agent sessions push only claude/* and conductor/state; a tag is never pushed; BASH-PROTECTED-PUSH stays."""

    def setUp(self) -> None:
        self.root = support.make_tree()
        support.git(self.root, "branch", "-M", "main")
        support.git(self.root, "tag", "v0.1.0")
        support.git(self.root, "tag", "plain-tag")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def rules(self, command: str) -> list:
        proc = support.gate(self.root, ["hook", "pre-bash"], {"tool_input": {"command": command}, "cwd": self.root})
        return [line.split("[", 1)[1].split("]", 1)[0] for line in proc.stderr.splitlines() if "blocked [" in line]

    def test_allowed_destinations(self) -> None:
        for command in ("git push -u origin claude/unit-12", "git push origin HEAD:claude/unit-12",
                        "git push origin HEAD:refs/heads/claude/unit-12", "git push origin conductor/state",
                        "git push origin --delete claude/old", "git push origin :claude/old",
                        "git push origin claude/a claude/b"):
            self.assertEqual(self.rules(command), [], command)

    def test_other_destinations_are_red(self) -> None:
        for command in ("git push origin feature", "git push -u origin feature/main-fix", "git push origin unit/12-x",
                        "git push origin claude/a feature", "git push origin claude/x:release",
                        "git push origin conductor/state-2", "git push origin --delete feature",
                        "git push origin HEAD:refs/notes/x", "git push origin \"$BRANCH\""):
            self.assertIn("BASH-PUSH-MAIN-STATE", self.rules(command), command)

    def test_current_branch_decides_a_bare_push(self) -> None:
        self.assertIn("BASH-PROTECTED-PUSH", self.rules("git push"))
        self.assertIn("BASH-PUSH-MAIN-STATE", self.rules("git push origin HEAD"))
        support.git(self.root, "checkout", "-q", "-b", "claude/work")
        self.assertEqual(self.rules("git push"), [])
        self.assertEqual(self.rules("git push -u origin HEAD"), [])
        support.git(self.root, "config", "push.default", "matching")
        self.assertIn("BASH-PUSH-MAIN-STATE", self.rules("git push"))
        support.git(self.root, "config", "--unset", "push.default")
        support.git(self.root, "checkout", "-q", "--detach")
        self.assertIn("BASH-PUSH-MAIN-STATE", self.rules("git push origin HEAD"))

    def test_local_tag_names_are_tag_pushes(self) -> None:
        self.assertIn("BASH-TAG-PUSH", self.rules("git push origin plain-tag"))
        self.assertIn("BASH-TAG-PUSH", self.rules("git push origin v0.1.0"))

    def test_protected_push_keeps_its_contract(self) -> None:
        self.assertTrue(hooks.protected_push(self.root, [["git", "push"]], "main|master"))
        self.assertEqual(hooks.protected_push(self.root, [["git", "push", "origin", "claude/x"]], "main|master"), [])
        self.assertIn("BASH-PROTECTED-PUSH", self.rules("git push origin claude/x:main"))


if __name__ == "__main__":
    unittest.main()
