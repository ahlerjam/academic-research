"""Guard partial orders: roles.json, dispatch.json and the quality bar only grow, proof specs, lenses and the
dogfood scenario only gain lines, package tsconfigs follow the template; plus the prefilled roles and dispatch entries."""

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

from lib import catalog, engine, gitx, guard, hooks, layout, manifest, roles  # noqa: E402

TEMPLATE = {"extends": "../../tsconfig.base.json", "compilerOptions": {"types": []}, "include": ["src", "test"]}
CORE_TSCONFIG = {"extends": "../../tsconfig.base.json", "compilerOptions": {"types": ["vite/client"]}, "include": ["src"]}
PROOF = "packages/web/e2e/proof/S1-QUOTE-EXACT.spec.ts"
LENS = "docs/review/lenses/tests.md"
PROOF_TEXT = ("import { expect, test } from '@playwright/test';\n\n"
              "test('S1-QUOTE-EXACT', async ({ page }) => {\n  await page.goto('/');\n"
              "  await expect(page).toHaveURL('/');\n});\n")
BAR = {"note": "A value may only be tightened, never loosened.",
       "budgets": [{"id": "cold-open-ms", "label": "cold open", "unit": "ms", "direction": "max", "threshold": 2000},
                   {"id": "recall-at-10", "label": "recall@10", "unit": "ratio", "direction": "min", "threshold": 0.8}]}
DOGFOOD_TEXT = "# Dogfood scenario\n\n1. Open the app.\n2. Export the PDF.\n"
SH_C = ["sh", "-c", "echo pwned > gates/gate.py", "{file}"]
PWN = ["sh", "-c", "echo pwned > PWNED; exit 0", "{file}"]


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


def _component(roles_map: dict, lang: str = "typescript", name: str = "newpkg") -> dict:
    """Return a new component entry below packages/<name>."""
    return {"lang": lang, "dir": f"packages/{name}", "root": f"packages/{name}/src", "roles": roles_map}


class GuardCase(unittest.TestCase):
    """Create one committed tree per test and remove it afterwards."""

    def tree(self, extra: Optional[Dict[str, str]] = None) -> str:
        root = support.make_tree(extra)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def assert_each_red(self, root: str, rel: str, cases: list) -> None:
        """Apply each change to a fresh copy of the JSON file and expect a message that starts with the given text."""
        original = _json(root, rel)
        for expected, change in cases:
            with self.subTest(expected=expected):
                data = copy.deepcopy(original)
                change(data)
                _dump(root, rel, data)
                whats = _whats(root, rel)
                self.assertTrue(any(w.startswith(expected) for w in whats), whats)


