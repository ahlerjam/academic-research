"""Run foreign tools under the fail-closed contract: 0 clean, 1 findings, anything else red."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, NamedTuple, Optional, Sequence

from .findings import Finding

GENERIC = re.compile(r"^(?P<path>[^\s:][^:]*):(?P<line>\d+)(?::\d+)?:?\s+(?P<code>[A-Za-z][\w/@.-]*)?:?\s*(?P<what>.*)$")
RUFF = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+):\d+: (?P<code>[A-Z]+\d+) (?P<what>.*)$")
SQUAWK = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+):\d+: \w+: (?P<code>[\w-]+) (?P<what>.*)$")
BIN_DIRS = (".venv/bin", "node_modules/.bin", "build/tools", "bin")


class Outcome(NamedTuple):
    """Result of one tool call: findings, infrastructure failures and skipped tools."""

    findings: List[Finding]
    skipped: List[str]


def offline() -> bool:
    """Return whether missing tools are reported as skipped instead of red (matrix only)."""
    return os.environ.get("GATES_OFFLINE") == "1"


def resolve(tree: str, comp_dir: str, name: str) -> Optional[str]:
    """Find a tool in the component, the repo root, then PATH."""
    if "/" in name:
        path = os.path.join(tree, comp_dir, name)
        return path if os.access(path, os.X_OK) else None
    for base in (os.path.join(tree, comp_dir), tree):
        for sub in BIN_DIRS:
            path = os.path.join(base, sub, name)
            if os.access(path, os.X_OK):
                return path
    return shutil.which(name)


def expand(argv: Sequence[str], files: Sequence[str]) -> List[str]:
    """Replace {file} and {files} placeholders."""
    out: List[str] = []
    for arg in argv:
        if arg == "{files}":
            out.extend(files)
        elif "{file}" in arg:
            out.append(arg.replace("{file}", files[0] if files else ""))
        else:
            out.append(arg)
    return out


def parse(tool: str, stdout: str, stderr: str, cwd_rel: str, codes: Dict[str, str]) -> List[Finding]:
    """Parse tool output into findings (ast-grep JSON, ESLint JSON, ruff concise, generic)."""
    found: List[Finding] = []
    base = os.path.basename(tool)
    if base in ("ast-grep", "sg"):
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            item = json.loads(line)
            found.append(Finding(_rel(cwd_rel, item["file"]), item["range"]["start"]["line"] + 1,
                                 item.get("ruleId", "AST-GREP"), item.get("message", "").strip()))
        return found
    if base == "eslint" and stdout.lstrip().startswith("["):
        for result in json.loads(stdout):
            for msg in result.get("messages", []):
                rule = msg.get("ruleId") or "eslint"
                found.append(Finding(_rel(cwd_rel, result["filePath"]), int(msg.get("line") or 1),
                                     codes.get(rule, f"eslint:{rule}"), msg.get("message", "")))
        return found
    if base == "sqlfluff" and stdout.lstrip().startswith("["):
        for result in json.loads(stdout):
            for v in result.get("violations", []):
                code = v.get("code", "sqlfluff")
                found.append(Finding(_rel(cwd_rel, result["filepath"]), int(v.get("start_line_no") or 1),
                                     codes.get(code, f"sqlfluff:{code}"), v.get("description", "")))
        return found
    if base == "stylelint":
        text = stdout if stdout.lstrip().startswith("[") else stderr
        for result in json.loads(text[text.index("["):]):
            for w in result.get("warnings", []):
                rule = w.get("rule", "stylelint")
                found.append(Finding(_rel(cwd_rel, result["source"]), int(w.get("line") or 1),
                                     codes.get(rule, f"stylelint:{rule}"), w.get("text", "")))
        return found
    if base == "squawk":
        for line in stdout.splitlines():
            match = SQUAWK.match(line.strip())
            if match:
                code = match.group("code")
                found.append(Finding(_rel(cwd_rel, match.group("path")), int(match.group("line")) + 1,
                                     codes.get(code, f"squawk:{code}"), match.group("what")))
        return found
    pattern = RUFF if base == "ruff" else GENERIC
    for line in (stdout + "\n" + stderr).splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        code = match.group("code") or base
        found.append(Finding(_rel(cwd_rel, match.group("path")), int(match.group("line")),
                             codes.get(code, f"{base}:{code}"), match.group("what").strip()))
    return found


def _rel(cwd_rel: str, path: str) -> str:
    """Make a tool-reported path repo-relative."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(cwd_rel, path)) if cwd_rel not in ("", ".") else os.path.normpath(path)


def _in_tree(tree: str, finding: Finding) -> Finding:
    """Make an absolute path a tool reported (ESLint, Stylelint) relative to the tree, as the message contract wants."""
    if not os.path.isabs(finding.path):
        return finding
    rel = os.path.relpath(os.path.realpath(finding.path), os.path.realpath(tree))
    return finding if rel.startswith("..") else finding._replace(path=rel)


def run(tree: str, comp_dir: str, argv: Sequence[str], files: Sequence[str], codes: Dict[str, str],
        timeout: float = 60.0, cwd_component: bool = False, finding_exits: Sequence[int] = (1,)) -> Outcome:
    """Run one tool and apply the fail-closed exit contract (finding_exits: codes that mean findings)."""
    name = argv[0]
    exe = resolve(tree, comp_dir, name)
    if exe is None:
        if offline():
            return Outcome([], [name])
        return Outcome([Finding(files[0] if files else ".", 1, "GATES-INFRA",
                                f"infrastructure: tool '{name}' not found; run `make setup`")], [])
    cwd = os.path.join(tree, comp_dir) if cwd_component else tree
    cwd_rel = comp_dir if cwd_component else "."
    call_files = [os.path.relpath(os.path.join(tree, f), cwd) for f in files]
    try:
        proc = subprocess.run([exe] + expand(argv[1:], call_files), cwd=cwd, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Outcome([Finding(files[0] if files else ".", 1, "GATES-INFRA",
                                f"infrastructure: '{name}' exceeded {int(timeout)} s")], [])
    if proc.returncode == 0:
        return Outcome([], [])
    try:
        found = [_in_tree(tree, f) for f in parse(name, proc.stdout, proc.stderr, cwd_rel, codes)]
    except (ValueError, KeyError, TypeError):
        found = []
    if proc.returncode in finding_exits and found:
        return Outcome(found, [])
    tail = " ".join((proc.stderr or proc.stdout).strip().splitlines()[-3:])[:300]
    label = "findings without parsable location" if proc.returncode in finding_exits else f"exit {proc.returncode}"
    return Outcome(found + [Finding(files[0] if files else ".", 1, "GATES-INFRA",
                                    f"infrastructure: '{name}' {label}: {tail}")], [])
