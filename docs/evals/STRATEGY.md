# Eval-Strategie

[← Doku-Übersicht](../README.md)

Der Sollzustand für alles unter `evals/`: welche Komponente real gemessen wird, welche
nur strukturell geprüft ist und was echte Läufe an API-Budget kosten. Diese Seite altert
nicht wie ein Report — sie wird von einem Guard gegen das Dateisystem gehalten.

**Issue:** #390 — echte Qualitätsmetriken statt stillschweigender Schema-Checks
**Guard:** `tests/evals/test_eval_strategy.py` (prüft diese Tabelle gegen das Dateisystem)

---

## Warum dieses Dokument

Bis Issue #390 galt für `evals/` eine unausgesprochene Behauptung: 37 Komponenten
haben Evals, also ist die Qualität belegt. Das stimmte nicht. Ein Lauf ohne
`ANTHROPIC_API_KEY` ergab **vor** #390:

```
$ uv run pytest tests/evals/ -q
112 passed, 147 skipped
```

Alle 147 Skips stammen aus einer einzigen Stelle — `tests/evals/eval_runner.py`
(`require_api_key()` → `pytest.skip`). Was in CI grün leuchtete, waren
Existenz- und Schema-Assertions: „die Datei ist da und hat die richtigen Felder",
nicht „der Skill liefert die versprochene Qualität".

**Nach** #390 lautet derselbe Lauf `184 passed, 148 skipped`. Die 72
zusätzlichen bestandenen Tests sind die drei neuen Suiten dieses Issues
(Strategie-Guard, auto-download-Routing, humanizer-Tell-Dichte); der eine
zusätzliche Skip ist die Kontroll-Quelle `general-06`, die per Definition
keinen Tier erreicht. **Die 147 API-gateten Skips sind unverändert geblieben** —
dieses Issue hat Transparenz geschaffen, keine LLM-Qualität gemessen.

Dieses Dokument benennt deshalb für **jede** Komponente unter `evals/` genau
einen Zustand — und der Guard erzwingt, dass keine Komponente stillschweigend
durchrutscht.

## Status-Vokabular

| Status | Bedeutung |
| --- | --- |
| `metric` | Es existiert ein Runner, der **Inhalt bewertet** und bei jedem `pytest`-Lauf durchläuft — ohne Netz, ohne API-Key. |
| `structural` | Es wird **nur die Struktur** geprüft (Datei existiert, Schema stimmt). Die inhaltliche Bewertung hängt an einem API-Key und **skippt** ohne ihn. Pflicht: Begründung, warum das hier vertretbar ist. |
| `removed` | Die Eval-Definition wurde entfernt, weil sie keinen Bezug zu ausführbarem Code hatte. |

`structural` ist ausdrücklich **kein „grün"**. Es heißt: hier wird derzeit keine
Qualität gemessen, und wir sagen es hin, statt es zu verstecken.

## Statustabelle

Spalten: Komponente | Status | Ausführungspfad | Begründung bzw. Anmerkung.

