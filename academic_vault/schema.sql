-- academic_vault SQLite Schema
-- Tabellen: papers, papers_fts, paper_fulltext, quotes, quote_embeddings,
--           decisions, notes, notes_fts, embedding_meta
-- FTS5-Trigger: papers_ai, papers_ad, papers_au, notes_ai, notes_ad, notes_au

CREATE TABLE IF NOT EXISTS papers (
  paper_id              TEXT PRIMARY KEY,
  type                  TEXT NOT NULL DEFAULT 'article-journal'
                          CHECK(type IN ('article-journal','book','chapter')),
  csl_json              TEXT NOT NULL,
  doi                   TEXT,
  isbn                  TEXT,
  pdf_path              TEXT,
  file_id               TEXT,
  file_id_expires_at    INTEGER,
  page_offset           INTEGER DEFAULT 0,
  ocr_done              INTEGER DEFAULT 0,
  editor                TEXT,
  chapter               TEXT,
  page_first            INTEGER,
  page_last             INTEGER,
  container_title       TEXT,
  parent_paper_id       TEXT REFERENCES papers(paper_id),
  provenance            TEXT DEFAULT NULL,
  added_at              INTEGER NOT NULL,
  updated_at            INTEGER NOT NULL,
  -- Herkunftsart der Quelle (Issue #473): 'literature' = fremde Publikation,
  -- 'primary' = eigenes Erhebungsmaterial (Transkript, Beobachtungsprotokoll).
  -- Bewusst eine eigene Spalte statt einer Erweiterung von `type` oder
  -- `provenance`: `type` traegt den CSL-Typ (CHECK-Constraint, in SQLite nicht
  -- per ALTER erweiterbar), `provenance` beantwortet "woher bezogen" (#195),
  -- nicht "ist das ueberhaupt Literatur". Werteliste gespiegelt in
  -- db.VALID_SOURCE_KINDS und migrate.add_source_kind_column().
  -- Bewusst als LETZTE Spalte: `ALTER TABLE ... ADD COLUMN` (migrate.py) haengt
  -- sie auf Bestands-DBs ebenfalls hinten an, so bleibt die Spaltenreihenfolge
  -- zwischen frischer und migrierter DB identisch (Muster quotes.stance).
  source_kind           TEXT NOT NULL DEFAULT 'literature'
                          CHECK(source_kind IN ('literature','primary')),
  -- Zeitpunkt (Unix-Epoch) der letzten Crossref-Retraction-Pruefung
  -- (Issue #604). NULL = noch nie geprueft. Nur bei erfolgreichem Check
  -- gesetzt (server.check_retractions()) -- ein Crossref-Ausfall laesst den
  -- Wert unangetastet, damit der naechste Lauf automatisch erneut prueft.
  -- Bewusst als LETZTE Spalte (gleiche Begruendung wie source_kind oben).
  retraction_checked_at INTEGER DEFAULT NULL
);

-- FTS5 als eigenstaendige virtuelle Tabelle (kein content=, manuell befuellt).
-- Trigger halten papers_fts synchron mit papers.
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
  paper_id,
  title,
  abstract,
  fulltext
);

-- Teilwort-Index fuer deutsche Komposita (Issue #703). ZWEITE virtuelle
-- Tabelle neben papers_fts, bewusst KEIN Tokenizer-Wechsel an papers_fts:
--
--   * FTS5 kennt keinen Tokenizer je Spalte -- `tokenize` ist eine
--     Tabellenoption. Eine "Trigram-Spalte" in papers_fts ist technisch nicht
--     baubar, und ein Umbau der Tabelle auf tokenize='trigram' wuerde Ranking
--     (bm25 ueber Wort-Tokens), die Prefix-Suche und jedes Token unter drei
--     Zeichen zerstoeren -- der Trigram-Tokenizer indiziert nur Folgen ab drei
--     Zeichen.
--
-- Preis dieses Wegs, bewusst getragen:
--
--   * Indexgroesse -- Trigram legt je Zeichenposition einen Term ab, der Index
--     waechst auf ein Mehrfaches des indizierten Textes. Genau deshalb ist
--     `fulltext` hier NICHT dabei: Titel+Abstract sind ~1-2 KB je Paper,
--     PDF-Volltexte 50-200 KB. Folge und zugleich dokumentierte Grenze:
--     `Mittelstand` findet `Mittelstandsdigitalisierung` in Titel/Abstract,
--     nicht im PDF-Volltext (siehe docs/reference/vault.md).
--   * Trefferrauschen bei Kurzsuchen -- ein 3-Zeichen-Token ist genau ein
--     Trigram und traefe jede Wortmitte ("KMU" in "Werkmuseum"). Deshalb
--     schaltet server._trigram_match_expression() den Zweig erst ab
--     `_TRIGRAM_MIN_TOKEN_LEN` (4) Zeichen frei; darunter bleibt die Suche
--     bitgleich auf dem alten Pfad.
--
-- paper_id ist UNINDEXED: die Spalte wird nur mitgelesen, ein indizierter
-- Bezeichner wuerde als Trigram-Rauschen in jede Suche einstreuen.
CREATE VIRTUAL TABLE IF NOT EXISTS papers_trgm USING fts5(
  paper_id UNINDEXED,
  title,
  abstract,
  tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS quotes (
  quote_id          TEXT PRIMARY KEY,
  paper_id          TEXT NOT NULL REFERENCES papers(paper_id),
  verbatim          TEXT NOT NULL,
  pdf_page          INTEGER,
  printed_page      INTEGER,
  section           TEXT,
  context_before    TEXT,
  context_after     TEXT,
  -- Herkunftsnachweis des Wortlauts. Werteliste gespiegelt in
  -- db.VALID_EXTRACTION_METHODS; Bestands-DBs hebt
  -- migrate.widen_extraction_method_check() per Tabellen-Rebuild auf diesen
  -- Stand (SQLite kann CHECK-Constraints nicht per ALTER TABLE aendern).
  -- 'local-verbatim' (Issue #512) wird in server.add_quote() fail-closed
  -- gegen den lokalen PDF-Volltext geprueft, bevor irgendetwas geschrieben
  -- wird -- der CHECK hier ist nur die zweite Verteidigungslinie fuer
  -- Direkt-Inserts.
  extraction_method TEXT NOT NULL
                      CHECK(extraction_method IN ('citations-api','manual','local-verbatim')),
  api_response_id   TEXT,
  created_at        INTEGER NOT NULL,
  -- Haltung des Zitats zur zitierenden Aussage (Issue #400). Vorgemerkt fuer
  -- eine spaetere, rein lokale NLI-Klassifikation (Konzept-Anleihe: scite
  -- Smart Citations / SemanticCite) -- die Befuellung ist ein Folge-Issue,
  -- bis dahin bleibt das Feld NULL, sofern es nicht manuell gesetzt wird.
  -- Werteliste gespiegelt in db.VALID_STANCES und migrate.add_stance_column().
  -- Bewusst als LETZTE Spalte: `ALTER TABLE ... ADD COLUMN` (migrate.py) haengt
  -- sie auf Bestands-DBs ebenfalls hinten an, so bleibt die Spaltenreihenfolge
  -- zwischen frischer und migrierter DB identisch.
  stance            TEXT CHECK(stance IN ('supports','contrasts','mentions') OR stance IS NULL),
  -- Herkunft von context_before/context_after (Issue #520): 'fulltext' wenn
  -- server.resolve_quote_context() eine Fundstelle im echten paper_fulltext
  -- nachgewiesen und den Kontext daraus geschnitten hat, sonst NULL (Feld
  -- unbefuellt oder modell-generiert -- geraten wird hier nie). Werteliste
  -- gespiegelt in migrate.add_context_source_column(). Bewusst als LETZTE
  -- Spalte, siehe Kommentar bei `stance`.
  context_source    TEXT CHECK(context_source IN ('fulltext') OR context_source IS NULL),
  -- Audit-Historie (Issue #737), additiv zu `stance` und bewusst NICHT
  -- dasselbe Feld: `stance` ist lossy (bei Verdict 'unsupported' wird laut
  -- Mapping-Tabelle des quote-fidelity-auditor-Agenten GAR NICHTS
  -- persistiert, und `add_quote(stance=...)` kann `stance` schon ohne jedes
  -- Audit gesetzt sein) und kann "geprueft & unauffaellig" nicht von "nie
  -- geprueft" unterscheiden. `audited_at` ist NULL, solange kein Audit
  -- stattgefunden hat -- das ist das alleinige Unterscheidungsmerkmal fuer
  -- `vault.chapter_quote_balance()`. Werteliste gespiegelt in
  -- db.VALID_AUDIT_VERDICTS/db.VALID_AUDIT_SEVERITIES und
  -- migrate.add_quote_audit_columns(). Bewusst als LETZTE Spalten, siehe
  -- Kommentar bei `stance`.
  audited_at        INTEGER,
  audit_verdict     TEXT CHECK(audit_verdict IN
                      ('faithful','overstated','context-stripped','polarity-flip','unsupported')
                      OR audit_verdict IS NULL),
  -- NULL fuer `faithful` (kein Befund) UND solange kein Audit stattfand --
  -- `audited_at IS NULL` ist die einzige verlaessliche Unterscheidung
  -- zwischen beidem, `audit_severity` allein reicht dafuer nicht.
  audit_severity    TEXT CHECK(audit_severity IN ('kritisch','hoch','mittel') OR audit_severity IS NULL)
);

-- vec0 Virtual Tables: optional, nur wenn sqlite-vec Extension geladen ist.
-- Werden in db.py per try/except erstellt (quote_embeddings + chunk_vectors,
-- letztere als Spiegel der chunk_embeddings-Vektoren, Issue #372). Die Breite
-- ist seit #629 KEINE Konstante mehr, sondern kommt aus `embedding_meta`
-- (Default fuer einen frischen Vault: embedding_model.DEFAULT_EMBEDDING_DIM):
-- CREATE VIRTUAL TABLE IF NOT EXISTS quote_embeddings USING vec0(
--   quote_id TEXT PRIMARY KEY,
--   embedding FLOAT[<embedding_meta.dim>]
-- );
-- CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
--   chunk_id TEXT PRIMARY KEY,
--   embedding FLOAT[<embedding_meta.dim>]
-- );

-- Bestandsnachweis der Vektoren (Issue #629): mit WELCHEM Modell und in
-- welcher Breite der Vault gefuellt wurde. Singleton (`CHECK(id = 1)`) --
-- mehrere Embedding-Modelle nebeneinander sind bewusst nicht vorgesehen,
-- Vektoren aus zwei Modellen liegen nicht im selben Raum. Fehlt die Zeile,
-- ist noch nie ein Embedding geschrieben worden; die vec0-Tabellen haben
-- dann die Default-Breite. Geschrieben wird ausschliesslich ueber
-- `VaultDB.register_embedding_inventory()`, gelesen u. a. von `vault.stats`.
CREATE TABLE IF NOT EXISTS embedding_meta (
  id         INTEGER PRIMARY KEY CHECK(id = 1),
  model_id   TEXT,
  dim        INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
  decision_id   TEXT PRIMARY KEY,
  category      TEXT,
  text          TEXT NOT NULL,
  rationale     TEXT,
  created_at    INTEGER NOT NULL,
  superseded_by TEXT REFERENCES decisions(decision_id)
);

CREATE TABLE IF NOT EXISTS notes (
  note_id    TEXT PRIMARY KEY,
  paper_id   TEXT REFERENCES papers(paper_id),
  text       TEXT NOT NULL,
  tags       TEXT,
  created_at INTEGER NOT NULL,
  -- Optionale Seitenangabe des Exzerpts (Issue #462, AC2). Bewusst als
  -- LETZTE Spalte: `ALTER TABLE ... ADD COLUMN` (migrate.py) haengt sie auf
  -- Bestands-DBs ebenfalls hinten an, so bleibt die Spaltenreihenfolge
  -- zwischen frischer und migrierter DB identisch (Muster quotes.stance).
  page       INTEGER
);

-- FTS5-Index fuer Notizen (Issue #462, AC4). Eigenstaendige Tabelle statt
-- Erweiterung von papers_fts: FTS5-Virtual-Tables lassen sich nicht per
-- ALTER TABLE ADD COLUMN erweitern (verifiziert, sqlite3 liefert dabei
-- "OperationalError: virtual tables may not be altered"), und ein Rebuild
-- von papers_fts waere fuer dieses Issue unverhaeltnismaessig riskant.
-- paper_id wird -- analog zu papers_fts -- als regulaere (nicht UNINDEXED)
-- Spalte gefuehrt, damit sie ohne Zusatz-Join direkt aus einem Suchtreffer
-- gelesen werden kann.
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
  note_id,
  paper_id,
  text,
  tags
);

-- FTS5-Trigger: befuellen notes_fts manuell (kein content=). Bewusst DROP +
-- CREATE statt CREATE TRIGGER IF NOT EXISTS, siehe Kommentar bei papers_ai
-- oben -- init_schema() fuehrt dieses Skript auch auf Bestands-DBs aus.
DROP TRIGGER IF EXISTS notes_ai;
CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
  INSERT INTO notes_fts(note_id, paper_id, text, tags)
  VALUES (new.note_id, new.paper_id, new.text, new.tags);
END;

DROP TRIGGER IF EXISTS notes_ad;
CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
  DELETE FROM notes_fts WHERE note_id = old.note_id;
END;

DROP TRIGGER IF EXISTS notes_au;
CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
  DELETE FROM notes_fts WHERE note_id = old.note_id;
  INSERT INTO notes_fts(note_id, paper_id, text, tags)
  VALUES (new.note_id, new.paper_id, new.text, new.tags);
END;

-- Kanonischer Speicher des extrahierten PDF-Volltexts (Issue #373).
-- papers_fts ist nur der Index: die FTS-Zeile wird bei jedem UPDATE auf papers
-- vom Trigger papers_au neu aufgebaut, ein nur dort gehaltener Volltext waere
-- nach dem naechsten set_ocr_done/update_pdf_path still verschwunden.
CREATE TABLE IF NOT EXISTS paper_fulltext (
  paper_id     TEXT PRIMARY KEY REFERENCES papers(paper_id) ON DELETE CASCADE,
  text         TEXT NOT NULL,
  extractor    TEXT NOT NULL,
  extracted_at INTEGER NOT NULL
);

-- Strukturerhaltend extrahierte Tabellen (Issue #630). Bewusst NEBEN
-- paper_fulltext und ohne jede Beruehrung der FTS5-Trigger: der Volltextpfad
-- kollabiert Whitespace (richtig fuer den Index, toedlich fuer eine Tabelle),
-- dieser Speicher haelt Zeilen, Spalten und Zell-Bounding-Boxen als JSON.
-- rows_json  = Textmatrix (Zeile -> Spalte -> Wert, null fuer geschluckte
--              Positionen unter verbundenen Zellen)
-- cells_json = je Zelle {row, col, value, bbox} fuer den Beleg auf Zellebene
-- UNIQUE(paper_id, page, table_index) macht die Re-Extraktion idempotent.
CREATE TABLE IF NOT EXISTS paper_tables (
  table_id     TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
  page         INTEGER NOT NULL,
  table_index  INTEGER NOT NULL,
  backend      TEXT NOT NULL,
  n_rows       INTEGER NOT NULL,
  n_cols       INTEGER NOT NULL,
  bbox_json    TEXT NOT NULL,
  rows_json    TEXT NOT NULL,
  cells_json   TEXT NOT NULL,
  extracted_at INTEGER NOT NULL,
  UNIQUE(paper_id, page, table_index)
);

CREATE INDEX IF NOT EXISTS idx_paper_tables_paper ON paper_tables(paper_id);

-- Belegte Kennzahlen aus Tabellenzellen (Issue #741) -- der Weg fuer eine
-- Zahl von einer Tabellenzelle in den Kapiteltext, analog zu quotes fuer
-- Wortlaut. Jede Zeile ist NUR nach erfolgreicher Pruefung gegen die
-- tatsaechliche Zelle (paper_tables.cells_json ueber get_table_cell)
-- entstanden -- claimed_value haelt die vom Aufrufer uebergebene, cell_value
-- die tatsaechliche Zellschreibweise fest (koennen sich in der Schreibweise
-- unterscheiden, siehe academic_vault/numbers.py, niemals im Wert).
-- UNIQUE(paper_id, page, table_index, row, col) macht das erneute Erfassen
-- derselben Zelle idempotent (INSERT OR REPLACE), analog paper_tables.
CREATE TABLE IF NOT EXISTS table_values (
  table_value_id TEXT PRIMARY KEY,
  paper_id       TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
  page           INTEGER NOT NULL,
  table_index    INTEGER NOT NULL,
  row            INTEGER NOT NULL,
  col            INTEGER NOT NULL,
  claimed_value  TEXT NOT NULL,
  cell_value     TEXT NOT NULL,
  evidence       TEXT NOT NULL,
  created_at     INTEGER NOT NULL,
  UNIQUE(paper_id, page, table_index, row, col)
);

CREATE INDEX IF NOT EXISTS idx_table_values_paper ON table_values(paper_id);

-- FTS5-Trigger: befuellen papers_fts manuell via json_extract.
-- Bewusst DROP + CREATE statt CREATE TRIGGER IF NOT EXISTS: init_schema() fuehrt
-- dieses Skript auch auf Bestands-DBs aus; mit IF NOT EXISTS behielten die
-- ihre alten Trigger (fulltext hart NULL) und der Volltext-Index bliebe leer.
-- Seit #703 schreiben dieselben Trigger zusaetzlich papers_trgm fort -- ein
-- zweites Trigger-Trio waere eine zweite Stelle, die beim naechsten
-- Spalten-Zuwachs vergessen werden kann.
DROP TRIGGER IF EXISTS papers_ai;
CREATE TRIGGER papers_ai AFTER INSERT ON papers BEGIN
  INSERT INTO papers_fts(paper_id, title, abstract, fulltext)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract'),
    (SELECT text FROM paper_fulltext WHERE paper_id = new.paper_id)
  );
  INSERT INTO papers_trgm(paper_id, title, abstract)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract')
  );
END;

DROP TRIGGER IF EXISTS papers_ad;
CREATE TRIGGER papers_ad AFTER DELETE ON papers BEGIN
  DELETE FROM papers_fts WHERE paper_id = old.paper_id;
  DELETE FROM papers_trgm WHERE paper_id = old.paper_id;
END;

DROP TRIGGER IF EXISTS papers_au;
CREATE TRIGGER papers_au AFTER UPDATE ON papers BEGIN
  DELETE FROM papers_fts WHERE paper_id = old.paper_id;
  DELETE FROM papers_trgm WHERE paper_id = old.paper_id;
  INSERT INTO papers_fts(paper_id, title, abstract, fulltext)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract'),
    (SELECT text FROM paper_fulltext WHERE paper_id = new.paper_id)
  );
  INSERT INTO papers_trgm(paper_id, title, abstract)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract')
  );
END;

CREATE TABLE IF NOT EXISTS figures (
  figure_id           TEXT PRIMARY KEY,
  paper_id            TEXT NOT NULL REFERENCES papers(paper_id),
  page                INTEGER,
  caption             TEXT,
  vlm_description     TEXT,
  data_extracted_json TEXT,
  created_at          INTEGER NOT NULL
);

-- v6.4: Decision-Log Ergaenzungs-Tabellen
-- (zwei nie angebundene Tabellen sind mit #539 entfernt worden; Bestands-DBs
--  raeumt migrate.drop_dead_v64_tables() auf)

CREATE TABLE IF NOT EXISTS excluded_sources (
  paper_id   TEXT PRIMARY KEY,
  reason     TEXT,
  excluded_at INTEGER NOT NULL
);

-- v6.4: Risk-of-Bias Assessments
CREATE TABLE IF NOT EXISTS risk_of_bias_assessments (
  assessment_id      TEXT PRIMARY KEY,
  paper_id           TEXT NOT NULL REFERENCES papers(paper_id),
  study_type         TEXT NOT NULL,
  domain_scores_json TEXT NOT NULL,
  ts                 INTEGER NOT NULL
);

-- v6.4: Score-Trajectory-Tracking
CREATE TABLE IF NOT EXISTS score_history (
  snapshot_id TEXT PRIMARY KEY,
  paper_id    TEXT NOT NULL REFERENCES papers(paper_id),
  session_id  TEXT NOT NULL,
  ts          INTEGER NOT NULL,
  scores_json TEXT NOT NULL
);

-- v6.4: Material Passport Lock
CREATE TABLE IF NOT EXISTS vault_locked_status (
  slug      TEXT PRIMARY KEY,
  locked_at INTEGER NOT NULL
);

-- Empirischer Teil (Issue #473): eigenes Erhebungsmaterial.
-- Das Transkript selbst ist eine `papers`-Zeile mit source_kind='primary' --
-- nur so greift die bestehende Belegkette (quotes.paper_id -> papers,
-- verbatim-guard ueber search_quote_text()). `transcript_segments` haelt die
-- belegfaehige Stellenangabe: `seq` ist die zitierfaehige Absatznummer,
-- UNIQUE(paper_id, seq) macht den Re-Import idempotent.
CREATE TABLE IF NOT EXISTS transcript_segments (
  segment_id TEXT PRIMARY KEY,
  paper_id   TEXT NOT NULL REFERENCES papers(paper_id),
  seq        INTEGER NOT NULL,
  speaker    TEXT,
  timecode   TEXT,
  text       TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(paper_id, seq)
);

-- Kategorienzuordnung (Issue #473). `category_origin` haelt fest, ob eine
-- Kategorie am Material entwickelt (induktiv) oder aus der Theorie abgeleitet
-- (deduktiv) wurde -- die Herkunft ist Teil der Methodendokumentation, nicht
-- eine Randnotiz. Werteliste gespiegelt in db.VALID_CATEGORY_ORIGINS.
-- quote_id verweist auf das Ankerbeispiel; es bleibt NULL, solange keines
-- ausgewaehlt ist (ein Ankerzitat wird nie erfunden).
CREATE TABLE IF NOT EXISTS codings (
  coding_id       TEXT PRIMARY KEY,
  paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
  segment_id      TEXT REFERENCES transcript_segments(segment_id),
  quote_id        TEXT REFERENCES quotes(quote_id),
  category        TEXT NOT NULL,
  category_origin TEXT NOT NULL CHECK(category_origin IN ('induktiv','deduktiv')),
  memo            TEXT,
  created_at      INTEGER NOT NULL
);

-- v6.5: Contextual Embeddings + Hybrid Retrieval (#109)
-- Speichert Chunk-Texte mit kontextuellem 1-Satz-Kontext und Embedding-Text.
CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id         TEXT PRIMARY KEY,
  paper_id         TEXT NOT NULL REFERENCES papers(paper_id),
  chunk_text       TEXT NOT NULL,
  context_sentence TEXT NOT NULL,
  embedding_text   TEXT NOT NULL,
  embedding_vector BLOB,
  created_at       INTEGER NOT NULL
);

-- FTS5-Index ueber Chunk-Texte (Issue #726). `papers_fts`/`papers_trgm`
-- matchen nur Paper-Felder (Titel, Abstract, Volltext) -- ein Begriff, der
-- ausschliesslich im Methodikteil eines einzelnen Chunks steht, war darueber
-- unauffindbar, obwohl die Vektorsuche laengst chunkgenau trifft. Eigene
-- virtuelle Tabelle analog zu `notes_fts` (kein `content=`, manuell befuellt),
-- NICHT analog zu `papers_trgm`: der Auftrag ist ausdruecklich EIN FTS5-Index
-- mit derselben Tokenizer-Entscheidung wie `papers_fts` (unicode61-Default,
-- kein Stemming, keine Kompositazerlegung) -- ein Trigram-Pendant fuer
-- Chunk-Komposita ist bewusst nicht Teil dieses Issues. chunk_id und paper_id
-- sind regulaere (nicht UNINDEXED) Spalten, damit ein Treffer ohne Zusatz-Join
-- direkt die paper_id liefert.
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
  chunk_id,
  paper_id,
  chunk_text
);

-- FTS5-Trigger: befuellen chunk_fts manuell. Bewusst DROP + CREATE statt
-- CREATE TRIGGER IF NOT EXISTS, siehe Kommentar bei papers_ai oben --
-- init_schema() fuehrt dieses Skript auch auf Bestands-DBs aus.
DROP TRIGGER IF EXISTS chunk_ai;
CREATE TRIGGER chunk_ai AFTER INSERT ON chunk_embeddings BEGIN
  INSERT INTO chunk_fts(rowid, chunk_id, paper_id, chunk_text)
  VALUES (new.rowid, new.chunk_id, new.paper_id, new.chunk_text);
END;

DROP TRIGGER IF EXISTS chunk_ad;
CREATE TRIGGER chunk_ad AFTER DELETE ON chunk_embeddings BEGIN
  DELETE FROM chunk_fts WHERE rowid = old.rowid;
END;

DROP TRIGGER IF EXISTS chunk_au;
CREATE TRIGGER chunk_au AFTER UPDATE OF chunk_text, paper_id ON chunk_embeddings
  WHEN old.chunk_text IS NOT new.chunk_text OR old.paper_id IS NOT new.paper_id
BEGIN
  DELETE FROM chunk_fts WHERE rowid = old.rowid;
  INSERT INTO chunk_fts(rowid, chunk_id, paper_id, chunk_text)
  VALUES (new.rowid, new.chunk_id, new.paper_id, new.chunk_text);
END;
