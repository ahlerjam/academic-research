"""Tests of gh_ops.py and the route allowlist: every verb and argument outside the fixed set is refused with nothing sent."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import tempfile
import unittest

import github
import gh_ops
import state
from fake_github import FakeGitHub
from test_state import NOW, release_world

CFG = state.load_config()
REPO = "ahlerjam/academic-research"


def run(g: FakeGitHub, *argv: str) -> int:
    """Run one verb against the fake, silencing its output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return gh_ops.run(list(argv), t=g, cfg=CFG, now=NOW)


def open_pr_object(number=7, head="claude/unit-3-x", base="main", fork=False, state_="open") -> dict:
    """Build a PR object as the REST API answers it."""
    return {"number": number, "state": state_, "base": {"ref": base},
            "head": {"ref": head, "sha": "abc", "repo": {"full_name": "other/fork" if fork else REPO}}}


class Files(unittest.TestCase):
    """Temporary body files."""

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def file(self, text: str, name: str = "body.md") -> str:
        """Write a temporary file and return its path."""
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class Routes(unittest.TestCase):
    """The allowlist refuses every route that could merge, change settings or write contents."""

    def test_refused_routes(self) -> None:
        refused = [
            ("PUT", f"repos/{REPO}/pulls/7/merge"),
            ("POST", f"repos/{REPO}/merges"),
            ("DELETE", f"repos/{REPO}/git/refs/heads/main"),
            ("PATCH", f"repos/{REPO}/git/refs/heads/main"),
            ("POST", f"repos/{REPO}/git/refs"),
            ("PUT", f"repos/{REPO}/contents/README.md"),
            ("DELETE", f"repos/{REPO}/contents/README.md"),
            ("POST", f"repos/{REPO}/rulesets"),
            ("PUT", f"repos/{REPO}/rulesets/25426278"),
            ("PUT", f"repos/{REPO}/branches/main/protection"),
            ("PATCH", f"repos/{REPO}"),
            ("DELETE", f"repos/{REPO}"),
            ("POST", f"repos/{REPO}/actions/workflows/release.yml/dispatches"),
            ("PUT", f"repos/{REPO}/actions/secrets/X"),
            ("DELETE", f"repos/{REPO}/pulls/7/ccr/auto_merge"),
            ("PATCH", f"repos/{REPO}/pulls/7"),
            ("POST", f"repos/{REPO}/pulls/7/reviews"),
            ("POST", f"repos/other/repo/issues"),
            ("GET", "repos/other/repo/issues"),
            ("GET", "user"),
            ("POST", f"repos/{REPO}/issues/1/../../pulls/1/merge"),
            ("POST", f"repos/{REPO}/issues?x=1"),
            ("POST", f"/repos/{REPO}/issues"),
        ]
        for method, path in refused:
            with self.subTest(method=method, path=path):
                with self.assertRaises(github.RouteRefused):
                    github.check_route(REPO, method, path)

    def test_allowed_routes(self) -> None:
        for method, path in [("GET", f"repos/{REPO}/pulls?state=open"), ("POST", f"repos/{REPO}/pulls"),
                             ("PUT", f"repos/{REPO}/pulls/7/ccr/auto_merge"), ("POST", f"repos/{REPO}/issues/3/labels"),
                             ("DELETE", f"repos/{REPO}/issues/3/labels/state%3Aready"),
                             ("POST", f"repos/{REPO}/issues/3/comments"), ("POST", f"repos/{REPO}/issues"),
                             ("PATCH", f"repos/{REPO}/issues/3"), ("POST", f"repos/{REPO}/labels")]:
            with self.subTest(method=method, path=path):
                github.check_route(REPO, method, path)

    def test_workflow_allowlist(self) -> None:
        for wf, ref in [("ci.yml", "main"), ("release.yml", "claude/x"), ("protect-operator-files.yml", "main")]:
            with self.subTest(wf=wf, ref=ref), self.assertRaises(github.RouteRefused):
                github.check_workflow(wf, ref)
        github.check_workflow("release.yml", "main")
        github.check_workflow("proof.yml", "main")


