"""Tests of gh_ops.py and the route allowlist: every verb and argument outside the fixed set is refused with nothing sent."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
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
HOLDER = "lead-test"
PROGRESS_KEY = f"repos/{REPO}/contents/{CFG['progress_path']}?ref={CFG['state_branch']}"


def run(g: FakeGitHub, *argv: str) -> int:
    """Run one verb against the fake, silencing its output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return gh_ops.run(list(argv), t=g, cfg=CFG, now=NOW)


def leased(g: FakeGitHub, holder: str = HOLDER, beat: float = NOW - 60) -> FakeGitHub:
    """Give the fake a progress.json whose lease belongs to holder."""
    g.set_file(CFG["progress_path"], CFG["state_branch"], json.dumps({"lease": {"holder": holder, "beat_at": beat}}))
    return g


def open_pr_object(number=7, head="claude/unit-3-x", base="main", fork=False, state_="open") -> dict:
    """Build a PR object as the REST API answers it."""
    return {"number": number, "state": state_, "base": {"ref": base},
            "head": {"ref": head, "sha": "abc", "repo": {"full_name": "other/fork" if fork else REPO}}}


def issue_of(number: int, labels=("unit",), author: str = "OWNER", **extra) -> dict:
    """Build an open issue with the given labels and author association."""
    return dict({"number": number, "state": "open", "title": "x", "labels": [{"name": n} for n in labels],
                 "author_association": author}, **extra)


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

    def pr_args(self, head: str = "claude/unit-3-x", title: str = "unit 3\n") -> list:
        """Return valid open-pr arguments with the title in a file."""
        log = self.file("make check ok\n", "verify.log")
        return ["open-pr", "--holder", HOLDER, "--head", head, "--title-file", self.file(title, "title.txt"),
                "--body-file", self.file("Closes #3\n"), "--evidence-log", log,
                "--evidence-sha256", hashlib.sha256(b"make check ok\n").hexdigest()]

    def test_open_pr_only_from_claude_heads_into_main(self) -> None:
        for head in ["main", "feature/x", "claude", "claude/", "conductor/state", "claude/../main", "claude/x.lock",
                     "claude/a b", "refs/heads/claude/x", "claude/" + "x" * 120]:
            with self.subTest(head=head):
                g = leased(FakeGitHub())
                self.assertEqual(run(g, *self.pr_args(head=head)), 2)
                self.assertEqual(g.mutations(), [])
        g = leased(FakeGitHub())
        self.assertEqual(run(g, *self.pr_args()), 0)
        method, path, sent = g.mutations()[0]
        self.assertEqual((method, path, sent["base"], sent["head"]), ("POST", f"repos/{REPO}/pulls", "main", "claude/unit-3-x"))
        self.assertEqual(sent["title"], "unit 3")
        self.assertIn(hashlib.sha256(b"make check ok\n").hexdigest(), sent["body"])

    def test_the_pr_title_comes_from_a_file_never_from_the_command_line(self) -> None:
        g = leased(FakeGitHub())
        title = 'feat: x"; touch /tmp/pwned; echo "$(id)`id`'
        self.assertEqual(run(g, *self.pr_args(title=title + "\n")), 0)
        self.assertEqual(g.mutations()[0][2]["title"], title)
        for bad in ("two\nlines\n", "\n", "x" * 257):
            with self.subTest(bad=bad[:10]):
                g = leased(FakeGitHub())
                self.assertEqual(run(g, *self.pr_args(title=bad)), 2)
                self.assertEqual(g.mutations(), [])
        args = self.pr_args()
        i = args.index("--title-file")
        g = leased(FakeGitHub())
        self.file("x\n", "unit 3")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = gh_ops.run(args[:i] + ["--title", os.path.join(self.dir.name, "unit 3")] + args[i + 2:], t=g, cfg=CFG,
                              now=NOW)
        self.assertEqual(code, 2, "--title is no abbreviation of --title-file")
        self.assertEqual(g.calls, [])

    def test_open_pr_refuses_wrong_evidence_and_bad_bodies(self) -> None:
        log = self.file("make check ok\n", "verify.log")
        body = self.file("Closes #3\n")
        title = self.file("t\n", "title.txt")
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
                g = leased(FakeGitHub())
                self.assertEqual(run(g, "open-pr", "--holder", HOLDER, "--head", "claude/unit-3-x", "--title-file", title,
                                     *extra), 2)
                self.assertEqual(g.mutations(), [])

    def lease_verbs(self) -> list:
        """Return one valid call of every verb that needs the own lease, with the fake data it reads."""
        actions = self.file(json.dumps({"actions": [{"verb": "comment", "issue": 3, "body": "x"}]}), "a.json")
        body = self.file("text\n")
        reason = "the agents now apply proof.yml through the kernel bootstrap"
        return [self.pr_args(), ["enable-auto-merge", "--holder", HOLDER, "--pr", "7"],
                ["apply-actions", "--holder", HOLDER, "--file", actions],
                ["label", "--holder", HOLDER, "--issue", "4", "--add", "state:building"],
                ["comment", "--holder", HOLDER, "--issue", "4", "--body-file", body],
                ["create-issue", "--holder", HOLDER, "--title", "x", "--body-file", body, "--label", "unit"],
                ["close-issue", "--holder", HOLDER, "--issue", "4", "--reason", "completed", "--comment-file", body],
                ["clear-needs-operator", "--holder", HOLDER, "--issue", "99", "--charter-section", "3", "--reason", reason],
                ["rerun-failed", "--holder", HOLDER, "--run", "77"],
                ["dispatch-proof", "--holder", HOLDER, "--stage", "1"],
                ["dispatch-release", "--holder", HOLDER, "--version", "0.1.0", "--dry-run", "true"]]

    def lease_world(self) -> FakeGitHub:
        """A fake with the objects the lease verbs read."""
        g = FakeGitHub()
        g.set("pulls/7", open_pr_object())
        g.set("issues/4", issue_of(4))
        g.set("issues/99", issue_of(99, labels=("needs-operator",)))
        g.set("actions/runs/77", {"id": 77, "head_branch": "claude/unit-3-x", "status": "completed",
                                  "conclusion": "cancelled", "head_repository": {"full_name": REPO}})
        return g

    def test_every_verb_but_the_status_issue_and_the_labels_needs_the_own_lease(self) -> None:
        verbs = self.lease_verbs()
        self.assertEqual(sorted(argv[0] for argv in verbs), sorted(gh_ops.HOLDER_VERBS))
        self.assertEqual(sorted(gh_ops.HOLDER_VERBS + ("update-status-issue", "ensure-labels")), sorted(gh_ops.VERBS))
        leases = {"no progress": None, "another holder": {"lease": {"holder": "lead-other", "beat_at": NOW - 60}},
                  "a beat in the future": {"lease": {"holder": HOLDER, "beat_at": NOW + 3600}},
                  "a stale lease": {"lease": {"holder": HOLDER, "beat_at": NOW - CFG["lease_max_age_s"] - 1}},
                  "corrupt file": "not json"}
        g = self.lease_world()
        for why, progress in leases.items():
            for argv in verbs:
                with self.subTest(why=why, verb=argv[0]):
                    g.calls.clear()
                    g.answers.pop(PROGRESS_KEY, None)
                    if progress is not None:
                        g.set_file(CFG["progress_path"], CFG["state_branch"],
                                   progress if isinstance(progress, str) else json.dumps(progress))
                    self.assertEqual(run(g, *argv), 2)
                    self.assertEqual((g.mutations(), g.dispatches), ([], []))
        for argv in verbs:
            with self.subTest(verb=argv[0], lease="none named"):
                leased(g)
                g.calls.clear()
                self.assertEqual(run(g, *[a for i, a in enumerate(argv) if a != "--holder" and argv[i - 1] != "--holder"]), 2)
                self.assertEqual(g.mutations(), [])
        for argv in verbs:
            with self.subTest(verb=argv[0], lease="own"):
                g = leased(self.lease_world())
                self.assertEqual(run(g, *argv), 0)
                self.assertGreaterEqual(len(g.mutations()) + len(g.dispatches), 1)

    def test_the_status_issue_and_the_labels_need_no_lease(self) -> None:
        g = FakeGitHub()
        g.set("issues?state=open&labels=conductor", [])
        g.set("labels", [])
        self.assertEqual(run(g, "update-status-issue", "--body-file", self.file("status\n")), 0)
        self.assertEqual(run(g, "ensure-labels"), 0)
        self.assertNotIn(PROGRESS_KEY, [c[1] for c in g.calls])
        self.assertEqual(run(g, "ensure-labels", "--holder", HOLDER), 2)

    def test_auto_merge_only_for_claude_heads_into_main(self) -> None:
        bad = [open_pr_object(head="feature/x"), open_pr_object(base="release"), open_pr_object(fork=True),
               open_pr_object(state_="closed"), open_pr_object(head="conductor/state")]
        for obj in bad:
            with self.subTest(obj=obj["head"]["ref"] + "->" + obj["base"]["ref"]):
                g = leased(FakeGitHub())
                g.set("pulls/7", obj)
                self.assertEqual(run(g, "enable-auto-merge", "--holder", HOLDER, "--pr", "7"), 2)
                self.assertEqual(g.mutations(), [])
        g = leased(FakeGitHub())
        self.assertEqual(run(g, "enable-auto-merge", "--holder", HOLDER, "--pr", "8"), 2)
        g = leased(FakeGitHub())
        g.set("pulls/7", open_pr_object())
        self.assertEqual(run(g, "enable-auto-merge", "--holder", HOLDER, "--pr", "7"), 0)
        self.assertEqual(g.mutations(), [("PUT", f"repos/{REPO}/pulls/7/ccr/auto_merge", {"merge_method": "merge"})])
        for value in ["0", "-1", "7; rm", "abc"]:
            with self.subTest(value=value):
                self.assertEqual(run(leased(FakeGitHub()), "enable-auto-merge", "--holder", HOLDER, "--pr", value), 2)

    def test_labels_from_the_catalogue_only(self) -> None:
        g = leased(FakeGitHub())
        lab = ("label", "--holder", HOLDER, "--issue", "3")
        self.assertEqual(run(g, *lab, "--add", "not-a-label"), 2)
        self.assertEqual(run(g, *lab, "--remove", "needs-operator"), 2)
        for name in ("conductor:pause", "conductor", "op:external", "op:kernel", "op:taste"):
            with self.subTest(remove=name):
                self.assertEqual(run(g, *lab, "--remove", name), 2)
        self.assertEqual(run(g, *lab, "--add", "conductor"), 2)
        self.assertEqual(run(g, *lab), 2)
        self.assertEqual(g.mutations(), [])
        self.assertEqual(run(g, *lab, "--add", "state:building", "--remove", "state:ready"), 0)
        self.assertEqual(g.mutations(), [("POST", f"repos/{REPO}/issues/3/labels", {"labels": ["state:building"]}),
                                         ("DELETE", f"repos/{REPO}/issues/3/labels/state%3Aready", None)])

    def test_comment_create_close(self) -> None:
        body = self.file("text\n")
        g = leased(FakeGitHub())
        self.assertEqual(run(g, "create-issue", "--holder", HOLDER, "--title", "x", "--body-file", body, "--label", "bogus"), 2)
        self.assertEqual(run(g, "close-issue", "--holder", HOLDER, "--issue", "4", "--reason", "because",
                             "--comment-file", body), 2)
        self.assertEqual(run(g, "close-issue", "--holder", HOLDER, "--issue", "4", "--reason", "completed",
                             "--comment-file", body + "x"), 2)
        self.assertEqual(g.mutations(), [])
        g.set("issues/4", {"number": 4, "state": "open", "labels": []})
        self.assertEqual(run(g, "close-issue", "--holder", HOLDER, "--issue", "4", "--reason", "not_planned",
                             "--comment-file", body), 0)
        self.assertEqual([c[0] for c in g.mutations()], ["POST", "PATCH"])
        self.assertEqual(g.mutations()[1][2], {"state": "closed", "state_reason": "not_planned"})
        g = leased(FakeGitHub())
        g.set("issues/9", {"number": 9, "state": "open", "labels": [], "pull_request": {}})
        self.assertEqual(run(g, "close-issue", "--holder", HOLDER, "--issue", "9", "--reason", "completed",
                             "--comment-file", body), 2)
        self.assertEqual(g.mutations(), [])
        self.assertEqual(run(g, "comment", "--holder", HOLDER, "--issue", "9", "--body-file", body), 0)
        self.assertEqual(run(g, "create-issue", "--holder", HOLDER, "--title", "x", "--body-file", body, "--label", "unit"), 0)

    def test_operator_issues_are_never_closed(self) -> None:
        body = self.file("text\n")
        protected = [
            {"title": "Conductor status", "labels": [{"name": "conductor"}, {"name": "conductor:pause"}]},
            {"title": "Conductor status", "labels": []},
            {"title": "Operator-Inbox", "labels": [{"name": "conductor"}]},
            {"title": "x", "labels": [{"name": "conductor:pause"}]},
            {"title": "x", "labels": [{"name": "needs-operator"}]},
            {"title": "x", "labels": [{"name": "op:kernel"}]},
            {"title": "Anthropic request: use of the Claude plan by the plugin", "labels": [{"name": "op:external"}]},
            {"title": "Anthropic request: use of the Claude plan by the plugin", "labels": []},
        ]
        close = ("close-issue", "--holder", HOLDER, "--issue", "7", "--reason", "completed", "--comment-file", body)
        for issue in protected:
            with self.subTest(issue=issue):
                g = leased(FakeGitHub())
                g.set("issues/7", dict(issue, number=7, state="open"))
                self.assertEqual(run(g, *close), 2)
                self.assertEqual(g.mutations(), [])
        g = leased(FakeGitHub())
        g.set("issues/7", {"number": 7, "state": "open", "title": "Release 0.1.0", "labels": []})
        self.assertEqual(run(g, *close), 0)

    def test_clear_needs_operator_names_the_charter_rule(self) -> None:
        g = leased(FakeGitHub())
        g.set("issues/99", {"number": 99, "state": "open", "labels": [{"name": "needs-operator"}]})
        reason = "the agents now apply proof.yml through the kernel bootstrap"
        clear = ("clear-needs-operator", "--holder", HOLDER, "--issue", "99", "--charter-section")
        self.assertEqual(run(g, *clear, "4", "--reason", reason), 2)
        self.assertEqual(run(g, *clear, "3", "--reason", "short"), 2)
        self.assertEqual(g.mutations(), [])
        self.assertEqual(run(g, *clear, "3", "--reason", reason), 0)
        (m1, p1, b1), (m2, p2, _) = g.mutations()
        self.assertEqual((m1, p1), ("POST", f"repos/{REPO}/issues/99/comments"))
        self.assertIn("docs/autonomy/charter.md section 3", b1["body"])
        self.assertIn(reason, b1["body"])
        self.assertEqual((m2, p2), ("DELETE", f"repos/{REPO}/issues/99/labels/needs-operator"))

    def test_the_anthropic_request_keeps_needs_operator(self) -> None:
        g = leased(FakeGitHub())
        g.set("issues/120", {"number": 120, "state": "open",
                             "labels": [{"name": "needs-operator"}, {"name": "op:external"}]})
        clear = ("clear-needs-operator", "--holder", HOLDER, "--charter-section", "3", "--issue")
        self.assertEqual(run(g, *clear, "120", "--reason", "would replace the operator action"), 2)
        self.assertEqual(g.mutations(), [])
        g.set("issues/121", {"number": 121, "state": "open", "labels": []})
        self.assertEqual(run(g, *clear, "121", "--reason", "would replace the operator action"), 2)
        g.set("issues/122", {"number": 122, "state": "open", "labels": [{"name": "needs-operator"}],
                             "title": "Anthropic request: use of the Claude plan by the plugin"})
        self.assertEqual(run(g, *clear, "122", "--reason", "op:external was removed before, the title still names it"), 2)
        self.assertEqual(run(g, "label", "--holder", HOLDER, "--issue", "120", "--remove", "op:external"), 2)
        self.assertEqual(g.mutations(), [])

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


