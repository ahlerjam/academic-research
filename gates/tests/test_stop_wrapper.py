"""The Stop wrappers release the second stop when the project directory vanished; everything else stays fail-closed."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import support  # noqa: E402

from lib import sync  # noqa: E402


def run(command: str, project_dir: str, active: bool, cwd: str) -> subprocess.CompletedProcess:
    """Run one rendered wrapper with a stop payload and the given CLAUDE_PROJECT_DIR."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
    env.pop("GATES_NESTED", None)
    payload = json.dumps({"stop_hook_active": active, "cwd": cwd})
    return subprocess.run(["sh", "-c", command], input=payload, capture_output=True, text=True, env=env, cwd=cwd)


class VanishedProjectDir(unittest.TestCase):
    """Operator patch item 25: a renamed or deleted repository directory must not trap the session in its stop hook."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="gates-gone-")
        self.gone = os.path.join(self.tmp, "renamed-away")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_stop_is_released(self) -> None:
        for event in ("stop", "subagent-stop"):
            with self.subTest(event=event):
                released = run(sync.verified(event, "main"), self.gone, True, self.tmp)
                self.assertEqual(released.returncode, 0, released.stderr)
                self.assertIn("no longer exists", json.loads(released.stdout)["systemMessage"])

    def test_first_stop_still_blocks(self) -> None:
        for event in ("stop", "subagent-stop"):
            with self.subTest(event=event):
                first = run(sync.verified(event, "main"), self.gone, False, self.tmp)
                self.assertEqual(first.returncode, 2)
                self.assertIn("blocked as a precaution", first.stderr)

    def test_existing_dir_without_gate_code_stays_blocked(self) -> None:
        present = os.path.join(self.tmp, "present")
        os.makedirs(present)
        for event in ("stop", "subagent-stop"):
            with self.subTest(event=event):
                self.assertEqual(run(sync.verified(event, "main"), present, True, self.tmp).returncode, 2)

    def test_empty_project_dir_stays_blocked(self) -> None:
        self.assertEqual(run(sync.verified("stop", "main"), "", True, self.tmp).returncode, 2)

    def test_config_change_never_releases(self) -> None:
        self.assertEqual(run(sync.verified("config-change", "main"), self.gone, True, self.tmp).returncode, 2)

    def test_rendered_settings_carry_the_release(self) -> None:
        root = support.make_tree()
        try:
            hooks = json.loads(sync.settings(root))["hooks"]
            for event in ("Stop", "SubagentStop"):
                with self.subTest(event=event):
                    command = hooks[event][0]["hooks"][0]["command"]
                    self.assertEqual(run(command, self.gone, True, self.tmp).returncode, 0)
            self.assertNotIn("no longer exists", hooks["ConfigChange"][0]["hooks"][0]["command"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ExtraSettings(unittest.TestCase):
    """Operator patch item 24: cloud sessions get their env and attribution from the committed settings."""

    def test_project_extra_settings_render_and_keep_the_deny_list(self) -> None:
        root = support.make_tree()
        try:
            path = os.path.join(root, "gates", "project.json")
            with open(path, encoding="utf-8") as handle:
                project = json.load(handle)
            project["extra_settings"] = {"env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"},
                                         "attribution": {"commit": "", "pr": "", "sessionUrl": False}}
            support.write(root, "gates/project.json", json.dumps(project, indent=1) + "\n")
            data = json.loads(sync.settings(root))
            self.assertEqual(data["env"], {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"})
            self.assertEqual(data["attribution"]["sessionUrl"], False)
            self.assertEqual(data["permissions"]["deny"], sync.deny_rules(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_committed_project_sets_the_cloud_env_without_permissions(self) -> None:
        tree = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(tree, "gates", "project.json"), encoding="utf-8") as handle:
            extra = json.load(handle)["extra_settings"]
        self.assertNotIn("permissions", extra)
        self.assertNotIn("hooks", extra)
        self.assertEqual(extra["env"]["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"], "1")
        self.assertEqual(extra["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "sonnet")
        self.assertFalse(any(key.startswith("GATES_") for key in extra["env"]))


if __name__ == "__main__":
    unittest.main()
