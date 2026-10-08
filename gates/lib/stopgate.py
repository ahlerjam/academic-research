"""Stop and SubagentStop gate: honest blocking with a change fingerprint, cache and single flight."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

from . import gitx, manifest, roles, state

HARD_EDGE = 150.0
WAIT_FOR_PEER = 120.0
LOCATION = re.compile(r"(^\S+:\d+|\[[A-Z][A-Z0-9-]+\]|^FAILED |^ERROR[: ]|error[:\s]|\S+ -> \S+ \(l\.\d+\)|is not allowed to import)")
PYRIGHT = re.compile(r"^(?P<path>\S+):(?P<line>\d+):\d+ - error: (?P<what>.*?)(?: \((?P<code>report\w+)\))?$")
NOISE = re.compile(r"^(RESULT: PASS |All checks passed|\d+ files? already formatted)")
FIX_HINT = "Run `make fix` for formatting findings."
SKIP_AGENTS = ("Explore", "Plan")
REPO = "repo"


def _scope_stop(tree: str) -> List[str]:
    """Files changed, added or deleted since the merge base with the base ref, plus untracked files."""
    return gitx.changed_since_base(tree, deleted=True)


def _scope_subagent(tree: str, agent_id: str) -> List[str]:
    """Files whose hash changed since this agent started (commits and deletions included)."""
    path = os.path.join(gitx.state_dir(tree), "agents", f"{agent_id}.json")
    if not os.path.isfile(path):
        return _scope_stop(tree)
    with open(path, encoding="utf-8") as handle:
        snap = json.load(handle)
    before: Dict[str, str] = snap.get("hashes", {})
    now = state.file_hashes(tree, gitx.dirty(tree, deleted=True))
    changed = {rel for rel, h in now.items() if before.get(rel) != h}
    changed |= {rel for rel in before if rel not in now}
    head = gitx.head(tree)
    if snap.get("head") and head and head != snap["head"]:
        changed |= set(gitx.files_between(tree, snap["head"], head, deleted=True))
    return sorted(changed)


def components_for(tree: str, files: List[str]) -> Dict[str, List[str]]:
    """Group scope files by component (role index first, then component directory); every scope adds 'repo'."""
    cfg = roles.load(tree)
    idx = roles.index(tree, cfg)
    dirs = {c: roles.component_dir(cfg, c) for c in cfg["components"]}
    out: Dict[str, List[str]] = {}
    for rel in files:
        if rel in idx:
            out.setdefault(idx[rel].component, []).append(rel)
            continue
        for comp, base in dirs.items():
            if base not in (".", "") and rel.startswith(base.rstrip("/") + "/"):
                out.setdefault(comp, []).append(rel)
    if files:
        out[REPO] = list(files)
    return out


TOOLCHAIN_FILES = [".node-version", ".python-version", ".tool-versions", ".nvmrc", ".java-version"]
TOOLCHAIN_PROBES = {"python": [["uv", "--version"]], "sql": [["uv", "--version"]], "typescript": [["node", "-v"]],
                    "css": [["node", "-v"]], "kotlin": [["java", "-version"]]}


def _toolchain(tree: str, cwd: str, lang: str) -> str:
    """Return the versions the component's tools report, so a toolchain change invalidates a cached verdict."""
    out = []
    for argv in TOOLCHAIN_PROBES.get(lang, []):
        if shutil.which(argv[0]) is None:
            out.append(f"{argv[0]}: missing")
            continue
        try:
            proc = gitx.run(argv, cwd=os.path.join(tree, cwd), timeout=20)
            out.append(f"{argv[0]}: {proc.returncode} {(proc.stdout + proc.stderr).strip()[:200]}")
        except (OSError, subprocess.TimeoutExpired):
            out.append(f"{argv[0]}: unknown")
    return "\n".join(out)


