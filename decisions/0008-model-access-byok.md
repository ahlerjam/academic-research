---
id: 8
title: The copilot calls the Anthropic Messages API with each user's own key
status: accepted
tags: [copilot, llm, security, tokens, terms]
---

# ADR-0008: The copilot calls the Anthropic Messages API with each user's own key

Context: The operator wants an in-editor copilot (next sentence, find citations, drafts, chat).
This overturns the earlier non-goal "no LLM and no API key in the server". The Agent SDK docs say
third parties may not offer claude.ai login and must use API keys
(code.claude.com/docs/en/agent-sdk/overview). Whether one operator key may serve friends depends
on the Commercial Terms, which were not read: Nicht verifiziert.

Decision: The server calls the Messages API through the official SDK behind one `LlmPort` with
an in-memory replay double. Every user brings their own key (BYOK): local in the OS keychain,
hosted encrypted with AES-GCM and a master key outside the data directory; never in logs, errors,
the client, Yjs, exports or backups. The model never produces trusted text: it returns sentence
ids from retrieved passages, and code assembles quote, page and cite node. A shared operator key,
the Agent SDK, MCP and OAuth logins are not built in v1.

Rejected: driving a subscription login (not permitted for third-party apps); local models (quality
for German academic prose not shown).

Consequence: The project-level `allow_llm` switch gates sending PDF, transcript and survey text.
