# academic-research: Plan (accepted 2026-10-17)

Status: accepted. The operator mandated an autonomous setup on 2026-10-17 ("work fully autonomously, make every open decision yourself"); every open fork of the draft was decided by the setup agent as a builder's call (section 10) and recorded as an ADR in `decisions/`. The operator can overturn any call with a new ADR. Supersedes `docs/plan/2026-10-08-belegnetz-design.md`. The authoritative ticket text lives in the GitHub issues (label `stage-N`, one tracking issue per stage); section 12 keeps the draft for traceability.

## 1. Intent & wedge

academic-research is a local-first, self-hostable writing tool for scientific theses. A structured editor holds citations, data numbers, interview quotes and cross-references as typed inline nodes and generates LaTeX/PDF through a university template, so that "nothing in the thesis without a trace" can be enforced by code: hovering a citation shows the verbatim PDF passage with printed page, a number is a live reference to an analysis of the user's own data, an interview quote points at a transcript line, and a supervisor agent reviews a chapter with deterministic rules first and advisory LLM judgment second. The first user is the operator's BWL bachelor thesis (APA, topic DevOps governance), then friends. Answer to the operator's question: a raw LaTeX editor is not the right primary format, because a free-text `.tex` buffer cannot validate that a citation resolves, a number came from data or a quote matches a transcript. LaTeX stays as generated output, a read-only source view and opaque raw blocks. Whether a CSL processor can render a German footnote style with "ebd." correctly is the central bet and is not claimed until spike T05 closes.

## 2. Goals / non-goals / anti-goals

Goals (v1, each done fully):
- G1 Structured editor with LaTeX export, university template (with a default-class fallback), selectable citation style, compile and PDF preview.
- G2 Zotero connection, PDF import (Zotero, local upload, BibTeX/RIS), hover-to-passage, deterministic quote check.
- G3 Own survey data (CSV/XLSX) and interview transcripts: live numbers, result tables, transcript quotes.
- G4 Copilot: find citations, chat with literature and data, section/TOC drafts, next sentence. All edits arrive as proposals.
- G5 Collaboration for friends with authorship colours (absent from export), named versions, backup/restore, offline local mode.
- G6 Supervisor: reproducible rule findings plus advisory LLM findings.
- G7 Sourcing: a wishlist for every source without a PDF, with links into the user's configured library (DOI, OpenURL link resolver, JOP/ZDB, catalogue template, WorldCat, interlibrary loan) and exports (HTML, CSV, RIS, CSL-JSON, BibTeX), all built by core without a network call (v0.1); source search on click over open metadata services (OpenAlex, Crossref, DNB, K10plus, EconBiz) with deterministic dedupe and legal open-access download with provenance (stage 2a). Operator decision 2026-10-19; design memo: research workflow wf_82b92c7e-f95.

Non-goals (operator, binding): supervisor submission package, reading-bridge cards, interview coding (Mayring), defense training, literature radar (no background search, subscriptions or alerts; search runs only on a click), argument map, gamification, MCP server, an own docx writer (docx comes through Pandoc from the generated LaTeX, operator decision 2026-10-19), custom text format, git as sync engine, automated download behind a library login.

Anti-goals (failure even if it works):
- A1 A quote, page number, statistic or quoted string reaches the document unchecked (enforced for free text by the proposal-time validator, T25, not only for cite keys).
- A2 Any authorship marker in `.tex`/`.pdf` (including PDF metadata).
- A3 "Verified" wording where only "string present at p. N" is proven. The UI says "trace check".
- A4 Silent fuzzy-accept of a quote, a guessed page, a silent in-place re-extraction.
- A5 Data loss: a crash or accept-all that cannot be restored.
- A6 A secret (LLM key, Zotero key) in logs, error reports, client bundle, Yjs, shared DB rows, exports or backups next to its master key.
- A7 Feature sprawl: any v1 item outside G1-G7.
- A8 Examiner results that differ between runs and block export.
- A9 A hover card or trace check that silently fails for a co-author who lacks the PDF (it must degrade visibly, T38).
- A10 The tool is correct but joyless: slow open, laggy ghost text, no keyboard flow (UX budgets in section 7).

## 3. Product surface

Screens: Project settings (language, template, CSL style, Zotero key, own LLM key, allow-LLM toggle); Editor (outline navigator, find/replace, word counts, hover cards, ghost text, proposal diff, comments in stage 3); Source view (read-only LaTeX with source map plus editable raw blocks); Library (Zotero + manual sources, PDF state per item); Data (datasets, codebook, analyses, transcripts); Preview (PDF.js, click-to-source); Copilot panel; Review (change log by author kind, revert); Examiner; Versions/Backup.

| Capability | Deterministic (code) | LLM |
|---|---|---|
| Quote check, printed page, normalisation | all | none |
| Citekey resolve, bibliography data/rendering | all | none |
| Numbers (datum), result tables, staleness | all | none (model may select an analysis id) |
| Transcript quote text | all | none |
| TOC, xref, trace check | all | none |
| Free-text validator (numerals, quoted strings, cite keys) | all | none |
| Retrieval (FTS5 BM25 + trigram) | all | optional Haiku rerank |
| Find citations | retrieval, id validation | rerank, rationale |
| Chat with literature/data | tool execution, passage copy | wording, tool choice |
| Section/TOC drafts | evidence assignment, validation | prose |
| Next sentence | prompt, validation | text |
| Examiner rule findings | all (can block export) | none |
| Examiner judged findings | labelling | one on-demand pass, advisory, never blocks |
| Authorship colours | all | none |
| Spell/grammar | browser baseline, LanguageTool sidecar (LGPL) | none |

## 4. Architecture

Winner: Candidate A (TypeScript end to end). Python appears only as an isolated worker, and only if T07 shows inferential statistics are needed (T35) or T04 selects pypdfium2.

### 4.1 Build vs extend and format rationale
Overleaf CE is AGPL and lacks comments, track changes, git and sandboxed compile; no extension API was verified; CoCalc is ruled out (archived, MS-RSL) (sources 11). So: build lean. A half-day check of TeXlyre's licence and maturity is ticket T07 (reference or base only if it passes). Format: ProseMirror (MIT) document in Yjs 13.6.x via y-prosemirror 1.x; Tiptap Pro, BlockNote xl, Lexical, Milkdown rejected (research).

### 4.2 Components
- `packages/core`: pure, never throws, rejections as values. normalize, decide_quote, escapeLatex, citekey, schema validation, serializer, TOC, validators, examiner rules, trace check, analysis formatting, prompt assembly.
- `packages/server`: Node, Hono or Fastify. Flows (load, decide, apply) and adapters (sqlite, zotero, llm, compile, pdf, fs). Node pin: nodejs.org lists v24 and v22 as LTS and v26 as Current (opened 2026-10-17); the page does not split Active from Maintenance LTS, so pin the v24 line and record the exact version at T02; Hocuspocus v4 needs 22+ (research).
- `packages/web`: ProseMirror, PDF.js, hover cards, review view.
- Compile worker (4.8). Python worker (conditional).
- SQLite WAL, one DB file per project plus one instance file; files on disk. Single server process, local disk.

