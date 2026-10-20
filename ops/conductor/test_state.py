"""Tests of state.py: ready queue, dependencies, path overlap, PR status, milestones, release readiness, forecast."""

from __future__ import annotations

import json
import unittest

import state
from fake_github import FakeGitHub

NOW = 1_800_000_000.0
DAY = 86400.0
MAIN_SHA = "a" * 40


def iso(epoch: float) -> str:
    """Render epoch seconds as a GitHub timestamp."""
    import datetime
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unit(number: int, deps=(), paths=("packages/core/src/x/a.ts",), labels=(), state_="open", reason=None,
         kind="build", slice_="S1", proof=(), tags=(), header=True) -> dict:
    """Build a unit issue with a hidden header."""
    head = {"kind": kind, "slice": slice_, "deps": list(deps), "paths": list(paths), "proof": list(proof),
            "risk": "low", "tags": list(tags)}
    body = (f"<!-- unit: {json.dumps(head)} -->\nOutcome." if header else "no header")
    return {"number": number, "title": f"unit {number}", "state": state_, "state_reason": reason, "body": body,
            "labels": [{"name": "unit"}] + [{"name": n} for n in labels]}


def pr(number: int, head: str, sha: str, auto=False, mergeable=True, mstate="clean", merged_at=None) -> dict:
    """Build a pull request object."""
    return {"number": number, "head": {"ref": head, "sha": sha, "repo": {"full_name": "ahlerjam/academic-research"}},
            "base": {"ref": "main"}, "state": "open" if not merged_at else "closed", "draft": False,
            "mergeable": mergeable, "mergeable_state": mstate, "auto_merge": {"merge_method": "merge"} if auto else None,
            "merged_at": merged_at}


def checks(*rows) -> dict:
    """Build a check-runs answer from (name, status, conclusion) rows."""
    return {"check_runs": [{"name": n, "status": s, "conclusion": c} for n, s, c in rows]}


def runs_path(workflow: str) -> str:
    """Return the dispatched-runs listing path state.py reads for a workflow."""
    return f"actions/workflows/{workflow}/runs?branch=main&event=workflow_dispatch&per_page=100"


def world(units, prs=(), merged=(), progress=None, status_labels=(), legacy=(), files=None, release=None,
          runs=None, main_sha=MAIN_SHA) -> FakeGitHub:
    """Build a fake GitHub with the given objects and empty defaults for everything else."""
    g = FakeGitHub()
    g.set("issues?state=all&labels=unit", list(units))
    g.set("pulls?state=open&base=main", [p for p, _ in prs])
    for p, chk in prs:
        g.set(f"pulls/{p['number']}", p)
        g.set(f"commits/{p['head']['sha']}/check-runs", chk)
        g.set(f"commits/{p['head']['sha']}/status", {"statuses": []})
    g.set("pulls?state=closed&base=main&sort=updated&direction=desc", list(merged))
    status_issue = {"number": 5, "title": "Conductor status", "state": "open",
                    "labels": [{"name": "conductor"}] + [{"name": n} for n in status_labels]}
    g.set("issues?state=open&labels=conductor", [status_issue])
    g.set("issues?state=open&labels=needs-operator", list(legacy))
    if progress is not None:
        g.set_file("docs/autonomy/progress.json", "conductor/state", json.dumps(progress))
    for path, text in (files or {}).items():
        g.set_file(path, "main", text)
    if release is not None:
        g.set("releases/tags/v0.1.0", release)
    for workflow, rows in (runs or {}).items():
        g.set(runs_path(workflow), {"total_count": len(rows), "workflow_runs": list(rows)})
    if main_sha:
        g.set("commits/main", {"sha": main_sha})
    return g


def proof_run(run_id: int, stage: str, branch="main", conclusion="success", path=".github/workflows/proof.yml",
              created=NOW - DAY, status="completed") -> dict:
    """Build an Actions run of proof.yml with the run name `proof stage <s>`."""
    return {"id": run_id, "path": path, "head_branch": branch, "event": "workflow_dispatch", "status": status,
            "conclusion": conclusion if status == "completed" else None, "display_title": f"proof stage {stage}",
            "html_url": f"https://x/runs/{run_id}", "created_at": iso(created), "head_sha": MAIN_SHA}


