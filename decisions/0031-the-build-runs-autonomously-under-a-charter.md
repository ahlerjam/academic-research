---
id: 31
title: The build runs autonomously under a charter
status: proposed
tags: [process, agents, gates, ci, security, autonomy]
---

# ADR-0031: The build runs autonomously under a charter

Context: The build to the published v0.1.0 spans many days. Rules that ask the operator before an
ADR, a spike, a merge or a release stop it. ADR-0026 gave agents the operator's GitHub identity, so
CI cannot tell an agent's change from the operator's. The operator decided on 2026-10-20 (decisions
1 to 8 in `docs/autonomy/design.md`): full bootstrap, kernel frozen for every author, agents inside
the repository kernel, everything autonomous up to the published release, and one lead session with
a goal in the Claude cloud with agent teams, workflows and subagents as the runtime.

Decision: `docs/autonomy/charter.md` is the binding contract; AGENTS.md points to it in the Done
line. Agents decide architecture, slicing, spikes, new gates and `proposed` ADRs without asking; an
independent judge panel replaces the operator's taste checks and sets `accepted` before a release.
One lead session runs `/goal` with `docs/autonomy/lead-goal.md`, takes the order of work only from
`ops/conductor/state.py` (read-only GitHub access) and changes GitHub only through the fixed,
validated verbs of `ops/conductor/gh_ops.py`; workflows and subagents return actions and change
nothing themselves. GitHub merges a pull request by auto-merge once `gate` and `protect` are green,
never with `--admin`. An hourly routine takes over when the lead's lease on `conductor/state` is
older than two hours. `release.yml` publishes only after a green dry run of the same commit, green
proofs and the panel's `verdict: release`. The agent, workflow and lead-kit files are kernel files,
so whoever builds cannot change what checks it. Whoever writes code does not write its tests,
whoever reviews does not write, whoever judges has done neither.

Rejected: a second GitHub identity (operator decision of 2026-10-19); a launchd conductor on the
laptop and a GitHub Actions conductor with a repository token as secret (both replaced by decision
8); a lead that orders work by its own judgement; agent teams for every unit (only cross-package
contract units, with a sequential fallback, because in-process teammates do not survive a resume).

Consequence: Kernel changes reach main only by an operator merge through the ruleset bypass; a
kernel need becomes an `op:kernel` item on the Operator-Inbox issue and never blocks a unit. The only
human item left is the request to Anthropic. Whether pull requests opened through the cloud proxy
trigger CI, whether the auto-merge route works and how `/goal` behaves at the usage limit are open
until the Phase B smoke tests. This refines ADR-0026 and ADR-0003.
