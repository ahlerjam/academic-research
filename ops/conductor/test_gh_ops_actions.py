"""Tests of gh_ops.py apply-actions and the inbox target: validated as a whole, filed in order, never twice."""

from __future__ import annotations

import json
import os
import unittest

import gh_ops
from fake_github import FakeGitHub
from test_gh_ops import HOLDER, Files, leased, run

CARD = '<!-- unit: {"kind":"build","slice":"S1","deps":[{{c1}}],"paths":["a/**"],"proof":[],"risk":"low","tags":[]} -->\nOutcome.'
STATUS = {"number": 7, "state": "open", "title": "Conductor status", "author_association": "OWNER",
          "labels": [{"name": "conductor"}, {"name": "conductor:pause"}]}


def actions(*rows: dict) -> dict:
    """Wrap rows into an action file object."""
    return {"actions": list(rows)}


def world() -> FakeGitHub:
    """A fake with two existing issues, the lead's lease and no inbox."""
    g = leased(FakeGitHub())
    g.set("issues/40", {"number": 40, "state": "open", "labels": [{"name": "unit"}], "author_association": "OWNER"})
    g.set("issues/41", {"number": 41, "state": "open", "labels": [], "author_association": "OWNER"})
    g.set("issues/7", STATUS)
    g.set("issues?state=open&labels=conductor", [STATUS])
    return g


def apply(g: FakeGitHub, path: str) -> int:
    """Run apply-actions as the lease holder."""
    return run(g, "apply-actions", "--holder", HOLDER, "--file", path)


