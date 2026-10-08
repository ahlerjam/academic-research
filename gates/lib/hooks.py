"""Hook handlers: pure wiring between Claude Code events and the gate library."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Dict, List, Optional

from . import catalog, cmdnorm, engine, findings, gitx, manifest, roles, state, stopgate
from .findings import Finding

CONTEXT_LIMIT = 1500
BRIEF = ("Before you claim anything about code, configuration or tools on this machine, read, grep or run it; "
         "a claim needs file:line or command output. Look up libraries, APIs and versions in their docs, never "
         "from memory; if you cannot verify a fact, write 'Not verified'. Rules: AGENTS.md. Decisions: "
         "`make adr-find TAG=<tag> Q=<text>`, open only the hits.")
SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")


def read_payload() -> Optional[dict]:
    """Read the hook payload from stdin, None when it is not a JSON object."""
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def tree_of(payload: dict, path: Optional[str] = None) -> Optional[str]:
    """Return the work tree from a file path, the payload cwd or CLAUDE_PROJECT_DIR."""
    for candidate in (path, payload.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")):
        if candidate and os.path.exists(candidate):
            top = gitx.toplevel(candidate)
            if top:
                return top
    return None


def emit_context(event: str, text: str, limit: int = 9000) -> None:
    """Print additionalContext for an event, capped below the documented output limit."""
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text[:limit]}}))


def _controls(tree: str) -> List[str]:
    """Return operator-only globs."""
    try:
        return manifest.controls(tree)["operator_only"]
    except (OSError, ValueError, KeyError):
        return []


def glob_regex(glob: str) -> str:
    """Translate a controls glob into a heuristic regex for command and path matching."""
    out = ""
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out += r"(?:[^\s'\"]*/)?"
            i += 3
        elif glob.startswith("**", i):
            out += r"[^\s'\"]*"
            i += 2
        elif glob[i] == "*":
            out += r"[^\s'\"/]*"
            i += 1
        else:
            out += re.escape(glob[i])
            i += 1
    return out


def is_control_path(tree: str, rel: str) -> bool:
    """Return whether a repo-relative path falls under an operator-only glob."""
    rel = rel.rstrip("/")
    return any(re.fullmatch(glob_regex(g), rel) or g.startswith(rel + "/") for g in _controls(tree))


def _bash_rules(tree: str) -> dict:
    """Load gates/bash_rules.json."""
    with open(os.path.join(tree, "gates", "bash_rules.json"), encoding="utf-8") as handle:
        return json.load(handle)


def session_start(payload: dict) -> int:
    """Inject branch, tool readiness, red marker and baseline status; snapshot settings."""
    tree = tree_of(payload)
    if tree is None:
        return 0
    branch = gitx.run(["git", "branch", "--show-current"], cwd=tree).stdout.strip() or "(detached)"
    lines = [f"[gates] branch={branch} changed-files={len(gitx.dirty(tree))}"]
    if not os.path.isfile(os.path.join(gitx.state_dir(tree), "setup.json")):
        lines.append("[gates] toolchain not confirmed in this worktree; run `make setup`")
    else:
        lines.append("[gates] toolchain ready (make setup ran)")
    marker = state.load(tree).get("red_marker")
    if marker:
        lines.append(f"[gates] last stop ended RED since {marker.get('since')}: {', '.join(marker.get('rules', []))}")
    if manifest.reference(tree)[1] is None:
        lines.append("[gates] BASELINE MISSING: the operator runs `make controls-baseline` and commits it")
    reach = manifest.anchoring(tree)
    if reach != "remote":
        lines.append("[gates] SELF-PROTECTION UNANCHORED: no origin default branch; the local reference ("
                     + ("refs/gates/baseline" if reach == "anchor" else "HEAD, so a commit moves it")
                     + ") only slows an agent down; the operator pushes and sets the branch ruleset")
    lines += [f"[gates] {f.what}" for f in manifest.local_findings(tree)]
    if payload.get("source") == "compact":
        lines.append("[gates] keep after compaction: changed files, open tasks, test and build commands")
    lines.append("[gates] `make help` lists every verb; rules: AGENTS.md")
    snapshot = {}
    for rel in SETTINGS_FILES:
        path = os.path.join(tree, rel)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                snapshot[rel] = handle.read()
    state.update(tree, lambda d: d.update(settings_snapshot=snapshot))
    emit_context("SessionStart", "\n".join(lines), CONTEXT_LIMIT)
    return 0


def subagent_start(payload: dict) -> int:
    """Brief Explore and Plan; snapshot changed-file hashes for every other agent."""
    tree = tree_of(payload)
    if payload.get("agent_type") in ("Explore", "Plan"):
        emit_context("SubagentStart", BRIEF, CONTEXT_LIMIT)
        return 0
    if tree is None or not payload.get("agent_id"):
        return 0
    snap = {"head": gitx.head(tree), "hashes": state.file_hashes(tree, gitx.dirty(tree)), "at": time.time()}
    agents = os.path.join(gitx.state_dir(tree), "agents")
    os.makedirs(agents, exist_ok=True)
    with open(os.path.join(agents, f"{payload['agent_id']}.json"), "w", encoding="utf-8") as handle:
        json.dump(snap, handle)
    return 0


PUSH_VALUE_FLAGS = ("-o", "--push-option", "--repo", "--receive-pack", "--exec")


def protected_push(tree: str, segs: List[List[str]], protected: str) -> List[tuple]:
    """Return a hit for 'git push' without a refspec, or with HEAD, while the current branch is protected."""
    branch = gitx.run(["git", "branch", "--show-current"], cwd=tree).stdout.strip()
    if not branch or not re.fullmatch(f"(?:{protected})", branch):
        return []
    hits = []
    for seg in (s for s in segs if s[:2] == ["git", "push"]):
        args = seg[2:]
        positional = [a for i, a in enumerate(args) if not a.startswith("-") and (i == 0 or args[i - 1] not in PUSH_VALUE_FLAGS)]
        refspecs = positional[1:]
        if not refspecs or any(r.lstrip("+") in ("HEAD", "@") for r in refspecs):
            hits.append(("BASH-PROTECTED-PUSH", f"this pushes the current branch '{branch}', which is protected; "
                                                "push a feature branch and open a pull request"))
    return hits


WRITE_HINT = re.compile(r"open\([^)]*['\"][wax+]|write|unlink|remove|rename|replace|rmtree|truncate|>|\btee\b|\brm\b|\bmv\b|\bcp\b|\bsed\b")
SCRIPT_LIMIT = 262144


def _rel(tree: str, cwd: str, target: str) -> Optional[str]:
    """Return a target path relative to the tree, or None outside it."""
    path = os.path.relpath(os.path.realpath(os.path.join(cwd, target)), tree)
    path = os.path.normpath(path) if path not in ("", ".") else path
    return None if not path or path.startswith("..") else path


def _names_control_path(tree: str, text: str) -> bool:
    """Return whether a script text names an operator-only path and looks like it writes."""
    return bool(WRITE_HINT.search(text)) and any(
        re.search(r"(?:^|[\s'\"/=(,])" + glob_regex(g) + r"(?:$|[\s'\",)])", text) for g in _controls(tree))


def _read_small(path: str) -> str:
    """Read a file up to the script limit, empty when unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(SCRIPT_LIMIT)
    except OSError:
        return ""