def _fingerprint(tree: str, comp: str, files: List[str]) -> str:
    """Hash touched files, the component's lockfiles, tool configs, version files and reported tool versions."""
    cfg = roles.load(tree)
    extra: List[str] = gitx.ls(tree, TOOLCHAIN_FILES)
    toolchain = ""
    if comp in cfg["components"]:
        base = roles.component_dir(cfg, comp)
        prefix = "" if base in (".", "") else base.rstrip("/") + "/"
        extra += gitx.ls(tree, [f"{prefix}{name}" for name in cfg["components"][comp].get(
            "fingerprint_files", ["*.lock", "*-lock.json", "*.toml", "*.json", "*.kts", ".importlinter"])
            + TOOLCHAIN_FILES])
        toolchain = _toolchain(tree, base or ".", cfg["components"][comp].get("lang", ""))
    extra += [r for r in manifest.control_files(tree) if r.startswith(("gates/", "mk/", "Makefile"))]
    extra += gitx.ls(tree, cfg.get("shared_fingerprint", []))
    files_fp = state.fingerprint(tree, sorted(set(files) | set(extra)))
    return hashlib.sha256((files_fp + "\n" + toolchain).encode()).hexdigest()


def _relative(tree: str, line: str) -> str:
    """Make an absolute path inside the tree repo-relative, as the message contract wants."""
    return line.replace(tree + os.sep, "") if tree else line


def normalize(tree: str, out: str) -> List[str]:
    """Translate tool output to the contract: relative paths, pyright as path:line [pyright:code] what, no noise."""
    # constraint: pyright indents its continuation lines with no-break spaces (U+00A0), not plain spaces
    lines = [_relative(tree, line) for line in out.splitlines() if not NOISE.match(line)]
    result: List[str] = []
    for index, line in enumerate(lines):
        match = PYRIGHT.match(line.strip())
        if match is None:
            result.append(line)
            continue
        tail = [t.strip() for t in lines[index + 1:index + 3] if t[:1].isspace() and t.strip()]
        code = match.group("code") or next((m.group(1) for t in tail for m in [re.search(r"\((report\w+)\)$", t)] if m), None)
        what = "; ".join([match.group("what")] + [re.sub(r" \(report\w+\)$", "", t) for t in tail])
        result.append(f"{match.group('path')}:{match.group('line')} [pyright{':' + code if code else ''}] {what}")
    return result


def _filter(tree: str, out: str) -> str:
    """Keep lines with a location or a rule id; fall back to the tail; add the fix hint for format findings."""
    lines = normalize(tree, out)
    keep = [line for line in lines if LOCATION.search(line)]
    text = "\n".join(keep[:15]) if keep else "\n".join("\n".join(lines).strip().splitlines()[-8:])
    return text + ("\n" + FIX_HINT if "[GATES-FORMAT]" in text else "")