class ApplyActions(Files):
    """The lead files a workflow's actions through one validated verb."""

    def write(self, data: object, name: str = "actions.json") -> str:
        """Write an action file."""
        return self.file(json.dumps(data), name)

    def test_cards_in_order_with_placeholders(self) -> None:
        g = world()
        path = self.write(actions(
            {"verb": "create-issue", "ref": "c1", "title": "Unit one", "body": "first", "labels": ["unit", "kind:build"]},
            {"verb": "create-issue", "ref": "c2", "title": "Unit two after #{{c1}}", "body": CARD, "labels": ["unit"]},
            {"verb": "comment", "issue": 41, "body": "Replaced by #{{c1}} and #{{c2}}."},
            {"verb": "label", "ref": "c2", "add": ["state:blocked"]},
            {"verb": "close-issue", "issue": 40, "reason": "completed", "body": "Covered by #{{c2}}."}))
        self.assertEqual(apply(g, path), 0)
        posts = [(m, p.split("/", 3)[3], b) for m, p, b in g.mutations()]
        self.assertEqual(posts[0], ("POST", "issues", {"title": "Unit one", "body": "first", "labels": ["unit", "kind:build"]}))
        self.assertEqual(posts[1][2]["title"], "Unit two after #901")
        self.assertIn('"deps":[901]', posts[1][2]["body"])
        self.assertEqual(posts[2], ("POST", "issues/41/comments", {"body": "Replaced by #901 and #902."}))
        self.assertEqual(posts[3], ("POST", "issues/902/labels", {"labels": ["state:blocked"]}))
        self.assertEqual(posts[4], ("POST", "issues/40/comments", {"body": "Covered by #902."}))
        self.assertEqual(posts[5], ("PATCH", "issues/40", {"state": "closed", "state_reason": "completed"}))
        self.assertEqual(len(posts), 6)

    def test_whole_list_is_refused_before_anything_is_sent(self) -> None:
        bad = {
            "unknown verb": {"verb": "merge", "issue": 1, "body": "x"},
            "forward ref": {"verb": "comment", "ref": "later", "body": "x"},
            "forward placeholder": {"verb": "comment", "issue": 41, "body": "see #{{later}}"},
            "unknown label": {"verb": "label", "issue": 41, "add": ["no-such-label"]},
            "needs-operator removal": {"verb": "label", "issue": 41, "remove": ["needs-operator"]},
            "pause removal": {"verb": "label", "issue": 41, "remove": ["conductor:pause"]},
            "conductor removal": {"verb": "label", "issue": 40, "remove": ["conductor"]},
            "op:external removal": {"verb": "label", "issue": 40, "remove": ["op:external"]},
            "op:kernel removal": {"verb": "label", "issue": 40, "remove": ["op:kernel"]},
            "conductor added": {"verb": "label", "issue": 40, "add": ["conductor"]},
            "bad reason": {"verb": "close-issue", "issue": 41, "reason": "merged", "body": "x"},
            "empty body": {"verb": "comment", "issue": 41, "body": " "},
            "two targets": {"verb": "comment", "issue": 41, "inbox": True, "body": "x"},
            "no target": {"verb": "comment", "body": "x"},
            "bad ref": {"verb": "create-issue", "ref": "Bad Ref", "title": "t", "body": "x"},
            "multi-line title": {"verb": "create-issue", "ref": "c9", "title": "a\nb", "body": "x"},
        }
        for name, row in bad.items():
            with self.subTest(case=name):
                g = world()
                first = {"verb": "create-issue", "ref": "c1", "title": "ok", "body": "ok", "labels": ["unit"]}
                path = self.write(actions(first, row), f"{name.replace(' ', '-').replace(':', '-')}.json")
                self.assertEqual(apply(g, path), 2)
                self.assertEqual(g.mutations(), [])
                self.assertFalse(os.path.exists(path + ".done.json"))

    def test_model_chosen_targets_must_be_trusted_unit_critic_or_hypothesis_issues(self) -> None:
        targets = {
            "status issue with the kill switch": STATUS,
            "inbox": {"number": 7, "state": "open", "title": "Operator-Inbox", "labels": [{"name": "conductor"}],
                      "author_association": "OWNER"},
            "Anthropic request": {"number": 7, "state": "open", "title": "Anthropic request: use of the Claude plan",
                                  "labels": [{"name": "needs-operator"}, {"name": "op:external"}],
                                  "author_association": "OWNER"},
            "kernel item": {"number": 7, "state": "open", "title": "x", "labels": [{"name": "unit"}, {"name": "op:kernel"}],
                            "author_association": "OWNER"},
            "needs-operator ticket": {"number": 7, "state": "open", "title": "x", "author_association": "OWNER",
                                      "labels": [{"name": "type:feature"}, {"name": "needs-operator"}]},
            "outsider feature issue": {"number": 7, "state": "open", "title": "x", "author_association": "OWNER",
                                       "labels": [{"name": "type:feature"}]},
            "unlabelled outsider issue": {"number": 7, "state": "open", "title": "x", "labels": [],
                                          "author_association": "OWNER"},
            "unit card of an outsider": {"number": 7, "state": "open", "title": "x", "labels": [{"name": "unit"}],
                                         "author_association": "NONE"},
            "hypothesis of a contributor": {"number": 7, "state": "open", "title": "x", "author_association": "CONTRIBUTOR",
                                            "labels": [{"name": "hypothesis"}, {"name": "slice:S1"}]},
            "unit card without author": {"number": 7, "state": "open", "title": "x", "labels": [{"name": "unit"}]},
            "pull request": {"number": 7, "state": "open", "title": "x", "labels": [{"name": "unit"}], "pull_request": {},
                             "author_association": "OWNER"},
        }
        rows = ({"verb": "close-issue", "issue": 7, "reason": "completed", "body": "No longer reproduces."},
                {"verb": "label", "issue": 7, "add": ["state:ready"], "remove": ["state:building"]})
        for name, issue in targets.items():
            for row in rows:
                with self.subTest(target=name, verb=row["verb"]):
                    g = world()
                    g.set("issues/7", issue)
                    first = {"verb": "create-issue", "ref": "c1", "title": "ok", "body": "ok", "labels": ["unit"]}
                    path = self.write(actions(first, row), f"t-{len(name)}-{row['verb']}.json")
                    self.assertEqual(apply(g, path), 2)
                    self.assertEqual(g.mutations(), [])
        for author in ("OWNER", "MEMBER", "COLLABORATOR"):
            for labels in ([{"name": "unit"}], [{"name": "critic"}], [{"name": "hypothesis"}], [{"name": "slice:S1"}]):
                with self.subTest(allowed=labels[0]["name"], author=author):
                    g = world()
                    g.set("issues/9", {"number": 9, "state": "open", "title": "x", "labels": labels,
                                       "author_association": author})
                    path = self.write(actions({"verb": "close-issue", "issue": 9, "reason": "completed", "body": "done"}),
                                      f"ok-{author}-{labels[0]['name'].replace(':', '-')}.json")
                    self.assertEqual(apply(g, path), 0)

    def test_duplicate_ref_and_too_many_actions_are_refused(self) -> None:
        row = {"verb": "create-issue", "ref": "c1", "title": "t", "body": "x"}
        self.assertEqual(apply(world(), self.write(actions(row, row), "dup.json")), 2)
        many = [{"verb": "comment", "issue": 41, "body": "x"}] * (gh_ops.MAX_ACTIONS + 1)
        self.assertEqual(apply(world(), self.write(actions(*many), "many.json")), 2)
        self.assertEqual(apply(world(), self.write({"cards": []}, "shape.json")), 2)

    def test_rerun_after_an_error_files_nothing_twice(self) -> None:
        g = world()
        path = self.write(actions(
            {"verb": "create-issue", "ref": "c1", "title": "Unit one", "body": "first"},
            {"verb": "comment", "ref": "c1", "body": "hello"}))
        g.fail("POST", "issues/901/comments", 502)
        self.assertEqual(apply(g, path), 1)
        with open(path + ".done.json", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["done"], 1)
        g.failures.clear()
        self.assertEqual(apply(g, path), 0)
        creates = [c for c in g.mutations() if c[0] == "POST" and c[1].endswith("/issues")]
        self.assertEqual(len(creates), 1, "the card was filed once")
        self.assertEqual(g.mutations()[-1][1].split("/", 3)[3], "issues/901/comments")
        self.assertEqual(apply(g, path), 0)
        self.assertEqual(len(g.mutations()), 3, "a finished file sends nothing more")

    def test_changed_file_after_a_partial_run_is_refused(self) -> None:
        g = world()
        path = self.write(actions({"verb": "create-issue", "ref": "c1", "title": "one", "body": "x"},
                                  {"verb": "comment", "ref": "c1", "body": "y"}))
        g.fail("POST", "issues/901/comments", 502)
        self.assertEqual(apply(g, path), 1)
        self.write(actions({"verb": "create-issue", "ref": "c1", "title": "other", "body": "x"}))
        before = len(g.mutations())
        self.assertEqual(apply(g, path), 2)
        self.assertEqual(len(g.mutations()), before)