def dry_run(run_id: int = 200, conclusion="success", sha=MAIN_SHA, title="release 0.1.0 dry_run=true",
            status="completed") -> dict:
    """Build a release.yml run with the run name release.yml sets (a dry run unless the title says otherwise)."""
    return {"id": run_id, "path": ".github/workflows/release.yml", "head_branch": "main", "event": "workflow_dispatch",
            "status": status, "conclusion": conclusion if status == "completed" else None, "display_title": title,
            "head_sha": sha, "created_at": iso(NOW - 3600), "html_url": f"https://x/runs/{run_id}"}


CFG = state.load_config()


class ReadyQueue(unittest.TestCase):
    """Dependencies, blocking labels, cycles and headers decide what is ready."""

    def test_dependencies_decide_ready_and_blocked(self) -> None:
        g = world([unit(1), unit(2, deps=[1]), unit(3, deps=[10]), unit(4, deps=[11]), unit(5, deps=[999]),
                   unit(10, state_="closed", reason="completed"), unit(11, state_="closed", reason="not_planned")])
        s = state.compute(g, CFG, NOW)
        self.assertEqual(sorted(s["ready"]), [1, 3])
        why = {b["unit"]: b["blocked_by"] for b in s["blocked"]}
        self.assertEqual(why[2], [{"issue": 1, "status": "open"}])
        self.assertEqual(why[4], [{"issue": 11, "status": "dropped"}])
        self.assertEqual(why[5], [{"issue": 999, "status": "missing"}])

    def test_dependency_outside_the_unit_list_is_read_individually(self) -> None:
        g = world([unit(1, deps=[50])])
        g.set("issues/50", {"number": 50, "state": "closed", "state_reason": "completed", "labels": []})
        self.assertEqual(state.compute(g, CFG, NOW)["ready"], [1])

    def test_needs_operator_parked_stuck_and_missing_header_block(self) -> None:
        g = world([unit(1, labels=["needs-operator"]), unit(2, labels=["state:parked"]),
                   unit(3, labels=["state:stuck"]), unit(4, header=False), unit(6)])
        s = state.compute(g, CFG, NOW)
        self.assertEqual(s["ready"], [6])
        self.assertEqual({b["unit"]: b["why"] for b in s["blocked"]}[4], "no unit header")

    def test_cycle_blocks_its_members(self) -> None:
        g = world([unit(1, deps=[2]), unit(2, deps=[1]), unit(3)])
        s = state.compute(g, CFG, NOW)
        self.assertEqual(s["cycles"], [[1, 2]])
        self.assertEqual(s["ready"], [3])

    def test_longest_remaining_path_goes_first(self) -> None:
        g = world([unit(1, paths=["a/**"]), unit(2, paths=["b/**"]), unit(3, deps=[2], paths=["c/**"]),
                   unit(4, deps=[3], paths=["d/**"])])
        s = state.compute(g, CFG, NOW)
        self.assertEqual(s["ready"], [2, 1])
        self.assertEqual([u["number"] for u in s["pick"]], [2])

    def test_critic_s1_beats_path_weight(self) -> None:
        g = world([unit(1, paths=["a/**"]), unit(2, deps=[1], paths=["b/**"]),
                   unit(7, labels=["critic", "sev:S1"], paths=["c/**"])])
        self.assertEqual(state.compute(g, CFG, NOW)["ready"][0], 7)


