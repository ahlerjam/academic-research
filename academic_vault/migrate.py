"""migrate.py — Seed-Skript: literature_state.md + PDFs -> SQLite-Vault.

CLI:
    python migrate.py --state literature_state.md --pdf-dir ./pdfs --db vault.db

Parst YAML-Frontmatter-aehnliche Bloecke aus Markdown-Listeneintraegen.
Idempotent (INSERT OR REPLACE via add_paper-Upsert).
"""

import argparse
import json
import re
import sys
from pathlib import Path


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


def apply_pending_migrations(db_path: str) -> None:
    """Buendelt die bekannten additiven Bestands-Migrationshelfer (Issue #368).

    Fuehrt die jeweils fuer sich idempotenten Helfer in fester Reihenfolge aus.
    `VaultDB.init_schema()` ruft diese Funktion ueber ein
    `PRAGMA user_version`-Gate genau einmal pro Schema-Generation auf einer
    Legacy-DB auf; jeder neue Helfer gehoert hier hinein UND braucht seine
    Spalten in `db._LEGACY_MIGRATION_COLUMNS` (Verifikation vor dem Stempeln).

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
    add_note_page_column(db_path)
    add_notes_fts(db_path)
    add_source_kind_column(db_path)
    add_empirical_tables(db_path)
    drop_dead_v64_tables(db_path)


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
        "--limit",
        type=int,
        default=None,
        help="Obergrenze fuer --backfill-fulltext (default: alle)",
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
