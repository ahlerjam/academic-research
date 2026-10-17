"""Migrations: unique gapless numbers, immutable once on the baseline, exactly one Alembic head."""

from __future__ import annotations

import os
import re
from typing import List

from . import gitx
from .findings import Finding

SQL_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
REVISION = re.compile(r"^revision\s*(?::\s*\w+\s*)?=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*(.+)$", re.MULTILINE)


def sql_violations(tree: str, directory: str, rule: str) -> List[Finding]:
    """Return numbering and immutability findings for plain SQL migrations."""
    files = sorted(f for f in gitx.ls(tree, [f"{directory}/*.sql"]))
    found: List[Finding] = []
    numbers = []
    for rel in files:
        match = SQL_NAME.match(os.path.basename(rel))
        if not match:
            found.append(Finding(rel, 1, rule, "migration name must be NNNN_snake_case.sql"))
            continue
        numbers.append((int(match.group(1)), rel))
    seen = {}
    for number, rel in numbers:
        if number in seen:
            found.append(Finding(rel, 1, rule, f"migration number {number:04d} also used by {seen[number]}"))
        seen.setdefault(number, rel)
    expected = list(range(1, len(seen) + 1))
    if sorted(seen) != expected:
        found.append(Finding(directory, 1, rule, f"migration numbers must run 0001..{len(seen):04d} without gaps"))
    ref = gitx.base_ref(tree) or ("HEAD" if gitx.head(tree) else None)
    if ref:
        for rel in files:
            old = gitx.show(tree, ref, rel)
            with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as handle:
                if old is not None and old != handle.read():
                    found.append(Finding(rel, 1, rule, f"migration exists on {ref} and was changed; add a new one"))
    return found


def alembic_violations(tree: str, directory: str, rule: str) -> List[Finding]:
    """Return a finding unless the Alembic versions form exactly one head."""
    revisions, downs = {}, set()
    for rel in gitx.ls(tree, [f"{directory}/*.py"]):
        with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        rev = REVISION.search(text)
        if not rev:
            continue
        revisions[rev.group(1)] = rel
        down = DOWN.search(text)
        if down:
            downs |= set(re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)))
    heads = sorted(set(revisions) - downs)
    if revisions and len(heads) != 1:
        return [Finding(directory, 1, rule, f"expected exactly one Alembic head, found {len(heads)}: {', '.join(heads)}")]
    return []
