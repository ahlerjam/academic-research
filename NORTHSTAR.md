# North star

Operator file. Goal, stages and non-goals of this repository. Agents read it and never change it.

## Goal

A provable citation chain for academic writing: every quote and every paraphrase in a thesis
resolves to an evidence passage that was checked, deterministically and verbatim, against the
printed page of the source PDF. The export refuses any gap and names it.

Source (PDF) → evidence (verbatim, printed page) → claim (supports / contradicts / mentions)
→ outline point → reference in text `[[b:…]]` → export.

The server proves, it does not think: no LLM and no API key in the server. Reading, judging and
writing happen in the user's own AI client (Claude, ChatGPT, Codex, …). Local-first: one Docker
command or `uvx`, zero configuration, bound to 127.0.0.1.

## Stages

| Stage | Outcome | Proof |
| --- | --- | --- |
| 1 (v1) | Local evidence network: add PDF sources, page mapping (page labels/segments), evidence check (exact/normalized only), search, claims, links, outline, `network_status`, `check_text`, export to DOCX/PDF. Access via MCP (stdio + local HTTP), CLI and JSON API, one engine behind all three | green proof workflow: golden path PDF → evidence → claim → text → export; gold set of ~10 OA PDFs with 0 false positives; one test suite passing against MCP, JSON API and CLI |
| 2 (v1.x) | Public mode: built-in OAuth authorization server (MCP spec 2026-07-28, CIMD + PKCE), invitation links, PDF upload, tunnel guide; works from claude.ai and ChatGPT | green proof workflow incl. OAuth conformance tests |
| 3 (v2) | Zotero: import (metadata, PDFs, highlights as evidence candidates), then the Zotero add-in on the JSON API | green proof workflow |
| 4 (v3) | Visibility: MCP Apps views (network, claims, PDF page) and a web app sharing them | green proof workflow |
| 5 (v4) | Sourcing: external search (OpenAlex, Crossref, EconBiz), open-access fetch by DOI | green proof workflow |

## Non-goals

- No LLM and no API key in the server.
- No niche methodology (meta-analysis, risk of bias, grants, posters, defense, preregistration).
- No large local models.
- No plagiarism or AI-text detection promise.
- No Sci-Hub and no paywall circumvention.
- No replacement for Zotero: connect to it, never rebuild it.
- No meta-process overhead: no custom review pipeline, no auto-issues, no tests on prompt text.
- Maybe later, not planned: ghostwriting assistance.
