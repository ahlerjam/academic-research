---
id: 17
title: People write through Yjs, agents through block proposals with claims and conflict detection
status: accepted
tags: [sync, yjs, editor, proposals, agents, authorship]
---

# ADR-0017: People write through Yjs, agents through block proposals with claims and conflict detection

Context: The operator wants several people and several agents to write in one thesis at the same
time (decision of 2026-10-19). Yjs merges concurrent edits of people (ADR-0005); agents edit only
through `propose_edit` (ADR-0013); proposals carry `baseBlockHash` (ADR-0010). What happens when a
block changes while an agent works on it was not specified.

Decision: People edit the shared Y.Doc directly. An agent never edits the Y.Doc; it sends a
proposal for one or more blocks with the block hashes it read and Yjs relative positions of the
spans it changes. On accept the server applies it in one Yjs transaction: unchanged base hashes
apply as they are; a changed block applies when no human edit since the base overlaps the
proposal's spans, because relative positions move with the text; an overlap marks the proposal
`conflict`, shows both versions side by side, and offers "ask the agent to redo" with the current
text. A block claim `{blockId, agentId, expiresAt}` lasts 10 minutes and is renewed while the agent
works; it ends on submit, on agent stop or on expiry. A second agent's proposal for a claimed block
is refused with `claimed`. People are never blocked: a human edit in a claimed block shows a
notice, ends the claim and informs the agent. Every agent has its own author id (session, agent
name, model) in the change log, so colours and the review view tell agents and people apart.

Rejected: agents typing into the Y.Doc (no review, no provenance); discarding every proposal on a
changed block (wastes long drafts); locking blocks for people (the human always wins).

Consequence: Claims and conflicts need their own table with a migration, a core decision
`decideProposalApply` with tests for each case, and a behaviour test with two agents and one
person. ADR-0010's author kinds gain the agent id.
