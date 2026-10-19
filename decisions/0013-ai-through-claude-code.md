---
id: 13
title: AI features run in the user's own Claude Code session through a plugin; the app holds no model key
status: accepted
tags: [copilot, llm, claude-code, mod, mcp, security, terms]
supersedes: [8]
---

# ADR-0013: AI features run in the user's own Claude Code session through a plugin; the app holds no model key

Context: The operator wants research, drafting and autocomplete without an API key, with agents
up to full autonomy, and the web editor beside the chat. The Agent SDK docs forbid third parties to
offer claude.ai login (code.claude.com/docs/en/agent-sdk/overview); the Consumer Terms forbid
automated access except through an API key or where Anthropic permits it (section 3 item 7). Claude
Code mods are an Anthropic feature that may call a model on the user's plan (`$.model.complete`),
start a turn (`$.prompt.submit`), list agents and read usage (code.claude.com/docs/en/plugins/mods/api).
A prototype on 2026-10-19 showed a Haiku completion through a mod after 1506 ms.

Decision: The app ships an `academic-research` Claude Code plugin with a mod, an MCP server and
skills. The user starts `claude` with the plugin; the mod bridges that session and the local web
app on 127.0.0.1: chat messages from the web app start turns, replies and agent status flow back,
and editor autocomplete runs as a tool-less `$.model.complete` after a typing pause. Claude changes
the thesis only through MCP tools (`propose_edit` and the evidence tools); every change is a
proposal with provenance (model, feature, time), and accept-all requires a green trace check.
Claude may look at the web app, never operate it to edit. Several
people and several agents (subagents, agent-team teammates) may write at once: people edit through
Yjs (ADR-0005), each agent has its own author id in the change log (ADR-0010), proposals target
blocks and apply as Yjs transactions, and a block claim keeps two agents from rewriting one block. The server holds no model key and makes
no model call. Text from PDFs and transcripts reaches Claude only as tool results marked untrusted.

Rejected: BYOK in the app (ADR-0008; the operator wants no key); running `claude -p` in the
background with the user's subscription (automated access, tools able to run commands on injected
text); channels (research preview, start flag `--dangerously-load-development-channels`).

Consequence: Users need Claude Code. Mods change between releases, so each supported Claude Code
version gets a bridge test. Permission prompts stay in the terminal. Whether a distributed plugin
that bills the user's plan is within Anthropic's terms is the operator's judgement, documented in
the README with a link to the terms; Nicht verifiziert by a lawyer. NORTHSTAR's "No MCP server"
needs the operator's change.
