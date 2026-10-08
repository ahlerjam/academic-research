---
id: 1
title: The feedback loop enforces the rules inside the turn
status: accepted
tags: [gates, hooks, agents, ci]
---

# ADR-0001: The feedback loop enforces the rules inside the turn

Context: Agents write most of the code. A rule that exists only as prose in AGENTS.md does not
hold: the agent builds the violation and learns about it in CI after building on top of it.

Decision: Every rule is an entry in `gates/catalog.json` with carrier, role, fixture, reason and
fix. The hooks in `.claude/settings.json` only wire to `gates/gate.py`: PostToolUse reports
`path:line [ID]` after every write, the stop gate lets no turn end with red checks, CI runs the
same make targets. Every rule has a fixture with a real violation that `make gates-selftest` must
see red. There is no warning level: red or nothing. A blocking hook fails closed.

Rejected: CI as the only gate, because the agent keeps building on the error until then; rules in
hook scripts, because there they have neither tests nor type checks.

Consequence: A turn gets slower because the stop gate checks the touched components. Every new
rule costs a catalog entry, a fixture and a rule test.

