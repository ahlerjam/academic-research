"""Drift checks D1 to D16: the gates themselves stay complete, strict and in sync."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Callable, List

from . import catalog as catalog_mod
from . import gitx, manifest, roles, tools
from .findings import Finding

RULE_DIRS = re.compile(r"^ruleDirs:\s*\n((?:\s+-\s+.+\n)+)", re.MULTILINE)


def _rule_files(tree: str) -> List[str]:
    """Return every ast-grep rule YAML under gates/rules."""
    return gitx.ls(tree, ["gates/rules/**/*.yml"])


def _read(tree: str, rel: str) -> str:
    """Read a file as text."""
    with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _top_value(text: str, key: str) -> str:
    """Return the value of a top-level YAML scalar key."""
    match = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip().strip("'\"") if match else ""


def d1(tree: str) -> List[Finding]:
    """D1: every source file under a component has a role."""
    return roles.unmapped_findings(roles.unmapped_sources(tree))


def d2_d3(tree: str) -> List[Finding]:
    """D2: no files:/ignores: in rule YAML. D3: every rule has severity error."""
    found = []
    for rel in _rule_files(tree):
        text = _read(tree, rel)
        if re.search(r"^(files|ignores):", text, re.MULTILINE):
            found.append(Finding(rel, 1, "GATES-D2", "rule YAML scopes itself with files:/ignores:; roles.json scopes rules"))
        if _top_value(text, "severity") != "error":
            found.append(Finding(rel, 1, "GATES-D3", "rule severity must be error"))
    return found


def d4(tree: str) -> List[Finding]:
    """D4: rule ids and test ids match one to one; every test has valid and invalid cases."""
    rules = {_top_value(_read(tree, r), "id"): r for r in _rule_files(tree)}
    tests = {}
    found = []
    for rel in gitx.ls(tree, ["gates/rule-tests/**/*.yml"]):
        text = _read(tree, rel)
        tests[_top_value(text, "id")] = rel
        for key in ("valid", "invalid"):
            if not re.search(rf"^{key}:\s*\n\s+-\s+\S", text, re.MULTILINE):
                found.append(Finding(rel, 1, "GATES-D4", f"rule test needs at least one {key} case"))
    found += [Finding(rules[i], 1, "GATES-D4", f"rule {i} has no test") for i in sorted(set(rules) - set(tests))]
    found += [Finding(tests[i], 1, "GATES-D4", f"test {i} has no rule") for i in sorted(set(tests) - set(rules))]
    return found


def d5(tree: str) -> List[Finding]:
    """D5: ast-grep rule tests pass, including rules switched off."""
    if not _rule_files(tree):
        return []
    sg = tools.resolve(tree, ".", "ast-grep") or tools.resolve(tree, ".", "sg")
    if sg is None:
        return [] if tools.offline() else [Finding("gates/sgconfig.yml", 1, "GATES-INFRA", "ast-grep not found")]
    proc = subprocess.run([sg, "test", "-c", "gates/sgconfig.yml", "--skip-snapshot-tests", "--include-off"],
                          cwd=tree, capture_output=True, text=True)
    if proc.returncode == 0:
        return []
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL")] or [proc.stderr.strip()[:300]]
    return [Finding("gates/rule-tests", 1, "GATES-D5", f"ast-grep test: {line}") for line in failed]


def d6(tree: str) -> List[Finding]:
    """D6: fact rules (budgets) live outside ruleDirs, so they never run as findings."""
    text = _read(tree, "gates/sgconfig.yml")
    match = RULE_DIRS.search(text)
    dirs = [d.strip().lstrip("-").strip() for d in match.group(1).splitlines()] if match else []
    return [Finding("gates/sgconfig.yml", 1, "GATES-D6", f"ruleDirs entry '{d}' contains fact rules")
            for d in dirs if d.startswith("facts")]


def d7(tree: str) -> List[Finding]:
    """D7: a text rule forbids ast-grep-ignore, because it would silence the anti-suppress rule."""
    entries = catalog_mod.load(tree)
    ok = any(e["carrier"] == "text" and re.search(e["pattern"], "// ast-grep-ignore: X") for e in entries)
    return [] if ok else [Finding("gates/catalog.json", 1, "GATES-D7", "no text rule forbids ast-grep-ignore")]


def d8(tree: str) -> List[Finding]:
    """D8: every source extension in use has a dispatch entry; every dispatch binary resolves."""
    with open(os.path.join(tree, "gates", "dispatch.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    cfg = roles.load(tree)
    found = []
    covered = set()
    for entry in data["entries"]:
        covered |= {g.rsplit(".", 1)[-1] for g in entry["glob"].split("|") if "." in g}
    exts = {os.path.splitext(r)[1].lstrip(".") for r in roles.index(tree, cfg)}
    found += [Finding("gates/dispatch.json", 1, "GATES-D8", f"no dispatch entry for .{e} files")
              for e in sorted(exts - covered) if e]
    if not tools.offline():
        for entry in data["entries"]:
            for argv in [entry.get("format") or [], entry.get("format_check") or []] + entry.get("check", []):
                if argv and not argv[0].startswith("@") and argv[0] not in ("make", "python3") and not any(
                        tools.resolve(tree, roles.component_dir(cfg, c), argv[0]) for c in cfg["components"]):
                    found.append(Finding("gates/dispatch.json", 1, "GATES-D8", f"binary '{argv[0]}' not found; run `make setup`"))
    return sorted(set(found))


def d11(tree: str) -> List[Finding]:
    """D11: no 'latest' as a tool version."""
    found = []
    for rel in gitx.ls(tree, ["**/package.json", "**/pyproject.toml", "**/*.gradle.kts", "**/libs.versions.toml"]):
        text = _read(tree, rel)
        for match in re.finditer(r"""["':@=]\s*["']?latest["']""", text):
            found.append(Finding(rel, text.count("\n", 0, match.start()) + 1, "GATES-D11", "tool version 'latest'; pin it"))
    return found


def d12(tree: str) -> List[Finding]:
    """D12: neither CI nor make nor the settings run the gates offline."""
    places = [".github/workflows/*.yml", "Makefile", "mk/*.mk", ".claude/settings.json", ".claude/settings.local.json"]
    return [Finding(rel, 1, "GATES-D12", "GATES_OFFLINE set outside the skill's matrix; a missing tool must be red")
            for rel in gitx.ls(tree, places) if "GATES_OFFLINE" in _read(tree, rel)]


def d14(tree: str) -> List[Finding]:
    """D14: every .PHONY name of the Makefile and mk/*.mk is a defined target."""
    texts = {rel: _read(tree, rel) for rel in gitx.ls(tree, ["Makefile", "mk/*.mk"])}
    joined = "\n".join(texts.values()).replace("\\\n", " ")
    targets = {name for line in re.findall(r"^([A-Za-z0-9][A-Za-z0-9 _.-]*):(?!=)", joined, re.MULTILINE)
               for name in line.split()}
    phony = {name for line in re.findall(r"^\.PHONY:(.*)$", joined, re.MULTILINE) for name in line.split()}
    return [Finding("Makefile", 1, "GATES-D14", f".PHONY names '{name}', which no rule defines")
            for name in sorted(phony - targets)]


def d13(tree: str) -> List[Finding]:
    """D13: every catalog entry is complete and its fixture and carrier file exist."""
    found = []
    seen = set()
    for entry in catalog_mod.load(tree):
        rid = entry.get("id", "?")
        if rid in seen:
            found.append(Finding("gates/catalog.json", 1, "GATES-D13", f"duplicate id {rid}"))
        seen.add(rid)
        for key in ("carrier", "why", "fix", "fixture"):
            if not entry.get(key):
                found.append(Finding("gates/catalog.json", 1, "GATES-D13", f"{rid} lacks '{key}'"))
        fixture = entry.get("fixture", "")
        if fixture and not fixture.startswith("test:") and not os.path.isdir(os.path.join(tree, fixture)):
            found.append(Finding("gates/catalog.json", 1, "GATES-D13", f"{rid} fixture {fixture} missing"))
        ref = entry.get("carrier_ref", "")
        if entry.get("carrier") == "ast-grep" and not os.path.isfile(os.path.join(tree, ref)):
            found.append(Finding("gates/catalog.json", 1, "GATES-D13", f"{rid} rule file {ref} missing"))
    return found


TOOL_TABLES = re.compile(r"^\[tool\.(ruff|pyright|pytest|importlinter|mypy)\b", re.MULTILINE)


def d15(tree: str) -> List[Finding]:
    """D15: no tool table in a pyproject.toml outranks the operator's ruff.toml, pyrightconfig.json or pytest.ini."""
    found = []
    for rel in gitx.ls(tree, ["**/pyproject.toml", "pyproject.toml"]):
        text = _read(tree, rel)
        for match in TOOL_TABLES.finditer(text):
            found.append(Finding(rel, text.count("\n", 0, match.start()) + 1, "GATES-D15",
                                 f"[tool.{match.group(1)}] in pyproject.toml overrides the operator's config; remove it"))
    return found


def d16(tree: str) -> List[Finding]:
    """D16: make never runs npx (without a TTY it installs an unpinned version) and local settings never switch hooks off."""
    found = [Finding(rel, 1, "GATES-D16", "npx in a make verb; call node_modules/.bin/<tool>")
             for rel in gitx.ls(tree, ["Makefile", "mk/*.mk"])
             if re.search(r"(^|[\s;&|(])npx\s", re.sub(r"(?m)^\s*#.*$", "", _read(tree, rel)))]
    return found + manifest.local_findings(tree)


CHECKS: List[Callable[[str], List[Finding]]] = [d1, d2_d3, d4, d5, d6, d7, d8, d11, d12, d13, d14, d15, d16]


def violations(tree: str) -> List[Finding]:
    """Run every drift check (D9 sync and D10 AGENTS.md/ADR run in check-repo)."""
    found: List[Finding] = []
    for check in CHECKS:
        found += check(tree)
    return found
