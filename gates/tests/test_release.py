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
    """Each case builds a git tree and fake gh output, then runs the inline check of release.yml."""

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

    def tree_with(self, files: Dict[str, str], tags: Optional[List[str]] = None) -> str:
        """Create the release tree with one commit and the given tags; return the commit sha."""
        os.makedirs(self.tree)
        for rel, text in files.items():
            support.write(self.tree, rel, text)
        support.git(self.tree, "init", "-q")
        support.git(self.tree, "add", "-A")
        support.git(self.tree, *support.GIT_ID, "commit", "-q", "-m", "release tree")
        for tag in tags or []:
            support.git(self.tree, "tag", tag)
        return support.git(self.tree, "rev-parse", "HEAD").stdout.strip()

    def run_check(self, sha: str, version: str = "0.1.0", dry_run: str = "true", ref: str = "refs/heads/main",
                  proofs: Optional[List[dict]] = None, releases: Optional[List[dict]] = None) -> subprocess.CompletedProcess:
        """Run the check with fake gh answers and return the finished process."""
        answers = {"PROOF": proofs if proofs is not None else [proof_run(s, sha) for s in STAGES],
                   "RELEASE": releases or []}
        env = {"PATH": self.bin + os.pathsep + os.environ.get("PATH", ""), "HOME": self.root,
               "FAKE_GH_LOG": os.path.join(self.root, "gh.log"), "VERSION": version, "DRY_RUN": dry_run,
               "GITHUB_SHA": sha, "GITHUB_RUN_ID": "99", "GITHUB_REF": ref}
        for name, rows in answers.items():
            path = os.path.join(self.root, f"{name.lower()}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(rows, handle)
            env[f"FAKE_GH_{name}"] = path
        return subprocess.run([sys.executable, "-I", self.script], cwd=self.tree, env=env, capture_output=True, text=True)

    def good_files(self, verdict: str = "verdict: release") -> Dict[str, str]:
        """Return a changelog with a 0.1.0 section and a verdict file."""
        return {"CHANGELOG.md": "# Changelog\n\n## [0.1.0]\n\n- Added the editor.\n",
                "docs/release/0.1.0.md": f"# Release 0.1.0\n\n{verdict}\ncommit: abc\n"}

    def assert_red(self, done: subprocess.CompletedProcess, text: str) -> None:
        """Assert the check failed and named the unmet condition."""
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn(text, done.stdout)

    def test_dry_run_with_every_condition_met_is_green_and_only_reads(self) -> None:
        sha = self.tree_with(self.good_files())
        done = self.run_check(sha)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("PASS proof stage 5", done.stdout)
        with open(os.path.join(self.root, "gh.log"), encoding="utf-8") as handle:
            calls = [json.loads(line) for line in handle]
        self.assertTrue(calls and all(call[:2] == ["run", "list"] for call in calls), calls)

    def test_real_run_with_a_green_dry_run_of_the_same_commit_is_green(self) -> None:
        sha = self.tree_with(self.good_files(), tags=["v0.0.9"])
        dry = {"databaseId": 41, "displayTitle": "release 0.1.0 dry_run=true", "status": "completed",
               "conclusion": "success", "headSha": sha, "createdAt": "2026-11-02T10:00:00Z", "url": "https://example.invalid/r/41"}
        done = self.run_check(sha, dry_run="false", releases=[dry])
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_real_run_without_a_dry_run_is_red(self) -> None:
        sha = self.tree_with(self.good_files())
        own = {"databaseId": 99, "displayTitle": "release 0.1.0 dry_run=true", "status": "completed",
               "conclusion": "success", "headSha": sha, "createdAt": "2026-11-02T10:00:00Z", "url": "https://example.invalid/r/99"}
        self.assert_red(self.run_check(sha, dry_run="false", releases=[own]), "needs a successful dry run")

    def test_version_not_higher_than_the_last_tag_is_red(self) -> None:
        sha = self.tree_with(self.good_files(), tags=["v0.1.0"])
        self.assert_red(self.run_check(sha), "not higher than the last tag v0.1.0")

    def test_version_with_a_v_prefix_is_red(self) -> None:
        sha = self.tree_with(self.good_files())
        self.assert_red(self.run_check(sha, version="v0.1.0"), "is not MAJOR.MINOR.PATCH")

    def test_missing_changelog_section_is_red(self) -> None:
        files = self.good_files()
        files["CHANGELOG.md"] = "# Changelog\n\n## [0.0.9]\n"
        sha = self.tree_with(files)
        self.assert_red(self.run_check(sha), "CHANGELOG.md has no section")

    def test_changelog_heading_with_a_v_is_green(self) -> None:
        files = self.good_files()
        files["CHANGELOG.md"] = "# Changelog\n\n## v0.1.0 - 2026-11-01\n\n- Added the editor.\n"
        sha = self.tree_with(files)
        done = self.run_check(sha)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_verdict_hold_is_red(self) -> None:
        sha = self.tree_with(self.good_files(verdict="verdict: hold"))
        self.assert_red(self.run_check(sha), "must be 'verdict: release'")

    def test_two_verdict_lines_are_red(self) -> None:
        sha = self.tree_with(self.good_files(verdict="verdict: release\nverdict: hold"))
        self.assert_red(self.run_check(sha), "exactly one verdict line")

    def test_latest_proof_run_failed_is_red_even_after_an_older_green_one(self) -> None:
        sha = self.tree_with(self.good_files())
        proofs = [proof_run(s, sha) for s in STAGES] + [proof_run("3", sha, "failure", "2026-11-03T10:00:00Z")]
        self.assert_red(self.run_check(sha, proofs=proofs), "stage 3: the latest proof run")

    def test_stage_without_proof_run_is_red(self) -> None:
        sha = self.tree_with(self.good_files())
        proofs = [proof_run(s, sha) for s in STAGES if s != "2b"]
        self.assert_red(self.run_check(sha, proofs=proofs), "stage 2b: no completed proof.yml run on main")

    def test_proof_run_on_a_commit_outside_the_history_is_red(self) -> None:
        sha = self.tree_with(self.good_files())
        proofs = [proof_run(s, sha if s != "4" else "0" * 40) for s in STAGES]
        self.assert_red(self.run_check(sha, proofs=proofs), "stage 4: the latest green proof run")

    def test_dispatch_on_another_branch_is_red(self) -> None:
        sha = self.tree_with(self.good_files())
        self.assert_red(self.run_check(sha, ref="refs/heads/claude/x"), "a release runs on refs/heads/main only")


if __name__ == "__main__":
    unittest.main()
