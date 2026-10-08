"""The message contract: path:line [RULE-ID] what, then Why and Fix from the catalog."""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, NamedTuple, Optional

MAX_FINDINGS = 15
MAX_CHARS = 6000


class Finding(NamedTuple):
    """One rule violation or infrastructure failure at a place in the tree."""

    path: str
    line: int
    rule: str
    what: str


def adr_ref(entry: dict) -> str:
    """Return ' (ADR-NNNN)' for an entry with an ADR, else an empty string."""
    adr = entry.get("adr")
    return f" (ADR-{int(adr):04d})" if adr else ""


def render(findings: List[Finding], catalog: Dict[str, dict], log_rel: str,
           first_path: Optional[str] = None, footer: str = "") -> str:
    """Render findings by the message contract, capped in count and characters."""
    ordered = sorted(findings, key=lambda f: (f.path != first_path, f.path, f.line, f.rule))
    files = len({f.path for f in ordered})
    head = (f"gates: {len(ordered)} finding{'s' if len(ordered) != 1 else ''} in {files} "
            f"file{'s' if files != 1 else ''}{' (edited file first)' if first_path else ''}. "
            f"Full log: {log_rel}")
    lines = [head]
    seen = set()
    shown = 0
    for finding in ordered:
        block = [f"{finding.path}:{finding.line} [{finding.rule}] {finding.what}"]
        entry = catalog.get(finding.rule, {})
        if entry.get("why") and finding.rule not in seen:
            block.append(f"  Why: {entry['why']}{adr_ref(entry)}.")
        if entry.get("fix"):
            example = f"; see {entry['example']}" if entry.get("example") else ""
            block.append(f"  Fix: {entry['fix']}{example}")
        seen.add(finding.rule)
        candidate = "\n".join(lines + block)
        if shown >= MAX_FINDINGS or len(candidate) > MAX_CHARS - 200:
            break
        lines.extend(block)
        shown += 1
    if shown < len(ordered):
        lines.append(f"{len(ordered) - shown} more, see {log_rel}")
    if footer:
        lines.append(footer)
    return "\n".join(lines)


def write_log(state_dir: str, name: str, findings: Iterable[Finding], extra: str = "") -> str:
    """Write every finding to the event log and return its absolute path."""
    logs = os.path.join(state_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    path = os.path.join(logs, f"{name}.log")
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(f"{f.path}:{f.line} [{f.rule}] {f.what}\n" for f in findings)
        handle.write(extra)
    return path
