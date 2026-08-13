# Agents

[← Doku-Übersicht](../README.md)

Agents sind LLM-Subagents. Anders als Skills aktivieren sie sich nicht selbst — sie
werden von einem Command oder einem Skill gestartet und laufen in eigenem Kontext.
Das Plugin bringt **21 Agents** mit (`agents/*.md`).

Die Dispatch-Spalte zeigt, wie ein Agent tatsächlich gestartet wird: **automatisch**
heißt, ein Command/Skill/anderer Agent löst ihn ohne weiteres Zutun aus (sobald der
Caller läuft); **manuell** heißt, es gibt keinen solchen Auslöser im Code — der Agent
wird nur gestartet, wenn er direkt per Task-Aufruf adressiert wird.

Wie in der [Skills-Referenz](skills.md) trägt jeder Eintrag dieselben drei Felder:
**Voraussetzung**, **Rückgabe** und **Fehlschlag erkennbar an**. Die Rückgabe ist bei
Agents durchweg ein festes Antwortformat — meist ein JSON-Objekt, das der aufrufende
Command oder Skill weiterverarbeitet.

## Recherche und Bewertung

| Agent | Model | Genutzt von | Dispatch | Aufgabe | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|-------|-------------|----------|---------|---------------|----------|-------------------------|
| `query-generator` | Haiku | `/search` | automatisch via `/search` | Expandiert Suchquery auf Modulebene | Suchbegriff des Nutzers; keine Tools nötig | JSON mit `queries` je Modul, `display_title` und `known_works_queries` | Antwort ohne `queries`-Objekt oder mit nur einer Modul-Variante |
| `relevance-scorer` | Sonnet | `/search`, `/score` | automatisch via `/search`, `/score` | Semantische Relevanz 0–1, 10er-Batches mit Prompt-Caching | Trefferliste mit Titel und Abstract plus die Suchfrage | JSON `scores[]` mit `doi`, `relevance_score` (0.0–1.0), `reasoning`, `confidence` | Weniger Score-Einträge als übergebene Treffer, oder ein Score außerhalb 0.0–1.0 |
| `quote-extractor` | Sonnet | `citation-extraction` | automatisch via `citation-extraction` | Verbatim-Zitate via lokalem PDF-Pfad (`Read` + `local-verbatim`), Citations-API nur noch Opt-in | Paper im Vault mit lesbarem lokalem `pdf_path` | JSON `quotes[]` mit `text`, `page`, `section`, Kontext und Score; Zitate landen per `vault.add_quote` im Vault | `vault.add_quote` lehnt mit `ValueError` ab (`no-match`/`no-textlayer`), oder `possible_pdf_mismatch` ist gesetzt |
| `quality-reviewer` | Sonnet | `chapter-writer`, `abstract-generator` | automatisch via `chapter-writer`, `abstract-generator` | Evaluator-Optimizer-Pattern (PASS/REVISE/ESCALATE) | Der zu prüfende Entwurf plus die Kriterien des Aufrufers | Block mit `VERDICT`, `BEGRÜNDUNG` je Kriterium, `EMPFEHLUNGEN` und `BLOCKIERT_VON` | `VERDICT` fehlt, oder `ESCALATE` kommt ohne Empfehlungsliste zurück |
| `screening-judge` | Sonnet | `parallel-screening` | automatisch via `parallel-screening` | Ein Treffer, ein Urteil: include/exclude/unclear als Ein-Fall-JSON | Genau ein Treffer mit Titel/Abstract und die Ein-/Ausschlusskriterien | Ein-Fall-JSON mit `paper_id`, `decision`, `reason`, `criterion`, `confidence`, `evidence` | Rahmentext um das JSON, mehrere Fälle in einer Antwort, oder `decision` außerhalb include/exclude/unclear |
| `sparring-partner` | Opus | direkt, `advisor`/`research-question-refiner`/`methodology-advisor` | manuell | Denk- und Impulsgeber: benennt Schwächen, Gegenpositionen und Anschlussfragen, schreibt keine Kapitel-Prosa | Vorgelegte Frage, These oder Argumentationslinie; Vault und `academic_context.md` optional | Fester Abschnittsblock `SCHWÄCHE` / `ALTERNATIVE` / `GEGENPOSITION` / `ANSCHLUSSFRAGEN` | Freier Fließtext statt der vier Abschnitte, oder erfundene Belege statt des Degradationspfads bei leerem Vault |

## Buchbeschaffung

