-- academic_vault SQLite Schema
-- Tabellen: papers, papers_fts, paper_fulltext, quotes, quote_embeddings,
--           decisions, notes
-- FTS5-Trigger: papers_ai, papers_ad, papers_au

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
  updated_at            INTEGER NOT NULL
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
  extraction_method TEXT NOT NULL CHECK(extraction_method IN ('citations-api','manual')),
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
  stance            TEXT CHECK(stance IN ('supports','contrasts','mentions') OR stance IS NULL)
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
  created_at INTEGER NOT NULL
);

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

CREATE TABLE IF NOT EXISTS glossary (
  term        TEXT PRIMARY KEY,
  definition  TEXT NOT NULL,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS style_overrides (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

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
