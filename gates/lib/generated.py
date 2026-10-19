"""Generated code: every file under a 'generated' role starts with its generator's header line."""

from __future__ import annotations

import os
from typing import Dict, List

from . import gitx, roles
from .findings import Finding


def header_violations(tree: str, cfg: dict, rule_by_component: Dict[str, str]) -> List[Finding]:
    """Return one finding per file in a generated directory that lacks the generator header."""
    found: List[Finding] = []
    for component, rule in rule_by_component.items():
        comp = cfg["components"][component]
        header = comp.get("generated_header", "")
        if not header or "generated" not in comp["roles"]:
            continue
        for rel in gitx.ls(tree, roles.patterns(cfg, component, "generated")):
            with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as handle:
                first = next((line.strip() for line in handle if line.strip()), "")
            if first != header:
                found.append(Finding(rel, 1, rule, f"not generator output (first line must be '{header}')"))
    return found
