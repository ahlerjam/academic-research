"""Thin git helpers; every path is POSIX and relative to the tree root."""

from __future__ import annotations

import os
import subprocess
from typing import Dict, List, Optional, Sequence


ANCHOR = "refs/gates/baseline"
DEFAULT_TIMEOUT = 30.0


def run(args: Sequence[str], cwd: str, stdin: Optional[str] = None,
        timeout: Optional[float] = DEFAULT_TIMEOUT, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run a command and capture text output without raising on a non-zero exit; a hung git raises TimeoutExpired."""
    return subprocess.run(list(args), cwd=cwd, input=stdin, capture_output=True, text=True,
                          timeout=timeout, env=env)


def toplevel(path: str) -> Optional[str]:
    """Return the work tree root that contains path, or None outside git."""
    start = path if os.path.isdir(path) else os.path.dirname(path) or "."
    proc = run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    return os.path.realpath(proc.stdout.strip()) if proc.returncode == 0 else None


def gitdir(tree: str) -> str:
    """Return the absolute git directory of this work tree (per worktree)."""
    return run(["git", "rev-parse", "--absolute-git-dir"], cwd=tree).stdout.strip()


def common_dir(tree: str) -> str:
    """Return the git directory shared by all worktrees."""
    out = run(["git", "rev-parse", "--git-common-dir"], cwd=tree).stdout.strip()
    return os.path.realpath(os.path.join(tree, out))


def state_dir(tree: str) -> str:
    """Return the per-worktree directory for gate state, locks, caches and logs."""
    path = os.path.join(gitdir(tree), "gates")
    os.makedirs(path, exist_ok=True)
    return path


def ls(tree: str, patterns: Sequence[str]) -> List[str]:
    """List tracked and untracked, not ignored files matching git glob pathspecs."""
    if not patterns:
        return []
    specs = [":(glob)" + p for p in patterns]
    proc = run(["git", "ls-files", "-co", "--exclude-standard", "-z", "--"] + specs, cwd=tree)
    if proc.returncode != 0:
        return []
    return sorted({p for p in proc.stdout.split("\0") if p and os.path.lexists(os.path.join(tree, p))})


def exists_in_tree(tree: str, rel: str) -> bool:
    """Return whether rel is a regular file in the work tree."""
    return os.path.isfile(os.path.join(tree, rel))


def dirty(tree: str, deleted: bool = False) -> List[str]:
    """Return changed or untracked files that still exist (renames give the new path); deleted=True keeps deletions."""
    proc = run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=tree)
    parts = proc.stdout.split("\0")
    out: List[str] = []
    skip = False
    for part in parts:
        if skip:
            skip = False
            if deleted and part:
                out.append(part)
            continue
        if len(part) < 4:
            continue
        code, path = part[:2], part[3:]
        if "R" in code or "C" in code:
            skip = True
        if exists_in_tree(tree, path) or (deleted and "D" in code):
            out.append(path)
    return sorted(set(out))


def default_ref(tree: str) -> Optional[str]:
    """Return origin's default branch as a ref, or None without a remote."""
    proc = run(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd=tree)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    for name in ("origin/main", "origin/master"):
        if run(["git", "rev-parse", "--verify", "--quiet", name], cwd=tree).returncode == 0:
            return name
    return None


def anchor(tree: str) -> Optional[str]:
    """Return the local baseline ref the operator set without a remote, or None."""
    proc = run(["git", "rev-parse", "--verify", "--quiet", ANCHOR + "^{commit}"], cwd=tree)
    return ANCHOR if proc.returncode == 0 else None


def base_ref(tree: str) -> Optional[str]:
    """Return the reference the gates compare against: origin's default branch, else the local anchor."""
    return default_ref(tree) or anchor(tree)


def head(tree: str) -> Optional[str]:
    """Return the HEAD commit, or None in a repository without commits."""
    proc = run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=tree)
    return proc.stdout.strip() if proc.returncode == 0 else None


def show(tree: str, ref: str, rel: str) -> Optional[str]:
    """Return the content of rel at ref, or None if it does not exist there."""
    proc = run(["git", "show", f"{ref}:{rel}"], cwd=tree)
    return proc.stdout if proc.returncode == 0 else None


def changed_since_base(tree: str, deleted: bool = False) -> List[str]:
    """Return files changed since the merge base with the base ref (never @{upstream}) plus untracked files."""
    ref = base_ref(tree)
    proc = run(["git", "merge-base", "HEAD", ref], cwd=tree) if ref else None
    if proc is None or proc.returncode != 0:
        if head(tree) is None:
            return ls(tree, ["**"])
        listed = run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=tree)
        return sorted(p for p in listed.stdout.split("\0") if p and exists_in_tree(tree, p))
    base = proc.stdout.strip()
    diff = run(["git", "diff", "--name-only", "-z", "--no-renames", base], cwd=tree).stdout.split("\0")
    files = {p for p in diff if p and (deleted or exists_in_tree(tree, p))}
    return sorted(files | set(dirty(tree, deleted)))


def files_between(tree: str, old: str, new: str = "HEAD", deleted: bool = False) -> List[str]:
    """Return files that differ between two commits; deleted=True keeps files that no longer exist."""
    proc = run(["git", "diff", "--name-only", "-z", "--no-renames", old, new], cwd=tree)
    return sorted(p for p in proc.stdout.split("\0") if p and (deleted or exists_in_tree(tree, p)))
