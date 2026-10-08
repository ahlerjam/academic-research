"""Function and module line budgets per role, from ast-grep fact rules outside ruleDirs."""

from __future__ import annotations

import json
import os
import subprocess
from typing import List

from .findings import Finding

FACT_LANG = {"python": "python", "typescript": "typescript", "kotlin": "kotlin"}


def function_lengths(tree: str, rel: str, lang: str, sg: str) -> List[tuple]:
    """Return (line, length) for every function in the file, via gates/facts/<lang>-functions.yml."""
    fact = os.path.join(tree, "gates", "facts", f"{FACT_LANG.get(lang, lang)}-functions.yml")
    if not os.path.isfile(fact):
        return []
    proc = subprocess.run([sg, "scan", "-r", fact, "--json=compact", rel], cwd=tree,
                          capture_output=True, text=True)
    if proc.returncode not in (0, 1) or not proc.stdout.strip().startswith("["):
        raise RuntimeError(f"ast-grep fact rule failed with exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    return [(m["range"]["start"]["line"] + 1, m["range"]["end"]["line"] - m["range"]["start"]["line"] + 1)
            for m in json.loads(proc.stdout)]


def function_findings(rel: str, lengths: List[tuple], limit: int, rule: str) -> List[Finding]:
    """Return one finding per function longer than the role budget."""
    return [Finding(rel, line, rule, f"function has {length} lines (budget {limit})")
            for line, length in lengths if length > limit]


def module_findings(rel: str, text: str, limit: int, rule: str) -> List[Finding]:
    """Return a finding when the module exceeds the role budget."""
    count = len(text.splitlines())
    return [Finding(rel, 1, rule, f"module has {count} lines (budget {limit})")] if count > limit else []
