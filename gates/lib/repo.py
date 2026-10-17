"""Repo-level rules: layout, feature imports, test duties, migrations, AGENTS.md, ADRs, suppression count."""

from __future__ import annotations

from typing import Dict, List, Optional

from . import adr, agents_md, catalog, drift, feature_imports, generated, layout, migrations, roles, suppress, sync, tests_duty
from .findings import Finding

REPO_REFS = ("layout", "feature_imports.cross", "feature_imports.adapter", "tests_duty.decide",
             "tests_duty.behaviour", "tests_duty.diff", "migrations.sql", "migrations.alembic",
             "agents_md", "adr", "suppress.count", "generated.header")


def _by_component(entries: List[dict], ref: str) -> Dict[str, str]:
    """Map component to rule id for one gate reference."""
    return {e.get("component", "*"): e["id"] for e in entries if e.get("carrier") == "gate" and e.get("carrier_ref") == ref}


def rules(tree: str, only: Optional[str] = None) -> List[Finding]:
    """Run every repo-level gate rule of the catalog, or only one id."""
    entries = [e for e in catalog.load(tree) if only in (None, e["id"])]
    cfg = roles.load(tree)
    found: List[Finding] = []
    lay = _by_component(entries, "layout")
    if lay:
        found += layout.violations(tree, cfg, lay)
    cross, adapter = _by_component(entries, "feature_imports.cross"), _by_component(entries, "feature_imports.adapter")
    pairs = {c: {"cross": cross.get(c), "adapter": adapter.get(c)} for c in set(cross) | set(adapter)}
    if pairs:
        found += feature_imports.violations(tree, cfg, pairs)
    for ref, func in (("tests_duty.decide", tests_duty.decide_violations),
                      ("tests_duty.behaviour", tests_duty.behaviour_violations),
                      ("tests_duty.diff", tests_duty.diff_violations)):
        mapping = _by_component(entries, ref)
        if mapping:
            found += func(tree, cfg, mapping)
    headers = _by_component(entries, "generated.header")
    if headers:
        found += generated.header_violations(tree, cfg, headers)
    for component, rid in _by_component(entries, "migrations.sql").items():
        found += migrations.sql_violations(tree, cfg["components"][component].get("migrations_dir", "db/migrations"), rid)
    for component, rid in _by_component(entries, "migrations.alembic").items():
        directory = cfg["components"][component].get("alembic_versions")
        if directory:
            found += migrations.alembic_violations(tree, directory, rid)
    for rid in _by_component(entries, "agents_md").values():
        found += agents_md.violations(tree, catalog.by_id(catalog.load(tree)), rid)
    for rid in _by_component(entries, "adr").values():
        found += adr.violations(tree, rid)
    for rid in _by_component(entries, "suppress.count").values():
        found += suppress.violations(tree, rid)
    return found


def check_all(tree: str) -> List[Finding]:
    """Repo rules plus drift plus the sync check: what an edit of a control file must keep green."""
    return rules(tree) + drift.violations(tree) + sync.check(tree)
