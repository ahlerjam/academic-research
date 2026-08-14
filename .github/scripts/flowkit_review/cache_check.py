"""Decide whether the LLM review can be skipped for this run (review cache).

Every merge makes the gate update the remaining open PR branches
(``git merge origin/main`` + push) — a ``synchronize`` event that re-triggers
the full deep review although the PR's diff against its merge base is
byte-identical when main touched disjoint files. This module compares the
sha256 of the current diff with the ``diffHash`` stored in the previous
sticky comment's embedded JSON. On a hit the stored findings are re-emitted
so the gate re-applies the SAME verdict without spending a single model
token.

The caller MUST pass the full, untruncated diff here — not the ~200KB-bounded
copy handed to the LLM reviewers for their context budget (see
``pr-deep-review.yml``'s "Bounded diff + sanitize" step). Hashing the bounded
copy made this cache blind to any change past the 200KB mark: large eval/
fixture files routinely fill the first 200KB of a diff by themselves, so a
follow-up commit touching only files past that point looked byte-identical
to the cache even though the PR head had moved (#817).

Conservative by design — any anomaly is a MISS (full review runs):
missing comment, missing/mismatched hash, malformed JSON, findings that
would crash the gate (missing ``severity``), and cached ``ci-failure``
placeholders (see below). Fail-open goes toward a full review, never toward
green-without-review. Note that a base update touching the same files as the
PR changes the diff's context lines, so the hash differs and a real re-review
runs — exactly when it is warranted.

The ``ci-failure`` case is what made five PRs unmergeable at once (run
``wf_9e31f7a1-4fb``): when a reviewer job is cancelled, ``pr-deep-review.yml``
writes a P1 placeholder saying the reviewer produced no output. Caching that
placeholder is self-sealing — the hit skips the reviewer jobs, the gate
re-applies the phantom P1, and since the diff stays byte-identical a re-run
never clears it. Only a human forcing ``override-claude-review`` could break
the loop. Such a placeholder is therefore always a MISS.

Output (stdout, ``$GITHUB_OUTPUT`` format)::

    cache_hit=true|false
    diff_hash=<sha256 of the full (untruncated) diff>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

JSON_MARKER_OPEN = "<!-- flowkit-review-json:v1"
JSON_MARKER_CLOSE = "-->"

# Kategorie des Platzhalter-Findings, das ``pr-deep-review.yml`` schreibt, wenn
# ein Reviewer-Job kein Artifact hinterlaesst (``result=cancelled``/``failure``).
# Es ist KEIN Urteil ueber den Diff, sondern eine Aussage ueber einen kaputten
# Lauf — und darf deshalb nie aus dem Cache wiederkehren (siehe ``check``).
CI_FAILURE_CATEGORY = "ci-failure"


def extract_payload(previous_body: str) -> dict[str, Any]:
    """Parse the embedded JSON payload from a sticky comment; {} on any problem."""
    start_idx = previous_body.find(JSON_MARKER_OPEN)
    if start_idx < 0:
        return {}
    start = start_idx + len(JSON_MARKER_OPEN)
    end = previous_body.rfind(JSON_MARKER_CLOSE)
    if end <= start:
        return {}
    try:
        prev = json.loads(previous_body[start:end].strip())
    except json.JSONDecodeError:
        return {}
    return prev if isinstance(prev, dict) else {}


def check(diff_path: Path, previous_path: Path) -> tuple[bool, str, dict[str, Any]]:
    """Return (cache_hit, current_diff_hash, cached_payload)."""
    diff_hash = hashlib.sha256(diff_path.read_bytes()).hexdigest()

    try:
        previous_body = previous_path.read_text()
    except OSError:
        return (False, diff_hash, {})

    payload = extract_payload(previous_body)
    if payload.get("diffHash") != diff_hash:
        return (False, diff_hash, {})

    findings = payload.get("findings")
    if not isinstance(findings, list) or any(
        not isinstance(f, dict) or "severity" not in f for f in findings
    ):
        return (False, diff_hash, {})

    # Ein Platzhalter aus einem abgebrochenen Reviewer-Job ist kein Befund ueber
    # den Diff — er sagt nur, dass niemand geurteilt hat. Waere er cachefaehig,
    # bliebe der PR dauerhaft blockiert: der Treffer ueberspringt die
    # Reviewer-Jobs, das Gate wendet das Phantom-P1 erneut an, und weil der Diff
    # byte-identisch ist, aendert auch ein Re-Run daran nichts. MISS heisst hier
    # "einmal richtig reviewen" und deckt sich mit der Fail-open-Regel oben.
    if any(f.get("category") == CI_FAILURE_CATEGORY for f in findings):
        return (False, diff_hash, {})

    return (True, diff_hash, payload)


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Review-cache check on the full PR diff.")
    parser.add_argument(
        "--diff",
        type=Path,
        required=True,
        help="Full, untruncated diff (NOT the ~200KB-bounded copy sent to reviewers).",
    )
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument(
        "--findings-out",
        type=Path,
        required=True,
        help="Where to write the cached payload on a hit (untouched on a miss).",
    )
    args = parser.parse_args()

    hit, diff_hash, payload = check(args.diff, args.previous)
    if hit:
        args.findings_out.write_text(json.dumps(payload, indent=2))
        sys.stderr.write(
            "cache_check: HIT — LLM review will be skipped, gate re-applies stored findings\n"
        )
    else:
        sys.stderr.write("cache_check: miss — full review runs\n")
    print(f"cache_hit={'true' if hit else 'false'}")
    print(f"diff_hash={diff_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
