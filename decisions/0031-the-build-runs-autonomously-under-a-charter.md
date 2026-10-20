---
id: 31
title: The build runs autonomously under a charter
status: proposed
tags: [process, agents, gates, ci, security, autonomy]
---

# ADR-0031: The build runs autonomously under a charter

Context: The build to v0.1.0-rc spans many days. Rules that ask the operator before an ADR, a
spike or a merge stop it. ADR-0026 gave agents the operator's GitHub identity, so CI cannot tell an
agent's change from the operator's. The operator decided on 2026-10-20: full bootstrap, kernel
frozen for every author, agents inside the repository kernel, real runs local without a budget cap.

Decision: `docs/autonomy/charter.md` is the binding contract; AGENTS.md points to it in the Done
line. Agents decide architecture, slicing, spikes, new gates and `proposed` ADRs without asking;
only the operator sets `accepted`. A model-free conductor is the only process that pushes, opens
pull requests and merges green ones, never with `--admin`. The agent, workflow and conductor
files are kernel files, so whoever builds cannot change what checks it. Whoever writes code does
not write its tests, whoever reviews does not write, whoever judges has done neither. Real bridge
and measurement runs happen on local workers under the operator's Claude Code login; CI stays on
the fake host because a real run needs a subscription token as a secret (ADR-0013).

Rejected: a second GitHub identity (operator decision of 2026-10-19), an interactive session as
conductor (a model in the merge path), agent teams as the default (experimental, not resumable).

Consequence: Kernel changes reach main only by an operator merge through the ruleset bypass.
Local worker runs have no spend limit; retry limits and the stop on an identical failure
fingerprint remain. The operator accepts or rejects `proposed` ADRs from the inbox. This refines
ADR-0026 and ADR-0003.
