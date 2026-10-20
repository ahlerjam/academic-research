"""In-memory GitHub for the conductor tests: canned GET answers, recorded mutations, the same route allowlist."""

from __future__ import annotations

import base64
import json
import re
from typing import Dict, List, Optional, Tuple

import github

PAGE_RX = re.compile(r"[?&]per_page=\d+&page=(\d+)$")


class FakeGitHub:
    """A fake transport: `set` canned GET answers, `fail` a mutation, read `calls` and `dispatches` afterwards."""

    def __init__(self, repo: str = "ahlerjam/academic-research") -> None:
        """Start with no resources; every unknown GET answers 404."""
        self.repo = repo
        self.answers: Dict[str, object] = {}
        self.failures: Dict[Tuple[str, str], int] = {}
        self.calls: List[Tuple[str, str, Optional[dict]]] = []
        self.dispatches: List[Tuple[str, str, Dict[str, str]]] = []
        self.next_number = 900

    def set(self, path: str, data: object) -> None:
        """Answer GET path (relative to repos/<repo>/, without paging parameters) with data."""
        self.answers[f"repos/{self.repo}/{path}" if path else f"repos/{self.repo}"] = data

    def set_file(self, path: str, ref: str, text: str) -> None:
        """Answer a contents API GET for path at ref with base64 text."""
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self.set(f"contents/{path}?ref={ref}", {"encoding": "base64", "content": encoded})

    def fail(self, method: str, path: str, status: int) -> None:
        """Make one mutation (path relative to repos/<repo>/) answer with an HTTP error."""
        self.failures[(method, f"repos/{self.repo}/{path}")] = status

    def mutations(self) -> List[Tuple[str, str, Optional[dict]]]:
        """Return every non-GET call in order."""
        return [c for c in self.calls if c[0] != "GET"]

    def request(self, method: str, path: str, body: Optional[dict] = None) -> object:
        """Check the route like the real transport, record the call, answer GETs from the canned data."""
        github.check_route(self.repo, method, path)
        self.calls.append((method, path, json.loads(json.dumps(body)) if body is not None else None))
        if method == "GET":
            page = PAGE_RX.search(path)
            key = PAGE_RX.sub("", path)
            if key not in self.answers:
                raise github.GitHubError(404, f"Not Found ({key})")
            data = self.answers[key]
            if page and int(page.group(1)) > 1:
                if isinstance(data, list):
                    return []
                if isinstance(data, dict):
                    return {k: ([] if isinstance(v, list) else v) for k, v in data.items()}
            return json.loads(json.dumps(data))
        if (method, path) in self.failures:
            raise github.GitHubError(self.failures[(method, path)], f"failed {method} {path}")
        self.next_number += 1
        return {"number": self.next_number, "html_url": f"https://github.com/{self.repo}/x/{self.next_number}"}

    def run_workflow(self, workflow: str, ref: str, inputs: Dict[str, str]) -> None:
        """Check the workflow allowlist and record the dispatch."""
        github.check_workflow(workflow, ref)
        self.dispatches.append((workflow, ref, dict(inputs)))