class Verbs(Files):
    """Each verb validates its arguments before anything is sent."""

    def test_unknown_verbs_are_refused(self) -> None:
        for verb in ["merge", "merge-pr", "api", "push", "delete-branch", "set-ruleset", "edit-workflow", "close-pr", ""]:
            with self.subTest(verb=verb):
                g = FakeGitHub()
                self.assertEqual(run(g, verb), 2)
                self.assertEqual(g.calls, [])

    def test_open_pr_only_from_claude_heads_into_main(self) -> None:
        body = self.file("Closes #3\n")
        log = self.file("make check ok\n", "verify.log")
        sha = hashlib.sha256(open(log, "rb").read()).hexdigest()
        for head in ["main", "feature/x", "claude", "claude/", "conductor/state", "claude/../main", "claude/x.lock",
                     "claude/a b", "refs/heads/claude/x", "claude/" + "x" * 120]:
            with self.subTest(head=head):
                g = FakeGitHub()
                self.assertEqual(run(g, "open-pr", "--head", head, "--title", "t", "--body-file", body,
                                     "--evidence-log", log, "--evidence-sha256", sha), 2)
                self.assertEqual(g.calls, [])
        g = FakeGitHub()
        self.assertEqual(run(g, "open-pr", "--head", "claude/unit-3-x", "--title", "unit 3", "--body-file", body,
                             "--evidence-log", log, "--evidence-sha256", sha), 0)
        method, path, sent = g.calls[0]
        self.assertEqual((method, path, sent["base"], sent["head"]), ("POST", f"repos/{REPO}/pulls", "main", "claude/unit-3-x"))
        self.assertIn(sha, sent["body"])

    def test_open_pr_refuses_wrong_evidence_and_bad_bodies(self) -> None:
        log = self.file("make check ok\n", "verify.log")
        body = self.file("Closes #3\n")
        cases = [
            ["--body-file", body, "--evidence-log", log, "--evidence-sha256", "0" * 64],
            ["--body-file", body, "--evidence-log", log + ".missing", "--evidence-sha256", "0" * 64],
            ["--body-file", self.file("  \n", "empty.md"), "--evidence-log", log,
             "--evidence-sha256", hashlib.sha256(b"make check ok\n").hexdigest()],
            ["--body-file", self.file("x" * 60001, "big.md"), "--evidence-log", log,
             "--evidence-sha256", hashlib.sha256(b"make check ok\n").hexdigest()],
        ]
        for extra in cases:
            with self.subTest(extra=extra[1]):
                g = FakeGitHub()
                self.assertEqual(run(g, "open-pr", "--head", "claude/unit-3-x", "--title", "t", *extra), 2)
                self.assertEqual(g.calls, [])
        g = FakeGitHub()
        self.assertEqual(run(g, "open-pr", "--head", "claude/unit-3-x", "--title", "two\nlines", "--body-file", body,
                             "--evidence-log", log, "--evidence-sha256", hashlib.sha256(b"make check ok\n").hexdigest()), 2)

    def test_auto_merge_only_for_claude_heads_into_main(self) -> None:
        bad = [open_pr_object(head="feature/x"), open_pr_object(base="release"), open_pr_object(fork=True),
               open_pr_object(state_="closed"), open_pr_object(head="conductor/state")]
        for obj in bad:
            with self.subTest(obj=obj["head"]["ref"] + "->" + obj["base"]["ref"]):
                g = FakeGitHub()
                g.set("pulls/7", obj)
                self.assertEqual(run(g, "enable-auto-merge", "--pr", "7"), 2)
                self.assertEqual(g.mutations(), [])
        g = FakeGitHub()
        self.assertEqual(run(g, "enable-auto-merge", "--pr", "8"), 2)
        g = FakeGitHub()
        g.set("pulls/7", open_pr_object())
        self.assertEqual(run(g, "enable-auto-merge", "--pr", "7"), 0)
        self.assertEqual(g.mutations(), [("PUT", f"repos/{REPO}/pulls/7/ccr/auto_merge", {"merge_method": "merge"})])
        for value in ["0", "-1", "7; rm", "abc"]:
            with self.subTest(value=value):
                self.assertEqual(run(FakeGitHub(), "enable-auto-merge", "--pr", value), 2)

    def test_labels_from_the_catalogue_only(self) -> None:
        g = FakeGitHub()
        self.assertEqual(run(g, "label", "--issue", "3", "--add", "not-a-label"), 2)
        self.assertEqual(run(g, "label", "--issue", "3", "--remove", "needs-operator"), 2)
        self.assertEqual(run(g, "label", "--issue", "3", "--remove", "conductor:pause"), 2)
        self.assertEqual(run(g, "label", "--issue", "3"), 2)
        self.assertEqual(g.calls, [])
        self.assertEqual(run(g, "label", "--issue", "3", "--add", "state:building", "--remove", "state:ready"), 0)
        self.assertEqual(g.mutations(), [("POST", f"repos/{REPO}/issues/3/labels", {"labels": ["state:building"]}),
                                         ("DELETE", f"repos/{REPO}/issues/3/labels/state%3Aready", None)])

    def test_comment_create_close(self) -> None:
        body = self.file("text\n")
        g = FakeGitHub()
        self.assertEqual(run(g, "create-issue", "--title", "x", "--body-file", body, "--label", "bogus"), 2)
        self.assertEqual(run(g, "close-issue", "--issue", "4", "--reason", "because", "--comment-file", body), 2)
        self.assertEqual(run(g, "close-issue", "--issue", "4", "--reason", "completed", "--comment-file", body + "x"), 2)
        self.assertEqual(g.mutations(), [])
        g.set("issues/4", {"number": 4, "state": "open", "labels": []})
        self.assertEqual(run(g, "close-issue", "--issue", "4", "--reason", "not_planned", "--comment-file", body), 0)
        self.assertEqual([c[0] for c in g.mutations()], ["POST", "PATCH"])
        self.assertEqual(g.mutations()[1][2], {"state": "closed", "state_reason": "not_planned"})
        g = FakeGitHub()
        g.set("issues/9", {"number": 9, "state": "open", "labels": [], "pull_request": {}})
        self.assertEqual(run(g, "close-issue", "--issue", "9", "--reason", "completed", "--comment-file", body), 2)
        self.assertEqual(g.mutations(), [])
        self.assertEqual(run(g, "comment", "--issue", "9", "--body-file", body), 0)
        self.assertEqual(run(g, "create-issue", "--title", "x", "--body-file", body, "--label", "unit"), 0)

    def test_clear_needs_operator_names_the_charter_rule(self) -> None:
        g = FakeGitHub()
        g.set("issues/99", {"number": 99, "state": "open", "labels": [{"name": "needs-operator"}]})
        reason = "the agents now apply proof.yml through the kernel bootstrap"
        self.assertEqual(run(g, "clear-needs-operator", "--issue", "99", "--charter-section", "4", "--reason", reason), 2)
        self.assertEqual(run(g, "clear-needs-operator", "--issue", "99", "--charter-section", "3", "--reason", "short"), 2)
        self.assertEqual(g.mutations(), [])
        self.assertEqual(run(g, "clear-needs-operator", "--issue", "99", "--charter-section", "3", "--reason", reason), 0)
        (m1, p1, b1), (m2, p2, _) = g.mutations()
        self.assertEqual((m1, p1), ("POST", f"repos/{REPO}/issues/99/comments"))
        self.assertIn("docs/autonomy/charter.md section 3", b1["body"])
        self.assertIn(reason, b1["body"])
        self.assertEqual((m2, p2), ("DELETE", f"repos/{REPO}/issues/99/labels/needs-operator"))

    def test_the_anthropic_request_keeps_needs_operator(self) -> None:
        g = FakeGitHub()
        g.set("issues/120", {"number": 120, "state": "open",
                             "labels": [{"name": "needs-operator"}, {"name": "op:external"}]})
        self.assertEqual(run(g, "clear-needs-operator", "--issue", "120", "--charter-section", "3",
                             "--reason", "would replace the operator action"), 2)
        self.assertEqual(g.mutations(), [])
        g.set("issues/121", {"number": 121, "state": "open", "labels": []})
        self.assertEqual(run(g, "clear-needs-operator", "--issue", "121", "--charter-section", "3",
                             "--reason", "would replace the operator action"), 2)

    def test_status_issue_is_updated_or_created(self) -> None:
        body = self.file("status\n")
        g = FakeGitHub()
        g.set("issues?state=open&labels=conductor", [{"number": 5, "title": "Conductor status", "labels": []}])
        self.assertEqual(run(g, "update-status-issue", "--body-file", body), 0)
        self.assertEqual(g.mutations(), [("PATCH", f"repos/{REPO}/issues/5", {"body": "status\n"})])
        g = FakeGitHub()
        g.set("issues?state=open&labels=conductor", [])
        self.assertEqual(run(g, "update-status-issue", "--body-file", body), 0)
        self.assertEqual(g.mutations()[0][2]["labels"], ["conductor"])

    def test_ensure_labels_creates_only_missing(self) -> None:
        g = FakeGitHub()
        g.set("labels", [{"name": "unit"}])
        self.assertEqual(run(g, "ensure-labels"), 0)
        created = [c[2]["name"] for c in g.mutations()]
        self.assertNotIn("unit", created)
        self.assertIn("needs-operator", created)
        self.assertIn("conductor:pause", created)


