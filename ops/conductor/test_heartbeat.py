"""Tests of heartbeat.py against a throwaway bare origin: lease takeover only after lease_max_age_s, never main, no force."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest

import heartbeat
import state

CFG = state.load_config()
T0 = 1_800_000_000.0
HOUR = 3600.0
LEASE = float(CFG["lease_max_age_s"])


def sh(cwd: str, *args: str) -> str:
    """Run git and return stdout, failing the test on error."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


class Origin(unittest.TestCase):
    """A bare origin with main and two clones, as two lead sessions would have."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.origin = os.path.join(root, "origin.git")
        sh(root, "init", "-q", "--bare", "-b", "main", self.origin)
        self.a = self.clone("a")
        with open(os.path.join(self.a, "README.md"), "w", encoding="utf-8") as handle:
            handle.write("x\n")
        sh(self.a, "add", "README.md")
        sh(self.a, "commit", "-q", "-m", "init")
        sh(self.a, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.main_sha = sh(self.a, "rev-parse", "HEAD")
        self.b = self.clone("b")

    def clone(self, name: str) -> str:
        """Clone the origin with a local identity and no signing and return its path."""
        path = os.path.join(self.tmp.name, name)
        sh(self.tmp.name, "clone", "-q", self.origin, path)
        sh(path, "config", "user.name", f"lead {name}")
        sh(path, "config", "user.email", f"{name}@example.invalid")
        sh(path, "config", "commit.gpgsign", "false")
        return path

    def beat(self, repo: str, holder: str, now: float, *extra: str) -> tuple:
        """Run `heartbeat.py beat` and return (exit code, JSON output)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = heartbeat.main(["beat", "--holder", holder, *extra], repo=repo, cfg=CFG, now=now)
        return code, (json.loads(out.getvalue()) if out.getvalue() else {})

    def status(self, repo: str, now: float) -> dict:
        """Run `heartbeat.py status` and return its JSON."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(heartbeat.main(["status"], repo=repo, cfg=CFG, now=now), 0)
        return json.loads(out.getvalue())

    def remote_tip(self) -> str:
        """Return the state branch commit on the origin, or empty."""
        proc = subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{CFG['state_branch']}"],
                              cwd=self.origin, capture_output=True, text=True)
        return proc.stdout.strip()


class Lease(Origin):
    """The lease moves to a second holder only when it is older than lease_max_age_s."""

    def test_first_beat_creates_the_state_branch(self) -> None:
        self.assertEqual(self.status(self.a, T0)["watch"], "stale")
        code, out = self.beat(self.a, "lead-a", T0, "--unit-start", "12", "--next-step", "build #12")
        self.assertEqual((code, out["result"], out["lease"]), (0, "ok", "free"))
        st = self.status(self.b, T0 + 60)
        self.assertEqual((st["watch"], st["lease_holder"]), ("fresh", "lead-a"))
        self.assertEqual(st["progress"]["units"], {"12": {"holder": "lead-a", "started_at": T0, "beat_at": T0}})
        self.assertEqual(sh(self.a, "ls-tree", "-r", "--name-only", self.remote_tip()), CFG["progress_path"])
        self.assertEqual(sh(self.a, "ls-remote", "origin", "refs/heads/main").split()[0], self.main_sha)

    def test_second_holder_waits_for_the_lease_age(self) -> None:
        self.assertEqual(LEASE, HOUR)
        self.beat(self.a, "lead-a", T0)
        before = self.remote_tip()
        for later in (60, LEASE / 2, LEASE):
            with self.subTest(later=later):
                code, out = self.beat(self.b, "lead-b", T0 + later)
                self.assertEqual((code, out["result"], out["holder"]), (3, "held", "lead-a"))
                self.assertEqual(self.remote_tip(), before)
        self.assertEqual(self.status(self.b, T0 + LEASE)["watch"], "fresh")
        self.assertEqual(self.status(self.b, T0 + LEASE + 1)["watch"], "stale")
        code, out = self.beat(self.b, "lead-b", T0 + LEASE + 1)
        self.assertEqual((code, out["lease"]), (0, "takeover"))
        st = self.status(self.a, T0 + LEASE + 2)
        self.assertEqual(st["lease_holder"], "lead-b")
        self.assertEqual(st["progress"]["takeovers"][0]["from"], "lead-a")
        code, out = self.beat(self.a, "lead-a", T0 + LEASE + 3)
        self.assertEqual((code, out["holder"]), (3, "lead-b"))

    def test_unit_records_start_stay_alive_and_end(self) -> None:
        self.beat(self.a, "lead-a", T0, "--unit-start", "12", "--unit-start", "13")
        self.beat(self.a, "lead-a", T0 + 1200, "--unit-alive", "12")
        units = self.status(self.b, T0 + 1201)["progress"]["units"]
        self.assertEqual((units["12"]["started_at"], units["12"]["beat_at"], units["13"]["beat_at"]), (T0, T0 + 1200, T0))
        self.beat(self.a, "lead-a", T0 + 1300, "--unit-end", "12")
        self.assertEqual(sorted(self.status(self.b, T0 + 1301)["progress"]["units"]), ["13"])
        self.beat(self.a, "lead-a", T0 + 1400, "--clear-units")
        self.assertEqual(self.status(self.b, T0 + 1401)["progress"]["units"], {})
        self.assertEqual(self.beat(self.a, "lead-a", T0 + 1500, "--unit-start", "0")[0], 1)

    def test_a_beat_in_the_future_never_blocks_the_lease(self) -> None:
        for ahead in (301, 1e9):
            with self.subTest(ahead=ahead):
                prog = {"lease": {"holder": "lead-x", "beat_at": T0 + ahead}}
                self.assertEqual(heartbeat.decide_lease(prog, "lead-b", T0, LEASE)["kind"], "free")
                self.assertEqual(heartbeat.watch_verdict(prog, T0, LEASE), "stale")
                self.assertTrue(state.lease_future(prog, T0))
        far = {"lease": {"holder": "lead-x", "beat_at": T0 + 1e9}}
        self.assertEqual(heartbeat.decide_lease(far, "lead-b", T0 + 30 * 86400, LEASE)["kind"], "free")
        prog = {"lease": {"holder": "lead-x", "beat_at": T0 + 300}}
        self.assertEqual(heartbeat.decide_lease(prog, "lead-b", T0, LEASE)["kind"], "held")
        self.assertFalse(state.lease_future(prog, T0))

    def test_the_command_line_has_no_clock_override(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stop:
                heartbeat.main(["--now", "99999999999", "beat", "--holder", "lead-x"], repo=self.a, cfg=CFG)
        self.assertEqual(stop.exception.code, 2)
        self.assertEqual(self.remote_tip(), "")

    def test_a_beat_works_without_a_git_identity(self) -> None:
        sh(self.a, "config", "--unset", "user.name")
        sh(self.a, "config", "--unset", "user.email")
        names = [k for k in os.environ if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_", "GIT_CONFIG_"))]
        keep = {k: os.environ.pop(k) for k in names}
        self.addCleanup(os.environ.update, keep)
        os.environ.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.addCleanup(os.environ.pop, "GIT_CONFIG_GLOBAL", None)
        self.addCleanup(os.environ.pop, "GIT_CONFIG_NOSYSTEM", None)
        code, out = self.beat(self.a, "lead-a", T0)
        self.assertEqual((code, out.get("result")), (0, "ok"))
        self.assertEqual(sh(self.a, "log", "-1", "--format=%an <%ae>", self.remote_tip()),
                         "academic-research conductor <conductor@users.noreply.github.com>")

    def test_own_beats_renew_and_keep_acquired_at(self) -> None:
        self.beat(self.a, "lead-a", T0)
        self.beat(self.a, "lead-a", T0 + 1.5 * HOUR, "--note", "compacted; re-read state")
        self.beat(self.a, "lead-a", T0 + 3 * HOUR, "--run", "proof:1=4242", "--limit-stop")
        prog = self.status(self.b, T0 + 3 * HOUR + 1)["progress"]
        self.assertEqual(prog["lease"]["acquired_at"], T0)
        self.assertEqual(prog["lease"]["beat_at"], T0 + 3 * HOUR)
        self.assertEqual(prog["runs"], {"proof:1": "4242"})
        self.assertEqual(prog["limit_stops"], 1)
        self.assertEqual(prog["notes"][0]["text"], "compacted; re-read state")
        self.assertEqual(len(sh(self.a, "rev-list", self.remote_tip()).split()), 3)

    def test_state_file_feeds_forecast(self) -> None:
        path = os.path.join(self.tmp.name, "state.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"forecast": {"units_per_day": 1.5}, "last_merged": {"pr": 7}}, handle)
        self.beat(self.a, "lead-a", T0, "--state-file", path)
        prog = self.status(self.b, T0 + 1)["progress"]
        self.assertEqual((prog["forecast"], prog["last_merged"]), ({"units_per_day": 1.5}, {"pr": 7}))

    def test_goal_met_tells_the_watchdog_done(self) -> None:
        self.beat(self.a, "lead-a", T0, "--goal-met")
        self.assertEqual(self.status(self.b, T0 + 10 * HOUR)["watch"], "done")

    def test_bad_arguments(self) -> None:
        self.assertEqual(self.beat(self.a, "x", T0)[0], 1)
        self.assertEqual(self.beat(self.a, "lead a", T0)[0], 1)
        self.assertEqual(self.beat(self.a, "lead-a", T0, "--run", "proof:9zz=1")[0], 1)
        self.assertEqual(self.beat(self.a, "lead-a", T0, "--run", "anything=1")[0], 1)
        self.assertEqual(self.remote_tip(), "")


class Git(Origin):
    """Plumbing writes never force and never touch main."""

    def test_stale_parent_is_rejected_not_forced(self) -> None:
        self.beat(self.a, "lead-a", T0)
        stale = heartbeat.fetch_tip(self.a, CFG["state_branch"])
        self.beat(self.a, "lead-a", T0 + 60)
        tip = self.remote_tip()
        commit = heartbeat.commit_file(self.b, None, CFG["progress_path"], "{}\n", "orphan")
        self.assertEqual(heartbeat.push(self.b, commit, CFG["state_branch"]), "rejected")
        commit = heartbeat.commit_file(self.a, stale, CFG["progress_path"], "{}\n", "stale parent")
        self.assertEqual(heartbeat.push(self.a, commit, CFG["state_branch"]), "rejected")
        self.assertEqual(self.remote_tip(), tip)

    def test_main_is_never_the_state_branch(self) -> None:
        commit = heartbeat.commit_file(self.a, None, CFG["progress_path"], "{}\n", "x")
        for branch in ("main", "master", ""):
            with self.subTest(branch=branch), self.assertRaises(heartbeat.GitError):
                heartbeat.push(self.a, commit, branch)
        self.assertNotIn(CFG["state_branch"], ("main", "master"))
        self.assertEqual(sh(self.a, "ls-remote", "origin", "refs/heads/main").split()[0], self.main_sha)

    def test_working_tree_and_head_stay_untouched(self) -> None:
        head = sh(self.a, "rev-parse", "HEAD")
        branch = sh(self.a, "branch", "--show-current")
        self.beat(self.a, "lead-a", T0)
        self.assertEqual(sh(self.a, "rev-parse", "HEAD"), head)
        self.assertEqual(sh(self.a, "branch", "--show-current"), branch)
        self.assertEqual(sh(self.a, "status", "--porcelain"), "")

    def test_holder_cache(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            heartbeat.main(["new-holder"], repo=self.a, cfg=CFG)
        holder = json.loads(out.getvalue())["holder"]
        self.assertRegex(holder, r"^lead-[0-9a-f]{12}$")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            heartbeat.main(["whoami"], repo=self.a, cfg=CFG)
        self.assertEqual(json.loads(out.getvalue())["holder"], holder)


class Pure(unittest.TestCase):
    """Lease decisions without git."""

    def test_decide_lease(self) -> None:
        prog = {"lease": {"holder": "lead-a", "beat_at": T0}}
        self.assertEqual(heartbeat.decide_lease({}, "lead-b", T0, 7200)["kind"], "free")
        self.assertEqual(heartbeat.decide_lease(prog, "lead-a", T0 + 9 * HOUR, 7200)["kind"], "own")
        self.assertEqual(heartbeat.decide_lease(prog, "lead-b", T0 + 7200, 7200)["kind"], "held")
        self.assertEqual(heartbeat.decide_lease(prog, "lead-b", T0 + 7201, 7200)["kind"], "takeover")
        self.assertEqual(CFG["lease_max_age_s"], 3600)


if __name__ == "__main__":
    unittest.main()
