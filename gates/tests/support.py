"""Temporary git trees with the real gates and a stub Makefile, shared by the gate tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, Optional

SOURCE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STUB_MAKEFILE = (
    "check-%:\n"
    "\t@echo run >> .git/count-$*\n"
    "\t@if [ \"$*\" = repo ] && [ -f RED ]; then echo 'probe/data.txt:1 [STUB-RED] stub finding'; exit 1; fi\n"
)
GIT_ID = ["-c", "user.name=gates-test", "-c", "user.email=gates-test@example.invalid"]


def make_tree(extra: Optional[Dict[str, str]] = None, baseline: bool = True) -> str:
    """Create a git tree with gates/, CLAUDE settings, a stub Makefile and a committed baseline."""
    root = tempfile.mkdtemp(prefix="gates-test-")
    shutil.copytree(os.path.join(SOURCE, "gates"), os.path.join(root, "gates"),
                    ignore=shutil.ignore_patterns("__pycache__", "controls.sha256"))
    for rel in ("AGENTS.md", ".gitignore", ".claude/settings.json"):
        src = os.path.join(SOURCE, rel)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
            shutil.copy2(src, os.path.join(root, rel))
    write(root, "Makefile", STUB_MAKEFILE)
    with open(os.path.join(root, "gates", "roles.json"), encoding="utf-8") as handle:
        cfg = json.load(handle)
    first = sorted(cfg["components"])[0]
    write(root, os.path.join(cfg["components"][first].get("dir", "."), "README.txt"), "component\n")
    for rel, text in (extra or {}).items():
        write(root, rel, text)
    git(root, "init", "-q")
    if baseline:
        gate(root, ["baseline"])
    git(root, "add", "-A")
    git(root, *GIT_ID, "commit", "-q", "-m", "init")
    return root


def write(root: str, rel: str, text: str) -> None:
    """Write a file below root."""
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def git(root: str, *args: str) -> subprocess.CompletedProcess:
    """Run git in root."""
    return subprocess.run(["git"] + list(args), cwd=root, capture_output=True, text=True, check=True)


def gate(root: str, args: list, payload: Optional[dict] = None, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run root's gate.py with an optional JSON payload on stdin."""
    full_env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    full_env.pop("GATES_NESTED", None)
    full_env.update(env or {})
    return subprocess.run([sys.executable, "-I", os.path.join(root, "gates", "gate.py")] + args, cwd=root,
                          input=json.dumps(payload) if payload is not None else None, capture_output=True,
                          text=True, env=full_env, timeout=300)


def count(root: str, component: str) -> int:
    """Return how often the stub ran check-<component>."""
    path = os.path.join(root, ".git", f"count-{component}")
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as handle:
        return len(handle.read().splitlines())


def state(root: str) -> dict:
    """Return the gate state of root."""
    with open(os.path.join(root, ".git", "gates", "state.json"), encoding="utf-8") as handle:
        return json.load(handle)