class PathOverlap(unittest.TestCase):
    """Two units with overlapping paths never run together."""

    def test_overlapping_globs(self) -> None:
        self.assertTrue(state.paths_overlap(["packages/core/**"], ["packages/core/src/x.ts"]))
        self.assertTrue(state.paths_overlap(["packages/*/test/**"], ["packages/web/test/a.test.ts"]))
        self.assertFalse(state.paths_overlap(["packages/core/**"], ["packages/web/**"]))
        self.assertTrue(state.paths_overlap([], ["packages/web/**"]))

    def test_overlap_with_unit_in_flight_defers(self) -> None:
        many = [pr(80 + i, f"claude/unit-{40 + i}-x", f"m{i}", merged_at=iso(NOW - DAY)) for i in range(3)]
        g = world([unit(1, labels=["state:building"], paths=["packages/core/**"]),
                   unit(2, paths=["packages/core/src/a.ts"]), unit(3, paths=["packages/web/**"])], merged=many)
        s = state.compute(g, CFG, NOW)
        self.assertEqual([u["unit"] for u in s["in_flight"]], [1])
        self.assertEqual([u["number"] for u in s["pick"]], [3])
        self.assertEqual(s["deferred_overlap"], [2])

    def test_two_ready_units_with_overlap_never_picked_together(self) -> None:
        many = [pr(80 + i, f"claude/unit-{40 + i}-x", f"m{i}", merged_at=iso(NOW - DAY)) for i in range(3)]
        g = world([unit(1, paths=["packages/server/src/a/**"]), unit(2, paths=["packages/server/src/a/api.ts"])],
                  merged=many)
        s = state.compute(g, CFG, NOW)
        self.assertEqual(s["wip"], 2)
        self.assertEqual(len(s["pick"]), 1)
        self.assertEqual(len(s["deferred_overlap"]), 1)

    def test_wip_is_one_until_three_merges(self) -> None:
        g = world([unit(1, paths=["a/**"]), unit(2, paths=["b/**"])])
        s = state.compute(g, CFG, NOW)
        self.assertEqual((s["wip"], len(s["pick"])), (1, 1))

    def test_open_unit_pr_counts_as_in_flight(self) -> None:
        g = world([unit(1, paths=["a/**"]), unit(2, paths=["b/**"])],
                  prs=[(pr(30, "claude/unit-1-x", "s1"), checks(("gate", "in_progress", None)))])
        s = state.compute(g, CFG, NOW)
        self.assertEqual([u["unit"] for u in s["in_flight"]], [1])
        self.assertEqual(s["slots"], 0)
        self.assertEqual(s["pick"], [])


class PullRequests(unittest.TestCase):
    """Check runs reduce to one verdict and one next action per PR."""

    def test_verdicts(self) -> None:
        req = ["gate", "protect"]
        green = [{"name": "gate", "status": "completed", "conclusion": "success"},
                 {"name": "protect", "status": "completed", "conclusion": "success"}]
        self.assertEqual(state.check_verdict(green, [], req)[0], "green")
        self.assertEqual(state.check_verdict(green[:1], [], req), ("pending", {"gate": "pass", "protect": "missing"}))
        red = green + [{"name": "ts", "status": "completed", "conclusion": "failure"}]
        self.assertEqual(state.check_verdict(red, [], req)[0], "red")
        self.assertEqual(state.check_verdict(green[:1] + [{"name": "protect", "status": "completed",
                                                           "conclusion": "cancelled"}], [], req)[0], "infra")
        self.assertEqual(state.check_verdict(green[:1], [{"context": "protect", "state": "success"}], req)[0], "green")

    def test_actions_per_pr(self) -> None:
        ok = checks(("gate", "completed", "success"), ("protect", "completed", "success"))
        g = world([unit(1, paths=["a/**"]), unit(2, paths=["b/**"]), unit(3, paths=["c/**"])],
                  prs=[(pr(31, "claude/unit-1-a", "s1"), ok),
                       (pr(32, "claude/unit-2-b", "s2", auto=True), ok),
                       (pr(33, "claude/unit-3-c", "s3"), checks(("gate", "completed", "failure")))])
        s = state.compute(g, CFG, NOW)
        by = {p["number"]: p for p in s["prs"]}
        self.assertEqual(by[31]["action"], "enable-auto-merge")
        self.assertTrue(by[31]["merge_ready"])
        self.assertEqual(by[32]["action"], "wait")
        self.assertEqual(by[33]["action"], "fix")
        self.assertEqual(s["next"][0], {"do": "enable-auto-merge", "pr": 31, "unit": 1})

    def test_non_claude_heads_and_forks_are_ignored(self) -> None:
        fork = pr(41, "claude/unit-1-a", "f1")
        fork["head"]["repo"] = {"full_name": "someone/fork"}
        g = world([unit(1)], prs=[(pr(40, "feature/x", "x1"), checks()), (fork, checks())])
        self.assertEqual(state.compute(g, CFG, NOW)["prs"], [])

    def test_conflict(self) -> None:
        ok = checks(("gate", "completed", "success"), ("protect", "completed", "success"))
        g = world([unit(1)], prs=[(pr(31, "claude/unit-1-a", "s1", mergeable=False, mstate="dirty"), ok)])
        self.assertEqual(state.compute(g, CFG, NOW)["prs"][0]["action"], "conflict")


