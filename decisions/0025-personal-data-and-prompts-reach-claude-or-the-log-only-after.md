---
id: 25
title: Personal data and prompts reach Claude or the log only after a per-project opt-in
status: accepted
tags: [privacy, personal-data, interviews, provenance, copilot, mcp]
---

# ADR-0025: Personal data and prompts reach Claude or the log only after a per-project opt-in

Context: Interview transcripts and survey answers are personal data; many theses work under an
ethics vote or GDPR conditions. MCP tool results enter the user's Claude Code session and thus
Anthropic's service. The change log (T26b) keeps AI provenance, and the plan revision left open
whether prompts and answers are stored too. The operator decided both on 2026-10-20.

Decision: Two project settings, both off by default. "Personal data to Claude": while off, MCP
tools return only metadata and anonymised codes of private data (Y2), never transcript or survey
text; switching it on shows a warning and is written to the change log. "Store prompts": while
off, the change log keeps model, feature, agent and time only; while on, it also keeps prompt and
answer of each AI call in the project database. Stored prompts never reach an export, the
disclosure annex or a backup shared with another project member unless the owner exports them.

Rejected: always sending personal data (unsafe for interview studies); never sending it (the AI
cannot help with the user's own data); always storing prompts (storage and privacy cost).

Consequence: T30b, T28, T33 and Y2 read the first setting; T26b, J1 and T45 read the second. T26b
changes its old AC9 accordingly. Keys and tokens stay excluded from every stored prompt (AGENTS.md).
