"""Ratchet guard: agents may add gates, never weaken them (compared with origin's default branch)."""

from __future__ import annotations

import json
import os
from typing import List

from . import gitx, manifest
from .findings import Finding


def violations(tree: str) -> List[Finding]:
    """Return weakening changes on ratchet paths against the baseline branch."""
    cfg = manifest.controls(tree)
    if not cfg.get("ratchet"):
        return []
    ref = gitx.base_ref(tree) or ("HEAD" if gitx.head(tree) else None)
    if ref is None:
        return []
    found: List[Finding] = []
    base = gitx.run(["git", "ls-tree", "-r", "--name-only", ref, "--", "gates/rules", "gates/rule-tests",
                     "gates/fixtures"], cwd=tree).stdout.split()
    for rel in base:
        old = gitx.show(tree, ref, rel)
        path = os.path.join(tree, rel)
        if not os.path.isfile(path):
            found.append(Finding(rel, 1, "GATES-RATCHET", f"deleted against {ref}; gates may only grow"))
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            new = handle.read()
        if rel.startswith("gates/rule-tests/"):
            lost = [line for line in (old or "").splitlines() if line.strip() and line not in new.splitlines()]
            if lost:
                found.append(Finding(rel, 1, "GATES-RATCHET", f"{len(lost)} test lines removed"))
        elif old != new:
            found.append(Finding(rel, 1, "GATES-RATCHET", f"changed against {ref}; add a new rule instead"))
    old_cat = gitx.show(tree, ref, "gates/catalog.json")
    if old_cat:
        with open(os.path.join(tree, "gates", "catalog.json"), encoding="utf-8") as handle:
            now = {e["id"]: e for e in json.load(handle)}
        for entry in json.loads(old_cat):
            if now.get(entry["id"]) != entry:
                found.append(Finding("gates/catalog.json", 1, "GATES-RATCHET", f"{entry['id']} removed or changed"))
    old_roles = gitx.show(tree, ref, "gates/roles.json")
    if old_roles:
        with open(os.path.join(tree, "gates", "roles.json"), encoding="utf-8") as handle:
            if json.load(handle) != json.loads(old_roles):
                found.append(Finding("gates/roles.json", 1, "GATES-RATCHET", "roles or budgets changed; operator only"))
    return found
