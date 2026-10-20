"""Ratchet guard: agents may add gates, never weaken them (compared with origin's default branch)."""

from __future__ import annotations

import json
import os
import posixpath
import re
from typing import Callable, Dict, List, Optional

from . import gitx, manifest, roles
from .findings import Finding

RULE = "GATES-RATCHET"
ROLES = "gates/roles.json"
DISPATCH = "gates/dispatch.json"
TEMPLATE = "gates/templates/package-tsconfig.json"
PROOF_DIR = "packages/web/e2e/proof"
ADD_ONLY = (PROOF_DIR, "docs/review/lenses")
EXPECT = re.compile(r"\bexpect\b(?:\.\w+)*\s*\(")
PACKAGE_TSCONFIG = re.compile(r"packages/[^/]+/tsconfig\.json")
ROLES_GROWING = ("ignore", "components", "budgets", "shared_fingerprint")
COMPONENT_KEYS = ("lang", "dir", "root", "roles")
DEFAULT_NON_FEATURE = ["adapters"]


def violations(tree: str) -> List[Finding]:
    """Return weakening changes on ratchet paths against the baseline branch."""
    cfg = manifest.controls(tree)
    if not cfg.get("ratchet"):
        return []
    ref = gitx.base_ref(tree) or ("HEAD" if gitx.head(tree) else None)
    if ref is None:
        return []
    found: List[Finding] = []
    base = gitx.run(["git", "ls-tree", "-r", "--name-only", ref, "--", "gates/rules", "gates/rule-tests",
                     "gates/fixtures"], cwd=tree).stdout.split()
    for rel in base:
        old = gitx.show(tree, ref, rel)
        path = os.path.join(tree, rel)
        if not os.path.isfile(path):
            found.append(Finding(rel, 1, RULE, f"deleted against {ref}; gates may only grow"))
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            new = handle.read()
        if rel.startswith("gates/rule-tests/"):
            lost = [line for line in (old or "").splitlines() if line.strip() and line not in new.splitlines()]
            if lost:
                found.append(Finding(rel, 1, RULE, f"{len(lost)} test lines removed"))
        elif old != new:
            found.append(Finding(rel, 1, RULE, f"changed against {ref}; add a new rule instead"))
    old_cat = gitx.show(tree, ref, "gates/catalog.json")
    if old_cat:
        with open(os.path.join(tree, "gates", "catalog.json"), encoding="utf-8") as handle:
            now = {e["id"]: e for e in json.load(handle)}
        for entry in json.loads(old_cat):
            if now.get(entry["id"]) != entry:
                found.append(Finding("gates/catalog.json", 1, RULE, f"{entry['id']} removed or changed"))
    found += _ordered(tree, ref, ROLES, lambda old, new: roles_order(tree, old, new))
    found += _ordered(tree, ref, DISPATCH, dispatch_order)
    return found + add_only(tree, ref) + tsconfigs(tree, ref)


def _parse(text: Optional[str]) -> Optional[dict]:
    """Return a JSON object, or None for a missing or unparsable text."""
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _read(tree: str, rel: str) -> Optional[str]:
    """Return the text of a work tree file, or None when it does not exist."""
    path = os.path.join(tree, rel)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _ordered(tree: str, ref: str, rel: str, order: Callable[[dict, dict], List[str]]) -> List[Finding]:
    """Compare a ratchet JSON file with its base version through a partial-order function."""
    old = _parse(gitx.show(tree, ref, rel))
    if old is None:
        return []
    new = _parse(_read(tree, rel))
    if new is None:
        return [Finding(rel, 1, RULE, f"missing or not a JSON object; the version on {ref} only grows")]
    return [Finding(rel, 1, RULE, f"{why}; only additions are allowed against {ref}") for why in order(old, new)]