class RolesPartialOrder(GuardCase):
    """New roles, globs and tighter budgets pass; anything that weakens an existing entry is red."""

    def test_additions_and_tightening_pass(self) -> None:
        root = self.tree()
        cfg = _json(root, guard.ROLES)
        cfg["components"]["server"]["roles"]["wiring"].append("tools/run.ts")
        cfg["components"]["server"]["roles"]["adapter"].append("jobs/queue.ts")
        cfg["components"]["server"]["non_feature"].append("tools")
        cfg["components"]["core"]["roles"]["core"].append("lib/**/*.ts")
        cfg["components"]["core"]["roles"]["test"].append("../test/x/**/*.ts")
        cfg["components"]["web"]["roles"].setdefault("ui", []).append("panels/**/*.ts")
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
            ("component 'web' new glob 'views2/**/*.ts' for role 'test' lies inside the source root",
             lambda c: c["components"]["web"]["roles"]["test"].append("views2/**/*.ts")),
            ("component 'server' new glob '../src/x/**/*.ts' for role 'test' lies inside the source root",
             lambda c: c["components"]["server"]["roles"]["test"].append("../src/x/**/*.ts")),
            ("component 'server' new glob 'q/*.sql' for role 'migration' lies inside the source root",
             lambda c: c["components"]["server"]["roles"]["migration"].append("q/*.sql")),
            ("component 'server' new glob 'newfeat/*.ts' for role 'adapter' needs one file name without wildcards",
             lambda c: c["components"]["server"]["roles"]["adapter"].append("newfeat/*.ts")),
            ("component 'server' new glob 'jobs/**' for role 'wiring' needs one file name without wildcards",
             lambda c: c["components"]["server"]["roles"]["wiring"].append("jobs/**")),
            ("component 'web' new glob 'views/panel.ts' for role 'adapter' takes a file that an older glob",
             lambda c: c["components"]["web"]["roles"]["adapter"].append("views/panel.ts")),
            ("component 'server' new glob 'x/*.ts' for unknown role 'queue'",
             lambda c: c["components"]["server"]["roles"].update(queue=["x/*.ts"])),
            ("new component 'lax' needs a role api, ui with a '**/' glob",
             lambda c: c["components"].update(lax={"lang": "typescript", "dir": "packages/lax", "root": "packages/lax/src",
                                                   "roles": {"test": ["../test/**/*.ts"], "ui": ["views/*.ts"]}})),
            ("component 'lax2' new glob '**/*.ts' for role 'adapter' needs one file name without wildcards",
             lambda c: c["components"].update(lax2={"lang": "typescript", "dir": "packages/lax2",
                                                    "root": "packages/lax2/src",
                                                    "roles": {"ui": ["**/*.ts"], "adapter": ["**/*.ts"]}})),
        ]
        self.assert_each_red(self.tree(), guard.ROLES, cases)

    def test_edge_globs_stay_outside_the_source_root_and_keep_the_rules_they_take(self) -> None:
        cases = [
            ("component 'core' new glob '../**/*.logic.ts' for role 'test' lies inside the source root",
             lambda c: c["components"]["core"]["roles"]["test"].append("../**/*.logic.ts")),
            ("component 'web' new glob '../**/*.view.ts' for role 'test' lies inside the source root",
             lambda c: c["components"]["web"]["roles"]["test"].append("../**/*.view.ts")),
            ("component 'server' new glob '../**/*.q.ts' for role 'migration' lies inside the source root",
             lambda c: c["components"]["server"]["roles"]["migration"].append("../**/*.q.ts")),
            ("component 'core' new glob '**/*.test.ts' for role 'test' takes paths of role 'core' and drops",
             lambda c: c["components"]["core"]["roles"]["test"].append("**/*.test.ts")),
            ("component 'core' new glob '../../core/src/x.ts' is not in normal form",
             lambda c: c["components"]["core"]["roles"]["test"].append("../../core/src/x.ts")),
        ]
        self.assert_each_red(self.tree(), guard.ROLES, cases)
        root = self.tree()
        cfg = _json(root, guard.ROLES)
        cfg["components"]["core"]["roles"]["test"].append("../test/x/**/*.ts")
        cfg["components"]["server"]["roles"]["migration"].append("../migrations/x/*.sql")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [])

    def test_globs_in_normal_form_only(self) -> None:
        cases = [(f"component 'server' new glob '{glob}' is not in normal form",
                  lambda c, glob=glob: c["components"]["server"]["roles"]["adapter"].append(glob))
                 for glob in ("./feat/api.ts", "x/../feat/flow.ts", "feat//api.ts", "feat/", "feat/./api.ts")]
        self.assert_each_red(self.tree(), guard.ROLES, cases)
        root = self.tree()
        cfg = _json(root, guard.ROLES)
        cfg["components"]["server"]["roles"]["adapter"].append("./feat/api.ts")
        _dump(root, guard.ROLES, cfg)
        support.write(root, "packages/server/src/feat/api.ts", "export const api = 1;\n")
        place =roles.place_of(root, "packages/server/src/feat/api.ts", roles.load(root))
        self.assertEqual(place.role if place else None, "adapter", "the glob would have taken a future api file")

    def test_a_new_glob_that_takes_an_existing_file_is_red(self) -> None:
        root = self.tree({"packages/server/src/x/api.ts": "export const api = 1;\n"})
        cfg = _json(root, guard.ROLES)
        cfg["components"]["server"]["roles"]["flow"].append("x/*.ts")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), ["packages/server/src/x/api.ts moves from server/api to server/flow; "
                                                     "only additions are allowed against HEAD"])
        cfg["components"]["server"]["roles"]["flow"][-1] = "y/*.ts"
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [])

    def test_future_files_never_get_a_laxer_role(self) -> None:
        root = self.tree()
        cfg = _json(root, guard.ROLES)
        cfg["components"]["web"]["roles"]["test"].append("views2/**/*.ts")
        cfg["components"]["server"]["roles"]["adapter"].append("newfeat/*.ts")
        _dump(root, guard.ROLES, cfg)
        whats = _whats(root, guard.ROLES)
        self.assertEqual(len(whats), 2, whats)
        self.assertTrue(any("'views2/**/*.ts' for role 'test'" in w for w in whats), whats)
        self.assertTrue(any("'newfeat/*.ts' for role 'adapter'" in w for w in whats), whats)

    def test_a_new_open_role_glob_keeps_every_rule_of_the_role_it_outranks(self) -> None:
        root = self.tree()
        cfg = _json(root, guard.ROLES)
        cfg["components"]["web"]["roles"]["core"] = ["view2/**/*.ts"]
        _dump(root, guard.ROLES, cfg)
        self.assertIn("component 'web' new glob 'view2/**/*.ts' for role 'core' takes paths of role 'ui' and drops "
                      "TS-IO-ONLY-ADAPTER, TS-NO-CONSOLE, TS-NO-INNERHTML; else op:kernel; only additions are allowed "
                      "against HEAD", _whats(root, guard.ROLES))
        cfg["components"]["web"]["roles"].pop("core")
        cfg["components"]["web"]["roles"]["ui"].append("view2/**/*.ts")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [])

    def test_rule_ids_and_budgets_both_count(self) -> None:
        cases = [
            ("component 'server' new glob 'rules/*.ts' for role 'core' takes paths of role 'flow' and drops "
             "TS-IO-ONLY-ADAPTER, TS-NO-CONSOLE, TS-NO-DECISION-IN-FLOW, budget function_lines 30, budget module_lines 300",
             lambda c: c["components"]["server"]["roles"].update(core=["rules/*.ts"])),
            ("component 'web' new glob '**/*.html' for role 'api' takes paths of role 'ui' and drops TS-NO-INNERHTML",
             lambda c: c["components"]["web"]["roles"].update(api=["**/*.html"])),
            ("component 'plugin' new glob 'mcp' for role 'core' takes paths of role 'api'",
             lambda c: c["components"]["plugin"]["roles"].update(core=["mcp"])),
        ]
        self.assert_each_red(self.tree(), guard.ROLES, cases)
        root = self.tree()
        cfg = _json(root, guard.ROLES)
        cfg["components"]["server"]["roles"]["flow"].append("jobs/*.ts")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [], "flow keeps every rule of api")

    def test_core_and_flow_only_where_the_component_has_them(self) -> None:
        cases = [
            ("component 'server' new glob 'x/core/*.ts' for role 'core', which component 'server' does not have yet",
             lambda c: c["components"]["server"]["roles"].update(core=["x/core/*.ts"])),
            ("component 'web' new glob 'x/flow.ts' for role 'flow', which component 'web' does not have yet",
             lambda c: c["components"]["web"]["roles"].update(flow=["x/flow.ts"])),
            ("component 'web' new glob 'x/api.ts' for role 'api', new to 'web', would lose",
             lambda c: c["components"]["web"]["roles"].update(api=["x/api.ts"])),
        ]
        self.assert_each_red(self.tree(), guard.ROLES, cases)

    def test_new_components_hold_no_core_or_flow(self) -> None:
        cases = [
            (f"new component 'newpkg' role '{role}' would lose the component-bound rules of '{role}'; op:kernel",
             lambda c, role=role: c["components"].update(newpkg=_component({role: ["**/*.ts"], "api": ["**/*.ts"]})))
            for role in ("core", "flow")
        ]
        self.assert_each_red(self.tree(), guard.ROLES, cases)

    def test_new_components_keep_the_rules_of_each_role_elsewhere(self) -> None:
        cases = [
            ("new component 'newpkg' role 'ui' would lose TS-NO-INNERHTML",
             lambda c: c["components"].update(newpkg=_component({"ui": ["**/*.ts"]}))),
            ("new component 'newpkg' role 'api' would lose TS-ADAPTER-NO-FEATURE, TS-BEHAVIOUR, TS-FEATURES-INDEPENDENT, "
             "TS-LAYOUT",
             lambda c: c["components"].update(newpkg=_component({"api": ["**/*.ts"]}))),
            ("new component 'newpkg' role 'adapter' would lose",
             lambda c: c["components"].update(newpkg=_component({"ui": ["**/*.ts"], "adapter": ["lib/api.ts"]}))),
            ("new component 'newpkg' lang 'python' must be the lang of an existing component and match every glob's "
             "extension (not **/*.ts)",
             lambda c: c["components"].update(newpkg=_component({"ui": ["**/*.ts"]}, lang="python"))),
            ("new component 'newpkg' lang 'kotlin' must be the lang of an existing component",
             lambda c: c["components"].update(newpkg=_component({"ui": ["**/*.kt"]}, lang="kotlin"))),
        ]
        self.assert_each_red(self.tree(), guard.ROLES, cases)

    def test_glob_overlap_follows_git_pathspecs(self) -> None:
        pairs = [("packages/web/src/view2/**/*.ts", "packages/web/src/**/*.ts", True),
                 ("packages/server/src/rules/*/*.ts", "packages/server/src/*/flow.ts", False),
                 ("packages/server/src/rules/*.ts", "packages/server/src/*/flow.ts", True),
                 ("gates", "gates/lib/**", True), ("gate*", "gates/lib/**", False),
                 ("**/*.md", "AGENTS.md", True), ("packages/**/*.md", "**/.editorconfig", False),
                 ("packages/[ab]*/x.ts", "packages/a/x.ts", True), ("**/*.sh", ".claude/hooks/**", True),
                 ("scripts/run.sh", "**/.editorconfig", True), ("scripts/*.sh", "**/.editorconfig", False),
                 ("packages/core/**/*.logic.ts", "packages/core/src", True),
                 ("packages/core/test/x/**/*.ts", "packages/core/src", False)]
        for left, right, want in pairs:
            with self.subTest(left=left, right=right):
                self.assertEqual(guard._overlap(left, right), want)
                self.assertEqual(guard._overlap(right, left), want)

    def test_non_feature_only_for_new_directories_with_a_role_glob(self) -> None:
        root = self.tree({"packages/server/src/billing/flow.ts": "export const flow = 1;\n"})
        cfg = _json(root, guard.ROLES)
        cfg["components"]["server"]["non_feature"].append("billing")
        _dump(root, guard.ROLES, cfg)
        self.assertTrue(any("'billing', which already holds mapped files" in w for w in _whats(root, guard.ROLES)))
        cfg["components"]["server"]["non_feature"] = ["adapters", "cli", "dev", "data", "batch"]
        _dump(root, guard.ROLES, cfg)
        self.assertTrue(any("'batch' without a role glob" in w for w in _whats(root, guard.ROLES)))
        cfg["components"]["server"]["roles"]["wiring"].append("batch/run.ts")
        _dump(root, guard.ROLES, cfg)
        self.assertEqual(_whats(root, guard.ROLES), [])

    def test_unparsable_roles_file_is_red(self) -> None:
        root = self.tree()
        support.write(root, guard.ROLES, "{ not json\n")
        self.assertEqual(len(_whats(root, guard.ROLES)), 1)