class LabelTargets(Files):
    """Labels that schedule work land only on unprotected unit, critic or hypothesis issues of trusted authors."""

    TRIGGERS = ("unit", "kind:build", "kind:plan", "slice:S1", "hypothesis", "critic", "state:ready")

    def label(self, issue: dict, add: str) -> FakeGitHub:
        """Run label --add on issue #7 and return the fake."""
        g = leased(FakeGitHub())
        g.set("issues/7", issue)
        self.code = run(g, "label", "--holder", HOLDER, "--issue", "7", "--add", add)
        return g

    def test_scheduling_labels_are_refused_on_other_targets(self) -> None:
        refused = {
            "pull request": issue_of(7, pull_request={}),
            "outsider unit issue": issue_of(7, author="NONE"),
            "contributor unit issue": issue_of(7, author="CONTRIBUTOR"),
            "issue without author association": dict(issue_of(7), author_association=None),
            "type:feature issue": issue_of(7, labels=("type:feature",)),
            "unlabelled issue": issue_of(7, labels=()),
            "kernel unit": issue_of(7, labels=("unit", "op:kernel")),
            "status issue": issue_of(7, labels=("conductor",), title="Conductor status"),
        }
        for why, issue in refused.items():
            for add in self.TRIGGERS:
                with self.subTest(target=why, add=add):
                    g = self.label(issue, add)
                    self.assertEqual(self.code, 2)
                    self.assertEqual(g.mutations(), [])
        g = leased(FakeGitHub())
        self.assertEqual(run(g, "label", "--holder", HOLDER, "--issue", "8", "--add", "unit"), 2, "a missing issue")

    def test_scheduling_labels_on_a_trusted_card_are_sent(self) -> None:
        for author in ("OWNER", "MEMBER", "COLLABORATOR"):
            for labels in (("unit",), ("critic",), ("hypothesis",), ("slice:S2",)):
                with self.subTest(author=author, labels=labels):
                    g = self.label(issue_of(7, labels=labels, author=author), "state:ready")
                    self.assertEqual(self.code, 0)
                    self.assertIn(("GET", f"repos/{REPO}/issues/7", None), g.calls)
                    self.assertEqual(g.mutations(), [("POST", f"repos/{REPO}/issues/7/labels", {"labels": ["state:ready"]})])

    def test_other_labels_need_no_target_read(self) -> None:
        g = leased(FakeGitHub())
        self.assertEqual(run(g, "label", "--holder", HOLDER, "--issue", "31", "--add", "state:pr",
                             "--remove", "state:building"), 0)
        self.assertNotIn(("GET", f"repos/{REPO}/issues/31", None), g.calls)
        self.assertEqual(len(g.mutations()), 2)


