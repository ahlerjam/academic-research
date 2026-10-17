"""Suppression counter: inline suppressions may never increase against the baseline."""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List

from . import gitx
from .findings import Finding

MARKERS = {
    "python": r"#\s*(noqa|type:\s*ignore|pyright:\s*ignore|ruff:\s*(ignore|noqa))",
    "typescript": r"(eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck)",
    "kotlin": r"@(file:)?(kotlin\.)?Suppress\b|\bimport\s+kotlin\.Suppress\b|\bSuppressWarnings\b",
    "sql": r"--\s*(noqa|squawk-ignore)|/\*\s*noqa",
    "css": r"stylelint-disable",
    "any": r"ast-grep-ignore",
}
EXT = {".py": "python", ".ts": "typescript", ".kt": "kotlin", ".kts": "kotlin", ".sql": "sql",
       ".css": "css", ".scss": "css", ".html": "typescript"}
BASELINE = "gates/suppress-baseline.json"


def count(tree: str) -> Dict[str, int]:
    """Count suppression markers per language across tracked source files."""
    totals: Dict[str, int] = {}
    for rel in gitx.ls(tree, ["**"]):
        lang = EXT.get(os.path.splitext(rel)[1])
        if lang is None or rel.startswith("gates/"):
            continue
        with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        for key in (lang, "any"):
            hits = len(re.findall(MARKERS[key], text))
            if hits:
                totals[key] = totals.get(key, 0) + hits
    return totals


def violations(tree: str, rule: str) -> List[Finding]:
    """Return a finding per language whose suppression count rose above the baseline."""
    path = os.path.join(tree, BASELINE)
    base = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            base = json.load(handle)
    return [Finding(BASELINE, 1, rule, f"{lang}: {n} inline suppressions, baseline allows {base.get(lang, 0)}")
            for lang, n in sorted(count(tree).items()) if n > base.get(lang, 0)]
