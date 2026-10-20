---
id: 26
title: Agents work under the operator's own GitHub identity
status: accepted
tags: [gates, security, ci, identity, process]
---

# ADR-0026: Agents work under the operator's own GitHub identity

Context: ADR-0003 ends with "the protection only holds with a separate agent identity and a branch
ruleset with code owner review". The operator decided on 2026-10-19 that there is no separate bot
identity for agents, and `gates/project.json` sets `agent_identity` to `operator`.

Decision: Agents commit, push and open pull requests as the operator. The ruleset on main requires
a pull request and the checks `gate` and `protect`; `protect-operator-files` and CODEOWNERS
therefore cannot tell an agent's change from the operator's. The protection of control files rests
on the local layers of ADR-0003 (`permissions.deny`, `pre-write`, `pre-bash`, the manifest in the
stop gate, the ConfigChange hook) and on the operator's own review of every pull request that
touches a path in `gates/controls.json`. Merging green pull requests is allowed to agents, never
with `--admin`.

Rejected: a bot account (operator decision); disabling the remote checks (they still catch
mistakes, only not intent).

Consequence: The last sentence of ADR-0003 no longer holds; this record replaces it. An agent that
changes a control file is stopped locally, and a change that slips through is visible in CI but
not blocked. This refines ADR-0003.
