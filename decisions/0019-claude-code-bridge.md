---
id: 19
title: The mod bridges the web app and the Claude Code session over a local channel with an automatic token
status: accepted
tags: [claude-code, mod, mcp, bridge, security, chat]
---

# ADR-0019: The mod bridges the web app and the Claude Code session over a local channel with an automatic token

Context: The operator works only in the web app: chat, skills, agents and autocomplete must be
reachable from there, while the user's Claude Code session runs in a terminal (ADR-0013). Any
program on the machine could otherwise post into that session. The operator wants this protection
to work without any action from the user.

Decision: On start the local server writes a random 256-bit bridge token into the project's data
directory with mode 0600; the mod and the MCP server read it from there, the browser receives it
inside the authenticated session, and the user never sees or types it. Every bridge request
carries it; requests without it are refused and logged. The flow: the web chat posts a message to
the local server; the mod polls the server (`$.clock.every`, `$.http.fetch`), starts a turn with
`$.prompt.submit` as the user's words, and reports the turn's text, tool steps, agents
(`$.agent.list`) and usage (`$.session.usage`) back to the server, which streams them to the web
app. Buttons in the web app send the matching skill command (`/recherche`, `/gliederung`,
`/kapitel`, `/pruefen`). Autocomplete requests go the same way and are answered by a tool-less
`$.model.complete` with Haiku after a typing pause. The mod checks the Claude Code version at
start and shows a notice when the bridge test does not cover it.

Rejected: channels (research preview, start flag); a token shown to the user; the web app talking
to Claude Code without the local server in between.

Consequence: Whether a submitted `/command` starts a skill, and how reliably replies come back, is
Nicht verifiziert; a bridge spike measures both before stage-2b tickets start. A bridge test per
supported Claude Code version runs in CI.
