"""make doctor and make gates-bench: is the setup complete and are the S0 commands fast enough."""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import sys
import time
from typing import List

from . import agents_md, catalog, drift, engine, gitx, manifest, roles

BLOCKING = ("PreToolUse", "Stop", "SubagentStop", "ConfigChange")
MIN_TIMEOUT = 30
S0_LIMIT = 1.0
S1_LIMIT = 5.0


def doctor(tree: str) -> int:
    """Print one line per check and return 1 when any check fails."""
    problems: List[str] = []
    path = os.path.join(tree, ".claude", "settings.json")
    if not os.path.isfile(path):
        problems.append(".claude/settings.json missing")
    else:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        for event, groups in data.get("hooks", {}).items():
            for group in groups:
                for hook in group.get("hooks", []):
                    command = hook.get("command", "")
                    if re.search(r"(^|[\s\"'])/(Users|home)/", command):
                        problems.append(f"{event}: absolute path in hook command")
                    if event in BLOCKING and ("exit 2" not in command or "rc=$?" not in command):
                        problems.append(f"{event}: blocking hook without fail-closed wrapper (missing tool and crash)")
                    if event in BLOCKING and hook.get("timeout", 600) < MIN_TIMEOUT:
                        problems.append(f"{event}: timeout {hook.get('timeout')} s; a timed-out hook does not block")
        if any(rule.startswith("Write(") for rule in data.get("permissions", {}).get("deny", [])):
            problems.append("permissions.deny holds a Write(...) path rule; it is never consulted")
    if sys.version_info < (3, 9):
        problems.append(f"python3 {sys.version.split()[0]} is older than 3.9")
    with open(os.path.join(tree, "AGENTS.md"), encoding="utf-8") as handle:
        lines = len(handle.read().splitlines())
    if lines > agents_md.MAX_LINES:
        problems.append(f"AGENTS.md has {lines} lines")
    problems += [f"{f.path}: {f.what}" for f in manifest.violations(tree)]
    problems += _node_version(tree)
    print(f"doctor: self-protection reference = {manifest.anchoring(tree)} (only 'remote' is effective)")
    problems += [f"{f.what}" for f in drift.d8(tree)]
    if not os.path.isfile(os.path.join(gitx.state_dir(tree), "setup.json")):
        problems.append("make setup has not run in this worktree")
    for problem in problems:
        print(f"doctor: FAIL {problem}")
    print(f"RESULT: {'FAIL' if problems else 'PASS'} doctor ({len(problems)} problems)")
    return 1 if problems else 0


def _node_version(tree: str) -> List[str]:
    """Compare the local node with every .node-version in the tree."""
    wanted = {open(os.path.join(tree, rel), encoding="utf-8").read().strip().lstrip("v")
              for rel in gitx.ls(tree, ["**/.node-version", ".node-version"])}
    if not wanted:
        return []
    proc = gitx.run(["node", "-v"], cwd=tree) if shutil.which("node") else None
    have = proc.stdout.strip().lstrip("v") if proc is not None and proc.returncode == 0 else "missing"
    return [f"node {have} differs from .node-version {w}; the operator installs it (for example "
            f"`asdf install nodejs {w} && asdf set nodejs {w}`)" for w in sorted(wanted) if w != have]


def bench(tree: str, runs: int = 5) -> int:
    """Time each S0 dispatch entry on one example file; recommend moving slow ones to S1 or S2."""
    with open(os.path.join(tree, "gates", "dispatch.json"), encoding="utf-8") as handle:
        entries = json.load(handle)["entries"]
    cfg = roles.load(tree)
    cat = catalog.load(tree)
    report = []
    for entry in (e for e in entries if e.get("tier") == "s0"):
        files = [f for f in gitx.ls(tree, entry["glob"].split("|")) if not f.startswith("gates/fixtures/")]
        if not files:
            continue
        engine.run_tier(tree, files[0], "s0", cfg, cat, do_format=False)
        times = []
        for _ in range(runs):
            start = time.time()
            engine.run_tier(tree, files[0], "s0", cfg, cat, do_format=False)
            times.append(time.time() - start)
        times.sort()
        p95 = times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))]
        move = "s2" if p95 > S1_LIMIT else "s1" if p95 > S0_LIMIT else "s0"
        report.append({"glob": entry["glob"], "example": files[0], "p50": round(statistics.median(times), 3),
                       "p95": round(p95, 3), "recommended_tier": move})
        print(f"bench: {entry['glob']:<40} p50={report[-1]['p50']:.3f}s p95={p95:.3f}s -> {move}")
    with open(os.path.join(gitx.state_dir(tree), "bench.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1)
    print(f"RESULT: PASS gates-bench ({len(report)} entries, see .git/gates/bench.json)")
    return 0
