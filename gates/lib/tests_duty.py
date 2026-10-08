"""Test duties instead of coverage: every decide* and adapter translate* result is asserted, every feature has a behaviour test."""

from __future__ import annotations

import ast
import os
import posixpath
import re
from typing import Dict, List, Set

from . import gitx, roles
from .findings import Finding

TS_EXPORT = re.compile(r"export\s+(?:const|function)\s+((?:decide|translate)[A-Z]\w*)")
KT_FUN = re.compile(r"^\s*(?:internal\s+|public\s+)?fun\s+((?:decide|translate)[A-Z]\w*)", re.MULTILINE)
TS_TEST_START = re.compile(r"(?m)^\s*(?:it|test)(?!\.(?:skip|todo|fixme)\b)(?:\.\w+)?\s*\(")
SKIP_MARK = re.compile(r"\b(skip|skipif|xfail)\b")
KT_TEST_START = re.compile(r"(?m)^\s*@Test\b")
ASSIGN = re.compile(r"\b(?:const|let|val|var)\s+(\w+)\s*(?::[^=\n]+)?=\s*[^;\n]*?\b((?:decide|translate)\w*)\s*[(<]")
PREFIXES = {"core": ("decide_", "decide"), "adapter": ("translate_", "translate")}
BEHAVIOUR_NEEDS = {"typescript": (r"\bexpect\s*\(", r"\bpage\.goto\s*\("), "kotlin": (r"@Test\b", r"\bassert\w*\s*\(|shouldBe")}


def _read(tree: str, rel: str) -> str:
    """Read a file as text."""
    with open(os.path.join(tree, rel), encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _py_duties(tree: str, rel: str, prefix: str) -> Dict[str, int]:
    """Return top-level function names with the prefix and their lines."""
    try:
        module = ast.parse(_read(tree, rel))
    except SyntaxError:
        return {}
    return {n.name: n.lineno for n in module.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith(prefix)}


def _call_name(node: ast.AST) -> str:
    """Return the called name of a Call node, '' otherwise."""
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _assert_names(func: ast.AST) -> Set[str]:
    """Return plain names read inside the asserts of a test function."""
    return {sub.id for node in ast.walk(func) if isinstance(node, ast.Assert)
            for sub in ast.walk(node.test) if isinstance(sub, ast.Name)}


def _assert_calls(func: ast.AST) -> Set[str]:
    """Return names of functions called inside the asserts of a test function."""
    return {_call_name(sub) for node in ast.walk(func) if isinstance(node, ast.Assert)
            for sub in ast.walk(node.test)} - {""}


def _py_skipped(node: ast.AST) -> bool:
    """Return whether a test function or module is switched off by a skip or xfail mark."""
    if isinstance(node, ast.Module):
        return any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
                   and SKIP_MARK.search(ast.unparse(n.value)) for n in node.body)
    return any(SKIP_MARK.search(ast.unparse(d)) for d in getattr(node, "decorator_list", []))


def _py_tests(module: ast.Module) -> List[ast.AST]:
    """Return the test functions of a module that actually run (no skip or xfail mark)."""
    if _py_skipped(module):
        return []
    return [f for f in ast.walk(module) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and f.name.startswith("test") and not _py_skipped(f)]


def _py_checked(tree: str, tests: List[str]) -> Set[str]:
    """Return functions whose result flows into an assert of the same test, directly or through a name."""
    checked: Set[str] = set()
    for rel in tests:
        try:
            module = ast.parse(_read(tree, rel))
        except SyntaxError:
            continue
        for func in _py_tests(module):
            asserted = _assert_names(func)
            checked |= _assert_calls(func)
            for node in (n for n in ast.walk(func) if isinstance(n, ast.Assign)):
                called = {_call_name(sub) for sub in ast.walk(node.value)} - {""}
                bound = {sub.id for t in node.targets for sub in ast.walk(t) if isinstance(sub, ast.Name)}
                if bound & asserted:
                    checked |= called
    return checked


def _blocks(text: str, start: "re.Pattern[str]") -> List[str]:
    """Split a test file into one text block per test."""
    marks = [m.start() for m in start.finditer(text)] + [len(text)]
    return [text[a:b] for a, b in zip(marks, marks[1:])]


def _text_checked(bodies: List[str], lang: str) -> Set[str]:
    """Return functions whose result reaches an assertion line of the same test (TypeScript and Kotlin)."""
    start = TS_TEST_START if lang == "typescript" else KT_TEST_START
    assertion = re.compile(r"\bexpect\s*\(" if lang == "typescript" else r"\bassert\w*\s*\(|shouldBe|\bexpect\s*\(")
    checked: Set[str] = set()
    for block in (b for body in bodies for b in _blocks(body, start)):
        bound = {m.group(1): m.group(2) for m in ASSIGN.finditer(block)}
        for line in (ln for ln in block.splitlines() if assertion.search(ln)):
            checked |= set(re.findall(r"\b((?:decide|translate)\w*)\s*[(<]", line))
            checked |= {fn for var, fn in bound.items() if re.search(rf"\b{re.escape(var)}\b", line)}
    return checked


