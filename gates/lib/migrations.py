"""Migrations: unique gapless numbers, immutable once on the baseline, exactly one Alembic head; numbering under a lock."""

from __future__ import annotations

import fcntl
import os
import posixpath
import re
import time
from typing import List, Set

from . import gitx, roles
from .findings import Finding

SQL_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
REVISION = re.compile(r"^revision\s*(?::\s*\w+\s*)?=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*(.+)$", re.MULTILINE)
SLUG = re.compile(r"^[a-z0-9_]+$")
LOCK_SECONDS = 30


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


def sql_directory(tree: str) -> str:
    """Return the one repo-relative SQL migration directory: migrations_dir or a plain *.sql migration role glob.

    ValueError when no component or more than one directory qualifies, because `migration new` takes no
    component and must never guess.
    """
    cfg = roles.load(tree)
    found = set()
    for name, comp in sorted(cfg["components"].items()):
        if comp.get("migrations_dir"):
            found.add(comp["migrations_dir"])
            continue
        for glob in roles.patterns(cfg, name, "migration"):
            folder, base = posixpath.split(glob)
            if base.endswith(".sql") and not any(c in folder for c in "*?["):
                found.add(folder)
    if len(found) != 1:
        raise ValueError(f"expected exactly one SQL migration directory in gates/roles.json, found {sorted(found)}")
    return found.pop()


def taken_numbers(tree: str, directory: str) -> Set[int]:
    """Return migration numbers used in any worktree of this repository or on any local or remote branch."""
    def numbers(names: List[str]) -> Set[int]:
        return {int(m.group(1)) for m in (SQL_NAME.match(os.path.basename(n)) for n in names) if m}

    found = numbers(os.listdir(os.path.join(tree, directory))) if os.path.isdir(os.path.join(tree, directory)) else set()
    listing = gitx.run(["git", "worktree", "list", "--porcelain"], cwd=tree).stdout
    for line in listing.splitlines():
        folder = os.path.join(line[len("worktree "):], directory) if line.startswith("worktree ") else ""
        if folder and os.path.isdir(folder):
            found |= numbers(os.listdir(folder))
    refs = gitx.run(["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"], cwd=tree).stdout
    for ref in refs.split():
        found |= numbers(gitx.run(["git", "ls-tree", "--name-only", ref, directory + "/"], cwd=tree).stdout.split())
    return found


def new(tree: str, name: str) -> str:
    """Create the next SQL migration under a lock in the shared git directory and return its repo-relative path.

    The number skips every number in any worktree and on any local or remote branch, so parallel units never
    draw the same one (the pattern of adr.new); ValueError for a name that is not snake_case or without exactly
    one migration directory, RuntimeError when another migration new holds the lock for longer than LOCK_SECONDS.
    """
    if not SLUG.match(name or ""):
        raise ValueError("migration name must be snake_case: [a-z0-9_]+")
    directory = sql_directory(tree)
    with open(os.path.join(gitx.common_dir(tree), "gates-migration.lock"), "w") as lock:
        deadline = time.time() + LOCK_SECONDS
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() > deadline:
                    raise RuntimeError("another migration new holds the lock")
                time.sleep(0.2)
        number = max(taken_numbers(tree, directory), default=0) + 1
        rel = f"{directory}/{number:04d}_{name}.sql"
        os.makedirs(os.path.join(tree, directory), exist_ok=True)
        with open(os.path.join(tree, rel), "x", encoding="utf-8") as handle:
            handle.write(f"-- {number:04d}_{name}\n")
        return rel
