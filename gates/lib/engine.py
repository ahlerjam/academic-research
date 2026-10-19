"""Internal rule engine for one file: ast-grep by role, text rules, budgets, Python AST rules."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, List, Optional

from . import budgets, catalog, gitx, pyast, roles, textrules, tools
from .findings import Finding


def _sg(tree: str) -> Optional[str]:
    """Locate ast-grep (also installed as 'sg')."""
    return tools.resolve(tree, ".", "ast-grep") or tools.resolve(tree, ".", "sg")


def ast_grep(tree: str, files: List[str], ids: List[str]) -> List[Finding]:
    """Run the given ast-grep rule ids on files; fail closed on every exit other than 0 or 1."""
    if not ids or not files:
        return []
    sg = _sg(tree)
    if sg is None:
        if tools.offline():
            return []
        return [Finding(files[0], 1, "GATES-INFRA", "infrastructure: ast-grep not found; run `make setup`")]
    pattern = "^(" + "|".join(sorted(ids)) + ")$"
    try:
        proc = subprocess.run([sg, "scan", "-c", "gates/sgconfig.yml", "--error", "--json=stream",
                               "--filter", pattern] + files, cwd=tree, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return [Finding(files[0], 1, "GATES-INFRA", "infrastructure: ast-grep exceeded 60 s")]
    if proc.returncode not in (0, 1):
        return [Finding(files[0], 1, "GATES-INFRA",
                        f"infrastructure: ast-grep exit {proc.returncode}: {proc.stderr.strip()[:240]}")]
    found = tools.parse("ast-grep", proc.stdout, "", ".", {})
    if proc.returncode == 1 and not found:
        return [Finding(files[0], 1, "GATES-INFRA", "infrastructure: ast-grep reported errors without JSON")]
    return found


def file_findings(tree: str, rel: str, place: roles.Place, cfg: dict, entries: List[dict]) -> List[Finding]:
    """Return every internal finding for one file of a known place."""
    try:
        with open(os.path.join(tree, rel), encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as err:
        return [Finding(rel, 1, "GATES-INFRA", f"infrastructure: cannot read file: {err}")]
    own = catalog.for_file(entries, place.component, place.role)
    found = ast_grep(tree, [rel], [e["id"] for e in own if e["carrier"] == "ast-grep"])
    own = [e for e in own if e["carrier"] != "ast-grep"]
    found += textrules.scan(rel, text, [e for e in own if e["carrier"] == "text" and e.get("scope", "file") == "file"])
    budget = cfg.get("budgets", {}).get(place.role, {})
    for entry in (e for e in own if e["carrier"] == "gate"):
        ref = entry.get("carrier_ref")
        if ref == "budgets.function" and "function_lines" in budget:
            sg = _sg(tree)
            if sg is None:
                found += [] if tools.offline() else [Finding(rel, 1, "GATES-INFRA", "infrastructure: ast-grep not found")]
                continue
            try:
                lengths = budgets.function_lengths(tree, rel, place.lang, sg)
            except (RuntimeError, ValueError) as err:
                found.append(Finding(rel, 1, "GATES-INFRA", f"infrastructure: {err}"))
                continue
            found += budgets.function_findings(rel, lengths, budget["function_lines"], entry["id"])
        elif ref == "budgets.module" and "module_lines" in budget:
            found += budgets.module_findings(rel, text, budget["module_lines"], entry["id"])
        elif ref == "pyast.argument_mutation" and place.lang == "python":
            found += pyast.argument_mutation(rel, text, entry["id"])
    return found


def dispatch_entries(tree: str, rel: str, tier: str) -> List[dict]:
    """Return dispatch.json entries of a tier whose glob matches the file."""
    with open(os.path.join(tree, "gates", "dispatch.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    out = []
    for entry in data["entries"]:
        if entry.get("tier") != tier:
            continue
        if rel in set(gitx.ls(tree, entry["glob"].split("|"))):
            out.append(entry)
    return out


def dispatch_mode(tree: str) -> str:
    """Return 'strict' or 'touched-lines' from dispatch.json."""
    with open(os.path.join(tree, "gates", "dispatch.json"), encoding="utf-8") as handle:
        return json.load(handle).get("mode", "strict")


def format_check(tree: str, comp_dir: str, argv: List[str], rel: str, cwd_component: bool) -> List[Finding]:
    """Run the formatter in check mode on a file written outside Edit: exit 1 is a GATES-FORMAT finding."""
    exe = tools.resolve(tree, comp_dir, argv[0])
    if exe is None:
        return [] if tools.offline() else [Finding(rel, 1, "GATES-INFRA", f"infrastructure: tool '{argv[0]}' not found; run `make setup`")]
    cwd = os.path.join(tree, comp_dir) if cwd_component else tree
    call = os.path.relpath(os.path.join(tree, rel), cwd)
    try:
        proc = subprocess.run([exe] + tools.expand(argv[1:], [call]), cwd=cwd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return [Finding(rel, 1, "GATES-INFRA", f"infrastructure: '{argv[0]}' exceeded 60 s")]
    if proc.returncode == 0:
        return []
    if proc.returncode == 1:
        return [Finding(rel, 1, "GATES-FORMAT", "not formatted (written outside Edit); run `make fix`")]
    tail = " ".join((proc.stderr or proc.stdout).strip().splitlines()[-3:])[:300]
    return [Finding(rel, 1, "GATES-INFRA", f"infrastructure: '{argv[0]}' exit {proc.returncode}: {tail}")]


def run_tier(tree: str, rel: str, tier: str, cfg: dict, entries: List[dict],
             do_format: bool = True, check_format: bool = False) -> tools.Outcome:
    """Format (or, for files written outside Edit, check the format) then check one file with every entry of a tier."""
    place = roles.place_of(tree, rel, cfg)
    owner = place.component if place else roles.component_of_path(cfg, rel)
    comp_dir = roles.component_dir(cfg, owner) if owner else "."
    codes = catalog.code_map(entries)
    found: List[Finding] = []
    skipped: List[str] = []
    for entry in dispatch_entries(tree, rel, tier):
        if do_format and entry.get("format"):
            outcome = tools.run(tree, comp_dir, entry["format"], [rel], codes,
                                cwd_component=entry.get("cwd") == "component")
            skipped += outcome.skipped
            found += [Finding(f.path, f.line, "GATES-FORMAT", f"formatter failed: {f.what}") for f in outcome.findings]
        elif check_format and entry.get("format_check"):
            found += format_check(tree, comp_dir, entry["format_check"], rel, entry.get("cwd") == "component")
        for argv in entry.get("check", []):
            if argv == ["@rules"]:
                if place is not None:
                    found += file_findings(tree, rel, place, cfg, entries)
                continue
            if argv == ["@repo"]:
                from . import repo
                found += repo.check_all(tree)
                continue
            outcome = tools.run(tree, comp_dir, argv, [rel], codes,
                                cwd_component=entry.get("cwd") == "component",
                                finding_exits=tuple(entry.get("finding_exits", [1])))
            found += outcome.findings
            skipped += outcome.skipped
    return tools.Outcome(_dedupe(found), sorted(set(skipped)))


def _dedupe(found: List[Finding]) -> List[Finding]:
    """Drop identical findings reported by two carriers."""
    seen: Dict[tuple, Finding] = {}
    for f in found:
        seen.setdefault((f.path, f.line, f.rule), f)
    return list(seen.values())


def touched_lines(tree: str, rel: str) -> Optional[set]:
    """Return changed line numbers of a file against HEAD (retrofit mode), None for new files."""
    proc = gitx.run(["git", "diff", "-U0", "HEAD", "--", rel], cwd=tree)
    if proc.returncode != 0 or not proc.stdout:
        tracked = gitx.run(["git", "ls-files", "--error-unmatch", rel], cwd=tree).returncode == 0
        return set() if tracked else None
    lines = set()
    for line in proc.stdout.splitlines():
        if line.startswith("@@"):
            part = line.split("+")[1].split(" ")[0]
            start, _, count = part.partition(",")
            n = int(count) if count else 1
            lines.update(range(int(start), int(start) + n))
    return lines


def filter_touched(tree: str, found: List[Finding]) -> List[Finding]:
    """Keep only findings on touched lines (retrofit), infrastructure findings always stay."""
    cache: Dict[str, Optional[set]] = {}
    out = []
    for f in found:
        if f.rule.startswith("GATES-"):
            out.append(f)
            continue
        if f.path not in cache:
            cache[f.path] = touched_lines(tree, f.path)
        lines = cache[f.path]
        if lines is None or f.line in lines:
            out.append(f)
    return out


def lint(tree: str, component: Optional[str] = None) -> List[Finding]:
    """Run the internal per-file rules over every role file, one ast-grep call per component and role."""
    cfg = roles.load(tree)
    entries = catalog.load(tree)
    idx = roles.index(tree, cfg)
    groups: Dict[tuple, List[str]] = {}
    for rel, place in idx.items():
        if component in (None, place.component):
            groups.setdefault((place.component, place.role), []).append(rel)
    found: List[Finding] = []
    for (comp, role), files in sorted(groups.items()):
        own = catalog.for_file(entries, comp, role)
        ids = [e["id"] for e in own if e["carrier"] == "ast-grep"]
        for start in range(0, len(files), 200):
            found += ast_grep(tree, files[start:start + 200], ids)
        rest = [e for e in own if e["carrier"] != "ast-grep"]
        if not rest:
            continue
        for rel in files:
            place = idx[rel]
            found += [f for f in file_findings(tree, rel, place, cfg, rest)]
    if dispatch_mode(tree) == "touched-lines":
        found = filter_touched(tree, found)
    return _dedupe(found)