def _patch_targets(text: str) -> List[str]:
    """Return the paths a unified diff touches."""
    return [m.group(2) for m in re.finditer(r"^(\+\+\+|---) (?:[ab]/)?(\S+)", text, re.MULTILINE) if m.group(2) != "/dev/null"]


def pre_bash(payload: dict) -> int:
    """Block dangerous commands and writes to control paths (heuristic, behind permissions.deny and the stop gate)."""
    tree = tree_of(payload)
    command = (payload.get("tool_input") or {}).get("command", "")
    if not command or tree is None:
        return 0
    rules = _bash_rules(tree)
    hits = cmdnorm.match(command, rules["rules"])
    segs = cmdnorm.segments(command)
    cwd = os.path.realpath(payload.get("cwd") or tree)
    cwd = cwd if (cwd + os.sep).startswith(tree + os.sep) else tree
    for seg in segs or []:
        if seg and seg[0] == "cd":
            cwd = os.path.realpath(os.path.join(cwd, seg[1])) if len(seg) > 1 else tree
            continue
        targets = cmdnorm.write_targets(seg)
        for patch in cmdnorm.patch_inputs(seg):
            targets += _patch_targets(_read_small(os.path.join(cwd, patch)))
        for target in targets:
            path = _rel(tree, cwd, target)
            if path and is_control_path(tree, path):
                hits.append(("BASH-CONTROL-WRITE", f"writes to operator-only {path}; deliver a patch in your report instead"))
        for script in cmdnorm.script_inputs(seg):
            own = _rel(tree, cwd, script)
            if own is None or is_control_path(tree, own):
                continue
            if _names_control_path(tree, _read_small(os.path.join(cwd, script))):
                hits.append(("BASH-CONTROL-WRITE", f"{script} names an operator-only path and writes; deliver a patch instead"))
    head, bodies = cmdnorm.split_heredocs(command)
    fed = re.search(r"\b(python3?|node|ruby|perl|bash|sh|zsh)\b[^\n|;&]*<<", head)
    if fed and any(_names_control_path(tree, body) for body in bodies):
        hits.append(("BASH-CONTROL-WRITE", "a heredoc names an operator-only path and writes; deliver a patch instead"))
    hits += protected_push(tree, segs or [], rules.get("protected_branches", "main|master"))
    if segs is None and any(re.search(r"(?:^|[\s'\"/])" + glob_regex(g) + r"(?:$|[\s'\"])", command)
                            for g in _controls(tree)) and re.search(r">|\btee\b|-i\b|\brm\b|\bmv\b|\bcp\b", command):
        hits.append(("BASH-CONTROL-WRITE", "unparsable command touches an operator-only path; split it or ask the operator"))
    if not hits:
        return 0
    for rid, message in dict.fromkeys(hits):
        sys.stderr.write(f"gates: blocked [{rid}] {message}\n")
    return 2


