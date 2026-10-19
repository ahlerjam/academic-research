---
id: 3
title: The controls protect themselves
status: accepted
tags: [gates, security, hooks, ci]
---

# ADR-0003: The controls protect themselves

Context: An agent that can weaken its own gates will, when in doubt, turn them green instead of
fixing the error. No single layer is tight: `permissions.deny` does not stop scripts that write
on their own, and `disableAllHooks` is allowed in every settings file.

Decision: `gates/controls.json` is the only list of control files. From it `make sync` generates
the `Edit(...)` rules in `permissions.deny` (Claude Code never consults path rules for `Write`),
CODEOWNERS and the path list of the `protect-operator-files` workflow. Behind them sit `pre-write`
and `pre-bash` as a second line, the manifest `gates/controls.sha256` in the stop gate, the
ConfigChange hook and CI. A finding in a control file is reported as a patch, never changed.

Rejected: `permissions.deny` alone, because subprocesses write past it.

Consequence: After every change of a control file the operator runs `make controls-baseline`.
The protection only holds with a separate agent identity and a branch ruleset with code owner
review.

