"""Manifest of control files: hashes plus the structure of .claude/settings.json."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

from . import gitx, state
from .findings import Finding

MANIFEST = "gates/controls.sha256"
SETTINGS = ".claude/settings.json"
LOCAL = ".claude/settings.local.json"
LOCAL_FORBIDDEN = ("disableAllHooks", "hooks", "allowManagedHooksOnly")
GATE_ENV_PREFIX = "GATES_"


def gate_env(data: dict) -> List[str]:
    """Return GATES_* variables a settings object sets through its env block."""
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    return sorted(k for k in env if k.startswith(GATE_ENV_PREFIX))


def controls(tree: str) -> dict:
    """Load gates/controls.json."""
    with open(os.path.join(tree, "gates", "controls.json"), encoding="utf-8") as handle:
        return json.load(handle)


def control_files(tree: str) -> List[str]:
    """Return every file covered by operator_only, minus ratchet paths, the manifest and local settings."""
    cfg = controls(tree)
    ratchet = set(gitx.ls(tree, cfg.get("ratchet", [])))
    return [rel for rel in gitx.ls(tree, cfg["operator_only"])
            if rel not in ratchet and rel not in (MANIFEST, LOCAL)]


def settings_structure(text: str) -> Dict[str, str]:
    """Return hook count, deny count and the multiset of hook commands of a settings file."""
    try:
        data = json.loads(text)
    except ValueError:
        return {"settings": "unparsable"}
    commands = sorted(h.get("command", "") for groups in data.get("hooks", {}).values()
                      for group in groups for h in group.get("hooks", []))
    return {"hooks": str(len(commands)), "deny": str(len(data.get("permissions", {}).get("deny", []))),
            "commands": hashlib.sha256("\n".join(commands).encode()).hexdigest(),
            "gate_env": ",".join(gate_env(data)) or "-"}


def render(tree: str) -> str:
    """Render the manifest text for the current tree."""
    lines = [f"{h}  {rel}" for rel, h in sorted(state.file_hashes(tree, control_files(tree)).items())]
    settings = os.path.join(tree, SETTINGS)
    if os.path.isfile(settings):
        with open(settings, encoding="utf-8") as handle:
            lines += [f"#settings {k}={v}" for k, v in sorted(settings_structure(handle.read()).items())]
    return "\n".join(lines) + "\n"


def parse(text: str) -> Dict[str, str]:
    """Parse a manifest into {key: value}."""
    out = {}
    for line in text.splitlines():
        if line.startswith("#settings "):
            key, _, value = line[len("#settings "):].partition("=")
            out["settings:" + key] = value
        elif "  " in line:
            value, _, rel = line.partition("  ")
            out[rel] = value
    return out


def reference(tree: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (ref name, manifest text) from origin's default branch, else the local anchor, else HEAD."""
    for ref in (gitx.default_ref(tree), gitx.anchor(tree), "HEAD" if gitx.head(tree) else None):
        if ref:
            text = gitx.show(tree, ref, MANIFEST)
            if text is not None:
                return ref, text
    return None, None


def anchoring(tree: str) -> str:
    """Return 'remote', 'anchor' or 'head': how far the self-protection reference reaches."""
    if gitx.default_ref(tree):
        return "remote"
    return "anchor" if gitx.anchor(tree) else "head"


def local_findings(tree: str) -> List[Finding]:
    """Flag keys in settings.local.json that switch hooks off or replace them."""
    path = os.path.join(tree, LOCAL)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError:
        return [Finding(LOCAL, 1, "GATES-CONTROLS", "settings.local.json is not valid JSON")]
    found = [Finding(LOCAL, 1, "GATES-CONTROLS", f"settings.local.json sets '{key}'; only the operator may")
             for key in LOCAL_FORBIDDEN if key in data and data[key] not in (False, None)]
    sandbox = data.get("sandbox") if isinstance(data.get("sandbox"), dict) else {}
    if sandbox.get("enabled") is False or sandbox.get("excludedCommands") or sandbox.get("allowUnsandboxedCommands"):
        found.append(Finding(LOCAL, 1, "GATES-CONTROLS", "settings.local.json loosens the sandbox; only the operator may"))
    return found + [Finding(LOCAL, 1, "GATES-CONTROLS", f"settings.local.json sets env {name}; gates never run offline")
                    for name in gate_env(data)]


def violations(tree: str) -> List[Finding]:
    """Compare the tree with the baseline manifest; a missing baseline is red."""
    ref, text = reference(tree)
    if text is None:
        return [Finding(MANIFEST, 1, "GATES-BASELINE",
                        "BASELINE MISSING: the operator runs `make controls-baseline` and commits it")]
    want, have = parse(text), parse(render(tree))
    found = [Finding(rel if not rel.startswith("settings:") else SETTINGS, 1, "GATES-CONTROLS",
                     f"control differs from {ref} ({'missing' if rel not in have else 'changed'})")
             for rel in sorted(want) if have.get(rel) != want[rel]]
    found += [Finding(rel, 1, "GATES-CONTROLS", f"new control file not in the {ref} manifest")
              for rel in sorted(set(have) - set(want)) if not rel.startswith("settings:")]
    return found + local_findings(tree)
