# North star (proposed 2026-10-17, adopted as NORTHSTAR.md by the bootstrap)

## Goal

A local-first, self-hostable writing tool for scientific theses where nothing in the thesis is
without a trace. A structured editor holds citations, data numbers, interview quotes and
cross-references as typed nodes and generates LaTeX and PDF through the university template in any
common citation style. Hovering a citation shows the verbatim PDF passage with its printed page; a
number is a live reference to an analysis of the author's own data; an interview quote points at a
transcript line. A copilot suggests the next sentence, finds citations, drafts sections and
answers questions about the literature and the data, and every change it makes is a reviewable
proposal. Friends write together with colours for who wrote what, which never reach the export.
A supervisor agent reviews a chapter: deterministic rules first, advisory judgement second.

Deterministic wherever possible, token-saving, secure, easy to install. Few features, each done
fully.

## Stages

| Stage | Outcome | Proof |
| --- | --- | --- |
| 1 | Write and compile one real chapter locally: structured editor, Zotero and PDFs, hover-to-passage, quote check, LaTeX/PDF with template, trace check, versions and backup, install | `proof.yml` stage 1 green; the operator writes and exports a real chapter (T23) |
| 2 | Evidence wedge and copilot: live numbers, result tables, transcript quotes, proposals with review, grounded copilot | `proof.yml` stage 2 green; validator and injection fixtures; recall@10 >= 0.8 |
| 3 | Friends: hosted profile, auth, collaboration with block-level colours, comments, supervisor agent | `proof.yml` stage 3 green; two users on a hosted instance; byte-identical mixed-author export |
| 4 | Open-source readiness | licence report, tested install docs on three OSes |
| 5 | Whole-thesis drafting, designed from measured costs | written design approved by the operator |

## Non-goals

- No MCP server, no docx output, no custom text format, no git as sync engine.
- No supervisor submission package, reading-bridge cards, interview coding, defense training,
  literature radar, argument map or gamification.
- No Sci-Hub or paywall circumvention; no shared operator LLM key in v1.
- No feature outside the plan's goals G1-G6.
