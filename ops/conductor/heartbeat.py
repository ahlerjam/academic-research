"""Lease and progress of the cloud lead in docs/autonomy/progress.json on the state branch (never main).

Usage:
    python3 -I ops/conductor/heartbeat.py new-holder          # once per lead session; prints and caches the id
    python3 -I ops/conductor/heartbeat.py whoami              # the cached holder id of this checkout
    python3 -I ops/conductor/heartbeat.py status              # watch done|fresh|stale plus the progress (read-only)
    python3 -I ops/conductor/heartbeat.py beat --holder H [--unit-in-flight N ...] [--next-step T] [--note T]
        [--run proof:1=RUN_ID] [--limit-stop] [--state-file .ar/state.json] [--goal-met]

The branch holds one file and is written with git plumbing (hash-object, mktree, commit-tree) and a plain,
never forced push, so the lead's working tree is untouched. A rejected push means another writer won: the
beat re-reads and decides again. A second lead takes over only when the lease is older than 2 hours.
Exit codes: 0 done, 1 git error (a refused push counts), 3 the lease belongs to another holder.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from typing import Dict, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import state

LOCAL_REF = "refs/conductor/state"
HOLDER_RX = re.compile(r"^[A-Za-z0-9._:-]{3,80}$")
RUN_RX = re.compile(r"^(proof:[0-9][a-z]?|release-dry:[0-9]+\.[0-9]+\.[0-9]+)=([1-9][0-9]{0,19})$")
NOTES_KEEP = 20
PUSH_TRIES = 3
REJECTED = ("non-fast-forward", "fetch first", "[rejected]", "stale info", "cannot lock ref")


class GitError(Exception):
    """A git command failed."""


# ---------------------------------------------------------------- pure decisions


def lease_age(progress: dict, now: float) -> Optional[float]:
    """Return the age of the lease in seconds, or None without a lease."""
    lease = progress.get("lease") if isinstance(progress.get("lease"), dict) else None
    if not lease or not lease.get("holder"):
        return None
    return max(0.0, now - float(lease.get("beat_at") or 0))


def decide_lease(progress: dict, holder: Optional[str], now: float, max_age_s: float) -> dict:
    """Decide free, own, takeover (lease older than max_age_s) or held for one would-be holder."""
    age = lease_age(progress, now)
    current = (progress.get("lease") or {}).get("holder") if age is not None else None
    if age is None:
        kind = "free"
    elif holder is not None and current == holder:
        kind = "own"
    elif age > max_age_s:
        kind = "takeover"
    else:
        kind = "held"
    return {"kind": kind, "holder": current, "age_s": None if age is None else round(age)}


def watch_verdict(progress: dict, now: float, max_age_s: float) -> str:
    """Tell the watchdog: done when the goal was met, fresh while a lease lives, else stale."""
    if progress.get("goal_met"):
        return "done"
    return "fresh" if decide_lease(progress, None, now, max_age_s)["kind"] == "held" else "stale"


def apply_beat(progress: dict, holder: str, now: float, updates: dict) -> dict:
    """Return the next progress document: lease renewed for holder, fields from updates merged in."""
    out = json.loads(json.dumps(progress)) if progress else {}
    out.pop("corrupt", None)
    out["schema"] = 1
    old = out.get("lease") if isinstance(out.get("lease"), dict) else {}
    acquired = old.get("acquired_at") if old.get("holder") == holder else now
    out["lease"] = {"holder": holder, "acquired_at": acquired, "beat_at": now}
    if old.get("holder") and old.get("holder") != holder:
        takeovers = out.get("takeovers") if isinstance(out.get("takeovers"), list) else []
        takeovers.append({"from": old.get("holder"), "to": holder, "at": now})
        out["takeovers"] = takeovers[-NOTES_KEEP:]
    for key in ("unit_in_flight", "next_step", "forecast", "last_merged"):
        if key in updates:
            out[key] = updates[key]
    if updates.get("runs"):
        runs = out.get("runs") if isinstance(out.get("runs"), dict) else {}
        runs.update(updates["runs"])
        out["runs"] = runs
    if updates.get("limit_stop"):
        out["limit_stops"] = int(out.get("limit_stops") or 0) + 1
        out["last_limit_stop"] = now
    if updates.get("note"):
        notes = out.get("notes") if isinstance(out.get("notes"), list) else []
        notes.append({"at": now, "by": holder, "text": updates["note"]})
        out["notes"] = notes[-NOTES_KEEP:]
    if updates.get("goal_met"):
        out["goal_met"] = True
    return out


def parse_runs(items: Sequence[str]) -> Dict[str, str]:
    """Parse `proof:<stage>=<run id>` and `release-dry:<version>=<run id>` arguments."""
    out: Dict[str, str] = {}
    for item in items:
        m = RUN_RX.match(item or "")
        if not m:
            raise ValueError(f"--run must be proof:<stage>=<id> or release-dry:<version>=<id>, got {item!r}")
        out[m.group(1)] = m.group(2)
    return out


# ---------------------------------------------------------------- git


def git(repo: str, args: Sequence[str], stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run git in repo without raising, with English messages so rejections can be recognised."""
    env = dict(os.environ, LC_ALL="C", LANGUAGE="C")
    return subprocess.run(["git", *args], cwd=repo, input=stdin, capture_output=True, text=True, timeout=120, env=env)


