"""release.yml job verify: the inline release check is red for every unmet condition, green when all hold, and only reads GitHub."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from typing import Dict, List, Optional

from tests import support

WORKFLOW = os.path.join(support.SOURCE, ".github", "workflows", "release.yml")
STAGES = ("1", "2a", "2b", "3", "4", "5")
REPO = "ahlerjam/academic-research"
RELEASE_MERGE = "Merge pull request #5 from ahlerjam/claude/release-0.1.0"
GOOD_VERDICT = "verdict: release\ncommit: {base}"
GOOD_CHANGELOG = "# Changelog\n\n## [0.1.0]\n\n- Added the editor.\n"
FAKE_GH = """import json, os, sys
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] != ["run", "list"] or "--json" not in args:
    sys.exit(2)
name = args[args.index("--workflow") + 1]
with open(os.environ["FAKE_GH_" + name.split(".")[0].upper()], encoding="utf-8") as handle:
    print(handle.read())
"""


def release_check() -> str:
    """Return the Python program of the step 'Release conditions' in release.yml."""
    with open(WORKFLOW, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = next(i for i, line in enumerate(lines) if "<<'RELEASE_CHECK'" in line) + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "RELEASE_CHECK")
    return textwrap.dedent("\n".join(lines[start:end])) + "\n"


def proof_run(stage: str, sha: str, conclusion: str = "success", created: str = "2026-11-01T10:00:00Z") -> dict:
    """Return one gh run list row of proof.yml for a stage."""
    return {"databaseId": 7, "displayTitle": f"proof stage {stage}", "status": "completed", "conclusion": conclusion,
            "headSha": sha, "createdAt": created, "url": f"https://example.invalid/proof/{stage}/{created}"}


class ReleaseCheckTest(unittest.TestCase):
    """Each case builds a git history and fake gh output, then runs the inline check of release.yml."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="release-check-")
        self.tree = os.path.join(self.root, "tree")
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        gh = os.path.join(self.bin, "gh")
        with open(gh, "w", encoding="utf-8") as handle:
            handle.write(f"#!{sys.executable}\n{FAKE_GH}")
        os.chmod(gh, 0o755)
        self.script = os.path.join(self.root, "check.py")
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write(release_check())

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def commit(self, files: Dict[str, str], message: str) -> str:
        """Write files, commit them on the current branch and return the commit sha."""
        for rel, text in files.items():
            support.write(self.tree, rel, text)
        support.git(self.tree, "add", "-A")
        support.git(self.tree, *support.GIT_ID, "commit", "-q", "-m", message)
        return support.git(self.tree, "rev-parse", "HEAD").stdout.strip()

    def merge_branch(self, branch: str, files: Dict[str, str], subject: str) -> None:
        """Commit files on a new branch from main and merge it into main with a merge commit named subject."""
        support.git(self.tree, "switch", "-q", "-c", branch)
        self.commit(files, f"work on {branch}")
        support.git(self.tree, "switch", "-q", "main")
        support.git(self.tree, *support.GIT_ID, "merge", "-q", "--no-ff", "-m", subject, branch)

    def release_tree(self, verdict: str = GOOD_VERDICT, changelog: str = GOOD_CHANGELOG,
                     tags: Optional[List[str]] = None, judged: str = "base", merge: str = RELEASE_MERGE,
                     after: Optional[List[dict]] = None, prep: Optional[Dict[str, str]] = None) -> str:
        """Build main: base commit, then claude/release-0.1.0 (the `prep` files committed first and named "prep",
        then the verdict naming the judged commit and CHANGELOG) merged by a pull request merge (`merge` is its
        subject, or "ff" for a fast-forward), then the `after` steps ({"files": ..., "branch": ...} merged by a PR,
        or a plain commit without branch); return the head sha."""
        os.makedirs(self.tree)
        support.git(self.tree, "init", "-q", "-b", "main")
        base = self.commit({"src/app.ts": "export {};\n"}, "base")
        for tag in tags or []:
            support.git(self.tree, "tag", tag)
        names = {"base": base}
        if judged == "stray":
            support.git(self.tree, "switch", "-q", "-c", "stray")
            names["stray"] = self.commit({"src/stray.ts": "export {};\n"}, "stray")
            support.git(self.tree, "switch", "-q", "main")
        support.git(self.tree, "switch", "-q", "-c", "claude/release-0.1.0")
        if prep:
            names["prep"] = self.commit(prep, "code on the release branch")
        self.commit({"CHANGELOG.md": changelog,
                     "docs/release/0.1.0.md": "# Release 0.1.0\n\n" + verdict.replace("{base}", names.get(judged, judged)) + "\n"},
                    "release 0.1.0")
        support.git(self.tree, "switch", "-q", "main")
        if merge == "ff":
            support.git(self.tree, "merge", "-q", "--ff-only", "claude/release-0.1.0")
        else:
            support.git(self.tree, *support.GIT_ID, "merge", "-q", "--no-ff", "-m", merge, "claude/release-0.1.0")
        for step in after or []:
            texts = {rel: text.replace("{base}", base) for rel, text in step["files"].items()}
            if step.get("branch"):
                self.merge_branch(step["branch"], texts, f"Merge pull request #9 from ahlerjam/{step['branch']}")
            else:
                self.commit(texts, "direct change")
        return support.git(self.tree, "rev-parse", "HEAD").stdout.strip()

    def run_check(self, sha: str, version: str = "0.1.0", dry_run: str = "true", ref: str = "refs/heads/main",
                  proofs: Optional[List[dict]] = None, releases: Optional[List[dict]] = None) -> subprocess.CompletedProcess:
        """Run the check with fake gh answers and return the finished process."""
        answers = {"PROOF": proofs if proofs is not None else [proof_run(s, sha) for s in STAGES],
                   "RELEASE": releases or []}
        env = {"PATH": self.bin + os.pathsep + os.environ.get("PATH", ""), "HOME": self.root,
               "FAKE_GH_LOG": os.path.join(self.root, "gh.log"), "VERSION": version, "DRY_RUN": dry_run,
               "GITHUB_SHA": sha, "GITHUB_RUN_ID": "99", "GITHUB_REF": ref, "GH_REPO": REPO}
        for name, rows in answers.items():
            path = os.path.join(self.root, f"{name.lower()}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(rows, handle)
            env[f"FAKE_GH_{name}"] = path
        return subprocess.run([sys.executable, "-I", self.script], cwd=self.tree, env=env, capture_output=True, text=True)

    def assert_red(self, done: subprocess.CompletedProcess, text: str) -> None:
        """Assert the check failed and named the unmet condition."""
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn(text, done.stdout)

    def assert_green(self, done: subprocess.CompletedProcess) -> None:
        """Assert the check passed."""
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_dry_run_with_every_condition_met_is_green_and_only_reads(self) -> None:
        sha = self.release_tree()
        done = self.run_check(sha)
        self.assert_green(done)
        self.assertIn("PASS proof stage 5", done.stdout)
        with open(os.path.join(self.root, "gh.log"), encoding="utf-8") as handle:
            calls = [json.loads(line) for line in handle]
        self.assertTrue(calls and all(call[:2] == ["run", "list"] for call in calls), calls)

    def test_real_run_with_a_green_dry_run_of_the_same_commit_is_green(self) -> None:
        sha = self.release_tree(tags=["v0.0.9"])
        dry = {"databaseId": 41, "displayTitle": "release 0.1.0 dry_run=true", "status": "completed",
               "conclusion": "success", "headSha": sha, "createdAt": "2026-11-02T10:00:00Z", "url": "https://example.invalid/r/41"}
        self.assert_green(self.run_check(sha, dry_run="false", releases=[dry]))

    def test_real_run_without_a_dry_run_is_red(self) -> None:
        sha = self.release_tree()
        own = {"databaseId": 99, "displayTitle": "release 0.1.0 dry_run=true", "status": "completed",
               "conclusion": "success", "headSha": sha, "createdAt": "2026-11-02T10:00:00Z", "url": "https://example.invalid/r/99"}
        self.assert_red(self.run_check(sha, dry_run="false", releases=[own]), "needs a successful dry run")

    def test_version_not_higher_than_the_last_tag_is_red(self) -> None:
        sha = self.release_tree(tags=["v0.1.0"])
        self.assert_red(self.run_check(sha), "not higher than the last tag v0.1.0")

    def test_version_with_a_v_prefix_is_red(self) -> None:
        sha = self.release_tree()
        self.assert_red(self.run_check(sha, version="v0.1.0"), "is not MAJOR.MINOR.PATCH")

    def test_missing_changelog_section_is_red(self) -> None:
        sha = self.release_tree(changelog="# Changelog\n\n## [0.0.9]\n")
        self.assert_red(self.run_check(sha), "CHANGELOG.md has no section")

    def test_changelog_heading_with_a_v_is_green(self) -> None:
        sha = self.release_tree(changelog="# Changelog\n\n## v0.1.0 - 2026-11-01\n\n- Added the editor.\n")
        self.assert_green(self.run_check(sha))

    def test_verdict_hold_is_red(self) -> None:
        sha = self.release_tree(verdict="verdict: hold\ncommit: {base}")
        self.assert_red(self.run_check(sha), "must be 'verdict: release'")

    def test_two_verdict_lines_are_red(self) -> None:
        sha = self.release_tree(verdict="verdict: release\nverdict: hold\ncommit: {base}")
        self.assert_red(self.run_check(sha), "exactly one verdict line")

    def test_a_missing_short_or_second_commit_line_is_red(self) -> None:
        for verdict in ("verdict: release", "verdict: release\ncommit: abc", "verdict: release\ncommit: {base}\ncommit: {base}",
                        "verdict: release\ncommit: {base} "):
            with self.subTest(verdict=verdict):
                shutil.rmtree(self.tree, ignore_errors=True)
                sha = self.release_tree(verdict=verdict)
                self.assert_red(self.run_check(sha), "needs exactly one line 'commit: <40-hex sha")

    def test_a_judged_commit_that_does_not_exist_is_red(self) -> None:
        sha = self.release_tree(judged="0" * 40)
        self.assert_red(self.run_check(sha), "which is not a commit of this repository")

    def test_a_judged_commit_outside_the_history_is_red(self) -> None:
        sha = self.release_tree(judged="stray")
        self.assert_red(self.run_check(sha), "is not on the history of")

    def test_a_judged_commit_on_the_release_branch_is_red(self) -> None:
        sha = self.release_tree(judged="prep", prep={"src/app.ts": "export const unjudged = 1;\n"})
        self.assert_red(self.run_check(sha), "is not the commit the release PR was merged onto")

    def test_code_on_the_release_branch_is_red_when_main_is_judged(self) -> None:
        sha = self.release_tree(prep={"src/app.ts": "export const unjudged = 1;\n"})
        self.assert_red(self.run_check(sha), "changed since the judged commit")

    def test_a_code_change_after_the_verdict_is_red(self) -> None:
        sha = self.release_tree(after=[{"files": {"src/app.ts": "export const x = 1;\n"}, "branch": "claude/unit-9-x"}])
        self.assert_red(self.run_check(sha), "changed since the judged commit")

    def test_a_direct_code_commit_after_the_merge_is_red(self) -> None:
        sha = self.release_tree(after=[{"files": {"packages/core/src/x.ts": "export {};\n"}}])
        self.assert_red(self.run_check(sha), "changed since the judged commit")

    def test_a_changelog_fix_after_the_verdict_is_green(self) -> None:
        sha = self.release_tree(after=[{"files": {"CHANGELOG.md": GOOD_CHANGELOG + "- Fixed a typo.\n"},
                                        "branch": "claude/unit-9-x"}])
        self.assert_green(self.run_check(sha))

    def test_a_verdict_rewritten_by_another_merge_is_red(self) -> None:
        text = "# Release 0.1.0\n\nverdict: release\ncommit: {base}\npanel: forged\n"
        sha = self.release_tree(after=[{"files": {"docs/release/0.1.0.md": text}, "branch": "claude/unit-9-x"}])
        self.assert_red(self.run_check(sha), "is not a merge 'Merge pull request #<n> from ahlerjam/claude/release-0.1.0'")

    def test_a_verdict_without_the_release_merge_is_red(self) -> None:
        cases = {"fast-forward": "ff", "fork": "Merge pull request #5 from someone/claude/release-0.1.0",
                 "other branch": "Merge pull request #5 from ahlerjam/claude/unit-3-x",
                 "other version": "Merge pull request #5 from ahlerjam/claude/release-0.1.0x"}
        for why, merge in cases.items():
            with self.subTest(why=why):
                shutil.rmtree(self.tree, ignore_errors=True)
                sha = self.release_tree(merge=merge)
                self.assert_red(self.run_check(sha), "is not a merge 'Merge pull request #<n> from ahlerjam/claude/release-0.1.0'")

    def test_a_direct_commit_of_the_verdict_after_the_merge_is_red(self) -> None:
        text = "# Release 0.1.0\n\nverdict: release\ncommit: {base}\n\nedited\n"
        sha = self.release_tree(after=[{"files": {"docs/release/0.1.0.md": text}}])
        self.assert_red(self.run_check(sha), "is not a merge")

    def test_latest_proof_run_failed_is_red_even_after_an_older_green_one(self) -> None:
        sha = self.release_tree()
        proofs = [proof_run(s, sha) for s in STAGES] + [proof_run("3", sha, "failure", "2026-11-03T10:00:00Z")]
        self.assert_red(self.run_check(sha, proofs=proofs), "stage 3: the latest proof run")

    def test_stage_without_proof_run_is_red(self) -> None:
        sha = self.release_tree()
        proofs = [proof_run(s, sha) for s in STAGES if s != "2b"]
        self.assert_red(self.run_check(sha, proofs=proofs), "stage 2b: no completed proof.yml run on main")

    def test_proof_run_on_a_commit_outside_the_history_is_red(self) -> None:
        sha = self.release_tree()
        proofs = [proof_run(s, sha if s != "4" else "0" * 40) for s in STAGES]
        self.assert_red(self.run_check(sha, proofs=proofs), "stage 4: the latest green proof run")

    def test_dispatch_on_another_branch_is_red(self) -> None:
        sha = self.release_tree()
        self.assert_red(self.run_check(sha, ref="refs/heads/claude/x"), "a release runs on refs/heads/main only")


class Credentials(unittest.TestCase):
    """No checkout leaves the job token in .git/config, where agent-written build scripts could push with it."""

    def test_every_checkout_drops_its_credentials(self) -> None:
        with open(WORKFLOW, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        checkouts = [i for i, line in enumerate(lines) if "uses: actions/checkout@" in line]
        self.assertEqual(len(checkouts), 3)
        for i in checkouts:
            block = []
            for line in lines[i + 1:]:
                if line.lstrip().startswith("- "):
                    break
                block.append(line.strip())
            with self.subTest(line=i + 1):
                self.assertIn("persist-credentials: false", block)

    def test_the_token_reaches_only_the_read_check_and_the_release_step(self) -> None:
        with open(WORKFLOW, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(text.count("GH_TOKEN: ${{ github.token }}"), 2)


if __name__ == "__main__":
    unittest.main()