class Release(unittest.TestCase):
    """dispatch-release refuses dry_run=false unless state.py reports release_ready."""

    def test_dry_run_true_is_dispatched(self) -> None:
        g = leased(FakeGitHub())
        self.assertEqual(run(g, "dispatch-release", "--holder", HOLDER, "--version", "0.1.0", "--dry-run", "true"), 0)
        self.assertEqual(g.dispatches, [("release.yml", "main", {"dry_run": "true", "version": "0.1.0"})])

    def test_dry_run_false_refused_when_not_ready(self) -> None:
        for world in (release_world(files={"docs/release/0.1.0.md": "verdict: hold\n"}),
                      release_world(pr_files=["docs/release/0.1.0.md", "packages/core/src/x.ts"])):
            with self.subTest():
                g = leased(world)
                self.assertEqual(run(g, "dispatch-release", "--holder", HOLDER, "--version", "0.1.0", "--dry-run", "false"), 2)
                self.assertEqual(g.dispatches, [])
                self.assertEqual(g.mutations(), [])

    def test_dry_run_false_dispatched_when_ready(self) -> None:
        g = leased(release_world())
        self.assertEqual(run(g, "dispatch-release", "--holder", HOLDER, "--version", "0.1.0", "--dry-run", "false"), 0)
        self.assertEqual(g.dispatches, [("release.yml", "main", {"dry_run": "false", "version": "0.1.0"})])

    def test_bad_release_arguments(self) -> None:
        g = leased(release_world())
        for version, dry in [("0.2.0", "false"), ("v0.1.0", "true"), ("0.1", "true"), ("0.1.0", "yes"),
                             ("0.1.0", "False"), ("0.1.0", "")]:
            with self.subTest(version=version, dry=dry):
                self.assertEqual(run(g, "dispatch-release", "--holder", HOLDER, "--version", version, "--dry-run", dry), 2)
        self.assertEqual(g.dispatches, [])

    def test_dispatch_proof_validates_stage(self) -> None:
        g = leased(FakeGitHub())
        self.assertEqual(run(g, "dispatch-proof", "--holder", HOLDER, "--stage", "6"), 2)
        self.assertEqual(run(g, "dispatch-proof", "--holder", HOLDER, "--stage", "2a"), 0)
        self.assertEqual(g.dispatches, [("proof.yml", "main", {"stage": "2a"})])


if __name__ == "__main__":
    unittest.main()
