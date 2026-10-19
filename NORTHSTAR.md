# North star

Operator file. Goal, stages and non-goals of this repository. Agents read it and never change it.

## Goal

A local-first, self-hostable writing tool for scientific theses where nothing in the thesis is
without a trace. A structured editor holds citations, data numbers, interview quotes and
cross-references as typed nodes and generates LaTeX, PDF and docx through the university template in
any common citation style. Every citation can carry an anchored passage, for a direct quote as well
as for a paraphrase: source, printed page and the exact text range. Quotes, pages, numbers and cite
keys are checked by code, never by a model; what is not anchored is listed, and a broken trace
blocks the export. Hovering a citation shows the anchored passage with its printed page; a direct
quote is additionally checked verbatim. A number is a live reference to an analysis of the
author's own data; an interview quote points at a transcript line, without writing code.
The tool helps to find and obtain sources: on a click it searches open metadata services, downloads
what is legally open access, and puts everything else on a wishlist with links into the author's
own library (DOI, link resolver, catalogue, interlibrary loan), configurable for any library.
The AI is the author's own Claude Code, connected through an academic-research plugin: a chat,
autocomplete and agents beside the editor suggest the next sentence, research sources, draft
sections and answer questions about the literature and the data, up to autonomous work, and every
change they make is a reviewable proposal. AI provenance is never silently lost: the change log
keeps model, feature, agent and time, and the author can export a disclosure annex; no automatic
marker reaches the thesis. People and agents write together at the same time, with colours for who
wrote what, which never reach the export. An examiner reviews a chapter: deterministic rules first,
advisory judgement second.

Deterministic wherever possible, token-saving, secure, easy to install. Few features, each done
fully. Plan: `docs/plan/2026-10-17-academic-research-plan.md` with
`docs/plan/2026-10-19-plan-revision.md`.

## Who it is for

Hypotheses, checked by T23 and T44:

- Students writing a bachelor or master thesis in German or English who keep their sources in
  Zotero or as PDFs and write in APA or another author-date style; footnote styles follow once
  spike T05 has shown them. The AI features need Claude Code; everything else works without it.
- Their co-authors and friends, each with their own Claude Code, sharing a project (stage 3).
- Not yet: users without any compile path (Docker, host TeX, or an external TeX for the export
  bundle).

## Stages

| Stage | Outcome | Proof |
| --- | --- | --- |
| 1 | Write and compile one real chapter locally: structured editor, Zotero and PDFs, anchored citations (quote or paraphrase) with hover and quote check, LaTeX/PDF with template, trace check, versions and backup, install | `proof.yml` stage 1 green; the operator writes and exports a real chapter (T23) |
| v0.1 | First public release: all of stage 1 plus the wishlist with library links and a library profile, and open-source basics (security policy, contributing guide, release, demo project) | stage 1 done, wishlist export with links for a configured library, T44a done, tag `v0.1.0` |
| 2a | Own data and sources without a model: live numbers, result tables, transcript quotes, deletion path for interview data, source search on click and legal open-access download | `proof.yml` stage 2a green; a chapter with a live number, a result table and a transcript quote, exported without a model call; a search that adds an open-access PDF with its provenance |
| 2b | Copilot through the Claude Code plugin: chat, autocomplete and agents in the web app, proposals with review and provenance, AI-usage annex | `proof.yml` stage 2b green; bridge test per supported Claude Code version; validator and injection fixtures; recall@10 >= 0.8; annex test |
| 3 | Friends: shared projects through a sync server, auth, people and agents writing at once with block-level colours, comments, examiner | `proof.yml` stage 3 green; two users and an agent on one project; byte-identical mixed-author export |
| 4 | Open-source readiness | licence report, tested install docs on three OSes |
| 5 | Whole-thesis drafting, designed from measured costs | written design approved by the operator |

## Non-goals

- No own docx writer (docx only through Pandoc from the generated LaTeX), no custom text format, no
  git as sync engine.
- No supervisor submission package, reading-bridge cards, interview coding, defense training,
  literature radar (no background search, subscriptions or alerts), argument map or gamification.
- No Sci-Hub or paywall circumvention, no automated download behind a library login; the app holds
  no model key and makes no model call of its own.
- No AI edit outside a proposal; Claude never operates the web app to change the thesis.
- No fuzzy acceptance of a quote, no model judgement as an export gate, no printed page without a
  derivation or a user setting.
- No telemetry; outbound connections only on the user's click and only to Zotero, open metadata and
  open-access services; model calls run only in the user's own Claude Code session; thesis text
  never goes to a search service.
- No mobile or tablet layout in v1; desktop browsers only.
- No feature outside the plan's goals G1-G7.