def _duties(tree: str, rel: str, lang: str, role: str) -> Dict[str, int]:
    """Return the functions of one core or adapter file that need an asserting test."""
    py_prefix, other_prefix = PREFIXES[role]
    if lang == "python":
        return _py_duties(tree, rel, py_prefix)
    text = _read(tree, rel)
    pattern = TS_EXPORT if lang == "typescript" else KT_FUN
    return {m.group(1): text.count("\n", 0, m.start()) + 1 for m in pattern.finditer(text)
            if m.group(1).startswith(other_prefix)}


def decide_violations(tree: str, cfg: dict, rule_by_component: Dict[str, str]) -> List[Finding]:
    """Return one finding per decide (core) or translate (adapter) function whose result no test asserts."""
    found: List[Finding] = []
    idx = roles.index(tree, cfg)
    for component, rule in rule_by_component.items():
        lang = cfg["components"][component]["lang"]
        tests = [r for r, p in idx.items() if p.component == component and p.role == "test"]
        checked = _py_checked(tree, tests) if lang == "python" else _text_checked([_read(tree, t) for t in tests], lang)
        for rel, place in sorted(idx.items()):
            if place.component != component or place.role not in PREFIXES:
                continue
            for name, line in _duties(tree, rel, lang, place.role).items():
                if name not in checked:
                    found.append(Finding(rel, line, rule, f"the result of '{name}' is not asserted by any test"))
    return found


def _behaviour_ok(tree: str, rel: str, lang: str) -> bool:
    """Return whether a behaviour test holds at least one real test with an assertion."""
    text = _read(tree, rel)
    if lang == "python":
        try:
            module = ast.parse(text)
        except SyntaxError:
            return False
        return any(any(isinstance(n, ast.Assert) for n in ast.walk(f)) for f in _py_tests(module))
    if lang == "typescript" and not any(re.search(r"\bexpect\s*\(", b) for b in _blocks(text, TS_TEST_START)):
        return False
    return all(re.search(p, text) for p in BEHAVIOUR_NEEDS.get(lang, ()))


def behaviour_violations(tree: str, cfg: dict, rule_by_component: Dict[str, str]) -> List[Finding]:
    """Return one finding per feature without a behaviour test that asserts something."""
    found: List[Finding] = []
    for (component, feature), files in sorted(roles.features(tree, cfg).items()):
        rule = rule_by_component.get(component)
        template = cfg["components"][component].get("behaviour_test")
        if not rule or not template:
            continue
        expected = posixpath.normpath(posixpath.join(cfg["components"][component]["root"],
                                                     template.replace("{feature}", feature)))
        if not os.path.isfile(os.path.join(tree, expected)):
            found.append(Finding(sorted(files)[0], 1, rule, f"feature '{feature}' has no behaviour test {expected}"))
        elif not _behaviour_ok(tree, expected, cfg["components"][component]["lang"]):
            found.append(Finding(expected, 1, rule, "behaviour test without a test that asserts (Playwright: "
                                                    "page.goto and expect)"))
    return found


def _names_in(tree: str, rel: str, lang: str) -> Set[str]:
    """Return the top-level function names a core defines."""
    text = _read(tree, rel)
    if lang == "python":
        try:
            return {n.name for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        except SyntaxError:
            return set()
    pattern = r"export\s+(?:const|function)\s+(\w+)" if lang == "typescript" else r"^\s*(?:internal\s+|public\s+)?fun\s+(\w+)"
    return set(re.findall(pattern, text, re.MULTILINE))


def diff_violations(tree: str, cfg: dict, rule_by_component: Dict[str, str]) -> List[Finding]:
    """Return a finding when a changed core has no changed test of its component that names one of its functions."""
    if gitx.base_ref(tree) is not None:
        changed = set(gitx.changed_since_base(tree))
    else:
        changed = set(gitx.dirty(tree)) if gitx.head(tree) else set()
    idx = roles.index(tree, cfg)
    found: List[Finding] = []
    for component, rule in rule_by_component.items():
        lang = cfg["components"][component]["lang"]
        cores = sorted(r for r in changed if r in idx and idx[r].component == component and idx[r].role == "core")
        tests = [_read(tree, r) for r in changed if r in idx and idx[r].component == component and idx[r].role == "test"]
        for core in cores:
            names = _names_in(tree, core, lang)
            if not tests or (names and not any(re.search(rf"\b{re.escape(n)}\b", t) for n in names for t in tests)):
                found.append(Finding(core, 1, rule, "core changed without a changed test that calls one of its functions"))
    return found
