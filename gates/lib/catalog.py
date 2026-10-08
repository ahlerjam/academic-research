"""Read gates/catalog.json, the single source of every rule."""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

FILE_CARRIERS = ("ast-grep", "text")
GATE_FILE_REFS = ("budgets.function", "budgets.module", "pyast.argument_mutation")


def load(tree: str) -> List[dict]:
    """Load the catalog entries from the checked tree."""
    with open(os.path.join(tree, "gates", "catalog.json"), encoding="utf-8") as handle:
        return json.load(handle)


def by_id(entries: List[dict]) -> Dict[str, dict]:
    """Index catalog entries by rule id."""
    return {e["id"]: e for e in entries}


def roles_of(entry: dict) -> List[str]:
    """Return the roles an entry applies to ('role' or 'roles', '*' for all)."""
    value = entry.get("roles", entry.get("role", "*"))
    return [value] if isinstance(value, str) else list(value)


def applies(entry: dict, component: str, role: str) -> bool:
    """Return whether an entry binds a file of this component and role."""
    comp = entry.get("component", "*")
    roles = roles_of(entry)
    return (comp in ("*", component)) and ("*" in roles or role in roles)


def for_file(entries: List[dict], component: str, role: str, carrier: Optional[str] = None) -> List[dict]:
    """Return entries of one carrier that bind a file of this component and role."""
    return [e for e in entries if applies(e, component, role) and (carrier is None or e["carrier"] == carrier)]


def code_map(entries: List[dict]) -> Dict[str, str]:
    """Map external tool codes (ruff, eslint, ...) to catalog ids."""
    return {code: e["id"] for e in entries for code in e.get("codes", [])}
