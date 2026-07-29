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
| `abstract-generator` | structural | `tests/evals/test_abstract_generator_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Quality-Prompts bewerten generierten Fließtext; ohne LLM-Aufruf gibt es dafür kein deterministisches Surrogat. Läuft nur mit `ANTHROPIC_API_KEY`, sonst Skip. |
| `academic-context` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Prüft Konversationsverhalten beim Kontext-Setup — nicht ohne Modell messbar; ohne Key Skip. |
| `advisor` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Beratungsqualität ist ein Urteil über freien Text, kein prüfbares Artefakt; ohne Key Skip. |
| `anchor-paper-survey` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | arXiv-Resolution, PDF-Titel-Heuristik und die Vault-/Suchintegration sind in `tests/test_anchor_paper_survey.py` deterministisch getestet; die Evals prüfen nur Trigger und Dialogführung. Ohne Key Skip. |
| `book-handler` | structural | `tests/evals/test_book_handler_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die deterministischen Anteile (PDF-Seitenversatz, OCR-Erkennung) sind bereits in `tests/test_book_handler*.py` abgedeckt; die Evals messen den LLM-Anteil. Ohne Key Skip. |
| `chapter-writer` | structural | `tests/evals/test_chapter_writer_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Kapitelqualität ist der Kern-LLM-Output; ein Offline-Proxy wäre eine Scheinmetrik. Ohne Key Skip. |
| `citation-extraction` | structural | `tests/evals/test_citation_extraction_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Extraktion aus Freitext-PDFs; die Parser-Anteile sind separat in `tests/test_citation*.py` getestet. Ohne Key Skip. |
| `citation-style-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Nur Trigger- und Schema-Ebene; der CSL-Import selbst hat kein projekteigenes Skript, das offline bewertbar wäre. Ohne Key Skip. |
| `cluster-visualizer` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bewertet Diagramm-Interpretation; die Clustering-Mathematik ist in `tests/test_cluster*.py` abgedeckt. Ohne Key Skip. |
| `conference-poster` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Layout- und Textqualität eines Posters ist ein Gestaltungsurteil, kein Assert. Ohne Key Skip. |
| `extraction-matrix` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Reine Aggregation vorhandener Vault-Belege zu einer Vergleichstabelle; ob Spalten korrekt aus `academic_context.md` abgeleitet und Zellen korrekt als fehlend markiert sind, ist ein Modellurteil ohne deterministisches Surrogat. Ohne Key Skip. |
| `fetch` | structural | `tests/test_fetch_command.py` (Schema-Assertions) | Die drei Cases prüfen Identifier-Erkennung, deren Logik ausschließlich als Prompt in `commands/fetch.md` existiert. Ein Offline-Runner müsste die Testhilfe `tests/test_fetch_command.py` gegen sich selbst prüfen — Tautologie statt Metrik. |
| `generic-fetcher` | structural | `tests/test_generic_fetcher.py` (Navigations-Spiegel gegen einen lokalen HTTP-Ursprung) | Die vier Cases beschreiben Volltext-Beschaffung auf realen Plattformen (Zenodo, MDPI, OpenEdition Books) plus eine Paywall-Gegenprobe. Die drei Plattform-Cases laufen end-to-end: `tests/helpers/local_origin.py` serviert die gespeicherte Plattform-DOM **und** die PDF-Route auf 127.0.0.1, `tests/helpers/generic_fetcher_nav.py` holt die Datei per HTTP, schreibt sie und verifiziert sie von der Platte (existiert, > 0 Bytes, `%PDF-`); der Test vergleicht die geschriebenen Bytes mit den ausgelieferten. Der Status bleibt `structural`, weil die DOM aus Fixtures stammt und das öffentliche Netz der drei Plattformen ungetestet bleibt — ob Zenodo, MDPI oder OpenEdition heute real ausliefern, ist netzabhängig und bleibt Operator-Sache (gleiche Lage wie `oa-fetchers`/`publisher-fetchers`). |
| `figure-verifier` | structural | `tests/test_figure_verifier.py` (Schema-Assertions) | Cases setzen einen realen VLM-Aufruf plus PDF-Seitenrender voraus; beides ist weder kostenlos noch deterministisch. |
| `github-repo-research` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | README-/CITATION.cff-Extraktion und -Resolution sind in `tests/test_github_repo_research.py` deterministisch getestet; die Evals prüfen nur Trigger und Dialogführung. Ohne Key Skip. |
| `grant-proposal` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Antragsqualität ist ein inhaltliches Urteil über Fließtext. Ohne Key Skip. |
| `humanizer-de` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Skill selbst formuliert um (LLM-Aufgabe); die messbare Wirkung deckt `humanizer-de-pipeline` als `metric` ab. Ohne Key Skip. |
| `latex-export` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der deterministische Export ist in `tests/test_latex_export.py` getestet; die Evals adressieren die Formulierungsebene. Ohne Key Skip. |
| `literature-excel` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Trigger-Kollision zwischen literaturbezogenen und literaturfremden Excel-Wünschen ist Modellverhalten und ohne LLM-Aufruf nicht bewertbar; die statische Verdrahtung (Verweis auf `commands/excel.md`, keine Spezifikations-Duplikation) ist bereits in `tests/test_issue_447_literature_excel_router.py` deterministisch abgedeckt. Ohne Key Skip. |
| `word-export` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bib-Selektion, Stilregel-Ladepfad und `\cite{}`-Aufloesung sind in `tests/test_word_export.py` deterministisch getestet; die Evals adressieren nur Trigger und Formulierungsebene. Ohne Key Skip. |
| `slide-export` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Kapitel-Aufloesung und Kernaussage-Extraktion sind in `tests/test_slide_export.py` deterministisch getestet; die Evals adressieren nur Trigger und Formulierungsebene. Ohne Key Skip. |
| `literature-gap-analysis` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Lückenanalyse ist eine Syntheseleistung über Volltexte; offline nicht bewertbar. Ohne Key Skip. |
| `material-passport` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Passport-Mechanik liegt im Vault (`tests/test_vault_*.py`); die Evals prüfen die Skill-Anleitung. Ohne Key Skip. |
| `methodology-advisor` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Methodenberatung ist ein fachliches Urteil ohne eindeutige Referenzlösung. Ohne Key Skip. |
| `notebook-bundle` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bündel-Erzeugung ist in `tests/test_notebook_bundle.py` abgedeckt; die Evals bewerten die Erläuterungstexte. Ohne Key Skip. |
| `oa-fetchers` | structural | `tests/test_oa_fetchers.py` (Schema-Assertions) | Cases erwarten Live-Downloads von TIB/OAPEN/DOAB; jeder Lauf wäre netzabhängig und würde CI bei fremden Ausfällen rot färben. |
| `parallel-screening` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Wellen-Planung, Ledger, Resume und PRISMA-Summe sind in `tests/test_issue_460_parallel_screening.py` deterministisch getestet; die Evals prüfen nur Trigger und den Umgang mit uneindeutigen Fällen. Ohne Key Skip. |
| `plagiarism-check` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bewertet Textähnlichkeits-Urteile im Fließtext; die Vault-Seite deckt `verbatim-guard` ab. Ohne Key Skip. |
| `prisma-flow` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Zähllogik ist in `tests/test_prisma*.py` getestet; die Evals adressieren die Ableitung aus Prosa. Ohne Key Skip. |
| `publisher-fetchers` | structural | `tests/test_publisher_fetchers.py` (Schema-Assertions) | Cases erwarten Verlagsseiten inkl. Captcha-/Auth-Pfaden; nicht hermetisch reproduzierbar. |
| `quality-reviewer` | structural | `tests/evals/test_quality_reviewer_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Agent ist selbst ein LLM-Judge; ihn offline zu bewerten hieße, einen Judge durch einen Regex zu ersetzen. Ohne Key Skip. |
| `query-generator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Suchstring-Qualität hängt von Recherchekontext ab; kein deterministischer Sollwert. Ohne Key Skip. |
| `quote-extractor` | structural | `tests/evals/test_quote_extractor_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Extraktionsqualität ist LLM-Leistung; die Verbatim-Absicherung danach ist als `verbatim-guard` bereits `metric`. Ohne Key Skip. |
| `reading-list-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Import-Parsing ist in `tests/test_reading_list*.py` abgedeckt; die Evals prüfen die Dialogführung. Ohne Key Skip. |
| `reading-notes` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | CRUD und FTS5-Suche sind in `tests/test_issue_462_vault_notes.py` deterministisch getestet; die Evals prüfen nur, ob das Modell die Kernbefund/Methode/Verwendbarkeit-Struktur ohne Nutzervorgabe einhält. Ohne Key Skip. |
| `research-question-refiner` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Schärfung einer Forschungsfrage hat keine eindeutige Musterlösung. Ohne Key Skip. |
| `reviewer-response` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Antwortschreiben an Gutachter sind Fließtext-Urteile. Ohne Key Skip. |
| `source-quality-audit` | structural | `tests/evals/test_source_quality_audit_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die harten Kriterien (DOI, Peer-Review-Flag) prüft der Vault; die Evals bewerten die Einordnung. Ohne Key Skip. |
| `sparring-partner` | structural | `tests/evals/test_sparring_partner_recording.py` (Snapshot/Fixture, CI-fest), `tests/evals/test_sparring_partner_evals.py` (API-gated) | `recordings.json` hält fünf in derselben Sitzung wie `evals.json::expected` verfasste Transkripte (sha256-gepinnt an `agents/sparring-partner.md`, Drift schlägt fehl statt still zu bestehen) — das ist ein Konsistenz-Check zwischen eingefrorenem Text und Regex, kein unabhängiger Verhaltensbeleg: Transkript und Erwartung stammen aus derselben Quelle, der einzige echte Fehlerpfad ist der Hash-Pin (Coordinator-Gate-Befund, PR #494, Issue #454). Der inhaltliche AC-Beleg bleibt `tests/evals/test_sparring_partner_evals.py` — API-gated, Live-Aufruf gegen echtes Modell, ohne Key Skip. |
| `style-evaluator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Stilurteil über Fließtext; der einzige offline messbare Teilaspekt ist als `humanizer-de-pipeline` abgedeckt. Ohne Key Skip. |
| `submission-checker` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Prüft Einreichungsrichtlinien in natürlicher Sprache, die je Journal variieren. Ohne Key Skip. |
| `title-generator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Titelqualität ist ein Geschmacks- und Präzisionsurteil ohne Referenzlösung. Ohne Key Skip. |
| `topic-brainstorm` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ideengenerierung ist per Definition offen; ein Offline-Assert würde Vielfalt bestrafen. Ohne Key Skip. |
| `zotero-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Import-Pfad ist in `tests/test_zotero_import.py` abgedeckt; die Evals prüfen Trigger und Dialog. Ohne Key Skip. |

**Bilanz:** 3 × `metric`, 44 × `structural`, 0 × `removed` (Stand Issue #446:
`word-export`/`slide-export` neu, beide `structural`; Stand Issue #454:
`sparring-partner` neu, `structural` — der Recording-Runner ist ein
Snapshot/Fixture-Check, kein unabhängiger Verhaltensbeleg, siehe Zeile oben).

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