### 4.3 Data model (numbered migration in the same PR as each table)
projects; yjs_updates (durable log); snapshots (named versions: plain canonical JSON per block plus content hash; no deduplicating object store); blocks (stable blockId); library_items (CSL-JSON, immutable citekey); sources (kind: pdf | print-no-pdf | scanned | user-transcribed; sha256; raw extracted text; extractor name+version stored as plain fields, no re-verify machinery until the first re-extraction happens; page labels or user offset; owner and `share_with_project` flag in stage 3); passages (sentence ids, page, offsets; FTS5); assets (figures: sha256, mime, size, project); datasets (hash, codebook); analyses (spec, dataset_hash, result, result_hash; engine and version stored as plain fields, no engine abstraction beyond one port); transcripts (turns); proposals; changelog (block-level before/after, author kind, user, proposal id, ts); usage (counter); users/sessions (stage 3). There is no llm_cache table in v1 (no response cache) and no per-source LLM flag; privacy uses one project-level toggle `allow_llm` (blocks sending interview/survey/PDF text; default off for transcripts and survey data).

Document schema. Blocks: heading, paragraph, list, table, figure+caption, mathBlock, footnote, blockquote, rawLatex, frontmatter. Inline atoms: `cite`, `datum`, `tquote`, `xref`, `math`. Every block has a stable blockId.
`cite` = `{mode: parenthetical | narrative | suppress-author, items: [{key, locator, label, prefix, suffix, anchorId?}]}` so "(Müller, 2020; Schmidt, 2021)", narrative form and suppress-author are representable; a single-source cite is a cluster of one. `datum` = `{analysisId, path, format}`. A `resultTable` block references an analysis and renders a table or chart from it. `tquote` = `{transcriptId, turnFrom, turnTo}`. A quote is not stored text; its text is rendered from the passage or turn range. Anchors use stable ids, never content hashes.

### 4.4 Sync, authorship, offline (one source of truth)
- Authorship v1 = block-level attribution derived from the changelog (T26 writes rows; T40 paints colours). That is the single structure. A span-level ledger (op-id ranges tagged server-side, Teleportal pattern documented by a third party; compatibility with Yjs 13.6 and y-prosemirror Nicht verifiziert) is an optional upgrade, tried only after T40 as a measured spike inside T40's backlog note; if it ever ships it refines block attribution and does not become a parallel store. The UI says "block-level" until then.
- Export, review and changelog never read span data. Mixed-author export is asserted byte-identical (T40).
- Offline: local mode (one user, localhost) works offline except LLM and Zotero calls. Hosted mode is online-only in v1; client-side persistence (y-indexeddb) and offline merge are deferred (section 9). The earlier "offline merge" tag claim is removed.
- Yjs update validation on the server is Nicht verifiziert feasibility: the research shows hooks exist (beforeHandleMessage, onChange, throw in onAuthenticate) but not that updates can be schema-checked before apply (onChange fires after apply). T39 is a spike; fallback = server-side snapshot validation with rollback to the last valid snapshot.

### 4.5 Proposals, accept-all, review (stage 2, T26)
Agent edits are proposals `{id, blockId, baseBlockHash, op, rationale, evidenceIds, model, influencedByExternalText}`; one Yjs transaction on accept; the accepting human is `acceptedBy`, not author. Accept-all (per-user policy) snapshots first, writes the same changelog rows, and NEVER auto-applies: proposals that add or change cite/datum/tquote/rawLatex nodes; delete operations; operations touching more than N blocks (N=3, judgment); proposals flagged `influencedByExternalText` (generated after retrieval of PDF/transcript text, which is all of them in practice, so the flag is displayed and the first three rules carry the safety). AI may not create or edit rawLatex at all. Review = changelog list filtered by author kind, block-level before/after, one "revert" (creates a proposal). It has no dependency on collaboration. Baselines, reviewed-ticks, per-hunk revert are later.
Git: operator asked to evaluate git as local history engine. Reasoning (T07 turns it into a one-page memo): the history units here are block-level changelog rows plus named snapshots; git adds a CLI dependency, line-based diffs that do not map to blocks or authors, and cannot delete interview data from history. isomorphic-git is community-maintained with limited development and lacks diff/blame in its listed commands (research). Decision proposed: not the history engine; optional one-way git export of named versions later. Operator confirms in fork F9.

### 4.6 Evidence layer (core)
1. Normalisation: one pure function for quote and source: NFC plus an explicit fold table (ligatures, quote/dash unification, NBSP, whitespace collapse, line-end dehyphenation flagged ambiguous). NFKC is avoided because UAX #15 states that NFKC removes formatting distinctions such as superscripts (https://unicode.org/reports/tr15/, opened); that "m²" folds to "m2" specifically is implied, not quoted, so T16 tests it. Offset map back to raw indices.
2. `decide_quote(quote, passage) -> Match{page, rawRange} | Rejected{reason}`; near misses are reported, never accepted.
3. Printed page: PDF /PageLabels (pypdf `page_labels`, pypdfium2 `get_page_label`) else a user-set offset; a page is never shown unless derived or set.
4. Citation rendering: cite nodes are style independent. Rendering path per T05 (CSL processor vs biblatex). A per-style capability table {note|in-text, page required for direct quote, ibid allowed, narrative supported} drives examiner rules, tested on APA 7, a German footnote style with "ebd.", IEEE. Nothing is claimed about "every style" before T05 closes; stage 1 ships with APA via the fallback.
5. Escaping (new, security-critical): every untrusted string that reaches LaTeX (Zotero titles/abstracts, transcript text, survey strings, AI-proposed text, xref labels, citekeys, datum formats, filenames) passes `escapeLatex` in core, with a property/fuzz gate (output contains no active control sequence from input, braces balanced, no `\input`, `\write18`, `\openin`, `\read`, catcode changes survive) and hostile fixtures for plain-text nodes, not only rawLatex.
6. Free-text proposal validator (T25), pure, runs before any proposal reaches the user (stage 2, before T27/T31/T32): rejects or flags any numeral pattern (percentages, decimals, n=, p-values, numerals beside statistics keywords) not backed by a datum node or a cited passage, any quoted string not equal to a checked quote or tquote, any cite key outside the retrieved set. Flag, not silent drop, for ambiguous cases. Test: gold file of 40 adversarial sentences.
7. Numbers: analysis = {dataset hash, spec, result, result_hash}; locale-aware format (3,4 DE / 3.4 EN); stale datum fails trace check; result tables render from the same analysis.
8. Trace check (export gate): cites resolve; quote anchors re-check; datum fresh; xrefs resolve; compile clean; template parts present; no authorship markers in `.tex`/PDF metadata; print-book sources reported as "declared, not checkable" (never silently untraced); manifest + hash. It states what it does not cover (does the passage support the claim).
9. Examiner: `rule` findings reproducible (can block), `judged` findings advisory (never block). Rules cover missing locator on direct quote, quote mismatch, unresolved key, stale/missing datum, bare numerals, narrative-vs-parenthetical misuse per style table, "ebd." only after a same-source note in note styles, ibid correctness. The "claim without evidence" check is judged. Stage 3 ships rules first (T42); judged is one LLM pass behind a button with no cache layer (T43).

