-- academic_vault SQLite Schema
-- Tabellen: papers, papers_fts, paper_fulltext, quotes, quote_embeddings,
--           decisions, notes, notes_fts
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
                          CHECK(source_kind IN ('literature','primary'))
);

-- FTS5 als eigenstaendige virtuelle Tabelle (kein content=, manuell befuellt).
-- Trigger halten papers_fts synchron mit papers.
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
  paper_id,
  title,
  abstract,
  fulltext
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
  context_source    TEXT CHECK(context_source IN ('fulltext') OR context_source IS NULL)
);

-- vec0 Virtual Tables: optional, nur wenn sqlite-vec Extension geladen ist.
-- Werden in db.py per try/except erstellt (quote_embeddings + chunk_vectors,
-- letztere als Spiegel der chunk_embeddings-Vektoren, Issue #372).
-- CREATE VIRTUAL TABLE IF NOT EXISTS quote_embeddings USING vec0(
--   quote_id TEXT PRIMARY KEY,
--   embedding FLOAT[384]
-- );
-- CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
--   chunk_id TEXT PRIMARY KEY,
--   embedding FLOAT[384]
-- );

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

-- FTS5-Trigger: befuellen papers_fts manuell via json_extract.
-- Bewusst DROP + CREATE statt CREATE TRIGGER IF NOT EXISTS: init_schema() fuehrt
-- dieses Skript auch auf Bestands-DBs aus; mit IF NOT EXISTS behielten die
-- ihre alten Trigger (fulltext hart NULL) und der Volltext-Index bliebe leer.
DROP TRIGGER IF EXISTS papers_ai;
CREATE TRIGGER papers_ai AFTER INSERT ON papers BEGIN
  INSERT INTO papers_fts(paper_id, title, abstract, fulltext)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract'),
    (SELECT text FROM paper_fulltext WHERE paper_id = new.paper_id)
  );
END;

DROP TRIGGER IF EXISTS papers_ad;
CREATE TRIGGER papers_ad AFTER DELETE ON papers BEGIN
  DELETE FROM papers_fts WHERE paper_id = old.paper_id;
END;

DROP TRIGGER IF EXISTS papers_au;
CREATE TRIGGER papers_au AFTER UPDATE ON papers BEGIN
  DELETE FROM papers_fts WHERE paper_id = old.paper_id;
  INSERT INTO papers_fts(paper_id, title, abstract, fulltext)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract'),
    (SELECT text FROM paper_fulltext WHERE paper_id = new.paper_id)
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
