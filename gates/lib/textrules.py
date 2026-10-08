"""Regex rules from the catalog (carrier 'text'), for what no parser expresses."""

from __future__ import annotations

import re
from typing import List

from .findings import Finding


def scan(rel: str, text: str, entries: List[dict]) -> List[Finding]:
    """Apply every text rule to one file's content and return one finding per match."""
    found: List[Finding] = []
    for entry in entries:
        pattern = re.compile(entry["pattern"], re.MULTILINE)
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(Finding(rel, line, entry["id"], entry.get("what", entry["id"].lower())))
    return found