def pre_write(payload: dict) -> int:
    """Block secret literals and writes to control files (second line behind permissions.deny)."""
    data = payload.get("tool_input")
    if not isinstance(data, dict):
        sys.stderr.write("gates: blocked [GATES-INFRA] write payload unreadable\n")
        return 2
    path = data.get("file_path", "")
    tree = tree_of(payload, os.path.dirname(path) if path else None)
    texts = [data.get("content") or "", data.get("new_string") or ""]
    texts += [e.get("new_string") or "" for e in data.get("edits") or [] if isinstance(e, dict)]
    blob = "\n".join(texts)
    if tree is None:
        return 0
    hits = []
    for rule in _bash_rules(tree).get("write_rules", []):
        for match in re.finditer(rule["pattern"], blob):
            hits.append((rule["id"], f"{rule['message']} ({match.group(0)[:12]}...)"))
    rel = os.path.relpath(os.path.realpath(path), tree) if path else ""
    if rel and not rel.startswith("..") and is_control_path(tree, rel):
        hits.append(("WRITE-CONTROL", f"{rel} is operator-only; deliver a patch in your report instead"))
    for rid, message in hits:
        sys.stderr.write(f"gates: blocked [{rid}] {message}\n")
    return 2 if hits else 0


def _report(tree: str, name: str, found: List[Finding], first: Optional[str] = None, skipped: Optional[List[str]] = None) -> str:
    """Log and render findings by the message contract."""
    entries = catalog.by_id(catalog.load(tree))
    log = findings.write_log(gitx.state_dir(tree), name, found)
    footer = "Run `make fix` for formatting findings." if any(f.rule == "GATES-FORMAT" for f in found) else ""
    if skipped:
        footer = (footer + "\n" if footer else "") + f"Not exercised (offline): {', '.join(skipped)}"
    return findings.render(found, entries, os.path.relpath(log, tree), first, footer)


def post_edit(payload: dict) -> int:
    """S0: format and check the edited file; exit 2 shows the findings to the agent."""
    data = payload.get("tool_input") or {}
    path = data.get("file_path") or (payload.get("tool_response") or {}).get("filePath") or ""
    if not path or not os.path.isfile(path):
        return 0
    path = os.path.realpath(path)
    tree = tree_of(payload, path)
    if tree is None or not path.startswith(tree + os.sep):
        return 0
    rel = os.path.relpath(path, tree)
    cfg = roles.load(tree)
    entries = catalog.load(tree)
    outcome = engine.run_tier(tree, rel, "s0", cfg, entries)
    found = outcome.findings + roles.unmapped_findings([rel] if roles.is_unmapped(tree, rel, cfg) else [])
    if engine.dispatch_mode(tree) == "touched-lines":
        found = engine.filter_touched(tree, found)
    state.update(tree, lambda d: d.setdefault("batch_hashes", {}).update(state.file_hashes(tree, [rel])))
    if not found:
        return 0
    sys.stderr.write(_report(tree, "post-edit", found, rel, outcome.skipped) + "\n")
    return 2


