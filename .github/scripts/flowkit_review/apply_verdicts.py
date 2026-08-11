"""Drop verifier-refuted findings from the merged set.

The adversarial verifier job re-examines each merged P0/P1 finding against the
diff and marks it ``confirmed`` or ``refuted``. This module removes the
refuted ones before the gate runs.

Matching a verdict to a finding: the verifier's ``--json-schema`` (see
``pr-deep-review.yml``) only requires ``title`` and ``verdict`` — ``file`` and
``line`` are both optional AND nullable
(``{"type": ["string", "null"]}`` / ``{"type": ["integer", "null"]}``). A
schema-conformant verdict for a merged finding can therefore arrive as
``{"title": "...", "verdict": "refuted"}`` with no ``file``/``line`` at all.
Joining strictly on ``(file, line, title)`` — the key ``merge.py`` dedups
on — would silently fail to match such a verdict and leave the finding in
place with no indication anything went wrong.

Matching here is title-first: ``title`` must match; ``file``/``line`` are
only compared when the verdict actually supplies them (non-``None``). A
verdict is dropped against a finding only when exactly one finding matches —
0 matches (unmatched) or >1 matches (ambiguous) are never dropped, since
guessing risks silently removing the wrong finding. Both cases are surfaced
via :func:`unresolved_verdicts` so the caller can log them loudly instead of
a silent no-op.

Conservative by design: a missing, empty, or malformed verdict set removes
nothing (the pipeline then behaves exactly as if no verifier ran). Only an
explicit ``"refuted"`` verdict drops a finding; ``confirmed`` and unseen
findings are always kept.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _matches(finding: dict[str, Any], verdict: dict[str, Any]) -> bool:
    """True if ``finding`` is the one ``verdict`` refers to.

    ``title`` is always required. ``file``/``line`` are only checked when the
    verdict provides them (not ``None``) — a verdict that omits them (either
    by leaving the key out or by sending JSON ``null``, both schema-legal)
    matches on title alone.
    """
    if finding.get("title") != verdict.get("title"):
        return False
    v_file = verdict.get("file")
    if v_file is not None and finding.get("file") != v_file:
        return False
    v_line = verdict.get("line")
    if v_line is not None and finding.get("line") != v_line:
        return False
    return True


def _refuted_verdicts(verdicts: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        v
        for v in verdicts.get("verdicts", [])
        if isinstance(v, dict) and v.get("verdict") == "refuted" and "title" in v
    ]


def _resolve(
    findings: dict[str, Any], verdicts: dict[str, Any]
) -> tuple[set[int], list[dict[str, Any]]]:
    """Resolve each refuted verdict against ``findings``.

    Returns the set of finding-list indices to drop (each refuted verdict
    that matched exactly one finding) plus the list of verdicts that could
    NOT be safely resolved (0 or >1 matches), each annotated with
    ``_match_count``.
    """
    all_findings = findings.get("findings", [])
    drop_indices: set[int] = set()
    unresolved: list[dict[str, Any]] = []
    for v in _refuted_verdicts(verdicts):
        candidates = [i for i, f in enumerate(all_findings) if _matches(f, v)]
        if len(candidates) == 1:
            drop_indices.add(candidates[0])
        else:
            unresolved.append({**v, "_match_count": len(candidates)})
    return drop_indices, unresolved


def apply_verdicts(findings: dict[str, Any], verdicts: dict[str, Any]) -> dict[str, Any]:
    """Return ``findings`` with verifier-refuted entries removed.

    Only unambiguous matches (exactly one finding matched) are dropped. Use
    :func:`unresolved_verdicts` to inspect refuted verdicts that could not be
    safely applied.
    """
    all_findings = findings.get("findings", [])
    drop_indices, _ = _resolve(findings, verdicts)
    kept = [f for i, f in enumerate(all_findings) if i not in drop_indices]
    return {"findings": kept}


def unresolved_verdicts(findings: dict[str, Any], verdicts: dict[str, Any]) -> list[dict[str, Any]]:
    """Refuted verdicts that could not be matched to exactly one finding.

    Each returned item is the original verdict dict plus ``_match_count``
    (``0`` = no match, ``>=2`` = ambiguous). Empty when every refuted verdict
    resolved cleanly.
    """
    _, unresolved = _resolve(findings, verdicts)
    return unresolved


def _load_required(path: Path) -> dict[str, Any]:
    """Load findings — must be valid; a bad file is a hard error (no silent pass)."""
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _load_optional(path: Path) -> dict[str, Any]:
    """Load verdicts — missing/garbled is fine and means 'verify nothing'."""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Drop verifier-refuted findings.")
    parser.add_argument("--findings", type=Path, required=True)
    parser.add_argument("--verdicts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    findings = _load_required(args.findings)
    verdicts = _load_optional(args.verdicts)
    result = apply_verdicts(findings, verdicts)
    dropped = len(findings.get("findings", [])) - len(result["findings"])
    args.output.write_text(json.dumps(result, indent=2))
    sys.stderr.write(f"apply_verdicts: dropped {dropped} refuted finding(s)\n")

    unresolved = unresolved_verdicts(findings, verdicts)
    if unresolved:
        no_match = sum(1 for v in unresolved if v["_match_count"] == 0)
        ambiguous = sum(1 for v in unresolved if v["_match_count"] > 1)
        titles = "; ".join(sorted({str(v.get("title", "?")) for v in unresolved}))
        sys.stderr.write(
            f"::warning::apply_verdicts: {len(unresolved)} verdict(s) could not be matched to "
            f"exactly one finding ({no_match} no match, {ambiguous} ambiguous) — refuted "
            f"finding(s) may still be blocking the gate. Titles: {titles}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