class Inbox(Files):
    """The Operator-Inbox issue is found by its title among the lead's conductor issues or created once."""

    def test_inbox_is_created_when_missing(self) -> None:
        g = world()
        path = self.file(json.dumps(actions({"verb": "comment", "inbox": True, "body": "kernel patch"})), "a.json")
        self.assertEqual(apply(g, path), 0)
        create, note = g.mutations()
        self.assertEqual(create[2]["title"], "Operator-Inbox")
        self.assertEqual(create[2]["labels"], ["conductor"])
        self.assertEqual(note[1].split("/", 3)[3], "issues/901/comments")

    def test_existing_inbox_gets_the_comment(self) -> None:
        g = world()
        g.set("issues?state=open&labels=conductor", [STATUS, {"number": 12, "title": "Operator-Inbox",
                                                              "labels": [{"name": "conductor"}]}])
        self.assertEqual(run(g, "comment", "--holder", HOLDER, "--issue", "inbox", "--body-file", self.file("patch")), 0)
        self.assertEqual([c[1].split("/", 3)[3] for c in g.mutations()], ["issues/12/comments"])

    def test_an_outsider_issue_with_the_inbox_title_is_never_used(self) -> None:
        g = world()
        g.set("issues?state=open", [{"number": 3, "title": "Operator-Inbox", "labels": [], "user": {"login": "outsider"}}])
        self.assertEqual(run(g, "comment", "--holder", HOLDER, "--issue", "inbox", "--body-file", self.file("patch")), 0)
        create, note = g.mutations()
        self.assertEqual((create[1].split("/", 3)[3], create[2]["labels"]), ("issues", ["conductor"]))
        self.assertEqual(note[1].split("/", 3)[3], "issues/901/comments")

    def test_comment_needs_a_number_or_inbox(self) -> None:
        self.assertEqual(run(world(), "comment", "--holder", HOLDER, "--issue", "operator", "--body-file", self.file("x")), 2)


class KillSwitch(Files):
    """A workflow result can neither close the status issue nor strip its labels (reproduction of the finding)."""

    def test_closing_the_paused_status_issue_is_refused_and_sends_nothing(self) -> None:
        for row in ({"verb": "close-issue", "issue": 7, "reason": "completed", "body": "No longer reproduces."},
                    {"verb": "label", "issue": 7, "remove": ["conductor"]},
                    {"verb": "label", "issue": 7, "remove": ["conductor:pause"]}):
            with self.subTest(row=row):
                g = world()
                path = self.file(json.dumps(actions(row)), f"k-{row['verb']}-{len(row)}.json")
                self.assertEqual(apply(g, path), 2)
                self.assertEqual(g.mutations(), [])
        g = world()
        self.assertEqual(run(g, "close-issue", "--holder", HOLDER, "--issue", "7", "--reason", "completed",
                             "--comment-file", self.file("x")), 2)
        self.assertEqual(g.mutations(), [])


if __name__ == "__main__":
    unittest.main()