def roles_order(tree: str, old: dict, new: dict) -> List[str]:
    """Return why new roles.json is no ratchet step: new components, roles and globs pass; nothing existing moves."""
    out = [f"top-level key '{k}' added" for k in new if k not in old]
    out += [f"'{k}' changed" for k in old if k not in ROLES_GROWING and new.get(k) != old[k]]
    out += [f"ignore gained '{g}'" for g in new.get("ignore", []) if g not in old.get("ignore", [])]
    out += [f"shared_fingerprint lost '{g}'" for g in old.get("shared_fingerprint", [])
            if g not in new.get("shared_fingerprint", [])]
    out += _budgets(old.get("budgets", {}), new.get("budgets", {}))
    old_comps, new_comps = old.get("components", {}), new.get("components", {})
    for name, comp in old_comps.items():
        out += _kept_component(name, comp, new_comps.get(name))
    for name, comp in new_comps.items():
        out += [] if name in old_comps else _new_component(name, comp, old_comps)
        out += _new_globs(name, comp, old_comps.get(name, {}).get("roles", {}))
    if out:
        return out
    before = roles.index(tree, old)
    out += _non_feature(tree, old_comps, new_comps, before)
    after = roles.index(tree, new)
    moved = [rel for rel in sorted(before) if rel not in after or after[rel][:2] != before[rel][:2]]
    return out + [f"{rel} moves from {'/'.join(before[rel][:2])} to "
                  f"{'/'.join(after[rel][:2]) if rel in after else 'no role'}" for rel in moved]


def _budgets(old: Dict[str, dict], new: Dict[str, dict]) -> List[str]:
    """Return every existing budget that grew or vanished; new budgets pass."""
    out = []
    for role, limits in old.items():
        for key, limit in limits.items():
            now = new.get(role, {}).get(key)
            if not isinstance(now, int) or isinstance(now, bool) or now > limit:
                out.append(f"budget {role}.{key} {limit} -> {now}")
    return out


def _kept_component(name: str, comp: dict, now: Optional[dict]) -> List[str]:
    """Return what changed in an existing component: keys byte-identical, role globs only added."""
    if now is None:
        return [f"component '{name}' removed"]
    out = [f"component '{name}' key '{k}' changed" for k in sorted(set(comp) | set(now))
           if k not in ("roles", "non_feature") and comp.get(k) != now.get(k)]
    out += [f"component '{name}' non_feature lost '{d}'" for d in comp.get("non_feature", DEFAULT_NON_FEATURE)
            if d not in now.get("non_feature", DEFAULT_NON_FEATURE)]
    new_roles = now.get("roles", {})
    return out + [f"component '{name}' role '{role}' lost '{g}'" for role, globs in comp["roles"].items()
                  for g in globs if g not in new_roles.get(role, [])]


def _new_component(name: str, comp: object, old: Dict[str, dict]) -> List[str]:
    """Return why a new component is malformed or overlaps the directory of an existing one."""
    if not isinstance(comp, dict) or any(k not in comp for k in COMPONENT_KEYS) or not isinstance(comp["roles"], dict):
        return [f"new component '{name}' needs {', '.join(COMPONENT_KEYS)}"]
    mine = posixpath.normpath(comp["dir"])
    out = [f"new component '{name}' needs its own directory, not '.'"] if mine in (".", "") else []
    for other, data in old.items():
        theirs = posixpath.normpath(data.get("dir", "."))
        if theirs in (".", "", mine) or mine.startswith(theirs + "/") or theirs.startswith(mine + "/"):
            out.append(f"new component '{name}' dir '{mine}' overlaps component '{other}'")
    return out


def _new_globs(name: str, comp: object, old_roles: Dict[str, list]) -> List[str]:
    """Return new globs that claim generated code or reach outside their component directory."""
    if not isinstance(comp, dict) or not isinstance(comp.get("roles"), dict):
        return []
    home = posixpath.normpath(comp.get("dir", "."))
    out = []
    for role, globs in comp["roles"].items():
        for glob in globs:
            if glob in old_roles.get(role, []):
                continue
            full = posixpath.normpath(posixpath.join(comp.get("root", "."), glob))
            if role == "generated":
                out.append(f"component '{name}' new glob '{glob}' for role 'generated'; operator only")
            elif home in (".", "") or not full.startswith(home + "/"):
                out.append(f"component '{name}' new glob '{glob}' reaches outside '{home}'")
    return out


