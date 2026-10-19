"""Features never import each other; adapters never import a feature."""

from __future__ import annotations

import os
import posixpath
import re
from typing import List, Optional

from . import gitx
from .findings import Finding
from .layout import feature_root

PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
TS_IMPORT = re.compile(r"""(?:^|\n)\s*(?:import|export)\b[^'"]*?from\s*['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)""")
KT_IMPORT = re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE)


def _features(tree: str, root: str, skip: set) -> set:
    """Return the names of the feature directories under root."""
    return {rel[len(root) + 1:].split("/")[0] for rel in gitx.ls(tree, [f"{root}/*/**"])} - skip


def _target(lang: str, rel: str, spec: str, root: str, comp: dict) -> Optional[str]:
    """Return the first directory under the feature root that an import points to."""
    if lang == "typescript":
        if not spec.startswith("."):
            return None
        path = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
        return path[len(root) + 1:].split("/")[0] if path.startswith(root + "/") else None
    if lang == "python":
        package = comp.get("package", posixpath.basename(comp["root"]))
        parts = spec.split(".")
        return parts[1] if len(parts) > 1 and parts[0] == package else None
    base = comp.get("package", "").split(".")
    parts = spec.split(".")
    return parts[len(base)] if base and parts[:len(base)] == base and len(parts) > len(base) else None


def violations(tree: str, cfg: dict, rules: dict) -> List[Finding]:
    """Return cross-feature and adapter-to-feature imports; rules maps component to {'cross','adapter'} ids."""
    found: List[Finding] = []
    for component, ids in rules.items():
        comp = cfg["components"][component]
        lang = comp["lang"]
        root = feature_root(comp)
        skip = set(comp.get("non_feature", ["adapters"]))
        names = _features(tree, root, skip)
        regex = {"python": PY_IMPORT, "typescript": TS_IMPORT, "kotlin": KT_IMPORT}.get(lang)
        if regex is None:
            continue
        for rel in gitx.ls(tree, [f"{root}/**"]):
            if not rel.endswith((".py", ".ts", ".kt")) or rel.endswith(".spec.ts"):
                continue
            own = rel[len(root) + 1:].split("/")[0]
            in_adapter = own == "adapters"
            if own not in names and not in_adapter:
                continue
            with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            for match in regex.finditer(text):
                spec = next(g for g in match.groups() if g)
                target = _target(lang, rel, spec, root, comp)
                if target not in names or target == own:
                    continue
                line = text.count("\n", 0, match.start(0) + (1 if text[match.start(0)] == "\n" else 0)) + 1
                if in_adapter and ids.get("adapter"):
                    found.append(Finding(rel, line, ids["adapter"], f"adapter imports feature '{target}'"))
                elif not in_adapter and ids.get("cross"):
                    found.append(Finding(rel, line, ids["cross"], f"feature '{own}' imports feature '{target}'"))
    return found