class DispatchPartialOrder(GuardCase):
    """Entries may only be appended and only reuse older argv lists; mode only moves to strict."""

    def test_appended_entry_passes(self) -> None:
        root = self.tree()
        data = _json(root, guard.DISPATCH)
        prettier = data["entries"][1]
        bash_n = next(e for e in data["entries"] if e.get("finding_exits"))
        data["entries"].append({"glob": "packages/**/*.txt", "tier": "s1", "check": [["@rules"]]})
        data["entries"].append({"glob": "packages/**/*.md|scripts/**/*.md", "tier": "s0", "format": prettier["format"],
                                "format_check": prettier["format_check"], "check": prettier["check"]})
        data["entries"].append({"glob": "scripts/**/*.bash", "tier": "s0", "check": bash_n["check"],
                                "finding_exits": bash_n["finding_exits"]})
        _dump(root, guard.DISPATCH, data)
        self.assertEqual(_whats(root, guard.DISPATCH), [])
        self.assertEqual(guard.runnable_dispatch(root), (data["entries"], []))

    def test_weakening_is_red(self) -> None:
        cases = [
            ("existing entries changed", lambda d: d["entries"][1]["check"].pop(0)),
            ("existing entries changed", lambda d: d["entries"].reverse()),
            ("existing entries changed", lambda d: d["entries"].pop()),
            ("mode 'strict' -> 'touched-lines'", lambda d: d.update(mode="touched-lines")),
            ("top-level key 'extra' added", lambda d: d.update(extra=1)),
            ("new entry 8 needs a string 'glob' and 'tier'", lambda d: d["entries"].append({"glob": "x/*.md"})),
        ]
        self.assert_each_red(self.tree(), guard.DISPATCH, cases)

    def test_a_new_entry_runs_no_new_command(self) -> None:
        def add(**entry: object):
            return lambda d: d["entries"].append(dict({"glob": "packages/**/*.ts", "tier": "s0"}, **entry))

        prettier_write = ["prettier", "--write", "--log-level", "warn", "{file}"]
        cases = [
            (f"new entry 8 'format' {json.dumps(SH_C)} is not taken from the same key", add(format=SH_C)),
            (f"new entry 8 'format_check' {json.dumps(SH_C)} is not taken", add(format_check=SH_C)),
            (f"new entry 8 'format_check' {json.dumps(prettier_write)} is not taken", add(format_check=prettier_write)),
            (f"new entry 8 check {json.dumps(SH_C)} is neither an older check", add(check=[["@rules"], SH_C])),
            ("new entry 8 check \"sh\" is neither an older check", add(check="sh")),
            ("new entry 8 'cwd' \"component\" is not taken", add(cwd="component")),
            ("new entry 8 'finding_exits' [0, 1, 2] is not taken", add(finding_exits=[0, 1, 2])),
            ("new entry 8 'tier' \"s9\" is not taken", add(tier="s9")),
            ("new entry 8 has unknown key 'env'", add(env={"PATH": "."})),
        ]
        self.assert_each_red(self.tree(), guard.DISPATCH, cases)

    def test_a_new_entry_stays_off_operator_paths(self) -> None:
        def glob(text: str):
            return lambda d: d["entries"].append({"glob": text, "tier": "s1", "check": [["@rules"]]})

        cases = [
            ("new entry 8 glob part 'gates/lib/**' reaches operator-only '**/.editorconfig'", glob("gates/lib/**")),
            ("new entry 8 glob part 'Makefile' reaches operator-only 'Makefile', '**/.editorconfig'", glob("packages/**/*.ts|Makefile")),
            ("new entry 8 glob part 'gates' reaches operator-only", glob("gates")),
            ("new entry 8 glob part '**/*.md' reaches operator-only 'AGENTS.md'", glob("**/*.md")),
            ("new entry 8 glob part './ops/conductor/x.py' reaches operator-only '**/.editorconfig'",
             glob("./ops/conductor/x.py")),
            ("new entry 8 glob part 'packages/**/*.cjs' reaches operator-only '**/eslint.config.cjs'",
             glob("packages/**/*.cjs")),
            ("new entry 8 glob part '../x/*.ts' is empty, absolute, outside", glob("../x/*.ts")),
            ("new entry 8 glob part '' is empty", glob("packages/**/*.ts|")),
            ("new entry 8 glob part '/etc/*' is empty, absolute", glob("/etc/*")),
        ]
        self.assert_each_red(self.tree(), guard.DISPATCH, cases)

    def test_the_hook_never_runs_a_rejected_entry(self) -> None:
        root = self.tree({"packages/web/src/a.ts": "export const a = 1;\n"})
        base = _json(root, guard.DISPATCH)
        data = copy.deepcopy(base)
        data["entries"].append({"glob": "packages/**/*.ts", "tier": "s0", "format": PWN, "check": [PWN]})
        _dump(root, guard.DISPATCH, data)
        self.assertTrue(_whats(root, guard.DISPATCH))
        runnable, held = guard.runnable_dispatch(root)
        self.assertEqual(runnable, base["entries"])
        self.assertTrue(held and all("the hook runs only the entries of" in why for why in held), held)
        self.assertNotIn(PWN, [e.get("format") for e in engine.dispatch_entries(root, "packages/web/src/a.ts", "s0")])
        payload = {"tool_input": {"file_path": os.path.join(root, "packages/web/src/a.ts")}, "cwd": root}
        result = support.gate(root, ["hook", "post-edit"], payload)
        self.assertFalse(os.path.exists(os.path.join(root, "PWNED")), result.stderr)
        self.assertFalse(os.path.exists(os.path.join(root, "packages/web/src/PWNED")), result.stderr)
        self.assertEqual(result.returncode, 2)
        self.assertIn("GATES-RATCHET", result.stderr)
        batch = {"tool_calls": [{"tool_input": {"file_path": os.path.join(root, "packages/web/src/a.ts")}}], "cwd": root}
        support.gate(root, ["hook", "post-batch"], batch)
        self.assertFalse(os.path.exists(os.path.join(root, "PWNED")))


