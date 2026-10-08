"""Resolve the role of a file from gates/roles.json through git pathspecs."""

from __future__ import annotations

import json
import os
import posixpath
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import gitx

ROLE_PRIORITY = ("generated", "test", "wiring", "migration", "adapter", "core", "flow", "api", "ui")
SOURCE_EXTENSIONS = (".py", ".ts", ".kt", ".kts", ".html", ".css", ".scss", ".sql", ".go", ".rs")
ROLE_DIRS = ("core", "flow", "ui", "api")


class Place(NamedTuple):
    """Where a file sits: component id, role, language and feature (or None)."""

    component: str
    role: str
    lang: str
    feature: Optional[str]


def load(tree: str) -> dict:
    """Load gates/roles.json from the checked tree."""
    with open(os.path.join(tree, "gates", "roles.json"), encoding="utf-8") as handle:
        return json.load(handle)


def patterns(cfg: dict, component: str, role: str) -> List[str]:
    """Return repo-relative glob patterns of one role of one component."""
    comp = cfg["components"][component]
    root = comp["root"]
    return [posixpath.normpath(posixpath.join(root, p)) for p in comp["roles"].get(role, [])]


def index(tree: str, cfg: Optional[dict] = None) -> Dict[str, Place]:
    """Map every non-ignored file that has a role to its place."""
    cfg = cfg or load(tree)
    ignored = set(gitx.ls(tree, cfg.get("ignore", [])))
    out: Dict[str, Place] = {}
    for component, comp in cfg["components"].items():
        for role in ROLE_PRIORITY:
            if role not in comp["roles"]:
                continue
            for rel in gitx.ls(tree, patterns(cfg, component, role)):
                if rel in ignored or rel in out:
                    continue
                out[rel] = Place(component, role, comp["lang"], feature_of(cfg, component, rel, role))
    return out


def place_of(tree: str, rel: str, cfg: Optional[dict] = None) -> Optional[Place]:
    """Return the place of one file, or None when no role claims it."""
    cfg = cfg or load(tree)
    if rel in set(gitx.ls(tree, cfg.get("ignore", []))):
        return None
    for component, comp in cfg["components"].items():
        root = comp["root"]
        if root not in (".", "") and not rel.startswith(root.rstrip("/") + "/") and not _outside_root(comp):
            continue
        for role in ROLE_PRIORITY:
            if role in comp["roles"] and rel in set(gitx.ls(tree, patterns(cfg, component, role))):
                return Place(component, role, comp["lang"], feature_of(cfg, component, rel, role))
    return None


def _outside_root(comp: dict) -> bool:
    """Return whether any pattern of the component reaches above its root."""
    return any(p.startswith("..") for globs in comp["roles"].values() for p in globs)


def feature_of(cfg: dict, component: str, rel: str, role: str) -> Optional[str]:
    """Return the feature a file belongs to, or None for adapters, wiring and tests."""
    if role not in ("core", "flow", "api", "ui"):
        return None
    comp = cfg["components"][component]
    root = comp["root"].rstrip("/")
    inner = rel[len(root) + 1:] if root not in (".", "") and rel.startswith(root + "/") else rel
    parts = inner.split("/")
    if comp["lang"] == "python":
        return parts[-2] if len(parts) >= 2 else None
    for i, part in enumerate(parts[:-1]):
        if part in ROLE_DIRS and i > 0:
            return parts[i - 1]
    return None


def component_dir(cfg: dict, component: str) -> str:
    """Return the directory that holds the component's tool installation."""
    return cfg["components"][component].get("dir", ".")


def unmapped_sources(tree: str, cfg: Optional[dict] = None) -> List[str]:
    """Return tracked source files under a component that no role claims (drift D1)."""
    cfg = cfg or load(tree)
    known = index(tree, cfg)
    ignored = set(gitx.ls(tree, cfg.get("ignore", [])))
    roots = {component_dir(cfg, c) for c in cfg["components"]}
    candidates = gitx.ls(tree, [f"{r}/**" if r not in (".", "") else "**" for r in sorted(roots)])
    return [rel for rel in candidates
            if rel.endswith(SOURCE_EXTENSIONS) and rel not in known and rel not in ignored
            and not rel.startswith("gates/")]


def is_unmapped(tree: str, rel: str, cfg: dict) -> bool:
    """Return whether one source file sits under a component but no role claims it (drift D1 for one file)."""
    if not rel.endswith(SOURCE_EXTENSIONS) or rel.startswith("gates/") or component_of_path(cfg, rel) is None:
        return False
    return rel not in set(gitx.ls(tree, cfg.get("ignore", []))) and place_of(tree, rel, cfg) is None


def unmapped_findings(files: List[str]) -> list:
    """Return GATES-ROLES findings for files without a role."""
    from .findings import Finding
    return [Finding(rel, 1, "GATES-ROLES", "source file without a role; the paths per role are in gates/roles.json")
            for rel in files]


def component_of_path(cfg: dict, rel: str) -> Optional[str]:
    """Return the component whose directory holds a path, the longest directory first."""
    dirs = sorted(((component_dir(cfg, c), c) for c in cfg["components"]), key=lambda d: -len(d[0]))
    for base, comp in dirs:
        if base in (".", "") or rel.startswith(base.rstrip("/") + "/"):
            return comp
    return None


def features(tree: str, cfg: Optional[dict] = None) -> Dict[Tuple[str, str], List[str]]:
    """Group feature files by (component, feature)."""
    out: Dict[Tuple[str, str], List[str]] = {}
    for rel, place in index(tree, cfg).items():
        if place.feature:
            out.setdefault((place.component, place.feature), []).append(rel)
    return out
