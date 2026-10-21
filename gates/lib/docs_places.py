"""New markdown files only in fixed places (compared with origin's default branch); existing files stay as they are."""

from __future__ import annotations

import re
from typing import List

from . import gitx
from .findings import Finding

PLACES = (
    r"decisions/[0-9]{4}-[^/]+\.md",
    r"docs/release/(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.md",
    r"docs/review/lenses/[^/]+\.md",
    r"docs/product/[^/]+\.md",
    r"docs/autonomy/[^/]+\.md",
    r"packages/[^/]+/README\.md",
    r"docs/release/README\.md",
    r"\.claude/agents/[^/]+\.md",
    r"\.claude/rules/[^/]+\.md",
    r"gates/proofs/[^/]+\.md",
    r"docs/spikes/spike-[1-9][0-9]*\.md",
    r"CHANGELOG\.md",
)
ALLOWED = re.compile("|".join(f"(?:{p})" for p in PLACES))


def violations(tree: str, rule: str) -> List[Finding]:
    """Return a finding for every markdown file in the work tree that its base lacks, outside the allowed places.

    The base is the merge base with refs/remotes/origin/<branch> (else the local anchor), without a remote
    HEAD; tracked and untracked files count, ignored ones not. A base that cannot be listed is one finding.
    """
    ref = gitx.base_ref(tree)
    if ref is None and gitx.head(tree) is None:
        return []
    base = "HEAD"
    if ref is not None:
        merge = gitx.run(["git", "merge-base", "HEAD", ref], cwd=tree)
        base = merge.stdout.strip() if merge.returncode == 0 and merge.stdout.strip() else ref
    listed = gitx.run(["git", "ls-tree", "-r", "-z", "--name-only", base], cwd=tree)
    if listed.returncode != 0:
        return [Finding(".", 1, rule, f"cannot list the files of the base {base}; new markdown files cannot be "
                                     "told from old ones")]
    old = set(listed.stdout.split("\0"))
    return [Finding(rel, 1, rule, "new markdown file outside the places DOCS-PLACES allows")
            for rel in gitx.ls(tree, ["**/*.md"]) if rel not in old and not ALLOWED.fullmatch(rel)]