def _make(tree: str, comp: str, env: Dict[str, str], timeout: float) -> Optional[Tuple[int, str]]:
    """Run make -s check-<comp> in its own process group; on timeout kill the whole group and return None."""
    proc = subprocess.Popen(["make", "-s", f"check-{comp}"], cwd=tree, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                break
            try:
                proc.communicate(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue
        return None


def _run_component(tree: str, comp: str, fp: str, deadline: float) -> Tuple[str, bool, str]:
    """Run make -s check-<comp> under a single-flight lock; reuse a peer's green verdict for the same fingerprint."""
    cached = state.load(tree).get("results", {}).get(comp)
    if cached and cached.get("fp") == fp and cached.get("ok"):
        return comp, True, ""
    waited_since = time.time()
    with state.lock(tree, f"check-{comp}", timeout=min(WAIT_FOR_PEER, max(1.0, deadline - time.time()))) as got:
        if not got:
            return comp, False, f"stage {comp}: another gate run holds the lock; run `make check-{comp}`"
        cached = state.load(tree).get("results", {}).get(comp)
        if cached and cached.get("fp") == fp and (cached.get("ok") or cached.get("at", 0) >= waited_since):
            return comp, bool(cached["ok"]), cached.get("out", "")
        env = {k: v for k, v in os.environ.items() if k != "GATES_OFFLINE"}
        env["GATES_NESTED"] = "1"
        remaining = deadline - time.time()
        if remaining <= 1:
            return comp, False, f"stage {comp} too slow, run `make check-{comp}`"
        result = _make(tree, comp, env, remaining)
        if result is None:
            return comp, False, f"stage {comp} too slow, run `make check-{comp}`"
        ok = result[0] == 0
        text = "" if ok else _filter(tree, result[1])
        log_dir = os.path.join(gitx.state_dir(tree), "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, f"stop-{comp}.log"), "w", encoding="utf-8") as handle:
            handle.write(result[1])
        entry = {"fp": fp, "ok": ok, "out": text, "at": time.time()}
        state.update(tree, lambda d: d.setdefault("results", {}).update({comp: entry}))
        return comp, ok, text


def evaluate(tree: str, scope: List[str], key: str, active: bool, controls_always: bool = False) -> int:
    """Apply the stop algorithm to a scope; key separates main stops from each subagent."""
    if not scope and not controls_always:
        return 0
    controls = manifest.violations(tree)
    if controls:
        return _controls_red(tree, controls, key, active)
    if not scope:
        return 0
    if shutil.which("make") is None:
        sys.stderr.write("gates: [GATES-INFRA] make not found; run `make setup`\n")
        return 2
    groups = components_for(tree, scope)
    fps = {comp: _fingerprint(tree, comp, files) for comp, files in groups.items()}
    deadline = time.time() + HARD_EDGE
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(fps))) as pool:
        results = list(pool.map(lambda c: _run_component(tree, c, fps[c], deadline), sorted(fps)))
    red = [(comp, out) for comp, ok, out in results if not ok]
    combined = hashlib.sha256(json.dumps(fps, sort_keys=True).encode()).hexdigest()
    data = state.load(tree)
    if not red:
        state.update(tree, lambda d: (d.setdefault("red_fp", {}).pop(key, None), d.pop("red_marker", None)))
        return 0
    rules = sorted({m for _, out in red for m in re.findall(r"\[([A-Z][A-Z0-9-]+)\]", out)}) or [c for c, _ in red]
    if data.get("red_fp", {}).get(key) == combined and active:
        marker = {"rules": rules, "since": time.strftime("%Y-%m-%d %H:%M:%S"), "components": [c for c, _ in red]}
        state.update(tree, lambda d: d.update(red_marker=marker))
        print(json.dumps({"systemMessage": "gates: red, agent stopped without changes; see .git/gates/state.json"}))
        return 0
    state.update(tree, lambda d: d.setdefault("red_fp", {}).update({key: combined}))
    sys.stderr.write("gates: the turn cannot end with red gates. Fix and stop again.\n")
    for comp, out in red:
        sys.stderr.write(f"== make check-{comp} (log: .git/gates/logs/stop-{comp}.log)\n{out}\n")
    return 2


def _controls_red(tree: str, controls: list, key: str, active: bool) -> int:
    """Block on control findings; release loudly when the agent stopped again without any change."""
    fp = hashlib.sha256(json.dumps(sorted(f"{f.path}|{f.rule}|{f.what}" for f in controls)).encode()
                        + state.fingerprint(tree, sorted(set(gitx.dirty(tree, deleted=True)))).encode()).hexdigest()
    marker_key = f"controls:{key}"
    if active and state.load(tree).get("red_fp", {}).get(marker_key) == fp:
        marker = {"rules": sorted({f.rule for f in controls}), "since": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "components": ["controls"]}
        state.update(tree, lambda d: d.update(red_marker=marker))
        print(json.dumps({"systemMessage": "gates: control files differ from the baseline, agent stopped without "
                                           "changes; the operator decides (see .git/gates/state.json)"}))
        return 0
    state.update(tree, lambda d: d.setdefault("red_fp", {}).update({marker_key: fp}))
    sys.stderr.write("gates: control files differ from the baseline; the turn cannot end.\n")
    sys.stderr.writelines(f"{f.path}:{f.line} [{f.rule}] {f.what}\n" for f in controls[:15])
    sys.stderr.write("Fix: restore the control files or ask the operator; deliver changes as a patch.\n")
    return 2


def on_stop(payload: dict) -> int:
    """Stop handler."""
    if os.environ.get("GATES_NESTED"):
        return 0
    from .hooks import tree_of
    tree = tree_of(payload)
    if tree is None:
        return 0
    return evaluate(tree, _scope_stop(tree), "stop", bool(payload.get("stop_hook_active")), controls_always=True)


def on_subagent_stop(payload: dict) -> int:
    """SubagentStop handler: Explore and Plan pass, every other agent is gated on its own delta."""
    if os.environ.get("GATES_NESTED") or payload.get("agent_type") in SKIP_AGENTS:
        return 0
    from .hooks import tree_of
    tree = tree_of(payload)
    agent = payload.get("agent_id")
    if tree is None:
        return 0
    scope = _scope_subagent(tree, agent) if agent else _scope_stop(tree)
    return evaluate(tree, scope, f"subagent:{agent}", bool(payload.get("stop_hook_active")))


def last_marker(tree: str) -> Optional[dict]:
    """Return the RED marker for session-start."""
    return state.load(tree).get("red_marker")
