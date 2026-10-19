---
id: 10
title: AI edits are proposals; authorship is block-level from one change log
status: accepted
tags: [copilot, editor, sync, authorship, review]
---

# ADR-0010: AI edits are proposals; authorship is block-level from one change log

Context: The operator wants colours for who wrote what (never in the export), AI edits as diffs,
and an accept-all mode that stays reviewable like a merge request. Span-level attribution in
Yjs 13.6 with y-prosemirror is not verified.

Decision: Agent edits are proposals `{blockId, baseBlockHash, op, rationale, evidenceIds, model}`
applied in one Yjs transaction on accept. Every applied change writes a block-level change-log
row (before, after, author kind human/friend/AI, user, proposal id). Colours and the review view
read only that log. Accept-all snapshots first and never auto-applies proposals that touch cite,
datum, tquote or rawLatex nodes, delete content or span more than three blocks.

Rejected: git as the history engine (line diffs do not map to blocks or authors, needs the git CLI,
cannot delete interview data from history); a span-level ledger as a second store.

Consequence: The UI says "block-level"; span-level colours are a later measured upgrade.
