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
OPEN_ROLES = ("core", "flow", "api", "ui")
FILE_ROLES = ("adapter", "wiring")
EDGE_ROLES = ("test", "migration")
WILDCARDS = "*?["
COMMENTS = re.compile(r"/\*.*?\*/|(?<![:\\])//[^\n]*", re.S)


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
    """Return why a new component is malformed, overlaps an existing one or leaves its sources without a strict role."""
    if not isinstance(comp, dict) or any(k not in comp for k in COMPONENT_KEYS) or not isinstance(comp["roles"], dict):
        return [f"new component '{name}' needs {', '.join(COMPONENT_KEYS)}"]
    mine = posixpath.normpath(comp["dir"])
    out = [f"new component '{name}' needs its own directory, not '.'"] if mine in (".", "") else []
    for other, data in old.items():
        theirs = posixpath.normpath(data.get("dir", "."))
        if theirs in (".", "", mine) or mine.startswith(theirs + "/") or theirs.startswith(mine + "/"):
            out.append(f"new component '{name}' dir '{mine}' overlaps component '{other}'")
    if not any(str(g).startswith("**/") for role in OPEN_ROLES for g in comp["roles"].get(role, [])):
        out.append(f"new component '{name}' needs a role {', '.join(OPEN_ROLES)} with a '**/' glob over its sources")
    return out


def _glob_rx(glob: str) -> "re.Pattern[str]":
    """Compile a role glob relative to the component root: '**/' spans directories, '*' and '?' stop at '/'."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:[^/]*/)*", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + "$")


def _new_globs(name: str, comp: object, old_roles: Dict[str, list]) -> List[str]:
    """Return new globs that claim generated code, reach outside the component or give future files a laxer role.

    Role priority (gates/lib/roles.py) puts test, wiring, migration and adapter before core, flow, api and ui,
    so a new glob of those roles would exempt files that do not exist yet from the stricter rules. New globs may
    therefore add core, flow, api and ui freely; test and migration only outside the source root (test also as
    `*.test.ts`); adapter and wiring only as single file names that no older glob of the component claims.
    """
    if not isinstance(comp, dict) or not isinstance(comp.get("roles"), dict):
        return []
    home = posixpath.normpath(comp.get("dir", "."))
    root = posixpath.normpath(comp.get("root", "."))
    older = [_glob_rx(str(g)) for globs in old_roles.values() for g in globs]
    out = []
    for role, globs in comp["roles"].items():
        for glob in globs:
            if glob in old_roles.get(role, []):
                continue
            label = f"component '{name}' new glob '{glob}'"
            full = posixpath.normpath(posixpath.join(comp.get("root", "."), glob))
            if role == "generated":
                out.append(f"{label} for role 'generated'; operator only")
            elif home in (".", "") or not full.startswith(home + "/"):
                out.append(f"{label} reaches outside '{home}'")
            elif role in EDGE_ROLES:
                inside = full == root or full.startswith(root + "/")
                if inside and not (role == "test" and glob.endswith(".test.ts")):
                    out.append(f"{label} for role '{role}' lies inside the source root '{root}'; only paths outside it"
                               + (" or *.test.ts files" if role == "test" else "") + "; else op:kernel")
            elif role in FILE_ROLES:
                if any(c in glob for c in WILDCARDS):
                    out.append(f"{label} for role '{role}' needs one file name without wildcards; else op:kernel")
                elif any(rx.match(glob) for rx in older):
                    out.append(f"{label} for role '{role}' takes a file that an older glob of '{name}' claims; op:kernel")
            elif role not in OPEN_ROLES:
                out.append(f"{label} for unknown role '{role}'")
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


def _appended(old: str, new: str) -> bool:
    """Return whether new is old with text appended at its end (trailing blank lines of old may change)."""
    return new.startswith(old.rstrip("\n"))


def add_only(tree: str, ref: str) -> List[Finding]:
    """Proof specs and review lenses only grow at their end; every proof file holds at least one expect call.

    Text inserted in the middle (an early `return;` in a test body, an exception line between checks) would
    keep every old line and still change what the file proves, so only appending passes; a new scenario goes
    into a new file or at the end. Comments do not count as expect calls.
    """
    found = []
    listed = gitx.run(["git", "ls-tree", "-r", "--name-only", ref, "--"] + list(ADD_ONLY), cwd=tree).stdout.split()
    for rel in listed:
        new = _read(tree, rel)
        if new is None:
            found.append(Finding(rel, 1, RULE, f"deleted against {ref}; this path only grows"))
        elif not _appended(gitx.show(tree, ref, rel) or "", new):
            found.append(Finding(rel, 1, RULE, f"changed before its end against {ref}; only append at the end"))
    for rel in gitx.ls(tree, [f"{PROOF_DIR}/**"]):
        if not EXPECT.search(COMMENTS.sub("", _read(tree, rel) or "")):
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
