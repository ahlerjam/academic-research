"""Ratchet guard: agents may add gates, never weaken them (compared with origin's default branch)."""

from __future__ import annotations

import functools
import json
import math
import os
import posixpath
import re
from typing import Callable, Dict, List, Optional, Sequence, Set

from . import catalog, gitx, manifest, roles
from .findings import Finding

RULE = "GATES-RATCHET"
ROLES = "gates/roles.json"
DISPATCH = "gates/dispatch.json"
CATALOG = "gates/catalog.json"
TEMPLATE = "gates/templates/package-tsconfig.json"
QUALITY_BAR = "docs/product/quality-bar.json"
DOGFOOD = "docs/product/dogfood-scenario.md"
PROOF_DIR = "packages/web/e2e/proof"
ADD_ONLY = (PROOF_DIR, "docs/review/lenses", DOGFOOD)
EXPECT = re.compile(r"\bexpect\b(?:\.\w+)*\s*\(")
PACKAGE_TSCONFIG = re.compile(r"packages/[^/]+/tsconfig\.json")
ROLES_GROWING = ("ignore", "components", "budgets", "shared_fingerprint")
COMPONENT_KEYS = ("lang", "dir", "root", "roles")
DEFAULT_NON_FEATURE = ["adapters"]
OPEN_ROLES = ("core", "flow", "api", "ui")
CATCH_ALL_ROLES = ("api", "ui")
KERNEL_ROLES = ("core", "flow")
FILE_ROLES = ("adapter", "wiring")
EDGE_ROLES = ("test", "migration")
WILDCARDS = "*?["
DISPATCH_KEYS = ("glob", "tier", "format", "format_check", "check", "cwd", "finding_exits")
DISPATCH_COPIED = ("tier", "format", "format_check", "cwd", "finding_exits")
BUILTIN_CHECKS = (["@rules"], ["@repo"])
DIRECTIONS = ("max", "min")
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
    old_cat = gitx.show(tree, ref, CATALOG)
    if old_cat:
        with open(os.path.join(tree, CATALOG), encoding="utf-8") as handle:
            now = {e["id"]: e for e in json.load(handle)}
        for entry in json.loads(old_cat):
            if now.get(entry["id"]) != entry:
                found.append(Finding(CATALOG, 1, RULE, f"{entry['id']} removed or changed"))
    entries = json.loads(old_cat) if old_cat else catalog.load(tree)
    kernel = list(cfg.get("operator_only", []))
    found += _ordered(tree, ref, ROLES, lambda old, new: roles_order(tree, old, new, entries))
    found += _ordered(tree, ref, DISPATCH, lambda old, new: dispatch_order(old, new, kernel))
    found += _ordered(tree, ref, QUALITY_BAR, quality_order)
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


def _tokens(segment: str) -> List[str]:
    """Split one glob segment into '*', '?' (a bracket class counts as '?') and literal characters."""
    out, i = [], 0
    while i < len(segment):
        end = segment.find("]", i + 2) if segment[i] == "[" else -1
        if end > 0:
            out, i = out + ["?"], end + 1
        else:
            out, i = out + [segment[i]], i + 1
    return out


def _meet(a: Sequence[str], b: Sequence[str], star: str, same: Callable[[str, str], bool]) -> bool:
    """Return whether two token sequences share a word; `star` stands for any run of tokens, `same` compares the rest."""

    @functools.lru_cache(maxsize=None)
    def step(i: int, j: int) -> bool:
        if i < len(a) and a[i] == star and step(i + 1, j):
            return True
        if j < len(b) and b[j] == star and step(i, j + 1):
            return True
        if i == len(a) or j == len(b):
            return i == len(a) and j == len(b)
        if a[i] == star:
            return step(i, j + 1)
        if b[j] == star:
            return step(i + 1, j)
        return same(a[i], b[j]) and step(i + 1, j + 1)

    return step(0, 0)


def _segment_meet(a: str, b: str) -> bool:
    """Return whether two glob segments match one common file or directory name."""
    return _meet(_tokens(a), _tokens(b), "*", lambda x, y: x == y or "?" in (x, y))


def _segments(glob: str) -> List[str]:
    """Split a glob at '/'; a segment that holds '**' next to other text counts as '**' (an over-approximation)."""
    return ["**" if "**" in part else part for part in glob.split("/")]


def _overlap(a: str, b: str) -> bool:
    """Return whether two git glob pathspecs can match one common path (fail-closed over-approximation).

    A pathspec without wildcards also matches every path below it, as `git ls-files ':(glob)gates'` lists
    gates/**; one with a wildcard matches only whole paths.
    """
    left = [a] + ([a + "/**"] if not any(c in a for c in WILDCARDS) else [])
    right = [b] + ([b + "/**"] if not any(c in b for c in WILDCARDS) else [])
    return any(_meet(_segments(x), _segments(y), "**", _segment_meet) for x in left for y in right)


