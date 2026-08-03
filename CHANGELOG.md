# Changelog

Alle bemerkenswerten Änderungen an diesem Plugin werden hier dokumentiert.

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

---

## [Unreleased]

### Added

- **node:sqlite gegen Python-Subprozess gemessen und dokumentiert (#600):**
  CI läuft jetzt auf Node 22 (`node:sqlite` unflagged ab 22.13.0) statt Node
  20. Ein Mikrobenchmark (`scripts/dev/bench_vault_bridge.mjs`) belegt den
  reinen Zugriffswegs-Unterschied — Median über 20 Wiederholungen:
  Python-Subprozess ~22,7 ms gegen `node:sqlite` in-process ~0,9 ms (~25x).
  Der Python-Subprozess bleibt trotzdem der Zugriffsweg der Node-Hooks: die
  drei Aufrufer der Bridge (`post-tool-use-decisions.mjs`,
  `mid-session-reinforcement.mjs`, `context-fidelity-guard.mjs`) rufen keine
  rohen SELECTs auf, sondern Geschäftslogik, die ausschließlich in
  `academic_vault` existiert (Dedup/Supersede, FTS5-Suche, Fuzzy-Matching) —
  eine Migration würde diese Logik in JavaScript duplizieren und damit genau
  die Divergenz zwischen zwei Speicherorten riskieren, derentwegen die Brücke
  (#527) überhaupt existiert. Begründung im Modulkopf von
  `hooks/lib/vault-bridge.mjs`.

- **Vault-Snapshot auch am Sitzungsende (#625):** Der einzige automatische
  Snapshot hing bislang am `PreCompact`-Hook, der nur in langen Sitzungen
  feuert — kurze Sitzungen erzeugten über Wochen keinen einzigen Snapshot.
  Neu ist `hooks/session-snapshot.mjs`, zusätzlich (nicht ersetzend) unter
  `Stop` verdrahtet: ein Fingerprint der Vault-DB (Größe + `mtimeMs`) gegen
  eine Marker-Datei entscheidet, ob ein neuer Export nötig ist, unveränderte
  Vaults erzeugen keinen überflüssigen Snapshot. Export läuft über die
  vorhandene `academic_vault.server.export_snapshot()` via
  `hooks/lib/vault-bridge.mjs`s Interpreter-Kaskade. Retention:
  `ACADEMIC_SNAPSHOTS_KEEP` (Default 20) `.tgz`-Dateien je Projekt, älteste
  zuerst geprunt. Fail-open bei Exportfehlern (sichtbare `⚠️`-Meldung, Sitzung
  läuft weiter). Details: `docs/reference/hooks.md`.

- **Manuelle Zitate im Material-Passport ausweisen (#595):** `manual` ist der
  einzige Pfad, auf dem ein Zitat ohne maschinelle Verifikation in den Vault
  gelangt — der Material-Passport unterschied ihn bislang nicht von
  `local-verbatim`-geprüften Zitaten. `vault.export_material_passport` weist
  jetzt je `quote_id` die verwendete `extraction_method` aus
  (`quote_extraction_methods`) und nennt Anzahl sowie Anteil manuell
  erfasster Zitate (`manual_quotes_count`, `manual_quotes_ratio`). Beide
  Felder sind immer gesetzt, auch bei 0 manuellen Zitaten — die Abwesenheit
  ist ein Ergebnis, keine fehlende Angabe. `material-passport.schema.json`
  nimmt die drei Felder in `required` auf; bereits exportierte
  `material-passport.json`-Dateien validieren rückwirkend nicht mehr gegen
  das neue Schema.

- **Eigene quantitative Auswertung vom Rohdatensatz bis zum Ergebniskapitel
  (#610):** Zwischen `instrument-design` (Instrument bauen) und
  `chapter-writer` (Ergebniskapitel schreiben) klaffte bei quantitativen
  Arbeiten eine Lücke — `meta-analysis` rechnet über **fremde** Studien, für
  eigene Erhebungsdaten gab es nichts. Neuer Skill `quantitative-analysis` mit
  dem deterministischen Rechenkern
  `skills/quantitative-analysis/scripts/analyze.py` (Subkommandos `describe`,
  `run`, `report`). Umfang der ersten Fassung bewusst begrenzt: Deskription,
  Gruppenvergleiche (t-Test unabhängig/Welch/gepaart, Mann-Whitney-U,
  Wilcoxon), Mehrgruppenvergleiche (einfaktorielle ANOVA, Kruskal-Wallis) und
  Zusammenhangsmaße (χ²-Unabhängigkeitstest, Pearson r, Spearman ρ).
  Regression, mehrfaktorielle Designs, Post-hoc-Vergleiche und Poweranalyse
  sind ausdrücklich **nicht** abgedeckt und werden im Skill so benannt, statt
  von Hand nachgeschoben zu werden.
  Die drei harten Zusagen des Issues sind strukturell erzwungen, nicht als
  Prosa: (1) Der Renderer bricht mit `ValueError` ab, sobald einem
  inferenzstatistischen Ergebnis Effektstärke, Konfidenzintervall oder
  Voraussetzungsblock fehlt — ein Bericht mit nackten p-Werten kann gar nicht
  erst entstehen. (2) Jede Voraussetzungsprüfung (Shapiro-Wilk, Levene,
  erwartete Zellhäufigkeit, Mindestfallzahl) wird mit Kennwert, p-Wert und
  Verdikt berichtet, auch die erfüllte; eine Verletzung wird im Klartext
  ausgesprochen und mit benannter Alternative versehen, wechselt das geplante
  Verfahren aber **nie** still. (3) Reproduzierbarkeit über einen
  versionierbaren Analyseplan (JSON) plus getrennte Ausgabe: `ergebnisse.json`
  trägt keinen Zeitstempel und ist zwischen zwei Läufen byte-identisch, alles
  Laufabhängige (Zeit, Pfade, Python-/numpy-/scipy-Version) steht in
  `lauf_meta.json`, und `protokoll.md` enthält die vollständige
  Wiederhol-Kommandozeile samt SHA-256 der Rohdatei.
  Die Rohdaten bleiben außerhalb des Vaults (ein Datensatz mit tausend Fällen
  gehört nicht in eine Literatur-Datenbank); in den Vault gehen nur der
  `papers`-Anker mit `source_kind='primary'`, je Ergebnis eine `figures`-Zeile
  und jede Verfahrensentscheidung als `decisions`-Eintrag mit
  `category="auswertung"`. Der Skill formuliert keine inhaltliche Deutung: Das
  Protokoll weist sie als `Deutung: [vom Autor zu ergänzen]` aus.
  Neue explizite Runtime-Dependencies `numpy` und `scipy` (lagen bislang nur
  transitiv über `sentence-transformers` im Environment). Skill-Zähler
  40 → 41 in README.md, AGENTS.md, plugin.json, marketplace.json und
  docs/reference/skills.md.

- **Vault-weite, wiederholbare Retraction-Prüfung (#604):** Der bisherige
  Crossref-Retraction-Check lief nur einmalig beim `reading-list-import` und
  erreichte damit weder Papers aus anderen Importwegen (`zotero-import`,
  `anchor-paper-survey`, `github-repo-research`, `fetch`) noch spätere
  Rückzüge längst importierter Papers (eine Dissertation läuft Jahre, ein
  2024 sauber importiertes Paper kann 2026 zurückgezogen sein). Neu ist das
  MCP-Tool `vault.check_retractions(max_age_days=90, force=False,
  project_dir=".")`: iteriert über alle Vault-Papers mit
  `source_kind='literature'` und DOI, prüft standardmäßig nur seit
  `max_age_days` nicht (oder noch nie) geprüfte Papers (neue Spalte
  `papers.retraction_checked_at`, gesetzt nur bei erfolgreichem Check — ein
  Crossref-Ausfall lässt den Zeitstempel unangetastet, sodass der nächste
  Lauf automatisch erneut versucht). Die Crossref-Abfragelogik selbst zieht
  aus `skills/reading-list-import/scripts/parse_list.py` in das neue,
  geteilte Modul `academic_vault/retraction.py` um (vgl. #527, wo zwei
  Implementierungen desselben Checks auseinanderdrifteten); der Rückgabetyp
  wechselt dabei von einem fail-safe `bool` auf ein `RetractionCheckResult`
  (`retracted`/`clean`/`error` + Fundstelle bei Treffer), weil ein
  Crossref-Ausfall im vault-weiten Check sichtbar bleiben muss statt wie
  „kein Rückzug" auszusehen. `reading-list-import` selbst bleibt an seinem
  alten Vertrag (automatisches `excluded_sources`, Ingest blockiert nie,
  Issue #383) — bewusst zwei unterschiedliche Verhalten für zwei
  unterschiedliche Kontexte. Ein Treffer wird dem Nutzer nur **vorgelegt**
  (nie automatisch nach `excluded_sources` geschrieben — ein Rückzug kann
  bewusst zitiert bleiben, wenn die Arbeit ihn selbst zum Gegenstand hat)
  und trägt die Fundstelle (Crossref-DOI der Retraction-Notiz) sowie ein
  heuristisches `cited_in_chapter`-Flag (Autor-Familienname + Jahr gegen
  `kapitel/**/*.md`, neue Funktion `db.paper_cited_in_chapters()`). Papers
  ohne DOI erscheinen als „nicht prüfbar" (`no_doi`), ein Crossref-Ausfall
  als eigene, sichtbare Fehlerkategorie (`error`, `error_count`) statt als
  leeres „keine Rückzüge gefunden". Workflow dokumentiert in
  `skills/reading-list-import/SKILL.md`. MCP-Tool-Zähler 45 → 46
  (README.md, docs/reference/vault.md).
- **KI-Offenlegungserklärung nach ICMJE 01/2026 (#605):** Neuer Skill
  `skills/ai-disclosure/` erzeugt eine zweigeteilte Offenlegungserklärung zur
  KI-Nutzung (Danksagung + Methodenteil, je DE/EN) entlang der
  ICMJE-Aufteilung vom Januar 2026 (Section V, "Use of Artificial
  Intelligence in Publishing"): Sprachpolitur/Übersetzung/Textaufbereitung
  gehören in die Danksagung, Datenerhebung/Analyse/Klassifikation/
  Abbildungserzeugung in den Methodenteil. Vorhandene Vault-Spuren
  (`quotes.extraction_method`, `papers.provenance`, `quotes.stance`,
  `codings.category_origin`) werden über vier read-only-MCP-Tools als
  **Vorschlag** vorgelegt statt behauptet — der Nutzer bestätigt oder
  korrigiert per `AskUserQuestion`. Angaben ohne Vault-Beleg (insbesondere
  die gesamte Danksagungs-Kategorie, für die es in diesem Vault kein
  Aktivitätsprotokoll gibt) sind im Output explizit als "Nutzerangabe, kein
  Vault-Beleg" markiert. Keine fakultäts-/zeitschriftenspezifischen
  Vorlagen — die Fundstelle (`skills/ai-disclosure/references/icmje-2026.md`)
  nennt die zugrunde gelegte ICMJE-Fassung, gegen die der Nutzer sein eigenes
  Merkblatt prüft. Skill-Zähler 39 → 40 (README.md, AGENTS.md, plugin.json,
  marketplace.json, docs/reference/skills.md).
- **Härteres Recall-Goldset für den Embedding-Modell-A/B (#628):** Das
  bestehende A/B (`docs/evals/recall-at-k-model-ab-375.md`, #375) erreichte
  auf 6 scharf getrennten Themenclustern mit allen drei Kandidaten
  Recall@10 = 1.0 — ein Deckeneffekt, keine Modell-Aussage. Neu ist ein
  zweites Goldset (`tests/fixtures/retrieval_goldset_hard_overlap_628.json`,
  24 Papers/2 Themen/6 eng verwandten Subtopics) sowie zwei zusätzliche
  A/B-Kandidaten in `scripts/eval/recall_at_k_model_ab.py`: `BAAI/bge-m3`
  (1024d, 8192 Tokens, kein Prompt-Präfix) und
  `intfloat/multilingual-e5-large` (1024d, 512 Tokens, `query:`/`passage:`
  -Präfixschema wie e5-small). Ein `--goldset {default,hard}`-Schalter wählt
  zwischen beiden Sets. Report: `docs/evals/recall-at-k-model-ab-hard-628.md`.
- **Tabellen strukturerhaltend extrahieren (#630):** Meta-Analyse,
  Extraktionsmatrix und Verzerrungsbewertung stehen und fallen mit Zahlen aus
  den Primärstudien — die stehen in Tabellen, und der einzige Volltextpfad
  (`normalize_whitespace()`) kollabierte dort jede Struktur zu einem
  Leerzeichen. Neu ist ein **zweiter, danebenliegender Pfad**:
  `academic_vault/tables.py` liest Zeilen, Spalten und Zellen inklusive
  Bounding-Box aus, `paper_tables` speichert sie, und die drei neuen MCP-Tools
  `vault.extract_tables()`, `vault.list_tables()` und `vault.get_table_cell()`
  machen sie abrufbar (42 → 45 Tools). Zu jeder Zahl liefert
  `vault.get_table_cell()` ein fertiges `evidence`-Feld
  (`smith2020, S. 1, Tabelle 1, Zeile 2, Spalte 2`); eine unbekannte Zelle
  ergibt `None` statt eines Näherungstreffers. Der FTS5-Volltext bleibt
  byteweise unverändert — `normalize_whitespace()` wird nicht aufgeweicht und
  vom neuen Modul nicht einmal importiert (Regressionstests:
  `test_fts5_fulltext_is_byte_identical_after_table_extraction`,
  `test_tables_module_does_not_use_normalize_whitespace`). Backend ist
  **pdfplumber** als optionales Extra (`uv sync --extra tables`), keine
  Pflichtabhängigkeit: fehlt es, läuft der Volltextpfad unverändert weiter und
  der Status `backend-missing` nennt die Nachinstallation. „Keine Tabelle
  erkannt" ist ebenfalls ein sichtbarer Status (`no-tables` /
  `no-textlayer`), kein leeres Ergebnis. `skills/extraction-matrix` füllt
  Zahlen-Spalten aus dieser Quelle statt sie als `— fehlend —` zu markieren,
  `agents/meta-analysis` zieht Kandidatenzahlen mit Beleg — `yi`/`vi` werden
  weiterhin nur nach ausdrücklicher Bestätigung übernommen. Der
  Backend-Vergleich (pdfplumber / camelot / Docling / Marker) und die bekannten
  Grenzen (verbundene Kopfzellen, zweispaltiges Layout, Tabellen ohne
  Gitterlinien) stehen in `docs/reference/vault.md`.
- **OCR mit Sprachangabe und Zeitlimit (#594):** `run_ocrmypdf()` in
  `scripts/ocr.py` ruft ocrmypdf jetzt mit `-l deu+eng` als Default auf
  (übersteuerbar per Parameter `lang` oder Env `ACADEMIC_RESEARCH_OCR_LANG`) —
  ohne `-l` nahm Tesseract Englisch an, was bei deutschen Scans mit Umlauten
  und ß messbar schlechteren Text lieferte, die Grundlage der
  `local-verbatim`-Verifikation. Der Subprozess bekommt zusätzlich ein
  Zeitlimit (Parameter `timeout` oder Env `ACADEMIC_RESEARCH_OCR_TIMEOUT`,
  sonst aus der Seitenzahl hochgerechnet mit Fallback-Festwert bei nicht
  lesbarer Seitenzahl); Überschreitung wirft die neue `OcrTimeoutError`
  (Unterklasse von `RuntimeError`), erkennbar unterschieden vom inhaltlichen
  OCR-Fehlschlag. Fehlt ein angefordertes Tesseract-Sprachpaket (ocrmypdf-Exit
  3), nennt die Fehlermeldung Paketname und Installationsweg
  (`brew install tesseract-lang` / `apt-get install tesseract-ocr-<lang>`)
  statt still auf Englisch zurückzufallen.
- **Guard-schwächende Env-Schalter sichtbar geloggt (#519, Audit R7):** Die
  drei guard-schwächenden Schalter `ACADEMIC_CITATION_AMBIGUOUS`,
  `ACADEMIC_CITATION_CASCADE` und `ACADEMIC_CITATION_MAX_PER_WRITE`
  hinterließen bei Nutzung keine Audit-Spur. `verbatim-guard.mjs` protokolliert
  jeden gesetzten Schalter jetzt pro Guard-Lauf einzeln (Name, Wert,
  Zieldatei) nach `~/.academic-research/vault-guard-env-switch.log`
  (Env-Override `VAULT_GUARD_ENV_SWITCH_LOG`, 0600/0700, fail-open — analog zum
  Bypass-Log aus #381). Der bestehende SessionStart-Hook
  `hooks/bypass-log-report.mjs` (#517) liest zusätzlich dieses Log (eigener
  Offset-Merkposten `vault-guard-env-switch-report-state.json`, Env-Override
  `VAULT_GUARD_ENV_SWITCH_REPORT_STATE`) und hängt bei neuen Einträgen einen
  zweiten Report-Abschnitt an — kein neuer Hooks.json-Eintrag. Geschrieben wird
  nur bei geänderter Schalter-Kombination (Dedup über den ganzen Block), sonst
  meldete der Report für eine einzige dauerhafte Einstellung dutzende
  „neue Nutzungen".
- **`context-fidelity-guard.mjs` — warnender Kontexttreue-Hook (#522):** Neuer
  `PreToolUse`-Hook (`Write|Edit|MultiEdit`) prüft beim Kapitel-Write jedes im
  Vault verifizierte Zitat gegen seinen **echten** Quellkontext und markiert
  Quote-Mining-Muster mit `[KONTEXT-PRÜFEN]`. Drei bewusst konservative
  lexikalische Signale im `PreToolUse`-Pfad: Kontrastmarker am Anfang von
  `context_after`, Rahmen-Marker am Ende von `context_before`, Hedge-Verlust
  Quelle → Kapitel. (Signal 4 — semantische Distanz über `quote_embeddings`
  (#521) — ist im `PreToolUse`-Pfad deaktiviert, um torch/sentence-transformers-
  Importe zu vermeiden; Funktionen `get_quote_embedding` und
  `quote_context_similarity` bleiben für zukünftige Nutzung erhalten.) Trägt das
  Kapitelfenster selbst ein Kontrastsignal, ist die Kontrastivität offengelegt
  und Signal 1+2 entfallen. Der Hook **blockiert nie** (Exit 0, kein
  `permissionDecision`); die harte Linie bleibt der deterministische
  `verbatim-guard`. Prüfbar ist nur ein Zitat mit `context_source = 'fulltext'`
  (#520) — gefüllte Kontextfelder allein sind kein Beleg für echten Quellkontext.
  Bei jedem Write mit Zitaten wird die Abdeckung ausgewiesen
  (`Abdeckung: x von y Zitaten prüfbar`), jedes nicht prüfbare Zitat mit Grund
  benannt statt still übersprungen. Der Vault-Lookup läuft in **einem**
  Python-Subprozess mit erzwungenem `HF_HUB_OFFLINE=1`.
- **`quote_embeddings` nach bestandener Prüfung befüllt, inkl. Backfill (#521):**
  Neue Funktion `academic_vault.server.embed_quote(db_path, quote_id,
  embedder=None)` erzeugt ein lokales e5-Embedding aus `context_before +
  verbatim + context_after` (Fallback: nur `verbatim` ohne Kontext) und
  schreibt es in die vec0-Tabelle `quote_embeddings`. `vault.add_quote` ruft
  die Funktion — non-fatal, Muster `_maybe_resolve_quote_context` (#520) —
  nach dem Insert für alle drei gültigen `extraction_method`-Werte auf
  (`citations-api`/`manual`/`local-verbatim` gelten laut CHECK-Constraint als
  "bestandene Prüfung", geraten wird nie). Fehlendes Embedding-Backend oder
  nicht ladbare sqlite-vec-Extension degradieren sauber (geloggt, kein
  Absturz) — anders als `chunk_embeddings` hat `quote_embeddings` KEINE
  BLOB-Basistabelle, ohne Extension ist Embedding hier ein vollständiges
  No-Op (bewusste Scope-Entscheidung). Neue idempotente Backfill-Funktion
  `academic_vault.migrate.backfill_quote_embeddings(db_path, limit=None)` +
  CLI-Flag `--backfill-quote-embeddings` füllen Bestands-Quotes ohne
  `quote_embeddings`-Eintrag nach. Kein Schema-Versionssprung — die leere
  vec0-Tabelle `quote_embeddings` existierte bereits seit #217/#219, nur
  ungenutzt.
- **`vault.verify_verbatim` — read-only Vorschau des Verbatim-Prüfpfads (#513):**
  Neues MCP-Tool `vault.verify_verbatim(paper_id, candidate)` prüft einen
  Zitat-Kandidaten gegen den lokalen PDF-Volltext eines Papers und liefert
  **immer** ein Ergebnis-dict `{status, verbatim, pdf_page, ratio}` zurück
  (`status` ∈ `"exact"`/`"snapped"`/`"no-match"`/`"no-textlayer"`) — anders
  als das Schreib-Gate `vault.add_quote(extraction_method="local-verbatim")`
  (#512) wirft es bei Nicht-Treffer keine `ValueError`, sondern gibt Agenten
  so die Möglichkeit, Kandidaten iterativ zu prüfen und zu korrigieren, bevor
  `add_quote` endgültig ablehnt. Das Tool schreibt nichts in die Datenbank.
  Paper-/`pdf_path`-Auflösungsfehler (unbekanntes Paper, fehlender/nicht
  lesbarer `pdf_path`) bleiben `ValueError` mit verständlicher Meldung —
  Bedienfehler des Aufrufers, keine Zitat-Prüfergebnisse. Intern teilt sich
  `academic_vault.server.verify_verbatim_preview()` die Paper-/`pdf_path`-
  Auflösung mit `_verify_local_verbatim()` über einen neuen gemeinsamen
  privaten Helfer (`_resolve_verbatim_pdf_path`), um Drift zwischen den
  beiden Prüfpfaden zu vermeiden.

- **`quote-fidelity-auditor` — Richter-Subagent mit Abstract-Abgleich (#523):**
  Neuer Subagent `agents/quote-fidelity-auditor.md` (Judge-Pattern analog
  `screening-judge.md`/`risk-of-bias.md`) urteilt über ein bestehendes Zitat
  gegen Kapitel-Behauptung, Quote-Kontext (`context_before`/`context_after`)
  und Paper-Abstract (`csl_json.abstract`) und liefert ein Urteil
  `faithful`/`overstated`/`context-stripped`/`polarity-flip`/`unsupported`.
  Der Abstract-Abgleich ist explizit die dritte, nachgeordnete Prüfebene und
  erzeugt allein nie ein Negativ-Urteil — Detail-Zitate jenseits des
  Abstracts bleiben legitim; fehlt `abstract`, wird das explizit als
  übersprungen markiert statt geraten. Neues Vault-Tool
  `vault.set_quote_stance(quote_id, stance)`
  (`academic_vault/db.py`/`server.py`) ergänzt den bisher fehlenden
  Schreibpfad für nachträgliche Audits — `add_quote()` befüllt `stance` nur
  bei Neuanlage. Das Mapping Verdict→`stance` ist im Agenten dokumentiert
  (`unsupported` persistiert bewusst nichts, um keine Scheingenauigkeit zu
  erzeugen). Der Agent hat kein `Write`/`Edit`/`MultiEdit` im
  Tool-Frontmatter — Urteil + Begründung gehen als Prosa an den aufrufenden
  Kontext, kein Auto-Rewrite von Kapiteltext. `hooks/claim-drift-guard.mjs`
  verweist in seiner Warnung additiv auf den neuen Agenten als Prüfoption.
  `set_quote_stance` respektiert wie jeder andere Schreibpfad den
  Material-Passport-Lock (`VaultLockedError`, Issue #380). Die Doku-Zähler
  sind mitgezogen: 41 → 43 MCP-Tools in derselben Merge-Runde wie
  `vault.verify_verbatim` (#513) (`README.md`, `docs/reference/vault.md`,
  `tests/helpers/smoke_core.py`, `tests/test_issue_207_readme_mcp_tools.py`)
  und 27 → 28 Agents (`README.md`, `AGENTS.md`, `docs/reference/agents.md`
  inklusive Dispatch-Zeile `manuell`).

- **`resolve_quote_context` — echter Quellkontext statt modell-erinnertem (#520):**
  Neue Funktion `academic_vault.server.resolve_quote_context(db_path, quote_id,
  window=600)` zieht ±600 Zeichen ECHTEN Text aus `paper_fulltext` um die
  Fundstelle eines Zitats (erst exakter Substring-Treffer, sonst Fuzzy-Fallback
  via `rapidfuzz.fuzz.partial_ratio_alignment`, weil der Volltext-Extraktor
  vom Seiten-Extraktor der Verbatim-Prüfung abweichen kann — Ligaturen,
  Trennstriche) und persistiert `context_before`/`context_after` samt neuer
  Spalte `quotes.context_source` (`'fulltext'` oder `NULL`). `vault.add_quote`
  ruft die Funktion für `extraction_method='local-verbatim'` nach dem Insert
  non-fatal auf — ein Kontext-Fehlschlag rollt das bereits verifizierte Zitat
  nicht zurück. Ohne `paper_fulltext`-Eintrag oder ohne Fundstelle bleibt alles
  unverändert (No-Op) — geraten wird nie. `CURRENT_SCHEMA_VERSION` 6→7.

### Removed

- **Keine Plugin-Funktion braucht mehr einen `ANTHROPIC_API_KEY` (#632):** Wer das
  Plugin installiert, hat bereits Claude Code — also eine Sitzung mit Modellzugang.
  Ein zweiter, selbst bezahlter Schlüssel war eine Hürde bei der Installation und
  ein zweites Abrechnungsverhältnis für dieselbe Sache. Alle vier verbliebenen
  SDK-Pfade sind entfallen:
  - `scripts/batch_api.py` samt der Optionen **`/search --batch` und
    `/history --batch`**. Das Relevanz-Scoring großer Treffermengen lief darüber
    asynchron über die Anthropic-Message-Batches-API (50 % Rabatt, ~1 h Latenz,
    Abholung per Job-ID) und setzte dafür einen eigenen `ANTHROPIC_API_KEY`
    voraus. **Bewusster Verzicht:** Batch-Rabatt und asynchrone Abholung fallen
    weg; auch ≥ 50 Paper laufen jetzt über `agents/relevance-scorer` in Gruppen
    von 10 — mehr Agent-Läufe statt eines Batch-Jobs, bezahlt aus dem
    Sitzungskontingent. Der Hebel gegen Kosten liegt damit vor dem Scoring
    (`--limit`, `--mode`), nicht daneben.
  - `academic_vault/files_api.py` und mit ihm das MCP-Tool **`vault.ensure_file`**
    (43 → 42 Tools). Der Pfad war seit #535 Legacy und seit #511/#532 durch die
    lokale Verbatim-Verifikation ersetzt. `vault.stats()` verliert dadurch das
    Feld `cached_files`: ohne Upload-Cache hätte es keinen Schreiber mehr und
    stünde dauerhaft auf 0 — genau die Phantomgröße, die #387/#453/#534
    verbieten. Die Spalten `file_id`/`file_id_expires_at` bleiben (keine
    Schema-Migration), der schreiberlose Setter `VaultDB.set_file_id()` nicht.
  - `generate_context_sentence()`/`_get_anthropic_client()` in
    `academic_vault/embeddings.py` samt `chunking.anthropic_context_provider()`
    und dem Env-Schalter `VAULT_CONTEXTUAL_EMBEDDING`. Kontextsätze kommen
    ausschließlich aus dem deterministischen Offline-Default
    `default_context_sentence()`; `ingest_paper_embeddings()` gibt entsprechend
    wieder einen blanken `int` zurück statt eines Ergebnisobjekts mit
    `context_failures`.
  - `llm_parse()` in `skills/reading-list-import/scripts/parse_list.py`. Das
    Skript ist jetzt zweistufig: `--extract` gibt den Rohtext einer
    Literaturliste aus, der Skill parst ihn in der Sitzung, `--entries` nimmt das
    fertige JSON entgegen und übernimmt DOI-/ISBN-Auflösung, Retraction-Check und
    Vault-Import. Das war der einzige der vier Pfade, der im Normalbetrieb lief.

  `anthropic` steht damit in keiner Datei mehr, die ein Endnutzer installiert
  (`scripts/requirements.txt`, `academic_vault/requirements.txt`,
  `[project.dependencies]`); als Dev-Extra bleibt es nur für
  `tests/evals/eval_runner.py` erhalten und entfällt dort mit #631. Neuer Guard
  `tests/test_issue_632_no_anthropic_sdk.py` lässt einen Test rot werden, sobald
  ein Produktivpfad das SDK wieder importiert, eine Endnutzer-Doku den Schlüssel
  wieder als Voraussetzung nennt oder `vault.ensure_file` zurückkehrt.

### Changed

- **Citation-Guard: ein Papers-Scan je Write statt je Beleg (#501):**
  `VaultDB.find_papers_by_author_year()` las bisher pro Aufruf die komplette
  `papers`-Tabelle inklusive `json.loads()` je Zeile; `server.verify_citation()`
  lief je Beleg einzeln, sodass ein Kapitel mit dem vollen Kontingent
  (`ACADEMIC_CITATION_MAX_PER_WRITE`, Default 100) gegen einen Vault mit
  einigen tausend Papers 100 Full Scans innerhalb des 10-s-Timeouts von
  `hooks/verbatim-guard.mjs` auslöste — riss das Timeout, meldete der Hook
  `unavailable` und alle Belege liefen fail-open mit `[UNVERIFIED]` durch.
  Neuer Batch-Einstieg `server.verify_citations(db_path, items)` teilt sich
  eine `VaultDB`-Instanz und genau einen
  `VaultDB._papers_snapshot()`-Aufruf über alle Belege eines Writes;
  `verify_citation()` bleibt als dünner Ein-Item-Wrapper mit unverändertem
  Rückgabeformat erhalten. `hooks/verbatim-guard.mjs::verifyCitationsInVault`
  ruft jetzt `verify_citations` statt einer Listcomprehension über
  `verify_citation` je Item auf.

- **`page_offset` wird beim Buch-Import bestätigt statt still gespeichert (#538):**
  `skills/book-handler/SKILL.md` Schritt 2.5 übernahm das Ergebnis von
  `scripts/page_offset.py` ohne Rückfrage in `vault.set_page_offset` — ein
  falscher Offset verschob damit stillschweigend alle Seitenzahlen des Buchs
  (Audit-Risiko R2). Neu steht vor dem Speichern ein `AskUserQuestion`-Gate;
  die Optionszeile nennt den Offset und ein Beispiel-Mapping („PDF-Seite
  {offset+1} = gedruckte Seite 1") zur Plausibilisierung. Die zweite Option
  führt zur manuellen Offset-Eingabe, nicht zum Abbruch; der berechnete Wert
  wird nie ungefragt übernommen. `AskUserQuestion` ist jetzt auch in
  `allowed-tools` deklariert. Die Offset-Berechnung selbst bleibt unverändert
  (#384/#73). Der Gate-Text lässt `SKILL.md` um 447 Zeichen wachsen; die
  Guard-Baselines wurden entsprechend angehoben — `skill_sizes.json`
  5362→5809 (Marge von `test_token_reduction` bleibt exakt 1420 Zeichen),
  `tokens.json` 862→1098 (neu gemessener Stand, der +20%-Drift-Korridor
  reichte nicht mehr). Etabliertes Repo-Muster, vgl. 9962c22 (#540);
  `tests/test_issue_538_page_offset_gate.py` hält beide Anhebungen an den
  tatsächlichen Zuwachs gebunden.
- **`bypass-log-report.mjs` zählt eine Bypass-Nutzung nicht mehr doppelt
  (#522):** Seit `context-fidelity-guard.mjs` am selben `PreToolUse`-Event
  hängt, protokollieren zwei Guards denselben Bypass. Der SessionStart-Report
  faltet Log-Zeilen mit gleichem Pfad innerhalb derselben Sekunde zu einer
  Nutzung zusammen; Zeilen ohne parsebaren Zeitstempel/Pfad bleiben
  ungefaltet (im Zweifel eine Nutzung zu viel melden statt eine zu
  verschweigen).
- **`files_api.py` ist ein optionaler Legacy-Pfad (#535):** Seit der
  Umstellung auf lokale Verbatim-Zitate (#507/#512/#532) hängt kein
  Standard-Workflow mehr an der Anthropic-Files-API — das Modul bleibt nur
  für den optionalen Citations-API-Pfad mit eigenem `ANTHROPIC_API_KEY`
  erhalten und darf ohne Key keine Fehler mehr erzeugen.
  `academic_vault.server.ensure_file()` gibt jetzt `str | None` zurück: ohne
  Key `None` statt einer Exception, während unbekanntes Paper bzw. fehlender
  `pdf_path` weiterhin (und **vor** dem Key-Check) `ValueError` werfen —
  ein fehlender Key verdeckt keine Datenfehler. Das MCP-Tool
  `vault.ensure_file` folgt der Signatur. Ohne Key wird kein
  `anthropic.Anthropic`-Client mehr gebaut (Guard in `_get_client()`, neue
  `FilesAPINotConfiguredError` für direkte Modul-Aufrufe); die
  Beta-Abhängigkeit steht nur noch in der Konstante
  `files_api.FILES_API_BETA` (`files-api-2025-04-14`). `zotero_pull.py`
  prüft die Verfügbarkeit explizit vor dem Aufruf und zählt einen Skip in
  `ImportResult.files_api_skipped` (CLI-Zeile), statt jede Exception in
  `result.errors` zu schlucken — dort landen nur noch echte Upload-Fehler
  **mit** Key. Die zuvor ungetesteten Zweige (TTL-Reupload, gültiger Cache,
  Cache-Miss ohne `papers`-Zeile) haben jetzt Tests
  (`tests/test_issue_535_files_api_legacy.py`); der Legacy-Status ist in
  Modul-Docstring und `docs/reference/vault.md` dokumentiert. Kein Tool
  entfernt, keine Schema-Änderung.
- **Kapitel-Zitat-Zuordnung als echtes `AskUserQuestion`-Gate (#518):**
  `skills/citation-extraction/SKILL.md` Schritt 6 „Kapitelzuordnung" hing
  bisher nur an der Prosa-Regel „User bestätigt Zuordnungen" — kein
  Mechanismus erzwang die Freigabe, bevor die Zuordnung weiterverwendet wurde
  (Audit-Risiko R5). Neu gilt der Vorschlag erst nach einer strukturierten
  `AskUserQuestion`-Bestätigung („Übernehmen" / „Ablehnen") als angenommen;
  Ablehnung verwirft die Zuordnung ohne Vault-Schreibzugriff und ohne
  Fehler-Framing (Default-Pfad, kein Abbruch). `AskUserQuestion` ist jetzt in
  `allowed-tools` deklariert; der Prosa-Bullet unter „Wichtige Regeln"
  verweist auf das Gate statt eigenständig zu stehen (analog zum
  Präzedenzfall `material-passport`/#536/PR #567). Reine Doku-Änderung, kein
  Vault-Schema-Change — die Kapitel-Zuordnung ist nirgends als eigenes
  Vault-Feld persistiert.

- **`quality-reviewer` eskaliert ab Iteration 2 statt durchzuwinken (#528):**
  Der Agent gab bei `iteration >= 2` unabhängig von offenen Findings ein
  PASS-with-warnings zurück (`agents/quality-reviewer.md` „Loop-Begrenzung" und
  Strategie-Punkt 5, gespiegelt in
  `skills/chapter-writer/references/quality-review-config.md`) — das
  Qualitäts-Gate war damit genau dann wirkungslos, wenn es zählt (Audit-Risiko
  R6). Neu gibt es ein drittes Verdict `ESCALATE`, gekoppelt an `iteration >= 2`
  **und** mindestens ein Kriterium mit FAIL; ohne offenes Finding bleibt PASS
  unverändert. Das Entscheidungs-Gate liegt beim Aufrufer, nicht im Subagenten
  (der läuft mit `tools: [Read]` und hat keinen User-Kanal): `chapter-writer`
  legt die Restprobleme vor und fragt via `AskUserQuestion` — akzeptieren /
  weitere Revision / abbrechen; das Tool ist jetzt auch in `allowed-tools`
  deklariert (es war für das Outline-Gate bereits undeklariert im Einsatz). Die
  Loop-Begrenzung bleibt erhalten: „weitere Revision" gewährt genau eine
  zusätzliche Runde, danach wird erneut eskaliert statt still akzeptiert.
  `evals/quality-reviewer/evals.json` prüft beide Pfade (`qr-03` ESCALATE mit
  offenem Finding, `qr-04` PASS am Iterations-Limit ohne Finding). `advisor`
  und `abstract-generator` rufen denselben Agenten auf, bleiben hier aber
  unverändert — ihr SKILL.md-Größenbudget ist ausgereizt (advisor: 2 Zeichen
  Luft), das Nachziehen erfordert eine eigene Textkompression.

### Added

- **Zotero-Highlights werden beim Import gegen den PDF-Volltext verifiziert
  (#529, Audit-Risiko R1):** `skills/zotero-import/scripts/zotero_pull.py`
  ruft beim Annotations-Import künftig `academic_vault.verbatim.verify_verbatim_with_pages()`
  (#511) gegen das lokal heruntergeladene PDF auf, statt `annotationText`
  ungeprüft als `quotes.verbatim` zu speichern. Belegbare Highlights
  (`exact`/`snapped`) werden mit dem gesnappten Quelltext gespeichert; nicht
  belegbare (`no-match`, `no-textlayer`, fehlendes PDF, Verifikationsfehler)
  landen **nicht** in `quotes`, sondern werden über die neuen
  `ImportResult`-Felder `unverified_quotes`/`unverified_details` gezählt und
  von der CLI ausgewiesen — kein stilles Verwerfen. **Bewusste
  Verhaltensänderung:** Annotationen ohne heruntergeladenes PDF wurden bisher
  trotzdem als Quote gespeichert; ohne PDF ist keine Verifikation möglich,
  sie zählen jetzt als unverifiziert statt gespeichert zu werden. Details:
  `skills/zotero-import/references/annotations.md` (Abschnitt „Verifikation
  gegen den PDF-Volltext").
- **Fail-closed `extraction_method="local-verbatim"` (#512):** `vault.add_quote`
  akzeptiert einen dritten Herkunftsnachweis und verifiziert ihn SELBST gegen
  den lokalen PDF-Volltext des Papers (`academic_vault/verbatim.py` aus #511) —
  vor jedem Schreibzugriff. Unbekanntes Paper, fehlender oder nicht lesbarer
  `pdf_path` sowie die Prüfstatus `no-match`/`no-textlayer` werfen `ValueError`,
  und es wird nichts gespeichert; bei `exact`/`snapped` landen der Wortlaut AUS
  DER QUELLE (nicht der übergebene Kandidat) und die VERIFIZIERTE Seite im
  Vault, ein abweichend übergebenes `pdf_page` wird verworfen und geloggt. Das
  Enforcement sitzt damit im Vault statt in einem Hook und ist bypass-immun; es
  schließt zugleich die Lücke, dass eine beliebige nicht-leere
  `api_response_id` als „Beweis" durchging. Die Pfade `citations-api` und
  `manual` sind unverändert — `manual` bleibt der dokumentierte Ausweichweg für
  die bekannten Grenzen der Prüfung (seitenübergreifende Zitate,
  Wort-Auslassungen). `import`-Kosten von pypdf/rapidfuzz fallen dank Lazy
  Import nur auf dem neuen Pfad an.

- **Bypass-Report beim SessionStart (#517):** Der Bypass-Marker
  `<!-- vault-guard: skip -->` ist für Ausnahmefälle legitim, blieb aber
  bisher unbemerkt — nichts las das seit #381 geschriebene Log
  (`~/.academic-research/vault-guard-bypass.log`). Der neue, rein lesende
  SessionStart-Hook `hooks/bypass-log-report.mjs` meldet Anzahl und
  betroffene Dateien NEUER Bypass-Nutzungen seit dem letzten SessionStart auf
  stdout, ohne neue Einträge bleibt er stumm. Der Merkposten „zuletzt
  gemeldet" liegt in `~/.academic-research/vault-guard-bypass-report-state.json`
  (0600/0700). Fail-open bei jedem Lese-/Rotationsfehler — der SessionStart
  wird nie blockiert. Die Schreibseite (`verbatim-guard.mjs`) ist unverändert.
- **`quote-extractor` ohne Citations-API (#514):** Der Agent verlangte im
  Abschnitt „Quellen-Bindung" bislang die Citations-API mit
  Files-API/`file_id` (`vault.ensure_file`) als einzigen Verifikationspfad —
  identisch zum bei `figure-verifier` (#533) bereits abgelösten Muster, das
  einen separaten `ANTHROPIC_API_KEY` voraussetzte und den Agenten ohne
  diesen Key funktionslos machte. Analog zu `figure-verifier`/`risk-of-bias`
  liest `quote-extractor` das PDF jetzt lokal: `vault.get_paper(paper_id)` →
  `pdf_path` → `Read`, optional vorab per `vault.verify_verbatim` geprüft.
  Persistiert wird über `vault.add_quote(extraction_method="local-verbatim")`
  (#512), das serverseitig fail-closed gegen den PDF-Volltext verifiziert und
  bei Erfolg Wortlaut+Seite AUS DER QUELLE zurückschreibt — kein
  Anthropic-API-Call mehr im Standardpfad, kein separater, abgerechneter
  Console-Key nötig. `tools:`-Frontmatter ersetzt `vault_ensure_file` durch
  `vault_get_paper` (Pflicht) und `vault_verify_verbatim` (optional);
  `maxTurns` von 5 auf 8 angehoben (PDF-Read + optionale Vorabchecks +
  mehrere `add_quote`-Aufrufe, analog `figure-verifier`). Der bisherige
  Citations-API-Block bleibt als kurzer Opt-in-Hinweis erhalten (z. B. für
  HTML-/Markdown-Quellen ohne PDF-Volltext) — das `citations[]`-Array pro
  Zitat entfällt damit ersatzlos aus dem Standard-Output; das seitengenaue
  Nachschlagen dafür ist Scope von `skills/citation-extraction` (eigenes
  Issue). Qualitätsregeln unverändert: ≤ 25 Wörter/Zitat, max. 3/Paper,
  Titel-Plausibilitätscheck (`possible_pdf_mismatch`, jetzt gegen den
  `Read`-Output statt die Citations-API-Response geprüft), „lieber 0 Zitate
  als schlechte Zitate".
- **`figure-verifier` ohne Citations-API (#533):** Der Agent verlangte in
  Schritt 2 der Vorgehensweise bislang die Citations-API mit
  `document`-Parameter (`file_id`) als einzigen Verifikationspfad — identisch
  zum Muster in `skills/chapter-writer/references/citations-api.md`, das einen
  separaten `ANTHROPIC_API_KEY` voraussetzt und den Agenten ohne diesen Key
  funktionslos machte. Analog zu `risk-of-bias` liest `figure-verifier` das
  PDF jetzt lokal: `vault.get_paper(paper_id)` → `pdf_path` → `Read(pdf_path,
  pages=...)`, kein externer API-Call mehr nötig. `tools:`-Frontmatter ersetzt
  `vault_ensure_file` durch `vault_get_paper`. Nicht verifizierbare Seiten
  (fehlender/ungültiger `pdf_path`, korrupte/leere Seite, OCR fehlgeschlagen)
  werden explizit im neuen `unverifiable_pages`-Feld des Outputs gemeldet statt
  still übersprungen.
- **Werkzeugsatz für den empirischen Teil (#473):** Zwei neue Skills schließen
  die Lücke zwischen Methodenwahl und Ergebniskapitel. `instrument-design`
  leitet aus Forschungsfrage, Unterfragen und Methodik in `academic_context.md`
  ein Erhebungsinstrument ab und liefert dazu verpflichtend eine
  Rückverweis-Matrix (jede Frage → genau eine Unterfrage bzw. die
  Forschungsfrage); ohne Forschungsfrage bricht der Workflow ab und verweist auf
  `academic-context`/`research-question-refiner`. `qualitative-coding` nimmt
  Transkripte belegfähig auf und unterstützt die Kategorienbildung induktiv wie
  deduktiv. Der deterministische Teil liegt in
  `skills/qualitative-coding/scripts/transcript_import.py` (Subcommands
  `import`/`overview`/`codebook`): Absatz-Segmentierung mit Sprecherkürzel und
  optionalem Timecode, idempotenter Re-Import über eine aus `(paper_id, seq)`
  abgeleitete `segment_id`, Kodier-Übersicht und Kodierleitfaden nach
  `empirie/kodierleitfaden.md` inklusive `vault.add_decision(category="kodierung")`.
  Vault-Schema auf Version 5: neue Spalte `papers.source_kind`
  (`literature`|`primary`) plus die Tabellen `transcript_segments` und
  `codings`, vier neue MCP-Tools (`vault.add_transcript_segment`,
  `vault.list_transcript_segments`, `vault.add_coding`, `vault.list_codings`,
  37 → 41). Eigenes Erhebungsmaterial liegt bewusst in derselben
  `papers`-Tabelle wie Literatur — nur so greift die bestehende Belegkette, und
  ein Interviewzitat wird von `hooks/verbatim-guard.mjs` genauso geprüft wie ein
  Literaturzitat (kein Sonderweg). Unterschieden werden beide über
  `source_kind`; `scripts/export-literature-state.mjs` filtert Primärmaterial
  aus dem Literatur-Snapshot. `scripts/project_bootstrap.py` legt zusätzlich
  `empirie/` an. Skill-Zähler 37 → 39.
- **Fetcher-Agents für HathiTrust, Internet Archive/Open Library und MDZ (#450):**
  Drei neue OA-Subagenten (`agents/hathitrust-fetcher.md`,
  `agents/internetarchive-fetcher.md`, `agents/mdz-fetcher.md`) nach dem
  `doabooks-fetcher`/`oapen-fetcher`/`tib-fetcher`-Muster: nur `browser-use`,
  identisches 5-Status-Output-Schema (`success`/`metadata_only`/
  `pickup_required`/`captcha`/`no_match`). Alle drei Archive digitalisieren
  überwiegend gemeinfreie Werke, führen aber pro Treffer eine *Zugriffsstufe*
  (Vollansicht vs. eingeschränkter Zugriff — HathiTrust "search-only",
  Internet-Archive-Borrow/CDL, MDZ-Katalogisat ohne Digitalisat): das
  `reason`-Feld bei `metadata_only` trägt dafür ein festes Vokabular
  (`"Zugriffsstufe: …"`), das gesperrte 5er-Enum bleibt unangetastet. Der
  `success`-Output bekommt zusätzlich ein `edition`-Feld — Jahr/Ausgabe/Verlag
  werden ausdrücklich aus dem Katalog-/Metadaten-Eintrag des konkret
  heruntergeladenen Digitalisats entnommen, nie aus der Eingabe-ISBN/-Titel
  übernommen (AC4: verschiedene Bibliotheken digitalisieren teils
  unterschiedliche Auflagen desselben Werks). `agents/book-fetcher.md`
  (Schritt 3 OA-Kette + Tools-Frontmatter) und
  `tests/helpers/book_fetcher_router.py` (`OA_SUBAGENTS`) wurden additiv um
  die drei neuen Hosts erweitert und ans Ende der bestehenden OA-Liste
  angehängt — lizenzfrei, daher weiterhin nachweislich vor jedem
  Verlags-Subagenten (AC3, geprüft in
  `tests/test_book_fetcher.py::test_all_oa_metadata_only_then_springer_success`).
  Jeder Agent bekommt einen passenden `config/browser_guides/*.md` mit
  Access-Level-Matrix und dem expliziten Verbot, Suchtreffer-/Snippet-Text zu
  einem Volltext-Ersatz zusammenzusetzen (AC2). HTTP-429-Rate-Limits werden
  als `metadata_only` mit Statuscode + Retry-Hinweis diagnostiziert statt als
  `no_match` fehlgedeutet (Operator-Hinweis 2026-07-30 zu PR #498: ein echtes
  HathiTrust-Rate-Limit darf den AC-Verify nicht mehr allein zum Scheitern
  bringen). Neuer Test `tests/test_free_archive_fetchers.py` (Analog zu
  `tests/test_oa_fetchers.py`), neue `evals/free-archive-fetchers/evals.json`
  (3 Cases, je 1 bekannter gemeinfreier Testtitel pro Archiv, Status
  `structural` in `docs/evals/STRATEGY.md` — netzabhängige Live-Downloads,
  gleiche Begründung wie `oa-fetchers`). Agent-Zähler 24 → 27
  (`docs/reference/agents.md`, `AGENTS.md`, `README.md`). Fixrunde: das
  `edition`-Feld reicht jetzt bis in den Vault durch — `book-fetcher.md`
  übernimmt es aus der OA-Subagenten-Antwort unverändert in sein eigenes
  Output-Schema, und `commands/fetch.md` ruft bei `status: success`
  tatsächlich `mcp__academic-vault__vault_add_paper` auf (`csl_json` trägt
  `edition` nur, wenn die Quelle es meldet — nie ein erfundener Platzhalter).
  Geprüft in `tests/test_issue_450_vault_wiring.py`, inkl. echtem
  `add_paper()`/`get_paper()`-Roundtrip gegen eine reale `VaultDB` (AC4). Ein
  `title`-Feld fehlt in der Kette weiterhin — kein Subagent liefert bislang
  einen Titel aus der Quelle selbst; das bleibt ein offener, größerer
  Koordinationspunkt außerhalb von #450.
  **Zweite Fixrunde — AC1 real belegt statt zugesagt:** Die vorige Fassung hat
  den geforderten Live-Nachweis mit „Realer Live-Lauf bleibt Operator-Sache"
  beantwortet; belegt war damit nichts, denn `evals/free-archive-fetchers/evals.json`
  ist `structural` und `docs/evals/STRATEGY.md` definiert das ausdrücklich als
  „kein grün". Der Beleg liegt jetzt als nachfahrbares Artefakt in
  `evals/free-archive-fetchers/live-verification.json` (URL-Kette, HTTP-Status,
  Bytes, Prüfsumme, Seitenzahl je Lauf), nach dem Muster von Issue #449:
  Internet Archive liefert real ein 922-seitiges Digitalisat der Erstausgabe von
  1813 ohne Login (byteweise über zwei Abrufe reproduzierbar), MDZ das
  Grimm-Digitalisat als Gesamtwerk-PDF mit 471 Seiten, HathiTrust antwortet am
  Download-Endpunkt mit HTTP 403 und der Sperrseite „Error - Blocked from
  HathiTrust" — 2 von 3 Anbietern real als PDF belegt, wie AC1 es verlangt.
  Nachfahrbar mit `RUN_LIVE_FREE_ARCHIVE_FETCH=1 uv run pytest tests/test_issue_450_live_fetch.py`
  (opt-in, nicht im CI); hermetisch geprüft in
  `tests/test_issue_450_fetcher_evidence.py`.
  Die Live-Läufe haben dabei drei Zugriffshindernisse gefunden, für die die
  Agenten keine Regel hatten — jedes mit eigenem Test in
  `tests/test_free_archive_fetchers.py::TestLiveObservedAccessBarriers`:
  MDZ gibt ein PDF erst nach **Bestätigung des Rechtehinweises** heraus (das
  Feld steht auf „Nein" vorbelegt, ohne Umstellung antwortet der Server mit
  HTTP 200 und wieder dem Formular — der Schritt scheitert lautlos);
  Internet Archive beantwortet den Download eines CDL-Titels mit **HTTP 401**,
  erkennbar vorab am Metadatenfeld `access-restricted-item`, nicht nur am
  Borrow-Button; und HathiTrusts Sperrseite ist **kein CAPTCHA** — die
  Captcha-Erkennung des Repos schlägt an der real aufgezeichneten Seite
  (`tests/fixtures/free_archive_fetchers/hathitrust_page_blocked.html`)
  nicht an, weshalb `metadata_only` mit der Zugriffsstufe „Plattform-Sperre"
  der richtige Ausgang ist und weder `captcha` noch `no_match`.

- **Neuer Skill `latex-layout-auditor` (#392):** Read-only-Prüfung eines
  `latex-export`-Outputs auf LaTeX-spezifische Layout-Fehler, ergänzend zu
  `submission-checker` (der prüft Hochschul-Formalia, nicht LaTeX-Layout).
  Zwei deterministische Regeln decken die im Issue genannten Digest-Befunde
  zu `skills/latex-export/scripts/render_tex.py` ab: fehlendes
  `\tightlist` ohne vorangehende `\providecommand`/`\newcommand`-Definition
  (pdflatex-Build-Abbruch) und korrumpierte Zitationskommandos wie
  `\textbackslash{}cite{key}` statt `\cite{key}`. Beide Bugs sind im
  Renderpfad selbst bereits durch #386 gefixt — dieser Auditor erkennt
  dasselbe Muster zusätzlich in beliebigen, auch manuell editierten oder
  extern erzeugten `.tex`-Dateien, meldet sie aber nur (Scope-Abgrenzung
  laut Issue: kein automatisches Fixen). Referenzimplementierung
  `scripts/check_layout.py::audit_tex()` ist reine, seiteneffektfreie
  Pruef-Logik, separat pytest-getestet; der Skill selbst bleibt
  `allowed-tools: [Read]` und wendet dieselben Muster beim Lesen an, statt
  das Skript zur Laufzeit auszuführen. Vier weitere Checklisten-Dimensionen
  (Package-Konflikte, Kapitel-Nummerierungssprünge, Bildunterschriften-
  Format, Cross-Referenzierung) sind prompt-basiert und orientieren sich am
  30-Prinzipien-Katalog aus
  [andrehuang/academic-writing-agents](https://github.com/andrehuang/academic-writing-agents)
  (MIT-Lizenz, real via GitHub-API verifiziert; Wortlaut-Übernahme mit
  Quellenhinweis laut Issue erlaubt) — Auszug in
  `skills/latex-layout-auditor/references/academic-writing-agents-principles.md`.
  Skill-Zahl 36 → 37 (`plugin.json`-description, `docs/reference/skills.md`,
  `README.md`, `AGENTS.md`) — Manifest-Version bleibt bewusst bei 6.5.1
  (Präzedenzfall #447/literature-excel bzw. #472/defense-prep). Neue
  Fixtures `tests/fixtures/latex_layout_auditor/{missing_tightlist,
  valid_structure}.tex`, neuer Test `tests/test_latex_layout_auditor.py`.

- **Praxis-Leitfaden: Erste Schritte, voller Durchlauf, Modellwahl, Token-Sparen
  (#461):** Vier neue Seiten unter `docs/guide/` schließen die Lücke zwischen
  „welche Bestandteile gibt es" (Referenz) und „wie entsteht damit eine Arbeit".
  `getting-started.md` trägt selbsttragend von der Installation bis zum ersten
  verifizierten Zitat, je Schritt mit Erfolgssignal. `model-choice.md` ordnet
  sieben Aufgabentypen den Claude-Code-Modell-Aliasen zu (`haiku`, `sonnet`,
  `opus`, `opusplan`, `fable`, `sonnet[1m]`) und erklärt `/model`, die
  `model`-Einstellung in `.claude/settings.json` und das Subagent-Frontmatter
  `model:` inklusive `inherit`-Default; die Empfehlungen sind an die realen
  `model:`-Werte in `agents/*.md` gekoppelt, ein Modellwechsel im Repo macht den
  Guard rot. Die Alias-Bedeutungen geben den Wortlaut von
  [Model configuration](https://code.claude.com/docs/en/model-config) wieder —
  `fable` steht dort für die schwersten und längsten Aufgaben (lange autonome
  Läufe mit eigener Nachprüfung), nicht für kreatives Schreiben; ein Guard hält
  die Seite auf dieser Lesart fest. `token-budget.md` benennt die vier teuren
  Schritte und je Hebel
  einen realen Befehl (`--mode quick`/`--mode metadata`, `--limit`,
  `--no-expand`/`--no-browser`, `--batch`) plus die Abschnitte „eigener Kontext"
  und „Zwischenstand sichern" gegen die echte Mechanik (`hooks/pre-compact.mjs`,
  `/academic-research:history --restore`). `best-practices.md` sammelt bewährtes
  Vorgehen, typische Fehler und acht konkrete Nicht-Eignungen (u. a. keine
  Zitat-Garantie ohne Gegenprüfung, kein Plagiatsdienst-Ersatz, keine eigene
  Datenerhebung, Office-Export nur mit dem externen Plugin `document-skills`,
  Ausrichtung auf deutschsprachige Hochschulen, SciHub rechtlich umstritten und
  per Default aus). `docs/guide/walkthrough.md` ist auf 23 Arbeitsschritte in
  realer Reihenfolge umgebaut, jeder mit Beispielformulierung und
  „Ergebnis:"-Angabe; fehlende Schritte (Screening, Quellenqualität,
  Lesenotizen, Extraktionsmatrix, Lückenanalyse, Word-/Slides-Export) sind
  ergänzt. Der Suchschritt nennt den realen Ablageort der Volltexte —
  `~/.academic-research/sessions/<zeitstempel>/pdfs/` je Lauf, nicht den flachen
  Ordner `~/.academic-research/pdfs/`, den `scripts/setup.sh` nur leer anlegt —
  und die Abschlussmeldung im Wortlaut von `scripts/search.py`. Verlinkung aus
  `README.md` und `docs/README.md`; Guards in
  `tests/test_issue_461_practice_guide.py` (54 Tests) prüfen Reihenfolge der
  Einstiegsschritte, reale Commands/Flags, Trigger-Phrasen gegen
  `docs/reference/skills.md` bzw. `vault.*`-Tools gegen
  `academic_vault/server.py`, Modell-Aliase gegen die Claude-Code-Doku,
  PDF-Ablage und Erfolgssignal gegen `commands/search.md` bzw.
  `scripts/search.py`, Token-Hebel, Querverweise und den Grenzen-Abschnitt.

- **Verhaltens-Evals real ausführbar (#470):** Neuer, ausschließlich per
  `workflow_dispatch` auslösbarer Workflow `.github/workflows/eval-behavior.yml`
  führt `uv run pytest tests/evals/` mit `ANTHROPIC_API_KEY` aus den
  Repo-Secrets aus (begrenzt auf dieses Unterverzeichnis, nicht `tests/`) und
  bricht bei fehlendem Secret mit `::error::` hart ab, statt täuschend grün
  als „0 failed, N skipped" durchzulaufen. `timeout-minutes: 30` deckelt das
  Budget; Ergebnis geht als Pass/Fail-Tabelle nach `$GITHUB_STEP_SUMMARY`
  (`scripts/dev/summarize_eval_junit.py`, parst die `--junitxml`-Ausgabe) und
  als Artefakt (`eval-results.xml`/`eval-output.log`). `docs/evals/STRATEGY.md`
  (Abschnitt „API-Budget") verweist jetzt auf diesen realen Pfad statt nur
  hypothetisch ~400 Aufrufe zu beziffern. `ci.yml` bleibt unverändert — der
  reguläre `pytest tests/`-Lauf skippt die API-gateten Evals weiterhin ohne
  Key, unverändert bei 182 Skips. Nebenbei bereinigt: `docs/SKIP_REASONS.md`
  enthielt vier `todo:*`-Zeilen zu bereits erledigten Voraussetzungen
  (`ocr.py` existiert, Page-Offset-Fixtures liegen vor, Publisher-Evals-JSON
  existiert, Token-Baseline ist erfasst — alle vier Tests laufen bereits mit
  0 Skips) sowie eine veraltete Beschreibung des `anthropic`-Package-Imports
  als „optional", obwohl `anthropic>=0.40` seit #390 Pflicht-Dependency ist;
  beide Klassen sind jetzt korrigiert bzw. entfernt.

- **Endphase: ehrliche Abgabeprüfung, Ausgabeformen-Erhebung, Verteidigungsvorbereitung (#472):**
  `submission-checker` behauptete bisher Prüfungen (Typografie, Zeilenabstand,
  Ränder, exakte Seitenzahl), die es am reinen Markdown-Material
  (`kapitel/*.md`, `writing_state.md`) gar nicht belegen kann — Layout entsteht
  erst beim Export (`word-export`/`latex-export`). Die Checkliste ist jetzt in
  "am Material prüfbar" (Pflichtabschnitte, Quellenzahl, Text-Ebene von
  Abbildungen/Tabellen, Text-Präsenz der eidesstattlichen Erklärung) vs. "nicht
  prüfbar ohne Export/explizite User-Angabe" (Seitenzahl, Formatierung)
  getrennt; das Output-Template hat eine neue Pflicht-Sektion "Nicht geprüft".
  Nennt der User Formatwerte explizit im Gespräch, bleibt die Prüfung dagegen
  möglich (bestehender Eval `sc-01` bleibt PASS-fähig). Die Few-Shot-Beispiele
  ziehen mit: das bisherige *Gut*-Beispiel führte mit "Zeilenabstand 1.0 statt
  geforderten 1.5 (Seiten 12-18)" genau den erfundenen Layout-Befund vor, den
  die neue Regel verbietet — es steht jetzt als *Schlecht*-Fall da, daneben ein
  *Gut*-Beispiel für die ehrliche "NICHT GEPRÜFT"-Antwort und eines für den
  echten Score auf Basis vom User genannter Werte. `academic-context`
  erhebt in der Erstaktivierung neu das Feld "Gewünschte Ausgabeformen"
  (`output_targets`), wodurch die drei bereits vorhandenen, aber mangels
  Erhebung nie erreichbaren Default-Off-Skills `grant-proposal`/
  `conference-poster`/`reviewer-response` überhaupt aktivierbar werden. Neuer
  Skill `defense-prep`: leitet aus `kapitel/*.md` + dem Methodik-Feld in
  `academic_context.md` eine Vortragsgliederung mit Zeitbudget und
  Kernaussage je Kapitel ab, dazu einen Fragenkatalog, der an die tatsächlich
  gewählte Methodik und die im Fazit-Kapitel benannten Limitationen gebunden
  ist — fehlt die Limitationen-Sektion, fragt der Skill nach statt generische
  Fragen zu erfinden. Kein Foliensatz (das deckt `slide-export`) und keine
  automatische Bewertungsprognose (bewusster Scope-Out). Skill-Zahl 35 → 36
  (`plugin.json`/`marketplace.json`-description, `docs/reference/skills.md`,
  `README.md`, `AGENTS.md`) — die Manifest-*Version* bleibt bewusst bei 6.5.1
  (Präzedenzfall #447/literature-excel: Skill-Zahl-Änderungen allein lösen
  keinen Versionsbump aus, sonst bricht `tests/test_issue_370_version_sync.py`
  den Gleichlauf mit `pyproject.toml` und dem obersten versionierten
  CHANGELOG-Eintrag). Baselines für
  `submission-checker` und `academic-context` in `tests/baselines/
  {skill_sizes,tokens}.json` ehrlich um den Netto-Zuwachs angehoben (analoges
  Muster zu #395/#439) — für `submission-checker` in zwei Schritten: 8897 →
  12227 für die Ehrlichkeitsregeln, danach 12227 → 12655 für die nachgezogenen
  Few-Shot-Beispiele (+428 Zeichen), die Reduktionsmarge gegen
  `test_token_reduction` bleibt dabei unverändert bei 1448 Zeichen;
  `defense-prep` erhält einen künstlich gesetzten
  Erstwert, da es keine Vorher-Version gibt. Neue Tests:
  `tests/test_submission_checker_honesty.py`,
  `tests/test_academic_context_output_targets.py`, `tests/test_defense_prep.py`.
  Neue Eval-Cases: `evals/submission-checker/evals.json` (sc-03, "Nicht
  geprüft" ohne Export), `evals/academic-context/{evals.json,trigger_evals.json}`
  (ac-03 + ein Trigger-Case für `output_targets`), `evals/defense-prep/*` neu
  (Status `structural` in `docs/evals/STRATEGY.md`, Begründung: Kernaussage-
  und Fragenkatalog-Qualität sind Modellurteile über Fließtext, die
  strukturellen Vorgaben deckt `tests/test_defense_prep.py`).

- **Fetcher-Agents für Cambridge Core, Oxford Academic und JSTOR (#449):** Drei
  neue Verlags-Subagenten (`agents/cambridge-core.md`, `agents/oxford-academic.md`,
  `agents/jstor.md`) nach dem `springer-book`/`degruyter`-Muster: Lizenz-Prüfung
  gegen `~/.academic-research/library-profiles/active.yaml` zuerst, danach
  Discovery → OA-Badge-Erkennung → Auth-Delegation an `auth-helper` bei
  fehlendem OA-Badge → Download, identisches 5-Status-Output-Schema
  (`success`/`metadata_only`/`no_match`/`pickup_required`/`captcha`). Jeder
  Agent bekommt einen passenden `config/browser_guides/*.md`. `jstor` läuft
  bewusst konservativ (Anti-Scraping: hoch — JSTORs Nutzungsbedingungen
  untersagen automatisiertes/systematisches Herunterladen ausdrücklich,
  `about.jstor.org/terms`); bei wiederholtem CAPTCHA meldet der Agent ehrlich
  `status: captcha` statt das Tempo zu erhöhen. `agents/book-fetcher.md`
  (Schritt-4-Tabelle + Tools-Frontmatter) und `tests/helpers/book_fetcher_router.py`
  (`PUBLISHER_DOMAIN_MAP`) wurden additiv um die drei neuen Hosts
  (`cambridge.org`, `academic.oup.com`, `jstor.org`) erweitert, ohne die
  bestehende Tier-Reihenfolge umzusortieren. Reale Uni-Profile
  (`config/library-profiles/*.yaml`) bleiben unverändert — `cambridge.org`/
  `academic.oup.com` sind dort in keinem der fünf Profile hinterlegt (nur
  `jstor.org` ist bereits überall gelistet); Operatoren müssen `licensed_sites`
  bei Bedarf manuell ergänzen. Agent-Zähler 20 → 23 (`docs/reference/agents.md`,
  `AGENTS.md`, `README.md`), Book-Fetcher-Subagenten-Zähler 10 → 13
  (`plugin.json`/`marketplace.json`, gegen `agents/book-fetcher.md`-Frontmatter
  geprüft von `tests/test_issue_453_manifest_honesty.py`). **Fixrunde PR #500
  (AC1 real belegt statt nur behauptet):** Die Review bemängelte zu Recht, dass
  `pf-06`/`pf-07`/`pf-08` in `evals/publisher-fetchers/evals.json` nur eine
  triviale Existenzprüfung des `status`-Felds waren (auch von `no_match`/
  `captcha` erfüllt) und nie ausgeführt wurden. Alle drei Fälle tragen jetzt
  einen konkreten Zielwert (`equals:success`/`equals:captcha`). Dabei
  aufgedeckt: die ursprüngliche Oxford-Academic-Testfall-DOI
  (`10.1093/oso/9780190247249.001.0001`) gehört real zu „Philosophies of
  Qualitative Research" (Brinkmann 2017), einem kostenpflichtigen OSO-Buch ohne
  OA-Badge — gegengeprüft über Crossref-Content-Negotiation, also unabhängig von
  der Verlagsseite; korrigiert auf einen realen Commit-to-Open-Titel.
  **Zweite Fixrunde PR #500 (Beleg als Artefakt statt als Prosa):** Die erste
  Fixrunde hat die drei Läufe wirklich gefahren, den Nachweis aber nur als
  Fließtext in `evals.json`/`CHANGELOG.md` abgelegt — mitsamt
  JSTOR-Block-Referenz, Client-IP und Uhrzeit. Diese drei Angaben werden pro
  Request neu vergeben (zwei Abrufe im Sekundenabstand liefern zwei
  verschiedene Block-Referenzen) und sind deshalb von niemandem nachprüfbar,
  auch nicht vom Autor. Abgesichert war das ausgerechnet durch einen Test, der
  prüfte, ob das Wort „verifiziert" in der Notiz vorkommt — er blieb grün, wenn
  man die Notiz durch eine beliebige Unwahrheit ersetzte. **Präzise Zahlen sind
  kein Beleg, solange sie niemand nachfahren kann.** Der Nachweis liegt jetzt
  als maschinell prüfbares Artefakt in
  `evals/publisher-fetchers/live-verification.json`: pro Agent URL-Kette,
  HTTP-Status, Bytes, SHA-256 und die mit `pypdf` aus dem geöffneten Dokument
  gelesene Seitenzahl. Nachfahrbar mit `RUN_LIVE_PUBLISHER_FETCH=1 uv run
  pytest tests/test_issue_449_live_fetch.py` (opt-in, bewusst nicht im CI — ein
  Ausfall der Verlage darf die Pipeline nicht rot färben). Belegt sind damit:
  Cambridge Core liefert anonym ein 228-Seiten-PDF, byteweise stabil über zwei
  Abrufe; Oxford Academic ein 225-Seiten-PDF, dessen Seite 1 den verlagseigenen
  Stempel „Downloaded … **by guest**" trägt — Oxfords eigene Kennzeichnung der
  nicht angemeldeten Sitzung und damit der eigentliche Beleg für den
  Login-freien Bezug (die Prüfsumme ist hier bewusst *kein* Kriterium, weil der
  Stempel das Abrufdatum enthält und die Bytes täglich wechseln). JSTOR
  antwortet am Volltext-Endpunkt mit HTTP 403 und der PerimeterX-Challenge
  „JSTOR: Access Check"; die Seite ist als Fixture eingecheckt
  (`tests/fixtures/publisher_fetchers/jstor_access_check.html`, flüchtige
  Felder neutralisiert — auch damit keine Client-IP im Repo landet) und wird
  hermetisch gegen die Captcha-Erkennung des Repos gefahren. Damit prüft
  `tests/test_issue_449_fetcher_evidence.py` die behauptete Tatsache statt ihrer
  Formulierung: keine Assertion dort prüft mehr den Wortlaut einer Notiz, und
  einmalige Bezeichner (Block-Referenz, IP, Uhrzeit) sind als Beleg verboten.
  Status bleibt `structural` (im CI nicht hermetisch fahrbar) — der Beleg ist
  jetzt aber für jeden reproduzierbar.
- **Word-/Slide-Export (#446):** Zwei neue Skill+Command-Paare, strukturell analog zu `latex-export`/`commands/latex.md`, beide auf dem externen `document-skills`-Plugin als Renderer-Backend. `skills/word-export/` (`/academic-research:word --kapitel <n>|all --output <datei.docx> [--format docx|pdf] [--template <uni>]`) erzeugt ein `.docx` mit echten Formatvorlagen (`HeadingLevel.*` statt manuellem Fett/Größe), Titelblatt, Inhaltsverzeichnis, eidesstattlicher Erklärung und optional einer PDF-Konvertierung derselben Datei via `soffice --convert-to pdf`. `skills/slide-export/` (`/academic-research:slides --kapitel <n>|all --output <datei.pptx> [--kolloquium|--konferenz]`) erzeugt einen Foliensatz mit genau einer Kernaussage pro Kapitel. Die Bibliografie-Auswahl wird **nicht** dupliziert: `skills/word-export/scripts/collect_references.py` importiert `get_all_papers()` aus `latex-export/scripts/build_bib.py` (dieselbe Vault-Query, nur anders formatiert) — ein Objekt-Identitäts-Test sichert das gegen künftigen Nachbau ab. Die Zitierstil-Regeln werden zur Laufzeit unverändert aus `citation-extraction/references/<style>.md` geladen (Zuordnung über `Zitationsstil` in `academic_context.md`, Default `apa.md`); `collect_references.py` selbst enthält keine eigenen Stilregel-Strings. `\cite{key}`/`\citep[…]{key}`-Marker aus `kapitel/*.md` (Issue #386) werden für den docx-Pfad zu Klartext-Kurzzitaten `(Nachname Jahr)` aufgelöst, unbekannte Keys sichtbar als `(? key)` statt lautlos zu verschwinden. `skills/slide-export/scripts/build_slide_deck.py` importiert `resolve_chapters()` aus `latex-export/scripts/export_thesis.py` (gleiche `--kapitel <n>|all`-Semantik) und extrahiert je Kapitel Titel (erste H1) + ersten Kernsatz nach der Überschrift; fehlt Fließtext, bleibt die Kernaussage leer statt fabriziert. Beide Commands übernehmen das Backend-Präflight-Muster aus `commands/excel.md` (`<!-- docx-backend:start/end -->`/`<!-- pptx-backend:start/end -->`, Verfügbarkeitsprüfung vor dem ersten Skill-Aufruf, Nachinstallations-Befehle) — bei fehlendem `document-skills`-Plugin bricht der Export mit einer verständlichen Meldung ab statt mit einem Stacktrace. `submission-checker/SKILL.md` verweist neu auf `word-export` für die Formatvorlagen-Pflicht. Da `document-skills:docx`/`:pptx` im CI-Runner nicht installiert sind (gleiche Lücke wie bei `xlsx`, #445), ist die echte Dokument-/Deck-Erzeugung nicht CI-fahrbar — getestet sind Bib-Selektion, Stilregel-Ladepfad, Cite-Marker-Auflösung, Kapitel-/Kernaussage-Extraktion und die Backend-Präflight-Struktur als reine Python-/Text-Funktionen (`tests/test_word_export.py`, `tests/test_word_export_skill_md.py`, `tests/test_word_command_frontmatter.py`, `tests/test_slide_export.py`, `tests/test_slide_command_frontmatter.py`). Skill-Zahl 32 → 34, Slash-Commands 9 → 11 (README-Badges, `docs/reference/`, `plugin.json`/`marketplace.json`-Description synchron aktualisiert); `tests/baselines/skill_sizes.json`/`tokens.json` und `docs/evals/STRATEGY.md` um die zwei neuen `structural`-Komponenten ergänzt. **Fixrunde PR #488 (vier live reproduzierte Defekte am ausgelieferten Aufrufweg):** (1) `commands/word.md`/`commands/slides.md` öffneten den vorbereitenden Python-Block mit einem *quotierten* Heredoc (`python3 - <<'PY'`). Ein quotierter Delimiter schaltet jede Shell-Expansion ab — `${CLAUDE_PLUGIN_ROOT}`, `$KAPITEL` und `$VAULT_DB_PATH` blieben literal stehen, `sys.path.insert()` bekam ein nicht existierendes Verzeichnis und der erste Import starb mit einem rohen `ModuleNotFoundError`, **bevor** `document-skills:docx`/`:pptx` überhaupt erreicht wurde (AC1/AC3/AC4/AC6). Statt den Heredoc zu reparieren, bekommen beide Skripte jetzt eine echte `argparse`-CLI und werden wie `latex-export` nach #467/#485 als normale Kommandozeile aufgerufen (`collect_references.py --kapitel <n>|all --payload <datei.json>`, `build_slide_deck.py --kapitel … --payload … --rahmen …`) — damit entfällt die Heredoc-Quoting-Klasse ganz, und Fehler kommen als `FEHLER: …` auf stderr statt als Stacktrace (AC6). (2) `$VAULT_DB_PATH` war in `commands/word.md` nirgends definiert; die Entrymengen-Garantie docx↔LaTeX (AC3) wurde vom Command nie hergestellt. Der Vault-Pfad wird jetzt im Skript über `academic_vault.db.default_db_path()` aufgelöst — exakt der Auflöser, den `export_thesis.py` für die `.bib` nutzt (#190); `--vault-db` bleibt als Test-Override. (3) `resolve_cite_markers()` schlug bei Mehrfachzitaten die komplette Key-Liste als **einen** Key nach: `\cite{a,b}` wurde selbst bei zwei im Vault bekannten Papers zu `(? a,b)` statt zu zwei Kurzbelegen (AC2). Jetzt Key für Key aufgelöst und zu `(Smith 2023; Jones et al. 2022)` zusammengefasst; die Kommando-Allowlist kommt neu als `LATEX_CITATION_COMMANDS` aus `render_tex.py` (Import statt zweiter handgepflegter Liste). (4) Beim Live-Lauf zusätzlich gefunden: `slide-export` schrieb rohe LaTeX-Marker wörtlich als Folien-Kernaussage (`\cite{smith2023,jones2022}` auf einer PowerPoint-Folie), und der Punkt in einem Locator (`\citep[S. 12]{k}`) zerschnitt die Erste-Satz-Erkennung an der falschen Stelle. `strip_latex_markers()` entfernt die Marker vor der Satzzerlegung (kein Auflösen — `slide-export` führt bewusst kein Literaturverzeichnis und hat keinen Vault-Zugriff). Neuer Regressionstest `tests/test_issue_446_documented_invocation.py` führt die `bash`-Blöcke aus `commands/word.md`/`commands/slides.md` **wirklich aus** (echtes Mini-Projekt mit `kapitel/`, `academic_context.md`, befülltem Vault) und sichert zwei Invarianten ab: quotierte Heredocs dürfen repo-weit keine Shell-Variablen referenzieren, und beide Commands dürfen keine undefinierten Shell-Variablen benutzen. `tests/baselines/skill_sizes.json` steigt um den Netto-Zuwachs der beiden SKILL.md (word-export 7769 → 8012, slide-export 5590 → 5734). **Zweite Fixrunde PR #488 (gemeinsame Ursache dreier Review-Funde):** AC1/AC2/AC4 waren strukturell unbelegbar, weil **kein Repo-Code die Zieldatei je erzeugt hat** — die Pipeline endete bei einer JSON-Payload, das Rendern war Prosa-Anweisung an den Agenten. Der Nachweisversuch der ersten Fixrunde landete deshalb als Test-only-Renderer *in* `tests/test_word_export_docx_render.py`/`tests/test_slide_export_pptx_render.py` und bewies nur, dass der Test ein `.docx`/`.pptx` schreiben kann. Gegenmittel ist das Muster des funktionierenden Geschwister-Skills `latex-export`, wo `render_tex.py` die `.tex` wirklich schreibt: neu `skills/word-export/scripts/render_docx.py` und `skills/slide-export/scripts/render_pptx.py` erzeugen `.docx`/`.pptx` deterministisch als Repo-Code (`python-docx`/`python-pptx` wandern dafür von `[project.optional-dependencies].dev` in die Runtime-Deps von `pyproject.toml` **und** `scripts/requirements.txt`). Beide Commands bekommen einen ausführbaren `### Schritt 4`-Block, der den Renderer aufruft; `document-skills:docx`/`:pptx` bleiben deklarierte Plugin-Abhängigkeit und übernehmen nur noch optionale Layout-Verfeinerung **auf der erzeugten Datei**. Die Zitierstil-Formatierung bleibt bewusst draußen: `render_docx.py` übernimmt `payload["bibliography"]` (vom Agenten aus `style_rules` formatiert) zeichengenau und in unveränderter Reihenfolge und bricht mit `FEHLER:` ab, wenn der Vault Papers liefert, die Einträge aber fehlen — ein Verzeichnis in einem nicht belegten Format wäre Fabrikation. Titelblatt-Angaben kommen aus dem neuen Payload-Feld `context` (`collect_references.parse_context_fields()`, nur wirklich ausgefüllte `academic_context.md`-Felder; fehlende erscheinen als sichtbares `[bitte ergänzen]`). Neuer Nachweis `tests/test_issue_446_render_pipeline.py` fährt ausschließlich die dokumentierten bash-Blöcke (Schritt 3 + Schritt 4) und öffnet die entstandene Datei wieder: OPC-Zip-Integrität, echte `Heading 1`/`Heading 2`/`Heading 6`-Formatvorlagen, Word-native TOC-Feldfunktion, aufgelöste Kurzbelege im Fließtext, APA- **und** Harvard-Literatureinträge zeichengenau unter dem Verzeichnis-Heading, eine Folie je Kapitel im `.pptx` — plus echte LibreOffice-Konvertierung, wo `soffice` verfügbar ist. Die beiden Vorrunden-Suiten rufen jetzt denselben Produktionsrenderer auf statt eigenen Rendering-Codes. `tests/baselines/skill_sizes.json`/`tokens.json` steigen um den Netto-Zuwachs der beiden SKILL.md (word-export 8012 → 9233 bzw. 1568 → 1959, slide-export 5734 → 6665 bzw. 1023 → 1317) — dieselbe Baseline, die dieser PR für die neuen Skills selbst eingeführt hat, kein Aufweichen eines historischen Guards.
- **Neuer Skill `parallel-screening` + Agent `screening-judge` (#460):** Die
  gleichförmigen Schritte der Recherche — Titel-/Abstract-Screening vieler
  Treffer und Verzerrungsbewertung vieler Studien — laufen jetzt wellenweise
  über Subagents statt seriell im Dialog. Der neue `screening-judge` urteilt
  über genau einen Treffer und gibt ein festes Ein-Fall-JSON zurück
  (`include`/`exclude`/`unclear` mit Begründung, Kriterium, Beleglage); die
  Verzerrungsbewertung nutzt den bestehenden `risk-of-bias`-Agent unverändert
  weiter. Die deterministische Buchführung liegt in
  `skills/parallel-screening/scripts/screening_ledger.py`: Wellen-Planung
  gegen ein konfigurierbares Limit (Argument > `ACADEMIC_RESEARCH_MAX_PARALLEL`
  > `config/parallel_agents.json` > Default 4, harter Deckel 8), ein
  append-only Ledger `$SESSION_DIR/screening_ledger.jsonl` als Protokoll
  „welche Quelle von welchem Agent" und Resume-Basis, sowie PRISMA-Zähler
  direkt aus dem Ledger. Geschrieben wird ausschließlich in die vorhandenen
  Zielstrukturen: Ausschlüsse nach `excluded_sources` (mit Stufen-Präfix
  `screening: …`), Einschlüsse bleiben in `papers`, RoB-Bewertungen im
  bestehenden Domain-Format. Uneindeutige Fälle erreichen den Vault nie und
  werden gesammelt zur menschlichen Entscheidung vorgelegt. Resume prüft bei
  RoB zusätzlich `vault.list_risk_of_bias()`, weil `add_risk_of_bias` ein
  reines INSERT ohne Idempotenz ist.

- **Neuer Skill `extraction-matrix` für die Synthese-Phase (#463):** Zwischen
  „Quellen gesammelt" und „Kapitel geschrieben" fehlte bisher der Schritt, in
  dem Befunde über mehrere Studien hinweg vergleichbar gemacht werden. Der
  neue Skill leitet die Spalten der Extraktionsmatrix aus den
  Schlüsselkonzepten in `academic_context.md` ab, ergänzt um die
  Standardmerkmale Methode, Stichprobe, Erhebungszeitraum und Kernbefund;
  die Zeilen kommen aus dem Paper-Inventar in `literature_state.md`. Jede
  Zelle wird ausschließlich aus vorhandenen `vault.find_notes()`/
  `vault.find_quotes()`-Belegen befüllt, fehlende Angaben werden explizit als
  `— fehlend —` markiert statt ergänzt zu werden; Quellen ganz ohne Notiz
  oder Zitat bleiben als eigene Zeile mit „Grundlage fehlt"-Hinweis sichtbar
  statt zu verschwinden. Ausgabe als Markdown-Tabelle zur Übernahme in
  `kapitel/literatur.md` sowie als Arbeitsblatt über den externen
  `document-skills:xlsx`-Skill (Verfügbarkeitsprüfung + Fallback-Hinweis,
  gleiches Muster wie `commands/excel.md`). Statistische Auswertung oder
  Interpretation der Matrix bleibt explizit out of scope (Meta-Analyse-Pfad).
  Skill-Zähler 30 → 31 in `docs/reference/skills.md`, `README.md` und
  `.claude-plugin/plugin.json`.

- **`sparring-partner`-Agent als wissenschaftlicher Denk- und Impulsgeber (#454):**
  Neuer Agent `agents/sparring-partner.md` (`model: opus`), der bei konzeptioneller
  Arbeit widerspricht statt auszuführen: benennt Argumentationslücken, blinde
  Flecken, Gegenpositionen und Anschlussfragen zu Themenzuschnitt, Forschungsfrage
  und Argumentationslinie. Liest `./academic_context.md` und fragt `vault.search`/
  `vault.get_paper` ab, um am konkreten Material zu argumentieren (Read-only,
  kein `Write`); erzwingt ein festes Antwortformat
  (`SCHWÄCHE:`/`ALTERNATIVE:`/`GEGENPOSITION:`/`ANSCHLUSSFRAGEN:`) statt
  Fließtext und lehnt Kapitel-Prosa-Anfragen mit Verweis ab, statt selbst Text zu
  produzieren. Abgrenzungsabschnitt benennt `advisor`, `research-question-refiner`,
  `methodology-advisor` und `quality-reviewer` namentlich; die drei erstgenannten
  Skills verweisen im Gegenzug auf den neuen Agenten zurück. Neu:
  `evals/sparring-partner/evals.json` (inkl. bewusst tautologischer
  Forschungsfrage), `tests/evals/test_sparring_partner_evals.py` (API-gated) und
  `tests/test_sparring_partner_agent.py` (Frontmatter-/Struktur-Guards, CI-fest).
  Fix-Runde (AC-Verifier zu PR #494): `evals/sparring-partner/recordings.json`
  hält fünf Transkripte fest, die während der Fix-Runde entstanden sind,
  sha256-an den Agent-Text gepinnt; `evals/sparring-partner/runner.py` +
  `tests/evals/test_sparring_partner_recording.py` prüfen sie offline und
  CI-fest gegen `evals.json::expected`, damit Drift am Agent-Text auffällt
  statt still zu bestehen. Zweite Fix-Runde (Coordinator-Gate-Befund):
  Transkript und Erwartung stammen aus derselben Sitzung — kein unabhängiger
  Verhaltensbeleg, nur der Hash-Pin kann real fehlschlagen; `docs/evals/STRATEGY.md`
  führt die Komponente deshalb korrekt als `structural`, nicht `metric`. Der
  inhaltliche AC-Beleg (AC2/AC3/AC5) bleibt `tests/evals/test_sparring_partner_evals.py`
  (API-gated, jetzt mit explizit übergebenem `model="claude-opus-4-6"` statt dem
  `call_claude()`-Default). `recordings.json::provenance` korrigiert außerdem die
  vorherige Aussage "unverändert übernommen" — die Texte sind ae/oe/ue-transliteriert
  bis auf die durch die Regex erzwungene Ausnahme `SCHWÄCHE`.
  Dritte Fix-Runde (AC-Verifier, erneut „verfehlt" für AC2–AC5): Die Ursache lag
  tiefer als der fehlende API-Key — **die Kriterien selbst hatten keine
  Unterscheidungskraft**. Eine rein bestätigende Antwort („SCHWÄCHE: Keine
  nennenswerte / ALTERNATIVE: Keine nötig") erfüllte `sp-01`/`sp-02`/`sp-05`,
  Kapitel-Prosa erfüllte `sp-04`, sobald irgendwo `chapter-writer` vorkam, und eine
  zustimmende Antwort erfüllte `sp-03`, solange sie das Stichwort „Meier" aus der
  Eingabe wiederholte. Das traf **beide** Ausführungspfade: auch mit gesetztem
  `ANTHROPIC_API_KEY` hätte der Live-Eval eine sykophantische Antwort durchgewinkt.
  Neu deshalb `evals/sparring-partner/counter_examples.json` (neun format-konforme
  Negativkontrollen) und `tests/evals/test_sparring_partner_criteria.py`, das
  fordert, dass jede davon abgelehnt und jedes Transkript weiter angenommen wird;
  das `expected`-Schema kennt dafür jetzt UND-Listen (`value`) und NOR-Listen
  (`reject`), abwärtskompatibel und in `evals/SCHEMA.md` dokumentiert.
  `evals/sparring-partner/record.py` ersetzt außerdem den selbstverfassten
  Recording-Text durch **echte, blinde Modellaufrufe** (Claude-Code-CLI headless,
  `claude --print --model opus`, OAuth statt API-Key): Kriterien vorher committed,
  Aufnahme-Subprozess sieht sie nicht, Prompt-Aufbau identisch zum API-gated Pfad
  (komplette Agent-Datei inkl. Frontmatter). Dass der Abgleich scheitern kann, ist
  belegt — der erste Lauf gegen die vorab festgelegten Kriterien ergab 1/5.

- **SciHub-Tier still ueber das Opt-in-Flag aktiviert, Provenance bleibt aus dem Schreibkontext (#459):**
  `agents/scihub-fetcher.md` hatte bereits Opt-in-Gate und Provenance-Tagging,
  war aber in keinem Orchestrator-Pfad erreichbar — `agents/book-fetcher.md`
  kannte kein `Agent(scihub-fetcher)` (Luecke bestand bereits seit F18/#161).
  Neuer Schritt 6 in `book-fetcher.md` dispatcht `scihub-fetcher` als
  Last-Resort nach `generic-fetcher`, ausschließlich gesteuert durch
  `scihub_optin: true` im aktiven Uni-Profil — kein Laufzeit-Dialog, keine
  Rueckfrage; fehlt das Flag, wird der Agent nie aufgerufen. Der bislang bei
  jedem erfolgreichen Fund ausgegebene Warnhinweis in `scihub-fetcher.md`
  entfaellt; die rechtliche Aufklaerung bleibt einmalig beim Opt-in
  (`commands/setup.md` Schritt 8) bestehen, erfolgreiche Funde setzen nur noch
  das Vault-Tag `provenance:scihub`. `commands/fetch.md` schreibt das
  `Quelle`-Feld nicht mehr in den `literature_state.md`-Block, den
  `chapter-writer` und `citation-extraction` als Kontext lesen duerfen — beide
  Skills erhalten zusaetzlich eine explizite Provenance-Blindheits-Regel
  ("Wichtige Regeln"), damit der Beschaffungskanal Zitierweise und
  Textbehandlung nie beeinflusst. Die Herkunft bleibt vollstaendig im Vault
  nachvollziehbar (`vault.get_paper()`, `vault.list_papers_by_provenance()`,
  Anschluss an #195). Neu: `tests/test_issue_459_scihub_wiring.py`.

- **`/history` verdrahtet den Sitzungs-Index tatsächlich (#466):** Neues Modul
  `scripts/session_index.py` kapselt Lesen/Schreiben/Filtern/Wiederherstellen
  von `~/.academic-research/session_index.json` — bisher schrieb keine Stelle
  im Plugin je in diese Datei, weshalb `/history` trotz durchgeführter Suchen
  immer leer blieb. Der Index liegt bewusst außerhalb von
  `~/.academic-research/sessions/`: `score.md`/`excel.md` wählen die
  "neueste" Session per `ls -t ~/.academic-research/sessions/ | head -1`
  (sortiert nach mtime, ohne zwischen Dateien und Verzeichnissen zu
  unterscheiden); eine Geschwisterdatei dort würde als zuletzt beschriebene
  Datei jeden echten Sitzungsordner dauerhaft überholen und den
  Default-Fluss `/search` -> `/score`/`/excel` brechen (PR #486 Review,
  live reproduziert, vor Merge behoben). `commands/search.md` schreibt am
  Ende jedes Laufs (neuer Schritt 9) per `update_session_index()`/
  `build_session_entry()` einen Eintrag mit Query, Modus, Trefferzahl und
  automatisch gezählter Volltext-Anzahl (`$SESSION_DIR/pdfs/*.pdf`) fort —
  ein Upsert nach `session_path`, atomarer Write (tmp-Datei + rename).
  `commands/history.md` liest/durchsucht diesen Index jetzt über
  `load_session_index()` + `search_session_index()` statt per rohem `cat`;
  ein zwischenzeitlich gelöschter oder verschobener Sitzungsordner wird über
  `annotate_missing_sessions()` als `missing` markiert und mit
  Klartext-Hinweis ausgegeben statt einen Fehler zu werfen. Neuer Flag
  `--restore-session <id>` (bewusst anders benannt als `--restore <ts>`, das
  bereits für Snapshot-Tarballs vergeben ist) macht eine frühere Session über
  `restore_session()` wieder zum Arbeitsstand — analog zur bestehenden
  `ls -t`-Konvention aus `score.md`/`excel.md` wird dafür nur die mtime des
  Sitzungsordners aktualisiert, die Sitzungsablage selbst bleibt unangetastet
  (out of scope). Sessions aus der Zeit vor diesem Fix haben keinen
  Index-Eintrag und bleiben in `/history` unsichtbar — kein Backfill im Scope.
  Neu: `tests/test_session_index.py`.

- **`generic-fetcher` wird universeller Plattform-Navigator (#448):** `agents/generic-fetcher.md` löst die bisherige Einzelseiten-Heuristik durch ein Zustandsmodell mit genau fünf Seitenzuständen ab (`open_access`, `licensed`, `paywalled`, `login_required`, `unavailable`), je Zustand genau eine erlaubte Folgeaktion. Neu sind (a) ein **hartes Schritt-Budget** im Frontmatter (`maxSteps: 12`; jede browser-use-Aktion zählt einen Schritt, bei Erschöpfung Abbruch mit `reason: step_budget_exhausted` — der Abbruch selbst erzeugt bewusst keinen weiteren `tries`-Eintrag, weil keine Aktion mehr stattfand), (b) eine **Viewer-/Embed-Heuristik** für JavaScript-eingebettete PDFs (`Content-Type: application/pdf` nach Weiterleitung, pdf.js-`viewer.html?file=` inklusive URL-Dekodierung, `<embed type="application/pdf">`, `<object type="application/pdf">`, `#viewerContainer` mit `data-pdf-url`), (c) die **profilgesteuerte Lizenzroute**: liegt der Host in `licensed_sites`, wird `proxy_pattern` (bzw. ersatzweise `auth_url`) genutzt und der neue Innen-Status `auth_required` gemeldet, statt nach anonymen Kopien zu suchen, (d) das optionale Input-Feld `session_context` (opaker Bezeichner aus `auth-helper`), mit dem eine bestehende Browser-Session weiterverwendet wird statt eines zweiten Login-Versuchs, und (e) ein **strukturiertes `tries[]`-Protokoll**: statt Freitext-Strings jetzt ein Objekt je Aktion (`step`, `action`, `url`, `observation`, `decision`), das den gegangenen Weg maschinell nachvollziehbar macht. Das Verbots-Kapitel benennt die Scope-Grenzen des Issues ausdrücklich (kein Proxy-Hopping ohne Profil-Eintrag, keine Cookie-/Header-Manipulation, kein SciHub-Umweg — die SciHub-Logik bleibt allein beim `scihub-fetcher` —, keine direkten HTTP-Calls, keine neuen Uni-Profile, keine Credential-Verarbeitung). `agents/book-fetcher.md` reicht in Schritt 5 `session_context` durch und löst `auth_required` nach dem Muster von Schritt 4 auf: `auth-helper` → **genau ein** Retry; nach außen bleibt das Vier-Status-Enum aus `commands/fetch.md` unverändert (`auth_required` leckt nie in den Master-Output). Testbar wird das nach dem etablierten Repo-Muster von `tests/helpers/book_fetcher_router.py` über den neuen Python-Spiegel `tests/helpers/generic_fetcher_nav.py`, der gegen gespeicherte DOM-Fixtures fährt und sein Schritt-Budget aus dem Agent-Frontmatter liest; gegen Spiegel-Drift sichert `TestPromptMirrorCoupling` in beide Richtungen ab (jedes Viewer-Muster, jeder Zustand und jeder `decision`-Wert muss wörtlich im Prompt stehen — und die Zustandstabelle des Prompts darf keinen Zustand jenseits des Spiegels nennen). Vor jedem `success` steht eine **Download-Verifikation**: die Datei unter dem vom Master vorgegebenen `output_path` muss existieren, größer als null Bytes sein und mit `%PDF-` beginnen — sonst wird sie gelöscht und der Agent meldet `pickup_required` mit `decision: download_failed`. Ein Klick, der eine HTML-Fehlerseite oder eine leere Datei speichert, gilt damit als Fehlschlag statt als Volltext; `file_path` ist immer der `output_path` und nie ein selbst gewählter Ort. Die drei Plattform-Cases (Zenodo, MDPI, OpenEdition Books — je per Gegenprobe gegen `agents/` als „ohne dedizierten Agent" belegt) laufen im Test **end-to-end**: `tests/helpers/local_origin.py` serviert Plattform-DOM und PDF-Route auf 127.0.0.1, der Spiegel holt die Datei per HTTP, schreibt sie und verifiziert sie von der Platte, der Test vergleicht die geschriebenen Bytes mit den ausgelieferten. **Ehrlich benannte Grenze:** Die DOM stammt aus Fixtures und das öffentliche Netz der drei Plattformen bleibt ungetestet — der Status in `docs/evals/STRATEGY.md` bleibt deshalb `structural`, ein realer Netz-Lauf bleibt Operator-Sache wie bei `oa-fetchers`/`publisher-fetchers`. Neu: `tests/helpers/generic_fetcher_nav.py`, `tests/helpers/local_origin.py`, sieben DOM-Fixtures unter `tests/fixtures/dom_heuristics/`, zwei Mock-Fixtures unter `tests/fixtures/book_fetcher_mocks/`.

- **Anker-Paper-Survey-Modus als neuer Skill (#394):** Neuer, eigenständiger Skill `skills/anchor-paper-survey/` (30. Skill) ergänzt die themenbasierte Recherche um einen Einstiegspunkt "ich kenne bereits ein Schlüsselpaper": statt eines Themas gibt der User eine arXiv-URL/-ID oder einen lokalen PDF-Pfad an. `scripts/anchor_paper.py` löst arXiv-Eingaben über die arXiv-API auf bzw. extrahiert bei PDFs Titel/Autoren heuristisch (`scripts/pdf.py::extract_text_from_pdf` + `detect_needs_ocr` als Vorab-Guard), legt genau ein Anker-Paper via `vault.add_paper(provenance="anchor-paper")` an und stößt darauf eine Folge-Suche über die bestehenden Fetcher (`scripts/search.py::run_search`) an — Treffer werden nur angezeigt, nicht automatisch importiert (kein neuer externer Dienst, keine Zitations-Graph-DB). Ungültige Eingaben (weder arXiv-URL/-ID noch existierender Pfad) brechen mit `ValueError` ab, ohne den Vault zu verändern. Musterhinweis: Konzept-Idee lose angelehnt an `JeanDiable/academic-research-plugin` (MIT), analog zum Geschwister-Feature `github-repo-research` (#401). Neu: `tests/test_anchor_paper_survey.py`, `evals/anchor-paper-survey/`.
- **Zotero-Annotation-Import (#395):** `zotero_pull.py` importiert jetzt Highlights (Zotero-Item-Typ `annotation`), die am ersten erkannten PDF-Attachment eines Items hängen (`zot.children(att_key)`), als `vault.add_quote(..., extraction_method="manual")`. Der Zitattext stammt **ausschließlich** aus `annotationText`; `annotationComment` wird **nie** zu `quotes.verbatim` — der Kommentar ist eigener Text der forschenden Person, kein Beleg aus der Quelle. `hooks/verbatim-guard.mjs` gibt ein Kapitel-Zitat allein deshalb frei, weil `search_quote_text()` es in `quotes.verbatim` findet (LIKE-Suche ohne weiteren Diskriminator, `extraction_method` wird nicht gelesen); ein Fallback hätte die eigene Notiz damit zum vermeintlich belegten Zitat gemacht und genau die Fehlzuschreibung durchgewinkt, die der Guard verhindern soll. Zotero trennt beides selbst strikt (Note-Templates rendern `{{:highlight}}` in Anführungszeichen bzw. `<blockquote>`, `{{:comment}}` außerhalb des Zitats). Nur-Kommentar-Annotationen (Notiz-, Bild-, Ink-Typ) werden übersprungen, aber in `ImportResult.comments_skipped` gezählt und von der CLI ausgewiesen, statt still zu verschwinden. Die Seitenzahl kommt aus `annotationPageLabel` — geparst wird ausschließlich exakt-numerisch (`_parse_page_label`); römische Ziffern, Bereiche oder leere Labels ergeben bewusst `printed_page = NULL` statt eines Rateversuchs. **Idempotent auch ohne DOI/ISBN:** vor dem Einfügen liest `_existing_quote_keys()` die vorhandenen Quotes des Papers und vergleicht auf `(verbatim, printed_page)`. Nötig, weil `add_quote()` selbst nicht dedupliziert (frische `uuid4()` je Aufruf) und Items ohne Identifikator vom Paper-Dedup nicht erfasst werden — sie durchlaufen bei jedem Lauf den vollen Importpfad, während `paper_id` über den stabilen Zotero-Key konstant bleibt; ohne den Filter wüchse pro Lauf eine weitere Kopie jeder Markierung an dasselbe Paper. Derselbe Wortlaut auf verschiedenen Seiten bleibt bewusst als zwei getrennte Quotes erhalten. Ein Fehler bei einer einzelnen Annotation bricht den Item-Import nicht ab, sondern landet in `result.errors`; neu `ImportResult.quotes_imported`. Die Detaildoku (Textquelle, Seitenlabel-Tabelle, Idempotenz, Grenzen sowie `54yyyu/zotero-mcp` — MIT, ~4,45k Stars, per `gh api` verifiziert, als optionale und **nicht** in `.mcp.json` eingebundene Companion-Integration) liegt nach Progressive-Disclosure-Muster in `skills/zotero-import/references/annotations.md`; `SKILL.md` selbst nennt `54yyyu/zotero-mcp` samt MIT-Lizenzstatus zusätzlich in einer eigenen Kurzzeile (nicht nur per Link auf die Referenzdatei) und wächst dadurch insgesamt um 43 statt 1696 Zeichen. Ein Teil des Budgets kam aus Kürzungen redundanter Bestandsformulierungen; zusätzlich hebt `tests/baselines/skill_sizes.json` die zotero-import-Baseline um den Netto-Zuwachs an (4524 → 4565, Marge 1438 → 1436 Zeichen) — etabliertes, mehrfach genutztes Repo-Muster für legitimes Skill-Wachstum (vgl. 89ca331, d12a976), keine stillschweigende Aufweichung des Guards. `tokens.json` bleibt dagegen unverändert bei 781 (Ist 782, Limit 937). `test_token_reduction`/`test_token_drift_vs_baseline` bleiben damit mit realem, wenn auch knappem Puffer grün. `_parse_page_label()` prüft `str.isdecimal()` statt `str.isdigit()` (Unicode-Ziffern wie Hochstellungen liefern damit korrekt `printed_page = NULL` statt eines `ValueError`, der die ganze Annotation verworfen hätte). Neu: `tests/test_zotero_import.py::TestAnnotationDocsProgressiveDisclosure::test_skill_md_mentions_companion_with_correct_license`, ein Regressionstest für den Unicode-Seitenlabel-Fall sowie `TestAnnotationCommentIsNotVerbatim` (5 Fälle) — inklusive der Gegenprobe über `search_quote_text()`, also genau den Lookup, mit dem der `verbatim-guard` ein Kapitel-Zitat freigibt. Bekannte Grenze (unverändert vom bestehenden Attachment-Design): nur das erste PDF-Attachment pro Item wird betrachtet, Annotationen an weiteren Attachments bleiben unerfasst; bei Dedup-Kurzschluss (Paper per DOI/ISBN bereits im Vault) werden auch neue Annotationen bei Re-Imports nicht nachgezogen.
- **Claim-Drift-Warnung als additiver PreToolUse-Hook (#397):** Neuer Hook `hooks/claim-drift-guard.mjs`, in `hooks/hooks.json` **zusätzlich** zu `verbatim-guard.mjs` an `PreToolUse(Write|Edit|MultiEdit)` gehängt — die bestehende Kernlogik (Quote-/Figure-Block) bleibt unangetastet. Der `verbatim-guard` prüft, ob ein Zitat überhaupt im Vault steht; er sieht aber nicht, wenn eine spätere Überarbeitung die **Aussage um ein bereits belegtes Zitat** verändert und die alte Quellenangabe stehen lässt (aus „moderater Effekt" wird „starker Effekt", Zitat und Beleg bleiben). Verglichen werden dabei **ganze Dateistände**, nicht die Tool-Strings: Ein realistischer `Edit` trägt in `old_string`/`new_string` nur die geänderte Stelle, während Zitat und Quellenangabe ausschließlich in der Datei stehen — ein reiner String-Vergleich sähe im Fenster nie ein Zitat und bliebe stumm. Der Hook liest deshalb den Stand von Platte und rekonstruiert den neuen Stand daraus (`MultiEdit` kumulativ, ein Vergleichspaar je Teil-Edit; `Write` gegen den Dateizustand; ohne lesbaren Vorgängerstand Rückfall auf den reinen String-Vergleich). Er grenzt die Änderung über gemeinsamen Präfix/Suffix ein und warnt nur, wenn im Fenster um diese Region (Default 300 Zeichen, `CLAIM_DRIFT_WINDOW`) ein in Alt **und** Neu wörtlich identischer Zitat-Span liegt, dessen Beleg-Marker (`(Autor Jahr, S. x)`, `\cite{…}`, `[^fussnote]`, `[@citekey]`) im Fenster **um dieses Zitat** ebenfalls unverändert sind und der im Vault belegt ist. Die Beleg-Prüfung hängt bewusst am Zitat und nicht an der Änderungsregion, weil bei einem `MultiEdit` „Aussage ändern" und „Quelle nachziehen" in zwei getrennten Teil-Edits stecken; maßgeblich ist der Stand nach dem kompletten Tool-Aufruf. Der Hook **blockiert nie** (immer Exit 0, Warnung als `systemMessage` + `hookSpecificOutput.additionalContext`, bewusst ohne `permissionDecision` — er informiert, er entscheidet nicht über die Berechtigung). Gegen False Positives: Normalisierung vor dem Vergleich (reine Markdown-/Whitespace-Änderungen zählen nicht), Anker nur an unveränderten Zitaten (ein ausgetauschtes Zitat ist Sache des `verbatim-guard`), Schweigen bei mitgeänderter Quellenangabe. Der Vault-Lookup ist **tri-state** (`found`/`not-found`/`unavailable`) — anders als `lookupInVault()` im `verbatim-guard`, wo eine fehlende DB fail-open zu „gefunden" wird: für einen Warn-Check hieße das, jede Änderung ohne Datenbasis zu bemängeln, deshalb schweigt der Hook bei nicht erreichbarem Vault. Alle Kandidaten laufen in **einem** Python-Subprozess (Budget `CLAIM_DRIFT_MAX_LOOKUPS`, Default 10, Interpreter-Kaskade wie in `mid-session-reinforcement.mjs`, #382), damit das 15-s-Hook-Timeout hält. Die Warnung zitiert `context_before`/`context_after` des Vault-Zitats mit, damit direkt prüfbar ist, ob der Beleg die neue Aussage noch trägt. Konzept-Anleihe: `academic-research-skills` von Imbad0202 (CC-BY-NC-4.0, laut Digest fälschlich als MIT beworben) — übernommen wurde ausschließlich die **Idee**, kein Code von dort gelesen oder kopiert. Neu: `tests/test_issue_397_claim_drift.py` (27 Fälle, Node-Subprocess-Harness — darunter der minimale Edit gegen eine echte Datei auf Platte, sein MultiEdit-Pendant und die Gegenproben gegen False Positives) und ein eigener Abschnitt in `docs/reference/hooks.md`.
- **Optionales `stance`-Feld an Zitaten (#400):** Die `quotes`-Tabelle bekommt die Spalte `stance TEXT CHECK(stance IN ('supports','contrasts','mentions') OR stance IS NULL)`; `vault.add_quote(..., stance=None)` reicht den Wert durch, `vault.get_quote()`/`vault.find_quotes()` liefern ihn per `SELECT *` automatisch mit. Validiert wird in Python (`db.VALID_STANCES`, neue `ValueError`-Meldung mit Wertliste), damit jeder Aufrufweg dieselbe lesbare Fehlermeldung bekommt statt eines rohen `sqlite3.IntegrityError`; der CHECK-Constraint bleibt die zweite Verteidigungslinie für Direkt-Inserts. Bestands-DBs zieht der neue idempotente Helfer `migrate.add_stance_column()` nach — er hängt (anders als frühere Helfer) an einer `quotes`-Spalte, weshalb `db._LEGACY_MIGRATION_COLUMNS` jetzt eine Tabelle→Spalten-Map ist und die Verifikation vor dem `user_version`-Stempel beide Tabellen prüft (`CURRENT_SCHEMA_VERSION` 1 → 2, Muster aus #368/PR #427). **Ausdrücklich nicht enthalten:** die Klassifikation selbst. Das Feld bleibt `null`, solange es nicht manuell gesetzt wird; eine lokale NLI-Klassifikation (Konzept-Anleihe scite Smart Citations / SemanticCite — nur als Idee, keine kostenpflichtige API-Anbindung) ist ein separates Folge-Issue. Kein neues MCP-Tool (weiterhin 34).
- **Seitenbewusstes generisches Chunking-Modul (#374):** Neues Modul `academic_vault/chunking.py`, unabhängig von `scripts/chunk_pdf.py` (bleibt unverändert). `chunk_pages()` nimmt eine Liste seitenweiser Texte (`[(page_number, text), ...]`) entgegen, erkennt Section-Überschriften heuristisch per Regex (Fallback-Label `"Unbenannter Abschnitt"`, falls keine erkannt wird), und baut Sliding-Window-Chunks mit `OVERLAP_RATIO=0.125` (10–15%-Korridor); `page_start`/`page_end` werden aus den Wort→Seiten-Offsets abgeleitet. Die Chunk-Größe wird in **Modell-Tokens** bemessen, nicht in Wörtern: `intfloat/multilingual-e5-small` hat ein hartes Kontextfenster von `max_seq_length=512`, und `SentenceTransformer.encode` kürzt darüber hinausgehende Eingaben stillschweigend (gemessen: 512 Wörter ergeben 858 e5-Tokens bei englischer, 1204 bei deutscher Prosa — der Chunk-Schwanz fiele unbemerkt aus dem Vektor). `TARGET_TOKENS = MODEL_MAX_TOKENS - CONTEXT_TOKEN_RESERVE` (512 − 64 = 448) ist das Budget für den reinen Chunk-Text, sodass der vollständige Embedding-Input inklusive Kontextsatz ins Fenster passt. Gezählt wird über einen austauschbaren `token_counter`: `resolve_token_counter()` nimmt bevorzugt den echten Tokenizer des konfigurierten Embedding-Modells und fällt nur bei nicht ladbarem Tokenizer (offline CI) auf die dokumentierte Zeichen-Näherung `approximate_token_count()` zurück — mit Warnung im Log. Überschreitet ein Chunk das Fenster dennoch (einzelnes überlanges Wort), wird die sonst stille Kürzung geloggt. `chunk_pdf()` liest ein PDF seitenweise via pypdf ein (eigener, minimaler Pfad — dupliziert nicht `academic_vault/fulltext.py` aus #373, das Seiten bewusst zu einem Fließtext zusammenfasst und die Seitenzuordnung dabei aufgibt). Der Kontextsatz kommt über einen austauschbaren `context_provider`: Default ist der deterministische, offline `default_context_sentence()` (kein API-Call), optional andockbar an `academic_vault.embeddings.generate_context_sentence` (#109) via `anthropic_context_provider()`; `embedding_text` wird über das bereits vorhandene `build_contextual_embedding_text()` zusammengesetzt. Neue Fixture `tests/fixtures/chunking/multi_section_paper.pdf` (6 Seiten, 1520 global eindeutige Body-Wörter, 6 Überschriften) plus `tests/test_chunking.py` (Tests je AC, inkl. Randfälle: leerer Text, Dokument unter/exakt an/knapp über der Zielgröße).
- **Recall@k-Goldset DE/EN + Embedding-Modell-A/B (#375):** Neue Fixture `tests/fixtures/retrieval_goldset_de_en.json` (12 DE/EN-Queries, 24 Papers in 6 klar getrennten Themenclustern) plus `tests/test_vault_recall_goldset.py`: der Test baut ein echtes Fixture-Vault via `add_paper()`, injiziert den deterministischen `fake_embedder` und ruft `search_papers(..., rerank=True)` real auf — `compute_recall_at_k()` rechnet damit erstmals gegen echte Hybrid-Suchergebnisse statt synthetischer ID-Listen (Mean-Recall@10 = 0.6875, hermetisch, kein API-Key/Netz nötig). Zusätzlich vergleicht `scripts/eval/recall_at_k_model_ab.py` (manuell/einmalig ausgeführt, nicht Teil der Kernsuite) die drei Modellkandidaten e5-small/MiniLM/Qwen3-Embedding-0.6B (`truncate_dim=384`) per Cosine-Top-k auf demselben Goldset; Ergebnis dokumentiert in `docs/evals/recall-at-k-model-ab-375.md` (alle drei erreichen Recall@10 = 1.0 — Deckeneffekt des bewusst sauber getrennten Goldsets, kein Modellvergleich mit Aussagekraft; e5-small bleibt Default).
- **Crossref-Retraction-Check im Reading-List-Import (#383):** `import_reading_list()` prüft nach jedem erfolgreichen `vault.add_paper()`-Aufruf mit DOI zusätzlich `check_retraction(doi)` gegen `api.crossref.org/works/{doi}` (Feld `message.updated-by`, `type == "retraction"`; seit 09/2023 mit Retraction-Watch-Daten integriert, kostenlos, kein API-Key). Maßgeblich ist `updated-by` — Crossref hängt dieses Feld an den zurückgezogenen Artikel, während das Gegenstück `update-to` zur Retraction-Notiz gehört und von dieser auf den Artikel zeigt. Bei Treffer wird das Paper automatisch über den neuen Wrapper `vault_add_excluded_source()` als `excluded_source` markiert. Fail-safe: Netzwerk-/Parse-Fehler bei `check_retraction()` liefern `False` und blockieren den regulären Paper-Ingest nicht. Aufgezeichnete Crossref-Payloads unter `tests/fixtures/crossref/` halten beide Richtungen fest.
- **Eval-Strategie statt stillschweigender Schema-Checks (#390):** Neues Dokument `docs/evals/STRATEGY.md` benennt für jede der 37 Komponenten unter `evals/` genau einen Zustand — `metric` (Offline-Runner bewertet Inhalt), `structural` (nur Struktur geprüft, inhaltliche Bewertung skippt ohne `ANTHROPIC_API_KEY`, Begründung Pflicht) oder `removed`. Der neue Guard `tests/evals/test_eval_strategy.py` prüft die Tabelle gegen das Dateisystem (Set-Gleichheit in beide Richtungen, geschlossenes Status-Vokabular, Existenz genannter Runner) und erzwingt, dass kein Eval-Runner API-Budget verbraucht. Das Dokument beziffert den Budgetbedarf für reale Läufe (ca. 400 Aufrufe pro Vollauf) ausdrücklich als Operator-Entscheid und hält fest, dass Alt-Issue #55 von #390 absorbiert und geschlossen ist.
- **Die zwei toten Eval-Definitionen haben einen echten Ausführungspfad (#390):** `evals/humanizer-de-pipeline/runner.py` misst die Tell-Dichte (Marker aus `skills/humanizer-de/references/patterns.md` pro 100 Wörter) je Vorher/Nachher-Draft-Paar; `evals/auto-download/runner.py` prüft das Tier-Routing der 20 kuratierten Quellen gegen `resolve_pdf_url()` mit gestubbten Tier-Funktionen. Beide laufen ohne Netz und ohne API-Key, beide sind über `tests/evals/test_humanizer_pipeline_evals.py` bzw. `tests/evals/test_auto_download_routing.py` in jeden `pytest`-Lauf eingebunden. Gegen Placebo-Metriken sichern Negativkontrollen: Detection-Floor und Substanz-Quotient (Humanizer, verhindert „Reduktion durch Kürzen") sowie ein Leerlauf ohne Treffer, der `(None, None)` liefern muss (auto-download).

### Changed

- **Schema-Version 6 — CHECK auf `quotes.extraction_method` erweitert (#512):**
  SQLite kann CHECK-Constraints nicht per `ALTER TABLE` ändern, deshalb hebt
  `migrate.widen_extraction_method_check()` Bestands-DBs mit dem
  dokumentierten Tabellen-Rebuild (`CREATE` → `INSERT … SELECT` → `DROP` →
  `RENAME`, `PRAGMA foreign_key_check` vor dem Commit). Der Helfer liest die
  neue Tabellendefinition aus der bestehenden `sqlite_master.sql` und kopiert
  die Spalten über `PRAGMA table_info` — dadurch reihenfolgeunabhängig zu
  `add_stance_column()` und ohne Datenverlust. Erste Migration ohne neue
  Spalte: `db.init_schema()` verifiziert sie deshalb an der CHECK-SQL statt an
  `PRAGMA table_info` und lässt den `user_version`-Stempel aus, wenn der
  Rebuild nicht gegriffen hat.

### Fixed

- **Decision-Log war faktisch tot (#527):** `hooks/post-tool-use-decisions.mjs`
  schrieb jede `.md`-Änderung in die Textdatei `~/.academic-research/decisions.log`,
  während `hooks/mid-session-reinforcement.mjs` die SQLite-Tabelle `decisions` vorlas —
  die niemand befüllte (`vault.add_decision` hatte null Aufrufer). Das seit v6.4
  (#90/#91) beworbene Feature erreichte die Session nie. Der Hook schreibt jetzt über
  das neue Modul `academic_vault/decision_log.py` in genau die Tabelle, aus der das
  Reinforcement liest. Damit die Divergenz nicht über unterschiedliche DB-Pfade oder
  Interpreter zurückkehrt, lösen beide Hooks beides in der gemeinsamen Brücke
  `hooks/lib/vault-bridge.mjs` auf (kein Hook, sondern ein importiertes Modul; liegt
  seit #542 bei den übrigen Bibliotheken in `hooks/lib/`). Auto-Einträge tragen die
  feste Kategorie `file-change` und bleiben pro Datei auf genau einen aktiven Eintrag
  begrenzt — gleicher Inhalts-Hash erzeugt keinen neuen Eintrag, geänderter Hash löst
  den Vorgänger per `superseded_by` ab. `printReminder` gibt sie in einem eigenen Block
  aus (max. 3), getrennt von den manuell gepflegten Decisions (max. 5), damit die
  letzten Writes keine echte Entscheidung aus dem Fenster drängen. Der Schreibpfad
  importiert bewusst nur `academic_vault.db` statt `academic_vault.server` (~0,06 s
  statt ~1,2 s CPU pro Write); dasselbe gilt jetzt für den Lesepfad. Fail-open bleibt
  durchgängig: fehlende DB (die der Hook nie selbst anlegt), gesperrter
  Material-Passport, belegte DB oder unbrauchbarer Interpreter enden in einer
  stderr-Zeile und Exit 0. `decisions.log` ist damit abgelöst und nur noch ein
  **Opt-in-Debug-Log**: es entsteht ausschließlich bei gesetztem
  `ACADEMIC_DECISIONS_LOG`. Die Privacy-Eigenschaften aus #191 gelten unverändert für
  beide Senken — gespeichert werden nur relativer Pfad, Tool-Name und SHA-256 des
  Inhalts, kein Klartext. Der Material-Passport (#380) bleibt von den Auto-Einträgen
  unberührt: `vault.export_material_passport` filtert `file-change` aus
  `decisions_snapshot`, sonst hätte jeder `.md`-Write den `passport_hash` verschoben,
  obwohl sich am Material nichts geändert hat.

- **`topic-brainstorm` fachabhängig statt hartkodierter Cyber-Security-Liste (#471):**
  `scripts/scorer.py` enthielt eine fest kodierte `_TOPIC_DB` mit 5 Themen
  ausschließlich aus dem Cyber-Security-Bereich; `_normalize_field()` mappte
  zusätzlich jede unbekannte Studienrichtung (z. B. „Maschinenbau", obwohl
  `SKILL.md` diese Option selbst anbietet) still auf „Wirtschaftsinformatik" —
  nur der `career_fit`-Score variierte je Fach, Titel, Forschungsfragen und
  Pilot-Papers blieben für jede Anfrage identisch, und kein Vorschlag trug
  eine Begründung. Folgt jetzt dem im Repo etablierten Muster von
  `methodology-advisor` (Scoring-Rubrik lebt im `SKILL.md`, das Modell wendet
  sie an — keine feste Kandidatenliste in Python): `_TOPIC_DB` und
  `_normalize_field`/`_FIELD_NORMALIZE` sind aus `scorer.py` entfernt. Ein
  neuer `--topics-json <pfad|->`-Input (Datei oder stdin) nimmt die vom
  Modell entworfenen Kandidaten entgegen; `--field`, `--work-type` (neu,
  Arbeitstyp) und `--scope` (neu, Umfang) sind zusammen mit `--interests`
  Pflicht-CLI-Args ohne Normalisierung/Fallback und landen unverändert im
  neuen `context`-Objekt der `--output-mode full`-Ausgabe. `scorer.py`
  normalisiert nur noch Feasibility (Budget-/Datenzugang-Modifikatoren) und
  Novelty (Interessens-Overlap); Career-Fit sowie die drei neuen
  Pflichtfelder `reason` (warum passt das Thema zum Zuschnitt), `feasibility_note`
  (Machbarkeitshinweis) und `source_note` (Quellenlagehinweis) reicht der
  Scorer unverändert durch und lehnt Kandidaten ohne diese Felder ab.
  `SKILL.md` Schritt 1 erhebt jetzt zusätzlich Arbeitstyp und Umfang als
  Pflichtangaben (konsistent zum `academic-context`-Skill), Schritt 2
  beschreibt den Kandidaten-Entwurf inkl. Beispiel-Snippet und
  Begründungs-/Machbarkeits-/Quellenlage-Pflicht; `references/scoring-criteria.md`
  stellt die Career-Fit-Referenzwerte als Orientierungshilfe fürs Modell dar
  statt als internen Scorer-Lookup. **Ehrlich benannte Grenze:** Dass das
  Modell inhaltlich sinnvolle, fachspezifische Themen erfindet, ist ein
  Generierungsverhalten ohne API-Budget (Issue #55) — pytest beweist nur den
  Mechanismus (kein Fixed-DB-Fallback mehr, keine stille Feld-Normalisierung,
  Fach/Arbeitstyp/Umfang/Interessen erreichen die Ausgabe unverändert, zwei
  disjunkte Fach-Fixtures bleiben disjunkt), nicht die inhaltliche
  Themenqualität selbst — Operator-Entscheid vom 2026-07-30 (Issue-Kommentar)
  hat AC entsprechend nachgeschärft. Da `SKILL.md` dadurch wächst, hebt
  `tests/baselines/skill_sizes.json`/`tokens.json` die
  `topic-brainstorm`-Baseline um den Netto-Zuwachs an (7200 → 11213 Zeichen,
  1412 → 2416 Token-Proxy) — etabliertes, mehrfach genutztes Repo-Muster für
  legitimes Skill-Wachstum (vgl. 89ca331, d12a976, #395/PR #439). Neu bzw.
  umgeschrieben: `tests/test_topic_brainstorm.py` (Fixtures statt
  Live-DB-Erwartung; neue Tests für Fachabhängigkeit ohne Normalisierung,
  Pflicht-CLI-Args und Skill-Text-Grep auf Begründungs-/Machbarkeits-/
  Quellenlage-Pflicht).

- **Zwei erfundene Flags in der Doku (#461):** `docs/guide/walkthrough.md` zeigte
  `/academic-research:search --import-list <datei>` und
  `/academic-research:fetch --isbn <nummer>` — beide Flags existieren in keinem
  Command (`commands/search.md`, `commands/fetch.md`; `fetch` nimmt ISBN/DOI/URL
  positionell). Ersetzt durch den realen Aufruf bzw. den
  `reading-list-import`-Trigger;
  `test_slash_examples_use_real_commands_and_flags` hält die Leitfaden-Seiten
  künftig gegen die Command-Definitionen.

### Changed

- **Interactive-Gates laufen per Default (#537):** Die beiden Human-Gates aus
  #105 waren vorhanden, standen aber auf Opt-in — im Normalbetrieb sah der User
  weder die Query-Expansion noch die Outline vor dem Draften (Audit-Befund R3).
  In `commands/search.md` ist `--interactive` jetzt `on`; das Phase-1-Gate
  (expandierte Queries aus `queries.json` + Top-5-10-Preview) ist zugleich von
  Schritt 10 an die Position direkt hinter dem Ranking gewandert und greift
  damit **vor** dem teuren LLM-Relevanz-Scoring statt danach, wo es wirkungslos
  war. In `skills/chapter-writer/SKILL.md` verliert das Outline-Gate seine
  Vorbedingung („wenn `/search --interactive` aktiv war") und wird Default. Die
  gate-freien Pfade bleiben erhalten und sind benannt: `--interactive=off` als
  dokumentiertes Opt-out (Verhalten wie vor #537), `--batch` sowie
  nicht-interaktive/headless Läufe ohne `AskUserQuestion`-Kanal; für das
  Outline-Gate ein ausdrücklicher User-Wunsch bzw. `outline_gate: off` in
  `./academic_context.md`. Dieser Schlüssel steht mit Default `on` in
  `scripts/bootstrap/academic_context.stub.md` — analog zu `humanizer_de`, damit
  das Opt-out auffindbar ist und nicht nur im Skill-Text existiert.
- **Jedes Vault-MCP-Tool hat einen Aufrufer (#540):** Neun der 37 per
  `@mcp.tool` registrierten Tools wurden von keinem Skill, Agent, Command oder
  Hook angesprochen — sie kosteten in jeder Session Tool-Listen-Kontext, ohne
  dass ein Workflow sie erreichte. Statt sie zu deregistrieren (was `#226` für
  `supersede_decision`/`list_excluded_sources` explizit zurückgedreht hätte),
  sind sie jetzt dort verdrahtet, wo die Lücke fachlich saß: `add_chapter` und
  `extract_fulltext` in `book-handler` (Kapitel am indexierten Sammelband; der
  Volltext-Index überlebt sonst kein `update_pdf_path` nach OCR), `get_figure`
  als Read-back in `figure-verifier`, `is_excluded` als Vorab-Check in
  `reading-list-import` (der Re-Import holte bis dahin aussortierte Quellen
  zurück), `list_excluded_sources` in `prisma-flow` (PRISMA 2020 verlangt
  Ausschlussgründe, nicht nur Zahlen), `add_score_snapshot`/`get_score_history`
  in `source-quality-audit` und die Decision-Tools in `academic-context` —
  letzteres füllt zugleich den bis dahin immer leeren `decisions_snapshot` des
  Material-Passports. Registrierung und Doku bleiben unverändert (37 Tools);
  `tests/test_issue_540_vault_tool_callers.py` hält den Vertrag: jedes
  `@mcp.tool` braucht eine Referenz in `skills/`, `agents/`, `commands/` oder
  `hooks/` (`docs/` zählt bewusst nicht mit, sonst wäre der Guard tautologisch
  grün), und die Tool-Tabellen in `docs/reference/vault.md` müssen sich exakt
  mit der Registrierung decken. `tests/baselines/*.json` um den Netto-Zuwachs
  der fünf Skills angehoben (etabliertes Repo-Muster, vgl. #471/PR #547).

- **`hooks/` trennt Hooks von Bibliotheken (#542):** Flach in `hooks/` liegen jetzt
  ausschließlich die fünf in `hooks/hooks.json` registrierten Hooks; die importierten
  Module (`citation-parse.mjs`, `citation-cascade.mjs`, `vault-bridge.mjs`) und das
  nicht verdrahtete Setup-Skript `onboard-project-uni-prompt.sh` liegen in `hooks/lib/`
  — weiterhin innerhalb der protected area „hooks". Voraussetzung dafür war der
  Syntax-Gate: der CI-Job `hook-syntax` iterierte über den **nicht-rekursiven** Glob
  `hooks/*.mjs` und hätte jede Datei unterhalb von `hooks/lib/` still ungeprüft
  gelassen — genau deshalb musste `vault-bridge.mjs` bis dahin flach liegen. Der Gate
  läuft jetzt als `scripts/dev/check-mjs-syntax.sh` über **alle getrackten `*.mjs`**
  (Vorbild: `scripts/dev/check-shell-syntax.sh`, #469) und erfasst damit auch
  `scripts/export-literature-state.mjs`, das bisher ebenfalls außerhalb des Gates lag.
  Er bricht ab, wenn er keine einzige Datei findet, damit ein künftiger
  Coverage-Verlust laut statt still ist.

- **`docs/` ist eine navigierbare Referenz statt eines gewachsenen Ordners (#452):**
  Neue Einstiegsseite `docs/README.md` mit drei Lesepfaden (Erstnutzer,
  Fortgeschrittene, Beitragende) plus einem eigenen Abschnitt für Historisches; von
  dort ist jede Datei unter `docs/` in höchstens zwei Klicks erreichbar. Die bisher
  neun verwaisten Dateien (u. a. `docs/evals/README.md`, `docs/literature-state-schema.md`,
  `docs/skills/notebook-bundle.md`, `docs/superpowers/README.md`) hängen jetzt am
  Linkgraphen. Alle Referenz- und Anleitungsseiten folgen derselben Grundstruktur —
  H1, Breadcrumb `[← Doku-Übersicht]` auf die Einstiegsseite, Lead-Absatz, dann die
  Abschnitte; die 13 bisherigen `[← zurück zur README]`-Backlinks zeigen entsprechend
  auf die Übersicht statt auf die README. Historische Dokumente und Momentaufnahmen
  tragen die Kennzeichnung jetzt am **Seitenanfang** statt irgendwo im Fließtext
  (`docs/evals/v6.2-tier-eval.md` hatte sie in Zeile 67) und stehen auf der
  Einstiegsseite getrennt von der gültigen Referenz. `docs/audit/2026-06-03-board-audit.md`
  beschrieb sich selbst als „untracked Arbeitsdokument", obwohl die Datei versioniert
  ist — korrigiert. Neuer Abschnitt „Versionierte `.claude/`-Dateien" in
  `docs/development.md`: welche fünf Pfade die `.gitignore`-Allowlist zulässt (#343),
  wozu jeder dient und was ihr Entfernen konkret bricht (CI-Job `flowkit-hook-harness`
  über `scripts/dev/test-pretooluse-blocker.sh`, vorsorgliche Bash-Blockade durch
  `.claude/settings.json`, verlorene `protectedAreas` für flowkit). Alle fünf
  Akzeptanzkriterien sind als Guards in `tests/test_issue_452_docs_structure.py`
  festgeschrieben (BFS über den Linkgraphen, Inbound-Map über alle Markdown-Dateien
  des Repos, Marker-Position, Drift-Check gegen `git ls-files .claude`,
  Layout-Prüfung je Seite); die Seitenlisten in `tests/helpers/docs.py` werden aus
  `git ls-files` abgeleitet, eine neue Seite fällt damit automatisch unter die Guards.
- **`prisma-flow` kennt uneindeutige Fälle (#460):** `render_flow.py` liest
  optional `n_unclear_screening`. Uneindeutige Treffer zählen nicht mehr als
  Volltextkandidaten, sondern bekommen einen eigenen Knoten
  („Unklar — menschliche Entscheidung offen"). Ohne den Zähler ist der Output
  unverändert.

### Fixed

- **Gesamt-Zeitbudget für den Suchlauf (#465):** `run_search()` in `scripts/search.py` wartete bisher unbegrenzt über `concurrent.futures.as_completed()`, bis alle 7 Modul-Futures fertig waren — insbesondere der EconStor-OAI-PMH-Fallback aus #236 (bis zu `OAI_MAX_PAGES=5` × `TIMEOUT=30s` ≈ 150s Worst-Case, laut #456 aktuell der Live-Normalfall, da `econstor.eu`'s REST-Endpunkt durchgehend HTTP 405 liefert) konnte den gesamten Lauf um Minuten verzögern, ohne dass die übrigen, längst fertigen Treffer ausgeliefert wurden. Neuer optionaler Parameter `time_budget: float | None = None` (Default `None` reproduziert exakt das alte, unbegrenzte Verhalten) schaltet auf `concurrent.futures.wait(futures, timeout=time_budget)` um; noch nicht fertige Futures werden **nicht** per `.result()` abgewartet, sondern als „übersprungen" gewertet — getrennt von echten Modulfehlern (`skipped_out`-Ausgabeparameter statt der bestehenden `failed`-Liste, damit die 2-Tuple-Rückgabe von `run_search()` unverändert bleibt und `skills/anchor-paper-survey/scripts/anchor_paper.py`, das `run_search()` ohne `time_budget` aufruft, im alten unbegrenzten Verhalten bleibt). Der Executor wird bei gesetztem Budget per `shutdown(wait=False, cancel_futures=True)` sofort freigegeben, statt am `with`-Block-Exit doch wieder zu blockieren. `search_econstor()` bekommt zusätzlich ein eigenes, engeres `fallback_time_budget` (Default `ECONSTOR_FALLBACK_TIME_BUDGET_S = 20.0`) direkt in der resumptionToken-Schleife (`time.monotonic()`-Vergleich vor jeder weiteren Runde, analog zu den bestehenden Mengenlimits aus #236) — bei Überschreitung bricht die Schleife mit den bis dahin gesammelten Treffern ab, statt weiterzupollen; `run_search()` bindet diesen Wert über `functools.partial()` an `search_econstor()`, ohne die generische `Callable[[str, int], list[dict]]`-Signatur der `MODULES`-Registry zu ändern. Die CLI bekommt zwei neue, optionale Flags `--time-budget` (Default `DEFAULT_TIME_BUDGET_S = 60.0`) und `--fallback-time-budget` (Default `20.0`) — CLI-Läufe sind damit ab sofort standardmäßig budgetiert, programmatische Aufrufer von `run_search()` bleiben unbetroffen, solange sie `time_budget` nicht setzen. Die Sidecar-Statusdatei (`<output-stem>_status.json`, seit #456) bekommt additiv das Feld `skipped_modules`; der Exitcode-1-Fall („alle Quellen ausgefallen") berücksichtigt jetzt `failed` **und** `skipped` gemeinsam, da ein komplett übersprungener Lauf ansonsten fälschlich als Erfolg (Exitcode 0) durchgegangen wäre. Neu: `tests/test_issue_465_time_budget.py` (14 Tests: Konstanten-Existenz, Einhaltung des Gesamtbudgets mit real verzögertem Modul, getrennte Skip-vs-Fail-Kennzeichnung, Vollständigkeit der übrigen Treffer, enges EconStor-Fallback-Budget unabhängig vom Gesamtbudget, CLI-Sidecar-Statusdatei, CLI-Flag-Defaults, sowie 7× Regressionsschutz für `time_budget=None` über alle Module). `commands/search.md` dokumentiert die beiden neuen Flags und das neue Statusfeld.
- **LaTeX-Export: dokumentierte Aufrufparameter existierten nicht im Code (#467):** `commands/latex.md` dokumentierte seit Langem `--kapitel <n>|all --output <datei.tex> [--bib <datei.bib>] [--template <uni>]`, real gab es aber nur die beiden rein positionalen Skripte `render_tex.py <input.md> <output.tex>` (ein File → ein File) und `build_bib.py <vault.db> <output.bib>` (voller Vault-Dump) — keine Kapitel-Auswahl, keine Mehrfach-Kapitel-Verkettung, keine unabhängige `.bib`-Pfadsteuerung, kein Uni-Template-Wrapping. Wer den dokumentierten Aufruf 1:1 nutzte, bekam einen Fehler statt eines Exports. Neuer Orchestrator `skills/latex-export/scripts/export_thesis.py` bündelt eine echte `argparse`-CLI: `resolve_chapters()` löst `--kapitel <n>` robust gegen die im Repo uneinheitliche Namenskonvention auf (`kapitel/3.md`, `kapitel/03-methodik.md` — Matching über die führende Ziffernfolge des Dateinamens-Stamms, numerisch statt alphabetisch sortiert für `all`), mit klarer Fehlermeldung bei fehlendem oder mehrdeutigem Treffer; `apply_template()` ersetzt `%%CONTENT%%` in `~/.academic-research/library-profiles/<uni>.tex.template` und exportiert bei fehlender Vorlage trotzdem — mit erklärender Meldung („Template `<uni>` fehlt.") statt Absturz; `--bib` ist strikt unabhängig von `--output` verkabelt (Default `output/refs.bib`) und nutzt ohne expliziten Pfad den kanonischen `academic_vault.db.default_db_path()` (Issue #190). `commands/latex.md` bekommt dafür ein konkretes Schritt-für-Schritt-Ablauf-Schema (Muster aus `commands/humanize.md`/`commands/excel.md`) statt der bisherigen abstrakten Beschreibung; die für #458 gepinnte `mkdir -p ~/.academic-research/library-profiles/`-Zeile bleibt wörtlich erhalten. Neu: `tests/test_latex_export.py::TestResolveChapters`, `TestApplyTemplate`, `TestExportThesisIntegration`, `TestExportThesisCLI` (22 Fälle, je Akzeptanzkriterium mindestens ein Test). Die neue Workflow-Sektion in `skills/latex-export/SKILL.md` hebt `tests/baselines/skill_sizes.json` (3000 → 3240) und `tests/baselines/tokens.json` (360 → 459) um exakt den Netto-Zuwachs an — etabliertes Repo-Muster für legitimes Skill-Wachstum (vgl. 89ca331, d12a976), keine Aufweichung des Token-Drift-Guards.
- **Suchmodule gegen fehlerhafte Einzeldatensätze abgesichert + Parser-Tests (#456):** `scripts/search.py` fing bisher Fehler nur rund um den *kompletten* Aufruf einer `search_*`-Funktion ab (`_run_module`) — brach die Verarbeitung eines einzelnen Treffers (z. B. `int()` auf ein nicht-numerisches Datumsfeld, `.get()` auf ein Item, das kein Dict ist), verlor die gesamte Quelle alle Treffer, ohne Fehlermeldung und mit Erfolgs-Exitcode. Jede der 7 `search_*`-Funktionen (inkl. beider EconStor-Parsing-Pfade, REST und OAI-PMH-Fallback aus #236) kapselt die Verarbeitung jedes einzelnen Items jetzt in try/except: ein kaputtes Item wird geloggt und übersprungen, die übrigen Treffer bleiben erhalten. `main()` protokolliert einen Quellenausfall jetzt als `WARNING` mit den betroffenen Modulnamen (statt nur einer Zählung) und schreibt bei gesetztem `--output` zusätzlich eine Sidecar-Statusdatei `<output-stem>_status.json` (`requested_modules`, `failed_modules`, `papers_per_module`) — die von `scripts/dedup.py` konsumierte flache `--output`-Liste bleibt unverändert. Nebenbefund beim Einfrieren einer echten EconBiz-Antwort für die Parser-Tests: die API liefert inzwischen ein Elasticsearch-Envelope (`hits.hits`) statt der von `search_econbiz()` erwarteten `results`/`items`-Liste — ohne Fix wären dort dauerhaft 0 Treffer zurückgekommen, ohne jeden Fehlerhinweis (derselbe Symptomkreis wie im Issue beschrieben). `search_econbiz()` erkennt jetzt beide Formen. Zwei weitere Befunde beim Einfrieren einer echten BASE-Antwort: (1) `api.base-search.net` ist registrierungspflichtig („The interface is IP controlled or with an apikey", BASE Interface Guide v1.27) und meldet seine dokumentierten Fehler — darunter das `Access denied` für jede nicht registrierte IP — nicht per HTTP-Status, sondern mit **HTTP 200 + `{"error": ...}`**; `search_base()` fand daraufhin schlicht keine `docs` und meldete 0 Treffer als Erfolg. Das Modul erkennt den Fehler-Envelope jetzt und lässt ihn als Modulausfall sichtbar werden. (2) `search_base()` las den Abstract aus `dcabstract` — ein Feld, das BASE nicht kennt (das Abstract-Feld heißt laut Interface Guide, Appendix 2 „Fields", `dcdescription`); BASE-Treffer hatten dadurch immer `abstract=None`. Neue Fixtures unter `tests/fixtures/search/` (6 echte, per `create_fixtures.py` live abgerufene Kleinantworten; EconStor als OAI-PMH-Antwort, da der REST-Endpunkt aktuell durchgehend HTTP 405 liefert und production Code dadurch immer den Fallback nimmt). Für BASE ist ein Live-Pull mangels Registrierung in keiner unregistrierten Umgebung möglich — eingefroren ist deshalb die vom Betreiber selbst veröffentlichte PerformSearch-Antwort aus dem Interface Guide (`base_documented_response.xml`; der enthaltene Datensatz ist unabhängig gegen `pub.uni-bielefeld.de/record/2710028` gegengeprüft), aus der `create_fixtures.py::solr_xml_to_json` die JSON-Fixture mechanisch ableitet. Neu: `tests/test_search_parsers.py` (7× Positiv-Test gegen die eingefrorene Antwort, 7× Negativ-Test mit einem mutierten Item je Modul, plus Provenienz-Guard, der jede als „echt" bezeichnete Fixture an `create_fixtures.py` bindet) und `tests/test_search_error_handling.py` (Rate-Limit/Serverausfall parametrisiert über alle 7 Module, BASE-Fehler-Envelope, Sichtbarkeits- und Exitcode-Tests für Total- und Teilausfall).
- **`openpyxl` fehlte als Dependency — `/excel` real defekt (#367):** Der vendorierte xlsx-Skill (`skills/xlsx/scripts/recalc.py`, genutzt vom Slash-Command `/excel`) braucht `openpyxl` zwingend, das Paket stand aber weder in `scripts/requirements.txt` noch in `pyproject.toml` — entgegen der Behauptung in `commands/setup.md`/`commands/excel.md`. Ein frisches Setup über den dokumentierten Weg ließ `/excel` mit `ModuleNotFoundError` scheitern. Issue #235 hatte `openpyxl` zuvor bewusst entfernt, weil kein `scripts/*.py`-Modul es importiert — der damalige Scan erfasste den Konsumenten in `skills/xlsx/` nicht; `tests/test_issue_235_unused_deps.py` prüft seither nur noch `pandas`. Neuer Regressionstest `tests/test_issue_367_openpyxl_dependency.py`. Korrektur: Der ursprüngliche Issue-Text (und dieser Eintrag) hatten `/pickup` fälschlich als mitbetroffen genannt — `/pickup` nutzt laut eigener Doku (`commands/pickup.md`) ausschließlich das externe `document-skills:xlsx`-Plugin (kein openpyxl/pandas) und konnte nie durch die fehlende Dependency scheitern; der Regressionstest sichert das jetzt ab.
- **`verbatim-guard.mjs` unterscheidet Fail-open-Fälle und loggt Bypass-Nutzung (#381):** `lookupInVault`/`lookupFigureInVault` behandelten bislang jede Exception aus dem Python-Subprozess identisch zum Fall „Vault-DB fehlt" (fail-open, gleicher Wortlaut) — ein korruptes DB-File wurde damit unsichtbar wie ein frisches Projekt ohne Vault behandelt. Neuer gemeinsamer Helper `warnFailOpen()` formuliert beide Fälle jetzt sichtbar unterschiedlich (`missing-db` vs. `lookup-error`), bleibt aber in beiden Fällen fail-open (kein Regressionsverlust bei fehlender DB). Zusätzlich nannte die Block-Message selbst den Bypass-Marker `<!-- vault-guard: skip -->` im Wortlaut — das lud zur Umgehung ein und ist entfernt (Operator-Doku bleibt einzig in `commands/latex.md`). Jede tatsächliche Nutzung des Markers wird jetzt sichtbar gemacht: stderr-Warnung plus Eintrag in `~/.academic-research/vault-guard-bypass.log` (Override via `VAULT_GUARD_BYPASS_LOG`, 0600-Rechte, best-effort — analog zu `ACADEMIC_DECISIONS_LOG`).

### Changed

- **`skills/xlsx/` entvendoriert — `document-skills` als Plugin-Dependency (#445):** Die 54 Dateien der vendorierten Kopie des Claude-eigenen Excel-Skills sind aus dem Repository entfernt. Grund ist die Lizenz: die mitgelieferte `skills/xlsx/LICENSE.txt` untersagte ausdrücklich abgeleitete Werke und die Weitergabe an Dritte — genau das tat dieses MIT-lizenzierte Marketplace-Plugin, indem es die Dateien versioniert mitverteilte. An ihre Stelle tritt ein `dependencies`-Eintrag in `.claude-plugin/plugin.json` (`{ "name": "document-skills", "marketplace": "anthropic-agent-skills" }`) plus `allowCrossMarketplaceDependenciesOn: ["anthropic-agent-skills"]` in `.claude-plugin/marketplace.json`; ohne diese Allowlist verweigert Claude Code Cross-Marketplace-Dependencies mit einem `cross-marketplace`-Fehler. **Bewusst ohne `version`-Constraint:** Versionsauflösung läuft ausschließlich über Git-Tags nach dem Muster `{plugin-name}--v{version}`, und `anthropics/skills` trägt derzeit keine Tags (`gh api repos/anthropics/skills/tags` → `[]`, Marketplace-Einträge ohne `version`-Feld) — jeder Constraint liefe damit zwingend in `no-matching-tag` und deaktivierte `academic-research` komplett. `commands/excel.md` und `commands/pickup.md` teilen sich jetzt einen wortgleichen, per HTML-Kommentar abgegrenzten Herkunfts-Textbaustein (`<!-- xlsx-backend:start -->`), der Plugin, Marketplace, Upstream-Repo und den Nachinstallations-Weg (`claude plugin marketplace add anthropics/skills` → `claude plugin install document-skills@anthropic-agent-skills`) nennt und die Verfügbarkeitsprüfung **vor** den ersten Skill-Aufruf zieht — fehlt die Dependency, sieht der Nutzer diese Meldung statt eines rohen Tool-Fehlers. `commands/pickup.md` bekommt zusätzlich die bisher fehlende `Skill(document-skills:xlsx)`-Permission (dieselbe Lücke, die #223 für `/excel` schloss). **Faktenkorrektur nebenbei:** `commands/pickup.md` behauptete seit PR #141 wörtlich „kein openpyxl/pandas", und `tests/test_issue_367_openpyxl_dependency.py` zementierte diese Aussage als Guard. Sie war falsch — `/excel` und `/pickup` rufen dasselbe Backend auf, und dessen SKILL.md schreibt „pandas for data, openpyxl for formulas/formatting" und importiert `from openpyxl import Workbook`; der Skill läuft im lokalen Python-Environment des Nutzers. Beide Assertions sind entsprechend umgedreht (`test_pickup_command_doc_names_openpyxl_backed_skill`, `test_openpyxl_dependency_comments_name_the_shared_backend`), die Begründungskommentare über der `openpyxl`-Zeile in `pyproject.toml`/`scripts/requirements.txt` nennen jetzt beide Konsumenten. `openpyxl` bleibt damit unverändert Pflicht-Dependency. Nachzug: Skill-Count 30 → 29 in README-Badge, Architektur-Diagramm, Doku-Karte, beiden Manifest-`description`s, `AGENTS.md` und `docs/reference/skills.md` (Abschnitt „Vendorierte Skills" → „Externe Skills (Plugin-Dependencies)"); Ruff-`extend-exclude` für `skills/xlsx` entfernt; `"xlsx"` aus den acht Vendor-/Exempt-Sets der Testsuite gestrichen, damit dort kein toter Eintrag zurückbleibt. `tests/test_issue_240_xlsx_fourth_edition_typo.py` (prüfte einen Pfad-Tippfehler *innerhalb* der Vendor-Kopie) ist gelöscht — sein Prüfobjekt existiert nicht mehr. **Scope-Korrektur zur Issue-Beschreibung:** `.github/workflows/ci.yml` enthielt entgegen der Annahme im Issue nie einen `skills/xlsx`-Ausschluss; die Vendor-Ausnahmen standen in `pyproject.toml`, dort sind sie entfernt. **Nicht CI-prüfbar und deshalb Operator-Smoke:** dass eine frische Installation die Dependency real mitzieht (`claude plugin list --json` ohne `errors`-Feld) und dass `/academic-research:excel` weiterhin ein Workbook mit allen vier Sheets samt Cluster-Farbcodierung erzeugt — im Runner ist kein Plugin installiert. Neu: `tests/test_issue_445_xlsx_devendored.py` (14 Fälle je Akzeptanzkriterium).

- **README als Schaufenster: Positionierung nach oben, Demo, Voraussetzungstabelle (#451):** Der README-Kopf nennt jetzt innerhalb der ersten Bildschirmseite **was** das Plugin tut, **für wen** es ist und **wodurch** es sich unterscheidet — vor Zitat-Warnung und SciHub-Block. Beide Warnblöcke bleiben wortgleich erhalten (der `SCIHUB-DISCLAIMER-BLOCK` ist unangetastet, es steht nur neuer Text darüber); der bisherige Abschnitt „Für wen ist das?" ist in den Kopf gewandert statt dupliziert zu werden. Neu ist eine visuelle Demonstration: `docs/assets/quickstart.cast` (asciicast v2) trägt die Befehle und Ausgaben der Schritte 1–5 aus `docs/quickstart-protocol.md` im Wortlaut, `scripts/dev/render_quickstart_svg.py` rendert daraus deterministisch `docs/assets/quickstart.svg`. Bewusst statisch statt animiert, weil GitHubs SVG-Sanitizer den Umgang mit SMIL nicht zusichert — der Cast bleibt als abspielbare Quelle im Repo. Zwei Guards halten das Bild ehrlich: jede im Cast getippte Befehlszeile muss im Protokoll belegt sein, und das SVG wird im Test neu gerendert und byteweise verglichen. Der Quickstart bekommt eine Voraussetzungstabelle **vor** dem ersten Befehl, die erstmals **Node.js** nennt (alle Hooks sind `.mjs` und werden in `hooks/hooks.json` als `node …` gestartet — ohne Node greift der Zitat-Guard nicht) und den einmaligen Modell-Download (`intfloat/multilingual-e5-small`, ~470 MB) als eigene Zeile führt, Pflicht sauber von Optional getrennt; die Langform steht in `docs/guide/installation.md`, die README verlinkt nur. Der Suchschritt zeigt jetzt die reale Erfolgsausgabe, damit ein Erstnutzer Erfolg von Fehlschlag unterscheiden kann. Neu: `tests/test_issue_451_readme_showcase.py` — Zahlen-Guards für die bisher ungeprüften Claims (14 Quellen, 7 Browser-Module, 5 Score-Dimensionen, Python-Mindestversion, Modellgröße) hängen an ihrer jeweiligen Code-Quelle (`scripts/search.py::MODULES`, Modul-Reihenfolge in `commands/search.md`, Gewichtstabelle in `commands/score.md`, `pyproject.toml::requires-python`, `academic_vault/embedding_model.py`), nicht an einer zweiten Doku-Stelle; dazu ein Guard, der wörtlich aus `docs/reference/*` kopierte Blöcke und MCP-Toolnamen im README verbietet. Jeder dieser Guards ist per Mutation gegengeprüft. `tests/test_issue_229_arxiv_https.py` erlaubt zusätzlich den SVG-Namespace `http://www.w3.org/2000/svg` — ein Namespace-Bezeichner wie die bereits gelisteten, kein Netzwerk-Endpoint.

- **`evals/SCHEMA.md` dokumentiert das zweite, `cases[]`-basierte Format (#390)** — `fetch`, `publisher-fetchers` (Objekt mit `cases[]`) sowie `figure-verifier` und `oa-fetchers` (Top-Level-Array ohne `component`-Feld) folgten nie dem dokumentierten `prompts[]`-Schema. Bewusst dokumentiert statt normalisiert; ein Umbau würde `tests/test_figure_verifier.py`, `tests/test_oa_fetchers.py` und `tests/test_publisher_fetchers.py` brechen, ohne die Messqualität zu erhöhen. Neu ist außerdem die `runner.py`-Konvention für `metric`-Komponenten.
- **README und `docs/evals/` sagen den Ist-Zustand offen (#390):** Der Abschnitt „Evals" nennt jetzt die tatsächliche Bilanz ohne API-Key (184 bestanden / 148 übersprungen, davon 147 API-gated; vor #390: 112 / 147) und die 3-von-37-Quote echter Offline-Metriken statt einer pauschalen Eval-Zusage. `docs/evals/v6.2-tier-eval.md` ist als historischer Report gekennzeichnet — der dort beschriebene „Eval-Lauf" war ein YAML-Dump ohne jede Prüfung.

- **PDF-Volltext im Suchindex (#373):** Neues Modul `academic_vault/fulltext.py` extrahiert den PDF-Text — pypdf als Default (offline), GROBID opt-in über `GROBID_URL` (`POST /api/processFulltextDocument`, TEI-`<text>`-Baum, Consolidation abgeschaltet) mit stillem Fallback auf pypdf. Neues MCP-Tool `vault.extract_fulltext(paper_id, backend="auto")` (jetzt 34 Tools), neue `VaultDB`-Methoden `set_fulltext()`/`get_fulltext()`/`papers_missing_fulltext()` und die idempotente Backfill-Migration `migrate.add_fulltext_support()` + `migrate.backfill_fulltext()` (CLI: `python -m academic_vault.migrate --db <pfad> --backfill-fulltext`). `vault.add_paper()` extrahiert den Volltext direkt beim Upsert (best effort, abschaltbar via `VAULT_AUTO_FULLTEXT=0`), sodass der Embedding-Ingest aus #372 den PDF-Text statt nur Titel+Abstract einbettet.
- **Klammer-Zitat-Validierung im `verbatim-guard` (#378):** Der Hook prüft jetzt als dritte, additive Stufe auch Klammer-/Paraphrase-Belege (`(Müller 2021, S. 45)`, `(Müller u. a. 2021, S. 45–47)`, `vgl. Schmidt 2019`) gegen den Vault — Familienname und Jahr gegen `papers.csl_json` (Umlaut-Faltung + Diakritika-Strip), Seitenzahl gegen `page_first`/`page_last` bzw. `quotes.printed_page` (wobei nur der vollständige Seitenumfang eine Seite widerlegen kann — `quotes.printed_page` ist eine punktuelle Stichprobe und bestätigt nur). Neue Module `hooks/citation-parse.mjs` (Extraktion inkl. Skip-Regeln für Code, LaTeX-Makros, Struktur-Verweise, `ebd.` und Literaturverzeichnis) und `hooks/citation-cascade.mjs` (Fallback-Kaskade arXiv → CrossRef → Semantic Scholar mit Score-Modell und Frühausstieg); neue Vault-Funktionen `VaultDB.find_papers_by_author_year()`, `VaultDB.page_coverage()` und `server.verify_citation()`. Jede nicht sauber beantwortete Anfrage (Timeout, `ECONNREFUSED`, abgebrochener Body, **jeder** Nicht-2xx-Status — 5xx und 429 ebenso wie 403-Drosselung oder 404 — sowie HTTP 200 mit unlesbarem Body) führt zu einem `[UNVERIFIED]`-Soft-Fail per `hookSpecificOutput.updatedInput` statt zu einem Hard-Block; nur ein sauberes Negativ (2xx mit parsbarem Body im erwarteten Format, aber ohne Treffer) blockiert. Schwellen und Base-URLs sind über `ACADEMIC_CITATION_*` konfigurierbar (Kill-Switch `ACADEMIC_CITATION_CASCADE=off` = Vault-only, kein Netzzugriff); Details in `docs/reference/hooks.md` („Klammer-Zitat-Validierung"). Das PreToolUse-Timeout in `hooks/hooks.json` steigt dafür von 15 s auf 30 s. Der Namensvergleich faltet zusätzlich führende Namenspartikel weg, damit `(von Neumann 1945)` das Paper trifft, dessen CSL-JSON das Partikel in `non-dropping-particle` führt. Die Belegstärke (Seitenangabe, Signalwort, echter Co-Autor — oder derselbe Familienname taucht im Dokument mindestens einmal in einer dieser Formen auf) steuert die Reaktionsstärke: nur eindeutige Belege blockieren, die nackte Form `(Wort Jahr)` erhält höchstens `[UNVERIFIED]`. Reine Datums- und Standangaben (`(Januar 2021)`, `(Stand 2021)`) gelten gar nicht erst als Beleg. Das Prüfkontingent je Write (`ACADEMIC_CITATION_MAX_PER_WRITE`, Default 100) verwirft überzählige Belege nicht mehr still, sondern behandelt sie wie einen API-Ausfall (`[UNVERIFIED]` plus stderr-Warnung) — sonst hätte genug Text vor einem erfundenen Beleg gereicht, um ihn ungeprüft durchzuwinken. **Fixrunde (Marker-Position):** Der Parser verwarf die Fundstelle (Dedup über den Beleg-Text), weshalb die Markierung den Beleg per `indexOf` im **unmaskierten** Text neu suchen musste — mit drei Ausprägungen desselben Fehlers: ein identischer Beleg-String in einem Code-Fence, `\cite{…}` oder im Literaturverzeichnis zog den Marker auf sich, während der tatsächlich ungeprüfte Beleg unmarkiert durchlief; ein dreifach zitierter Beleg bekam genau einen Marker; und bei `MultiEdit` landete ein Beleg aus `edits[1]` in `edits[0]`. `extractCitations()` liefert jetzt eine Fundstelle je Vorkommen mit Offsets `start`/`end` (Invariante `content.slice(start, end) === raw`, die Maskierung ist längenerhaltend), die neue reine Funktion `markSpans()` spleißt positionsbasiert von hinten nach vorne ein, und ein `slice`-Wächter überspringt jede Fundstelle, deren Span nicht zum erwarteten Text passt (stderr-Warnung statt Raten — ein fehlender Marker ist harmlos, ein falsch gesetzter ändert den Text des Nutzers). Die Zuordnung Fundstelle→Segment läuft über gemeinsame Basis-Offsets aus der neuen `collectSegments()`, die `extractContent` und `buildUpdatedInput` teilen, statt über eine zweite String-Suche. Geprüft wird seither je Beleg (dedupliziert über einen stabilen `key`, ein Vault-Lookup und eine Kaskaden-Auflösung), markiert wird je Fundstelle. Der Citation-Fail-open nutzt zudem `warnFailOpen()` aus #381 statt eines eigenen Warn-Wortlauts. **Zweite Fixrunde (verschachtelte Fundstellen):** Der Narrativ-Pass suchte auf einem Text, in dem Klammerinhalte zu Leerzeichen maskiert sind — das `\s+` hinter dem Signalwort sprang über eine ganze Klammer hinweg und erzeugte aus `vgl. (Müller 2021, S. 45) Schmidt 2019, S. 7` eine zweite Fundstelle, die die erste **enthält** (mit `Schmidt` als Autor, der dort gar nicht hinter dem Signalwort steht). `markSpans()` prüfte seinen Wächter gegen den Originaltext, spleißte aber in den bereits um die Marker-Länge gewachsenen Text: der zweite `[UNVERIFIED]` landete mitten im Wort (`… Schmi [UNVERIFIED]dt 2019 …`). Beide Ursachen sind repariert — der Parser verwirft Narrativ-Treffer, die über eine maskierte Region laufen (Zeichenvergleich gegen den Originaltext, damit legitime Belege über einen Zeilenumbruch hinweg erhalten bleiben), und `markSpans()` überspringt zusätzlich jede Fundstelle, die eine bereits markierte überlappt (Warnung auf stderr statt Raten; Sortier-Tie-Break auf `end`, damit bei gleichem Start der präzisere innere Span gewinnt). Die Soft-Fail-Tests für Write/Edit/MultiEdit prüfen seither die Invariante `updated.replace(' [UNVERIFIED]', '') == original` — sie hätte den Wort-Zerschnitt beim ersten Mal gefangen. Der Test-Harness räumt außerdem alle `ACADEMIC_CITATION_*` aus dem geerbten Env, damit die Default-Schwellen-Nachweise (80/65) nicht von der Shell des Ausführenden abhängen. **Dritte Fixrunde (`confidence` war ein Ja/Nein-Tor):** Die Belegstärke entschied, *ob* geprüft wird — und schlug dadurch in beide Richtungen fehl. Falsch-negativ: `runCitationCheck` filterte die unkorroborierte nackte Form vor jedem Vault- und Kaskaden-Lookup weg, ein erfundenes `(Fantasius 2087)` lief bei leerem Vault unblockiert **und** unmarkiert durch (AC2-Loch); die bestehenden Kaskaden-Tests auf dieser Form liefen unbemerkt ins Leere, weil gar keine Anfrage rausging. Falsch-positiv: `COAUTHORS` ließ das Trennzeichen ohne folgenden Namen zu (`(?:\/|&|,|und|…)\s*(?:NAME)?`), und `strong` las das rohe Trennzeichen statt einen wirklich gelesenen Zweitautor — das Komma vor der Jahreszahl galt damit als Co-Autoren-Marker und Prosa wie `(Paris, 2015)` wurde hart geblockt. Neue Regel: geprüft wird jede erkannte Form, die Belegstärke begrenzt nur noch die Reaktion — eindeutige Belege blocken, mehrdeutige bekommen höchstens `[UNVERIFIED]`. Der Prosa-Schutz hängt seither am *Treffer* statt am Ausfiltern: `Fukushima`, `Bologna` und `Paris` sind auch reale Nachnamen, zu denen Vault oder Kaskade in aller Regel ein Paper finden — dann schweigt der Hook. `COAUTHORS` verlangt nach `/`, `&`, `,`, `und` jetzt einen Namen (`u. a.`/`et al.` bleiben eigenständige Marker), und `strong` leitet sich aus den tatsächlich gelesenen Co-Autoren ab. Das Prüfkontingent vergibt eindeutige Belege zuerst, damit die nun mitgeprüften nackten Formen keinen Hard-Block verdrängen können. **Vierte Fixrunde (AC2 galt nur für eindeutige Formen):** Runde 3 hatte die Prüfung geöffnet, die Reaktion der nackten Form `(Wort Jahr)` aber fest auf `[UNVERIFIED]` gedeckelt — ein frei erfundenes `(Fantasius 2087)` lief bei leerem Vault weiterhin durch den Write hindurch, und genau dieser Fall ist die im Issue genannte Motivation; AC2 kennt keine Einschränkung auf eindeutige Formen. Der Deckel war zudem in sich widersprüchlich: dieselbe Codepfad-Alternative schreibt `(Fukushima 2011) [UNVERIFIED]` in genau die Prosa, deren Schonung er begründen sollte — wer diesen Eingriff akzeptiert, kann ihn nicht gegen den Block anführen, der sichtbar ist und nichts in die Datei schreibt. Der Trade-off ist deshalb jetzt eine Politik des Schreibenden statt einer stillen Hook-Entscheidung: neue Env-Variable `ACADEMIC_CITATION_AMBIGUOUS` (`block` = Default, `mark` = bisheriges Verhalten für prosa-lastige Texte); der Block auf einer mehrdeutigen Form nennt den Schalter in seiner Meldung, damit ein False Positive ohne Quellcode-Lektüre auflösbar ist. Sie greift ausschließlich beim **sauberen Negativ** — `unavailable` (API-Ausfall) und „ungeprüft" (Kontingent erschöpft) bleiben in beiden Werten ein Soft-Fail (AC3 steht über der Politik), und eindeutige Formen blockieren in beiden Werten. `confidence` klassifiziert seither nur noch die Form; was daraus folgt, entscheidet `verbatim-guard.mjs::ambiguousPolicy()`.
- **Lokale Embedding-Pipeline (#372):** Neues Modul `academic_vault/embedding_model.py` kapselt `intfloat/multilingual-e5-small` (MIT, 384d) inkl. der e5-Pflichtpräfixe `passage: `/`query: `, L2-Normalisierung und float32-Serialisierung. Neues Modul `academic_vault/ingest.py` verdrahtet Textquelle → Chunks → Embedding → `chunk_embeddings`; `vault.add_paper()` triggert den Ingest best effort (abschaltbar via `VAULT_AUTO_EMBED=0`).

### Dependencies

- **`voyageai`/`cohere` als optionales Extra `rerank-cloud` (#376):** `pyproject.toml` deklariert `[project.optional-dependencies].rerank-cloud` (`voyageai`, `cohere`; `uv sync --extra rerank-cloud`), bewusst getrennt von `dev`, damit die Default-CI-Installation schlank bleibt. Der lokale Reranker-Fallback (`FlagEmbedding`, `BAAI/bge-reranker-v2-m3`) ist dagegen **bewusst KEIN uv-verwaltetes Extra** (P1-Fix aus der Fixrunde zu PR #422, nach zwei gescheiterten Zwischenständen: erst als `rerank-local`-Extra, dann als globale `transformers<5.0`-Ceiling in `[project.dependencies]`) — uv löst ohne `tool.uv.conflicts` alle Extras/Gruppen GEMEINSAM zu einer universellen Version je Paket auf, ein Cap für `FlagEmbedding` (das `transformers<5.0` braucht, da `FlagEmbedding==1.4.0` intern `Tokenizer.prepare_for_model()` aufruft, entfernt in `transformers>=5.x`, verifiziert per Live-Modell-Download `AttributeError`) hätte an JEDER Stelle deklariert jede Installation heruntergezogen, auch `uv sync --extra dev` ohne den lokalen Reranker (real beobachtet: `transformers` 5.14.1→4.57.6, `huggingface-hub` 1.24.0→0.36.2 im Default-Lock). `tool.uv.conflicts` (die uv-eigene Lösung für inkompatible Extra-Versionen) verbietet dafür die gleichzeitige Installation der konfliktären Extras — genau das braucht aber der AC2-Live-Test (`dev` + lokaler Reranker zusammen). Opt-in daher nur manuell, außerhalb von uv.lock: `uv sync --extra dev && uv pip install 'FlagEmbedding>=1.3,<2.0' 'transformers<5.0'`, danach `uv run --no-sync ...` (sonst syncet uv den manuellen Downgrade weg).
- **`sentence-transformers>=3.0` ist neue Laufzeit-Abhängigkeit (#372)** — in `pyproject.toml` und `scripts/requirements.txt`. Ohne das Backend bliebe `chunk_embeddings` in jeder realen Installation leer und die Vektor-Suche wäre eine Attrappe. Torch bezieht `uv` über `[tool.uv.sources]` aus dem CPU-Index von PyTorch, damit der CUDA-Stack (mehrere GB) nicht in `uv.lock` und in jeden CI-Job wandert. Die Modellgewichte (~470 MB) werden beim ersten `add_paper()` nach `VAULT_EMBEDDING_CACHE` geladen; scheitert das, warnt der Vault im Log und läuft FTS5-only weiter.

### Changed

- **FTS5-Trigger schreiben `fulltext` nicht mehr hart auf `NULL` (#373):** `papers_ai`/`papers_au` ziehen den Volltext per Subselect aus der neuen Tabelle `paper_fulltext`, sodass er den Trigger-Rebuild bei jedem `UPDATE papers` (`set_ocr_done`, `update_pdf_path`, …) überlebt. Die Trigger werden in `schema.sql` per `DROP` + `CREATE` neu angelegt, damit `init_schema()` auch Bestands-DBs umstellt. `vault.search` nutzt `snippet(papers_fts, -1, …)` und zeigt damit die tatsächliche Fundstelle statt immer den Titel.
- **`_vec0_search` ist keine Attrappe mehr (#372):** echte KNN-Suche über die vec0-Tabelle `chunk_vectors` mit reinem Python-Fallback für Umgebungen ohne ladbare `sqlite-vec`-Extension (macOS-Matrix). Treffer werden auf Paper-Ebene aggregiert und mit Snippet an die Reciprocal-Rank-Fusion übergeben, sodass `vault.search(rerank=True)` reale Vektortreffer verarbeitet statt FTS5-Ergebnisse umzusortieren. Der Vektorpfad erhält die unsanitierte Query (FTS5-Sanitizing verfälscht die Semantik).
- `VaultDB.add_chunk_embedding()` respektiert jetzt den Material-Passport-Lock (analog #407) und spiegelt Vektoren nach `chunk_vectors`; neu sind `VaultDB.knn_chunks()`, `VaultDB.delete_chunk_embeddings()`, `VaultDB.sync_chunk_vectors()` und die idempotente Migration `migrate.add_chunk_vectors_table()` für Bestands-DBs.

### Fixed

- **Reranking war nie funktionsfähig (#376):** `apply_reranker` fing bei gesetztem `VOYAGE_API_KEY`/`COHERE_API_KEY` jede Exception mit einem stillen `except Exception: pass` — verifiziert schlug `rerank_with_voyage`/`rerank_with_cohere` sofort mit `ImportError` fehl, weil `voyageai`/`cohere` in keiner Dependency-Datei standen, ohne dass der Nutzer davon erfuhr. Behoben: benanntes Exception-Handling (`ImportError` separat + die jeweilige SDK-Fehlerbasis `voyageai.error.VoyageError`/`cohere.core.api_error.ApiError`) mit `logger.warning(...)` auf jeder Fallback-Stufe; jedes Ergebnis-Dict trägt jetzt `reranked` (bool) + `reranker` (`"voyage"`/`"cohere"`/`"local-bge"`/`"none"`). Neuer kostenfreier lokaler Fallback über `BAAI/bge-reranker-v2-m3` (Apache-2.0, FlagEmbedding), der **nur** greift, wenn beide Cloud-Keys fehlen — ein fehlgeschlagener Voyage/Cohere-Aufruf wird nicht still durch den lokalen Reranker ersetzt. `academic_vault/server.py::search_papers` ruft `apply_reranker` jetzt immer auf (statt nur bei gesetztem Cloud-Key), damit der lokale Fallback überhaupt erreichbar ist.
- **`mid-session-reinforcement.mjs` lief ins Leere (#382):** Der Hook war auf `Notification` und `PostCompact` verdrahtet — laut offizieller Claude-Code-Doku injizieren nur `UserPromptSubmit`, `UserPromptExpansion` und `SessionStart` ihr stdout tatsächlich als Modell-Kontext. Umgestellt auf `UserPromptSubmit` (Intervall-Trigger, alle ~20 Nachrichten) und `SessionStart` mit `matcher: "compact"` (Compaction-Trigger); `hooks/hooks.json` enthält damit 6 statt 7 Top-Level-Events.
- **`mid-session-reinforcement.mjs`: Intervall-Trigger feuerte auch nach dem `UserPromptSubmit`-Umbau nie (#382-Review-Nachbesserung):** Die Trigger-Bedingung hing an `input.message_count` — ein Feld, das der reale `UserPromptSubmit`-Payload von Claude Code laut Doku nicht enthält (nur `session_id`, `prompt_id`, `transcript_path`, `cwd`, `permission_mode`, `effort`, `hook_event_name`). `messageCount` blieb dadurch immer `0`, der Intervall-Pfad exitete stets ohne Ausgabe; nur der `SessionStart`/`compact`-Pfad funktionierte. Der Hook zählt jetzt seine eigenen `UserPromptSubmit`-Aufrufe persistent in der State-Datei (`prompt_count`) statt sich auf das nicht existente Feld zu verlassen — jeder Aufruf entspricht einer realen User-Message.
- **`mid-session-reinforcement.mjs`: ein Hook-Timeout fror den Intervall-Zähler dauerhaft ein (#382-Review-Nachbesserung):** Auf dem Trigger-Pfad wurde der bereits erhöhte `prompt_count` erst **nach** dem Vault-Lookup persistiert. Der Lookup blockiert pro Interpreter-Kandidat bis zu 10 s (bis zu vier Kandidaten), das `UserPromptSubmit`-Timeout in `hooks/hooks.json` beträgt 15 s — wird der Hook dabei abgeschossen, stand in der State-Datei weiterhin `TRIGGER_N-1`. Der nächste Prompt traf damit wieder den Trigger-Pfad, hing wieder, wurde wieder gekillt: der Zähler kam nie über `TRIGGER_N-1` hinaus und der teure Lookup lief ab da bei *jeder* Nachricht statt bei jeder N-ten. Der Zähler wird jetzt auf beiden Pfaden unmittelbar nach dem Inkrement gespeichert, vor dem Lookup. Preis: stirbt der Hook während des Lookups, entfällt die Erinnerung dieser Runde.
- **`mid-session-reinforcement.mjs` injizierte in echten Sessions einen leeren Hinweis (#382-Review-Nachbesserung):** Der Vault-Lookup lief über `python3` aus der `PATH`. In einer echten Session erbt der Hook die Shell-`PATH` des Nutzers, dort steht meist das System-Python (macOS: `/usr/bin/python3` == 3.9), das `academic_vault` mangels PEP-604-Syntax nicht einmal importieren kann — der Hook injizierte dann zwar Text, aber nur die leere Hülle `(keine aktiven Decisions)` trotz gefülltem Vault. In der Testsuite fiel das nie auf, weil `uv run pytest` das venv-Python an den `PATH`-Anfang stellt. Der Hook probiert jetzt der Reihe nach `$ACADEMIC_PYTHON`, `$VIRTUAL_ENV/bin/python`, `~/.academic-research/venv/bin/python` (Setup-venv) und zuletzt `python3`; scheitert alles, bleibt er fail-open.
- **AC1 von #382 ist jetzt direkt belegt statt nur aus der Doku abgeleitet:** Neues Skript `scripts/dev/verify_reinforcement_context.py` führt einen Nonce-Round-Trip gegen eine echte headless `claude -p`-Session (temporärer Vault mit gewürfeltem Marker → Hook → Modell-Antwort) und leitet die `settings.json` aus der deployten `hooks/hooks.json` ab, statt eine Attrappe zu bauen. Zusätzlich prüft es das Session-Transcript auf den `hook_success`-Eintrag. `tests/test_hook_midsession_live_context.py` prüft die Verdrahtung offline in jedem Lauf (nur Events mit echter Context-Injection, `SessionStart` nur mit `compact`-Matcher); der Live-Round-Trip ist per `ACADEMIC_LIVE_CONTEXT_TEST=1` gegated (Muster analog `VAULT_E5_LIVE_TEST`).
- **`pre-compact.mjs`: `SLUG`-Default vermischte Snapshots verschiedener Projekte (#382):** `SLUG` fiel ohne `ACADEMIC_PROJECT_SLUG` hartkodiert auf `'default'` zurück, während `DB_SLUG` bereits `basename(CLAUDE_PROJECT_DIR)` nutzte — Snapshots unterschiedlicher Projekte landeten dadurch im selben `~/.academic-research/snapshots/default/`-Ordner. `SLUG` nutzt jetzt denselben Default wie `DB_SLUG`.
- **Setup prüft jetzt die Node.js-Laufzeit + drei Zugangsdaten-Wege sind erstmals zusammenhängend dokumentiert (#468):** `scripts/setup.sh` warnt beim Fehlen von `node` deutlich (Installationshinweis `brew install node`) statt die 5 node-abhängigen Hooks (u. a. `verbatim-guard`, `claim-drift-guard`) lautlos ausfallen zu lassen — kein harter Abbruch, da venv/Bootstrap/Uni-Profil/SciHub node-unabhängig sind. Neuer Abschnitt „Zugangsdaten" in `docs/guide/installation.md` erklärt gebündelt alle drei tatsächlich existierenden Wege (Such-API-Umgebungsvariablen, Per-Uni-Profil `credentials_keys` via `auth-helper`, HAN-Zugangsdaten-Datei für `ebscohost`/`proquest`/`opac`) statt sie über drei Dateien verstreut zu lassen, inklusive Hinweis auf die bestehende Doku-Drift bei `credentials_keys` (Schema nennt „OS-Keychain", Code liest den Wert direkt aus der YAML). `uni-profiles.md`, `search.md` und `troubleshooting.md` verlinken jetzt dorthin statt Teil-Erklärungen zu duplizieren.
- **Manifest- und Doku-Ehrlichkeit (#453):** Beide Plugin-Manifeste behaupteten Zahlen ohne Code-Bezug — `.claude-plugin/plugin.json` zählte „Google Scholar und 9 weitere" auf 14 Quellen hoch, obwohl `google_scholar` laut `config/browser_guides/google_scholar.md` ein Browser-Modul ist (`scripts/search.py::MODULES` registriert exakt 7 API-Quellen, bereits korrekt in `docs/reference/search.md`); dieselbe Datei sowie `.claude-plugin/marketplace.json` bewarben eine „Universal Book Fetcher (8-Tier-Pipeline)" — der Begriff „Tier" kommt in `agents/book-fetcher.md` nirgends vor und gehört zu einem anderen Feature (`scripts/pdf.py::resolve_pdf_url()`, generische OA-PDF-Auflösung für einzelne Paper). Beide Manifeste nennen jetzt „7 API-Quellen" bzw. „10 Fetcher-Subagenten mit Fallback-Kette" (Zählbasis: die `Agent(...)`-Tools im `book-fetcher`-Frontmatter ohne `auth-helper`). `docs/reference/agents.md` bekommt eine Dispatch-Spalte (automatisch via Caller / manuell) für alle 20 Agents; dabei fielen zwei weitere „Genutzt von"-Fehlangaben auf: `risk-of-bias` wird tatsächlich von `parallel-screening` dispatcht, nicht von `prisma-flow` (das nur die resultierenden Zähler liest), und `figure-verifier` hat entgegen der bisherigen Tabelle gar keinen automatischen Aufrufer im Code — beide korrigiert. Drei Referenzen auf einen nie im Code existierenden `/academic-research:setup`-Migrationsschalter (`CHANGELOG.md`, `docs/guide/troubleshooting.md`, `docs/guide/installation.md`) sind durch den echten, eigenständigen Aufruf `python academic_vault/migrate.py --state literature_state.md --db <vault.db>` ersetzt; der CHANGELOG-Eintrag verlor zusätzlich einen toten Verweis auf `docs/MIGRATION-v5-to-v6.md` (bereits mit #346 entfernt). Neu: `tests/test_issue_453_manifest_honesty.py` prüft alle Zahlen-Claims gegen den Code, guardet gegen erneutes Zählen von Google Scholar als API-Quelle, erzwingt die Dispatch-Spalte und durchsucht die gesamte Doku-Oberfläche plus `CHANGELOG.md` nach dem alten toten Schalter.

### Removed

- **Tote Schema-Tabellen `glossary` und `style_overrides` (#539):** Beide standen seit v6.4 in `schema.sql` und in `migrate.add_v64_tables()`, hatten aber nie einen Lese- oder Schreibpfad (null Treffer in `db.py`/`server.py`) — sie täuschten ein Glossar-/Stil-Feature vor und liefen bei jeder Migration mit. Frische DBs legen sie nicht mehr an; Bestands-DBs räumt der neue idempotente Helfer `migrate.drop_dead_v64_tables()` am Ende von `apply_pending_migrations()` ab. Damit das Versions-Gate aus #368 die bereits auf `user_version = 3` gestempelten DBs überhaupt noch einmal anfasst, steigt `db.CURRENT_SCHEMA_VERSION` auf 4. Datensicherheit vor Aufräumen: Gedroppt wird nur bei `COUNT(*) = 0`; enthält eine der Tabellen wider Erwarten Zeilen, bleibt sie stehen, `init_schema()` verweigert den `user_version`-Stempel (nächster Aufruf versucht es erneut) und warnt mit dem Tabellennamen — kein `raise`, das würde den MCP-Server lahmlegen. Die Tabellennamen existieren im Paket nur noch als `migrate.DEAD_TABLES`; `db.py` importiert die Konstante, statt sie zu duplizieren, und `tests/test_issue_539_drop_dead_tables.py` hält beides fest. **Nicht enthalten:** die `decisions`-Tabelle (bleibt) und der Aufbau eines echten Glossar-Features (eigenes Feature-Issue). Kein Änderungsbedarf an der Doku: `docs/reference/glossary.md` ist das Begriffs-Glossar der Doku und hat mit der DB-Tabelle nichts zu tun.

### Fixed

- **Erste echte `live-fetch-weekly`-Läufe ausgewertet, zwei Live-Test-Fehlbefunde behoben (#612):** `live-fetch-weekly.yml` hatte bis dahin 0 Runs; diese Fix-Runde hat den Workflow zweimal real per `workflow_dispatch` laufen lassen (Runs [30851138735](https://github.com/ahlerjam/academic-research/actions/runs/30851138735), [30851295819](https://github.com/ahlerjam/academic-research/actions/runs/30851295819)) und die Ergebnisse je Fetcher ausgewertet (`docs/evals/2026-08-03-live-fetch-weekly-first-runs.md`). Zwei echte Befunde daraus behoben: (1) `IA_NODE_HOST_RE` in `tests/test_issue_450_live_fetch.py` akzeptierte nur mit `dn` beginnende archive.org-Speicherknoten — real beobachtet wurden in zwei unabhängigen Netzen sowohl `ia800108.us.archive.org` als auch `dn720200.ca.archive.org`; das Muster deckt jetzt beide Präfixe ab (Regression: `tests/test_issue_450_fetcher_evidence.py::test_ia_node_host_pattern_accepts_both_observed_node_prefixes`), der `internetarchive-fetcher` selbst war in beiden Läufen zuverlässig (PDF byteweise korrekt). (2) Der anonyme No-Login-Abruf, mit dem `pf-07` (Oxford Academic, Issue #449) ursprünglich am 2026-07-29 aufgezeichnet wurde, ist seit mindestens 2026-08-03 durch eine Cloudflare-Managed-Challenge gesperrt (HTTP 403, `Cf-Mitigated: challenge`) — bestätigt über beide Workflow-Läufe plus einen dritten, unabhängigen Abruf außerhalb von GitHub Actions. Da der produktive Zugriffsweg von `agents/oxford-academic.md` (`browser-use` + Shibboleth/OpenAthens) diesen anonymen Pfad nie genutzt hat, bleibt der Agent unverändert; korrigiert wurde stattdessen der jetzt irreführende Live-Test: `tests/test_issue_449_live_fetch.py::test_oxford_academic_still_serves_the_recorded_pdf`/`test_oxford_academic_pdf_is_served_without_login` sind jetzt `xfail(strict=True)` (schlägt der Anbieter die Sperre wieder ab, meldet CI das laut als XPASS), ein neuer Test bestätigt aktiv die Cloudflare-Challenge als aktuellen Zustand. `evals/publisher-fetchers/live-verification.json` trägt bei `pf-07` eine additive Korrekturnotiz (`anonymous_access_correction_612`) — der ursprüngliche Beleg von #449 bleibt als historischer Datensatz unverändert stehen.

---

## [6.5.1] — 2026-06-03

### Fixed

- **Vault-MCP-Server startet wieder (#217):** Drei sich gegenseitig blockierende Start-Ursachen behoben: (1) `.mcp.json` startet den Server jetzt mit der Projekt-venv (`${HOME}/.academic-research/venv/bin/python`) und setzt `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`; (2) `mcp>=1.0` + `sqlite-vec>=0.1.0` werden über `scripts/requirements.txt` ins venv installiert; (3) Namespace-Kollision mit dem `mcp`-SDK aufgelöst — lokales Paket `mcp/academic_vault/` → `academic_vault/` (Top-Level) verschoben, alle Referenzen (`.mcp.json`, Hooks, Skills, Tests) angepasst.
- **`/history --restore` repariert (#219):** Literal-Platzhalter `<PLUGIN_ROOT>` in `commands/history.md` durch `${CLAUDE_PLUGIN_ROOT}` ersetzt — der Pfad wird nun zur Laufzeit expandiert, `import academic_vault.server` schlägt nicht mehr fehl.

## [6.5.0] — 2026-05-18

### Added

- **Contextual Retrieval (#109):** Hybrid BM25 + vec0 mit Reciprocal-Rank-Fusion (RRF). 1-Satz-Kontext-Embedding vor jedem Chunk via Anthropic Prompt-Caching (1h-TTL). `vault.search(query, rerank=true)` für optionales Reranking.
- **Reading-List-Import (#95):** Neuer Skill `reading-list-import`. Input: PDF, Markdown oder Plaintext mit Quellenliste. LLM-Parser (Sonnet) → DOI/ISBN-Resolution → Vault. AskUserQuestion bei Mehrdeutigkeit. Anystyle (Ruby) als optionales Backend.
- **LaTeX-Export (#96):** Neuer Skill `latex-export`. Markdown-Kapitel → `.tex` (Pandoc optional, fallback custom Renderer). Bibliographie → `.bib` (biblatex, DIN-1505). Per-Uni-Template-Slot: `~/.academic-research/library-profiles/<uni>.tex.template`. Neuer Command `/academic-research:latex --kapitel <n>|all --output thesis.tex`. Verbatim-Validation auch auf `*.tex`-Outputs.
- **Topic-Brainstorm (#107):** Neuer Skill `topic-brainstorm`. Trigger: *„welches Thema?"*, *„Themenfindung"*. 3–5 Kandidaten mit Feasibility/Novelty/Career-Fit-Scores, je 2–3 Forschungsfragen + 1 Pilot-Paper-Set. Übergang zu `research-question-refiner`.
- **Grant / Poster / Response (#108):** Drei neue Output-Skills (Default-Off, Opt-in via `output_targets` in `academic_context.md`):
  - `grant-proposal`: DFG/BMBF/EU-Antragsstruktur mit Vault-Quellen
  - `conference-poster`: A0-Poster (LaTeX tikzposter / PowerPoint)
  - `reviewer-response`: Point-by-point Response-Letter
- **SciHub-Tier Opt-in (#97):** Optionaler Last-Resort-Fetcher. Default DEAKTIVIERT. Aktivierung via `/academic-research:setup` → explizite Opt-in-Frage. Provenance-Tag `provenance:scihub` im Vault. Output-Hinweis *„Quelle via SciHub bezogen — bitte zusätzlich legalen Zugriff klären."*
- **README + Docs Rewrite (#98):** Kompletter README-Rewrite für v6.x (Vault, Universal Book Fetcher, humanizer-de, Per-Uni-Profile, alle v6.x-Features). Neues `CHANGELOG.md` (alle v6.x-Releases). Neues `docs/MIGRATION-v5-to-v6.md`. Glossar-Erweiterung (Vault, Subagent, Site-Profile, Material-Passport, Contextual Retrieval, RRF, CSL, humanizer-de).

### Changed

- `vault.search()` unterstützt jetzt `rerank=true` für Cohere/Voyage-Reranking.
- `skills/style-evaluator/SKILL.md`: triggert `humanizer-de` als Subagent bei `output_target ∈ {Bachelor, Master, Diplom, Dissertation}`.

---

## [6.4.0] — 2026-05-17

### Added

- **Vault-Foundation (#148):** `vault.add_decision` / `vault.list_decisions`, `vault.add_score_snapshot` / `vault.get_score_history`, `vault.add_risk_of_bias` / `vault.list_risk_of_bias`, `vault.export_snapshot` / `vault.restore_snapshot`.
- **Material-Passport (#104):** `vault.export_material_passport` / `vault.lock_passport` / `vault.is_locked`. Neuer Skill `material-passport`. Repro-Lock verhindert nachträgliche Änderungen an gesperrten Artefakten.
- **PRISMA-Flow (#92):** Neuer Skill `prisma-flow`. Mermaid-Diagramm + 27-Punkte-PRISMA-2020-Checkliste. Integration in `/search` (schreibt `n_identified`, `n_after_dedup`) und `relevance-scorer` (`excluded_screening`).
- **Meta-Analysis (#150):** Neuer Agent `meta-analysis`. DerSimonian-Laird Random-Effects-Modell. Mermaid-Forest-Plot. Output via `scripts/meta_analysis.py`.
- **Risk-of-Bias (#100):** Neuer Agent `risk-of-bias`. Cochrane RoB 2, ROBINS-I, CASP Assessment. Ergebnisse in `vault.add_risk_of_bias()`.
- **Hooks-Stack (#91, #103):** 7 Hook-Events (5 Skript-Dateien + 1 Inline-Bash):
  - `pre-compact.mjs` (`PreCompact`): Snapshot-Backup vor Claude-Compaction nach `~/.academic-research/snapshots/`.
  - `post-tool-use-decisions.mjs` (`PostToolUse(Write)`): Decision-Log für alle `*.md`-Schreiboperationen.
  - `mid-session-reinforcement.mjs` (`Notification` + `PostCompact`): Anti-Fabrikations-Erinnerung nach ~20 Nachrichten bzw. nach Compaction.
  - `verbatim-guard.mjs` (`PreToolUse(Write)`): Blockt Kapitel-Writes mit nicht-verifizierten Zitaten.
  - `onboard-project-uni-prompt.sh` (`SessionStart`): Prüft Python-venv-Bereitschaft.
  - Inline-Bash (`Stop`): Hinweis bei ungesicherten `academic_context.md`-Änderungen.
  - `/academic-research:history --restore <ts>`: Snapshot-Restore.
- **Citation-Styles MLA/Vancouver/Springer-AD (#106):** Drei neue Varianten in `citation-extraction/references/`.
- **CSL-JSON Import (#93):** Neuer Skill `citation-style-import`. Lädt beliebige `.csl`-Datei aus CSL-Repository, parst zu promptfähigen Regeln, speichert als `references/custom-<style>.md`.
- **Batch-API für Bulk-Scoring (#94):** `--batch`-Flag für `/search` und `/score`. Job-ID in `$SESSION_DIR/batch.json`. 50 % Kostenreduktion bei > 50 Papers. Pickup via `/academic-research:history --batch <id>`.
- **Interactive Search Mode (#105):** Interaktiver Modus bei `/search --interactive`: schrittweise Filter, Query-Verfeinerung, Cluster-Vorschau.
- **Cluster-Visualisierung (#132):** Mermaid-Diagramm aus 5D-Scoring-Output. Einbettbar in `kapitel/literatur.md`.

### Changed

- `tests/baselines/skill_sizes.json`: aktualisiert für neue Skills.
- `scripts/requirements.txt`: `meta_analysis`-Dependencies ergänzt (scipy, numpy).

---

## [6.3.0] — 2026-05-16

### Added

- **Zotero-Import (#143):** Neuer Skill `zotero-import`. pyzotero-Pull-only (kein Push). DOI/ISBN-basierte Dedup gegen Vault. Konfiguration via `~/.academic-research/config.yaml` (Zotero API-Key, Library-ID).
- **NotebookLM-Bundle (#144):** Neuer Skill `notebook-bundle`. Packt PDF-Bundle aus Top-N-Papers + Bibliographie als ein PDF. Unterstützt Split-Modus für einzelne Dokumente. Für Bücher > 600 Seiten als Triage-Tool. Output-Pfad-Fix: Split-Modus respektiert `output_path`-Verzeichnis.

### Notes

- NotebookLM-Bundle ist kein Zitationsweg — kein Verbatim-Garantiepfad. Nur als Exploration-Tool gedacht.

---

## [6.2.0] — 2026-05-14

Wave 1: Universal Book Fetcher — 11 PRs (Tickets #131–#141).

### Added

- **Universal Book Fetcher — Site-Subagenten (#138):** 9 Browser-Subagenten für Buch-Download:
  - `tib-fetcher`, `springer-book`, `oapen-fetcher`, `doabooks-fetcher`, `degruyter`, `nationallizenzen`, `ebook-central`, `kvk-fetcher`, `generic-fetcher`
  - Jeder Subagent kennt nur seine Site. Nur `browser-use` CLI — kein curl/wget/direktes HTTP.
- **book-fetcher Master-Agent (#137):** Orchestriert Site-Subagenten. Strategie basiert auf Input-Typ (OA, Verlags, unbekannt) und Per-Uni-Profil. Strikt sequentiell (single Browser-Session).
- **auth-helper Subagent (#136):** Gemeinsamer Auth-Agent für alle Site-Subagenten. Unterstützt HAN, Shibboleth-WAYF, EZproxy, DFN-AAI.
- **Per-Uni-Profile (#133):** `library-profiles/<uni>.yaml`. Mitgelieferte Profile: Leibniz FH, TU München, RWTH Aachen, FAU Erlangen-Nürnberg. Templates: HAN, Shibboleth, EZproxy, OA-only. Setup fragt beim Erstaufruf nach Uni.
  > Anmerkung (#387, nachträglich): Das damalige Profil-Set wurde seither ersetzt. Unter `config/library-profiles/` liegen heute `eth-zurich`, `fu-berlin`, `tum`, `uni-hamburg`, `uni-wien` — dieser historische Log-Eintrag bleibt unverändert stehen, beschreibt aber nicht mehr den aktuellen Bestand.
- **`/academic-research:fetch` Command (#140):** Parst ISBN/DOI/URL/Freitext, startet `book-fetcher`, schreibt Ergebnis in Vault. Bei `captcha`: Screenshot + User-Handoff. Bei `pickup_required`: Eintrag in Pickup-Liste.
- **`/academic-research:pickup` Command (#141):** Erzeugt Bibliotheks-Pickup-Excel aus nicht-OA-Quellen. 4 Sheets: Vor-Ort / Fernleihe / OA / Lizenz. OPAC-Standort + Code128-Barcode.
- **OA-Site-Subagenten (#134):** TIB, OAPEN, DOAB, KVK mit Tests und Evals.
- **Auto-Download-Pipeline 8-Tier (#135):** OpenAccessButton, DOAB, EuropePMC als Tiers 6–8. Ergänzt bestehende 5-Tier-Pipeline.
- **Browser-Guides (#131):** Neue Guides für TIB, OAPEN, DOAB, De Gruyter, Nationallizenzen, Ebook Central, KVK. Springer-Guide überarbeitet (Buch-Download-Block).
- **Cluster-Mermaid (#132):** Cluster-Visualisierung als Mermaid-Diagramm.

### Changed

- `config/browser_guides/springer.md`: Buch-Download-Flow ergänzt.

---

## [6.1.0] — 2026-05-13

Wave 1: Bücher, OCR, Seitenmapping, VLM, Evals — viele Features.

### Added

- **Eval-Coverage Bücher (#130):** 5 Test-Cases (1 OA, 2 ISBN-only, 1 Scan-PDF, 1 Sammelband). Token-Regression-Baseline unter `tests/evals/book-handler/`.
- **VLM Figure/Table Verification (#129):** Neuer Agent `figure-verifier`. Vault-Tools: `add_figure`, `get_figure`, `list_figures`. Verbatim-Guard prüft Abbildungsreferenzen. Eval-Skeleton mit 5 Cases.
- **Page-Mapping pdf_page → printed_page (#128):** `page_offset` in Vault. Sanity-Check über 2 Stichproben-Seiten. Unterstützung für Bücher mit Doppelpaginierung / römischen Vorseiten.
- **OCR-Detection + Trigger-Workflow (#127):** Detektion bei < 100 extrahierbaren Zeichen. `ocrmypdf`-Integration (optional). AskUserQuestion vor OCR-Start.

### Changed

- Vault: `set_ocr_done`, `update_pdf_path`, `set_page_offset`, `get_printed_page`, `add_figure`, `get_figure`, `list_figures` ergänzt.
- `skills/book-handler/SKILL.md`: Kapitel-Schnitt + Seitenmapping + OCR-Pfad integriert.

---

## [6.0.0] — 2026-05-09

Foundation-Release: Vault, Buch-Pfad, humanizer-de, Files-API.

### Added

- **Vault-MCP-Server (initial):** `mcp/academic_vault/` — SQLite mit FTS5 + sqlite-vec. Tools: `vault.search`, `vault.get_paper`, `vault.add_paper`, `vault.add_chapter`, `vault.add_quote`, `vault.find_quotes`, `vault.search_quote_text`, `vault.ensure_file`, `vault.stats`. Datenbank unter `~/.academic-research/projects/<slug>/vault.db`.
- **`book-handler` Skill:** ISBN/Titel → DNB SRU + OpenLibrary + GoogleBooks → Metadaten → OPAC-Suche → DOAB/OAPEN → Kapitel-Schnitt + OCR-Check. CSL-Felder `type: book | chapter`, `container-title`, `editor[]`, `chapter`, `page-first`, `page-last`.
- **`/academic-research:humanize` Command:** Anti-KI-Audit-Pass für Kapitel. Aktiviert `humanizer-de`-Skill im gewünschten Modus. Output: `<basename>.humanized.md` + `<basename>.diff.md`.
- **`humanizer-de`-Integration in `chapter-writer`:** Draft → `humanizer-de(audit)` → `quality-reviewer` → final.
- **`style-evaluator`-Integration:** Triggert `humanizer-de` als Subagent bei Bachelor/Master/Diplom/Dissertation.
- **Files-API für PDFs:** `vault.ensure_file()` lädt PDF zu Anthropic Files-API hoch, cached `file_id` mit TTL. `quote-extractor` nutzt `file_id` statt base64. Feature-Flag in `~/.academic-research/config.yaml`.
- **1h-TTL-Prompt-Caching:** `relevance-scorer`, `quote-extractor`, `chapter-writer`, `quality-reviewer`: `cache_control: {type: "ephemeral", ttl: "1h"}` auf System-Prompt (nach Anthropic-Default-Änderung März 2026).
- **`git init` Auto-Setup:** `/academic-research:setup` bietet optionalen `git init` + Initial-Commit der Bootstrap-Files.

### Changed

- `quote-extractor`: schreibt via `vault.add_quote()` statt JSON-Datei.
- `chapter-writer`: liest via `vault.find_quotes()` + `vault.search()`.
- `literature_state.md`: read-only Snapshot-Export aus Vault (nicht mehr Primary Source).

### Migration

- Bestehende `literature_state.md` kann via `python academic_vault/migrate.py --state literature_state.md --db <vault.db>` in den Vault migriert werden (kein `/academic-research:setup`-Flag — dieser Aufruf ist eigenständig).

---

## [5.4.0] — 2026-04-24

Finale Review-Runde gegen anthropics/skills Cookbook (Commit `5128e186`).

### Changed

- Skill-Namen auf kebab-case (alle 13 Skills): `Abstract Generator` → `abstract-generator` usw.
- `./`-Prefix für Kontext-Datei-Referenzen durchgängig.
- `## Übersicht` als erste H2 in allen 13 Skills (Cookbook-Pattern).
- Few-Shot-Beispiele (Schlecht/Gut mit Grund-Annotation) in 10 bisher few-shot-losen Skills.
- Skill-Cross-Referenzen in Prosa: Title Case → `` `kebab-case` ``.
- `chapter-writer`, `citation-extraction` Trigger erweitert.

### Fixed

- `submission-checker`: Legacy-Datei entfernt, Variant-Selector aktiviert.
- `methodology-advisor`: fehlender `## Abgrenzung`-Block ergänzt.
- `agents/query-generator.md`, `agents/relevance-scorer.md`: `tools: []` Allowlist ergänzt.
- `commands/history.md`: `disable-model-invocation: true` ergänzt.
- `agents/quality-reviewer.md`: ASCII-Umlaute → echte Umlaute.

### Removed

- `settings.json` (Root), `.mcp.json` (Root), `templates/` (Root), `config/scoring.yaml` (obsolet).

### Internal

- 2 neue Regression-Guards: `tests/test_skill_naming.py`, `tests/test_cross_references.py`.

---

## [5.3.0] — 2026-04-24

### ⚠️ BREAKING — Kontext-Ablage geändert

Der akademische Kontext wandert von Claude-Memory (`~/.claude/projects/<hash>/memory/`) in projekt-lokale Dateien (`./academic_context.md`).

### Added

- `/academic-research:setup` erweitert um Projekt-Bootstrap: leere Ordner → Facharbeit-Init; existierende Ordner → idempotent nachrüsten; Code-Repos → nur Environment-Setup.
- Generierte `CLAUDE.md` mit Skill-Delegations-Tabelle und Anti-Fabrikations-Regel.
- Migrations-Helper: `/setup` erkennt Memory-basierten Kontext, bietet Copy an.
- `scripts/project_bootstrap.py` (12 Tests in `tests/test_project_bootstrap.py`).

### Changed

- Alle 13 Skills + `query-generator`: lesen `./academic_context.md` statt Memory.

---

## [5.2.0] — 2026-04-23

### Added

- Native Citations-API in `quote-extractor`, `citation-extraction`, `chapter-writer`.
- Evals-Suite (`tests/evals/`) mit Quality-Evals und Trigger-Evals.
- `quality-reviewer`-Agent (Evaluator-Optimizer-Pattern).
- Domain-organized References in 3 Skills.
- Prompt-Caching in `relevance-scorer` + `quote-extractor`.

---

## [5.1.1] — 2026-04-23

### Fixed

- Abgrenzungs-Klauseln in 8 weiteren Skills.
- Duplikat-Precondition in `literature-gap-analysis` entfernt.
- Trigger-Überschneidung `"Forschungsfrage"` aufgelöst.

---

## [5.1.0] — 2026-04-23

### Added

- Anti-Fabrikations-Klauseln in allen 13 Skills.
- Memory-Precondition-Checks in 12 Skills.
- Few-Shot-Paare in 4 Skills.
- Skill-Abgrenzung zwischen `literature-gap-analysis` und `source-quality-audit`.
- Smoke-Test `tests/test_skills_manifest.py` (51 parametrisierte Tests).

### Changed

- Numerische Schwellen in 5 Skills (advisor, methodology-advisor, submission-checker, style-evaluator, literature-gap-analysis).
- Sprache einheitlich Deutsch in allen Skills/Commands/Agents.
- Umlaut-Varianten in allen 13 Skill-Trigger-Descriptions.

---

## [5.0.1] — 2026-04-23

### Changed

- `scripts/setup.sh` zu vollständigem One-Click-Installer ausgebaut. `browser-use` CLI Auto-Install via `uv`/`pipx`.

---

## [5.0.0] — 2026-04-23

> **⚠️ BREAKING:** Playwright → `browser-use`, Excel → `document-skills:xlsx`.

### Changed

- Browser-Automation von Playwright-MCP auf `browser-use`-CLI umgestellt.
- Excel-Generierung an externes `document-skills:xlsx`-Plugin delegiert (ab v5.5 plugin-intern vendoriert).

### Removed

- `scripts/citations.py`, `scripts/style_analysis.py`, `scripts/ranking.py`, `scripts/excel.py` gelöscht.
- Playwright-Konfiguration entfernt.

---

## [4.0.0] — vor 2026-04-23

Erstes getracktes Release. Monolithische 7-Phasen-Pipeline → 13 modulare Skills. Siehe Git-Historie für frühere Änderungen.

[6.5.0]: https://github.com/ahlerjam/academic-research/compare/v6.4.0...v6.5.0
[6.4.0]: https://github.com/ahlerjam/academic-research/compare/v6.3.0...v6.4.0
[6.3.0]: https://github.com/ahlerjam/academic-research/compare/v6.2.0...v6.3.0
[6.2.0]: https://github.com/ahlerjam/academic-research/compare/v6.1.0...v6.2.0
[6.1.0]: https://github.com/ahlerjam/academic-research/compare/v6.0.0...v6.1.0
[6.0.0]: https://github.com/ahlerjam/academic-research/compare/v5.4.0...v6.0.0
[5.4.0]: https://github.com/ahlerjam/academic-research/compare/v5.3.0...v5.4.0
[5.3.0]: https://github.com/ahlerjam/academic-research/compare/v5.2.0...v5.3.0
[5.2.0]: https://github.com/ahlerjam/academic-research/compare/v5.1.1...v5.2.0
[5.1.1]: https://github.com/ahlerjam/academic-research/compare/v5.1.0...v5.1.1
[5.1.0]: https://github.com/ahlerjam/academic-research/compare/v5.0.1...v5.1.0
[5.0.1]: https://github.com/ahlerjam/academic-research/compare/v5.0.0...v5.0.1
[5.0.0]: https://github.com/ahlerjam/academic-research/compare/v4.0.0...v5.0.0