class QualityBarOrder(GuardCase):
    """Quality-bar budgets keep their ids and keys; max thresholds only fall, min thresholds only rise."""

    def base(self) -> str:
        return self.tree({guard.QUALITY_BAR: json.dumps(BAR, indent=1) + "\n", guard.DOGFOOD: DOGFOOD_TEXT})

    def test_both_product_files_are_ratchet_paths(self) -> None:
        root = self.base()
        cfg = manifest.controls(root)
        for rel in (guard.QUALITY_BAR, guard.DOGFOOD):
            with self.subTest(rel=rel):
                self.assertIn(rel, cfg["ratchet"])
                self.assertFalse(hooks.is_control_path(root, rel))

    def test_tightening_and_new_budgets_pass(self) -> None:
        root = self.base()
        bar = copy.deepcopy(BAR)
        bar["budgets"][0]["threshold"] = 1500
        bar["budgets"][1]["threshold"] = 0.9
        bar["budgets"].append({"id": "export-ms", "label": "export", "unit": "ms", "direction": "max", "threshold": 30000})
        _dump(root, guard.QUALITY_BAR, bar)
        support.write(root, guard.DOGFOOD, DOGFOOD_TEXT + "3. Restore a backup.\n")
        self.assertEqual(_whats(root, guard.QUALITY_BAR) + _whats(root, guard.DOGFOOD), [])

    def test_loosening_is_red(self) -> None:
        def budget(i: int, **change: object):
            return lambda b: b["budgets"][i].update(change)

        cases = [
            ("budget 'cold-open-ms' threshold 2000 -> 2001 loosens a 'max' bar", budget(0, threshold=2001)),
            ("budget 'recall-at-10' threshold 0.8 -> 0.7 loosens a 'min' bar", budget(1, threshold=0.7)),
            ("budget 'cold-open-ms' key 'direction' changed", budget(0, direction="min")),
            ("budget 'cold-open-ms' key 'unit' changed", budget(0, unit="s")),
            ("budget 'cold-open-ms' removed", lambda b: b["budgets"].pop(0)),
            ("budget 'cold-open-ms' needs a string id", budget(0, threshold=float("nan"))),
            ("budget 'cold-open-ms' needs a string id", budget(0, threshold=True)),
            ("budget 'cold-open-ms' needs a string id", budget(0, threshold="1000")),
            ("budget 'cold-open-ms' needs a string id", budget(0, direction="none")),
            ("budget 'cold-open-ms' appears twice", lambda b: b["budgets"].append(dict(b["budgets"][0], threshold=9e9))),
            ("'note' changed", lambda b: b.update(note="Loosen at will.")),
            ("top-level key 'override' added", lambda b: b.update(override=True)),
            ("'budgets' is no longer a list of objects", lambda b: b.update(budgets={"cold-open-ms": 1})),
        ]
        self.assert_each_red(self.base(), guard.QUALITY_BAR, cases)

    def test_the_dogfood_scenario_only_grows_at_its_end(self) -> None:
        root = self.base()
        support.write(root, guard.DOGFOOD, DOGFOOD_TEXT.replace("2. Export", "2. Skip the export.\n3. Export"))
        self.assertEqual(_whats(root, guard.DOGFOOD), ["changed before its end against HEAD; only append at the end"])
        support.write(root, guard.DOGFOOD, DOGFOOD_TEXT.rstrip("\n") + " Slow machines may take 300 s.\n")
        self.assertEqual(_whats(root, guard.DOGFOOD), ["changed before its end against HEAD; only append at the end"],
                         "the last step was lengthened")
        support.write(root, guard.DOGFOOD, DOGFOOD_TEXT + "\n\n")
        self.assertEqual(_whats(root, guard.DOGFOOD), [])
        support.write(root, guard.DOGFOOD, DOGFOOD_TEXT.rstrip("\n"))
        self.assertEqual(_whats(root, guard.DOGFOOD), [])
        os.remove(os.path.join(root, guard.DOGFOOD))
        os.remove(os.path.join(root, guard.QUALITY_BAR))
        self.assertEqual(_whats(root, guard.DOGFOOD), ["deleted against HEAD; this path only grows"])
        self.assertEqual(len(_whats(root, guard.QUALITY_BAR)), 1)


