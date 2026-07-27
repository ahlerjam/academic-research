# Agents

[← zurück zur README](../../README.md)

Agents sind LLM-Subagents. Anders als Skills aktivieren sie sich nicht selbst — sie
werden von einem Command oder einem Skill gestartet und laufen in eigenem Kontext.
Das Plugin bringt **19 Agents** mit (`agents/*.md`).

## Recherche und Bewertung

| Agent | Model | Genutzt von | Aufgabe |
|-------|-------|-------------|---------|
| `query-generator` | Haiku | `/search` | Expandiert Suchquery auf Modulebene |
| `relevance-scorer` | Sonnet | `/search`, `/score` | Semantische Relevanz 0–1, 10er-Batches mit Prompt-Caching |
| `quote-extractor` | Sonnet | `citation-extraction` | Verbatim-Zitate via Citations-API + Vault-Write |
| `quality-reviewer` | Sonnet | `chapter-writer`, `abstract-generator` | Evaluator-Optimizer-Pattern (PASS/REVISE) |

## Buchbeschaffung

Der `book-fetcher` ist der Master-Orchestrator; er entscheidet, welche Site-Agents in
welcher Reihenfolge probiert werden. Details zur Fallback-Kette in
[commands.md](commands.md#academic-researchfetch).

| Agent | Model | Genutzt von | Aufgabe |
|-------|-------|-------------|---------|
| `book-fetcher` | Sonnet | `/fetch` | Master-Orchestrator: entscheidet Fallback-Reihenfolge für Site-Subagenten |
| `tib-fetcher` | Sonnet | `book-fetcher` | tib.eu per browser-use |
| `springer-book` | Sonnet | `book-fetcher` | link.springer.com per browser-use + HAN |
| `oapen-fetcher` | Sonnet | `book-fetcher` | oapen.org per browser-use |
| `doabooks-fetcher` | Sonnet | `book-fetcher` | directory.doabooks.org per browser-use |
| `degruyter` | Sonnet | `book-fetcher` | degruyter.com per browser-use + Shibboleth |
| `nationallizenzen` | Sonnet | `book-fetcher` | nationallizenzen.de per browser-use |
| `ebook-central` | Sonnet | `book-fetcher` | ebookcentral.proquest.com per browser-use |
| `kvk-fetcher` | Sonnet | `book-fetcher` | KVK Meta-Suche (80+ Kataloge) |
| `generic-fetcher` | Sonnet | `book-fetcher` | Discovery-Fallback, DOM-Heuristiken |
| `auth-helper` | Sonnet | alle Site-Agents | HAN / Shibboleth-WAYF / EZproxy Login-Flow |
| `scihub-fetcher` | Sonnet | `book-fetcher` | SciHub-Tier — läuft nur bei `scihub_optin: true` |

## Methodik und Verifikation

| Agent | Model | Genutzt von | Aufgabe |
|-------|-------|-------------|---------|
| `risk-of-bias` | Sonnet | `prisma-flow` | Cochrane RoB 2 / ROBINS-I / CASP |
| `meta-analysis` | Sonnet | direkt | DerSimonian-Laird Random-Effects + Forest-Plot |
| `figure-verifier` | Sonnet | `chapter-writer` | VLM-basierte Abbildungsverifikation |
