"""Feature layout: only the allowed files or role directories inside a feature."""

from __future__ import annotations

import fnmatch
import posixpath
from typing import List

from . import gitx
from .findings import Finding


def feature_root(comp: dict) -> str:
    """Return the directory whose subdirectories are features."""
    base = comp.get("feature_base", "")
    return posixpath.normpath(posixpath.join(comp["root"], base)) if base else comp["root"]


def violations(tree: str, cfg: dict, rule_by_component: dict) -> List[Finding]:
    """Return one finding per file that breaks the feature layout of its component."""
    found: List[Finding] = []
    for component, rule in rule_by_component.items():
        comp = cfg["components"][component]
        layout = comp.get("feature_layout")
        if not layout:
            continue
        root = feature_root(comp)
        skip = set(comp.get("non_feature", ["adapters"]))
        ignored = set(gitx.ls(tree, cfg.get("ignore", [])))
        for rel in gitx.ls(tree, [f"{root}/*/**"]):
            if rel in ignored:
                continue
            inner = rel[len(root) + 1:].split("/")
            if inner[0] in skip or len(inner) < 2:
                continue
            if "files" in layout and (len(inner) != 2 or not any(fnmatch.fnmatchcase(inner[1], p) for p in layout["files"])):
                found.append(Finding(rel, 1, rule, f"unexpected file in feature '{inner[0]}' "
                                     f"(allowed: {', '.join(layout['files'])})"))
            if "dirs" in layout and (len(inner) < 3 or inner[1] not in layout["dirs"]):
                found.append(Finding(rel, 1, rule, f"file outside a role directory of feature '{inner[0]}' "
                                     f"(allowed: {', '.join(layout['dirs'])})"))
    return found