def _non_feature(tree: str, old: Dict[str, dict], new: Dict[str, dict], before: Dict[str, roles.Place]) -> List[str]:
    """Return non_feature names added for a directory that already holds files or that no new glob claims."""
    out = []
    for name, comp in old.items():
        now = new[name]
        root = posixpath.normpath(comp["root"])
        for added in now.get("non_feature", DEFAULT_NON_FEATURE):
            if added in comp.get("non_feature", DEFAULT_NON_FEATURE):
                continue
            if any(rel in before for rel in gitx.ls(tree, [f"{root}/{added}/**"])):
                out.append(f"component '{name}' non_feature gained '{added}', which already holds mapped files")
            elif not any(g.startswith(added + "/") for globs in now["roles"].values() for g in globs):
                out.append(f"component '{name}' non_feature gained '{added}' without a role glob '{added}/...'")
    return out


def dispatch_order(old: dict, new: dict) -> List[str]:
    """Return why new dispatch.json is no ratchet step: entries may only be appended; mode only to strict."""
    out = [f"top-level key '{k}' added" for k in new if k not in old]
    out += [f"'{k}' changed" for k in old if k not in ("mode", "entries") and new.get(k) != old[k]]
    if new.get("mode", "strict") not in (old.get("mode", "strict"), "strict"):
        out.append(f"mode '{old.get('mode', 'strict')}' -> '{new.get('mode')}'")
    kept, entries = old.get("entries", []), new.get("entries", [])
    if not isinstance(entries, list) or entries[:len(kept)] != kept:
        return out + ["existing entries changed, removed or reordered; append new entries at the end"]
    return out + [f"new entry {i + 1} needs a string 'glob' and 'tier'" for i, e in enumerate(entries)
                  if i >= len(kept) and not (isinstance(e, dict) and isinstance(e.get("glob"), str)
                                             and isinstance(e.get("tier"), str))]


def _kept_lines(old: str, new: str) -> bool:
    """Return whether every non-blank old line survives in the new text, in its order."""
    lines = iter(new.splitlines())
    return all(line in lines for line in old.splitlines() if line.strip())


def add_only(tree: str, ref: str) -> List[Finding]:
    """Proof specs and review lenses only gain lines; every proof file holds at least one expect call."""
    found = []
    listed = gitx.run(["git", "ls-tree", "-r", "--name-only", ref, "--"] + list(ADD_ONLY), cwd=tree).stdout.split()
    for rel in listed:
        new = _read(tree, rel)
        if new is None:
            found.append(Finding(rel, 1, RULE, f"deleted against {ref}; this path only grows"))
        elif not _kept_lines(gitx.show(tree, ref, rel) or "", new):
            found.append(Finding(rel, 1, RULE, f"lines removed or changed against {ref}; only add lines"))
    for rel in gitx.ls(tree, [f"{PROOF_DIR}/**"]):
        if not EXPECT.search(_read(tree, rel) or ""):
            found.append(Finding(rel, 1, RULE, "proof file without an expect call"))
    return found


def _without_include(data: dict) -> dict:
    """Return a tsconfig object without its free 'include' key."""
    return {k: v for k, v in data.items() if k != "include"}


def tsconfigs(tree: str, ref: str) -> List[Finding]:
    """A new package tsconfig equals the template, a changed one its base version, both except 'include'."""
    found = []
    for rel in gitx.ls(tree, ["packages/**/tsconfig*.json", "packages/**/jsconfig*.json"]):
        old, text = gitx.show(tree, ref, rel), _read(tree, rel)
        if old == text:
            continue
        if not PACKAGE_TSCONFIG.fullmatch(rel):
            found.append(Finding(rel, 1, RULE, "only packages/<name>/tsconfig.json may configure TypeScript"))
            continue
        want = _parse(old) if old is not None else _parse(_read(tree, TEMPLATE))
        now = _parse(text)
        source = f"its version on {ref}" if old is not None else TEMPLATE
        if want is None or now is None:
            found.append(Finding(rel, 1, RULE, f"cannot compare as plain JSON with {source}"))
        elif _without_include(now) != _without_include(want):
            found.append(Finding(rel, 1, RULE, f"differs from {source} outside 'include'"))
    return found
