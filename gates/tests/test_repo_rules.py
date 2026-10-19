"""Repo rules that need git history: diff duty, migration immutability, Alembic heads; plus the Bash normaliser."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import support  # noqa: E402

from lib import adr, cmdnorm, drift, engine, guard, hooks, manifest, migrations, stopgate, sync, tests_duty, tools  # noqa: E402
from lib.findings import Finding  # noqa: E402

PY_CFG = {"ignore": [], "budgets": {}, "components": {"c": {
    "lang": "python", "dir": "c", "root": "c/app",
    "roles": {"core": ["*/core.py"], "adapter": ["adapters/*.py"], "test": ["../tests/*.py"]}}}}


class DiffDuty(unittest.TestCase):
    """A changed core without a changed test of its component is red once a base branch exists."""

    def test_core_change_without_test_change(self) -> None:
        root = support.make_tree()
        remote = tempfile.mkdtemp(prefix="gates-remote-")
        try:
            cfg = {"ignore": [], "budgets": {}, "components": {"c": {
                "lang": "python", "dir": "c", "root": "c/app",
                "roles": {"core": ["*/core.py"], "test": ["../tests/*.py"]}}}}
            support.write(root, "c/app/f/core.py", "def decide_x() -> int:\n    return 1\n")
            support.write(root, "c/tests/test_f_core.py", "def test_x() -> None:\n    assert True\n")
            support.git(root, "add", "-A")
            support.git(root, *support.GIT_ID, "commit", "-q", "-m", "base")
            support.git(remote, "init", "-q", "--bare")
            support.git(root, "remote", "add", "origin", remote)
            support.git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
            support.git(root, "fetch", "-q", "origin")
            support.write(root, "c/app/f/core.py", "def decide_x() -> int:\n    return 2\n")
            self.assertEqual(len(tests_duty.diff_violations(root, cfg, {"c": "DIFF"})), 1)
            support.write(root, "c/tests/test_f_core.py", "def test_x() -> None:\n    assert 2\n")
            self.assertEqual(len(tests_duty.diff_violations(root, cfg, {"c": "DIFF"})), 1)
            support.write(root, "c/tests/test_f_core.py", "def test_x() -> None:\n    assert decide_x() == 2\n")
            self.assertEqual(tests_duty.diff_violations(root, cfg, {"c": "DIFF"}), [])
        finally:
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(remote, ignore_errors=True)


    def test_without_remote_the_working_tree_counts(self) -> None:
        root = support.make_tree({"c/app/f/core.py": "def decide_x() -> int:\n    return 1\n"})
        try:
            self.assertEqual(tests_duty.diff_violations(root, PY_CFG, {"c": "DIFF"}), [])
            support.write(root, "c/app/f/core.py", "def decide_x() -> int:\n    return 2\n")
            self.assertEqual(len(tests_duty.diff_violations(root, PY_CFG, {"c": "DIFF"})), 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestDuties(unittest.TestCase):
    """The result of every decide and translate function must flow into an assertion of the same test."""

    def run_duty(self, files: dict, cfg: dict = PY_CFG) -> list:
        root = support.make_tree(files)
        try:
            return [f.what for f in tests_duty.decide_violations(root, cfg, {"c": "DUTY"})]
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_python_data_flow(self) -> None:
        core = {"c/app/f/core.py": "def decide_x(n: int) -> int:\n    return n\n",
                "c/app/adapters/api.py": "def translate_answer(raw: dict) -> int:\n    return 1\n"}
        assert_true = "def test_x() -> None:\n    decide_x(1)\n    translate_answer({})\n    assert True\n"
        self.assertEqual(len(self.run_duty(dict(core, **{"c/tests/test_f.py": assert_true}))), 2)
        flows = ("def test_x() -> None:\n    result = decide_x(1)\n    assert result == 1\n"
                 "def test_y() -> None:\n    assert translate_answer({}) == 1\n")
        self.assertEqual(self.run_duty(dict(core, **{"c/tests/test_f.py": flows})), [])
        other_test = ("def test_x() -> None:\n    result = decide_x(1)\n    translate_answer({})\n"
                      "def test_y() -> None:\n    result = 2\n    assert result == 2\n")
        self.assertEqual(len(self.run_duty(dict(core, **{"c/tests/test_f.py": other_test}))), 2)

    def test_typescript_heuristic(self) -> None:
        cfg = {"ignore": [], "budgets": {}, "components": {"c": {
            "lang": "typescript", "dir": "c", "root": "c/src/app",
            "roles": {"core": ["*/core/**/*.ts"], "test": ["**/*.spec.ts"]}}}}
        core = {"c/src/app/f/core/value.ts": "export const decideValue = (n: number): number => n;\n"}
        bad = "it('x', () => {\n  decideValue(1);\n  expect(true).toBe(true);\n});\n"
        self.assertEqual(len(self.run_duty(dict(core, **{"c/src/app/f/core/value.spec.ts": bad}), cfg)), 1)
        good = "it('x', () => {\n  const v = decideValue(1);\n  expect(v).toBe(1);\n});\n"
        self.assertEqual(self.run_duty(dict(core, **{"c/src/app/f/core/value.spec.ts": good}), cfg), [])

    def test_empty_behaviour_test_is_red(self) -> None:
        cfg = {"ignore": [], "budgets": {}, "components": {"c": {
            "lang": "typescript", "dir": "c", "root": "c/src/app", "behaviour_test": "../../e2e/{feature}.spec.ts",
            "roles": {"core": ["*/core/**/*.ts"], "test": ["**/*.spec.ts", "../../e2e/**/*.ts"]}}}}
        root = support.make_tree({"c/src/app/f/core/value.ts": "export const v = 1;\n", "c/e2e/f.spec.ts": "\n"})
        try:
            self.assertEqual(len(tests_duty.behaviour_violations(root, cfg, {"c": "B"})), 1)
            support.write(root, "c/e2e/f.spec.ts", "test('f', async ({ page }) => {\n  await page.goto('/');\n"
                                                   "  await expect(page).toHaveURL('/');\n});\n")
            self.assertEqual(tests_duty.behaviour_violations(root, cfg, {"c": "B"}), [])
            support.write(root, "c/e2e/f.spec.ts", "test.skip('f', async ({ page }) => {\n  await page.goto('/');\n"
                                                   "  await expect(page).toHaveURL('/');\n});\n")
            self.assertEqual(len(tests_duty.behaviour_violations(root, cfg, {"c": "B"})), 1, "a skipped test is no test")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_skipped_python_test_proves_nothing(self) -> None:
        cfg = {"ignore": [], "budgets": {}, "components": {"c": {
            "lang": "python", "dir": "c", "root": "c/app", "behaviour_test": "../tests/test_{feature}.py",
            "roles": {"core": ["*/core.py"], "test": ["../tests/**/*.py"]}}}}
        skipped = ("import pytest\n\n\n@pytest.mark.skip(reason='wip')\ndef test_f() -> None:\n"
                   "    assert decide_x(1) == 1\n")
        root = support.make_tree({"c/app/f/core.py": "def decide_x(n: int) -> int:\n    return n\n",
                                  "c/tests/test_f.py": skipped})
        try:
            self.assertEqual(len(tests_duty.behaviour_violations(root, cfg, {"c": "B"})), 1)
            self.assertEqual(len(tests_duty.decide_violations(root, cfg, {"c": "D"})), 1)
            support.write(root, "c/tests/test_f.py", "pytestmark = __import__('pytest').mark.xfail\n"
                                                     "def test_f() -> None:\n    assert decide_x(1) == 1\n")
            self.assertEqual(len(tests_duty.behaviour_violations(root, cfg, {"c": "B"})), 1)
            support.write(root, "c/tests/test_f.py", "def test_f() -> None:\n    assert decide_x(1) == 1\n")
            self.assertEqual(tests_duty.behaviour_violations(root, cfg, {"c": "B"}), [])
            self.assertEqual(tests_duty.decide_violations(root, cfg, {"c": "D"}), [])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class AdrMechanics(unittest.TestCase):
    """Duplicate numbers are red, adr new skips numbers of other worktrees, supersedes needs the status."""

    def adr(self, number: int, slug: str, extra: str = "", status: str = "accepted") -> str:
        return (f"---\nid: {number}\ntitle: {slug}\nstatus: {status}\ntags: [x]\n{extra}---\n\n"
                f"# ADR-{number:04d}: {slug}\n")

    def test_duplicate_number_is_red(self) -> None:
        root = support.make_tree({"decisions/0001-a.md": self.adr(1, "a"), "decisions/0001-b.md": self.adr(1, "b")})
        try:
            self.assertTrue(any("duplicate ADR number" in f.what for f in adr.violations(root, "ADR-FORMAT")))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_superseded_target_needs_the_status(self) -> None:
        root = support.make_tree({"decisions/0001-a.md": self.adr(1, "a"),
                                  "decisions/0002-b.md": self.adr(2, "b", "supersedes: [1]\n")})
        try:
            whats = [f.what for f in adr.violations(root, "ADR-FORMAT")]
            self.assertTrue(any("set status: superseded" in w for w in whats))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_new_skips_numbers_of_other_worktrees(self) -> None:
        root = support.make_tree({"decisions/0001-a.md": self.adr(1, "a")})
        other = tempfile.mkdtemp(prefix="gates-wt-")
        try:
            os.rmdir(other)
            support.git(root, "worktree", "add", "-q", "-b", "other", other)
            first = adr.new(other, "alpha", "en")
            second = adr.new(root, "beta", "en")
            self.assertEqual(first, "decisions/0002-alpha.md")
            self.assertEqual(second, "decisions/0003-beta.md")
        finally:
            shutil.rmtree(other, ignore_errors=True)
            shutil.rmtree(root, ignore_errors=True)


class BashGuardExtras(unittest.TestCase):
    """Branch-aware push and vendor token shapes (built at runtime, never as literals)."""

    def test_bare_push_on_a_protected_branch(self) -> None:
        root = support.make_tree()
        try:
            support.git(root, "checkout", "-q", "-B", "main")
            self.assertTrue(hooks.protected_push(root, [["git", "push"]], "main|master"))
            self.assertTrue(hooks.protected_push(root, [["git", "push", "origin", "HEAD"]], "main|master"))
            self.assertEqual(hooks.protected_push(root, [["git", "push", "origin", "feature"]], "main|master"), [])
            support.git(root, "checkout", "-q", "-b", "feature")
            self.assertEqual(hooks.protected_push(root, [["git", "push"]], "main|master"), [])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_vendor_token_shapes(self) -> None:
        with open(os.path.join(support.SOURCE, "gates", "bash_rules.json"), encoding="utf-8") as handle:
            rules = [r for r in json.load(handle)["rules"] if r["id"] == "BASH-SECRET-VENDOR"]
        samples = ["AK" + "IA" + "A" * 16, "gh" + "p_" + "a" * 36, "s" + "k-" + "b" * 24]
        for sample in samples:
            self.assertTrue(cmdnorm.raw_match(f"curl -H 'x: {sample}' https://example.invalid", rules), sample)
        self.assertEqual(cmdnorm.raw_match("git status", rules), [])


class SharedFingerprint(unittest.TestCase):
    """A file outside every component (the contract) still changes the stop-gate cache key of each component."""

    def test_contract_change_invalidates_the_component_cache(self) -> None:
        from lib import stopgate
        root = support.make_tree({"contracts/openapi.json": "{}\n"})
        try:
            with open(os.path.join(root, "gates", "roles.json"), encoding="utf-8") as handle:
                cfg = json.load(handle)
            cfg["shared_fingerprint"] = ["contracts/**"]
            support.write(root, "gates/roles.json", json.dumps(cfg))
            comp = sorted(cfg["components"])[0]
            before = stopgate._fingerprint(root, comp, [])
            support.write(root, "contracts/openapi.json", '{"paths": {}}\n')
            self.assertNotEqual(before, stopgate._fingerprint(root, comp, []))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class PhonyTargets(unittest.TestCase):
    """D14: a .PHONY name without a rule is a finding."""

    def test_typo_in_phony_list(self) -> None:
        root = support.make_tree()
        try:
            support.write(root, "Makefile", ".PHONY: real @typo\nreal:\n\t@true\n")
            self.assertEqual([f.what for f in drift.d14(root)], [".PHONY names '@typo', which no rule defines"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Migrations(unittest.TestCase):
    """Numbering, immutability and Alembic heads."""

    def test_gap_duplicate_and_changed_migration(self) -> None:
        root = support.make_tree({"db/migrations/0001_init.sql": "create table a (id int);\n"})
        try:
            self.assertEqual(migrations.sql_violations(root, "db/migrations", "M"), [])
            support.write(root, "db/migrations/0001_init.sql", "create table b (id int);\n")
            support.write(root, "db/migrations/0003_gap.sql", "select 1;\n")
            whats = " ".join(f.what for f in migrations.sql_violations(root, "db/migrations", "M"))
            self.assertIn("without gaps", whats)
            self.assertIn("was changed", whats)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_two_alembic_heads(self) -> None:
        root = support.make_tree({
            "m/versions/a.py": 'revision = "a"\ndown_revision = None\n',
            "m/versions/b.py": 'revision = "b"\ndown_revision = "a"\n',
            "m/versions/c.py": 'revision = "c"\ndown_revision = "a"\n'})
        try:
            found = migrations.alembic_violations(root, "m/versions", "H")
            self.assertEqual(len(found), 1)
            os.remove(os.path.join(root, "m/versions/c.py"))
            self.assertEqual(migrations.alembic_violations(root, "m/versions", "H"), [])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Ratchet(unittest.TestCase):
    """With a ratchet, new rules pass and changed or deleted rules are red."""

    def test_changed_rule_is_red_and_new_rule_passes(self) -> None:
        root = support.make_tree({"gates/rules/x/R1.yml": "id: R1\n", "gates/rule-tests/x/R1-test.yml": "id: R1\nvalid:\n  - a\n"})
        try:
            path = os.path.join(root, "gates", "controls.json")
            with open(path, encoding="utf-8") as handle:
                controls = json.load(handle)
            controls["ratchet"] = ["gates/rules/**", "gates/rule-tests/**"]
            support.write(root, "gates/controls.json", json.dumps(controls))
            support.write(root, "gates/rules/x/R2.yml", "id: R2\n")
            self.assertEqual(guard.violations(root), [])
            support.write(root, "gates/rules/x/R1.yml", "id: R1\nseverity: off\n")
            support.write(root, "gates/rule-tests/x/R1-test.yml", "id: R1\n")
            rules = {f.path for f in guard.violations(root)}
            self.assertIn("gates/rules/x/R1.yml", rules)
            self.assertIn("gates/rule-tests/x/R1-test.yml", rules)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ToolTables(unittest.TestCase):
    """D15: a tool table in pyproject.toml would outrank the operator's config files."""

    def test_tool_table_in_pyproject_is_red(self) -> None:
        root = support.make_tree({"c/pyproject.toml": "[project]\nname = 'x'\n"})
        try:
            self.assertEqual(drift.d15(root), [])
            support.write(root, "c/sub/pyproject.toml", "[tool.ruff.lint]\nselect = ['E']\n")
            self.assertEqual([f.rule for f in drift.d15(root)], ["GATES-D15"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Sandbox(unittest.TestCase):
    """Question 11 = yes renders sandbox.enabled with concrete denyWrite paths; a local opt-out is red."""

    def test_sandbox_block_and_local_opt_out(self) -> None:
        root = support.make_tree({})
        try:
            path = os.path.join(root, "gates", "project.json")
            with open(path, encoding="utf-8") as handle:
                project = json.load(handle)
            self.assertNotIn("sandbox", json.loads(sync.settings(root)))
            project["sandbox"] = True
            support.write(root, "gates/project.json", json.dumps(project))
            block = json.loads(sync.settings(root))["sandbox"]
            self.assertTrue(block["enabled"])
            self.assertTrue(any(p == "./gates" or p.startswith("./gates/") for p in block["filesystem"]["denyWrite"]))
            self.assertFalse([p for p in block["filesystem"]["denyWrite"] if any(c in p for c in "*?[")])
            support.write(root, ".claude/settings.local.json", "{}")
            self.assertEqual(json.loads(sync.settings(root))["sandbox"], block, "a new local file changes nothing")
            support.write(root, ".claude/settings.local.json", '{"sandbox": {"enabled": false}}')
            self.assertEqual([f.rule for f in manifest.local_findings(root)], ["GATES-CONTROLS"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ToolPaths(unittest.TestCase):
    """Findings name repo-relative paths even when a tool reports absolute ones (ESLint, Stylelint)."""

    def test_absolute_path_becomes_relative(self) -> None:
        root = tempfile.mkdtemp(prefix="gates-paths-")
        try:
            found = tools._in_tree(root, Finding(os.path.join(root, "frontend", "a.ts"), 3, "X", "w"))
            self.assertEqual(found.path, os.path.join("frontend", "a.ts"))
            self.assertEqual(tools._in_tree(root, Finding("/elsewhere/a.ts", 1, "X", "w")).path, "/elsewhere/a.ts")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Normaliser(unittest.TestCase):
    """cmdnorm unwraps shells, strips git globals and masks commit messages."""

    def test_segments(self) -> None:
        self.assertEqual(cmdnorm.segments("git -C . push -f"), [["git", "push", "-f"]])
        self.assertEqual(cmdnorm.segments("bash -c 'a && git status'"), [["a"], ["git", "status"]])
        self.assertEqual(cmdnorm.segments('git commit -m "x --force"'), [["git", "commit", "-m", "MESSAGE"]])
        self.assertEqual(cmdnorm.segments("cat <<EOF\nx\nEOF"), [["cat"]])
        self.assertEqual(cmdnorm.segments("timeout 30 sudo -u me git push -f"), [["git", "push", "-f"]])
        self.assertEqual(cmdnorm.segments("xargs -n1 git status"), [["git", "status"]])

    def test_write_targets(self) -> None:
        self.assertEqual(cmdnorm.write_targets(["echo", "x", ">", "AGENTS.md"]), ["AGENTS.md"])
        self.assertEqual(cmdnorm.write_targets(["cp", "a", "b"]), ["b"])
        self.assertIn("gates/x", cmdnorm.write_targets(["sed", "-i", "s/a/b/", "gates/x"]))
        self.assertIn("Makefile", cmdnorm.write_targets(["dd", "if=/dev/zero", "of=Makefile"]))
        self.assertEqual(cmdnorm.write_targets(["git", "checkout", "--", "AGENTS.md"]), [])
        self.assertEqual(cmdnorm.write_targets(["git", "checkout", "HEAD~1", "--", "AGENTS.md"]), ["AGENTS.md"])

    def test_rules_file_parses(self) -> None:
        with open(os.path.join(support.SOURCE, "gates", "bash_rules.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertTrue(all("{{" not in r["pattern"] for r in data["rules"]))



class StopOutput(unittest.TestCase):
    """The stop gate reports tool output by the contract: relative paths, pyright with a code, no pass noise."""

    def test_pyright_lines_get_a_relative_path_and_a_code(self) -> None:
        out = ("RESULT: PASS lint-backend-py 1s\n/tree/backend/app/health/flow.py\n"
               "  /tree/backend/app/health/flow.py:18:12 - error: Type \"str\" is not assignable to return type \"int\"\n"
               "  \u00a0\u00a0\"str\" is not assignable to \"int\" (reportReturnType)\n1 error, 0 warnings, 0 informations\n")
        text = stopgate._filter("/tree", out)
        self.assertIn("backend/app/health/flow.py:18 [pyright:reportReturnType] Type \"str\" is not assignable "
                      "to return type \"int\"; \"str\" is not assignable to \"int\"", text)
        self.assertNotIn("/tree/", text)
        self.assertNotIn("RESULT: PASS", text)

    def test_format_findings_carry_the_fix_hint_and_pytest_errors_are_kept(self) -> None:
        text = stopgate._filter("/tree", "backend/app/x.py:1 [GATES-FORMAT] not formatted; run make fix\n")
        self.assertIn("Run `make fix`", text)
        kept = stopgate._filter("/tree", "ERROR: file or directory not found: tests/test_*_core.py\nmake: *** Error 1\n")
        self.assertIn("ERROR: file or directory not found", kept)
        self.assertNotIn("make: ***", kept)


class FormatCheck(unittest.TestCase):
    """A file written outside Edit is format-checked in post-batch: exit 1 is GATES-FORMAT, exit 2 infrastructure."""

    def test_exit_codes_map_to_findings(self) -> None:
        root = tempfile.mkdtemp(prefix="gates-format-")
        try:
            support.write(root, "a.py", "x\n")
            rules = [engine.format_check(root, ".", ["sh", "-c", f"exit {code}", "{file}"], "a.py", False) for code in (0, 1, 2)]
            self.assertEqual(rules[0], [])
            self.assertEqual([f.rule for f in rules[1]], ["GATES-FORMAT"])
            self.assertEqual([f.rule for f in rules[2]], ["GATES-INFRA"])
            self.assertEqual(rules[1][0].path, "a.py")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
