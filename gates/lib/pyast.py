"""Python AST rules that ast-grep cannot express (argument mutation)."""

from __future__ import annotations

import ast
from typing import List, Optional, Set

from .findings import Finding

MUTATING = frozenset({"append", "extend", "insert", "pop", "remove", "clear", "update", "sort",
                      "add", "discard", "setdefault", "popitem"})


def _params(node: ast.AST) -> Set[str]:
    """Return the parameter names of a function node."""
    args = node.args  # type: ignore[attr-defined]
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    names += [a.arg for a in (args.vararg, args.kwarg) if a is not None]
    return set(names) - {"self", "cls"}


def _target(node: ast.AST) -> Optional[str]:
    """Return the name a call, assignment or augmented assignment mutates in place."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in MUTATING:
        return node.func.value.id if isinstance(node.func.value, ast.Name) else None
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AugAssign) else []
    for target in targets:
        if isinstance(target, (ast.Subscript, ast.Attribute)) and isinstance(target.value, ast.Name):
            return target.value.id
        if isinstance(node, ast.AugAssign) and isinstance(target, ast.Name):
            return None
    return None


def argument_mutation(rel: str, text: str, rule: str) -> List[Finding]:
    """Return one finding per statement that mutates an argument of its own function."""
    try:
        tree = ast.parse(text)
    except SyntaxError as err:
        return [Finding(rel, err.lineno or 1, "GATES-INFRA", f"syntax error: {err.msg}")]
    found: List[Finding] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = _params(func)
        for stmt in func.body:
            for node in ast.walk(stmt):
                name = _target(node)
                if name and name in params:
                    found.append(Finding(rel, node.lineno, rule,
                                         f"argument '{name}' of '{func.name}' is mutated"))
    return found
