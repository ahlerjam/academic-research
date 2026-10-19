"""Behaviour of the hooks: honest stop gate, subagent delta, single flight, self-protection, fail-closed wrappers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from tests import support

CORE = "probe/data.txt"


class StopGateHonesty(unittest.TestCase):
    """Section 13: stop 1 blocks, stop 2 with changes blocks, stop 3 unchanged releases loudly."""

    def setUp(self) -> None:
        self.root = support.make_tree({CORE: "VALUE = 1\n"})
        support.write(self.root, "RED", "red\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def stop(self, active: bool) -> subprocess.CompletedProcess:
        return support.gate(self.root, ["hook", "stop"], {"stop_hook_active": active, "cwd": self.root})

    def test_red_tree_blocks_then_changed_tree_blocks_then_unchanged_tree_releases_loudly(self) -> None:
        first = self.stop(False)
        self.assertEqual(first.returncode, 2, first.stderr)
        self.assertIn("STUB-RED", first.stderr)
        support.write(self.root, CORE, "VALUE = 2\n")
        second = self.stop(True)
        self.assertEqual(second.returncode, 2, "a changed red tree must block even with stop_hook_active")
        third = self.stop(True)
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertIn("systemMessage", third.stdout)
        self.assertIn("red_marker", support.state(self.root))

    def test_new_turn_on_the_same_red_tree_blocks_again(self) -> None:
        self.assertEqual(self.stop(False).returncode, 2)
        self.assertEqual(self.stop(False).returncode, 2)

    def test_green_tree_passes_and_clears_the_marker(self) -> None:
        self.assertEqual(self.stop(False).returncode, 2)
        os.remove(os.path.join(self.root, "RED"))
        result = self.stop(False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("red_marker", support.state(self.root))


class SubagentDelta(unittest.TestCase):
    """A subagent is judged on its own changes, not on the red tree of its parent."""

    def setUp(self) -> None:
        self.root = support.make_tree({CORE: "VALUE = 1\n"})
        support.write(self.root, "RED", "red\n")
        support.write(self.root, CORE, "VALUE = 3\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_reading_subagent_passes_on_a_red_parent_tree(self) -> None:
        payload = {"agent_id": "a1", "agent_type": "general-purpose", "cwd": self.root}
        self.assertEqual(support.gate(self.root, ["hook", "subagent-start"], payload).returncode, 0)
        result = support.gate(self.root, ["hook", "subagent-stop"], dict(payload, stop_hook_active=False))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_writing_subagent_is_gated(self) -> None:
        payload = {"agent_id": "a2", "agent_type": "general-purpose", "cwd": self.root}
        support.gate(self.root, ["hook", "subagent-start"], payload)
        support.write(self.root, CORE, "VALUE = 4\n")
        result = support.gate(self.root, ["hook", "subagent-stop"], dict(payload, stop_hook_active=False))
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_explore_and_plan_pass(self) -> None:
        payload = {"agent_id": "a3", "agent_type": "Explore", "cwd": self.root, "stop_hook_active": False}
        self.assertEqual(support.gate(self.root, ["hook", "subagent-stop"], payload).returncode, 0)


class SingleFlight(unittest.TestCase):
    """Two parallel stops in one tree compute each component once."""

    def test_parallel_stops_share_one_run(self) -> None:
        root = support.make_tree({CORE: "VALUE = 1\n"})
        try:
            results = []
            threads = [threading.Thread(target=lambda: results.append(
                support.gate(root, ["hook", "stop"], {"stop_hook_active": False, "cwd": root}))) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual([r.returncode for r in results], [0, 0], [r.stderr for r in results])
            self.assertEqual(support.count(root, "repo"), 1)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class SelfProtection(unittest.TestCase):
    """Manifest, ConfigChange, pre-write and the fail-closed wrapper."""

    def setUp(self) -> None:
        self.root = support.make_tree({CORE: "VALUE = 1\n"})

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_script_write_to_a_control_file_is_caught_at_stop(self) -> None:
        with open(os.path.join(self.root, "gates", "roles.json"), "a", encoding="utf-8") as handle:
            handle.write("\n")
        result = support.gate(self.root, ["hook", "stop"], {"stop_hook_active": False, "cwd": self.root})
        self.assertEqual(result.returncode, 2)
        self.assertIn("GATES-CONTROLS", result.stderr)

    def test_unchanged_red_controls_release_loudly(self) -> None:
        with open(os.path.join(self.root, "gates", "roles.json"), "a", encoding="utf-8") as handle:
            handle.write("\n")
        first = support.gate(self.root, ["hook", "stop"], {"stop_hook_active": False, "cwd": self.root})
        self.assertEqual(first.returncode, 2)
        again = support.gate(self.root, ["hook", "stop"], {"stop_hook_active": True, "cwd": self.root})
        self.assertEqual(again.returncode, 0)
        self.assertIn("systemMessage", again.stdout)
        self.assertIn("GATES-CONTROLS", support.state(self.root)["red_marker"]["rules"])

    def test_stop_wrapper_verifies_the_gate_code(self) -> None:
        with open(os.path.join(self.root, ".claude", "settings.json"), encoding="utf-8") as handle:
            command = json.load(handle)["hooks"]["Stop"][0]["hooks"][0]["command"]
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.root)
        env.pop("GATES_NESTED", None)
        payload = json.dumps({"stop_hook_active": False, "cwd": self.root})
        clean = subprocess.run(["sh", "-c", command], input=payload, capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        path = os.path.join(self.root, "gates", "lib", "manifest.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        support.write(self.root, "gates/lib/manifest.py",
                      text.replace('    ref, text = reference(tree)\n', '    return []\n    ref, text = reference(tree)\n'))
        support.write(self.root, "gates/roles.json.bak", "x\n")
        tampered = subprocess.run(["sh", "-c", command], input=payload, capture_output=True, text=True, env=env,
                                  cwd=self.root)
        self.assertEqual(tampered.returncode, 2)
        self.assertIn("gates/lib/manifest.py differs", tampered.stderr)
        again = subprocess.run(["sh", "-c", command], input=json.dumps({"stop_hook_active": True, "cwd": self.root}),
                               capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(again.returncode, 0)
        self.assertIn("systemMessage", again.stdout)

    def test_gates_env_in_local_settings_is_red(self) -> None:
        support.write(self.root, ".claude/settings.local.json", json.dumps({"env": {"GATES_" + "OFFLINE": "1"}}))
        stop = support.gate(self.root, ["hook", "stop"], {"stop_hook_active": False, "cwd": self.root})
        self.assertEqual(stop.returncode, 2)
        self.assertIn("gates never run offline", stop.stderr)

    def test_missing_baseline_is_red(self) -> None:
        root = support.make_tree({CORE: "VALUE = 1\n"}, baseline=False)
        try:
            result = support.gate(root, ["hook", "stop"], {"stop_hook_active": False, "cwd": root})
            self.assertEqual(result.returncode, 2)
            self.assertIn("BASELINE MISSING", result.stderr)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_local_settings_that_disable_hooks_are_blocked(self) -> None:
        support.gate(self.root, ["hook", "session-start"], {"source": "startup", "cwd": self.root})
        support.write(self.root, ".claude/settings.local.json", json.dumps({"disableAllHooks": True}))
        payload = {"source": "local_settings", "file_path": os.path.join(self.root, ".claude/settings.local.json"),
                   "cwd": self.root}
        self.assertEqual(support.gate(self.root, ["hook", "config-change"], payload).returncode, 2)
        stop = support.gate(self.root, ["hook", "stop"], {"stop_hook_active": False, "cwd": self.root})
        self.assertEqual(stop.returncode, 2)

    def test_allow_rules_added_by_the_client_pass(self) -> None:
        support.write(self.root, ".claude/settings.local.json", json.dumps({"permissions": {"allow": []}}))
        support.gate(self.root, ["hook", "session-start"], {"source": "startup", "cwd": self.root})
        support.write(self.root, ".claude/settings.local.json", json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
        payload = {"source": "local_settings", "file_path": os.path.join(self.root, ".claude/settings.local.json"),
                   "cwd": self.root}
        self.assertEqual(support.gate(self.root, ["hook", "config-change"], payload).returncode, 0)

    def test_pre_write_blocks_control_paths_and_secret_literals(self) -> None:
        control = {"tool_input": {"file_path": os.path.join(self.root, "gates", "roles.json"), "content": "{}"},
                   "cwd": self.root}
        self.assertEqual(support.gate(self.root, ["hook", "pre-write"], control).returncode, 2)
        literal = "API_" + "TOKEN = '" + "x" * 24 + "'"
        secret = {"tool_input": {"file_path": os.path.join(self.root, CORE), "content": literal}, "cwd": self.root}
        result = support.gate(self.root, ["hook", "pre-write"], secret)
        self.assertEqual(result.returncode, 2)
        self.assertIn("WRITE-SECRET-LITERAL", result.stderr)
        plain = {"tool_input": {"file_path": os.path.join(self.root, CORE), "content": "VALUE = 1\n"}, "cwd": self.root}
        self.assertEqual(support.gate(self.root, ["hook", "pre-write"], plain).returncode, 0)

    def test_unreadable_payload_blocks(self) -> None:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.root)
        proc = subprocess.run([__import__("sys").executable, "-I", os.path.join(self.root, "gates", "gate.py"), "hook",
                               "pre-bash"], input="not json", capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual(proc.returncode, 2)

    def test_wrappers_fail_closed_without_gate_py(self) -> None:
        with open(os.path.join(self.root, ".claude", "settings.json"), encoding="utf-8") as handle:
            settings = json.load(handle)
        empty = support.make_tree()
        shutil.rmtree(os.path.join(empty, "gates"))
        try:
            for event in ("PreToolUse", "Stop", "SubagentStop", "ConfigChange"):
                for group in settings["hooks"][event]:
                    for hook in group["hooks"]:
                        if "flowkit" in hook["command"]:
                            continue
                        proc = subprocess.run(["sh", "-c", hook["command"]], input="{}", capture_output=True,
                                              text=True, env=dict(os.environ, CLAUDE_PROJECT_DIR=empty))
                        self.assertEqual(proc.returncode, 2, f"{event} wrapper is not fail-closed")
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_settings_hold_no_write_path_rule_and_no_absolute_path(self) -> None:
        with open(os.path.join(self.root, ".claude", "settings.json"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn('"Write(', text)
        self.assertNotRegex(text, r"/(Users|home)/")


class HookProtocol(unittest.TestCase):
    """Recorded payloads of every event used: a clean tree answers each with the expected exit code."""

    def test_recorded_payloads(self) -> None:
        root = support.make_tree({CORE: "value\n"})
        try:
            folder = os.path.join(support.SOURCE, "gates", "tests", "payloads")
            for name in sorted(os.listdir(folder)):
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    case = json.loads(handle.read().replace("$ROOT", root))
                result = support.gate(root, ["hook", case["event"]], case["payload"])
                self.assertEqual(result.returncode, case["expect_exit"], f"{name}: {result.stderr}")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class FailClosedTools(unittest.TestCase):
    """A broken rule file or a missing ast-grep is red, never a silent pass."""

    def rule_file(self, root: str) -> str:
        with open(os.path.join(root, "gates", "catalog.json"), encoding="utf-8") as handle:
            entry = next((e for e in json.load(handle) if e["carrier"] == "ast-grep"), None)
        if entry is None:
            self.skipTest("no ast-grep rule in this catalog")
        sys.path.insert(0, os.path.join(root, "gates"))
        from lib import roles, selftest  # noqa: E402
        ext = {"python": "py", "typescript": "ts", "kotlin": "kt", "html": "html"}
        cfg = roles.load(root)
        rel = selftest.synth_path(cfg, entry, ext[cfg["components"][entry["component"]]["lang"]])
        support.write(root, rel, "\n")
        return rel

    def test_broken_rule_yaml_blocks(self) -> None:
        root = support.make_tree()
        try:
            rel = self.rule_file(root)
            lang_dir = sorted(os.listdir(os.path.join(root, "gates", "rules")))[0]
            support.write(root, f"gates/rules/{lang_dir}/BROKEN.yml", "id: BROKEN\nlanguage: python\nrule:\n  kindx: x\n")
            payload = {"tool_input": {"file_path": os.path.join(root, rel)}, "cwd": root}
            result = support.gate(root, ["hook", "post-edit"], payload)
            self.assertEqual(result.returncode, 2)
            self.assertIn("GATES-INFRA", result.stderr)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_ast_grep_blocks(self) -> None:
        root = support.make_tree()
        try:
            rel = self.rule_file(root)
            payload = {"tool_input": {"file_path": os.path.join(root, rel)}, "cwd": root}
            result = support.gate(root, ["hook", "post-edit"], payload, env={"PATH": "/usr/bin:/bin", "GATES_OFFLINE": ""})
            self.assertEqual(result.returncode, 2)
            self.assertIn("GATES-INFRA", result.stderr)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class RoleCoverage(unittest.TestCase):
    """D1: a source file under a component without a role is a finding."""

    def test_unmapped_source_file_is_reported(self) -> None:
        root = support.make_tree({CORE: "VALUE = 1\n"})
        try:
            with open(os.path.join(root, "gates", "roles.json"), encoding="utf-8") as handle:
                cfg = json.load(handle)
            first = cfg["components"][sorted(cfg["components"])[0]]
            stray = os.path.normpath(os.path.join(first.get("dir", "."), "stray-dir", "stray.py"))
            support.write(root, stray, "x\n")
            support.gate(root, ["drift"])
            with open(os.path.join(root, ".git", "gates", "logs", "drift.log"), encoding="utf-8") as handle:
                self.assertIn(f"{stray}:1 [GATES-ROLES]", handle.read())
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ScopeAndAnchor(unittest.TestCase):
    """Pushed commits, deletions, a missing snapshot and the local anchor never empty the stop scope."""

    def setUp(self) -> None:
        self.root = support.make_tree({CORE: "VALUE = 1\n"})
        self.remote = tempfile.mkdtemp(prefix="gates-remote-")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.remote, ignore_errors=True)

    def push_base(self) -> None:
        support.git(self.remote, "init", "-q", "--bare")
        support.git(self.root, "remote", "add", "origin", self.remote)
        support.git(self.root, "push", "-q", "origin", "HEAD:refs/heads/main")
        support.git(self.root, "fetch", "-q", "origin")

    def stop(self, active: bool = False) -> subprocess.CompletedProcess:
        return support.gate(self.root, ["hook", "stop"], {"stop_hook_active": active, "cwd": self.root})

    def test_pushed_feature_branch_stays_in_scope(self) -> None:
        self.push_base()
        support.git(self.root, "checkout", "-q", "-b", "feature")
        support.write(self.root, "RED", "red\n")
        support.git(self.root, "add", "-A")
        support.git(self.root, *support.GIT_ID, "commit", "-q", "-m", "red")
        support.git(self.root, "push", "-q", "-u", "origin", "feature")
        result = self.stop()
        self.assertEqual(result.returncode, 2, "a pushed red commit must stay red at stop")
        self.assertIn("STUB-RED", result.stderr)

    def test_deleting_a_control_file_is_red(self) -> None:
        self.push_base()
        support.git(self.root, "rm", "-q", "gates/roles.json")
        result = self.stop()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("GATES-CONTROLS", result.stderr)

    def test_deletion_only_change_runs_the_checks(self) -> None:
        self.push_base()
        support.write(self.root, "RED", "red\n")
        support.git(self.root, "add", "-A")
        support.git(self.root, *support.GIT_ID, "commit", "-q", "-m", "red")
        support.git(self.root, "push", "-q", "origin", "HEAD:refs/heads/main")
        support.git(self.root, "fetch", "-q", "origin")
        support.git(self.root, "rm", "-q", CORE)
        result = self.stop()
        self.assertEqual(result.returncode, 2, "a change that only deletes must still run the checks")

    def test_subagent_without_snapshot_is_gated_like_stop(self) -> None:
        support.write(self.root, "RED", "red\n")
        payload = {"agent_id": "never-started", "agent_type": "general-purpose", "cwd": self.root,
                   "stop_hook_active": False}
        self.assertEqual(support.gate(self.root, ["hook", "subagent-stop"], payload).returncode, 2)

    def test_local_anchor_survives_a_rebaselined_commit(self) -> None:
        self.assertEqual(support.gate(self.root, ["anchor"]).returncode, 0)
        with open(os.path.join(self.root, "gates", "roles.json"), "a", encoding="utf-8") as handle:
            handle.write("\n")
        support.gate(self.root, ["baseline"])
        support.git(self.root, "add", "-A")
        support.git(self.root, *support.GIT_ID, "commit", "-q", "-m", "weaken")
        result = self.stop()
        self.assertEqual(result.returncode, 2, "a commit must not move the reference without the operator")
        self.assertIn("refs/gates/baseline", result.stderr)
        start = support.gate(self.root, ["hook", "session-start"], {"source": "startup", "cwd": self.root})
        self.assertIn("SELF-PROTECTION UNANCHORED", start.stdout)


class ToolchainFingerprint(unittest.TestCase):
    """A changed version file invalidates the cached verdict; only green verdicts are reused."""

    def test_version_file_changes_the_fingerprint(self) -> None:
        root = support.make_tree({CORE: "VALUE = 1\n"})
        try:
            from lib import stopgate
            with open(os.path.join(root, "gates", "roles.json"), encoding="utf-8") as handle:
                comp = sorted(json.load(handle)["components"])[0]
            before = stopgate._fingerprint(root, comp, [CORE])
            support.write(root, ".node-version", "24.19.0\n")
            self.assertNotEqual(before, stopgate._fingerprint(root, comp, [CORE]))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class WrapperFingerprint(unittest.TestCase):
    """The Stop wrapper releases only an unchanged tree; a crashing gate.py blocks every blocking event."""

    def setUp(self) -> None:
        self.root = support.make_tree({CORE: "VALUE = 1\n"})
        with open(os.path.join(self.root, ".claude", "settings.json"), encoding="utf-8") as handle:
            self.hooks = json.load(handle)["hooks"]
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=self.root)
        self.env.pop("GATES_NESTED", None)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def run_hook(self, event: str, payload: dict, index: int = 0) -> subprocess.CompletedProcess:
        command = self.hooks[event][index]["hooks"][0]["command"]
        return subprocess.run(["sh", "-c", command], input=json.dumps(payload), capture_output=True, text=True,
                              env=self.env, cwd=self.root)

    def test_changed_tree_after_tampering_blocks_again(self) -> None:
        path = os.path.join(self.root, "gates", "lib", "findings.py")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n")
        payload = {"stop_hook_active": False, "cwd": self.root}
        self.assertEqual(self.run_hook("Stop", payload).returncode, 2)
        support.write(self.root, CORE, "VALUE = 2\n")
        active = dict(payload, stop_hook_active=True)
        self.assertEqual(self.run_hook("Stop", active).returncode, 2, "a changed tree is no free pass")
        released = self.run_hook("Stop", active)
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertIn("systemMessage", released.stdout)

    def test_crashing_gate_blocks_pre_tool_use(self) -> None:
        path = os.path.join(self.root, "gates", "lib", "catalog.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        support.write(self.root, "gates/lib/catalog.py", "raise ImportError('broken')\n" + text)
        bash = {"tool_input": {"command": "ls"}, "cwd": self.root}
        write = {"tool_input": {"file_path": os.path.join(self.root, CORE), "content": "x"}, "cwd": self.root}
        self.assertEqual(self.run_hook("PreToolUse", bash, 0).returncode, 2)
        self.assertEqual(self.run_hook("PreToolUse", write, 1).returncode, 2)


class BashScripts(unittest.TestCase):
    """Scripts and heredocs that write control paths are blocked; restoring from HEAD is not."""

    def setUp(self) -> None:
        self.root = support.make_tree({CORE: "VALUE = 1\n"})

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def bash(self, command: str) -> int:
        return support.gate(self.root, ["hook", "pre-bash"], {"tool_input": {"command": command}, "cwd": self.root}).returncode

    def test_interpreter_heredoc_and_script(self) -> None:
        body = "open('gates/roles.json', 'w').write('{}')"
        self.assertEqual(self.bash("python3 - <<'EOF'\n" + body + "\nEOF"), 2)
        support.write(self.root, "tool.py", body + "\n")
        self.assertEqual(self.bash("python3 tool.py"), 2)
        self.assertEqual(self.bash("cat > notes.txt <<'EOF'\nsee gates/roles.json\nEOF"), 0)
        self.assertEqual(self.bash("cat > /tmp/n <<EOF\nx\nEOF\ngit push --force origin feature"), 2)

    def test_patch_on_a_control_path(self) -> None:
        support.write(self.root, "p.patch", "--- a/gates/roles.json\n+++ b/gates/roles.json\n@@ -1 +1 @@\n-x\n+y\n")
        self.assertEqual(self.bash("git apply p.patch"), 2)


if __name__ == "__main__":
    unittest.main()
