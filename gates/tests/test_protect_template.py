"""protect template: the inline check is red on a kernel path, on a rename out of one and on a PR too large to list."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from typing import List, Tuple

from tests import support

TEMPLATE = os.path.join(support.SOURCE, "gates", "templates", "protect-operator-files.yml")
FAKE_GH = """import json, os, sys
args = sys.argv[1:]
if args[:2] != ["api", "--paginate"] or "--jq" not in args:
    sys.exit(2)
path = args[2]
if path.endswith("/files"):
    with open(os.environ["FAKE_GH_FILES"], encoding="utf-8") as handle:
        for pair in json.load(handle):
            print(json.dumps(pair))
elif path.endswith("/pulls/" + os.environ["PR"]):
    print(os.environ["FAKE_GH_CHANGED"])
else:
    sys.exit(3)
"""
GLOBS = ["gates/lib/**", "AGENTS.md", ".github/**"]


def protect_check() -> str:
    """Return the Python program of the protect step in the template."""
    with open(TEMPLATE, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = next(i for i, line in enumerate(lines) if "<<'PY'" in line) + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "PY")
    return textwrap.dedent("\n".join(lines[start:end])) + "\n"


class ProtectTemplate(unittest.TestCase):
    """Run the embedded check against a fake gh that answers the files listing and the PR object."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="protect-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        gh = os.path.join(self.tmp, "gh")
        with open(gh, "w", encoding="utf-8") as handle:
            handle.write(f"#!{sys.executable}\n" + FAKE_GH)
        os.chmod(gh, 0o755)
        self.script = os.path.join(self.tmp, "check.py")
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write(protect_check())

    def check(self, files: List[Tuple[str, str]], changed: int) -> subprocess.CompletedProcess:
        listing = os.path.join(self.tmp, "files.json")
        with open(listing, "w", encoding="utf-8") as handle:
            json.dump([list(f) for f in files], handle)
        env = dict(os.environ, PATH=self.tmp + os.pathsep + os.environ.get("PATH", ""), REPO="o/r", PR="7",
                   CONTROL_GLOBS=json.dumps(GLOBS), FAKE_GH_FILES=listing, FAKE_GH_CHANGED=str(changed))
        return subprocess.run([sys.executable, "-I", self.script], capture_output=True, text=True, env=env, timeout=60)

    def test_a_small_pr_without_kernel_paths_is_green(self) -> None:
        proc = self.check([("packages/web/src/a.ts", ""), ("docs/x.md", "docs/old.md")], 2)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("no kernel path touched", proc.stdout)

    def test_kernel_paths_are_red(self) -> None:
        for files in ([("gates/lib/hooks.py", "")], [("notes/hooks.py", "gates/lib/hooks.py")],
                      [("AGENTS.md", "")]):
            with self.subTest(files=files):
                proc = self.check(files, len(files))
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("kernel paths changed", proc.stderr)

    def test_a_pr_beyond_the_listing_limit_is_red(self) -> None:
        filler = [(f"aaa/{i:05d}.txt", "") for i in range(3000)]
        for changed in (3001, 3000):
            with self.subTest(changed=changed):
                proc = self.check(filler, changed)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("too many to check", proc.stderr)
        proc = self.check([("a.txt", ""), ("b.txt", "")], 3)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("too many to check", proc.stderr)


if __name__ == "__main__":
    unittest.main()
