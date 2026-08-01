# Agents

[← Doku-Übersicht](../README.md)

Agents sind LLM-Subagents. Anders als Skills aktivieren sie sich nicht selbst — sie
werden von einem Command oder einem Skill gestartet und laufen in eigenem Kontext.
Das Plugin bringt **28 Agents** mit (`agents/*.md`).

Die Dispatch-Spalte zeigt, wie ein Agent tatsächlich gestartet wird: **automatisch**
heißt, ein Command/Skill/anderer Agent löst ihn ohne weiteres Zutun aus (sobald der
Caller läuft); **manuell** heißt, es gibt keinen solchen Auslöser im Code — der Agent
wird nur gestartet, wenn er direkt per Task-Aufruf adressiert wird.

## Recherche und Bewertung

| Agent | Model | Genutzt von | Dispatch | Aufgabe |
|-------|-------|-------------|----------|---------|
| `query-generator` | Haiku | `/search` | automatisch via `/search` | Expandiert Suchquery auf Modulebene |
| `relevance-scorer` | Sonnet | `/search`, `/score` | automatisch via `/search`, `/score` | Semantische Relevanz 0–1, 10er-Batches mit Prompt-Caching |
| `quote-extractor` | Sonnet | `citation-extraction` | automatisch via `citation-extraction` | Verbatim-Zitate via lokalem PDF-Pfad (`Read` + `local-verbatim`), Citations-API nur noch Opt-in |
| `quality-reviewer` | Sonnet | `chapter-writer`, `abstract-generator` | automatisch via `chapter-writer`, `abstract-generator` | Evaluator-Optimizer-Pattern (PASS/REVISE/ESCALATE) |
| `screening-judge` | Sonnet | `parallel-screening` | automatisch via `parallel-screening` | Ein Treffer, ein Urteil: include/exclude/unclear als Ein-Fall-JSON |
| `sparring-partner` | Opus | direkt, `advisor`/`research-question-refiner`/`methodology-advisor` | manuell | Denk- und Impulsgeber: benennt Schwächen, Gegenpositionen und Anschlussfragen, schreibt keine Kapitel-Prosa |

## Buchbeschaffung

Der `book-fetcher` ist der Master-Orchestrator; er entscheidet, welche Site-Agents in
welcher Reihenfolge probiert werden. Details zur Fallback-Kette in
[commands.md](commands.md#academic-researchfetch).

| Agent | Model | Genutzt von | Dispatch | Aufgabe |
|-------|-------|-------------|----------|---------|
| `book-fetcher` | Sonnet | `/fetch` | automatisch via `/fetch` | Master-Orchestrator: entscheidet Fallback-Reihenfolge für Site-Subagenten |
| `tib-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | tib.eu per browser-use |
| `springer-book` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | link.springer.com per browser-use + HAN |
| `oapen-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | oapen.org per browser-use |
| `doabooks-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | directory.doabooks.org per browser-use |
| `degruyter` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | degruyter.com per browser-use + Shibboleth |
| `nationallizenzen` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | nationallizenzen.de per browser-use |
| `ebook-central` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | ebookcentral.proquest.com per browser-use |
| `cambridge-core` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | cambridge.org/core per browser-use + Shibboleth |
| `oxford-academic` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | academic.oup.com per browser-use + Shibboleth/OpenAthens |
| `jstor` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | jstor.org per browser-use + Shibboleth (hohes Anti-Scraping) |
| `kvk-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | KVK Meta-Suche (80+ Kataloge) |
| `hathitrust-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | catalog.hathitrust.org per browser-use, nur Full-View-Digitalisate |
| `internetarchive-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | archive.org/openlibrary.org per browser-use, kein Export von Borrow/CDL-Titeln |
| `mdz-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | digitale-sammlungen.de (Münchener Digitalisierungszentrum) per browser-use |
| `generic-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | Universeller Plattform-Navigator: 5 Seitenzustände, Viewer-/Embed-Erkennung, Profil-Lizenzroute, hartes Schritt-Budget |
| `auth-helper` | Sonnet | `book-fetcher` (bei Login-Wall) | automatisch via `book-fetcher` | HAN / Shibboleth-WAYF / EZproxy Login-Flow |
| `scihub-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` (opt-in) | SciHub-Tier — läuft nur bei `scihub_optin: true` |

Site-Agents wie `degruyter` oder `ebook-central` können `auth-helper` nicht selbst
starten (kein `Agent(auth-helper)`-Tool in ihrer Frontmatter) — sie melden nur eine
Login-Wall zurück; den tatsächlichen Aufruf macht ausschließlich der Master
`book-fetcher`.

## Methodik und Verifikation

| Agent | Model | Genutzt von | Dispatch | Aufgabe |
|-------|-------|-------------|----------|---------|
| `risk-of-bias` | Sonnet | `parallel-screening` | automatisch via `parallel-screening` | Cochrane RoB 2 / ROBINS-I / CASP |
| `meta-analysis` | Sonnet | direkt | manuell | DerSimonian-Laird Random-Effects + Forest-Plot |
| `figure-verifier` | Sonnet | direkt | manuell | VLM-basierte Abbildungsverifikation |
| `quote-fidelity-auditor` | Sonnet | direkt (Empfehlung aus `claim-drift-guard`-Warnung) | manuell | Urteilt über ein bestehendes Zitat gegen Kapitel-Behauptung, Quote-Kontext und Abstract; persistiert `quotes.stance` |
