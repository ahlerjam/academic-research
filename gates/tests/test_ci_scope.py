"""ci scope step: the selftest runs when one of its inputs changed, on a schedule or without a base; else it is skipped."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from typing import Dict, Optional

from tests import support

WORKFLOW = os.path.join(support.SOURCE, ".github", "workflows", "ci.yml")
CONTROLS = {"operator_only": ["AGENTS.md", "gates/lib/**", ".github/**"], "ratchet": ["gates/roles.json"]}


def scope_step() -> str:
    """Return the Python program of the scope step in ci.yml."""
    with open(WORKFLOW, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    start = next(i for i, line in enumerate(lines) if "<<'PY'" in line) + 1
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "PY")
    return textwrap.dedent("\n".join(lines[start:end])) + "\n"


class CiScope(unittest.TestCase):
    """Run the embedded step in a scratch git tree, the way a checkout of a push or a PR merge commit looks."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="ci-scope-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.script = os.path.join(self.root, ".scope.py")
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write(scope_step())
        support.git(self.root, "init", "-q")
        self.base = self.commit({"gates/controls.json": json.dumps(CONTROLS), "gates/lib/x.py": "x = 1\n",
                                 "gates/roles.json": "{}\n", "packages/web/src/a.ts": "export const a = 1;\n"})

    def commit(self, files: Dict[str, str], remove: Optional[list] = None) -> str:
        for rel, text in files.items():
            support.write(self.root, rel, text)
        for rel in remove or []:
            support.git(self.root, "rm", "-q", rel)
        support.git(self.root, "add", "-A")
        support.git(self.root, *support.GIT_ID, "commit", "-q", "--allow-empty", "-m", "c")
        return support.git(self.root, "rev-parse", "HEAD").stdout.strip()

    def scope(self, event: str, before: str = "") -> str:
        output = os.path.join(self.root, ".output")
        open(output, "w", encoding="utf-8").close()
        env = dict(os.environ, EVENT=event, BEFORE=before, GITHUB_OUTPUT=output)
        proc = subprocess.run([sys.executable, "-I", self.script], cwd=self.root, capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(output, encoding="utf-8") as handle:
            return handle.read().strip()

    def test_a_product_push_skips_the_selftest(self) -> None:
        self.commit({"packages/web/src/a.ts": "export const a = 2;\n", "docs/review/x.md": "# x\n"})
        self.assertEqual(self.scope("push", self.base), "selftest=no")

    def test_a_push_touching_an_input_runs_it(self) -> None:
        for files in ({"gates/lib/x.py": "x = 2\n"}, {"gates/roles.json": "{\"a\": 1}\n"}, {"AGENTS.md": "# a\n"},
                      {"pnpm-lock.yaml": "lockfileVersion: 9\n"}, {"packages/web/package.json": "{}\n"},
                      {"decisions/0099-x.md": "# x\n"}, {"gates/catalog.json": "[]\n"},
                      {"packages/core/src/health/decideHealth.ts": "export const h = 1;\n"}):
            with self.subTest(files=files):
                before = support.git(self.root, "rev-parse", "HEAD").stdout.strip()
                self.commit(files)
                self.assertEqual(self.scope("push", before), "selftest=yes")

    def test_a_rename_out_of_an_input_runs_it(self) -> None:
        self.commit({"notes/x.py": "x = 1\n"}, remove=["gates/lib/x.py"])
        self.assertEqual(self.scope("push", self.base), "selftest=yes")

    def test_no_base_a_schedule_or_an_unknown_base_runs_it(self) -> None:
        self.commit({"packages/web/src/a.ts": "export const a = 3;\n"})
        for event, before in (("push", "0" * 40), ("schedule", ""), ("workflow_dispatch", ""),
                              ("push", "1" * 40)):
            with self.subTest(event=event, before=before):
                self.assertEqual(self.scope(event, before), "selftest=yes")

    def test_a_pull_request_compares_the_merge_commit_with_its_first_parent(self) -> None:
        support.git(self.root, "switch", "-q", "-c", "feature")
        self.commit({"packages/web/src/a.ts": "export const a = 4;\n"})
        support.git(self.root, "switch", "-q", "-")
        self.commit({"gates/lib/x.py": "x = 3\n"})
        support.git(self.root, *support.GIT_ID, "merge", "-q", "--no-ff", "-m", "m", "feature")
        self.assertEqual(self.scope("pull_request"), "selftest=no")
        support.git(self.root, "switch", "-q", "feature")
        self.commit({"gates/lib/y.py": "y = 1\n"})
        support.git(self.root, "switch", "-q", "-")
        support.git(self.root, "reset", "-q", "--hard", "HEAD^1")
        support.git(self.root, *support.GIT_ID, "merge", "-q", "--no-ff", "-m", "m", "feature")
        self.assertEqual(self.scope("pull_request"), "selftest=yes")


if __name__ == "__main__":
    unittest.main()
