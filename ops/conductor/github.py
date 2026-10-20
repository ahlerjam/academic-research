"""GitHub transport of the cloud lead kit: REST through `gh api`, one route allowlist for every caller.

In Claude Code cloud sessions GraphQL is blocked (`gh pr`, `gh issue` answer HTTP 403); REST through `gh api`
and REST subcommands such as `gh workflow run` work (measured 2026-10-20). Every request passes `check_route`
first, so neither `state.py` nor `gh_ops.py` can reach a merge, ruleset, branch-protection, contents-write,
ref or workflow-file endpoint, whatever its arguments say.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Dict, List, Optional, Protocol, Tuple

PER_PAGE = 100
MAX_PAGES = 30
WORKFLOWS = ("release.yml", "proof.yml")


class GitHubError(Exception):
    """A failed GitHub call: HTTP status (0 when unknown) and the error text."""

    def __init__(self, status: int, text: str) -> None:
        """Keep the status and a short error text."""
        super().__init__(f"HTTP {status}: {text}")
        self.status = status
        self.text = text


class RouteRefused(Exception):
    """A request outside the allowlist; raised before anything leaves the process."""


class Transport(Protocol):
    """What state.py and gh_ops.py need from GitHub; GhTransport and the fake both provide it."""

    repo: str

    def request(self, method: str, path: str, body: Optional[dict] = None) -> object:
        """Send one REST request and return the parsed JSON."""

    def run_workflow(self, workflow: str, ref: str, inputs: Dict[str, str]) -> None:
        """Dispatch one workflow run."""


def _mutations(repo: str) -> List[Tuple[str, "re.Pattern[str]"]]:
    """Return the only (method, path) pairs that may change anything on GitHub."""
    base = "repos/" + re.escape(repo)
    num = "[1-9][0-9]*"
    return [
        ("POST", re.compile(f"^{base}/pulls$")),
        ("PUT", re.compile(f"^{base}/pulls/{num}/ccr/auto_merge$")),
        ("POST", re.compile(f"^{base}/issues/{num}/labels$")),
        ("DELETE", re.compile(f"^{base}/issues/{num}/labels/[^/?#]+$")),
        ("POST", re.compile(f"^{base}/issues/{num}/comments$")),
        ("POST", re.compile(f"^{base}/issues$")),
        ("PATCH", re.compile(f"^{base}/issues/{num}$")),
        ("POST", re.compile(f"^{base}/labels$")),
        ("POST", re.compile(f"^{base}/actions/runs/{num}/rerun-failed-jobs$")),
    ]


def check_route(repo: str, method: str, path: str) -> None:
    """Raise RouteRefused unless the request is a read of this repo or one of the allowed mutations."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise RouteRefused(f"invalid repository {repo!r}")
    if ".." in path or "//" in path or path.startswith("/") or any(c.isspace() for c in path):
        raise RouteRefused(f"invalid path {path!r}")
    if method == "GET":
        if path == f"repos/{repo}" or path.startswith(f"repos/{repo}/"):
            return
        raise RouteRefused(f"GET outside repos/{repo}: {path}")
    if "?" in path:
        raise RouteRefused(f"query string on a mutation: {path}")
    if any(method == m and rx.match(path) for m, rx in _mutations(repo)):
        return
    raise RouteRefused(f"{method} {path} is not an allowed mutation")


def check_workflow(workflow: str, ref: str) -> None:
    """Raise RouteRefused unless the dispatch targets release.yml or proof.yml on main."""
    if workflow not in WORKFLOWS or ref != "main":
        raise RouteRefused(f"workflow dispatch {workflow}@{ref} is not allowed")


def _status_of(text: str) -> int:
    """Return the HTTP status that `gh api` names in its error output, or 0."""
    found = re.findall(r"HTTP (\d{3})", text or "")
    return int(found[-1]) if found else 0


class GhTransport:
    """Real transport: `gh api` for REST and `gh workflow run` for dispatches, both through the allowlist."""

    def __init__(self, repo: str, timeout: float = 60.0) -> None:
        """Bind the transport to one repository."""
        self.repo = repo
        self.timeout = timeout

    def request(self, method: str, path: str, body: Optional[dict] = None) -> object:
        """Send one REST request and return the parsed JSON (None for an empty answer); errors raise GitHubError."""
        check_route(self.repo, method, path)
        argv = ["gh", "api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
        payload = None
        if body is not None:
            argv += ["--input", "-"]
            payload = json.dumps(body)
        proc = subprocess.run(argv, input=payload, capture_output=True, text=True, timeout=self.timeout)
        if proc.returncode != 0:
            text = (proc.stderr.strip() + " " + proc.stdout.strip()).strip()
            raise GitHubError(_status_of(text), text[:500])
        out = proc.stdout.strip()
        return json.loads(out) if out else None

    def run_workflow(self, workflow: str, ref: str, inputs: Dict[str, str]) -> None:
        """Dispatch a workflow with `gh workflow run` after the workflow allowlist."""
        check_workflow(workflow, ref)
        argv = ["gh", "workflow", "run", workflow, "--repo", self.repo, "--ref", ref]
        for key in sorted(inputs):
            argv += ["-f", f"{key}={inputs[key]}"]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout)
        if proc.returncode != 0:
            text = (proc.stderr.strip() + " " + proc.stdout.strip()).strip()
            raise GitHubError(_status_of(text), text[:500])


def get(transport: Transport, path: str) -> object:
    """GET one resource; a 404 returns None, every other error raises."""
    try:
        return transport.request("GET", path)
    except GitHubError as err:
        if err.status == 404:
            return None
        raise


def get_all(transport: Transport, path: str, key: Optional[str] = None) -> List[dict]:
    """GET every page of a list endpoint (100 per page); `key` names the list inside an object answer."""
    sep = "&" if "?" in path else "?"
    out: List[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = transport.request("GET", f"{path}{sep}per_page={PER_PAGE}&page={page}")
        rows = data.get(key, []) if (key and isinstance(data, dict)) else data
        if not isinstance(rows, list):
            raise GitHubError(0, f"unexpected answer for {path}")
        out += [r for r in rows if isinstance(r, dict)]
        if len(rows) < PER_PAGE:
            return out
    raise GitHubError(0, f"more than {MAX_PAGES} pages for {path}")
