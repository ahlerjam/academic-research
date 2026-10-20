# academic-research: Plan revision (2026-10-19)

Status: accepted by the operator on 2026-10-19. This revision amends
`docs/plan/2026-10-17-academic-research-plan.md`; where the two disagree, this file wins. The
authoritative ticket text stays in the GitHub issues. Inputs: a review workflow with six critics,
adversarial verification and a judge (66 findings, none refuted), a research workflow on sourcing,
libraries, embeddings and method (12 agents), a mod prototype in a live Claude Code session, and the
operator's decisions recorded below.

## 1. Decisions of 2026-10-19

| # | Decision | Record |
| --- | --- | --- |
| 1 | v0.1 was first set to stage 1 plus the wishlist; later the same day the operator made v0.1 the whole product (row 16) | NORTHSTAR (PR #63), ADR-0021 |
| 2 | A citation anchor is a text range, for a direct quote (`quote`) and for a paraphrase (`locus`) | ADR-0014 |
| 3 | AI runs in the user's own Claude Code session through an `academic-research` plugin (mod bridge, MCP tools, skills, agents); the app holds no model key | ADR-0013, supersedes ADR-0008 |
| 4 | The product is a web app with the full editor beside a chat, task and proposal panel; the Claude Code session is the engine | ADR-0013 |
| 5 | Several people and several agents can write at the same time | ADR-0013, ADR-0010 |
| 6 | Sourcing: search on a click, legal open-access download, wishlist with links for any library, relevance filter with a screening log | ADR-0015, goal G7 |
| 7 | SQLite stays; no vector database; local embeddings only if retrieval measurement in T27 stays below recall@10 0.8 | ADR-0006 |
| 8 | Hard guarantees block export; paraphrase sense and relevance are advisory | ADR-0016 |
| 9 | docx only through Pandoc from the generated LaTeX | NORTHSTAR, ADR-0022 |
| 10 | UI in German and English, German default, through message codes | ADR-0023 |
| 11 | No separate agent identity on GitHub; no thesis deadline is tracked | this file |
| 12 | Stage 3: every co-author uses their own Claude Code; a small sync server shares the project | ADR-0018, supersedes ADR-0011 |
| 13 | People write through Yjs, agents through block proposals with claims and conflict detection | ADR-0017 |
| 14 | The mod bridges web app and Claude Code with an automatic token; skills start from the web chat | ADR-0019 |
| 15 | Autonomous work runs as resumable jobs with a plan-limit pause; accept-all needs a green check | ADR-0020 |
| 16 | v0.1 is the whole product; stages become internal milestones with their own proofs | ADR-0021 |
| 17 | LaTeX and PDF primary, docx through Pandoc, PDF/A and export bundle as options | ADR-0022 |
| 18 | Message codes with German and English text, German default | ADR-0023 |

## 2. Target picture

```
Browser (127.0.0.1): academic-research web app
  outline | editor (structured document, anchors, hover, PDF preview) | Claude panel
          |                                                           | chat, agents, proposals,
          |                                                           | trace check, wishlist, usage
  server (Hono, SQLite per project): evidence, export, sourcing, wishlist, proposals
        ^                                    ^
        | MCP tools                          | bridge (local HTTP)
Terminal: claude with the academic-research plugin
  mod: starts turns from the web chat, returns replies and agent status, runs autocomplete
  MCP server: search_sources, add_to_wishlist, search_library, get_passage, check_quote,
              get_outline, propose_edit, trace_check, compile
  skills: /recherche, /kapitel, /pruefen, /gliederung   agents: research, drafting, examiner
```

Rules that follow from it:

- The server never calls a model. Every model call happens in the user's Claude Code session.
- Claude edits the thesis only through `propose_edit`; it may look at the web app but never operate
  it. Every proposal carries model, feature, agent id and time; accept-all needs a green trace check.
- Autocomplete is a tool-less `$.model.complete` call after a typing pause (default 600 ms, Haiku;
  measured 1506 ms in the prototype). Defaults: autocomplete on, "check this" on a click on,
  per-paragraph review off, research only on a command; all configurable.
- Text from PDFs, transcripts and search results reaches Claude only as tool results marked
  untrusted (T33). Permission prompts stay in the terminal.
- Each supported Claude Code version gets a bridge test, because mods change between releases.

## 3. Goals and stages

- Goal G7 Sourcing is added (plan section 2): wishlist and library profile in milestone M1,
  search on a click and legal open-access download in milestone M2a.
- Stages become internal milestones M1, M2a, M2b, M3 and M5, each with its proof; v0.1 is tagged
  only when every milestone is green (ADR-0021). Stage 4 follows v0.1 unless the operator moves it.
- Stage 2 splits into 2a (own data and sources without a model) and 2b (copilot through the plugin).
- Stage 3 keeps collaboration with block-level authorship colours; each co-author runs their own
  Claude Code. The hosted profile becomes a sync and storage server.
- Stage 5 is part of v0.1: the whole-thesis pipeline runs on resumable jobs (ADR-0020), designed
  from measured costs (T45); provenance and the disclosure annex are mandatory there.

## 4. Architecture changes for stage 1

Numbers refer to the review (artifact "Plankritik academic-research", section 4).

| Area | Change |
| --- | --- |
| Anchors (1, 2, 3, 7, 9) | Range anchors per ADR-0014; matching on joined page text with an offset map; APA-permitted changes as typed spans; `locator-mismatch`; `stale` on hash or extractor change |
| Extraction (4, 5, 6) | Contract fixed before T15: normalised newlines, superscript and running-head spans, pdf.js with `disableNormalization: true`, U+FFFE as ambiguous dehyphenation, `isEvalSupported: false`; new state `unusable_text`; printed pages from page-label segments plus a confirmed metadata offset |
| Trace check (8) | Coverage line (quote, locus, unanchored, not checkable), `unanchored-direct-quote` listed, external-compile mode reported as not checked; hard guarantees per ADR-0016 |
| Library (10, 11) | New ticket T13a "library core" (`library_items`, `CslItem`, cite keys, Zotero `citationKey` taken when valid and unique); T13, T14 and T15 depend on it in parallel |
| Wiring (12, 15, 31) | T10 splits into T10a (server: security, session, project) and T10b (editor binding, sync, end-to-end); Hocuspocus through `upgradeWebSocket` of @hono/node-server; honest local threat model; 0700 data directory |
| Sync (13, 14) | Yjs 13.6 stays with a go/no-go point in T06; the Y.Doc is canonical with one conversion pair; log compaction moves to the start of stage 2a |
| Storage (16) | `node:sqlite` as default candidate, better-sqlite3 as fallback, Node pinned to 24.15 or later; integrity rules per ADR-0016 |
| Gates (17, 18) | New ratchet rules: network I/O in web only in adapters (R1, before T10b); unknown source extensions (R2) and a core import allowlist (R3) when first needed; migrations must use STRICT, foreign keys and CHECK |
| Export (21, 22, 23, 24) | Optional PDF/A-2b; container flags `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges --pids-limit --memory --cpus`; `.tex` import with raw LaTeX records a third-party import; export bundle (ZIP) as third compile path; docx through Pandoc in stage 4 |
| UI (19, 20, 36) | A UI ADR before T09a; message codes with German and English texts from T17a; keyboard and screen-reader access for hover card, picker and trace panel |
| Release (37, 38, 39) | Dependency updates, exit path (project format documented), bus factor stated in CONTRIBUTING; release pipeline T44c (issue #61) |

## 5. Stage 2b, redesigned for the plugin

| Ticket | New shape |
| --- | --- |
| T24 | Plugin skeleton: mod bridge (chat turns, replies, agent status, usage), MCP server with the evidence tools, version check of Claude Code; no keys, no usage meter in the server |
| T25 | The proposal validator runs inside `propose_edit`; numbers are checked sentence-locally |
| T26a, T26b | Proposals, accept-all with green trace check, change log with model, feature, agent id and time; block claims for concurrent agents |
| T27 | `search_library` tool; retrieval measurement with the operator's gold set; embeddings only after the measurement |
| T28 | Literature and data chat through the bridge, answers with passage chips |
| T31 | Outline and section drafts as skills, built on deterministic outline profiles and lints |
| T32 | Autocomplete through the mod with the measured quality gate |
| T33 | Injection hardening for every tool result that carries untrusted text |
| new | AI disclosure annex built by core from the change log |

## 6. v0.1 and waves

Milestone M1 needs 35 work packages plus the wishlist (N1) and the library profile (N2), in nine
waves. M2a adds own data, search and download (N6 to N8), the relevance filter and the screening
log; M2b the plugin, bridge and all AI functions; M3 shared projects, roles and concurrent agents;
M5 the whole-thesis pipeline. The ticket rework maps every ticket to a milestone label, a wave
label and one epic per capability; v0.1 is the sum of all milestones (ADR-0021).

## 7. Open questions for the operator

Answered on 2026-10-20, see §8. Still open: the TIB link resolver address (checked with the
profile's test link, ADR-0015) and the operator's request to Anthropic about the plugin's use of
the user's plan (ADR-0013); M2b is built in parallel and does not wait for the answer.

## 8. Decisions of 2026-10-20

| Topic | Decision | Record |
| --- | --- | --- |
| UI layer | Vanilla TypeScript DOM with a tested element builder; one ADR with message rendering, keyboard and layout as its rules; the agent proposes window width and shortcuts | ADR-UI (#67) |
| Templates | T07 writes generic memos with placeholders; universities follow later as profiles | T07 (#5) |
| Anthropic terms | The operator asks Anthropic; M2b is built in parallel | ADR-0013 |
| Personal data, prompts | Per-project opt-in for each, off by default | ADR-0025 |
| Sources without DOI or ISBN | Captured with a stored copy (web snapshot, law XML, scan), by form or with the assistant; only print-only quotes without a copy are "not checked" with a logged export confirmation | ADR-0024, N13 |
| docx | In M1 through Pandoc (T19b, T22) | ADR-0022 |
| Citation suggestion | Off by default; when switched on, Haiku may only reorder deterministic candidates | B4 (#71) |
| Stage 4 | Part of M5 and of v0.1 | ADR-0027 |
| New tickets | Methodology checklists (N14) and grey-literature capture (N13); no JOP check, no citation graph | ADR-0027 |
| Zotero | After v0.1 (`milestone:later`, #53) | ADR-0027 |
| S1 | Closed | ADR-0027 |
| T23 | An agent writes the dogfood chapter from CC-licensed articles; the operator reviews it | T23 (#25) |
| Plugin | `packages/plugin` in the workspace and the install entry point; bridge tested on the current and previous stable Claude Code | ADR-0028 |
| LanguageTool | Kept as an optional, switchable check after measurement | T34 (#37) |
| Gold set | An agent writes 30 questions from CC-licensed articles, a second agent checks them | T27 (#30) |
| Legal review | The operator checked open-access download, AI Act and library links for personal use; no further memos | N7, N8, N2 |
| Agent identity | Agents work as the operator; ADR-0003's last sentence is replaced | ADR-0026 |