### 4.7 Copilot and model access
- Anthropic Messages API behind `LlmPort`, official SDK. No Agent SDK, no claude binary, no MCP, no OAuth. The Agent SDK docs say third parties may not offer claude.ai login and must use API keys (https://code.claude.com/docs/en/agent-sdk/overview).
- Keys. Own key per user, never project-scoped, never in Yjs, shared DB rows, exports, or the client. Local: OS keychain; `.env` fallback lives outside the data directory (`~/.config/academic-research/`) and is excluded from backup and export. Hosted: per-user BYOK encrypted AES-GCM, master key outside the data dir and image. The Zotero API key gets the same treatment. Decrypt only in the adapter. WRITE-SECRET rule (new file) plus a redaction test cover logs, errors, and both keys. Recommend spend-limited keys. Shared operator key: not in v1; terms Nicht verifiziert (Commercial Terms not read).
- Models: Haiku 5.5 ($0.10/$0.50 per MTok to 100k prompt) for rerank and next sentence; Sonnet 5.5 ($2/$10) default writer/chat; Opus 5.5 ($4/$20) on request (https://platform.claude.com/docs/en/models/overview). German academic prose quality of Haiku-tier: Nicht verifiziert; T32 measures it before the feature is enabled by default.
- Grounding by reference: retrieval returns passages pre-split into numbered sentence ids; the model returns id ranges; code assembles text, page and cite node. Ids outside the retrieved set are dropped. The Citations API is not the trust anchor (incompatible with structured output, verified).
- Chat tools (5): search_library, get_passage, search_data (transcripts and survey open text, stage 2 after T30), list_analyses, propose_edit; plus read_outline folded into the prompt. Quote checks, cite resolution and datum lookup are code-side validators, not model tools. Max 3 tool rounds.
- Prompt injection: untrusted text delimited and flagged; chat/proposal output rendered as sanitized text (no markdown images or external links; CSP `img-src 'self' data:; connect-src 'self'` blocks external loads); accept-all limits (4.5); proposals carry `influencedByExternalText`; fixtures assert all of this (T33).

### 4.8 LaTeX, compile, install
- Serializer pure TS, golden-tested; source map outside the `.tex`; escaping per 4.6.5.
- Template: university template if the operator supplies it; fallback = default LaTeX class + biblatex-apa (requires biber, csquotes, biblatex>=3.4, https://ctan.org/pkg/biblatex-apa) so stage 1 never blocks on the Leibniz template.
- Engine: latexmk + real TeX Live, `-synctex=1 -interaction=nonstopmode -halt-on-error -no-shell-escape`. Not Tectonic (no built-in biber, issue #1267), not SwiftLaTeX (AGPL, dormant), texlive.js (dead), busytex (no biber), Typst (not LaTeX). URLs in section 11.
- Local compile is NOT "no sandbox is fine": `-no-shell-escape` is not a sandbox and does not stop file reads; restricted shell escape is not a sandbox (research). Plan: local default = the Docker image (which includes TeX Live) running compile in a no-network container with the project directory only; host-TeX mode is allowed with an explicit warning at import of any zip or third-party template (class/sty files are code) and with TeX's paranoid file policy (`openin_any`/`openout_any`) set; the effectiveness of that policy is Nicht verifiziert (TeX Live file-access docs not opened), so T20 tests it with hostile fixtures and the warning stays regardless.
- Install reality: measured image size is Nicht verifiziert (only the 2.6 GB full texlive image is sourced, https://hub.docker.com/r/texlive/texlive). T22 builds a scheme-small-plus-biber image, records size and time, and tests on macOS, Windows and Linux. State to the operator: a friend without Docker needs Docker Desktop or a host TeX install; there is no zero-dependency installer in v1.
- Hosted compile (T36, trusted-friends profile): one machine, throwaway no-network container per compile (read-only root, non-root, caps dropped, memory/CPU/pids limits, 60 s), worker takes only {projectId, contentHash} and fixed flags, no Docker socket reachable from the app (rootless runtime), per-user compile rate limit and queue cap. gVisor/VM isolation deferred (gVisor with TeX Live/biber Nicht verifiziert).
- Preview: PDF.js (Apache-2.0); click-to-source via `synctex` CLI plus source map.

### 4.9 Research layer
Zotero Web API v3 only (key header, `since` with 304, Backoff/429, max 4 concurrent, groups). Edge cases tested in T13: deleted items, multiple attachments per item, linked-file and WebDAV attachments that `/file` cannot serve (research: files via Zotero storage only), quota errors, group libraries. PDFs not in Zotero storage: manual upload (T14), visible "no PDF" state. Discovery/fetch (OpenAlex, Crossref, Unpaywall) is deferred, operator waiver requested (F8); citing stays library-only. Extraction: engine chosen by T04. pdfjs-dist is a candidate only: its npm licence is Nicht verifiziert (PDF.js is Apache-2.0), and advisories for code execution are Nicht verifiziert; T04 looks them up. Either engine runs in an rlimit-bounded, no-network subprocess, pinned and tracked. PyMuPDF excluded (AGPL, https://pymupdf.readthedocs.io/en/latest/about.html). Scanned PDFs without a text layer: detected, flagged "scanned", no OCR in v1; the user can attach a user-transcribed passage text labelled as such, or cite as print source. Retrieval: FTS5 BM25 + trigram; dense retrieval only if recall@10 < 0.8 on the gold set (backlog).

### 4.10 Security
- Local server: bind 127.0.0.1; reject requests whose Host is not `127.0.0.1:port`/`localhost:port` (DNS rebinding); require an Origin check on all state-changing HTTP and on WebSocket upgrade (cross-site WebSocket hijacking); the launcher opens `http://127.0.0.1:port/#code=<one-time>`; the page exchanges the code (URL fragment never reaches logs or referrers) for an HttpOnly, SameSite=Strict cookie; custom header required on mutating requests (CSRF). Same Origin check on hosted upgrade.
- Hosted auth (T37): admin bootstrap; invite link = 128-bit random, single use, 7-day expiry, stored hashed; password login (argon2id; library choice native vs WASM Nicht verifiziert, decided in T37); rate limiting and lockout; cookie Secure/HttpOnly/SameSite=Lax; password reset = admin-issued single-use link (no mail server). Departure from the research recommendation (Better Auth + passkeys, https://www.better-auth.com/docs/plugins/passkey): passkeys need a stable HTTPS origin and a custom invite flow anyway, and passwords work on a LAN host; passkeys remain later. Per-user LLM and compile rate limits.
- Sources and copyright: project-level sources with an explicit owner; PDFs are visible to project members only if the owner ticks `share_with_project` (T38). Otherwise the hover card for others shows "passage not available (source owned by X)" and the trace check marks that cite "unverifiable for you", never green. The LLM key is the caller's own; sharing material with the copilot is gated by the project's `allow_llm`. Publisher PDF licence terms for display to co-authors: Nicht verifiziert (arXiv never re-served: https://info.arxiv.org/help/api/tou.html).
- Tenant isolation: project_id enforced in one data-access layer; cross-tenant test (T38).
- Backups: encrypted archive (key from the OS keychain locally; hosted: key outside the data dir); contains PDFs and DB, never keys; restore drill. SQLite durability: Yjs log writes use `synchronous=FULL` in WAL (sqlite.org PRAGMA docs not opened: Nicht verifiziert, so T06's crash-injection test defines "no loss of acknowledged edits" empirically).
- Logging: one JSON line per unit of work with `status`, `duration_ms`; `X-Request-Id` returned; health endpoint; migrations tested upgrade-from-previous (T02, T12).

## 5. Tech stack

| Choice | Version | Reason |
|---|---|---|
| Node.js | v24 LTS line (nodejs.org lists v24 and v22 as LTS; Active vs Maintenance not shown) | one runtime; Hocuspocus v4 needs 22+ |
| Yjs / y-prosemirror | Yjs 13.6.x, y-prosemirror 1.3.x (research 1.3.7) | stable lines; v14 only RC |
| ProseMirror | pin at install (upstream moved 2026-04-07) | typed nodes, MIT |
| Hocuspocus | v4; MIT per research hooks page (https://tiptap.dev/docs/hocuspocus/server/hooks); embedding in Hono/Fastify Nicht verifiziert (T06) | auth hooks |
| SQLite WAL + FTS5 | driver Nicht verifiziert (better-sqlite3 vs node:sqlite, T06) | single file, install anywhere |
| PDF extraction | pdfjs-dist or pypdfium2 (T04) | by quote hit rate |
| Citation rendering | CSL processor (licence/version Nicht verifiziert) vs biblatex (T05) | all-CSL requirement |
| LaTeX | latexmk + TeX Live, dated tag when containerised | biber |
| PDF.js | Apache-2.0 | preview |
| LLM | Anthropic Messages API, official SDK | verified terms path |
| Validation | zod (judgment, no source) | typed tool/API boundaries |
| Tests | Vitest (judgment, no source) | TS gates |
| KaTeX | pin at install | math |

## 6. Token budget design

- Prompt assembly = pure function; stable prefix first behind `cache_control` (project brief, style rules, outline, library index), volatile context last.
- Verified multipliers (https://platform.claude.com/docs/en/about-claude/pricing): 5-min write 1.25x, 1-h write 2x, read 0.1x (0.05x Opus/Sonnet 5.5; Haiku read $0.01/MTok); Batch 50%. Minimum cacheable length on Haiku 5.5: Nicht verifiziert; T24 measures real cache hit rate and cost per feature with a usage meter. No response cache, no published cost-model docs in v1. Any dollar-per-suggestion figure is my arithmetic on list prices, excludes cache writes and tool rounds, and is not quoted in docs.
- Next sentence: explicit trigger or idle >= 1.5 s, in-flight cancel, max_tokens about 60, per-day cap; enabled by default only after T32's measurement.
- Chat: max 3 tool rounds, history compaction, top-k passages.
- Drafts: show estimated token count before the run; Batch only later.
- Per-user daily cap and usage meter are the only budget mechanisms.

## 7. Quality bar

Invariants (each a named test): quote check never accepts a non-substring (property test); `escapeLatex` fuzz; `.tex` byte-identical for any author mix; no page without derivation; citekeys never change; stale datum blocks trace check; accept-all never applies trace-node, delete or multi-block proposals; keys (LLM, Zotero) never in logs/errors/bundle/backup; AI never edits rawLatex; judged findings never block; proposal validator rejects the 40-sentence adversarial set.

Fixture strategy (copyright). CI uses synthetic and CC-licensed PDFs (generated with known quote/page pairs, ligatures, hyphenation, two-column, missing PageLabels) committed to the repo; the operator's real PDFs and the Leibniz template never enter the public repo or CI. A local script runs the operator's set and reports hit rate as a number recorded in T23's report. `proof.yml` therefore proves the synthetic set; the real-set number is a reported, not CI-enforced, figure.

Gold sets by the stage that needs them: stage 1: PDF quote/page set, serializer goldens (APA + fallback), escape/hostile-.tex fixtures, crash-injection, restore drill. Stage 2: recorded-LLM replay double, validator adversarial set, injection fixtures, retrieval recall set (30 queries), datum goldens vs hand-computed values. Stage 3: mixed-author export, cross-tenant test, examiner reproducibility (3 runs), e2e smoke (small, no skips).

Measurable UX budgets (fun): cold open to editable < 2 s on a 60-page document; keystroke-to-paint p95 < 50 ms; hover card p95 < 100 ms after first load; ghost text time-to-first-token p50 < 1.5 s and never shown after a newer keystroke; keyboard shortcuts for insert cite, accept/reject, next change; dogfood checklist item "would I open this again tomorrow" answered by the operator. (All thresholds are judgment.)

Repo gates (done by the bootstrap PR, ADR-0004):
- Kept from the agent-repo scaffold: GATES-ROLES, GATES-CONTROLS, BASH-GUARD, WRITE-SECRET, AGENTS-MD, ADR-FORMAT, SUPPRESS-COUNT, GATES-RATCHET, plus hooks (post-edit format and rules, stop gate), selftest, drift and sync.
- New TypeScript house rules (ast-grep, each with rule test and bad/good fixture): TS-CORE-NO-THROW, TS-CORE-DETERMINISTIC, TS-CORE-PURE, TS-TRY-ONLY-ADAPTER, TS-IO-ONLY-ADAPTER, TS-NO-DECISION-IN-FLOW, TS-NO-ANY, TS-NO-CONSOLE, TS-NO-INNERHTML, TS-DOC; text rules TS-SUPPRESS, TS-NO-SKIP, TS-COMMENT-FORM; budgets TS-BUDGET-FUNCTION/MODULE; repo rules TS-LAYOUT, TS-BEHAVIOUR, TS-DECIDE-TESTED, TS-TRANSLATE-TESTED, TS-FEATURES-INDEPENDENT, TS-ADAPTER-NO-FEATURE. ESLint strict-type-checked and tsc strict run in `make lint`/`make typecheck`; Vitest runs with `allowOnly: false` and a check that no test was skipped.
- Dropped: every PY-* rule (no Python component in v1). A Python worker, if T35 needs one, brings its rules back through the ratchet.
- CI: `.github/workflows/ci.yml` runs `make check-repo gates-selftest` and `make lint-ts typecheck test` on the own runners (`vars.RUNNER`), `proof.yml` runs `make check gates-selftest` plus `scripts/proof-stage-N.sh`; a stage is done when proof is green and the stage's checklist in section 8 is met. Former draft tickets T01 (operator migration) and T03 (minimal TS gates) are done by the bootstrap; T02 shrank to the server skeleton.

## 8. Stages and proof of done

No calendar claim is made: the earlier "weeks 1-6" had no basis. Order is by dependency; estimates are the operator's call after T02-T07 return. Rough size (judgment): T01-T03 a few days each but T01 needs the operator; stage 1 is the largest single block.

Stage 1, "write and compile one real chapter locally" (T01-T23). Cut to the dogfood path: monorepo, spikes, schema, editor basics (with spellcheck baseline, figures, find/replace, outline, word counts), persistence, settings and text import, versions/backup, Zotero, manual sources, PDF ingest, quote check, hover, serializer, template, compile, trace check, install. Proposals, the review view and the copilot are NOT in stage 1 (no AI yet). If T05 or the template is late, the fallback (default class + biblatex-apa) keeps the operator unblocked. Proof: (a) CI green on synthetic fixtures; (b) the operator writes a chapter, imports existing draft text, cites sources from Zotero and local PDFs, exports PDF with template or fallback; (c) real-PDF hit rate number reported (target judgment >= 90%); (d) crash-injection and restore drill pass; (e) dogfood checklist (T23).

Stage 2, "evidence wedge and copilot" (T24-T35). Proof: a chapter with a live number, a result table and a transcript quote; the copilot cannot emit a cite key outside the library and the validator rejects the adversarial set (tests); injection fixtures pass; retrieval recall@10 >= 0.8 on the 30-query gold set; accept-all review works; measured usage report; LanguageTool decision made.

Stage 3, "friends: hosting, collaboration, supervisor" (T36-T43). Proof: two users on a hosted instance edit, block-level colours show, export byte-identical, cross-tenant test green, a co-author without the PDF sees the degraded card, examiner rule findings identical across 3 runs.

Stage 4, "open-source readiness" (T44). Stage 5, "staged, not cut" (T45 and section 9).

## 9. Explicitly later (staged, not cut)

Ghostwriting whole theses (T45 plans the orchestrated pipeline; the build follows measured copilot cost); hardened hosted isolation (gVisor/VM); Python stats and .sav beyond T35's scope; dense retrieval; passkeys; review baselines and reviewed-ticks; client-side offline persistence for hosted mode; git export of named versions; Zotero local API; local-model adapter; docx transcripts and audio; OCR for scanned PDFs; shared operator key (needs terms answer); .tex import best effort; desktop packaging; span-level authorship; extraction versioning with re-verify reports and an analysis-engine abstraction (build on the first re-extraction or inferential test).

## 10. Builder's calls (decided 2026-10-17)

| Fork | Decision | ADR |
|---|---|---|
| F1 Licence | AGPL-3.0-only | 0012 |
| F2 Citation rendering for all CSL styles | style-independent cite nodes; path decided by spike T05 (CSL processor vs biblatex), biblatex-apa as fallback so stage 1 never blocks | 0009 |
| F3 Local compile | Docker image with TeX Live as the tested default; host TeX allowed with a warning | 0007 |
| F4 LaTeX source mode | read-only source view plus editable `rawLatex` blocks; no editable full-source mode in v1 | 0005 |
| F5 Authorship granularity | block-level from the change log; span-level later, measured | 0010 |
| F6 Inferential statistics | the operator answers in T07 (label `needs-operator`); T35 enters stage 2 only if needed | - |
| F7 Spell and grammar | browser spellcheck in stage 1; LanguageTool decision in T34 after a measurement | - |
| F8 Source discovery and fetch | superseded 2026-10-19 by G7: wishlist with library links in v0.1, search on click and legal open-access download in stage 2a | - |
| F9 Git as history engine | no; change log plus named snapshots, optional one-way git export later | 0010 |
| F10 Shared sources in collaboration | owner plus `share_with_project` flag; visible degradation for others | 0011 |
| F11 University template | operator supplies it when available (T07/T19, `needs-operator`); default class + biblatex-apa until then | 0007 |
| F12 Hosted auth | invites plus argon2id passwords; passkeys later | 0011 |
| F13 Stage 1 without AI | yes; proposals, review and copilot arrive in stage 2 | 0010 |
| F14 Shared operator key | not in v1; BYOK only until the Commercial Terms are read | 0008 |

Other builder's calls: TypeScript 6.0.x (typescript-eslint peer range), Node 24 with type stripping, pnpm with a 7-day minimum release age, Hono as HTTP framework (T02 may revisit before T06), ADR-0004..0012.

## Review decisions (appendix)

Fixed: dependency chain (T10 wires editor to server; T14 etc. deps explicit); T01 split into operator ADR task, skeleton+CI, minimal TS gates as new rule files; operator-performed gate migration; identity before collaboration (auth T37 before T40, hosting T36); free-text validator T25; chat split into literature (T28) and data (T30); stage 1 usable (settings, text import, local PDFs/BibTeX/RIS, assets, print-book and scanned states, spellcheck baseline); minimal review view moved to T26 without ledger; cite cluster/mode model fixed in T08; numbers pipeline (result tables, open text, T07 decision, conditional T35); install story with measured image and OS tests (T22); measurable acceptance criteria; stage 1 cut and fallback template; UX budgets; offline stated honestly; git evaluated in writing; OSS ticket T44; ops items; Zotero edge cases; examiner narrative/ebd. rules; stage 5 ghostwriting ticket T45; plan self-contained; escape function and fuzz gate; local compile caveat; local HTTP Host/Origin/token; prompt-injection output sanitisation, CSP, accept-all limits; collaboration/copyright model; Zotero key and .env handling, llm_cache removed; fixture strategy; Yjs validation spike with fallback; comments (T41) kept because commenter role exists; manual PDF upload; build-vs-extend line; hosted auth details; PDF subprocess mandatory; backups; missing source URLs (section 11); single authorship structure; examiner trimmed; privacy trimmed to one toggle; chat tools reduced to five; deferrals of extraction versioning and engine abstraction; test load sequenced by stage; trusted-friends compile profile with cut line; ghost text last in stage 2; NFKC and Node claims sourced or labelled.
Rejected or modified with reason: (1) "Move T17 to stage 2 and T31 dependency removal": accepted. (2) Pull T42 into stage 2 unconditionally: rejected; conditional on T07 because a TS descriptive engine plus a Python engine would be two numeric implementations, so the rule is one engine per analysis kind and T35 replaces the TS engine wholesale if it ships. (3) Waive LanguageTool: not waived, moved to stage 2 with measurement first (F7). (4) Better Auth/passkeys: not adopted in v1, reason in 4.10. (5) Per-source flags and consent mechanisms: reduced to one project toggle. (6) Live injection job: dropped, replay fixtures only. (7) Dedicated "published cost model" docs and response cache: dropped. (8) Git as engine: rejected with reasoning, operator confirms (F9). (9) Span ledger: demoted to optional upgrade; block-level is v1. (10) T43 dense retrieval and the Python spike are no longer v1 tickets; backlog notes in section 9 (T35 stays as the single conditional ticket). (11) Rate limiting per user kept only for compile and LLM in hosted mode. (12) Items the critics marked Nicht verifiziert (prices, cache multipliers, Citations incompatibility, licences, Zotero behaviour, arXiv terms, Teleportal) are carried with their research URLs and the label "research-verified, not re-opened by me"; the ones I opened this pass are Node releases and UAX #15.

## 11. Sources

Opened in this revision: Node.js release table https://nodejs.org/en/about/previous-releases (v24 and v22 LTS, v26 Current; Active/Maintenance split not shown); Unicode normalization https://unicode.org/reports/tr15/ (NFKC removes formatting distinctions such as superscripts).
From the research pass (not re-opened by me):
- Claude Code legal and compliance: https://code.claude.com/docs/en/legal-and-compliance ; authentication: https://code.claude.com/docs/en/authentication ; Agent SDK: https://code.claude.com/docs/en/agent-sdk/overview
- Models: https://platform.claude.com/docs/en/models/overview ; pricing/caching/batch: https://platform.claude.com/docs/en/about-claude/pricing ; Citations: https://platform.claude.com/docs/en/build-with-claude/citations
- Commercial Terms (not read, Nicht verifiziert): https://www.anthropic.com/legal/commercial-terms
- Overleaf CE: https://github.com/overleaf/overleaf ; comparison: https://docs.overleaf.com/on-premises/welcome/server-pro-vs.-community-edition ; sandboxed compiles: https://docs.overleaf.com/on-premises/configuration/overleaf-toolkit/server-pro-only-configuration/sandboxed-compiles
- CoCalc: https://github.com/sagemathinc/cocalc ; TeXlyre (snippets only): https://forum.typst.app/t/typarr-a-collaborative-self-hosted-editing-platform-around-typst/8914
- Yjs releases: https://github.com/yjs/yjs/releases ; attribution: https://raw.githubusercontent.com/yjs/yjs/main/attributing-content.md ; Teleportal (third-party): https://teleportal.tools/core-concepts/attribution/
- y-prosemirror: https://github.com/yjs/y-prosemirror ; ProseMirror: https://github.com/ProseMirror/prosemirror ; Tiptap pricing: https://tiptap.dev/pricing ; BlockNote: https://github.com/TypeCellOS/BlockNote
- Hocuspocus hooks: https://tiptap.dev/docs/hocuspocus/server/hooks
- texlive image: https://hub.docker.com/r/texlive/texlive ; install-tl: https://tug.org/texlive/doc/install-tl.html ; TeX Live guide (restricted shell escape): https://www.tug.org/texlive/doc/texlive-en/texlive-en.html
- Tectonic: https://github.com/tectonic-typesetting/tectonic ; biber issue: https://github.com/tectonic-typesetting/tectonic/issues/1267
- SwiftLaTeX: https://github.com/SwiftLaTeX/SwiftLaTeX ; busytex: https://github.com/busytex/busytex ; texlive.js: https://github.com/manuels/texlive.js ; Typst bibliography: https://typst.app/docs/reference/model/bibliography/
- biblatex-apa: https://ctan.org/pkg/biblatex-apa ; https://github.com/plk/biblatex-apa
- PDF.js: https://mozilla.github.io/pdf.js/examples/ ; gVisor: https://gvisor.dev/docs/
- Zotero Web API: https://www.zotero.org/support/dev/web_api/v3/basics ; https://www.zotero.org/support/dev/web_api/v3/file_upload
- arXiv terms: https://info.arxiv.org/help/api/tou.html
- pypdfium2: https://pypdfium2.readthedocs.io/en/stable/python_api.html ; pypdf: https://pypi.org/project/pypdf/ ; PyMuPDF licence: https://pymupdf.readthedocs.io/en/latest/about.html
- SQLite FTS5: https://sqlite.org/fts5.html ; WAL: https://sqlite.org/wal.html
- Quarto visual editor: https://quarto.org/docs/visual-editor/ ; LanguageTool: https://github.com/languagetool-org/languagetool ; isomorphic-git: https://github.com/isomorphic-git/isomorphic-git ; Better Auth passkey: https://www.better-auth.com/docs/plugins/passkey

## 12. Ticket drafts (superseded by the GitHub issues)

Labels use stage-N, area:*, type:*. Each ticket: Goal, Acceptance, Notes, Depends.

### Stage 1

**T01 (done by the bootstrap PR) Operator: scaffold migration decisions** [stage-1, area:quality, type:chore] Depends: none. Goal: operator performs the Python-to-TS scaffold migration that agents may not do. Acceptance: ADRs merged for SQLite instead of Postgres, TS role idiom, looser idiom for editor/Yjs glue; `gates/controls.json` edits (if any) committed by the operator; AGENTS.md Python section and stop gate updated; `make gates-selftest` green after. Notes: blocks T02; agents supply draft ADR text as patches in their report only.

**T02 TS monorepo, Makefile, CI, health, logging** [stage-1, area:infra, type:chore] Depends: T01. Goal: empty but green TS workspace. Acceptance: packages core/server/web build; `make fix lint typecheck test-core check` run TS; compose has no Postgres; `proof.yml` runs the TS job and is green; `/health` returns 200; every request logs one JSON line with status and duration_ms and returns X-Request-Id (test); a migration-runner test upgrades a v(n-1) DB to v(n); Node version pinned and recorded. Notes: no feature code.

**T03 (done by the bootstrap PR) Minimal TS gates as new rule files** [stage-1, area:quality, type:chore] Depends: T02. Goal: enforce the core contract. Acceptance: new YAML rules each with test and bad/good fixture and catalog entry: core purity and no-throw, try/catch only in adapters, decide_*/translate_* asserted, no-any, WRITE-SECRET; no existing rule edited; `make gates-selftest` green. Notes: do not port more; each rule is a ratchet addition.

**T04 Spike: PDF extraction engine** [stage-1, area:data, type:spike] Depends: T02. Goal: choose pdfjs-dist or pypdfium2 and fix the fixture strategy. Acceptance: 30 synthetic/CC PDFs with known quote/page pairs in repo; both engines run in a no-network rlimit subprocess; decide_quote-style hit rate and page-label support reported per engine; pdfjs-dist npm licence and security advisories looked up and linked; written go/no-go with the pass line hit rate >= 90% (judgment); local script reports the same number on the operator's PDFs. Notes: operator PDFs never committed.

**T05 Spike: citation rendering path and template** [stage-1, area:export, type:spike] Depends: T02. Goal: decide CSL-processor vs biblatex and produce the style capability table. Acceptance: APA 7 and a German footnote style with "ebd." render in-text/footnotes/bibliography through the chosen path and compile with the default class; the same attempt with the Leibniz template if supplied, else recorded as pending; processor licence and version recorded; capability table committed and tested on APA, German footnote, IEEE; written decision; cite node shape confirmed compatible. Notes: fallback if undecided = biblatex-apa.

**T06 Spike: Hocuspocus embed, sqlite driver, durability** [stage-1, area:sync, type:spike] Depends: T02. Goal: prove the sync/storage base. Acceptance: Hocuspocus embedded in the chosen HTTP framework or documented fallback process; driver chosen with install test on macOS, Windows, Linux; crash-injection test (kill -9 during edits, restart): no loss of acknowledged edits, with the synchronous setting used recorded; written go/no-go. Notes: update validation is T39, not here.

**T07 Spike: decision memos** [stage-1, area:data, type:spike] Depends: none. Goal: close open operator-input questions. Acceptance: list of analyses the thesis needs (descriptives only vs t-test/correlation/chi-square/.sav) written by the operator; TeXlyre licence and maturity checked (half day) with verdict; one-page git-as-history memo; template availability noted. Notes: feeds F6, F9, F11.

**T08 Document schema** [stage-1, area:editor, type:feature] Depends: T02. Goal: the node set from 4.3 with validation. Acceptance: ProseMirror schema and a pure core validator; cite = cluster with mode, items with locator/label/prefix/suffix; datum, resultTable, tquote, xref, figure, rawLatex, footnote, math, frontmatter; blockIds stable across edits; tests: "(Müller, 2020; Schmidt, 2021)", narrative, suppress-author documents round-trip validation; schema version field. Notes: renderer-independent.

**T09 Editor basics** [stage-1, area:editor, type:feature] Depends: T08. Goal: a pleasant writing surface. Acceptance: headings/lists/tables/footnotes/math/figure insert, edit, undo/redo each covered by a named Vitest/Playwright test; asset upload stores images (sha256, mime, size limit) and figure node references them; outline navigator with move-section; find/replace; per-chapter word count; spellcheck uses the browser baseline with language per block; keyboard shortcuts for common nodes; keystroke-to-paint p95 < 50 ms and cold open < 2 s on a 60-page synthetic document. Notes: UX budget from section 7.

**T10 Persistence wiring and local security** [stage-1, area:sync, type:feature] Depends: T06, T08, T09. Goal: the editor loads and saves through the server. Acceptance: y-prosemirror binding + Hocuspocus connection + load/save from SQLite; reload shows all edits (test); server binds 127.0.0.1, rejects wrong Host and Origin on HTTP and WebSocket upgrade (tests with forged headers), one-time code in URL fragment exchanged for HttpOnly SameSite=Strict cookie, mutating requests need custom header; CSP set. Notes: hosted variant is T36.

**T11 Project settings and import of existing text** [stage-1, area:editor, type:feature] Depends: T10. Goal: configure and bring drafts in. Acceptance: settings screen stores language, template, citation style, Zotero key (encrypted, redacted from logs per test), own LLM key field (stored only, used in T24); import of Markdown and pasted text and best-effort .tex into blocks, unknown constructs become rawLatex, with a golden test on 3 sample files; import never runs TeX. Notes: Word text arrives via paste.

**T12 Named versions, backup, restore** [stage-1, area:data, type:feature] Depends: T10. Goal: no data loss. Acceptance: named snapshot create/list/restore (plain canonical JSON per block + hash); automatic snapshot before restore; encrypted backup archive (PDFs + DB, no keys) and restore drill test; forward migration test from previous schema; crash-injection test in CI. Notes: master key from OS keychain locally.

**T13 Zotero sync** [stage-1, area:zotero, type:feature] Depends: T02, T06. Goal: library in the app. Acceptance: Web API v3 incremental sync with since/304, Backoff/429, max 4 concurrent; user and group libraries; tests with recorded fixtures for deleted items, multiple attachments per item, linked-file/WebDAV attachments reported as "file not downloadable", quota error; persisted immutable citekeys (never regenerated, test); PDF download with ETag check. Notes: key never logged.

**T14 Manual sources and source states** [stage-1, area:zotero, type:feature] Depends: T13. Goal: every cite has an honest source state. Acceptance: local PDF upload attached to a library item; BibTeX and RIS import creates items; states pdf | print-no-pdf | scanned | user-transcribed shown in the library; trace check inputs expose each state; scanned PDFs detected (no text layer) and flagged; fixtures for each state. Notes: no OCR in v1.

**T15 PDF ingest pipeline** [stage-1, area:evidence, type:feature] Depends: T04, T13. Goal: PDFs become searchable passages. Acceptance: extraction in subprocess with rlimits and no network (hostile/corrupt PDF fixture terminates cleanly); per-page text, page labels, passages with sentence ids and offsets, FTS5 BM25 + trigram search; extractor name and version stored; 100-page PDF ingests with progress and no UI block. Notes: engine from T04.

**T16 Normalisation and decide_quote** [stage-1, area:evidence, type:feature] Depends: T04. Goal: the deterministic quote check. Acceptance: pure functions with offset map; property test: never accepts a non-substring; fold table tests including "m²" vs "m2" not matching, ligatures, dehyphenation ambiguity returned as flagged; near-miss reports first differing token; hit rate on the synthetic PDF set meets the T04 line. Notes: NFC plus fold table, not NFKC.

**T17 Cite insertion and hover card** [stage-1, area:evidence, type:feature] Depends: T08, T09, T13, T15, T16. Goal: the first wedge feature. Acceptance: insert cite cluster (parenthetical/narrative/suppress-author, locator, prefix/suffix) from library via keyboard; hover shows verbatim passage and printed page (or the source-state message); p95 hover < 100 ms after first load; a page is never shown unless derived or user-set (test). Notes: UI wording "string present at p. N".

**T18 LaTeX escaping and serializer** [stage-1, area:export, type:feature] Depends: T03, T05, T08. Goal: safe, deterministic export. Acceptance: `escapeLatex` core function with property/fuzz test and hostile fixtures in plain-text nodes (`\input{/etc/passwd}`, `\write18`, unbalanced braces) produce inert text; serializer output golden-tested; source map line to blockId outside the `.tex`; `.tex` identical for any author metadata. Notes: Zotero titles, transcripts, labels, citekeys all escaped.

**T19 Template and citation rendering** [stage-1, area:export, type:feature] Depends: T05, T13, T18. Goal: title page, lists, declaration, bibliography. Acceptance: default class + biblatex-apa fallback works end to end; university template package if supplied; frontmatter generated from project metadata; chosen rendering path from T05 produces citations and bibliography for APA; template-required parts checked.

**T20 Compile and preview** [stage-1, area:export, type:feature] Depends: T19. Goal: PDF from the document. Acceptance: latexmk with fixed flags; container-first compile with no network; host-TeX mode shows a warning on first use and on importing a zip/template; hostile .tex fixtures (`\input` of a host file, `\openin`) do not leak host content into the PDF in container mode; paranoid-policy effectiveness for host mode recorded as measured; PDF.js preview; errors mapped to blocks; click-to-source via synctex; recompile on idle.

**T21 Trace check** [stage-1, area:evidence, type:feature] Depends: T16, T17, T20. Goal: pre-export gate. Acceptance: pure checklist from 4.6.8; print-book sources listed as "declared, not checkable"; unresolved cite, mismatched quote, missing xref each fail with a named test; PDF/`.tex` metadata contain no authorship marker (test); UI says "trace check" and lists what it does not cover.

**T22 Install: launcher and Docker image** [stage-1, area:infra, type:feature] Depends: T20. Goal: honest install story. Acceptance: one command starts the server and opens the page; Docker image with TeX Live (scheme-small + biber + biblatex-apa) with measured size and build time recorded; smoke test passes on macOS, Windows, Linux; README states prerequisites and that a friend needs Docker or host TeX.

**T23 Dogfood stage 1** [stage-1, area:quality, type:chore] Depends: T21, T22, T11, T12, T07. Goal: the operator uses it for the thesis. Acceptance: operator writes and exports a chapter; real-PDF hit rate number recorded; checklist: cold open, shortcuts, crash recovery, restore, import of existing draft, and the answer "would I open this tomorrow"; defects filed as tickets with severity.

### Stage 2

**T24 LlmPort, keys, usage, prompt assembly** [stage-2, area:copilot, type:feature] Depends: T02, T10. Goal: model access. Acceptance: Anthropic Messages API adapter behind a port with in-memory replay double; keys per user (keychain or `.env` outside data dir, excluded from backup/export, tests); redaction test over logs and errors for LLM and Zotero keys; `allow_llm` project toggle blocks sending PDF/transcript/survey text (test); prompt assembly pure with cached prefix; usage meter and per-user daily cap; measured cache hit rate and cost per feature reported.

**T25 Proposal-time validator** [stage-2, area:copilot, type:feature] Depends: T08, T16. Goal: A1 for free text. Acceptance: pure `validateProposal` rejects/flags numerals not backed by datum or cited passage, quoted strings not equal to checked quote/tquote, cite keys outside retrieved set; 40-sentence adversarial gold file passes (all bad rejected, all good accepted); DE and EN numerals.

**T26 Proposals, change log, review, accept-all** [stage-2, area:copilot, type:feature] Depends: T08, T10. Goal: the merge-request-like review. Acceptance: proposal diff accept/reject; accept-all snapshots first, never auto-applies cite/datum/tquote/rawLatex, delete ops, ops over 3 blocks (tests); change log list filtered by author kind (human/friend/AI) with block before/after and revert-as-proposal; AI cannot touch rawLatex (test); stale proposals marked.

**T27 Find citations** [stage-2, area:copilot, type:feature] Depends: T24, T25, T15. Goal: cite finder. Acceptance: selected sentence returns top passages from FTS5 with optional Haiku rerank; recall@10 >= 0.8 on a 30-query gold set from the operator's library (judgment), else dense retrieval spike opened; only library items can be inserted; insertion shows hover preview.

**T28 Literature chat** [stage-2, area:copilot, type:feature] Depends: T24, T25, T15, T26. Goal: chat with literature. Acceptance: tools search_library, get_passage, propose_edit; max 3 rounds; answers carry passage chips opening the PDF page; faithfulness: >= 95% of answer claims on a 30-question gold set map to retrieved passage ids, others flagged (judgment); no dependency on survey import.

**T29 Datasets, analyses, datum, result tables** [stage-2, area:data, type:feature] Depends: T08, T10, T21. Goal: wedge 2 numbers. Acceptance: CSV/XLSX import with codebook; open-text columns stored as free text and excluded from numeric analyses; descriptives (counts, mean, SD, frequencies, crosstab) with goldens vs hand values; datum node and resultTable block render from analyses with DE/EN formatting; dataset change marks datum stale and trace check fails; one numeric engine behind one port.

**T30 Transcripts, tquote, data chat** [stage-2, area:data, type:feature] Depends: T28, T29, T24. Goal: interviews and data in chat. Acceptance: txt/vtt/srt parse to turns; tquote renders text from the range; transcripts and survey open text indexed in FTS5; chat gains search_data and list_analyses; `allow_llm` off blocks them (test); quotes from transcripts pass the validator.

**T31 Section and TOC drafts** [stage-2, area:copilot, type:feature] Depends: T26, T25, T27, T28. Goal: copilot writes sections. Acceptance: outline proposal and per-section draft proposals with evidence assigned from retrieved passages; every draft passes T25; token estimate shown before the run; accepted drafts appear in the change log as AI.

**T32 Next-sentence ghost text** [stage-2, area:copilot, type:feature] Depends: T27, T28, T25. Goal: IDE-like suggestion. Acceptance: explicit trigger or idle >= 1.5 s; cancel on keystroke; time-to-first-token p50 < 1.5 s; suppressed inside nodes; output validated (T25); measured cost per accepted suggestion reported; operator blind-rates 20 German suggestions, enabled by default only if >= 70% usable (judgment).

**T33 Injection hardening** [stage-2, area:quality, type:feature] Depends: T28, T26. Goal: prompt-injection safety. Acceptance: output rendered as sanitized text, no external images/links, CSP blocks external loads (Playwright test); fixtures (PDF/transcript with "ignore previous instructions", markdown image to attacker URL, deletion request) replayed through recorded responses assert: no external request, accept-all does not apply the proposal, `influencedByExternalText` set.

**T34 LanguageTool** [stage-2, area:editor, type:feature] Depends: T10. Goal: DE/EN grammar. Acceptance: first measure RAM and German detection on a 50-sentence error set and document integration feasibility; if acceptable, sidecar behind a port with decorations per paragraph, nodes masked; otherwise record the waiver and keep browser spellcheck.

**T35 Conditional: Python analysis engine** [stage-2, area:data, type:feature] Depends: T29, T07. Goal: inferential tests only if T07 requires them. Acceptance: if T07 lists only descriptives, ticket closed as not needed; else pinned pandas/scipy worker (no network, rlimits) replaces the TS engine for all analyses behind the same port, .sav via pyreadstat, results match R/SPSS on the operator's survey within rounding, engine and version stored.

### Stage 3

**T36 Hosted profile** [stage-3, area:infra, type:feature] Depends: T22, T23. Goal: a friend-ready server. Acceptance: compose profile with TLS reverse proxy and documented domain; WebSocket origin check; no-network throwaway compile container, rootless runtime, worker takes only {projectId, contentHash}, per-user compile rate limit and queue cap (flood test); health check; documented trusted-friends cut line.

**T37 Hosted auth** [stage-3, area:auth, type:feature] Depends: T36, T10. Goal: identity. Acceptance: admin bootstrap; 128-bit single-use hashed invites expiring in 7 days; argon2id (library choice recorded and installed on all OSes); login rate limit and lockout; Secure/HttpOnly cookies; admin-issued password reset; roles owner/editor/commenter; per-user LLM rate limit; tests for each.

**T38 Shared sources and tenant isolation** [stage-3, area:data, type:feature] Depends: T37, T15, T13. Goal: collaboration vs copyright. Acceptance: sources have owner and `share_with_project`; non-owner hover shows "passage not available (owner X)" and trace check says "unverifiable for you"; LLM key always the caller's; cross-tenant test (user A cannot read project B via any API); project_id enforced in one data layer.

**T39 Spike: Yjs update validation** [stage-3, area:sync, type:spike] Depends: T10, T06. Goal: bad updates cannot corrupt a shared doc. Acceptance: test whether schema/size validation is possible before apply (scratch-doc apply) with the Hocuspocus hooks; else implement fallback of snapshot validation with rollback to the last valid snapshot; hostile-client test sends oversize and off-schema updates.

**T40 Collaboration and authorship colours** [stage-3, area:sync, type:feature] Depends: T37, T39, T26, T21. Goal: write together. Acceptance: two users edit live; block-level colours (human, friend, AI) painted from the change log; UI says "block-level"; export `.tex` byte-identical for mixed vs single author (test); no authorship marker in PDF; offline editing explicitly absent in hosted mode. Notes: span-level ledger only as later measured upgrade.

**T41 Comments** [stage-3, area:editor, type:feature] Depends: T40. Goal: the commenter role works. Acceptance: anchored comment threads on blocks, resolved state, commenter can comment but not edit (test); comments never appear in export.

**T42 Examiner rules** [stage-3, area:quality, type:feature] Depends: T16, T21, T05, T08. Goal: reproducible supervisor findings. Acceptance: rules from 4.6.9 including narrative-vs-parenthetical and "ebd." per capability table, tested on APA, German footnote, IEEE; bare-numeral rule with per-project exceptions; identical findings in 3 runs; only rule findings can block export.

**T43 Examiner judged pass** [stage-3, area:copilot, type:feature] Depends: T42, T28, T24. Goal: advisory LLM review. Acceptance: one on-demand pass per chapter behind a button; findings labelled judged with model and version; never block export (test); no cache layer; counter-position, overclaiming, weak logic prompts; claim-without-evidence reported as judged.

### Stage 4 and 5

**T44 Open-source readiness** [stage-4, area:quality, type:chore] Depends: T23, T36. Goal: publishable repo. Acceptance: LICENSE per F1; contribution and install docs (README tested on three OSes); dependency licence report with PyMuPDF excluded and pdfjs-dist npm licence recorded; no operator PDFs or template in the repo (scan).

**T45 Ghostwriting pipeline plan** [stage-5, area:copilot, type:spike] Depends: T31, T26, T24. Goal: whole-thesis drafting, staged. Acceptance: written design (outline, evidence plan, per-section drafts as a reviewable proposal branch, Batch for non-interactive steps, token budget from measured stage-2 costs, operator approval gate per chapter); no code.
