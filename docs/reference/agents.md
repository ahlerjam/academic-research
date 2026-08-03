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

Von den 28 Agents greifen 16 als Site-Agent direkt auf fremde Verlags- oder
Archivseiten zu, plus `auth-helper` als Grenzfall (führt SSO-Logins gegen
Verlags-/Hochschulseiten aus, ist aber kein eigener Site-Agent). `book-fetcher`
selbst ruft keine fremde Seite auf — er ist reiner Dispatcher (Issue #612). Die
Spalte **Live-Test** hält fest, ob ein wöchentlicher Live-Lauf
(`.github/workflows/live-fetch-weekly.yml`) den Zugriffsweg belegt:

- **getestet** — verweist auf die konkrete Testdatei.
- **ungeprüft** — es existiert (noch) kein Live-Test.
- **n/a — kein Volltext-Host** — der Agent liefert strukturell kein PDF (Meta-Suche).
- **n/a — Dispatcher** — der Agent ruft selbst keine fremde Seite auf.
- **bewusst ungetestet (Opt-in)** — rechtlich heikler Zugriffsweg, Default OFF;
  ein Live-Test würde den Opt-in-Charakter unterlaufen (Scope-Out Issue #603).

| Agent | Model | Genutzt von | Dispatch | Aufgabe | Live-Test |
|-------|-------|-------------|----------|---------|-----------|
| `book-fetcher` | Sonnet | `/fetch` | automatisch via `/fetch` | Master-Orchestrator: entscheidet Fallback-Reihenfolge für Site-Subagenten | n/a — Dispatcher |
| `tib-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | tib.eu per browser-use | ungeprüft |
| `springer-book` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | link.springer.com per browser-use + HAN | ungeprüft |
| `oapen-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | oapen.org per browser-use | ungeprüft |
| `doabooks-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | directory.doabooks.org per browser-use | ungeprüft |
| `degruyter` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | degruyter.com per browser-use + Shibboleth | ungeprüft |
| `nationallizenzen` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | nationallizenzen.de per browser-use | ungeprüft |
| `ebook-central` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | ebookcentral.proquest.com per browser-use | ungeprüft |
| `cambridge-core` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | cambridge.org/core per browser-use + Shibboleth | getestet (`test_issue_449_live_fetch.py`) |
| `oxford-academic` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | academic.oup.com per browser-use + Shibboleth/OpenAthens | getestet (`test_issue_449_live_fetch.py`) — deckt nur den anonymen No-Login-Pfad ab, seit 2026-08-03 durch Cloudflare-Challenge gesperrt (Issue #612); der SSO-Pfad des Agenten selbst ist ungeprüft |
| `jstor` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | jstor.org per browser-use + Shibboleth (hohes Anti-Scraping) | getestet (`test_issue_449_live_fetch.py`) |
| `kvk-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | KVK Meta-Suche (80+ Kataloge) | n/a — kein Volltext-Host |
| `hathitrust-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | catalog.hathitrust.org per browser-use, nur Full-View-Digitalisate | getestet (`test_issue_450_live_fetch.py`) |
| `internetarchive-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | archive.org/openlibrary.org per browser-use, kein Export von Borrow/CDL-Titeln | getestet (`test_issue_450_live_fetch.py`) |
| `mdz-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | digitale-sammlungen.de (Münchener Digitalisierungszentrum) per browser-use | getestet (`test_issue_450_live_fetch.py`) |
| `generic-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | Universeller Plattform-Navigator: 5 Seitenzustände, Viewer-/Embed-Erkennung, Profil-Lizenzroute, hartes Schritt-Budget | ungeprüft |
| `auth-helper` | Sonnet | `book-fetcher` (bei Login-Wall) | automatisch via `book-fetcher` | HAN / Shibboleth-WAYF / EZproxy Login-Flow | ungeprüft |
| `scihub-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` (opt-in) | SciHub-Tier — läuft nur bei `scihub_optin: true` | bewusst ungetestet (Opt-in) |

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
| `quote-fidelity-auditor` | Sonnet | direkt (Empfehlung aus `claim-drift-guard`-Warnung oder aus dem NLI-Batch-Vorfilter `academic_vault/nli_prefilter.py`, #592, Default AUS) | manuell | Urteilt über ein bestehendes Zitat gegen Kapitel-Behauptung, Quote-Kontext und Abstract; persistiert `quotes.stance` |
