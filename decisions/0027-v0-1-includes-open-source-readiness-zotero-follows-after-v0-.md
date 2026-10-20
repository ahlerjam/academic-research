---
id: 27
title: v0.1 includes open-source readiness; Zotero follows after v0.1
status: accepted
tags: [release, scope, stages, proof, zotero]
supersedes: [21]
---

# ADR-0027: v0.1 includes open-source readiness; Zotero follows after v0.1

Context: ADR-0021 made v0.1 the whole product with internal milestones and kept stage 4 as a step
after v0.1. On 2026-10-20 the operator kept T44 in M5, moved Zotero after v0.1 (the operator uses
none, and the library works through upload and BibTeX or RIS import), dropped the developer script
S1 and added methodology checklists.

Decision: v0.1 is the whole product: milestones M1, M2a, M2b, M3 and M5, each done only when its
proof in `proof.yml` is green on main. Stage 4 (licence report, tested install on three operating
systems, T44) is part of M5, so tag `v0.1.0` requires every milestone, the open-source basics
(T44a), the release pipeline (T44c) and T44. The Zotero adapter (T13) carries the label
`milestone:later` and is tracked in #53; nothing in v0.1 depends on it, and cite keys, CSL items and
imports live in the library core (T13a) and manual sources (T14). S1 is closed. The engine for
inferential statistics (T35) also moves to `milestone:later`, because v0.1 computes descriptive
statistics only. Methodology checklists (N14) join M3, after the review skill of T43. Issues carry a milestone label and a wave label; each capability has an
epic.

Rejected: a public release per stage (ADR-0021); Zotero in M1 without a user who tests it.

Consequence: NORTHSTAR needs the operator's change in the stage 1 row and in "Who it is for"
(Zotero later). T17a and T38 drop their dependency on T13, and the wave labels follow the graph.
