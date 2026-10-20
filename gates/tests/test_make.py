"""The real Makefile against the stop gate: check-<component> exists, a changed core file passes, a recipe override is red."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Dict, Optional

from tests import support

SKIP_DIRS = {".git", "node_modules", "__pycache__", "proof-out", ".ar"}
CORE_FILE = "packages/core/src/health/decideHealth.ts"


def real_tree(extra: Optional[Dict[str, str]] = None) -> str:
    """Copy the working tree without tool directories into a fresh git tree with a baseline, link node_modules."""
    root = tempfile.mkdtemp(prefix="gates-make-")
    for base, dirs, files in os.walk(support.SOURCE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name == "controls.sha256" or name.endswith(".pyc"):
                continue
            src = os.path.join(base, name)
            dest = os.path.join(root, os.path.relpath(src, support.SOURCE))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
    modules = os.path.join(support.SOURCE, "node_modules")
    if not os.path.isdir(modules):
        raise AssertionError("node_modules missing: run make setup before the gate tests")
    os.symlink(modules, os.path.join(root, "node_modules"))
    for package in sorted(os.listdir(os.path.join(support.SOURCE, "packages"))):
        inner = os.path.join(support.SOURCE, "packages", package, "node_modules")
        if os.path.isdir(inner):
            os.symlink(inner, os.path.join(root, "packages", package, "node_modules"))
    for rel, text in (extra or {}).items():
        support.write(root, rel, text)
    support.git(root, "init", "-q")
    support.gate(root, ["baseline"])
    support.git(root, "add", "-A")
    support.git(root, *support.GIT_ID, "commit", "-q", "-m", "init")
    os.makedirs(root + "-remote")
    support.git(root + "-remote", "init", "-q", "--bare")
    support.git(root, "remote", "add", "origin", root + "-remote")
    support.git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
    support.git(root, "fetch", "-q", "origin")
    return root


def drop(root: str) -> None:
    """Remove a tree made by real_tree and its bare remote."""
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(root + "-remote", ignore_errors=True)


def make(root: str, *args: str) -> subprocess.CompletedProcess:
    """Run make in root without the nesting guard of an outer gate run."""
    env = {k: v for k, v in os.environ.items() if k not in ("GATES_NESTED", "MAKEFLAGS", "MFLAGS")}
    env["CLAUDE_PROJECT_DIR"] = root
    return subprocess.run(["make", *args], cwd=root, capture_output=True, text=True, env=env, timeout=300)


class StopGateWithChangedCore(unittest.TestCase):
    """The stop gate calls make -s check-<component>; that verb must exist and be green on a clean change."""

    def setUp(self) -> None:
        self.root = real_tree()

    def tearDown(self) -> None:
        drop(self.root)

    def test_check_core_is_a_real_target(self) -> None:
        result = make(self.root, "-n", "check-core")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tsc -p packages/core", result.stdout)

    def test_unknown_component_is_red(self) -> None:
        result = make(self.root, "-s", "check-nowhere")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[GATES-INFRA]", result.stdout + result.stderr)

    def test_stop_gate_green_with_a_changed_core_file(self) -> None:
        path = os.path.join(self.root, CORE_FILE)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("any failing probe degrades it", text)
        support.write(self.root, CORE_FILE, text.replace("any failing probe degrades it", "one failing probe degrades it"))
        result = support.gate(self.root, ["hook", "stop"], {"stop_hook_active": False, "cwd": self.root})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("No rule to make target", result.stderr)

    def test_stop_gate_red_with_a_broken_core_file(self) -> None:
        support.write(self.root, CORE_FILE, "export const broken: number = 'text';\n")
        result = support.gate(self.root, ["hook", "stop"], {"stop_hook_active": False, "cwd": self.root})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("make check-core", result.stderr)


class RecipeOverride(unittest.TestCase):
    """A second recipe for a verb would replace a gate; check-repo must see make's warning and go red."""

    def test_second_recipe_for_a_verb_is_red(self) -> None:
        root = real_tree({"mk/zz-override.mk": "doctor:\n\t@true\n"})
        try:
            result = make(root, "-s", "check-repo")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("[GATES-INFRA] a recipe is defined twice", result.stdout + result.stderr)
        finally:
            drop(root)

    def test_clean_makefile_is_green(self) -> None:
        root = real_tree()
        try:
            result = make(root, "-s", "check-repo")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            drop(root)


if __name__ == "__main__":
    unittest.main()