Der `book-fetcher` ist der Master-Orchestrator; er entscheidet, welche Site-Agents in
welcher Reihenfolge probiert werden. Details zur Fallback-Kette in
[commands.md](commands.md#academic-researchfetch).

Von den 21 Agents greifen 8 als Site-Agent direkt auf fremde Verlags- oder
Archivseiten zu, plus `auth-helper` als Grenzfall (führt SSO-Logins gegen
Verlags-/Hochschulseiten aus, ist aber kein eigener Site-Agent). `book-fetcher`
selbst ruft keine fremde Seite auf — er ist reiner Dispatcher (Issue #612).
Sieben dieser acht sind auf genau eine Plattform zugeschnitten; der achte,
`generic-fetcher`, bedient als **Ultimate Fetcher** acht weitere Plattformen
über Site-Configs unter `config/browser_guides/` (Issue #840, Tabelle unten).
Die Spalte **Live-Test** hält fest, ob ein wöchentlicher Live-Lauf
(`.github/workflows/live-fetch-weekly.yml`) den Zugriffsweg belegt:

- **getestet** — verweist auf die konkrete Testdatei.
- **ungeprüft** — es existiert (noch) kein Live-Test.
- **n/a — kein Volltext-Host** — der Agent liefert strukturell kein PDF (Meta-Suche).
- **n/a — Dispatcher** — der Agent ruft selbst keine fremde Seite auf.
- **bewusst ungetestet (Opt-in)** — rechtlich heikler Zugriffsweg, Default OFF;
  ein Live-Test würde den Opt-in-Charakter unterlaufen (Scope-Out Issue #603).

Alle Site-Agents antworten im selben Schema: ein JSON-Objekt mit `status`, dem eigenen
Namen unter `source` und — nur bei `status: "success"` — dem `file_path`. Kommt die
Antwort vom Ultimate Fetcher mit einer Site-Config, trägt sie zusätzlich `site`.
Deshalb lautet das Fehlschlag-Signal überall gleich: `status` ist etwas anderes als
`success`, und `reason` nennt den Grund.

| Agent | Model | Genutzt von | Dispatch | Aufgabe | Live-Test | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|-------|-------------|----------|---------|-----------|---------------|----------|-------------------------|
| `book-fetcher` | Sonnet | `/fetch` | automatisch via `/fetch` | Master-Orchestrator: entscheidet Fallback-Reihenfolge für Site-Subagenten | n/a — Dispatcher | ISBN, DOI, Titel oder URL plus `output_path`; Uni-Profil optional | JSON mit `status` (`success`/`pickup_required`/`captcha`/`no_match`), `source`, `file_path` und der `tries`-Kette | `status` ist nicht `success`; die `tries`-Kette zeigt, welcher Subagent woran gescheitert ist |
| `tib-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | tib.eu per browser-use | ungeprüft | `browser-use` verfügbar; ISBN, DOI oder Titel plus `output_path` | JSON mit `status` (`success`/`metadata_only`/`no_match`), bei Erfolg `pdf_path` | `status` ist nicht `success` — `reason` nennt fehlenden Treffer oder fehlenden Volltext |
| `springer-book` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | link.springer.com per browser-use + HAN | ungeprüft | `browser-use`, Uni-Profil mit Springer-Lizenz für den Volltextpfad | JSON mit `status` (`success`/`metadata_only`/`no_match`/`pickup_required`/`captcha`), bei Erfolg `pdf_path` | `status` ist nicht `success`; `metadata_only` heißt fehlende Lizenz, `captcha` heißt Abbruch vor dem Download |
| `degruyter` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | degruyter.com per browser-use + Shibboleth | ungeprüft | `browser-use`, Uni-Profil mit De-Gruyter-Lizenz für den Volltextpfad | JSON mit `status` (`success`/`metadata_only`/`no_match`/`pickup_required`/`captcha`), bei Erfolg `pdf_path` | `status` ist nicht `success`; bei einer Login-Wall meldet der Agent zurück, statt selbst einzuloggen |
| `cambridge-core` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | cambridge.org/core per browser-use + Shibboleth | getestet (`test_issue_449_live_fetch.py`) | `browser-use`, Uni-Profil mit Cambridge-Lizenz für den Volltextpfad | JSON mit `status` (`success`/`metadata_only`/`no_match`/`pickup_required`/`captcha`), bei Erfolg `pdf_path` | `status` ist nicht `success` — `metadata_only` heißt fehlende Lizenz |
| `oxford-academic` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | academic.oup.com per browser-use + Shibboleth/OpenAthens | getestet (`test_issue_449_live_fetch.py`) — deckt nur den anonymen No-Login-Pfad ab, seit 2026-08-03 durch Cloudflare-Challenge gesperrt (Issue #612); der SSO-Pfad des Agenten selbst ist ungeprüft | `browser-use`, Uni-Profil mit Shibboleth/OpenAthens für den Volltextpfad | JSON mit `status` (`success`/`metadata_only`/`no_match`/`pickup_required`/`captcha`), bei Erfolg `pdf_path` | `status` ist nicht `success`; seit der Cloudflare-Challenge ist `captcha` der Regelfall ohne Login |
| `jstor` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | jstor.org per browser-use + Shibboleth (hohes Anti-Scraping) | getestet (`test_issue_449_live_fetch.py`) | `browser-use`, Uni-Profil mit JSTOR-Zugang | JSON mit `status` (`success`/`metadata_only`/`no_match`/`pickup_required`/`captcha`), bei Erfolg `pdf_path` | `status` ist nicht `success`; das hohe Anti-Scraping macht `captcha` wahrscheinlich |
| `generic-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` | Ultimate Fetcher: 5 Seitenzustände, Viewer-/Embed-Erkennung, Profil-Lizenzroute, hartes Schritt-Budget — mit `site_config` zusätzlich Site-Fetcher für die acht Plattformen der Tabelle unten | getestet (`test_issue_450_live_fetch.py`) — deckt HathiTrust, Internet Archive und MDZ über ihre Site-Configs ab; der guide-freie Fallback ist ungeprüft | `browser-use`; Eingabe-JSON mit `url` (oder auflösbarer `doi`/`isbn`) und `output_path` | JSON mit `status`, `source`, `file_path`, `reason` und dem `tries`-Protokoll je Schritt | `status` ist nicht `success`; das `tries`-Protokoll zeigt das erschöpfte Schritt-Budget |
| `auth-helper` | Sonnet | `book-fetcher` (bei Login-Wall) | automatisch via `book-fetcher` | HAN / Shibboleth-WAYF / EZproxy Login-Flow | ungeprüft | Profil-YAML mit Zugangsdaten, Dateirechte genau `0600`; `target_url` der Login-Wall | Meldung an `book-fetcher`, ob die Login-Wall überwunden ist; die Sitzung bleibt in browser-use bestehen | Abbruch wegen falscher Dateirechte am Profil, oder die Zielseite zeigt nach dem Flow weiterhin die Login-Wall |
| `scihub-fetcher` | Sonnet | `book-fetcher` | automatisch via `book-fetcher` (opt-in) | SciHub-Tier — läuft nur bei `scihub_optin: true` | bewusst ungetestet (Opt-in) | `scihub_optin: true` im aktiven Profil; ohne das bricht der Agent sofort ab | JSON mit `status` (`success`/`captcha`/`no_match`/`opted_out`/`error`), `provenance: "scihub"` und dem Provenance-Sidecar | `status: "opted_out"` (Opt-in fehlt) oder ein anderer Status als `success` |

Site-Agents wie `degruyter` oder `jstor` können `auth-helper` nicht selbst
starten (kein `Agent(auth-helper)`-Tool in ihrer Frontmatter) — sie melden nur eine
Login-Wall zurück; den tatsächlichen Aufruf macht ausschließlich der Master
`book-fetcher`. Für den `generic-fetcher` gilt dasselbe.

### Site-Configs des Ultimate Fetchers

Acht Plattformen haben seit Issue #840 keinen eigenen Agenten mehr. `book-fetcher`
ruft für sie `generic-fetcher` mit dem Parameter `site_config` auf; das gesamte
Site-Wissen (Discovery-Weg, Zugriffsstufen, Fallstricke, Quelle der
`edition`-Angabe) steht in der jeweiligen Datei unter `config/browser_guides/`.
Der Site-Schlüssel ist ihr Dateiname ohne `.md` und erscheint als `site` in der
Antwort und in der `tries`-Kette.

| Site | Site-Config | Stufe | Aufgabe | Live-Test |
|------|-------------|-------|---------|-----------|
| `doab` | `config/browser_guides/doab.md` | frei (Schritt 3) | directory.doabooks.org — OA-Aggregator ohne eigenen Volltext | ungeprüft |
| `oapen` | `config/browser_guides/oapen.md` | frei (Schritt 3) | oapen.org — reines OA-Repositorium | ungeprüft |
| `kvk` | `config/browser_guides/kvk.md` | frei (Schritt 3) | KVK Meta-Suche über 80+ Kataloge; Regelfall `metadata_only` mit Standorten unter `reason` | n/a — kein Volltext-Host |
| `hathitrust` | `config/browser_guides/hathitrust.md` | frei (Schritt 3) | catalog.hathitrust.org, nur Full-View-Digitalisate; liefert `edition` | getestet (`test_issue_450_live_fetch.py`) |
| `internetarchive` | `config/browser_guides/internetarchive.md` | frei (Schritt 3) | archive.org/openlibrary.org, kein Export von Borrow/CDL-Titeln; liefert `edition` | getestet (`test_issue_450_live_fetch.py`) |
| `mdz` | `config/browser_guides/mdz.md` | frei (Schritt 3) | digitale-sammlungen.de, Rechtehinweis ist Pflichtschritt; liefert `edition` | getestet (`test_issue_450_live_fetch.py`) |
| `nationallizenzen` | `config/browser_guides/nationallizenzen.md` | Verlag (Schritt 4) | nationallizenzen.de → Verlagsseite via DFN-AAI/Shibboleth | ungeprüft |
| `ebook-central` | `config/browser_guides/ebook-central.md` | Verlag (Schritt 4) | ebookcentral.proquest.com, Login immer nötig; DRM und Download-Limit erkennen | ungeprüft |

## Methodik und Verifikation

| Agent | Model | Genutzt von | Dispatch | Aufgabe | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|-------|-------|-------------|----------|---------|---------------|----------|-------------------------|
| `risk-of-bias` | Sonnet | `parallel-screening` | automatisch via `parallel-screening` | Cochrane RoB 2 / ROBINS-I / CASP | Paper im Vault mit erreichbarem PDF-Inhalt und bekanntem Studientyp | `assessment_id` aus `vault.add_risk_of_bias`; `domain_scores` je Domain mit `score`, `reasoning` und `quote_id` | Eine Domain ohne `quote_id`, oder `vault.add_risk_of_bias` wird nie aufgerufen |
| `meta-analysis` | Sonnet | direkt | manuell | DerSimonian-Laird Random-Effects + Forest-Plot | Effektgrößen und Varianzen je Studie, ausdrücklich bestätigt (`yi`/`vi`) | `kapitel/meta-analyse.md` mit Statistik-Tabelle, Mermaid-Forest-Plot, I², τ², gepooltem Effekt und 95 %-KI | Eine der vier Prüfpositionen fehlt in der Datei — etwa Forest-Plot ohne Pool-Node |
| `figure-verifier` | Sonnet | direkt | manuell | VLM-basierte Abbildungsverifikation | Paper im Vault mit lesbarem `pdf_path` | JSON je Figure (`figure_id`, `caption`, `vlm_description`) plus Zusammenfassung mit `unverifiable_pages` | Seiten landen in `unverifiable_pages`, mit `reason` wie „pdf_path fehlt" oder „OCR fehlgeschlagen" |
| `quote-fidelity-auditor` | Sonnet | direkt (Empfehlung aus `claim-drift-guard`-Warnung oder aus dem NLI-Batch-Vorfilter `academic_vault/nli_prefilter.py`, #592, Default AUS) | manuell | Urteilt über ein bestehendes Zitat gegen Kapitel-Behauptung, Quote-Kontext und Abstract; persistiert `quotes.stance` UND (additiv, immer, #737) die Audit-Historie `quotes.audited_at`/`audit_verdict`/`audit_severity` — Grundlage für `vault.chapter_quote_balance()` | Bestehende `quote_id` im Vault und die Kapitel-Behauptung, auf die sie sich stützt | JSON mit `verdict`, `severity` (feste Stufe `kritisch`/`hoch`/`mittel`, `null` bei `faithful`; #736), `stance_persisted`, `abstract_check`, `reasoning` und `recommendation` | `vault.set_quote_stance`/`vault.record_quote_audit` wirft `ValueError` (unbekannte `quote_id` oder ungültiger Wert), `stance_persisted` fehlt, oder `severity` fehlt/ist nicht der festen Verdict-Tabelle zugeordnet |
| `chunk-context-writer` | Sonnet | `/academic-research:fetch` (Schritt 4, nach `vault_add_paper`), auch direkt für einen Bestandsvault-Nachtrag | automatisch via `/academic-research:fetch`; manuell für den Nachtrag | Schreibt je ausstehendem Chunk eines Papers einen inhaltlichen Kontextsatz (≤ 25 Wörter, Sprache des Chunks) statt des deterministischen Metadaten-Satzes (#710/#783/#784) | Paper im Vault mit Chunks, deren `context_source` noch nicht `'model'` ist (`vault.pending_context_chunks`) | `vault.enrich_chunk_contexts`-Ergebnis mit `updated`-Liste (Chunk-IDs) und `skipped` (Grund je Item) | `status="embedder-unavailable"` (nichts geschrieben, kein Fehler) oder Einträge bleiben nach dem einen Korrekturdurchgang weiterhin in `skipped` |