class Release(unittest.TestCase):
    """dispatch-release refuses dry_run=false unless state.py reports release_ready."""

    def test_dry_run_true_is_dispatched(self) -> None:
        g = FakeGitHub()
        self.assertEqual(run(g, "dispatch-release", "--version", "0.1.0", "--dry-run", "true"), 0)
        self.assertEqual(g.dispatches, [("release.yml", "main", {"dry_run": "true", "version": "0.1.0"})])

    def test_dry_run_false_refused_when_not_ready(self) -> None:
        g = release_world(files={"docs/release/0.1.0.md": "verdict: hold\n"})
        self.assertEqual(run(g, "dispatch-release", "--version", "0.1.0", "--dry-run", "false"), 2)
        self.assertEqual(g.dispatches, [])
        self.assertEqual(g.mutations(), [])

    def test_dry_run_false_dispatched_when_ready(self) -> None:
        g = release_world()
        self.assertEqual(run(g, "dispatch-release", "--version", "0.1.0", "--dry-run", "false"), 0)
        self.assertEqual(g.dispatches, [("release.yml", "main", {"dry_run": "false", "version": "0.1.0"})])

    def test_bad_release_arguments(self) -> None:
        g = release_world()
        for version, dry in [("0.2.0", "false"), ("v0.1.0", "true"), ("0.1", "true"), ("0.1.0", "yes"),
                             ("0.1.0", "False"), ("0.1.0", "")]:
            with self.subTest(version=version, dry=dry):
                self.assertEqual(run(g, "dispatch-release", "--version", version, "--dry-run", dry), 2)
        self.assertEqual(g.dispatches, [])

    def test_dispatch_proof_validates_stage(self) -> None:
        g = FakeGitHub()
        self.assertEqual(run(g, "dispatch-proof", "--stage", "6"), 2)
        self.assertEqual(run(g, "dispatch-proof", "--stage", "2a"), 0)
        self.assertEqual(g.dispatches, [("proof.yml", "main", {"stage": "2a"})])


if __name__ == "__main__":
    unittest.main()