def roles_order(tree: str, old: dict, new: dict, entries: List[dict]) -> List[str]:
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
        out += _new_globs(name, comp, old_comps.get(name, {}).get("roles", {}), entries, new.get("budgets", {}))
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
            if not _within(now, limit):
                out.append(f"budget {role}.{key} {limit} -> {now}")
    return out


def _within(value: object, limit: int) -> bool:
    """Return whether a budget value is an integer no larger than the limit."""
    return isinstance(value, int) and not isinstance(value, bool) and value <= limit


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
    """Return why a new component is malformed, overlaps an existing one or holds sources with fewer rules.

    Catalog rules bound to a component never reach a new one, so a new component gets only the rules with
    component '*'. Core and flow carry their strictest rules per component (TS-CORE-* in core,
    TS-NO-DECISION-IN-FLOW in server); in a new component they are therefore op:kernel. Its sources need a
    catch-all api or ui glob.
    """
    if not isinstance(comp, dict) or any(k not in comp for k in COMPONENT_KEYS) or not isinstance(comp["roles"], dict):
        return [f"new component '{name}' needs {', '.join(COMPONENT_KEYS)}"]
    mine = posixpath.normpath(comp["dir"])
    out = [f"new component '{name}' needs its own directory, not '.'"] if mine in (".", "") else []
    for other, data in old.items():
        theirs = posixpath.normpath(data.get("dir", "."))
        if theirs in (".", "", mine) or mine.startswith(theirs + "/") or theirs.startswith(mine + "/"):
            out.append(f"new component '{name}' dir '{mine}' overlaps component '{other}'")
    out += [f"new component '{name}' role '{role}' would lose the component-bound rules of '{role}'; op:kernel"
            for role in KERNEL_ROLES if comp["roles"].get(role)]
    if not any(str(g).startswith("**/") for role in CATCH_ALL_ROLES for g in comp["roles"].get(role, [])):
        out.append(f"new component '{name}' needs a role {', '.join(CATCH_ALL_ROLES)} with a '**/' glob over its sources")
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


