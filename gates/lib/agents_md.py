"""AGENTS.md: line budget and the (gate: ID) or (review) tag on every rule line."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Tuple

from .findings import Finding

MAX_LINES = 100
INFO_SECTIONS = ("commands", "layout", "where things live")
TAG = re.compile(r"\((?:gate:\s*([A-Z0-9-]+(?:\s*,\s*[A-Z0-9-]+)*)|review)\)\s*$")


def rule_lines(text: str) -> List[Tuple[int, str]]:
    """Return (first line, joined text) of every bullet outside the info sections."""
    out: List[Tuple[int, str]] = []
    section = ""
    current = None
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("#"):
            section = line.lstrip("#").strip().lower()
            current = None
            continue
        if section in INFO_SECTIONS:
            continue
        if line.startswith("- "):
            current = [number, line[2:].strip()]
            out.append(current)  # type: ignore[arg-type]
        elif current is not None and line.startswith("  ") and line.strip():
            current[1] = f"{current[1]} {line.strip()}"
        else:
            current = None
    return [(n, t) for n, t in out]


def violations(tree: str, catalog: Dict[str, dict], rule: str) -> List[Finding]:
    """Return findings for budget, missing tags, unknown ids and catalog rules missing from AGENTS.md."""
    path = os.path.join(tree, "AGENTS.md")
    if not os.path.isfile(path):
        return [Finding("AGENTS.md", 1, rule, "AGENTS.md is missing")]
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    found: List[Finding] = []
    count = len(text.splitlines())
    if count > MAX_LINES:
        found.append(Finding("AGENTS.md", 1, rule, f"AGENTS.md has {count} lines (max {MAX_LINES})"))
    mentioned = set()
    for number, line in rule_lines(text):
        match = TAG.search(line)
        if not match:
            found.append(Finding("AGENTS.md", number, rule, "rule line ends without (gate: ID) or (review)"))
            continue
        for rid in [i.strip() for i in (match.group(1) or "").split(",") if i.strip()]:
            mentioned.add(rid)
            entry = catalog.get(rid)
            if entry is None:
                found.append(Finding("AGENTS.md", number, rule, f"unknown gate id {rid}"))
            elif not entry.get("fixture") or not entry.get("carrier"):
                found.append(Finding("AGENTS.md", number, rule, f"gate {rid} has no fixture or carrier"))
    for rid, entry in sorted(catalog.items()):
        if entry.get("agents_md") and rid not in mentioned:
            found.append(Finding("AGENTS.md", 1, rule, f"catalog rule {rid} is not tagged in AGENTS.md"))
    return found


def review_count(tree: str) -> int:
    """Return the number of (review) rule lines, reported by audit."""
    path = os.path.join(tree, "AGENTS.md")
    if not os.path.isfile(path):
        return 0
    with open(path, encoding="utf-8") as handle:
        return sum(1 for _, line in rule_lines(handle.read()) if line.endswith("(review)"))