class Milestones(unittest.TestCase):
    """A stage is green only by its newest completed, successful, dispatched `proof stage <s>` run on main."""

    def test_stage_status(self) -> None:
        self.assertTrue(state.stage_status("1", proof_run(1, "1"), "proof.yml", "main")["green"])
        self.assertFalse(state.stage_status("1", proof_run(1, "1", branch="claude/x"), "proof.yml", "main")["green"])
        self.assertFalse(state.stage_status("1", proof_run(1, "1", conclusion="failure"), "proof.yml", "main")["green"])
        self.assertFalse(state.stage_status("2a", proof_run(1, "1"), "proof.yml", "main")["green"])
        self.assertFalse(state.stage_status("1", proof_run(1, "1", path=".github/workflows/ci.yml"), "proof.yml", "main")["green"])
        self.assertFalse(state.stage_status("1", None, "proof.yml", "main")["green"])

    def test_dispatch_proof_only_after_units_of_the_stage_are_done(self) -> None:
        g = world([unit(1, proof=["S1-QUOTE-EXACT"], state_="closed", reason="completed")])
        steps = state.compute(g, CFG, NOW)["next"]
        self.assertIn({"do": "dispatch-proof", "stage": "1"}, steps)
        self.assertNotIn({"do": "dispatch-proof", "stage": "2a"}, steps)
        g = world([unit(1, proof=["S1-QUOTE-EXACT"], state_="closed", reason="completed"), unit(2, proof=["S1-HOVER-PAGE"])])
        self.assertNotIn({"do": "dispatch-proof", "stage": "1"}, state.compute(g, CFG, NOW)["next"])

    def test_newest_completed_run_decides(self) -> None:
        rows = [proof_run(1, "1", created=NOW - 3 * DAY), proof_run(2, "1", conclusion="failure", created=NOW - DAY)]
        s = state.compute(world([unit(1, state_="closed", reason="completed")], runs={"proof.yml": rows}), CFG, NOW)
        self.assertFalse(s["milestones"][0]["green"], "a newer red run beats an older green one")
        rows = [proof_run(1, "1", conclusion="failure", created=NOW - 3 * DAY), proof_run(2, "1", created=NOW - DAY)]
        s = state.compute(world([unit(1, state_="closed", reason="completed")], runs={"proof.yml": rows}), CFG, NOW)
        self.assertTrue(s["milestones"][0]["green"])

    def test_running_proof_is_not_dispatched_again(self) -> None:
        rows = [proof_run(3, "1", status="in_progress", created=NOW - 60)]
        g = world([unit(1, proof=["S1-QUOTE-EXACT"], state_="closed", reason="completed")], runs={"proof.yml": rows})
        s = state.compute(g, CFG, NOW)
        self.assertTrue(s["milestones"][0]["running"])
        self.assertNotIn({"do": "dispatch-proof", "stage": "1"}, s["next"])

    def test_other_run_names_do_not_count(self) -> None:
        other = dict(proof_run(4, "1"), display_title="proof")
        s = state.compute(world([unit(1)], runs={"proof.yml": [other]}), CFG, NOW)
        self.assertFalse(s["milestones"][0]["green"])