def _new_globs(name: str, comp: object, old_roles: Dict[str, list], entries: List[dict],
               budgets: Dict[str, dict]) -> List[str]:
    """Return new globs that claim generated code, reach outside the component or give future files a laxer role.

    Role priority (gates/lib/roles.py) decides which role a path gets; the catalog decides whether that role is
    laxer. Test and migration may claim only paths outside the source root (test also `*.test.ts`); adapter and
    wiring only single file names that no older glob of the component claims; core, flow, api and ui keep every
    rule id and budget of each lower-priority role whose older globs they overlap ('**/' globs: of every one).
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
            else:
                out += [f"{label} for role '{role}' {why}; else op:kernel"
                        for why in _laxer(name, role, str(glob), root, old_roles, entries, budgets)]
    return out


def _rule_ids(entries: List[dict], component: str, role: str) -> Set[str]:
    """Return the ids of every catalog rule that binds a file of this component and role."""
    return {e["id"] for e in catalog.for_file(entries, component, role)}


def _laxer(name: str, role: str, glob: str, root: str, old_roles: Dict[str, list], entries: List[dict],
           budgets: Dict[str, dict]) -> List[str]:
    """Return why a new open-role glob would hand paths of a lower-priority role fewer rules or a larger budget."""
    rank = roles.ROLE_PRIORITY.index(role)
    full = posixpath.normpath(posixpath.join(root, glob))
    mine, out = _rule_ids(entries, name, role), []
    for other, globs in old_roles.items():
        if other not in roles.ROLE_PRIORITY or roles.ROLE_PRIORITY.index(other) <= rank:
            continue
        if not (glob.startswith("**/") or any(_overlap(full, posixpath.normpath(posixpath.join(root, str(g))))
                                              for g in globs)):
            continue
        lost = sorted(_rule_ids(entries, name, other) - mine)
        lost += [f"budget {key} {limit}" for key, limit in sorted(budgets.get(other, {}).items())
                 if not _within(budgets.get(role, {}).get(key), limit)]
        if lost:
            out.append(f"takes paths of role '{other}' and drops {', '.join(lost)}")
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


def dispatch_order(old: dict, new: dict, kernel: Sequence[str] = ()) -> List[str]:
    """Return why new dispatch.json is no ratchet step: entries may only be appended; mode only to strict.

    The engine runs every argv of a matching entry in the post-edit hook, so an appended entry may only reuse
    values of older entries: each argv (format, format_check, every check) verbatim from the same key of an
    older entry, or ["@rules"]/["@repo"] as a check; tier, cwd and finding_exits likewise. Its glob stays
    inside the repository and off every operator-only path.
    """
    out = [f"top-level key '{k}' added" for k in new if k not in old]
    out += [f"'{k}' changed" for k in old if k not in ("mode", "entries") and new.get(k) != old[k]]
    if new.get("mode", "strict") not in (old.get("mode", "strict"), "strict"):
        out.append(f"mode '{old.get('mode', 'strict')}' -> '{new.get('mode')}'")
    kept, entries = old.get("entries", []), new.get("entries", [])
    if not isinstance(entries, list) or entries[:len(kept)] != kept:
        return out + ["existing entries changed, removed or reordered; append new entries at the end"]
    known: Dict[str, Set[str]] = {key: {json.dumps(e[key]) for e in kept if key in e} for key in DISPATCH_COPIED}
    known["check"] = {json.dumps(argv) for e in kept for argv in e.get("check", [])} | {
        json.dumps(argv) for argv in BUILTIN_CHECKS}
    for number, entry in enumerate(entries[len(kept):], start=len(kept) + 1):
        out += [f"new entry {number} {why}" for why in _new_entry(entry, known, kernel)]
    return out


def _new_entry(entry: object, known: Dict[str, Set[str]], kernel: Sequence[str]) -> List[str]:
    """Return why one appended dispatch entry is malformed, runs a new command or reaches an operator-only path."""
    if not (isinstance(entry, dict) and isinstance(entry.get("glob"), str) and isinstance(entry.get("tier"), str)):
        return ["needs a string 'glob' and 'tier'"]
    out = [f"has unknown key '{k}'" for k in entry if k not in DISPATCH_KEYS]
    out += [f"'{k}' {json.dumps(entry[k])} is not taken from the same key of an older entry"
            for k in DISPATCH_COPIED if k in entry and json.dumps(entry[k]) not in known[k]]
    checks = entry.get("check", [])
    out += [f"check {json.dumps(argv)} is neither an older check nor @rules or @repo"
            for argv in (checks if isinstance(checks, list) else [checks]) if json.dumps(argv) not in known["check"]]
    for part in entry["glob"].split("|"):
        norm = posixpath.normpath(part) if part else ""
        if norm in ("", ".") or norm.startswith(("/", "..")) or "\\" in part:
            out.append(f"glob part '{part}' is empty, absolute, outside the repository or escaped")
            continue
        hits = [g for g in kernel if _overlap(norm, g)]
        more = f" and {len(hits) - 3} more" if len(hits) > 3 else ""
        out += [f"glob part '{part}' reaches operator-only {', '.join(repr(g) for g in hits[:3])}{more}"] if hits else []
    return out


def _bar_ok(budget: dict) -> bool:
    """Return whether a quality-bar budget has a string id, a direction max or min and a finite numeric threshold."""
    value = budget.get("threshold")
    return (isinstance(budget.get("id"), str) and budget.get("direction") in DIRECTIONS
            and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))


def quality_order(old: dict, new: dict) -> List[str]:
    """Return why new quality-bar.json is no ratchet step: every budget stays, thresholds only tighten.

    An existing budget keeps its id and every key but threshold; a max threshold may only fall and a min
    threshold only rise. New budgets need a string id, direction max or min and a finite numeric threshold.
    """
    out = [f"top-level key '{k}' added" for k in new if k not in old]
    out += [f"'{k}' changed" for k in old if k != "budgets" and new.get(k) != old[k]]
    budgets = new.get("budgets")
    if not isinstance(budgets, list) or not all(isinstance(b, dict) for b in budgets):
        return out + ["'budgets' is no longer a list of objects"]
    now: Dict[str, dict] = {}
    for budget in budgets:
        if not _bar_ok(budget):
            out.append(f"budget {budget.get('id')!r} needs a string id, direction max or min "
                       "and a finite numeric threshold")
        elif budget["id"] in now:
            out.append(f"budget '{budget['id']}' appears twice")
        else:
            now[budget["id"]] = budget
    for was in old.get("budgets", []) if isinstance(old.get("budgets"), list) else []:
        if not isinstance(was, dict) or not _bar_ok(was):
            continue
        cur = now.get(was["id"])
        if cur is None:
            out.append(f"budget '{was['id']}' removed")
            continue
        out += [f"budget '{was['id']}' key '{k}' changed" for k in sorted(set(was) | set(cur))
                if k != "threshold" and was.get(k) != cur.get(k)]
        looser = cur["threshold"] > was["threshold"] if was["direction"] == "max" else cur["threshold"] < was["threshold"]
        if looser:
            out.append(f"budget '{was['id']}' threshold {was['threshold']} -> {cur['threshold']} loosens "
                       f"a '{was['direction']}' bar")
    return out


def _appended(old: str, new: str) -> bool:
    """Return whether new is old with text appended at its end (trailing blank lines of old may change)."""
    return new.startswith(old.rstrip("\n"))


def add_only(tree: str, ref: str) -> List[Finding]:
    """Proof specs, review lenses and the dogfood scenario only grow at their end; every proof file holds an expect.

    Text inserted in the middle (an early `return;` in a test body, an exception line between checks, a
    skipped dogfood step) would keep every old line and still change what the file proves, so only appending
    passes; a new scenario goes into a new file or at the end. Comments do not count as expect calls.
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