def _ok(proc: subprocess.CompletedProcess, what: str) -> str:
    """Return stdout of a successful git call or raise GitError."""
    if proc.returncode != 0:
        raise GitError(f"git {what}: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def fetch_tip(repo: str, branch: str) -> Optional[str]:
    """Fetch the state branch into a private ref and return its commit, or None when the branch does not exist yet."""
    probe = git(repo, ["ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"])
    if probe.returncode == 2:
        git(repo, ["update-ref", "-d", LOCAL_REF])
        return None
    _ok(probe, f"ls-remote {branch}")
    _ok(git(repo, ["fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/{branch}:{LOCAL_REF}"]), f"fetch {branch}")
    return _ok(git(repo, ["rev-parse", LOCAL_REF]), "rev-parse") or None


def read_progress(repo: str, tip: Optional[str], path: str) -> dict:
    """Read progress.json at a commit; a missing file is empty progress, an unreadable one is flagged corrupt."""
    if not tip:
        return {}
    proc = git(repo, ["show", f"{tip}:{path}"])
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {"corrupt": True}
    return data if isinstance(data, dict) else {"corrupt": True}


def commit_file(repo: str, parent: Optional[str], path: str, text: str, message: str) -> str:
    """Write a commit whose tree holds exactly one file at path, on top of parent."""
    entry_sha = _ok(git(repo, ["hash-object", "-w", "--stdin"], stdin=text), "hash-object")
    parts = path.split("/")
    entry = f"100644 blob {entry_sha}\t{parts[-1]}\n"
    for name in reversed(parts[:-1]):
        tree = _ok(git(repo, ["mktree"], stdin=entry), "mktree")
        entry = f"040000 tree {tree}\t{name}\n"
    root = _ok(git(repo, ["mktree"], stdin=entry), "mktree")
    args = ["commit-tree", root, "-m", message] + (["-p", parent] if parent else [])
    return _ok(git(repo, args), "commit-tree")


def push(repo: str, commit: str, branch: str) -> str:
    """Push a commit to the state branch without force: ok, rejected (someone else wrote first) or raise."""
    if not branch or branch in ("main", "master"):
        raise GitError(f"refusing to push the state to {branch!r}")
    proc = git(repo, ["push", "--quiet", "origin", f"{commit}:refs/heads/{branch}"])
    if proc.returncode == 0:
        return "ok"
    if any(word in proc.stderr.lower() for word in REJECTED):
        return "rejected"
    raise GitError(f"git push {branch}: {proc.stderr.strip()[:300]}")


def holder_file(repo: str) -> str:
    """Return the path of the cached holder id inside the git common dir."""
    common = _ok(git(repo, ["rev-parse", "--git-common-dir"]), "rev-parse")
    return os.path.join(os.path.realpath(os.path.join(repo, common)), "conductor", "holder")


# ---------------------------------------------------------------- verbs


def beat(repo: str, cfg: dict, holder: str, now: float, updates: dict) -> dict:
    """Renew the lease and merge updates; refuse when another holder owns a lease of at most 2 hours."""
    if not HOLDER_RX.match(holder or ""):
        raise ValueError(f"--holder must match {HOLDER_RX.pattern}")
    for _ in range(PUSH_TRIES):
        tip = fetch_tip(repo, cfg["state_branch"])
        progress = read_progress(repo, tip, cfg["progress_path"])
        decision = decide_lease(progress, holder, now, float(cfg["lease_max_age_s"]))
        if decision["kind"] == "held":
            return {"result": "held", **decision}
        text = json.dumps(apply_beat(progress, holder, now, updates), indent=1, sort_keys=True) + "\n"
        commit = commit_file(repo, tip, cfg["progress_path"], text, f"heartbeat: {holder} ({decision['kind']})")
        if push(repo, commit, cfg["state_branch"]) == "ok":
            return {"result": "ok", "lease": decision["kind"], "holder": holder, "commit": commit}
    raise GitError(f"push to {cfg['state_branch']} rejected {PUSH_TRIES} times")


def status(repo: str, cfg: dict, now: float) -> dict:
    """Return the watchdog verdict, the lease holder and age and the progress document (read-only)."""
    tip = fetch_tip(repo, cfg["state_branch"])
    progress = read_progress(repo, tip, cfg["progress_path"])
    decision = decide_lease(progress, None, now, float(cfg["lease_max_age_s"]))
    return {"watch": watch_verdict(progress, now, float(cfg["lease_max_age_s"])), "lease_holder": decision["holder"],
            "lease_age_s": decision["age_s"], "max_age_s": cfg["lease_max_age_s"], "progress": progress}


def _updates(a: argparse.Namespace) -> dict:
    """Collect the beat updates from the command line."""
    up: dict = {}
    if a.unit_in_flight is not None:
        up["unit_in_flight"] = sorted(set(a.unit_in_flight))
    if a.next_step:
        up["next_step"] = a.next_step[:500]
    if a.note:
        up["note"] = a.note[:2000]
    if a.run:
        up["runs"] = parse_runs(a.run)
    if a.limit_stop:
        up["limit_stop"] = True
    if a.goal_met:
        up["goal_met"] = True
    if a.state_file:
        with open(a.state_file, encoding="utf-8") as handle:
            computed = json.load(handle)
        up["forecast"] = computed.get("forecast")
        up["last_merged"] = computed.get("last_merged")
    return up


def _holder_verb(repo: str, create: bool) -> dict:
    """Create and cache a new holder id, or read the cached one."""
    path = holder_file(repo)
    if create:
        holder = "lead-" + uuid.uuid4().hex[:12]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(holder + "\n")
        return {"holder": holder}
    if not os.path.isfile(path):
        return {"holder": None}
    with open(path, encoding="utf-8") as handle:
        return {"holder": handle.read().strip() or None}


def main(argv: Optional[Sequence[str]] = None, repo: Optional[str] = None, cfg: Optional[dict] = None) -> int:
    """Run one heartbeat verb and print JSON."""
    p = argparse.ArgumentParser(prog="heartbeat.py", description=__doc__.splitlines()[0])
    p.add_argument("--now", type=float, default=None, help="epoch seconds (tests only)")
    sub = p.add_subparsers(dest="verb", required=True)
    sub.add_parser("new-holder")
    sub.add_parser("whoami")
    sub.add_parser("status")
    b = sub.add_parser("beat")
    b.add_argument("--holder", required=True)
    b.add_argument("--unit-in-flight", type=int, action="append")
    b.add_argument("--next-step")
    b.add_argument("--note")
    b.add_argument("--run", action="append")
    b.add_argument("--limit-stop", action="store_true")
    b.add_argument("--goal-met", action="store_true")
    b.add_argument("--state-file")
    a = p.parse_args(argv)
    cfg = cfg or state.load_config()
    repo = repo or os.getcwd()
    now = a.now if a.now is not None else time.time()
    try:
        if a.verb in ("new-holder", "whoami"):
            out = _holder_verb(repo, a.verb == "new-holder")
        elif a.verb == "status":
            out = status(repo, cfg, now)
        else:
            out = beat(repo, cfg, a.holder, now, _updates(a))
    except (GitError, ValueError, OSError) as err:
        sys.stderr.write(f"heartbeat: {err}\n")
        return 1
    sys.stdout.write(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return 3 if out.get("result") == "held" else 0


if __name__ == "__main__":
    sys.exit(main())