def release_world(**over) -> FakeGitHub:
    """A world in which every release condition holds unless overridden."""
    proofs = [proof_run(100 + i, s) for i, s in enumerate(CFG["stages"])] + over.pop("extra_proofs", [])
    releases = over.pop("dry", [dry_run()])
    files = {"CHANGELOG.md": "# Changelog\n\n## [0.1.0] - 2026-11-30\n- first\n",
             "docs/release/0.1.0.md": "# Release 0.1.0\n\nverdict: release\n"}
    files.update(over.pop("files", {}))
    for path in over.pop("drop_files", []):
        files.pop(path)
    units = [unit(1, state_="closed", reason="completed")] + over.pop("units", [])
    return world(units, progress={"limit_stops": 0}, files=files,
                 runs={"proof.yml": proofs, "release.yml": releases}, release=over.pop("release", None),
                 main_sha=over.pop("main_sha", MAIN_SHA))


class Release(unittest.TestCase):
    """release_ready is the AND of proofs, changelog, verdict, dry run of main's head and not-yet-released."""

    def test_all_conditions_hold(self) -> None:
        s = state.compute(release_world(), CFG, NOW)
        self.assertTrue(s["release"]["release_ready"], s["release"])
        self.assertEqual(s["next"][0], {"do": "dispatch-release", "dry_run": False, "version": "0.1.0"})

    def test_each_missing_condition_blocks(self) -> None:
        cases = {
            "changelog_entry": [{"files": {"CHANGELOG.md": "# Changelog\n## [0.0.9]\n"}},
                                {"files": {"CHANGELOG.md": "# Changelog\n### 0.1.0\n"}}],
            "judge_verdict": [{"files": {"docs/release/0.1.0.md": "verdict: fix\n"}},
                              {"files": {"docs/release/0.1.0.md": "verdict: release\nverdict: hold\n"}},
                              {"files": {"docs/release/0.1.0.md": "  verdict: release\n"}}],
            "dry_run_green": [{"dry": [dry_run(conclusion="failure")]},
                              {"dry": [dry_run(sha="b" * 40)]},
                              {"dry": [dry_run(title="release 0.1.0 dry_run=false")]},
                              {"dry": [dry_run(title="release 0.2.0 dry_run=true")]},
                              {"dry": []},
                              {"main_sha": None}],
            "not_yet_released": [{"release": {"tag_name": "v0.1.0", "draft": False, "prerelease": False}}],
        }
        for key, overs in cases.items():
            for over in overs:
                with self.subTest(key=key, over=over):
                    s = state.compute(release_world(**dict(over)), CFG, NOW)
                    self.assertFalse(s["release"]["release_ready"])
                    self.assertFalse(s["release"]["checks"][key])

    def test_missing_verdict_file_blocks(self) -> None:
        s = state.compute(release_world(drop_files=["docs/release/0.1.0.md"]), CFG, NOW)
        self.assertFalse(s["release"]["checks"]["judge_verdict"])

    def test_one_red_stage_blocks(self) -> None:
        g = release_world(extra_proofs=[proof_run(150, "2a", conclusion="failure", created=NOW - 60)])
        s = state.compute(g, CFG, NOW)
        self.assertFalse(s["release"]["checks"]["proofs_green"])
        self.assertFalse(s["release"]["release_ready"])

    def test_goal_met_after_release(self) -> None:
        s = state.compute(release_world(release={"tag_name": "v0.1.0", "draft": False, "prerelease": False}), CFG, NOW)
        self.assertTrue(s["goal_met"])
        self.assertEqual(s["next"][0]["do"], "stop")

    def test_draft_release_is_not_released(self) -> None:
        s = state.compute(release_world(release={"tag_name": "v0.1.0", "draft": True}), CFG, NOW)
        self.assertFalse(s["goal_met"])

    def test_release_prep_only_on_a_quiet_main(self) -> None:
        s = state.compute(release_world(dry=[]), CFG, NOW)
        self.assertEqual(s["next"][0], {"do": "release-prep", "missing": ["dry_run_green"]})
        self.assertNotIn("plan", [x["do"] for x in s["next"]], "no new slice is planned once every proof is green")
        busy = state.compute(release_world(dry=[], units=[unit(7, paths=["a/**"])]), CFG, NOW)
        self.assertNotIn("release-prep", [x["do"] for x in busy["next"]])
        self.assertEqual(busy["next"][0]["do"], "start-unit")

    def test_nothing_is_dispatched_while_release_runs(self) -> None:
        s = state.compute(release_world(dry=[dry_run(status="in_progress")]), CFG, NOW)
        self.assertTrue(s["release"]["running"])
        self.assertEqual(s["next"], [{"do": "wait", "why": "release.yml is running"}])
        real = release_world(dry=[dry_run(), dry_run(201, title="release 0.1.0 dry_run=false", status="queued")])
        s = state.compute(real, CFG, NOW)
        self.assertTrue(s["release"]["release_ready"])
        self.assertNotIn("dispatch-release", [x["do"] for x in s["next"]])

    def test_red_dry_run_of_the_head_is_named_once(self) -> None:
        s = state.compute(release_world(dry=[dry_run(conclusion="failure")]), CFG, NOW)
        self.assertEqual(s["next"][0], {"do": "release-prep", "missing": ["dry_run_green"], "dry_run_red": "https://x/runs/200"})
        older = state.compute(release_world(dry=[dry_run(conclusion="failure", sha="b" * 40)]), CFG, NOW)
        self.assertEqual(older["next"][0], {"do": "release-prep", "missing": ["dry_run_green"]})


