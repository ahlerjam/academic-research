"""Guard partial orders: roles.json and dispatch.json only grow, proof specs and lenses only gain lines,
package tsconfigs follow the template; plus the prefilled roles and dispatch entries."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import unittest
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import support  # noqa: E402

from lib import catalog, engine, guard, layout, roles  # noqa: E402

TEMPLATE = {"extends": "../../tsconfig.base.json", "compilerOptions": {"types": []}, "include": ["src", "test"]}
CORE_TSCONFIG = {"extends": "../../tsconfig.base.json", "compilerOptions": {"types": ["vite/client"]}, "include": ["src"]}
PROOF = "packages/web/e2e/proof/S1-QUOTE-EXACT.spec.ts"
LENS = "docs/review/lenses/tests.md"
PROOF_TEXT = ("import { expect, test } from '@playwright/test';\n\n"
              "test('S1-QUOTE-EXACT', async ({ page }) => {\n  await page.goto('/');\n"
              "  await expect(page).toHaveURL('/');\n});\n")


def _json(root: str, rel: str) -> dict:
    """Load a JSON file of the test tree."""
    with open(os.path.join(root, rel), encoding="utf-8") as handle:
        return json.load(handle)


def _dump(root: str, rel: str, data: dict) -> None:
    """Write a JSON file into the test tree."""
    support.write(root, rel, json.dumps(data, indent=1) + "\n")


def _whats(root: str, rel: str) -> List[str]:
    """Return the guard messages about one path."""
    return [f.what for f in guard.violations(root) if f.path == rel and f.rule == "GATES-RATCHET"]


class GuardCase(unittest.TestCase):
    """Create one committed tree per test and remove it afterwards."""

    def tree(self, extra: Optional[Dict[str, str]] = None) -> str:
        root = support.make_tree(extra)
        self.addCleanup(shutil.rmtree, root, True)
        return root


class RolesPartialOrder(GuardCase):
    """New components, roles, globs and tighter budgets pass; anything that weakens an existing entry is red."""

    def test_additions_and_tightening_pass(self) -> None:
        root = self.tree()
        cfg = _json(root, guard.ROLES)
        cfg["components"]["extra"] = {"lang": "typescript", "dir": "packages/extra", "root": "packages/extra/src",
                                      "roles": {"test": ["../test/**/*.ts"], "adapter": ["**/*.ts"]}}
        cfg["components"]["server"]["roles"]["wiring"].append("tools/*.ts")
        cfg["components"]["server"]["roles"]["wiring"].append("jobs/*.ts")
        cfg["components"]["server"]["non_feature"].append("tools")
        cfg["components"]["server"]["roles"]["queue"] = ["queue/*.ts"]
        cfg["budgets"]["core"]["function_lines"] = 30
        cfg["budgets"]["tool"] = {"function_lines": 20, "module_lines": 100}
        cfg["ignore"].remove("**/playwright.config.ts")
        cfg["shared_fingerprint"].append("contracts/**")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [])

    def test_weakening_an_existing_entry_is_red(self) -> None:
        cases = [
            ("budget core.function_lines 40 -> 41", lambda c: c["budgets"]["core"].update(function_lines=41)),
            ("budget wiring.module_lines 200 -> None", lambda c: c["budgets"]["wiring"].pop("module_lines")),
            ("ignore gained 'packages/**'", lambda c: c["ignore"].append("packages/**")),
            ("shared_fingerprint lost 'pnpm-lock.yaml'", lambda c: c["shared_fingerprint"].remove("pnpm-lock.yaml")),
            ("top-level key 'mode' added", lambda c: c.update(mode="lax")),
            ("component 'web' removed", lambda c: c["components"].pop("web")),
            ("component 'server' key 'lang' changed", lambda c: c["components"]["server"].update(lang="python")),
            ("component 'server' key 'feature_layout' changed",
             lambda c: c["components"]["server"]["feature_layout"]["files"].append("*.ts")),
            ("component 'server' non_feature lost 'adapters'",
             lambda c: c["components"]["server"]["non_feature"].remove("adapters")),
            ("component 'core' role 'core' lost '**/*.ts'",
             lambda c: c["components"]["core"]["roles"].update(core=["*/core.ts"])),
            ("new component 'sub' dir 'packages/core/sub' overlaps component 'core'",
             lambda c: c["components"].update(sub={"lang": "typescript", "dir": "packages/core/sub",
                                                   "root": "packages/core/sub/src", "roles": {"adapter": ["*.ts"]}})),
            ("new component 'bare' needs lang, dir, root, roles",
             lambda c: c["components"].update(bare={"dir": "packages/bare"})),
            ("component 'server' new glob '../../web/src/**/*.ts' reaches outside 'packages/server'",
             lambda c: c["components"]["server"]["roles"]["adapter"].append("../../web/src/**/*.ts")),
            ("component 'server' new glob 'gen/*.ts' for role 'generated'; operator only",
             lambda c: c["components"]["server"]["roles"].update(generated=["gen/*.ts"])),
        ]
        root = self.tree()
        original = _json(root, guard.ROLES)
        for expected, change in cases:
            with self.subTest(expected=expected):
                cfg = copy.deepcopy(original)
                change(cfg)
                _dump(root, guard.ROLES, cfg)
                whats = _whats(root, guard.ROLES)
                self.assertTrue(any(w.startswith(expected) for w in whats), whats)

    def test_a_new_glob_that_takes_an_existing_file_is_red(self) -> None:
        root = self.tree({"packages/core/src/x/thing.ts": "export const thing = 1;\n"})
        cfg = _json(root, guard.ROLES)
        cfg["components"]["core"]["roles"]["test"].append("x/*.ts")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), ["packages/core/src/x/thing.ts moves from core/core to core/test; "
                                                     "only additions are allowed against HEAD"])
        cfg["components"]["core"]["roles"]["test"].remove("x/*.ts")
        cfg["components"]["core"]["roles"]["test"].append("y/*.ts")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [])

    def test_non_feature_only_for_new_directories_with_a_role_glob(self) -> None:
        root = self.tree({"packages/server/src/billing/flow.ts": "export const flow = 1;\n"})
        cfg = _json(root, guard.ROLES)
        cfg["components"]["server"]["non_feature"].append("billing")
        _dump(root, guard.ROLES, cfg)
        self.assertTrue(any("'billing', which already holds mapped files" in w for w in _whats(root, guard.ROLES)))
        cfg["components"]["server"]["non_feature"] = ["adapters", "cli", "dev", "data", "batch"]
        _dump(root, guard.ROLES, cfg)
        self.assertTrue(any("'batch' without a role glob" in w for w in _whats(root, guard.ROLES)))
        cfg["components"]["server"]["roles"]["wiring"].append("batch/*.ts")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [])

    def test_unparsable_roles_file_is_red(self) -> None:
        root = self.tree()
        support.write(root, guard.ROLES, "{ not json\n")
        self.assertEqual(len(_whats(root, guard.ROLES)), 1)


class DispatchPartialOrder(GuardCase):
    """Entries may only be appended; existing entries stay byte-identical; mode only moves to strict."""

    def test_appended_entry_passes(self) -> None:
        root = self.tree()
        data = _json(root, guard.DISPATCH)
        data["entries"].append({"glob": "packages/**/*.txt", "tier": "s1", "check": [["@rules"]]})
        _dump(root, guard.DISPATCH, data)
        self.assertEqual(_whats(root, guard.DISPATCH), [])

    def test_weakening_is_red(self) -> None:
        cases = [
            ("existing entries changed", lambda d: d["entries"][1]["check"].pop(0)),
            ("existing entries changed", lambda d: d["entries"].reverse()),
            ("existing entries changed", lambda d: d["entries"].pop()),
            ("mode 'strict' -> 'touched-lines'", lambda d: d.update(mode="touched-lines")),
            ("top-level key 'extra' added", lambda d: d.update(extra=1)),
            ("new entry 8 needs a string 'glob' and 'tier'", lambda d: d["entries"].append({"glob": "x/*.md"})),
        ]
        root = self.tree()
        original = _json(root, guard.DISPATCH)
        for expected, change in cases:
            with self.subTest(expected=expected):
                data = copy.deepcopy(original)
                change(data)
                _dump(root, guard.DISPATCH, data)
                whats = _whats(root, guard.DISPATCH)
                self.assertTrue(any(w.startswith(expected) for w in whats), whats)


class AddOnlyPaths(GuardCase):
    """Proof specs and review lenses gain lines only; each proof file holds an expect call."""

    def base(self) -> str:
        return self.tree({PROOF: PROOF_TEXT, LENS: "# Tests lens\n\n- A test fails on the old code.\n"})

    def test_added_lines_and_new_files_pass(self) -> None:
        root = self.base()
        support.write(root, PROOF, PROOF_TEXT.replace("  await page.goto('/');\n",
                                                      "  await page.goto('/');\n  await page.reload();\n"))
        support.write(root, LENS, "# Tests lens\n\n- A test fails on the old code.\n- A negative case exists.\n")
        support.write(root, "packages/web/e2e/proof/S1-TRACE-BLOCKS.spec.ts", PROOF_TEXT)
        self.assertEqual([f for f in guard.violations(root) if f.path.startswith(guard.ADD_ONLY)], [])

    def test_removed_changed_deleted_or_expectless_is_red(self) -> None:
        root = self.base()
        support.write(root, PROOF, PROOF_TEXT.replace("await expect(page).toHaveURL('/');", "await page.goto('/');"))
        os.remove(os.path.join(root, LENS))
        support.write(root, "packages/web/e2e/proof/S1-EMPTY.spec.ts", "test('S1-EMPTY', () => {});\n")
        whats = sorted((f.path, f.what.split(";")[0]) for f in guard.violations(root) if f.path.startswith(guard.ADD_ONLY))
        self.assertEqual(whats, sorted([(LENS, "deleted against HEAD"),
                                        (PROOF, "lines removed or changed against HEAD"),
                                        (PROOF, "proof file without an expect call"),
                                        ("packages/web/e2e/proof/S1-EMPTY.spec.ts", "proof file without an expect call")]))
        support.write(root, LENS, "- A test fails on the old code.\n# Tests lens\n")
        self.assertTrue(_whats(root, LENS))


class PackageTsconfig(GuardCase):
    """A new package tsconfig equals the template, a changed one its base version, both except include."""

    def base(self, template: bool = True) -> str:
        extra = {"packages/core/tsconfig.json": json.dumps(CORE_TSCONFIG)}
        if template:
            extra[guard.TEMPLATE] = json.dumps(TEMPLATE)
        root = self.tree(extra)
        if not template and os.path.isfile(os.path.join(root, guard.TEMPLATE)):
            os.remove(os.path.join(root, guard.TEMPLATE))
        return root

    def test_include_is_free(self) -> None:
        root = self.base()
        _dump(root, "packages/extra/tsconfig.json", dict(TEMPLATE, include=["src", "test", "e2e"]))
        core = _json(root, "packages/core/tsconfig.json")
        _dump(root, "packages/core/tsconfig.json", dict(core, include=["src", "test", "bench"]))
        self.assertEqual([f for f in guard.violations(root) if f.path.startswith("packages/")], [])

    def test_other_differences_are_red(self) -> None:
        root = self.base()
        _dump(root, "packages/extra/tsconfig.json", dict(TEMPLATE, compilerOptions={"strict": False}))
        core = _json(root, "packages/core/tsconfig.json")
        _dump(root, "packages/core/tsconfig.json", dict(core, compilerOptions={"types": ["node"]}))
        _dump(root, "packages/core/src/tsconfig.json", TEMPLATE)
        whats = {f.path: f.what for f in guard.violations(root) if f.path.startswith("packages/")}
        self.assertEqual(whats["packages/extra/tsconfig.json"], f"differs from {guard.TEMPLATE} outside 'include'")
        self.assertEqual(whats["packages/core/tsconfig.json"], "differs from its version on HEAD outside 'include'")
        self.assertIn("only packages/<name>/tsconfig.json", whats["packages/core/src/tsconfig.json"])

    def test_missing_template_is_red(self) -> None:
        root = self.base(template=False)
        self.assertFalse(os.path.exists(os.path.join(root, guard.TEMPLATE)))
        _dump(root, "packages/extra/tsconfig.json", TEMPLATE)
        self.assertEqual(_whats(root, "packages/extra/tsconfig.json"),
                         [f"cannot compare as plain JSON with {guard.TEMPLATE}"])


class Prefill(GuardCase):
    """The prefilled roles map the files tickets #26, #30, #35 and #41 name; dispatch covers sql, sh, mjs, yml."""

    def test_ticket_paths_have_their_roles(self) -> None:
        files = {"packages/server/src/cli/measureRecall.ts": "wiring", "packages/server/src/dev/ghostMeasure.ts": "wiring",
                 "packages/server/src/data/projectScoped.ts": "adapter", "packages/plugin/src/index.ts": "wiring",
                 "packages/plugin/src/mcp/main.ts": "wiring", "packages/plugin/src/mcp/tools.ts": "api",
                 "packages/plugin/src/mcp/client.fake.ts": "adapter", "packages/plugin/src/shared/tokenFile.ts": "adapter",
                 "packages/plugin/test/seed.test.ts": "test", "packages/server/migrations/0001_init.sql": "migration"}
        root = self.tree({rel: "export const x = 1;\n" for rel in files})
        cfg = roles.load(root)
        got = {rel: (roles.place_of(root, rel, cfg) or roles.Place("", "none", "", None)).role for rel in files}
        self.assertEqual(got, files)
        self.assertEqual(layout.violations(root, cfg, {"server": "TS-LAYOUT"}), [])

    def test_dispatch_entries_match_the_new_extensions(self) -> None:
        files = ["packages/server/migrations/0001_init.sql", "scripts/proof.sh", "scripts/tool.mjs",
                 "deploy/compose.app.yml", "packages/web/e2e/config.yaml"]
        root = self.tree({rel: "x\n" for rel in files})
        self.assertEqual([rel for rel in files if not engine.dispatch_entries(root, rel, "s0")], [])

    def test_shell_syntax_errors_are_findings_not_infrastructure(self) -> None:
        root = self.tree({"scripts/bad.sh": "if true; then\n  echo x\nfii\n", "scripts/good.sh": "echo ok\n"})
        cfg, entries = roles.load(root), catalog.load(root)
        bad = engine.run_tier(root, "scripts/bad.sh", "s0", cfg, entries).findings
        self.assertEqual([(f.path, f.rule) for f in bad], [("scripts/bad.sh", "bash:bash-syntax")])
        self.assertEqual(engine.run_tier(root, "scripts/good.sh", "s0", cfg, entries).findings, [])


if __name__ == "__main__":
    unittest.main()