| Komponente | Status | Ausführungspfad | Begründung |
| --- | --- | --- | --- |
| `auto-download` | metric | `evals/auto-download/runner.py`, `tests/evals/test_auto_download_routing.py` | Routing der 20 kuratierten Quellen gegen `resolve_pdf_url()`, Tier-Stubs statt Netz. `expected_hit` bleibt netzabhängig und ungeprüft. |
| `humanizer-de-pipeline` | metric | `evals/humanizer-de-pipeline/runner.py`, `tests/evals/test_humanizer_pipeline_evals.py` | Tell-Dichte (Marker/100 Wörter) je Vorher/Nachher-Draft, inkl. Detection-Floor und Substanz-Quotient als Negativkontrollen. |
| `verbatim-guard` | metric | `evals/verbatim-guard/runner.py`, `tests/evals/test_verbatim_guard_evals.py` | 10 Vault-Lookup-Cases gegen `search_quote_text()`; echte vs. erfundene Zitate, FPR 0 %. |
| `524-nli-prefilter` | structural | `evals/524-nli-prefilter/runner.py`, `tests/evals/test_nli_prefilter_evals.py` | Investigation (Issue #524): prueft, ob HHEM-2.1-Open (Apache-2.0) oder mDeBERTa-v3-XNLI (MIT) als lokaler NLI-Vorfilter fuer DE-Kapitelbehauptung/EN-Quellkontext taugt. Struktur-Checks (>= 30 Cases, beide Labels, Sprachkennzeichnung) laufen immer ohne Netz; der Inferenzlauf braucht ~1 GB Modellgewichte-Download (HHEM 418 MB + mDeBERTa 552 MB) und ist darum nicht hermetisch, `structural` statt `metric`. Nachfahrbar mit `RUN_LIVE_NLI_PREFILTER=1 uv run pytest tests/evals/test_nli_prefilter_evals.py`. Zielsystem `quote-fidelity-auditor` (#523) ist aktuell wegen eines CI-Hangs revertet (PR #582/#584) — Empfehlung bleibt Vorarbeit ohne Produktiv-Anschlusspunkt, dokumentiert als Kommentar an #524. |
| `abstract-generator` | structural | `tests/evals/test_abstract_generator_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Quality-Prompts bewerten generierten Fließtext; ohne LLM-Aufruf gibt es dafür kein deterministisches Surrogat. Läuft nur mit `ANTHROPIC_API_KEY`, sonst Skip. |
| `academic-context` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Prüft Konversationsverhalten beim Kontext-Setup — nicht ohne Modell messbar; ohne Key Skip. |
| `advisor` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Beratungsqualität ist ein Urteil über freien Text, kein prüfbares Artefakt; ohne Key Skip. |
| `ai-disclosure` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ob eine Vault-Spur korrekt als Vorschlag statt Behauptung formuliert und jede Zeile mit der richtigen Herkunftsmarkierung ausgegeben wird, ist ein Modellurteil über Fließtext; die Vertragsseite — vier Belegkategorien, Marker-Pflicht, DE/EN-Abschnitte, Fundstelle mit Locator — prüft `tests/test_ai_disclosure_skill.py` deterministisch. Ohne Key Skip. |
| `anchor-paper-survey` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | arXiv-Resolution, PDF-Titel-Heuristik und die Vault-/Suchintegration sind in `tests/test_anchor_paper_survey.py` deterministisch getestet; die Evals prüfen nur Trigger und Dialogführung. Ohne Key Skip. |
| `bibliography-auditor` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Differenzmengenbildung (`missing_in_bibliography`, `orphaned_entries`) gegen `\cite{key}`-Marker und Vault-Paper ist in `tests/test_bibliography_auditor.py` deterministisch getestet; die Evals prüfen nur Trigger und die Abgrenzung zu `submission-checker`. Ohne Key Skip. |
| `book-handler` | structural | `tests/evals/test_book_handler_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die deterministischen Anteile (PDF-Seitenversatz, OCR-Erkennung) sind bereits in `tests/test_book_handler*.py` abgedeckt; die Evals messen den LLM-Anteil. Ohne Key Skip. |
| `chapter-writer` | structural | `tests/evals/test_chapter_writer_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Kapitelqualität ist der Kern-LLM-Output; ein Offline-Proxy wäre eine Scheinmetrik. Ohne Key Skip. |
| `citation-extraction` | structural | `tests/evals/test_citation_extraction_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Extraktion aus Freitext-PDFs; die Parser-Anteile sind separat in `tests/test_citation*.py` getestet. Ohne Key Skip. |
| `citation-style-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Nur Trigger- und Schema-Ebene; der CSL-Import selbst hat kein projekteigenes Skript, das offline bewertbar wäre. Ohne Key Skip. |
| `cluster-visualizer` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bewertet Diagramm-Interpretation; die Clustering-Mathematik ist in `tests/test_cluster*.py` abgedeckt. Ohne Key Skip. |
| `conference-poster` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Layout- und Textqualität eines Posters ist ein Gestaltungsurteil, kein Assert. Ohne Key Skip. |
| `data-management-plan` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die sechs festen Abschnitte, `[OFFEN: ...]`-Markierung statt Erfindung und der Vault-Ausgangslage-Abschnitt sind in `tests/test_data_management_plan.py` deterministisch getestet; die Evals prüfen nur Trigger und die Abgrenzung zu `material-passport`. Ohne Key Skip. |
| `defense-prep` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ob Kernaussagen tatsächlich aus dem Kapiteltext belegt sind und der Fragenkatalog wirklich an Methodik/Limitationen gebunden bleibt, ist ein Modellurteil über Fließtext; die strukturellen Vorgaben (Preamble-Referenz, Nicht-Erfinden-Regel) prüft `tests/test_defense_prep.py` deterministisch. Ohne Key Skip. |
| `extraction-matrix` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Reine Aggregation vorhandener Vault-Belege zu einer Vergleichstabelle; ob Spalten korrekt aus `academic_context.md` abgeleitet und Zellen korrekt als fehlend markiert sind, ist ein Modellurteil ohne deterministisches Surrogat. Ohne Key Skip. |
| `fetch` | structural | `tests/test_fetch_command.py` (Schema-Assertions) | Die drei Cases prüfen Identifier-Erkennung, deren Logik ausschließlich als Prompt in `commands/fetch.md` existiert. Ein Offline-Runner müsste die Testhilfe `tests/test_fetch_command.py` gegen sich selbst prüfen — Tautologie statt Metrik. |
| `free-archive-fetchers` | structural | `tests/test_free_archive_fetchers.py` (Schema-Assertions), `tests/test_issue_450_fetcher_evidence.py` (Beleg-Kopplung, hermetisch) | Cases erwarten Live-Downloads von HathiTrust/Internet Archive/MDZ; jeder Lauf wäre netzabhängig und würde CI bei fremden Ausfällen oder Rate-Limits (HTTP 429) rot färben — gleiche Lage wie `oa-fetchers`. Für AC1 aus #450 (PR #557) liegt der Beleg deshalb als **nachfahrbares Artefakt** in `evals/free-archive-fetchers/live-verification.json` (URL-Kette, HTTP-Status, Bytes, Prüfsumme, Seitenzahl je Lauf) statt als Prosa: `fa-02` lädt real ein 922-seitiges Digitalisat der Erstausgabe von 1813 ohne Login (byteweise über zwei Abrufe reproduzierbar), `fa-03` erhält von MDZ das Gesamtwerk als ein PDF mit 471 Seiten — aber erst nach Bestätigung des Rechtehinweises, ohne die der Server lautlos das Formular zurückgibt. `fa-01` bekommt am HathiTrust-Download-Endpunkt HTTP 403 mit der Sperrseite „Error - Blocked from HathiTrust", während die Bib-API weiter antwortet. Damit sind 2 von 3 Anbietern real als PDF belegt, wie AC1 es verlangt. Nachfahrbar mit `RUN_LIVE_FREE_ARCHIVE_FETCH=1 uv run pytest tests/test_issue_450_live_fetch.py` (opt-in, nicht im CI). Hermetisch läuft zusätzlich `tests/test_issue_450_fetcher_evidence.py`: es zählt die PDF-Belege gegen die AC1-Schwelle, fährt die real aufgezeichnete HathiTrust-Sperrseite (`tests/fixtures/free_archive_fetchers/hathitrust_page_blocked.html`) gegen die Captcha-Erkennung des Repos — mit dem Ergebnis, dass sie **kein** Captcha ist und `status: captcha` dort falsch wäre — und verbietet einmalige Bezeichner (Client-IP, Cloudflare Ray ID, MDZ-Job-Präfix, archive.org-CDN-Knoten) als Beleg. |
| `generic-fetcher` | structural | `tests/test_generic_fetcher.py` (Navigations-Spiegel gegen einen lokalen HTTP-Ursprung) | Die vier Cases beschreiben Volltext-Beschaffung auf realen Plattformen (Zenodo, MDPI, OpenEdition Books) plus eine Paywall-Gegenprobe. Die drei Plattform-Cases laufen end-to-end: `tests/helpers/local_origin.py` serviert die gespeicherte Plattform-DOM **und** die PDF-Route auf 127.0.0.1, `tests/helpers/generic_fetcher_nav.py` holt die Datei per HTTP, schreibt sie und verifiziert sie von der Platte (existiert, > 0 Bytes, `%PDF-`); der Test vergleicht die geschriebenen Bytes mit den ausgelieferten. Der Status bleibt `structural`, weil die DOM aus Fixtures stammt und das öffentliche Netz der drei Plattformen ungetestet bleibt — ob Zenodo, MDPI oder OpenEdition heute real ausliefern, ist netzabhängig und bleibt Operator-Sache (gleiche Lage wie `oa-fetchers`/`publisher-fetchers`). |
| `figure-verifier` | structural | `tests/test_figure_verifier.py` (Schema-Assertions) | Cases setzen einen realen VLM-Aufruf plus PDF-Seitenrender voraus; beides ist weder kostenlos noch deterministisch. |
| `github-repo-research` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | README-/CITATION.cff-Extraktion und -Resolution sind in `tests/test_github_repo_research.py` deterministisch getestet; die Evals prüfen nur Trigger und Dialogführung. Ohne Key Skip. |
| `grant-proposal` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Antragsqualität ist ein inhaltliches Urteil über Fließtext. Ohne Key Skip. |
| `humanizer-de` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Skill selbst formuliert um (LLM-Aufgabe); die messbare Wirkung deckt `humanizer-de-pipeline` als `metric` ab. Ohne Key Skip. |
| `instrument-design` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Skill erzeugt Fließtext (Leitfaden-/Fragebogen-Items); ob eine Frage wirklich auf eine Unterfrage zurückgeht, ist ein inhaltliches Urteil ohne Offline-Surrogat. Die Vertragsseite — Rückverweis-Matrix als Pflichtausgabe, Abbruch ohne Forschungsfrage, Abgrenzung zu `methodology-advisor` — ist in `tests/test_instrument_design.py` deterministisch abgedeckt. Ohne Key Skip. |
| `latex-export` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der deterministische Export ist in `tests/test_latex_export.py` getestet; die Evals adressieren die Formulierungsebene. Ohne Key Skip. |
| `latex-layout-auditor` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die zwei deterministischen Digest-Regeln (fehlendes `\tightlist`, korrumpierte `\cite{}`-Befehle) prueft `tests/test_latex_layout_auditor.py` unmittelbar gegen `scripts/check_layout.py::audit_tex()`; die restlichen Checklisten-Dimensionen (Package-Konflikte, Kapitel-Nummerierung, Bildunterschriften-Format) sind Modellurteile ueber Fliesstext ohne deterministisches Surrogat. Ohne Key Skip. |
| `literature-excel` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Trigger-Kollision zwischen literaturbezogenen und literaturfremden Excel-Wünschen ist Modellverhalten und ohne LLM-Aufruf nicht bewertbar; die statische Verdrahtung (Verweis auf `commands/excel.md`, keine Spezifikations-Duplikation) ist bereits in `tests/test_issue_447_literature_excel_router.py` deterministisch abgedeckt. Ohne Key Skip. |
| `word-export` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bib-Selektion, Stilregel-Ladepfad und `\cite{}`-Aufloesung sind in `tests/test_word_export.py` deterministisch getestet; die Evals adressieren nur Trigger und Formulierungsebene. Ohne Key Skip. |
| `slide-export` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Kapitel-Aufloesung und Kernaussage-Extraktion sind in `tests/test_slide_export.py` deterministisch getestet; die Evals adressieren nur Trigger und Formulierungsebene. Ohne Key Skip. |
| `literature-gap-analysis` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Lückenanalyse ist eine Syntheseleistung über Volltexte; offline nicht bewertbar. Ohne Key Skip. |
| `material-passport` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Passport-Mechanik liegt im Vault (`tests/test_vault_*.py`); die Evals prüfen die Skill-Anleitung. Ohne Key Skip. |
| `methodology-advisor` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Methodenberatung ist ein fachliches Urteil ohne eindeutige Referenzlösung. Ohne Key Skip. |
| `notebook-bundle` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bündel-Erzeugung ist in `tests/test_notebook_bundle.py` abgedeckt; die Evals bewerten die Erläuterungstexte. Ohne Key Skip. |
| `oa-fetchers` | structural | `tests/test_oa_fetchers.py` (Schema-Assertions) | Cases erwarten Live-Downloads von TIB/OAPEN/DOAB; jeder Lauf wäre netzabhängig und würde CI bei fremden Ausfällen rot färben. |
| `parallel-screening` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Wellen-Planung, Ledger, Resume und PRISMA-Summe sind in `tests/test_issue_460_parallel_screening.py` deterministisch getestet; die Evals prüfen nur Trigger und den Umgang mit uneindeutigen Fällen. Ohne Key Skip. |
| `peer-review` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ob Bereichsbewertung, Redaktions-/Autoren-Trennung und Empfehlung tatsächlich aus dem eingefügten Manuskripttext folgen, ist ein Modellurteil über Fließtext; die strukturellen Vorgaben (5-Bereichs-Liste, getrennte Blöcke, Empfehlungs-Skala, Fundstelle-Pflicht) prüft `tests/test_issue_608_peer_review.py` deterministisch. Ohne Key Skip. |
| `plagiarism-check` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bewertet Textähnlichkeits-Urteile im Fließtext; die Vault-Seite deckt `verbatim-guard` ab. Ohne Key Skip. |
| `prisma-flow` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Zähllogik ist in `tests/test_prisma*.py` getestet; die Evals adressieren die Ableitung aus Prosa. Ohne Key Skip. |
| `publisher-fetchers` | structural | `tests/test_publisher_fetchers.py` (Schema-Assertions) | Cases erwarten Verlagsseiten inkl. Captcha-/Auth-Pfaden; im CI nicht hermetisch reproduzierbar, darum `structural`. Fuer `pf-06`/`pf-07`/`pf-08` (#449, PR #500) liegt der AC1-Beleg als **nachfahrbares Artefakt** in `evals/publisher-fetchers/live-verification.json` (URL-Kette, HTTP-Status, Bytes, SHA-256, Seitenzahl je Lauf) statt als Prosa: `pf-06` und `pf-07` laden real ein vollstaendiges Buch-PDF ohne Login (228 bzw. 225 Seiten, mit `pypdf` geoeffnet; `pf-07`s urspruengliche DOI zeigte auf ein kostenpflichtiges Buch und wurde korrigiert), `pf-08` erhaelt am Volltext-Endpunkt HTTP 403 mit JSTORs Bot-Challenge. Nachfahrbar mit `RUN_LIVE_PUBLISHER_FETCH=1 uv run pytest tests/test_issue_449_live_fetch.py` (opt-in, nicht im CI — ein Ausfall der Verlage darf die Pipeline nicht rot faerben). Hermetisch laeuft zusaetzlich `tests/test_issue_449_fetcher_evidence.py`: es fuehrt die real aufgezeichnete JSTOR-Challenge (`tests/fixtures/publisher_fetchers/jstor_access_check.html`) gegen die Captcha-Erkennung des Repos und verbietet einmalige Bezeichner (Block-Referenz, IP, Uhrzeit) als Beleg — sie sind pro Request neu und darum unpruefbar. |
| `qualitative-coding` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Kategorienbildung selbst ist Modellurteil; der deterministische Anteil (Segmentierung, Idempotenz des Re-Imports, Herkunfts-Validierung, Rendering von Übersicht und Kodierleitfaden) liegt in `tests/test_qualitative_coding.py`, die Belegpflicht für Interviewzitate in `tests/test_qualitative_coding_guard.py`. Ohne Key Skip. |
| `quantitative-analysis` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Verfahrenswahl im Dialog und die Weigerung, ein Ergebnis zu deuten, sind Modellurteile über Fließtext. Der Rechenkern dagegen ist vollständig deterministisch geprüft: `tests/test_issue_610_quantitative_analysis.py` erzwingt byte-identische Wiederholläufe, Effektstärke plus Konfidenzintervall je Test (Renderer wirft sonst), berichtete Voraussetzungsprüfungen inklusive benannter Alternative bei Verletzung und die Abgrenzung gegen `methodology-advisor`/`qualitative-coding`/`meta-analysis`. Ohne Key Skip. |
| `quality-reviewer` | structural | `tests/evals/test_quality_reviewer_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Agent ist selbst ein LLM-Judge; ihn offline zu bewerten hieße, einen Judge durch einen Regex zu ersetzen. Ohne Key Skip. |
| `query-generator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Suchstring-Qualität hängt von Recherchekontext ab; kein deterministischer Sollwert. Ohne Key Skip. |
| `quote-extractor` | structural | `tests/evals/test_quote_extractor_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Extraktionsqualität ist LLM-Leistung; die Verbatim-Absicherung danach ist als `verbatim-guard` bereits `metric`. Ohne Key Skip. |
| `reading-list-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Import-Parsing ist in `tests/test_reading_list*.py` abgedeckt; die Evals prüfen die Dialogführung. Ohne Key Skip. |
| `reading-notes` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | CRUD und FTS5-Suche sind in `tests/test_issue_462_vault_notes.py` deterministisch getestet; die Evals prüfen nur, ob das Modell die Kernbefund/Methode/Verwendbarkeit-Struktur ohne Nutzervorgabe einhält. Ohne Key Skip. |
| `research-question-refiner` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Schärfung einer Forschungsfrage hat keine eindeutige Musterlösung. Ohne Key Skip. |
| `reviewer-response` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Antwortschreiben an Gutachter sind Fließtext-Urteile. Ohne Key Skip. |
| `source-quality-audit` | structural | `tests/evals/test_source_quality_audit_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die harten Kriterien (DOI, Peer-Review-Flag) prüft der Vault; die Evals bewerten die Einordnung. Ohne Key Skip. |
| `sparring-partner` | structural | `tests/evals/test_sparring_partner_criteria.py` (Negativkontrollen, CI-fest), `tests/evals/test_sparring_partner_recording.py` (Snapshot, CI-fest), `tests/evals/test_sparring_partner_evals.py` (API-gated) | `recordings.json` hält fünf Transkripte aus **echten, blinden Modellaufrufen** (`evals/sparring-partner/record.py`, Claude-Code-CLI headless): die Kriterien waren vor der Aufnahme committed, der Aufnahme-Subprozess sah sie nicht. Dass der Abgleich scheitern kann, ist belegt — der erste Lauf gegen die vorab festgelegten Kriterien ergab 1/5. Zusätzlich prüfen neun format-konforme Negativkontrollen (`counter_examples.json`), dass die Kriterien überhaupt unterscheiden: vor Issue #454 bestand eine rein bestätigende Antwort sp-01/02/05 und Kapitel-Prosa bestand sp-04 — die Kriterien maßen Formattreue statt Verhalten, auf **beiden** Pfaden. Status bleibt `structural`, weil pro pytest-Lauf kein Modell befragt wird: die Transkripte sind eine eingefrorene Stichprobe aus fünf Prompts, und das im Frontmatter deklarierte Read-/Vault-Tooling war im Aufnahmelauf abgeschaltet (Material inline im Prompt). Der Nachweis für den Anthropic-API-Aufrufweg bleibt `tests/evals/test_sparring_partner_evals.py` — ohne Key Skip. |
| `style-evaluator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Stilurteil über Fließtext; der einzige offline messbare Teilaspekt ist als `humanizer-de-pipeline` abgedeckt. Ohne Key Skip. |
| `submission-checker` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Prüft Einreichungsrichtlinien in natürlicher Sprache, die je Journal variieren. Ohne Key Skip. |
| `title-generator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Titelqualität ist ein Geschmacks- und Präzisionsurteil ohne Referenzlösung. Ohne Key Skip. |
| `topic-brainstorm` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ideengenerierung ist per Definition offen; ein Offline-Assert würde Vielfalt bestrafen. Ohne Key Skip. |
| `zotero-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Import-Pfad ist in `tests/test_zotero_import.py` abgedeckt; die Evals prüfen Trigger und Dialog. Ohne Key Skip. |

**Bilanz:** 3 × `metric`, 45 × `structural`, 0 × `removed` (Stand Issue #446:
`word-export`/`slide-export` neu, beide `structural`; Stand Issue #454:
`sparring-partner` neu, `structural` — die Transkripte stammen aus echten,
blinden Modellaufrufen gegen vorab committete Kriterien, aber pro pytest-Lauf
wird kein Modell befragt; gemessen wird offline die Unterscheidungskraft der
Kriterien gegen neun Negativkontrollen, siehe Zeile oben; Stand Issue #472:
`defense-prep` neu, `structural` — Kernaussage- und Fragenkatalog-Qualität
bleiben Modellurteile, die strukturellen Vorgaben deckt `tests/test_defense_prep.py`).

Vor Issue #390 war der Stand 1 × `metric` (`verbatim-guard`) und 2 tote
Definitionen ohne jeden Code-Bezug (`auto-download`, `humanizer-de-pipeline`).

## Korrektur zur Issue-Beschreibung

Issue #390 nennt „14 Komponenten mit `evals.json`-Qualitäts-Prompts ganz ohne
Ausführungspfad". Nachgezählt sind es **17**: 13 Skills
(`citation-style-import`, `cluster-visualizer`, `conference-poster`,
`grant-proposal`, `humanizer-de`, `latex-export`, `material-passport`,
`notebook-bundle`, `prisma-flow`, `reading-list-import`, `reviewer-response`,
`topic-brainstorm`, `zotero-import`) plus 4 Nicht-Skills (`fetch`,
`figure-verifier`, `oa-fetchers`, `publisher-fetchers`). Die 13 Skills laufen
immerhin über `tests/evals/test_triggers.py` (API-gated), die 4 Nicht-Skills
haben ausschließlich Existenz- und Schema-Assertions.

## Zwei Schemata unter `evals/`

`evals/SCHEMA.md` beschreibt das `prompts[]`-Format. Fünf Verzeichnisse benutzen
faktisch ein zweites, `cases[]`-basiertes Format (`fetch`, `figure-verifier`,
`generic-fetcher`, `oa-fetchers`, `publisher-fetchers`; `figure-verifier` und
`oa-fetchers` sogar als Top-Level-Array ohne `component`-Feld). Das ist in
`evals/SCHEMA.md` dokumentiert, aber bewusst **nicht** normalisiert: ein Umbau
würde `tests/test_figure_verifier.py`, `tests/test_oa_fetchers.py` und
`tests/test_publisher_fetchers.py` brechen, ohne die Messqualität zu erhöhen.
`generic-fetcher` (#448) folgt demselben `cases[]`-Format wie die verwandten
Fetcher-Verzeichnisse, statt eine sechste Variante einzuführen.

## API-Budget

Was `structural` in `metric` verwandeln würde, ist ausschließlich Budget für
reale Modell-Aufrufe. Größenordnung, gerechnet auf dem heutigen Bestand:

| Posten | Aufrufe pro Vollauf |
| --- | --- |
| Quality-Evals (`prompts[]`, je `with_skill` + `without_skill`) | ca. 120 |
| Trigger-Evals (28 Skills × 10 Cases, Haiku-Klassifikation) | ca. 280 |
| **Summe** | **ca. 400 Aufrufe** |

Bei überwiegend kurzen Prompts und Haiku für den Trigger-Block liegt ein
Vollauf im niedrigen einstelligen USD-Bereich; die Quality-Evals mit einem
größeren Modell dominieren die Kosten. Ein Baseline-Lauf pro Release wäre der
sinnvolle Rhythmus, nicht pro Commit.

**Das ist eine Bezifferung, keine Forderung.** Ob und in welcher Höhe ein
`ANTHROPIC_API_KEY` mit Budget bereitgestellt wird, entscheidet der Operator.
Issue #390 verbraucht selbst kein Budget: alle in seinem Rahmen entstandenen
Runner laufen offline (per Guard `test_no_eval_runner_requires_api_key`
erzwungen), und die 147 Skips bleiben bis zu einer Operator-Entscheidung
bestehen.

**Realer Ausführungspfad (Issue #470):** `.github/workflows/eval-behavior.yml`
ist der einzige Weg, diese ca. 400 Aufrufe tatsächlich abzurufen — ein separat
per `workflow_dispatch` auslösbarer Job, begrenzt auf `tests/evals/` (nicht
`tests/`), mit `timeout-minutes: 60` als hartem Deckel (angehoben in #631, da
der CLI-Pfad pro Aufruf deutlich teurer ist als der SDK-Pfad). Der Job bricht mit
`::error::` ab, wenn weder `ANTHROPIC_API_KEY` noch `CLAUDE_CODE_OAUTH_TOKEN`
als Repo-Secret hinterlegt ist, statt täuschend grün als „0 failed, N
skipped" durchzulaufen. `ci.yml` bleibt davon unberührt: keine Auth dort,
weiterhin nur `push`/`pull_request`, die API-gateten Skips bestehen im
regulären Lauf unverändert fort. Ob eines der beiden Secrets hinterlegt wird,
bleibt — wie oben beschrieben — Operator-Entscheidung.

**Zwei Aufrufwege (Issue #631).** `tests/evals/eval_runner.py` probiert bei
jedem Aufruf zwei Wege statt einem:

1. **SDK-Pfad** (unverändert seit vor #631): `ANTHROPIC_API_KEY` gesetzt →
   `anthropic.Anthropic(...)`. Separates, eigens abgerechnetes API-Budget.
2. **CLI-Pfad** (neu): kein `ANTHROPIC_API_KEY`, aber die `claude`-CLI im
   PATH gefunden → `claude --print --output-format json` als Subprozess,
   Vorbild `evals/sparring-partner/record.py`. Läuft über die
   OAuth-Session — lokal die bereits eingeloggte Session, in CI
   `CLAUDE_CODE_OAUTH_TOKEN` (dasselbe Secret, das `pr-deep-review.yml`
   bereits fünffach nutzt), ohne zweites Abrechnungsverhältnis.
3. Weder Key noch CLI gefunden → `pytest.skip()`, exakt wie zuvor.

Ist die CLI vorhanden (**geändertes Verhalten, AC1**): Ein Rechner mit
einer bereits eingeloggten `claude`-Session löst künftig bei jedem
`pytest tests/`-Lauf reale (Abo-)Aufrufe aus, wo vorher lautlos geskippt
wurde. Das ist der beabsichtigte Kern von #631, keine Nebenwirkung —
wer offline entwickeln will, muss die CLI vom PATH nehmen oder sich ausloggen.
Fehlen dagegen sowohl Key als auch CLI, bleibt es beim bisherigen
`pytest.skip()` (**unverändertes Skip-Verhalten, AC7**).

**Was auf dem CLI-Pfad entfällt oder anders aussieht (AC6):**

- **Kein `--temperature`-Flag.** Laut `claude --help` kennt die CLI keine
  Temperatur-Steuerung. Der Determinismus-Schutz aus Issue #231
  (`temperature=0`, verhindert flaky Trigger-Evals) greift auf dem CLI-Pfad
  **nicht**. Betroffen: `test_should_trigger_recall` /
  `test_should_not_trigger_fpr` (ca. 280 Haiku-Klassifikationsaufrufe) — bei
  CLI-Betrieb potenziell leicht flakier als auf dem SDK-Pfad. Keine
  Kompensation umgesetzt (Out of Scope für #631); falls das in der Praxis zu
  Flakiness führt, ist ein Retry- oder Toleranz-Mechanismus ein Folge-Issue.
- **Typisierte SDK-Exceptions weg.** Der SDK-Pfad kann
  `anthropic.RateLimitError`, `anthropic.AuthenticationError` etc. werfen.
  Der CLI-Pfad kennt nur `eval_runner.ClaudeCliError` mit einem generischen
  `api_error_status` (aus dem JSON-Feld `api_error_status` der CLI-Antwort)
  — weniger granular, aber ausreichend, um einen Auth-/Rate-Limit-Fehler von
  einer inhaltlich falschen (aber technisch sauberen) Modellantwort zu
  unterscheiden (AC5).
- **Tokenzahlen bleiben verfügbar, aber anders geschnitten.** Das
  `usage`-Feld aus `--output-format json` liefert `input_tokens`/
  `output_tokens` für den jeweiligen Aufruf — kein bestehender
  Token-Baseline-Konsument (`call_claude_with_tokens`) ist bisher an eine
  reale Suite verdrahtet, betroffen ist also aktuell nur die
  Infrastruktur-Funktion selbst, keine bestehende Baseline in
  `tests/baselines/tokens.json`. Wichtig für spätere Nutzung: ein einzelner
  CLI-Aufruf erzeugt zusätzlich einen großen, hier nicht ausgewerteten
  Cache-Erstellungs-Block (`cache_creation_input_tokens`, im Probelauf
  ca. 17–18k Tokens für das Agenten-Scaffold) — Kostengrößenordnung pro
  Aufruf liegt dadurch spürbar über einem reinen SDK-`messages.create()`-Call
  mit demselben System-Prompt; die Bezifferung „ca. 400 Aufrufe" oben bleibt
  eine Aufrufzahl, keine Kostenaussage für den CLI-Pfad.
- **`stop_reason` bleibt erhalten**, wird aber wie zuvor nicht ausgewertet
  (weder SDK- noch CLI-Pfad extrahieren es aktuell).

## Alt-Issue #55

Issue #55 („Baseline-Eval v5.2.0") verlangte denselben Nachweis auf altem
Stand. Es ist **geschlossen** und ausdrücklich als von #390 absorbiert
vermerkt — es ist kein offener Punkt und soll nicht erneut als To-Do
hochgebracht werden. Der Grund für den damaligen Abbruch ist derselbe, der oben
im Abschnitt API-Budget steht: ohne bereitgestelltes Budget gibt es keinen
Baseline-Lauf.

## Wann diese Datei zu ändern ist

- **Neues Verzeichnis unter `evals/`** → Zeile ergänzen, sonst schlägt
  `test_every_eval_dir_has_exactly_one_status` fehl.
- **Neuer Offline-Runner** → Status auf `metric`, Pfad in Backticks eintragen.
- **Eval-Definition entfernt** → Status `removed`, Verzeichnis löschen.
- **Operator stellt Budget bereit** → Abschnitt API-Budget aktualisieren und die
  betroffenen Zeilen neu bewerten.