def post_batch(payload: dict) -> int:
    """S1: check files changed by the batch (including Bash) once; report as context, never block."""
    tree = tree_of(payload)
    if tree is None:
        return 0
    edited = set()
    for call in payload.get("tool_calls") or []:
        path = ((call or {}).get("tool_input") or {}).get("file_path")
        if path and os.path.isfile(path) and os.path.realpath(path).startswith(tree + os.sep):
            edited.add(os.path.relpath(os.path.realpath(path), tree))
    known: Dict[str, str] = state.load(tree).get("batch_hashes", {})
    now = state.file_hashes(tree, gitx.dirty(tree))
    by_bash = {rel for rel, h in now.items() if known.get(rel) != h} - edited
    state.update(tree, lambda d: d.update(batch_hashes=now))
    cfg = roles.load(tree)
    entries = catalog.load(tree)
    found: List[Finding] = []
    skipped: List[str] = []
    for rel in sorted(edited | by_bash):
        tiers = ["s1"] if rel in edited else ["s0", "s1"]
        for tier in tiers:
            outcome = engine.run_tier(tree, rel, tier, cfg, entries, do_format=False, check_format=rel in by_bash)
            found += outcome.findings
            skipped += outcome.skipped
    if engine.dispatch_mode(tree) == "touched-lines":
        found = engine.filter_touched(tree, found)
    if found:
        emit_context("PostToolBatch", _report(tree, "post-batch", found, None, sorted(set(skipped))))
    return 0


def config_change(payload: dict) -> int:
    """Block switching hooks off, rewiring them or shrinking deny during the session."""
    tree = tree_of(payload)
    if tree is None:
        return 0
    source = payload.get("source", "")
    if source == "skills":
        changed = [f for f in manifest.violations(tree) if f.path.startswith(".claude/skills/")]
        for f in changed:
            sys.stderr.write(f"gates: blocked [CONFIG-SKILLS] {f.path}: {f.what}\n")
        return 2 if changed else 0
    path = payload.get("file_path") or ""
    rel = os.path.relpath(os.path.realpath(path), tree) if path else ""
    if rel not in SETTINGS_FILES:
        return 0
    before_text = state.load(tree).get("settings_snapshot", {}).get(rel, "{}")
    try:
        with open(os.path.join(tree, rel), encoding="utf-8") as handle:
            after = json.load(handle)
        before = json.loads(before_text)
    except (OSError, ValueError):
        sys.stderr.write(f"gates: blocked [CONFIG-UNREADABLE] {rel} is not valid JSON\n")
        return 2
    problems = []
    if after.get("disableAllHooks") and not before.get("disableAllHooks"):
        problems.append("disableAllHooks switched on")
    if after.get("hooks") != before.get("hooks"):
        problems.append("hooks changed")
    if after.get("allowManagedHooksOnly") != before.get("allowManagedHooksOnly"):
        problems.append("allowManagedHooksOnly changed")
    if manifest.gate_env(after):
        problems.append(f"env sets {', '.join(manifest.gate_env(after))}; gates never run offline")
    deny_before = set((before.get("permissions") or {}).get("deny", []))
    deny_after = set((after.get("permissions") or {}).get("deny", []))
    if deny_before - deny_after:
        problems.append(f"deny rules removed: {', '.join(sorted(deny_before - deny_after))}")
    for problem in problems:
        sys.stderr.write(f"gates: blocked [CONFIG-CHANGE] {rel}: {problem}; only the operator may\n")
    if problems:
        return 2
    state.update(tree, lambda d: d.setdefault("settings_snapshot", {}).update({rel: json.dumps(after)}))
    return 0


HANDLERS = {"session-start": session_start, "subagent-start": subagent_start, "pre-bash": pre_bash,
            "pre-write": pre_write, "post-edit": post_edit, "post-batch": post_batch,
            "stop": stopgate.on_stop, "subagent-stop": stopgate.on_subagent_stop, "config-change": config_change}
BLOCKING = ("pre-bash", "pre-write", "stop", "subagent-stop", "config-change")


def main(event: str) -> int:
    """Dispatch one hook event; blocking events fail closed on any internal error."""
    if not os.environ.get("GATES_NESTED"):
        os.environ.pop("GATES_OFFLINE", None)
    payload = read_payload()
    if payload is None:
        if event in BLOCKING:
            sys.stderr.write(f"gates: blocked [GATES-INFRA] {event} payload is not JSON\n")
            return 2
        return 0
    handler = HANDLERS.get(event)
    if handler is None:
        sys.stderr.write(f"gates: unknown hook event {event}\n")
        return 2 if event in BLOCKING else 0
    try:
        return handler(payload)
    except Exception as err:  # constraint: a hook must answer with an exit code even when the library breaks
        sys.stderr.write(f"gates: [GATES-INFRA] {event} failed: {type(err).__name__}: {err}\n")
        return 2 if event in BLOCKING or event == "post-edit" else 0
