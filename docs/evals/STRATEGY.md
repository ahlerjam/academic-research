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
keinen Tier erreicht. Die 147 API-gateten Skips waren zu dem Zeitpunkt
unverändert geblieben — dieses Issue hat Transparenz geschaffen, keine
LLM-Qualität gemessen.

**Heutiger Stand** (Issue #619/#677, reproduzierbar mit `uv run pytest
tests/evals/ -q` ohne `ANTHROPIC_API_KEY` und ohne installierte `claude`-CLI
im PATH — `claude_cli_available()` gatet den Guard zusätzlich, Issue #631):
`274 passed, 194 skipped`. Seit #390 sind weitere Suiten dazugekommen (u. a.
#524, #626, #628, #630); die Skip-Zahl ist gegenüber dem #390-Snapshot
gestiegen, weil jede neue `structural`-Komponente eigene API-gatete Tests
mitbringt. `test_skip_count_matches_real_pytest_run` hält die **Skip-Zahl**
weiterhin per Gleichheit gegen einen echten Subprozesslauf; die `passed`-Zahl
prüft der Guard seit #677 nur noch als **Untergrenze** — echte Regressionen
bleiben rot, ein PR, der irgendwo unter `tests/evals/` einen neuen grünen
Test ergänzt, färbt diesen Guard nicht mehr rot. Vor #677 war die `passed`-Zahl
per strikter Gleichheit gekoppelt: jeder Merge aus main, der unter
`tests/evals/` einen Test hinzufügte, machte diesen und jeden Folge-PR rot,
ohne dass der PR `STRATEGY.md` je angefasst hätte (Vorfallsreihe allein
innerhalb von PR #664: `092c9c6`, `a5e656d`, `60527b5`, `17c7ec5`).

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
| `524-nli-prefilter` | structural | `evals/524-nli-prefilter/runner.py`, `tests/evals/test_nli_prefilter_evals.py` | Investigation (Issue #524): prueft, ob HHEM-2.1-Open (Apache-2.0) oder mDeBERTa-v3-XNLI (MIT) als lokaler NLI-Vorfilter fuer DE-Kapitelbehauptung/EN-Quellkontext taugt. Struktur-Checks (>= 30 Cases, beide Labels, Sprachkennzeichnung) laufen immer ohne Netz; der Inferenzlauf braucht ~1 GB Modellgewichte-Download (HHEM 418 MB + mDeBERTa 552 MB) und ist darum nicht hermetisch, `structural` statt `metric`. Nachfahrbar mit `RUN_LIVE_NLI_PREFILTER=1 uv run pytest tests/evals/test_nli_prefilter_evals.py`. Zielsystem `quote-fidelity-auditor` (#523) liegt auf main (PR #582); der Revert-PR #584 beruhte auf einer Fehlmessung (Post-Merge-Lauf war `cancelled`, nicht `failure`) und wurde geschlossen — ein Produktiv-Anschlusspunkt fuer einen Vorfilter existiert also, siehe `evals/524-nli-prefilter/README.md`. |
| `abstract-generator` | metric | `evals/abstract-generator/runner.py`, `tests/evals/test_abstract_generator_metrics.py` | Abstract-Treue gegen den Quelltext (Issue #606): Wortzahl, Verbot von Zitaten und Kapitelverweisen, vier IMRaD-Züge, Keyword-Zahl, DE/EN-Längenparität — und als inhaltlicher Kern der Fabrikations-Check, der jede Zahl im Abstract im Quelltext nachweist. Korpus hand-autoriert; vier Gegenproben, je genau ein Defekt. Die Bewertung des generierten Fließtexts selbst bleibt API-gated (`tests/evals/test_abstract_generator_evals.py`). |
| `academic-context` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Prüft Konversationsverhalten beim Kontext-Setup — nicht ohne Modell messbar; ohne Key Skip. |
| `advisor` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Beratungsqualität ist ein Urteil über freien Text, kein prüfbares Artefakt; ohne Key Skip. |
| `ai-disclosure` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ob eine Vault-Spur korrekt als Vorschlag statt Behauptung formuliert und jede Zeile mit der richtigen Herkunftsmarkierung ausgegeben wird, ist ein Modellurteil über Fließtext; die Vertragsseite — vier Belegkategorien, Marker-Pflicht, DE/EN-Abschnitte, Fundstelle mit Locator — prüft `tests/test_ai_disclosure_skill.py` deterministisch. Ohne Key Skip. |
| `anchor-paper-survey` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | arXiv-Resolution, PDF-Titel-Heuristik und die Vault-/Suchintegration sind in `tests/test_anchor_paper_survey.py` deterministisch getestet; die Evals prüfen nur Trigger und Dialogführung. Ohne Key Skip. |
| `bibliography-auditor` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Differenzmengenbildung (`missing_in_bibliography`, `orphaned_entries`) gegen `\cite{key}`-Marker und Vault-Paper ist in `tests/test_bibliography_auditor.py` deterministisch getestet; die Evals prüfen nur Trigger und die Abgrenzung zu `submission-checker`. Ohne Key Skip. |
| `book-handler` | structural | `tests/evals/test_book_handler_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die deterministischen Anteile (PDF-Seitenversatz, OCR-Erkennung) sind bereits in `tests/test_book_handler*.py` abgedeckt; die Evals messen den LLM-Anteil. Ohne Key Skip. |
| `chapter-writer` | metric | `evals/chapter-writer/runner.py`, `tests/evals/test_chapter_writer_metrics.py` | Zitatintegrität am Kapitelentwurf (Issue #606): jeder Beleg löst über `verify_citations()` gegen einen aus dem Korpus gebauten Vault auf, jedes Direktzitat ist über `search_quote_text()` wörtlich auffindbar, Zitatdichte ≥ 5/1000 Wörter nach `skills/chapter-writer/references/quality-review-config.md`. Drei Gegenproben, je genau ein Defekt. Kapitel*qualität* — Argumentation, Stil — bleibt ausdrücklich ungemessen und API-gated (`tests/evals/test_chapter_writer_evals.py`). |
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
| `parallel-screening` | metric | `evals/parallel-screening/runner.py`, `tests/evals/test_parallel_screening_metrics.py` | Ausbeute des Rankings (Issue #606): `validate_ranking()` aus `skills/parallel-screening/scripts/active_learning.py` (reine Stdlib, kein Modell-Download) fährt ein Gold-Screening-Set; gemessen wird der Recall nach 30 % der Liste gegen die Zufallsdiagonale (73,3 % vs. 30,0 %). Zwei Gegenproben — Label-Rotation und Text-Entleerung — müssen die Kurve auf die Diagonale bzw. die Ausgangsreihenfolge zurückfallen lassen. Trigger und Umgang mit uneindeutigen Fällen bleiben API-gated (`tests/evals/test_triggers.py`). |
| `peer-review` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ob Bereichsbewertung, Redaktions-/Autoren-Trennung und Empfehlung tatsächlich aus dem eingefügten Manuskripttext folgen, ist ein Modellurteil über Fließtext; die strukturellen Vorgaben (5-Bereichs-Liste, getrennte Blöcke, Empfehlungs-Skala, Fundstelle-Pflicht) prüft `tests/test_issue_608_peer_review.py` deterministisch. Ohne Key Skip. |
| `plagiarism-check` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Bewertet Textähnlichkeits-Urteile im Fließtext; die Vault-Seite deckt `verbatim-guard` ab. Ohne Key Skip. |
| `preregistration` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Vorhaben-Klassifikation und das Rendern der PROSPERO-Pflichtfelder sind in `tests/test_issue_607_preregistration.py` deterministisch getestet; die Evals prüfen nur Trigger und die Abgrenzung zu `methodology-advisor`/`parallel-screening`. Ohne Key Skip. |
| `prisma-flow` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Zähllogik ist in `tests/test_prisma*.py` getestet; die Evals adressieren die Ableitung aus Prosa. Ohne Key Skip. |
| `publisher-fetchers` | structural | `tests/test_publisher_fetchers.py` (Schema-Assertions) | Cases erwarten Verlagsseiten inkl. Captcha-/Auth-Pfaden; im CI nicht hermetisch reproduzierbar, darum `structural`. Fuer `pf-06`/`pf-07`/`pf-08` (#449, PR #500) liegt der AC1-Beleg als **nachfahrbares Artefakt** in `evals/publisher-fetchers/live-verification.json` (URL-Kette, HTTP-Status, Bytes, SHA-256, Seitenzahl je Lauf) statt als Prosa: `pf-06` und `pf-07` laden real ein vollstaendiges Buch-PDF ohne Login (228 bzw. 225 Seiten, mit `pypdf` geoeffnet; `pf-07`s urspruengliche DOI zeigte auf ein kostenpflichtiges Buch und wurde korrigiert), `pf-08` erhaelt am Volltext-Endpunkt HTTP 403 mit JSTORs Bot-Challenge. Nachfahrbar mit `RUN_LIVE_PUBLISHER_FETCH=1 uv run pytest tests/test_issue_449_live_fetch.py` (opt-in, nicht im CI — ein Ausfall der Verlage darf die Pipeline nicht rot faerben). Hermetisch laeuft zusaetzlich `tests/test_issue_449_fetcher_evidence.py`: es fuehrt die real aufgezeichnete JSTOR-Challenge (`tests/fixtures/publisher_fetchers/jstor_access_check.html`) gegen die Captcha-Erkennung des Repos und verbietet einmalige Bezeichner (Block-Referenz, IP, Uhrzeit) als Beleg — sie sind pro Request neu und darum unpruefbar. |
| `qualitative-coding` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Kategorienbildung selbst ist Modellurteil; der deterministische Anteil (Segmentierung, Idempotenz des Re-Imports, Herkunfts-Validierung, Rendering von Übersicht und Kodierleitfaden) liegt in `tests/test_qualitative_coding.py`, die Belegpflicht für Interviewzitate in `tests/test_qualitative_coding_guard.py`. Ohne Key Skip. |
| `quantitative-analysis` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Die Verfahrenswahl im Dialog und die Weigerung, ein Ergebnis zu deuten, sind Modellurteile über Fließtext. Der Rechenkern dagegen ist vollständig deterministisch geprüft: `tests/test_issue_610_quantitative_analysis.py` erzwingt byte-identische Wiederholläufe, Effektstärke plus Konfidenzintervall je Test (Renderer wirft sonst), berichtete Voraussetzungsprüfungen inklusive benannter Alternative bei Verletzung und die Abgrenzung gegen `methodology-advisor`/`qualitative-coding`/`meta-analysis`. Ohne Key Skip. |
| `quality-reviewer` | metric | `evals/quality-reviewer/runner.py`, `tests/evals/test_quality_reviewer_metrics.py` | Trennschärfe der Kriterien, gegen die der Agent urteilt (Issue #606): Satzlängen-Median, Passiv-Quote, Nominalstil und Quellen/1000 werden nach den `Metrik-Hinweise`n aus `agents/quality-reviewer.md` nachgerechnet und gegen von Hand ausgezählte Sollwerte gehalten, inkl. `iteration >= 2`-Fall für ESCALATE und einem committeten blinden Fleck der Passiv-Regel. Drei Gegenproben kippen das Verdict über je genau eine Achse. Ob das Modell die Regel im Betrieb anwendet, bleibt API-gated (`tests/evals/test_quality_reviewer_evals.py`). |
| `query-generator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Suchstring-Qualität hängt von Recherchekontext ab; kein deterministischer Sollwert. Ohne Key Skip. |
| `quote-extractor` | structural | `tests/evals/test_quote_extractor_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Extraktionsqualität ist LLM-Leistung; die Verbatim-Absicherung danach ist als `verbatim-guard` bereits `metric`. Ohne Key Skip. |
| `reading-list-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Import-Parsing ist in `tests/test_reading_list*.py` abgedeckt; die Evals prüfen die Dialogführung. Ohne Key Skip. |
| `reading-notes` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | CRUD und FTS5-Suche sind in `tests/test_issue_462_vault_notes.py` deterministisch getestet; die Evals prüfen nur, ob das Modell die Kernbefund/Methode/Verwendbarkeit-Struktur ohne Nutzervorgabe einhält. Ohne Key Skip. |
| `research-question-refiner` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Schärfung einer Forschungsfrage hat keine eindeutige Musterlösung. Ohne Key Skip. |
| `reviewer-response` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Antwortschreiben an Gutachter sind Fließtext-Urteile. Ohne Key Skip. |
| `source-quality-audit` | metric | `evals/source-quality-audit/runner.py`, `tests/evals/test_source_quality_audit_metrics.py` | Der Audit-Report gegen den Quellenbestand (Issue #606): die fünf gewichteten Dimensionen aus `skills/source-quality-audit/SKILL.md` werden aus dem Inventar nachgerechnet; ein Report, dessen Zahlen, Status oder Quellenzahl der Bestand nicht hergibt, fällt durch. Bezugspunkt ist der Bestand, nicht der Report — belegt dadurch, dass derselbe Report gegen ein fremdes Inventar kippt. Vier Gegenproben (Gesamtscore erfunden, Status geschönt, Quellenzahl aufgebläht, Einzeldimension hochgeschrieben). Die Einordnung im Fließtext bleibt API-gated (`tests/evals/test_source_quality_audit_evals.py`). |
| `sparring-partner` | structural | `tests/evals/test_sparring_partner_criteria.py` (Negativkontrollen, CI-fest), `tests/evals/test_sparring_partner_recording.py` (Snapshot, CI-fest), `tests/evals/test_sparring_partner_evals.py` (API-gated) | `recordings.json` hält fünf Transkripte aus **echten, blinden Modellaufrufen** (`evals/sparring-partner/record.py`, Claude-Code-CLI headless): die Kriterien waren vor der Aufnahme committed, der Aufnahme-Subprozess sah sie nicht. Dass der Abgleich scheitern kann, ist belegt — der erste Lauf gegen die vorab festgelegten Kriterien ergab 1/5. Zusätzlich prüfen neun format-konforme Negativkontrollen (`counter_examples.json`), dass die Kriterien überhaupt unterscheiden: vor Issue #454 bestand eine rein bestätigende Antwort sp-01/02/05 und Kapitel-Prosa bestand sp-04 — die Kriterien maßen Formattreue statt Verhalten, auf **beiden** Pfaden. Status bleibt `structural`, weil pro pytest-Lauf kein Modell befragt wird: die Transkripte sind eine eingefrorene Stichprobe aus fünf Prompts, und das im Frontmatter deklarierte Read-/Vault-Tooling war im Aufnahmelauf abgeschaltet (Material inline im Prompt). Der Nachweis für den Anthropic-API-Aufrufweg bleibt `tests/evals/test_sparring_partner_evals.py` — ohne Key Skip. |
| `style-evaluator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Stilurteil über Fließtext; der einzige offline messbare Teilaspekt ist als `humanizer-de-pipeline` abgedeckt. Ohne Key Skip. |
| `submission-checker` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Prüft Einreichungsrichtlinien in natürlicher Sprache, die je Journal variieren. Ohne Key Skip. |
| `title-generator` | structural | `tests/evals/test_rest_evals.py` (API-gated), `tests/evals/test_eval_coverage.py` | Titelqualität ist ein Geschmacks- und Präzisionsurteil ohne Referenzlösung. Ohne Key Skip. |
| `topic-brainstorm` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Ideengenerierung ist per Definition offen; ein Offline-Assert würde Vielfalt bestrafen. Ohne Key Skip. |
| `zotero-import` | structural | `tests/evals/test_triggers.py` (API-gated), `tests/evals/test_eval_coverage.py` | Der Import-Pfad ist in `tests/test_zotero_import.py` abgedeckt; die Evals prüfen Trigger und Dialog. Ohne Key Skip. |

**Bilanz:** 8 × `metric`, 51 × `structural`, 0 × `removed` (Stand Issue #606:
`abstract-generator`, `chapter-writer`, `parallel-screening`, `quality-reviewer`
und `source-quality-audit` von `structural` auf `metric` gehoben — vorher waren
es 3 × `metric` und 56 × `structural`; Stand Issue #446:
`word-export`/`slide-export` neu, beide `structural`; Stand Issue #454:
`sparring-partner` neu, `structural` — die Transkripte stammen aus echten,
blinden Modellaufrufen gegen vorab committete Kriterien, aber pro pytest-Lauf
wird kein Modell befragt; gemessen wird offline die Unterscheidungskraft der
Kriterien gegen neun Negativkontrollen, siehe Zeile oben; Stand Issue #472:
`defense-prep` neu, `structural` — Kernaussage- und Fragenkatalog-Qualität
bleiben Modellurteile, die strukturellen Vorgaben deckt `tests/test_defense_prep.py`;
seither sind weitere Verzeichnisse dazugekommen, die Bilanzzahl wird durch
`test_balance_line_matches_table_counts` gegen die Tabelle gehalten und muss bei
jedem neuen `structural`-Eintrag mitgepflegt werden).

Vor Issue #390 war der Stand 1 × `metric` (`verbatim-guard`) und 2 tote
Definitionen ohne jeden Code-Bezug (`auto-download`, `humanizer-de-pipeline`).

## Auswahl der Kern-Skills und bewusst `structural` (Issue #606)

Issue #606 hebt fünf Komponenten von `structural` auf `metric`. Das Auswahlkriterium
war **nicht** „was lässt sich leicht messen", sondern: *wessen Fehlverhalten landet
unbemerkt in der abgegebenen Arbeit?* Ein erfundener Beleg, eine erfundene Kennzahl,
ein geschönter Audit-Score — das sind Defekte, die beim Lesen nicht auffallen.

| Komponente | Gemessene Größe |
| --- | --- |
| `chapter-writer` | Zitatintegrität (Beleg löst auf, Direktzitat wörtlich, Zitatdichte) |
| `abstract-generator` | Abstract-Treue gegen den Quelltext, inkl. Fabrikations-Check auf Zahlen |
| `quality-reviewer` | Trennschärfe der vier Kriterien, gegen die der Agent urteilt |
| `parallel-screening` | Recall des Rankings gegen ein Gold-Set, gemessen an der Zufallsdiagonalen |
| `source-quality-audit` | Deckung des Audit-Reports mit dem Quellenbestand |

**Diese Komponenten bleiben ausdrücklich `structural` — und das ist kein Rückstand:**
`advisor`, `methodology-advisor`, `research-question-refiner`, `title-generator`,
`topic-brainstorm`, `literature-gap-analysis` und `peer-review`. Alle sieben lösen
offene Aufgaben ohne Referenzlösung: Es gibt keinen einen richtigen Titel, keine eine
richtige Methodenempfehlung, keine vollständige Liste der Forschungslücken. Eine
Offline-Schwelle würde dort Formattreue statt Verhalten messen — genau der Defekt,
den Issue #454 bei `sparring-partner` freigelegt hat, wo eine rein bestätigende
Antwort die Kriterien bestand. Für sie ist `structural` der ehrliche Zustand; ihr
Ausführungspfad bleibt der API-gatete Lauf.

**Was auch die fünf neuen `metric`-Zeilen nicht sind:** ein Urteil über Live-Qualität.
Die Korpora sind hand-autoriert und synthetisch. Gemessen wird die Trennschärfe gegen
bekannte, absichtlich eingebaute Defekte — belegt dadurch, dass jede Metrik eine
committete Gegenprobe hat, die ausschlagen **muss**. Was das Modell heute schreibt,
misst weiterhin nur der API-gatete Lauf.

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

| Posten | Aufrufe pro Vollauf (manuell) |
| --- | --- |
| Quality-Evals (`prompts[]`, je `with_skill` + `without_skill`) | ca. 120 |
| Trigger-Evals (45 Skills, 871 Faelle: 428 `should_trigger` + 443 `should_not_trigger`, Haiku-Klassifikation; live nachgezaehlt, Issue #614) | 871 |
| **Summe** | **ca. 991 Aufrufe** |

Ein Testfall ist keine Budget-Groesse: jeder der 871 Trigger-Testfaelle ist
selbst ein Klassifikations-*Aufruf* (1:1), waehrend ein Quality-Eval-Testfall
zwei Aufrufe buendelt (`with_skill` + `without_skill`) -- die Testfallzahl aus
`pytest --collect-only` und die API-Aufrufzahl fallen also je nach Suite
unterschiedlich auseinander.

Bei überwiegend kurzen Prompts und Haiku für den Trigger-Block liegt ein
Vollauf im niedrigen einstelligen USD-Bereich; die Quality-Evals mit einem
größeren Modell dominieren die Kosten. Ein Baseline-Lauf pro Release wäre der
sinnvolle Rhythmus, nicht pro Commit.

**Diese Tabelle gilt fuer einen manuellen Vollauf** (`workflow_dispatch` ohne
Filter). Der woechentliche geplante Lauf zieht seit der Rotation in
`tests/evals/test_triggers.py` deutlich weniger -- siehe Abschnitt "Geplanter
woechentlicher Lauf ueber ein Kern-Set" unten fuer die tatsaechliche Zahl.

**Das ist eine Bezifferung, keine Forderung.** Ob und in welcher Höhe ein
`ANTHROPIC_API_KEY` mit Budget bereitgestellt wird, entscheidet der Operator.
Issue #390 verbraucht selbst kein Budget: alle in seinem Rahmen entstandenen
Runner laufen offline (per Guard `test_no_eval_runner_requires_api_key`
erzwungen), und die 147 Skips bleiben bis zu einer Operator-Entscheidung
bestehen.

**Realer Ausführungspfad (Issue #470):** `.github/workflows/eval-behavior.yml`
ist der einzige Weg, diese ca. 991 Aufrufe eines manuellen Vollaufs tatsächlich
abzurufen — ein separat per `workflow_dispatch` auslösbarer Job, begrenzt auf
`tests/evals/` (nicht `tests/`), mit `timeout-minutes: 60` als hartem Deckel
fuer den manuellen Pfad (angehoben in #631, da der CLI-Pfad pro Aufruf
deutlich teurer ist als der SDK-Pfad; der geplante Pfad hat seit #597 ein
eigenes, hoeheres Limit — siehe Abschnitt "Geplanter woechentlicher Lauf"
unten fuer dessen tatsächliches, deutlich kleineres Aufrufvolumen). Der Job
bricht mit
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
  `test_should_not_trigger_fpr` (871 Haiku-Klassifikationsaufrufe, Stand
  Issue #614) — bei
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
  mit demselben System-Prompt; die Bezifferung „ca. 991 Aufrufe" oben bleibt
  eine Aufrufzahl, keine Kostenaussage für den CLI-Pfad.
- **`stop_reason` bleibt erhalten**, wird aber wie zuvor nicht ausgewertet
  (weder SDK- noch CLI-Pfad extrahieren es aktuell).

## Geplanter woechentlicher Lauf ueber ein Kern-Set (Issue #597)

Ein Vollauf (~991 Aufrufe, siehe API-Budget oben) laeuft nur manuell per
`workflow_dispatch`. Zusaetzlich fuehrt `.github/workflows/eval-behavior.yml`
seit Issue #597 einmal **woechentlich** (`schedule`-Trigger, Montag 07:00 UTC —
zeitversetzt zu `live-fetch-weekly.yml`, Montag 06:00 UTC) ein benanntes
**Kern-Set** aus: eine Teilmenge der API-gateten Suiten, nicht den Vollauf.

Die **eine Stelle**, an der das Kern-Set steht, ist der pytest-Marker
`eval_core_set` (registriert in `pyproject.toml`). Er sitzt als module-level
`pytestmark` an genau neun Dateien unter `tests/evals/`:

1. `test_abstract_generator_evals.py`
2. `test_chapter_writer_evals.py`
3. `test_citation_extraction_evals.py`
4. `test_quote_extractor_evals.py`
5. `test_quality_reviewer_evals.py`
6. `test_source_quality_audit_evals.py`
7. `test_sparring_partner_evals.py`
8. `test_rest_evals.py` (9 Skills + 1 Agent)
9. `test_triggers.py` (Trigger-Recall/FPR — der groesste Anteil am
   API-Budget und genau das Beispiel fuer stille Modell-Drift, das Issue #597
   im "Why" nennt; laeuft im geplanten Lauf als rotierende Stichprobe, siehe
   Unterabschnitt unten)

Reproduzierbar mit `uv run pytest tests/evals/ -m eval_core_set`. Der Guard
`test_eval_core_set_matches_documented_files` haelt diese Liste gegen den
tatsaechlichen Marker-Treffer (Datei-Ebene, nicht Test-Ebene) — eine neue
API-gatete Suite, die den Marker vergisst, faellt sonst lautlos aus dem
geplanten Lauf. Der Guard prueft ausschliesslich Datei-Zugehoerigkeit zum
Marker, keine Testfall-Zahl — er bleibt darum unveraendert wirksam, auch
wenn die Rotation unten die Zahl der pro Lauf tatsaechlich ausgefuehrten
Testfaelle innerhalb von `test_triggers.py` variieren laesst.

**Korrektur zum urspruenglichen Issue-Text:** Der Issue-Body nannte fuenf
konkrete Dateien plus vage "von `eval_runner` und `test_eval_strategy`
gegatete Faelle" als "sieben API-gatete Suiten". Codepruefung ergab: vier der
fuenf genannten Dateien (`test_sparring_partner_criteria.py`,
`test_sparring_partner_recording.py`, `test_humanizer_pipeline_evals.py`,
`test_issue_231_temperature.py`) sind **nicht** API-gated — sie laufen CI-fest
offline oder mocken `anthropic` vollstaendig. `test_eval_strategy.py` ist
ebenfalls **kein** Kandidat: sein einziger auf CLI/Key reagierender Test
(`test_skip_count_matches_real_pytest_run`) skippt gerade dann, wenn ein
Key/die CLI vorhanden ist — invertierte Pruefrichtung, kein Verhaltens-Signal.
Waere das Kern-Set woertlich aus dem Issue-Text uebernommen worden, fehlten
`test_triggers.py` und `test_rest_evals.py` — die beiden Suiten mit dem
groessten Anteil am API-Budget.

`workflow_dispatch` bleibt unveraendert: ein manueller Lauf kann weiterhin
alle Verhaltens-Evals anfordern (optional gefiltert ueber den bestehenden
`component`-Input), nur der geplante Lauf ist auf `-m eval_core_set`
eingeschraenkt. Schlaegt der geplante Lauf fehl, legt
`scripts/ci/report_eval_behavior_failure.sh` ein Issue mit der gerissenen
Suite im Titel an (Label `eval-behavior-failure`); ein wiederholter
Fehlschlag derselben Suite erzeugt kein Duplikat — dieselbe Dedup-Logik wie
`scripts/ci/report_live_fetch_failure.sh` (Issue #603), ueber eine
gemeinsame Bibliothek (`scripts/ci/lib/report_pytest_failure.sh`) geteilt statt
dupliziert. Bei korreliertem Ausfall (Modell-Drift, Quota-Abbruch mitten im
Lauf) faengt dieselbe Bibliothek eine Issue-Flut ab: hoechstens **5**
Einzel-Issues pro Lauf, alles Weitere landet gebuendelt in **einem**
Sammel-Issue, das die betroffene(n) Suite(n) im Titel nennt und ebenfalls
dedupliziert wird.

### Rotierende Stichprobe fuer `test_triggers.py` (Review-Korrektur nach #682)

Der erste Anlauf zum Kern-Set fuehrte `test_triggers.py` vollstaendig aus
(45 Skills x should_trigger/should_not_trigger = 871 der ~991 Aufrufe eines
Vollaufs) — das Kern-Set WAR damit faktisch der Vollauf, nur woechentlich
statt manuell, und widersprach dem Ziel "guenstiger als ein Vollauf".

Seit der Operator-Entscheidung im Review zu PR #682 laeuft `test_triggers.py`
im geplanten Lauf nur noch als **rotierende Stichprobe**: die 45 Skills sind
positionell (alphabetische Reihenfolge, Index modulo 4) in vier feste,
disjunkte Gruppen zu je 11-12 Skills eingeteilt (`ROTATION_GROUPS` in
`tests/evals/test_triggers.py`). Welche Gruppe ein geplanter Lauf zieht,
bestimmt die **ISO-Kalenderwoche** (`date.today().isocalendar().week % 4`) —
deterministisch und reproduzierbar aus dem Datum, kein Zufall. Ueber vier
aufeinanderfolgende Wochen kommt so jeder Skill genau einmal dran
(`test_rotation_full_cycle_hits_every_group_without_skipping` haelt das
fest, `test_rotation_groups_partition_all_skills` haelt die Vereinigung aller
Gruppen gegen `ALL_SKILLS`).

Das begrenzt `test_triggers.py` auf **~210-235 Aufrufe pro Woche** (statt
871). Zusammen mit den restlichen acht Kern-Set-Dateien (Quality-Evals,
unveraendert ~120 Aufrufe) liegt ein geplanter Lauf damit insgesamt bei
**~330-355 API-Aufrufen pro Woche** — statt vorher faktisch ~991.

Ueberschreibbar per `EVAL_TRIGGER_ROTATION_GROUP`-Umgebungsvariable
(vom Workflow gesetzt), fuer manuelle Laeufe zusaetzlich per
`workflow_dispatch`-Input `trigger_rotation_group`:

| Wert | Bedeutung |
| --- | --- |
| leer/unset | Voller Skill-Satz (Verhalten vor Issue #597 -- gilt automatisch fuer jeden manuellen Lauf ohne diesen Input). |
| `"all"` | Voller Skill-Satz, explizit erzwungen (z.B. manueller Nachvollzug eines Vollaufs). |
| `"auto"` | Rotationsgruppe der aktuellen ISO-Kalenderwoche -- setzt der geplante Lauf automatisch, sofern kein Override vorliegt. |
| `"0"`..`"3"` | Genau diese Rotationsgruppe erzwingen (z.B. um eine bestimmte Gruppe ausserhalb ihrer Woche nachzufahren). |

Ein unbekannter Wert bricht die Collection mit `ValueError` ab statt still
auf "alle Skills" zurueckzufallen -- ein Tippfehler im Input soll auffallen,
nicht lautlos das Budget sprengen.

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