class Operator(unittest.TestCase):
    """Kill switch and legacy needs-operator tickets."""

    def test_pause_label_stops_everything(self) -> None:
        g = world([unit(1)], status_labels=["conductor:pause"])
        s = state.compute(g, CFG, NOW)
        self.assertTrue(s["paused"])
        self.assertEqual([x["do"] for x in s["next"]], ["pause"])

    def test_legacy_tickets_clear_except_the_anthropic_request(self) -> None:
        legacy = [{"number": 99, "title": "OP-1", "state": "open", "labels": [{"name": "needs-operator"}]},
                  {"number": 120, "title": "Ask Anthropic", "state": "open",
                   "labels": [{"name": "needs-operator"}, {"name": "op:external"}]},
                  {"number": 121, "title": "unit", "state": "open", "labels": [{"name": "needs-operator"}, {"name": "unit"}]}]
        s = state.compute(world([unit(1)], legacy=legacy), CFG, NOW)
        self.assertEqual(s["legacy_operator"], [{"number": 99, "title": "OP-1", "action": "clear"},
                                                {"number": 120, "title": "Ask Anthropic", "action": "keep"}])
        self.assertIn({"do": "clear-needs-operator", "issues": [99]}, s["next"])

    def test_plan_when_nothing_is_open(self) -> None:
        s = state.compute(world([]), CFG, NOW)
        self.assertIn({"do": "plan", "why": "no ready, running or open unit"}, s["next"])


class Forecast(unittest.TestCase):
    """Units per day over the window and days left."""

    def test_rate_and_days(self) -> None:
        fc = state.forecast([NOW - DAY, NOW - 2 * DAY, NOW - 3 * DAY, NOW - 30 * DAY], NOW, 7, 6, 21, 2)
        self.assertEqual(fc["merged_in_window"], 3)
        self.assertEqual(fc["units_per_day"], 0.43)
        self.assertEqual(fc["days_to_next_milestone"], 14.0)
        self.assertEqual(fc["days_to_v0_1"], 48.8)
        self.assertEqual(fc["limit_stops"], 2)

    def test_no_rate_no_days(self) -> None:
        self.assertIsNone(state.forecast([], NOW, 7, 3, 3, 0)["days_to_v0_1"])

    def test_status_body_names_forecast_and_pause(self) -> None:
        body = state.render_status(state.compute(world([unit(1)], progress={"limit_stops": 4}), CFG, NOW))
        self.assertIn("Units merged per day", body)
        self.assertIn("Usage-limit stops recorded: 4", body)
        self.assertIn("conductor:pause", body)


if __name__ == "__main__":
    unittest.main()
