"""Inputs a hook runs besides the file: nested ESLint/Prettier configs and tool shims in the tree never run or judge."""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import support  # noqa: E402

from lib import drift, tools  # noqa: E402

NESTED = "packages/web/src/zz"
ESLINT_TRAP = "import fs from 'node:fs';\nfs.writeFileSync(new URL('ESLINT_RAN', import.meta.url), 'x');\nexport default [];\n"
PRETTIER_TRAP = ("import fs from 'node:fs';\nfs.writeFileSync(new URL('PRETTIER_RAN', import.meta.url), 'x');\n"
                 "export default { semi: false };\n")
SHIM = "#!/bin/sh\ntouch \"$(dirname \"$0\")/SHIM_RAN\"\necho '[]'\nexit 0\n"


def _root_file(rel: str) -> str:
    """Return the text of a file of the checked-out repository."""
    with open(os.path.join(support.SOURCE, rel), encoding="utf-8") as handle:
        return handle.read()


def _shim(root: str, rel: str) -> None:
    """Write an executable stand-in for a tool."""
    support.write(root, rel, SHIM)
    path = os.path.join(root, rel)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class NestedConfigs(unittest.TestCase):
    """ESLint and Prettier get --config <root file>; a nested config is operator-only and a D17 finding."""

    def test_the_pin_names_the_root_configs(self) -> None:
        self.assertEqual(tools.pinned("/t", ["eslint", "--format", "json", "{file}"]),
                         ["eslint", "--config", "/t/eslint.config.mjs", "--format", "json", "{file}"])
        self.assertEqual(tools.pinned("/t", ["prettier", "--check", "{file}"]),
                         ["prettier", "--config", "/t/.prettierrc.json", "--check", "{file}"])
        self.assertEqual(tools.pinned("/t", ["bash", "-n", "{file}"]), ["bash", "-n", "{file}"])
        self.assertEqual(tools.pinned("/t", ["prettier", "--config=x.json", "{file}"]), ["prettier", "--config=x.json", "{file}"])

    def test_a_nested_config_neither_runs_nor_switches_rules_off_in_the_hook(self) -> None:
        modules = os.path.join(support.SOURCE, "node_modules")
        self.assertTrue(os.path.isfile(os.path.join(modules, ".bin", "prettier")), "run `make setup` first")
        root = support.make_tree({"eslint.config.mjs": _root_file("eslint.config.mjs"),
                                  ".prettierrc.json": _root_file(".prettierrc.json"),
                                  f"{NESTED}/eslint.config.js": ESLINT_TRAP,
                                  f"{NESTED}/prettier.config.mjs": PRETTIER_TRAP,
                                  f"{NESTED}/a.ts": "export const a = 1\n"})
        self.addCleanup(shutil.rmtree, root, True)
        os.symlink(modules, os.path.join(root, "node_modules"))
        payload = {"tool_input": {"file_path": os.path.join(root, NESTED, "a.ts")}, "cwd": root}
        result = support.gate(root, ["hook", "post-edit"], payload)
        self.assertFalse(os.path.exists(os.path.join(root, NESTED, "ESLINT_RAN")), result.stderr)
        self.assertFalse(os.path.exists(os.path.join(root, NESTED, "PRETTIER_RAN")), result.stderr)
        with open(os.path.join(root, NESTED, "a.ts"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "export const a = 1;\n", "formatted by the root config, not by semi: false")
        self.assertEqual(result.returncode, 2, "ESLint still judges the file under the root config")
        self.assertIn("[eslint:", result.stderr, "the nested 'export default []' would have let ESLint pass silently")

    def test_nested_configs_are_operator_only_and_red_in_drift(self) -> None:
        root = support.make_tree({"eslint.config.mjs": "export default [];\n", ".prettierrc.json": "{}\n",
                                  "packages/web/package.json": json.dumps({"name": "w", "devDependencies": {"prettier": "3"}})})
        self.addCleanup(shutil.rmtree, root, True)
        self.assertEqual(drift.d17(root), [])
        for rel in (f"{NESTED}/eslint.config.js", f"{NESTED}/prettier.config.mjs", f"{NESTED}/.prettierrc",
                    f"{NESTED}/.prettierrc.yaml", f"{NESTED}/.eslintrc.json"):
            with self.subTest(rel=rel):
                write = {"tool_input": {"file_path": os.path.join(root, rel), "content": "x\n"}, "cwd": root}
                result = support.gate(root, ["hook", "pre-write"], write)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("WRITE-CONTROL", result.stderr)
        plain = {"tool_input": {"file_path": os.path.join(root, NESTED, "a.ts"), "content": "x\n"}, "cwd": root}
        self.assertEqual(support.gate(root, ["hook", "pre-write"], plain).returncode, 0)
        support.write(root, f"{NESTED}/eslint.config.js", "export default [];\n")
        support.write(root, "packages/plugin/package.json", json.dumps({"name": "p", "prettier": {"semi": False}}))
        self.assertEqual(sorted((f.path, f.rule) for f in drift.d17(root)),
                         [("packages/plugin/package.json", "GATES-D17"), (f"{NESTED}/eslint.config.js", "GATES-D17")])


class ToolShadows(unittest.TestCase):
    """ast-grep comes from PATH; a shim in bin/, build/tools/ or .venv/bin never judges, a versioned one is D18."""

    def test_a_shim_never_replaces_ast_grep(self) -> None:
        core = "packages/core/src/x/a.ts"
        root = support.make_tree({core: "export function f(): number {\n  throw new Error('x');\n}\n"})
        self.addCleanup(shutil.rmtree, root, True)
        for rel in ("bin/ast-grep", "build/tools/ast-grep", ".venv/bin/ast-grep", "node_modules/.bin/ast-grep",
                    "packages/core/node_modules/.bin/ast-grep", "bin/sg", ".venv/bin/sg"):
            _shim(root, rel)
        self.assertEqual(tools.resolve(root, "packages/core", "ast-grep"), shutil.which("ast-grep"))
        self.assertEqual(tools.resolve(root, ".", "sg"), shutil.which("sg"))
        self.assertIsNotNone(shutil.which("ast-grep"), "ast-grep belongs on PATH (make setup checks it)")
        payload = {"tool_input": {"file_path": os.path.join(root, core)}, "cwd": root}
        result = support.gate(root, ["hook", "post-edit"], payload)
        self.assertIn("TS-CORE-NO-THROW", result.stderr)
        ran = [rel for rel in ("bin", "build/tools", ".venv/bin", "node_modules/.bin", "packages/core/node_modules/.bin")
               if os.path.exists(os.path.join(root, rel, "SHIM_RAN"))]
        self.assertEqual(ran, [])

    def test_a_versioned_file_in_a_tool_directory_is_red(self) -> None:
        root = support.make_tree()
        self.addCleanup(shutil.rmtree, root, True)
        self.assertEqual(drift.d18(root), [])
        _shim(root, "node_modules/.bin/eslint")
        _shim(root, "packages/web/.venv/bin/ruff")
        self.assertEqual(drift.d18(root), [], "an ignored, unversioned install is no finding")
        support.git(root, "add", "-f", "node_modules/.bin/eslint", "packages/web/.venv/bin/ruff")
        self.assertEqual(sorted((f.path, f.rule) for f in drift.d18(root)),
                         [("node_modules/.bin/eslint", "GATES-D18"), ("packages/web/.venv/bin/ruff", "GATES-D18")])


if __name__ == "__main__":
    unittest.main()
