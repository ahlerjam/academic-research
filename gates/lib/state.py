"""Per-worktree gate state, locks and caches under <git-dir>/gates."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import time
from typing import Callable, Iterator, List

from . import gitx


def _path(tree: str, name: str = "state.json") -> str:
    """Return a path inside the state directory."""
    return os.path.join(gitx.state_dir(tree), name)


@contextlib.contextmanager
def lock(tree: str, name: str, timeout: float = 120.0) -> Iterator[bool]:
    """Hold an flock on <git-dir>/gates/<name>.lock; yield False if it was not acquired in time."""
    handle = open(_path(tree, f"{name}.lock"), "a+")
    deadline = time.time() + timeout
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                handle.seek(0)
                handle.truncate()
                handle.write(str(os.getpid()))
                handle.flush()
                break
            except OSError:
                if time.time() >= deadline:
                    break
                time.sleep(0.1)
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def load(tree: str, name: str = "state.json") -> dict:
    """Load a JSON state file, empty when missing or broken."""
    try:
        with open(_path(tree, name), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def update(tree: str, change: Callable[[dict], None], name: str = "state.json") -> dict:
    """Apply a change to a JSON state file under its own lock and return the new state."""
    with lock(tree, name + ".w", timeout=30) as got:
        if not got:
            raise OSError(f"gate state {name} stayed locked for 30 s; another gate run hangs")
        data = load(tree, name)
        change(data)
        tmp = _path(tree, f"{name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
        os.replace(tmp, _path(tree, name))
        return data


def file_hashes(tree: str, files: List[str]) -> dict:
    """Return sha256 of each existing file."""
    out = {}
    for rel in files:
        try:
            with open(os.path.join(tree, rel), "rb") as handle:
                out[rel] = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            out[rel] = "missing"
    return out


def fingerprint(tree: str, files: List[str]) -> str:
    """Return one hash over the names and contents of files."""
    digest = hashlib.sha256()
    for rel, value in sorted(file_hashes(tree, files).items()):
        digest.update(f"{rel}\0{value}\n".encode())
    return digest.hexdigest()
