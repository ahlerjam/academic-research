"""migrate.py — Seed-Skript: literature_state.md + PDFs -> SQLite-Vault.

CLI:
    python migrate.py --state literature_state.md --pdf-dir ./pdfs --db vault.db

Parst YAML-Frontmatter-aehnliche Bloecke aus Markdown-Listeneintraegen.
Idempotent (INSERT OR REPLACE via add_paper-Upsert).
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_literature_state(state_path: str) -> list[dict]:
    """Parst literature_state.md und gibt Liste von Paper-Dicts zurueck.

    Erwartet Eintraege im Format:
        ### citekey
        - title: ...
        - authors: ...
        - year: ...
        - doi: ...
        - pdf_path: ...

    Alternativ: YAML-Frontmatter-Bloecke zwischen ---
    """
    text = Path(state_path).read_text(encoding="utf-8")
    papers = []

    # Versuch 1: YAML-Frontmatter-Bloecke zwischen ---
    frontmatter_pattern = re.compile(r"---\s*\n(.*?)\n---", re.DOTALL)
    for match in frontmatter_pattern.finditer(text):
        block = match.group(1)
        paper = _parse_yaml_block(block)
        if paper.get("citekey") or paper.get("title"):
            papers.append(paper)

    if papers:
        return papers

    # Versuch 2: Markdown-Sektionen mit ### citekey + Listenwerten
    section_pattern = re.compile(
        r"^#{1,4}\s+(.+?)\s*\n((?:^[ \t]*[-*]\s+\S+.*\n?)*)",
        re.MULTILINE,
    )
    for match in section_pattern.finditer(text):
        citekey = match.group(1).strip()
        body = match.group(2)
        paper = _parse_list_block(body)
        if paper.get("title") or paper.get("doi"):
            paper.setdefault("citekey", citekey)
            papers.append(paper)

    return papers


def _parse_yaml_block(block: str) -> dict:
    """Parst einfaches YAML (kein nested). Gibt dict zurueck."""
    result = {}
    for line in block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _parse_list_block(block: str) -> dict:
    """Parst Markdown-Listenwerte (- key: value)."""
    result = {}
    for line in block.splitlines():
        line = line.strip().lstrip("-*").strip()
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _build_csl_json(paper: dict) -> str:
    """Baut minimales CSL-JSON aus geparsten Feldern."""
    csl: dict = {}
    if paper.get("title"):
        csl["title"] = paper["title"]
    if paper.get("abstract"):
        csl["abstract"] = paper["abstract"]
    if paper.get("year"):
        try:
            csl["issued"] = {"date-parts": [[int(paper["year"])]]}
        except ValueError:
            pass
    if paper.get("authors"):
        raw = paper["authors"]
        names = [n.strip() for n in raw.split(";") if n.strip()]
        csl["author"] = [{"literal": n} for n in names]
    if paper.get("doi"):
        csl["DOI"] = paper["doi"]
    if paper.get("isbn"):
        csl["ISBN"] = paper["isbn"]
    if paper.get("type"):
        csl["type"] = paper["type"]
    return json.dumps(csl, ensure_ascii=False)


def run_migration(
    state_path: str,
    pdf_dir: str,
    db_path: str,
) -> dict:
    """Fuehrt Migration aus. Gibt {inserted, skipped, errors} zurueck."""
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    db.init_schema()

    papers = _parse_literature_state(state_path)
    inserted = 0
    skipped = 0
    errors = 0

    for paper in papers:
        try:
            citekey = paper.get("citekey") or paper.get("title", "unknown")
            paper_id = re.sub(r"[^a-zA-Z0-9_-]", "_", citekey)

            # PDF-Pfad aufloesen
            pdf_path = paper.get("pdf_path")
            if pdf_path:
                candidate = Path(pdf_dir) / pdf_path
                if candidate.exists():
                    pdf_path = str(candidate)
                elif Path(pdf_path).exists():
                    pdf_path = str(Path(pdf_path))
                else:
                    pdf_path = None

            csl_json = _build_csl_json(paper)

            # Idempotenz: paper_id bereits vorhanden?
            existing = db.get_paper(paper_id)
            if existing is not None:
                skipped += 1
                continue

            db.add_paper(
                paper_id=paper_id,
                csl_json=csl_json,
                doi=paper.get("doi"),
                isbn=paper.get("isbn"),
                pdf_path=pdf_path,
            )
            inserted += 1
        except Exception as exc:
            print(f"[ERROR] Paper '{paper.get('citekey', '?')}': {exc}", file=sys.stderr)
            errors += 1

    return {"inserted": inserted, "skipped": skipped, "errors": errors}


def add_book_columns(db_path: str) -> None:
    """Fuegt book/chapter-Spalten zu papers hinzu. Idempotent (try/except pro Spalte).

    Aufruf-Sicher: Kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    new_cols = [
        ("editor", "TEXT"),
        ("chapter", "TEXT"),
        ("page_first", "INTEGER"),
        ("page_last", "INTEGER"),
        ("container_title", "TEXT"),
    ]
    conn = _sqlite3.connect(db_path)
    try:
        for col, coltype in new_cols:
            try:
                conn.execute(f"ALTER TABLE papers ADD COLUMN {col} {coltype}")
            except _sqlite3.OperationalError:
                pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_parent_paper_id_column(db_path: str) -> None:
    """Fuegt parent_paper_id-Spalte zu papers hinzu. Idempotent (try/except).

    Aufruf-Sicher: Kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                "ALTER TABLE papers ADD COLUMN parent_paper_id TEXT REFERENCES papers(paper_id)"
            )
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_provenance_column(db_path: str) -> None:
    """Fuegt provenance-Spalte zu papers hinzu. Idempotent (try/except). (#195)

    Persistiert den Herkunfts-Tag (z.B. "scihub") fuer Provenance-Audits.
    Default NULL fuer bestehende Eintraege. Aufruf-Sicher: kann mehrfach auf
    derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute("ALTER TABLE papers ADD COLUMN provenance TEXT DEFAULT NULL")
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_stance_column(db_path: str) -> None:
    """Fuegt die stance-Spalte zu quotes hinzu. Idempotent (try/except). (#400)

    Haelt die Haltung eines Zitats zur zitierenden Aussage fest
    (`supports`/`contrasts`/`mentions`, siehe ``db.VALID_STANCES``). Der
    CHECK-Constraint wird mit angelegt, damit eine migrierte Bestands-DB
    dieselbe zweite Verteidigungslinie hat wie eine frisch aus ``schema.sql``
    erzeugte. Default NULL fuer bestehende Zitate -- die automatische
    Befuellung per lokaler NLI-Klassifikation ist ein Folge-Issue.
    Aufruf-Sicher: kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                "ALTER TABLE quotes ADD COLUMN stance TEXT "
                "CHECK(stance IN ('supports','contrasts','mentions') OR stance IS NULL)"
            )
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


# CHECK-Constraint auf `quotes.extraction_method` in der von sqlite_master
# gelieferten CREATE-TABLE-SQL. Gruppe 1 ist die reine Werteliste -- der Rebuild
# haengt dort an, statt den ganzen Constraint neu zu schreiben, damit
# abweichende Formatierungen und etwaige Zusatzwerte erhalten bleiben.
_EXTRACTION_METHOD_CHECK_RE = re.compile(
    r"CHECK\s*\(\s*extraction_method\s+IN\s*\(([^)]*)\)\s*\)",
    re.IGNORECASE,
)

# Kopf der CREATE-TABLE-Anweisung fuer `quotes` (optional mit IF NOT EXISTS und
# Quoting), damit der Rebuild die Tabelle unter einem Zwischennamen anlegen kann.
_CREATE_QUOTES_HEAD_RE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?quotes[\"'`\]]?",
    re.IGNORECASE,
)

# Zwischenname waehrend des Tabellen-Rebuilds (Schritt 4-7 der SQLite-Prozedur
# "Making Other Kinds Of Table Schema Changes", lang_altertable.html).
_QUOTES_REBUILD_NAME = "quotes_rebuild_512"


def quotes_check_accepts_local_verbatim(table_sql: str | None) -> bool:
    """Prueft an der CREATE-TABLE-SQL, ob ``'local-verbatim'` erlaubt ist (#512).

    Reine Textfunktion ohne DB-Zugriff, damit der Aufrufer
    (``db.init_schema()``) sie auf seiner bereits offenen Connection nutzen
    kann, statt eine zweite aufzumachen.

    Args:
        table_sql: ``sqlite_master.sql`` der Tabelle ``quotes`` oder ``None``.

    Returns:
        ``True``, wenn der Wert eingefuegt werden darf -- also wenn die Tabelle
        gar nicht existiert, wenn sie keinen CHECK auf ``extraction_method``
        traegt (dann ist jeder Wert erlaubt) oder wenn ``'local-verbatim'``
        bereits in der Werteliste steht.
    """
    if not table_sql:
        return True
    match = _EXTRACTION_METHOD_CHECK_RE.search(table_sql)
    if match is None:
        return True
    return "local-verbatim" in match.group(1)


def widen_extraction_method_check(db_path: str) -> None:
    """Erweitert den CHECK auf ``quotes.extraction_method`` um ``'local-verbatim'``.

    SQLite kann CHECK-Constraints nicht per ``ALTER TABLE`` aendern; noetig ist
    der dokumentierte Tabellen-Rebuild (SQLite-Doku ``lang_altertable.html``,
    "Making Other Kinds Of Table Schema Changes"): ``foreign_keys=OFF``
    ausserhalb der Transaktion -> ``CREATE`` der neuen Tabelle -> ``INSERT ...
    SELECT`` -> ``DROP`` -> ``RENAME`` -> ``PRAGMA foreign_key_check`` ->
    ``COMMIT``. Auf ``quotes`` liegen keine Indizes, Trigger oder Views, die
    nachgebaut werden muessten -- ``codings.quote_id`` referenziert die Tabelle
    aber per Fremdschluessel, deshalb die FK-Pruefung vor dem Commit.

    Die neue Tabellendefinition entsteht aus der BESTEHENDEN
    ``sqlite_master.sql`` (nur die Werteliste des CHECK wird ergaenzt), und die
    Spalten werden ueber ``PRAGMA table_info(quotes)`` dynamisch kopiert. Damit
    ist der Helfer reihenfolgeunabhaengig: laeuft er vor oder nach
    :func:`add_stance_column`, bleibt in beiden Faellen genau der vorgefundene
    Spaltensatz erhalten (Issue #512).

    Idempotent: No-op, wenn ``quotes`` fehlt, keinen CHECK auf
    ``extraction_method`` traegt oder ``'local-verbatim'`` bereits zulaesst.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    # Explizite Transaktionssteuerung: PRAGMA foreign_keys wirkt nur ausserhalb
    # einer offenen Transaktion, und der DROP/RENAME muss atomar mit dem
    # Datentransfer laufen.
    conn.isolation_level = None
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='quotes'"
        ).fetchone()
        table_sql = row[0] if row is not None else None
        if not table_sql or quotes_check_accepts_local_verbatim(table_sql):
            return

        match = _EXTRACTION_METHOD_CHECK_RE.search(table_sql)
        if match is None:  # pragma: no cover -- von der Vorpruefung abgedeckt
            return
        widened_sql = table_sql[: match.end(1)] + ",'local-verbatim'" + table_sql[match.end(1) :]
        head = _CREATE_QUOTES_HEAD_RE.match(widened_sql)
        if head is None:
            logger.warning(
                "quotes-Tabellendefinition nicht als CREATE TABLE erkennbar -- "
                "CHECK-Erweiterung auf 'local-verbatim' uebersprungen (#512)."
            )
            return
        rebuild_sql = f'CREATE TABLE "{_QUOTES_REBUILD_NAME}"' + widened_sql[head.end() :]

        columns = [str(info[1]) for info in conn.execute("PRAGMA table_info(quotes)").fetchall()]
        column_list = ", ".join(f'"{name}"' for name in columns)

        foreign_keys_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.execute("BEGIN")
            conn.execute(f'DROP TABLE IF EXISTS "{_QUOTES_REBUILD_NAME}"')
            conn.execute(rebuild_sql)
            conn.execute(
                f'INSERT INTO "{_QUOTES_REBUILD_NAME}" ({column_list}) '
                f"SELECT {column_list} FROM quotes"
            )
            conn.execute("DROP TABLE quotes")
            conn.execute(f'ALTER TABLE "{_QUOTES_REBUILD_NAME}" RENAME TO quotes')
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                conn.execute("ROLLBACK")
                logger.warning(
                    "CHECK-Erweiterung auf 'local-verbatim' zurueckgerollt: "
                    "PRAGMA foreign_key_check meldet %d Verletzung(en) (#512).",
                    len(violations),
                )
                return
            conn.execute("COMMIT")
        except _sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            if foreign_keys_on:
                conn.execute("PRAGMA foreign_keys=ON")
    finally:
        conn.close()


def add_context_source_column(db_path: str) -> None:
    """Fuegt die context_source-Spalte zu quotes hinzu. Idempotent (try/except). (#520)

    Haelt fest, ob ``context_before``/``context_after`` aus dem echten
    ``paper_fulltext`` stammen (``'fulltext'``, gesetzt von
    ``server.resolve_quote_context()``) oder unbefuellt/modell-generiert sind
    (``NULL``, der Default). Der CHECK-Constraint wird mit angelegt, damit
    eine migrierte Bestands-DB dieselbe zweite Verteidigungslinie hat wie eine
    frisch aus ``schema.sql`` erzeugte.
    Aufruf-Sicher: kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                "ALTER TABLE quotes ADD COLUMN context_source TEXT "
                "CHECK(context_source IN ('fulltext') OR context_source IS NULL)"
            )
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_source_kind_column(db_path: str) -> None:
    """Fuegt die source_kind-Spalte zu papers hinzu. Idempotent (try/except). (#473)

    Unterscheidet eigenes Erhebungsmaterial (``'primary'``) von Literatur
    (``'literature'``, siehe ``db.VALID_SOURCE_KINDS``). Der CHECK-Constraint
    und der NOT-NULL-Default werden mit angelegt, damit eine migrierte
    Bestands-DB dieselbe zweite Verteidigungslinie hat wie eine frisch aus
    ``schema.sql`` erzeugte. Bestehende Paper werden dabei zu
    ``'literature'`` -- das ist die einzig richtige Annahme: alles, was vor
    diesem Feature im Vault lag, war Literatur.
    Aufruf-Sicher: kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                "ALTER TABLE papers ADD COLUMN source_kind TEXT NOT NULL "
                "DEFAULT 'literature' CHECK(source_kind IN ('literature','primary'))"
            )
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_empirical_tables(db_path: str) -> None:
    """Erstellt transcript_segments + codings falls nicht vorhanden. Idempotent. (#473)

    ``schema.sql`` legt beide Tabellen bei jedem ``init_schema()``-Lauf per
    ``CREATE TABLE IF NOT EXISTS`` an; dieser Helfer haelt den Bestands-Pfad
    (``apply_pending_migrations``) vollstaendig, damit eine Legacy-DB nicht
    davon abhaengt, in welcher Reihenfolge DDL und Migration laufen.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcript_segments (
              segment_id TEXT PRIMARY KEY,
              paper_id   TEXT NOT NULL REFERENCES papers(paper_id),
              seq        INTEGER NOT NULL,
              speaker    TEXT,
              timecode   TEXT,
              text       TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              UNIQUE(paper_id, seq)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS codings (
              coding_id       TEXT PRIMARY KEY,
              paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
              segment_id      TEXT REFERENCES transcript_segments(segment_id),
              quote_id        TEXT REFERENCES quotes(quote_id),
              category        TEXT NOT NULL,
              category_origin TEXT NOT NULL
                                CHECK(category_origin IN ('induktiv','deduktiv')),
              memo            TEXT,
              created_at      INTEGER NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def add_figures_table(db_path: str) -> None:
    """Erstellt figures-Tabelle falls nicht vorhanden. Idempotent.

    Aufruf-Sicher: Kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS figures (
              figure_id           TEXT PRIMARY KEY,
              paper_id            TEXT NOT NULL REFERENCES papers(paper_id),
              page                INTEGER,
              caption             TEXT,
              vlm_description     TEXT,
              data_extracted_json TEXT,
              created_at          INTEGER NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


# Tabellen, die frueher zum v6.4-Block gehoerten, aber nie einen Lese- oder
# Schreibpfad bekommen haben (Issue #539). Sie werden weder von `schema.sql`
# noch von `add_v64_tables()` neu angelegt; auf Bestands-DBs raeumt
# `drop_dead_v64_tables()` sie ab. Einzige Fundstelle der Namen im Paket --
# `db.py` importiert die Konstante, statt sie zu duplizieren.
DEAD_TABLES = frozenset({"glossary", "style_overrides"})


def add_v64_tables(db_path: str) -> None:
    """Erstellt v6.4-Tabellen falls nicht vorhanden. Idempotent.

    Tabellen: excluded_sources, risk_of_bias_assessments, score_history,
              vault_locked_status.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS excluded_sources (
              paper_id    TEXT PRIMARY KEY,
              reason      TEXT,
              excluded_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS risk_of_bias_assessments (
              assessment_id      TEXT PRIMARY KEY,
              paper_id           TEXT NOT NULL,
              study_type         TEXT NOT NULL,
              domain_scores_json TEXT NOT NULL,
              ts                 INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS score_history (
              snapshot_id TEXT PRIMARY KEY,
              paper_id    TEXT NOT NULL,
              session_id  TEXT NOT NULL,
              ts          INTEGER NOT NULL,
              scores_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vault_locked_status (
              slug      TEXT PRIMARY KEY,
              locked_at INTEGER NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def drop_dead_v64_tables(db_path: str) -> list[str]:
    """Entfernt die toten v6.4-Tabellen aus einer Bestands-DB (#539). Idempotent.

    Datensicherheit vor Aufraeumen: Eine Tabelle wird nur gedroppt, wenn sie
    leer ist. Enthaelt sie wider Erwarten Zeilen (ueber keinen existierenden
    Schreibpfad erreichbar, aber DROP ist irreversibel), bleibt sie stehen und
    ihr Name wird zurueckgegeben -- `db.init_schema()` verweigert dann den
    `user_version`-Stempel und warnt, statt still Daten zu vernichten.

    Returns:
        Sortierte Namen der Tabellen, die NICHT gedroppt werden konnten.
        Leere Liste = alles sauber (auch bei DBs, die die Tabellen nie hatten).
    """
    import sqlite3 as _sqlite3

    remaining: list[str] = []
    conn = _sqlite3.connect(db_path)
    try:
        for table in sorted(DEAD_TABLES):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists is None:
                continue  # nie angelegt oder bereits gedroppt -- idempotent
            # Tabellennamen sind in SQLite nicht parametrisierbar; die Werte
            # stammen ausschliesslich aus der Modul-Konstante DEAD_TABLES,
            # nie aus Nutzereingaben.
            rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if rows:
                remaining.append(table)
                continue
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    finally:
        conn.close()
    return remaining


def add_note_page_column(db_path: str) -> None:
    """Fuegt die page-Spalte zu notes hinzu. Idempotent (try/except). (#462)

    Optionale Seitenangabe eines Exzerpts. Default NULL fuer bestehende
    Notizen -- eine Seitenangabe ist nie Pflicht (AC2). Aufruf-Sicher: kann
    mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute("ALTER TABLE notes ADD COLUMN page INTEGER")
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_notes_fts(db_path: str) -> None:
    """Legt notes_fts an (falls fehlend) und zieht Bestandsnotizen nach. (#462)

    ``schema.sql`` legt ``notes_fts`` bereits bei jedem ``init_schema()``-Lauf
    an (``CREATE VIRTUAL TABLE IF NOT EXISTS``), aber die Trigger
    ``notes_ai``/``notes_au`` befuellen den Index nur fuer INSERTs/UPDATEs
    *nach* ihrer Erstellung -- Notizen, die schon vor der notes_fts-Einfuehrung
    in ``notes`` lagen, blieben sonst dauerhaft unsichtbar fuer
    ``vault.search_notes()`` (AC4). Der Backfill hier ist idempotent (per
    ``NOT IN`` werden bereits indizierte note_ids uebersprungen), daher
    unproblematisch bei wiederholtem Aufruf ueber das Versions-Gate.
    Aufruf-Sicher: kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts "
                "USING fts5(note_id, paper_id, text, tags)"
            )
            conn.execute(
                """
                INSERT INTO notes_fts (note_id, paper_id, text, tags)
                SELECT note_id, paper_id, text, tags FROM notes
                WHERE note_id NOT IN (SELECT note_id FROM notes_fts)
                """
            )
            conn.commit()
        except _sqlite3.OperationalError:
            pass  # notes_fts fehlt/notes-Tabelle fehlt -- idempotent uebersprungen
    finally:
        conn.close()


def add_papers_trgm_table(db_path: str) -> None:
    """Legt papers_trgm an (falls fehlend) und zieht Bestandspaper nach. (#703)

    ``schema.sql`` legt ``papers_trgm`` bei jedem ``init_schema()``-Lauf an
    (``CREATE VIRTUAL TABLE IF NOT EXISTS``), aber die Trigger
    ``papers_ai``/``papers_au`` befuellen den Teilwort-Index nur fuer
    INSERTs/UPDATEs *nach* ihrer Erstellung -- Paper, die schon vorher in
    ``papers`` lagen, blieben sonst dauerhaft unsichtbar fuer die
    Komposita-Suche. Der Backfill liest dieselben Felder wie die Trigger
    (``json_extract`` auf ``csl_json``) und ist per ``NOT IN`` idempotent,
    daher unproblematisch bei wiederholtem Aufruf ueber das Versions-Gate.

    Verifiziert wird der Helfer ueber ``db._REQUIRED_MIGRATION_TABLES``, bevor
    ``init_schema()`` die neue ``user_version`` stempelt.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS papers_trgm USING fts5("
                "paper_id UNINDEXED, title, abstract, tokenize='trigram')"
            )
            conn.execute(
                """
                INSERT INTO papers_trgm (paper_id, title, abstract)
                SELECT paper_id,
                       json_extract(csl_json, '$.title'),
                       json_extract(csl_json, '$.abstract')
                FROM papers
                WHERE paper_id NOT IN (SELECT paper_id FROM papers_trgm)
                """
            )
            conn.commit()
        except _sqlite3.OperationalError:
            pass  # papers-Tabelle fehlt/FTS5 ohne Trigram -- idempotent uebersprungen
    finally:
        conn.close()


def add_chunk_fts(db_path: str) -> None:
    """Legt chunk_fts an (falls fehlend) und zieht Bestandschunks nach. (#726)

    ``schema.sql`` legt ``chunk_fts`` bei jedem ``init_schema()``-Lauf an
    (``CREATE VIRTUAL TABLE IF NOT EXISTS``), aber die Trigger
    ``chunk_ai``/``chunk_au`` befuellen den Index nur fuer INSERTs/UPDATEs
    *nach* ihrer Erstellung -- Chunks, die schon vor der chunk_fts-Einfuehrung
    in ``chunk_embeddings`` lagen, blieben sonst dauerhaft unsichtbar fuer die
    lexikalische Chunk-Suche (AC3). Der Backfill ist per ``NOT IN`` idempotent
    (bereits indizierte chunk_ids werden uebersprungen), daher unproblematisch
    bei wiederholtem Aufruf ueber das Versions-Gate. Ruehrt ``embedding_vector``
    nicht an -- kein Reindex der Vektoren.

    Verifiziert wird der Helfer ueber ``db._REQUIRED_MIGRATION_TABLES``, bevor
    ``init_schema()`` die neue ``user_version`` stempelt.
    Aufruf-Sicher: kann mehrfach auf derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts "
                "USING fts5(chunk_id, paper_id, chunk_text)"
            )
            conn.execute(
                """
                INSERT INTO chunk_fts (chunk_id, paper_id, chunk_text)
                SELECT chunk_id, paper_id, chunk_text FROM chunk_embeddings
                WHERE chunk_id NOT IN (SELECT chunk_id FROM chunk_fts)
                """
            )
            conn.commit()
        except _sqlite3.OperationalError:
            pass  # chunk_embeddings-Tabelle fehlt -- idempotent uebersprungen
    finally:
        conn.close()


def apply_pending_migrations(db_path: str) -> None:
    """Buendelt die bekannten additiven Bestands-Migrationshelfer (Issue #368).

    Fuehrt die jeweils fuer sich idempotenten Helfer in fester Reihenfolge aus.
    `VaultDB.init_schema()` ruft diese Funktion ueber ein
    `PRAGMA user_version`-Gate genau einmal pro Schema-Generation auf einer
    Legacy-DB auf; jeder neue Helfer gehoert hier hinein UND braucht seine
    Spalten in `db._LEGACY_MIGRATION_COLUMNS` (Verifikation vor dem Stempeln).
    Helfer, die keine Spalte hinzufuegen, brauchen eine eigene Verifikation in
    `db.init_schema()` -- fuer `widen_extraction_method_check()` ist das
    `quotes_check_accepts_local_verbatim()` auf der CHECK-SQL (#512).

    Jeder Helfer oeffnet/schliesst seine eigene kurzlebige `sqlite3`-Connection
    (try/except pro ALTER bzw. `CREATE TABLE IF NOT EXISTS`), daher ist auch
    das wiederholte Ausfuehren dieser Buendel-Funktion sicher.

    Ausnahme von "additiv": `drop_dead_v64_tables()` laeuft als letzter Schritt
    und raeumt die toten Tabellen aus `DEAD_TABLES` ab (#539) -- nur wenn sie
    leer sind. Sein Rueckgabewert wird hier bewusst verworfen; die Verifikation
    vor dem `user_version`-Stempel passiert in `db.init_schema()`.
    """
    add_parent_paper_id_column(db_path)
    add_provenance_column(db_path)
    add_book_columns(db_path)
    add_figures_table(db_path)
    add_v64_tables(db_path)
    add_stance_column(db_path)
    # Nach add_stance_column(): der Rebuild kopiert den vorgefundenen
    # Spaltensatz, also muss `stance` zu diesem Zeitpunkt bereits stehen. Der
    # Helfer ist zwar reihenfolgeunabhaengig (dynamische Spaltenliste), diese
    # Reihenfolge spart aber einen zweiten Tabellendurchlauf (#512).
    widen_extraction_method_check(db_path)
    add_context_source_column(db_path)
    add_note_page_column(db_path)
    add_notes_fts(db_path)
    add_source_kind_column(db_path)
    add_empirical_tables(db_path)
    add_embedding_meta_table(db_path)
    add_paper_tables_table(db_path)
    add_retraction_checked_at_column(db_path)
    add_quote_audit_columns(db_path)
    add_table_values_table(db_path)
    add_papers_trgm_table(db_path)
    add_chunk_fts(db_path)
    drop_dead_v64_tables(db_path)


def add_embedding_meta_table(db_path: str) -> None:
    """Legt ``embedding_meta`` an (Issue #629). Idempotent.

    Haelt fest, mit welchem Modell und in welcher Breite die Vektoren eines
    Vaults entstanden sind. Bewusst OHNE Vorbefuellung: eine Zeile "384, Modell
    unbekannt" waere eine Behauptung ueber einen Bestand, den niemand geprueft
    hat. Fehlt die Zeile, gilt ``DEFAULT_EMBEDDING_DIM`` als Breite und der
    erste Schreibvorgang traegt die tatsaechliche Modell-ID nach
    (``VaultDB.register_embedding_inventory``).

    Verifiziert wird der Helfer ueber ``db._REQUIRED_MIGRATION_TABLES``, bevor
    ``init_schema()`` die neue ``user_version`` stempelt.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_meta (
              id         INTEGER PRIMARY KEY CHECK(id = 1),
              model_id   TEXT,
              dim        INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
        """)
        conn.commit()
    except _sqlite3.OperationalError:
        pass
    finally:
        conn.close()


def add_paper_tables_table(db_path: str) -> None:
    """Erstellt ``paper_tables`` falls nicht vorhanden. Idempotent. (#630)

    Rein additiv: kein FTS5-Trigger wird angefasst, ``paper_fulltext`` bleibt
    unberuehrt. Wie bei ``add_empirical_tables`` legt ``schema.sql`` die Tabelle
    ohnehin bei jedem ``init_schema()``-Lauf an; dieser Helfer haelt den
    Bestands-Pfad (``apply_pending_migrations``) unabhaengig von der Reihenfolge
    aus DDL und Migration vollstaendig.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        conn.execute("""
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
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_tables_paper ON paper_tables(paper_id)")
        conn.commit()
    finally:
        conn.close()


def add_table_values_table(db_path: str) -> None:
    """Erstellt ``table_values`` falls nicht vorhanden. Idempotent. (#741)

    Rein additiv, analog ``add_paper_tables_table``: ``schema.sql`` legt die
    Tabelle ohnehin bei jedem ``init_schema()``-Lauf an; dieser Helfer haelt
    den Bestands-Pfad (``apply_pending_migrations``) unabhaengig von der
    Reihenfolge aus DDL und Migration vollstaendig.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        conn.execute("""
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
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_table_values_paper ON table_values(paper_id)")
        conn.commit()
    finally:
        conn.close()


def add_retraction_checked_at_column(db_path: str) -> None:
    """Fuegt retraction_checked_at-Spalte zu papers hinzu. Idempotent. (#604)

    Haelt fest, wann ein Paper zuletzt auf Crossref-Retraction geprueft wurde
    -- Grundlage fuer den "nur unzureichend geprueft erneut abfragen"-Filter
    von ``server.check_retractions()``. Default NULL fuer bestehende
    Eintraege (noch nie geprueft). Aufruf-sicher: kann mehrfach auf
    derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute("ALTER TABLE papers ADD COLUMN retraction_checked_at INTEGER DEFAULT NULL")
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_quote_audit_columns(db_path: str) -> None:
    """Fuegt audited_at/audit_verdict/audit_severity zu quotes hinzu. Idempotent. (#737)

    Audit-Historie, additiv zu ``stance`` (siehe Kommentar in ``schema.sql``):
    ``audited_at`` ist NULL, solange kein Audit stattgefunden hat -- das ist
    die einzige verlaessliche Unterscheidung zwischen "nie geprueft" und
    "geprueft und unauffaellig" (``faithful``, ``audit_severity`` bleibt dann
    ebenfalls NULL). Die CHECK-Constraints werden mit angelegt, damit eine
    migrierte Bestands-DB dieselbe zweite Verteidigungslinie hat wie eine
    frisch aus ``schema.sql`` erzeugte. Aufruf-sicher: kann mehrfach auf
    derselben DB ausgefuehrt werden.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        try:
            conn.execute("ALTER TABLE quotes ADD COLUMN audited_at INTEGER")
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        try:
            conn.execute(
                "ALTER TABLE quotes ADD COLUMN audit_verdict TEXT CHECK(audit_verdict IN "
                "('faithful','overstated','context-stripped','polarity-flip','unsupported') "
                "OR audit_verdict IS NULL)"
            )
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        try:
            conn.execute(
                "ALTER TABLE quotes ADD COLUMN audit_severity TEXT "
                "CHECK(audit_severity IN ('kritisch','hoch','mittel') OR audit_severity IS NULL)"
            )
        except _sqlite3.OperationalError:
            pass  # Spalte existiert bereits -- idempotent
        conn.commit()
    finally:
        conn.close()


def add_chunk_vectors_table(db_path: str) -> int:
    """Legt die vec0-Tabelle ``chunk_vectors`` an und spiegelt Bestandsvektoren.

    Idempotent. Ohne ladbare sqlite-vec-Extension ein No-op (Rueckgabe 0) — die
    KNN-Suche laeuft dann ueber den Python-Fallback in ``VaultDB.knn_chunks``.
    Gibt die Anzahl gespiegelter Vektoren zurueck (Issue #372).
    """
    from academic_vault.db import VaultDB

    return VaultDB(db_path).sync_chunk_vectors()


def add_fulltext_support(db_path: str) -> None:
    """Ruestet eine Bestands-DB auf den Volltext-Index um (Issue #373). Idempotent.

    Legt ``paper_fulltext`` an und ersetzt die FTS5-Trigger, die ``fulltext``
    zuvor hart auf ``NULL`` geschrieben haben, durch die Subselect-Variante aus
    ``schema.sql``. ``papers`` bleibt unangetastet.
    """
    from academic_vault.db import VaultDB

    VaultDB(db_path).init_schema()


def backfill_fulltext(
    db_path: str,
    limit: int | None = None,
    backend: str = "auto",
) -> dict:
    """Extrahiert den Volltext aller Paper, die noch keinen haben (Issue #373).

    Idempotent: verarbeitet nur Paper mit ``pdf_path``, die noch keine Zeile in
    ``paper_fulltext`` haben. Schreibt ausschliesslich nach ``paper_fulltext``
    und ``papers_fts`` — ``papers`` (inkl. ``updated_at``) und ``quotes``
    bleiben unveraendert.

    Args:
        db_path: Pfad zur Vault-DB.
        limit: Maximale Anzahl Paper pro Lauf (``None`` = alle).
        backend: Extraktions-Backend, siehe ``fulltext.extract_fulltext``.

    Returns:
        ``{"filled": int, "skipped": int, "errors": int}``. ``skipped`` zaehlt
        PDFs ohne Text-Layer (Scans), ``errors`` fehlende/defekte Dateien.
    """
    from academic_vault.db import VaultDB
    from academic_vault.fulltext import extract_fulltext

    db = VaultDB(db_path)
    filled = 0
    skipped = 0
    errors = 0

    for candidate in db.papers_missing_fulltext(limit=limit):
        paper_id = candidate["paper_id"]
        pdf_path = candidate["pdf_path"]
        try:
            text, extractor = extract_fulltext(pdf_path, backend=backend)
        except Exception as exc:
            print(f"[ERROR] Volltext '{paper_id}': {exc}", file=sys.stderr)
            errors += 1
            continue
        if not text:
            skipped += 1
            continue
        if db.set_fulltext(paper_id, text, extractor):
            filled += 1
        else:  # pragma: no cover - text ist hier nachweislich nicht leer
            skipped += 1

    return {"filled": filled, "skipped": skipped, "errors": errors}


def backfill_quote_embeddings(
    db_path: str,
    limit: int | None = None,
    embedder: object | None = None,
) -> dict:
    """Erzeugt Embeddings fuer Bestands-Quotes ohne Eintrag in ``quote_embeddings`` (#521).

    Idempotent: verarbeitet nur Quotes, die noch keine Zeile in
    ``quote_embeddings`` haben (:meth:`academic_vault.db.VaultDB.quotes_missing_embedding`).
    Ein zweiter Lauf direkt danach findet keine Kandidaten mehr und schreibt
    nichts. Ohne ladbare sqlite-vec-Extension oder ohne Embedding-Backend ist
    der Lauf ein sauberes No-op (``skipped == len(quotes)``, kein Absturz) --
    fuer Quotes gibt es anders als bei Chunks keinen BLOB-Fallback-Speicher.

    Args:
        db_path: Pfad zur Vault-DB.
        limit: Maximale Anzahl Quotes pro Lauf (``None`` = alle).
        embedder: Embedder-Instanz. ``None`` = ``get_embedder()`` (Tests
            injizieren hier den deterministischen ``fake_embedder``).

    Returns:
        ``{"embedded": int, "skipped": int}``. ``skipped`` zaehlt Quotes, fuer
        die :func:`academic_vault.server.embed_quote` ``False`` zurueckgab
        (Degradationspfad).
    """
    from academic_vault.db import VaultDB
    from academic_vault.server import embed_quote

    db = VaultDB(db_path)
    embedded = 0
    skipped = 0

    for candidate in db.quotes_missing_embedding(limit=limit):
        if embed_quote(db_path, candidate["quote_id"], embedder=embedder):
            embedded += 1
        else:
            skipped += 1

    return {"embedded": embedded, "skipped": skipped}


def reindex_embeddings(
    db_path: str,
    embedder: object | None = None,
    batch_size: int = 128,
) -> dict:
    """Rechnet alle Vektoren eines Vaults mit dem aktuellen Modell neu (Issue #629).

    Der Weg, den ein Modellwechsel braucht: ``chunk_embeddings.embedding_vector``
    und ``quote_embeddings`` werden aus den gespeicherten Texten
    (``embedding_text`` bzw. ``verbatim`` + Kontext) neu berechnet, die
    vec0-Tabellen in der neuen Breite angelegt und ``embedding_meta``
    fortgeschrieben.

    Unterschied zu :func:`backfill_quote_embeddings`: dort werden nur Luecken
    gefuellt, hier wird der GESAMTE Bestand ersetzt. Ein Vault, der vor #629
    mit zwei Modellen befuellt wurde, traegt sonst weiter Vektoren aus dem
    alten Raum -- und die faenden sich in keiner Suche wieder, ohne dass es
    auffiele.

    Reihenfolge (Plan-Risiko 3+5): zuerst der Lock-Check, dann die Berechnung,
    erst danach DROP + CREATE der vec0-Tabellen. ``quote_embeddings`` hat keine
    BLOB-Basistabelle -- ein Abbruch nach dem Drop haette die Vektoren
    nirgends mehr, die Quelle (``quotes``) bleibt aber vollstaendig erhalten,
    ein erneuter Lauf stellt sie also wieder her.

    Args:
        db_path: Pfad zur Vault-DB.
        embedder: Embedder-Instanz. ``None`` = ``get_embedder()``.
        batch_size: Chunks pro Embedding-Aufruf (haelt den Speicher beschraenkt).

    Returns:
        ``{"chunks": int, "quotes": int, "dim": int, "model_id": str | None,
        "skipped_quotes": int}``.

    Raises:
        RuntimeError: kein Embedding-Backend verfuegbar.
        VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
    """
    from academic_vault.db import VaultDB
    from academic_vault.embedding_model import get_embedder, serialize_f32
    from academic_vault.server import _quote_embedding_text

    db = VaultDB(db_path)
    db.init_schema()

    active = embedder if embedder is not None else get_embedder()
    if active is None:
        raise RuntimeError(
            "Re-Index nicht moeglich: kein Embedding-Backend verfuegbar. "
            "sentence-transformers installieren bzw. VAULT_EMBEDDING_MODEL pruefen (#629)."
        )
    dim = int(active.dim)  # type: ignore[attr-defined]
    model_id = getattr(active, "model_id", None)

    # Lock-Check VOR jeder Aenderung: ein gesperrter Vault darf nicht halb
    # abgeraeumt zurueckbleiben.
    db.raise_if_locked()

    chunks = [
        (row["chunk_id"], row["embedding_text"])
        for row in db.all_chunk_embedding_texts()
        if (row["embedding_text"] or "").strip()
    ]
    vectors: list[tuple[str, bytes]] = []
    for start in range(0, len(chunks), max(batch_size, 1)):
        batch = chunks[start : start + max(batch_size, 1)]
        embedded = active.embed_documents([text for _, text in batch])  # type: ignore[attr-defined]
        vectors.extend(
            (chunk_id, serialize_f32(vector))
            for (chunk_id, _), vector in zip(batch, embedded, strict=True)
        )

    db.replace_chunk_vectors(vectors, model_id=model_id, dim=dim)

    quotes = 0
    skipped_quotes = 0
    for quote in db.all_quotes_for_embedding():
        vector = active.embed_documents([_quote_embedding_text(quote)])  # type: ignore[attr-defined]
        if not vector:
            skipped_quotes += 1
            continue
        if db.add_quote_embedding(quote["quote_id"], serialize_f32(vector[0])):
            quotes += 1
        else:
            # Ohne ladbare sqlite-vec-Extension gibt es fuer Quotes keinen
            # Speicher -- das ist ein bekannter Degradationspfad (#521), kein
            # Fehler des Re-Index.
            skipped_quotes += 1

    return {
        "chunks": len(vectors),
        "quotes": quotes,
        "skipped_quotes": skipped_quotes,
        "dim": dim,
        "model_id": model_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed-Migration: literature_state.md -> academic_vault SQLite"
    )
    parser.add_argument(
        "--state",
        help="Pfad zur literature_state.md (Pflicht ausser bei --backfill-fulltext)",
    )
    parser.add_argument(
        "--backfill-fulltext",
        action="store_true",
        help="Statt der Seed-Migration: PDF-Volltexte fuer Bestands-Paper nachtragen (#373)",
    )
    parser.add_argument(
        "--backfill-quote-embeddings",
        action="store_true",
        help="Statt der Seed-Migration: Embeddings fuer Bestands-Quotes ohne "
        "quote_embeddings-Eintrag nachtragen (#521)",
    )
    parser.add_argument(
        "--reindex-embeddings",
        action="store_true",
        help="Statt der Seed-Migration: alle Vektoren mit dem aktuell konfigurierten "
        "Modell (VAULT_EMBEDDING_MODEL) neu berechnen und die Spaltenbreite anpassen "
        "-- noetig nach einem Modellwechsel (#629)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Obergrenze fuer --backfill-fulltext/--backfill-quote-embeddings (default: alle)",
    )
    parser.add_argument(
        "--pdf-dir",
        default=".",
        help="Verzeichnis mit PDF-Dateien (default: .)",
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Pfad zur SQLite-Vault-Datenbank",
    )
    args = parser.parse_args()

    if args.backfill_fulltext:
        if not Path(args.db).exists():
            print(f"[ERROR] Vault-DB nicht gefunden: {args.db}", file=sys.stderr)
            sys.exit(1)
        add_fulltext_support(args.db)
        stats = backfill_fulltext(args.db, limit=args.limit)
        print(
            f"Volltext-Backfill abgeschlossen: "
            f"filled={stats['filled']}, "
            f"skipped={stats['skipped']}, "
            f"errors={stats['errors']}"
        )
        return

    if args.backfill_quote_embeddings:
        if not Path(args.db).exists():
            print(f"[ERROR] Vault-DB nicht gefunden: {args.db}", file=sys.stderr)
            sys.exit(1)
        from academic_vault.db import VaultDB

        VaultDB(args.db).init_schema()
        stats = backfill_quote_embeddings(args.db, limit=args.limit)
        print(
            f"Quote-Embedding-Backfill abgeschlossen: "
            f"embedded={stats['embedded']}, "
            f"skipped={stats['skipped']}"
        )
        return

    if args.reindex_embeddings:
        if not Path(args.db).exists():
            print(f"[ERROR] Vault-DB nicht gefunden: {args.db}", file=sys.stderr)
            sys.exit(1)
        stats = reindex_embeddings(args.db)
        print(
            f"Re-Index abgeschlossen: "
            f"model={stats['model_id']}, "
            f"dim={stats['dim']}, "
            f"chunks={stats['chunks']}, "
            f"quotes={stats['quotes']}, "
            f"skipped_quotes={stats['skipped_quotes']}"
        )
        return

    if not args.state:
        print("[ERROR] --state ist ohne --backfill-fulltext Pflicht", file=sys.stderr)
        sys.exit(1)

    if not Path(args.state).exists():
        print(f"[ERROR] state-Datei nicht gefunden: {args.state}", file=sys.stderr)
        sys.exit(1)

    result = run_migration(args.state, args.pdf_dir, args.db)
    print(
        f"Migration abgeschlossen: "
        f"inserted={result['inserted']}, "
        f"skipped={result['skipped']}, "
        f"errors={result['errors']}"
    )


if __name__ == "__main__":
    main()
