---
id: 28
title: The Claude Code plugin is a workspace package and the install entry point
status: accepted
tags: [plugin, install, bridge, workspace, release]
---

# ADR-0028: The Claude Code plugin is a workspace package and the install entry point

Context: ADR-0013 and ADR-0019 put the AI into a Claude Code plugin (mod bridge, MCP server,
skills) but named neither its place in the repository nor how a user who is not a developer
installs the product. The bridge depends on Claude Code's mod interface, which changes with
Claude Code releases.

Decision: The plugin lives in `packages/plugin` of the pnpm workspace, shares the types of
`packages/core` and runs under the same gates; it gets its own role in `gates/roles.json` through an
operator patch. It is also the install entry point: the user installs the plugin, and one command
of it downloads the app release, checks Docker or host TeX and Pandoc, starts the local web app and
opens its guided setup. The bridge test runs against the current and the previous stable Claude
Code release; an older version is detected at start and shown with a hint to update.

Rejected: a separate plugin repository (types and gates twice); native installers per operating
system for v0.1 (more release work, no AI without Claude Code anyway).

Consequence: T22 builds the install command on the plugin; T24 creates the package; P3 pins the
two tested versions; T44 tests the install on three operating systems. The operator applies the
roles patch before T24.