class AddOnlyPaths(GuardCase):
    """Proof specs and review lenses gain lines only; each proof file holds an expect call."""

    def base(self) -> str:
        return self.tree({PROOF: PROOF_TEXT, LENS: "# Tests lens\n\n- A test fails on the old code.\n"})

    def test_appended_text_and_new_files_pass(self) -> None:
        root = self.base()
        support.write(root, PROOF, PROOF_TEXT + "\ntest('S1-QUOTE-EXACT reload', async ({ page }) => {\n"
                                                "  await page.reload();\n  await expect(page).toHaveURL('/');\n});\n")
        support.write(root, LENS, "# Tests lens\n\n- A test fails on the old code.\n- A negative case exists.\n")
        support.write(root, "packages/web/e2e/proof/S1-TRACE-BLOCKS.spec.ts", PROOF_TEXT)
        self.assertEqual([f for f in guard.violations(root) if f.path.startswith(guard.ADD_ONLY)], [])

    def test_text_inserted_before_the_end_is_red(self) -> None:
        root = self.base()
        support.write(root, PROOF, PROOF_TEXT.replace("  await page.goto('/');\n", "  return;\n  await page.goto('/');\n"))
        support.write(root, LENS, "# Tests lens\n\n- Findings about X are out of scope.\n- A test fails on the old code.\n")
        self.assertEqual(_whats(root, PROOF), ["changed before its end against HEAD; only append at the end"])
        self.assertEqual(_whats(root, LENS), ["changed before its end against HEAD; only append at the end"])

    def test_an_expect_in_a_comment_does_not_count(self) -> None:
        root = self.base()
        support.write(root, "packages/web/e2e/proof/S1-NOTE.spec.ts",
                      "test('S1-NOTE', async () => {\n  // expect(page).toHaveURL('/');\n  /* expect(x) */\n});\n")
        self.assertEqual(_whats(root, "packages/web/e2e/proof/S1-NOTE.spec.ts"), ["proof file without an expect call"])

    def test_removed_changed_deleted_or_expectless_is_red(self) -> None:
        root = self.base()
        support.write(root, PROOF, PROOF_TEXT.replace("await expect(page).toHaveURL('/');", "await page.goto('/');"))
        os.remove(os.path.join(root, LENS))
        support.write(root, "packages/web/e2e/proof/S1-EMPTY.spec.ts", "test('S1-EMPTY', () => {});\n")
        whats = sorted((f.path, f.what.split(";")[0]) for f in guard.violations(root) if f.path.startswith(guard.ADD_ONLY))
        self.assertEqual(whats, sorted([(LENS, "deleted against HEAD"),
                                        (PROOF, "changed before its end against HEAD"),
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

    def test_package_tsconfigs_are_ratchet_paths_an_agent_may_write(self) -> None:
        root = self.base()
        cfg = manifest.controls(root)
        self.assertIn("packages/*/tsconfig.json", cfg["ratchet"])
        for rel in ("packages/extra/tsconfig.json", "packages/core/tsconfig.json"):
            with self.subTest(rel=rel):
                self.assertFalse(hooks.is_control_path(root, rel))
        self.assertTrue(hooks.is_control_path(root, "tsconfig.base.json"))
        _dump(root, "packages/extra/tsconfig.json", TEMPLATE)
        self.assertEqual(_whats(root, "packages/extra/tsconfig.json"), [])
        _dump(root, "packages/extra/tsconfig.json", dict(TEMPLATE, compilerOptions={"types": [], "strict": False}))
        self.assertEqual(_whats(root, "packages/extra/tsconfig.json"), [f"differs from {guard.TEMPLATE} outside 'include'"])

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


class BaseRef(GuardCase):
    """A local branch or tag named origin/main never replaces the remote-tracking ref the gates compare against."""

    def test_a_local_origin_main_does_not_shadow_the_remote(self) -> None:
        root = self.tree({"probe.txt": "remote\n"})
        remote = support.git(root, "rev-parse", "HEAD").stdout.strip()
        support.git(root, "update-ref", "refs/remotes/origin/main", remote)
        support.write(root, "probe.txt", "evil\n")
        support.git(root, *support.GIT_ID, "commit", "-q", "-am", "evil")
        support.git(root, "branch", "origin/main", "HEAD")
        support.git(root, "tag", "origin/main", "HEAD")
        self.assertEqual(support.git(root, "show", "origin/main:probe.txt").stdout, "evil\n", "short names are shadowed")
        ref = gitx.base_ref(root)
        self.assertEqual(ref, "refs/remotes/origin/main")
        self.assertEqual(gitx.show(root, ref, "probe.txt"), "remote\n")
        support.git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.assertEqual(gitx.default_ref(root), "refs/remotes/origin/main")


if __name__ == "__main__":
    unittest.main()
