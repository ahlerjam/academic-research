---
id: 21
title: v0.1 is the whole product; stages become internal milestones with their own proofs
status: superseded
tags: [release, scope, stages, proof]
---

# ADR-0021: v0.1 is the whole product; stages become internal milestones with their own proofs

Context: The operator decided on 2026-10-19 that the first public version contains everything:
editor and evidence, sourcing, own data, all AI functions through the plugin, collaboration,
parallel agents and the whole-thesis pipeline. A release that large gives no outside feedback for
a long time, so defects in the core must be caught by proofs, not by users.

Decision: The stages of NORTHSTAR become internal milestones M1 (stage 1), M2a, M2b, M3 and M5,
each with its proof in `proof.yml` exactly as NORTHSTAR states it. A milestone is done only when its
proof is green on main. Tag `v0.1.0` requires every milestone green, the open-source basics (T44a)
and the release pipeline (T44c). Stage 4 (licence report, tested install on three operating
systems) stays a separate step after v0.1 unless the operator moves it. Issues carry a milestone
label and a wave label; each capability has an epic.

Rejected: a public release per stage (operator decision); dropping the stage proofs (they are the
only check that a milestone works end to end).

Consequence: The v0.1 row of NORTHSTAR needs the operator's change. The ticket rework maps every
ticket to a milestone.
