"""VaultDB — SQLite-Datenbankschicht fuer academic_vault.

Context-Manager-Klasse mit sqlite-vec-Fallback und FTS5-Volltext-Suche.
"""

import contextlib
import json
import math
import os
import re
import sqlite3
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import uuid4

from .embedding_model import EMBEDDING_DIM, deserialize_f32, serialize_f32

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# vec0-Spiegel der chunk_embeddings-Vektoren (Issue #372). Die DDL steht hier
# statt in schema.sql, weil sie die geladene sqlite-vec-Extension voraussetzt.
_CHUNK_VECTORS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
    f"USING vec0(chunk_id TEXT PRIMARY KEY, embedding FLOAT[{EMBEDDING_DIM}])"
)

VALID_PAPER_TYPES = frozenset({"article-journal", "book", "chapter"})


class VaultLockedError(RuntimeError):
    """Material-Passport ist gesperrt -- Schreiboperation wurde verweigert.

    Wird geworfen sobald ein Eintrag in ``vault_locked_status`` existiert
    (siehe ``VaultDB._raise_if_locked``, Issue #380).
    """


# Typ-Alias-Map fuer Figure-Referenzen (Issue #379): alle Schreibweisen
# normalisieren auf "figure" bzw. "table", damit In-Text-Label
# ("Abb. 3.4") und Caption ("Abbildung 3.4: ...") strukturiert statt per
# Freitext-Teilstring verglichen werden koennen.
_FIGURE_REF_TYPE_ALIASES = {
    "abb": "figure",
    "abbildung": "figure",
    "fig": "figure",
    "figure": "figure",
    "tab": "table",
    "tabelle": "table",
}

_FIGURE_REF_RE = re.compile(
    r"\b(Abb|Abbildung|Fig|Figure|Tab|Tabelle)\.?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _parse_figure_reference(text: str) -> tuple[str, str] | None:
    """Parst Referenz-/Caption-Text in ``(kind, number)``.

    ``kind`` ist ``"figure"`` oder ``"table"`` (normalisiert ueber die
    Typ-Alias-Map), ``number`` das Nummern-Label als String (z. B. ``"3.4"``).
    Gibt ``None`` zurueck, wenn kein Typ+Nummer-Muster gefunden wird.
    """
    match = _FIGURE_REF_RE.search(text)
    if match is None:
        return None
    kind = _FIGURE_REF_TYPE_ALIASES[match.group(1).lower()]
    number = match.group(2)
    return (kind, number)


# Escape-Zeichen fuer LIKE-Patterns (siehe escape_like / ESCAPE-Klauseln unten).
_LIKE_ESCAPE_CHAR = "\\"


def escape_like(value: str) -> str:
    """Escaped LIKE-Wildcards (``%`` und ``_``) sowie das Escape-Zeichen selbst.

    SQLite-LIKE behandelt ``%`` und ``_`` als Wildcards. Ohne Escaping veraendert
    User-Input mit diesen Zeichen das Suchverhalten still. Mit dem Rueckgabewert
    laesst sich ein literales LIKE-Pattern bauen, das per ``ESCAPE '\\'`` an die
    Query gebunden wird. Backslash muss zuerst escaped werden, damit die spaeter
    eingefuegten Escape-Backslashes nicht doppelt escaped werden.
    """
    return (
        value.replace(_LIKE_ESCAPE_CHAR, _LIKE_ESCAPE_CHAR * 2)
        .replace("%", _LIKE_ESCAPE_CHAR + "%")
        .replace("_", _LIKE_ESCAPE_CHAR + "_")
    )


def project_slug(cwd: str | None = None) -> str:
    """Kanonischer Projekt-Slug fuer den DB-Pfad: basename(CLAUDE_PROJECT_DIR || CWD).

    Eine einzige Quelle der Wahrheit (Issue #190). Hooks (hooks/verbatim-guard.mjs)
    und MCP-Server muessen denselben Algorithmus verwenden, damit alle
    Komponenten gegen dieselbe vault.db schreiben.

    Praezedenz (Issue #365 -- muss mit hooks/verbatim-guard.mjs:34 uebereinstimmen):
      1. Expliziter ``cwd``-Parameter (Escape-Hatch fuer bestehende Aufrufer/Tests).
      2. ``CLAUDE_PROJECT_DIR``-Umgebungsvariable, falls gesetzt.
      3. ``Path.cwd()``.
    """
    if cwd is not None:
        base = Path(cwd)
    else:
        env_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(env_project_dir) if env_project_dir else Path.cwd()
    return base.name or "default"


def default_db_path() -> str:
    """Kanonischer Default-Pfad zur vault.db (Single Source of Truth, Issue #190).

    Reihenfolge:
      1. Falls ``VAULT_DB_PATH`` gesetzt ist, wird dieser Pfad verwendet.
      2. Sonst ``~/.academic-research/projects/<slug>/vault.db`` mit
         ``slug = basename(CWD)``.

    Bewusst NICHT das CWD direkt ("vault.db") und NICHT das Plugin-Verzeichnis
    (``CLAUDE_PLUGIN_ROOT``/``REPO_ROOT``), um Datenverlust bei Plugin-Updates
    und das versehentliche Committen von Forschungs-PII zu vermeiden (CWE-538).
    """
    env = os.environ.get("VAULT_DB_PATH")
    if env:
        return env
    return str(Path.home() / ".academic-research" / "projects" / project_slug() / "vault.db")


class VaultDB:
    """SQLite-Datenbankzugriff fuer den academic_vault MCP-Server."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.vec_available: bool = False
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Context-Manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "VaultDB":
        self._conn = self._open(self.db_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn is None:
            return
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()
        self._conn = None

    # ------------------------------------------------------------------
    # Schema-Initialisierung
    # ------------------------------------------------------------------

    @staticmethod
    def _open(db_path: str) -> sqlite3.Connection:
        """Oeffnet eine neue Verbindung mit Standard-Pragmas.

        Legt das Elternverzeichnis von ``db_path`` an, falls es noch nicht
        existiert (Issue #365): ``~/.academic-research/projects/<slug>/``
        wird von keiner anderen Komponente vorab erzeugt, daher scheiterte
        jeder erste Schreibzugriff eines neuen Projekt-Slugs bislang mit
        ``sqlite3.OperationalError: unable to open database file``.
        In-Memory-DBs (":memory:") haben kein Elternverzeichnis und werden
        uebersprungen.
        """
        if db_path != ":memory:":
            parent = Path(db_path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        """Gibt bestehende oder neue Verbindung zurueck."""
        if self._conn is not None:
            return self._conn
        return self._open(self.db_path)

    @contextlib.contextmanager
    def _connection(self, commit: bool = False) -> Iterator[sqlite3.Connection]:
        """Stellt eine Connection bereit und schliesst sie garantiert.

        Verhindert SQLite-Connection-Leaks bei Exceptions (Issue #237). Wird die
        Connection in dieser Methode selbst geoeffnet (``self._conn is None``,
        also ausserhalb des Context-Managers), so wird sie im ``finally``-Block
        immer geschlossen — auch wenn ``conn.execute()`` z. B. einen
        ``IntegrityError`` wirft. Bei ``commit=True`` wird im Erfolgsfall vorher
        committet. Eine geteilte Connection (``self._conn`` gesetzt) wird hier
        weder committet noch geschlossen; das uebernimmt ``__exit__``.

        Args:
            commit: Bei True wird die selbst geoeffnete Connection im Erfolgsfall
                committet (fuer write-Methoden).
        """
        own_conn = self._conn is None
        conn = self._get_conn()
        try:
            yield conn
            if own_conn and commit:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def load_vec_extension(self, conn: sqlite3.Connection | None = None) -> bool:
        """Versucht sqlite_vec Extension zu laden. Gibt True bei Erfolg zurueck.

        Default-Ladepfad ist ``sqlite_vec.loadable_path()`` (das pip-installierte
        Wheel liefert die Dylib an einem Paketpfad aus, den ein Bare-Name-Load
        ``load_extension("sqlite_vec")`` nie findet, Issue #371).
        ``SQLITE_VEC_PATH`` ist nur noch ein Override fuer Custom-Builds.

        Python-Builds ohne ``--enable-loadable-sqlite-extensions`` (z.B. das
        macOS-System-Python und die macOS-Builds von actions/setup-python)
        haben ``enable_load_extension`` nicht bzw. werfen beim Aufruf. Dann ist
        die Vektor-Suche schlicht nicht verfuegbar (optionales Feature) und
        ``vec_available`` bleibt False — der Rest des Vault funktioniert weiter.
        """
        vec_path = os.environ.get("SQLITE_VEC_PATH", "")
        target = conn if conn is not None else self._get_conn()

        if not hasattr(target, "enable_load_extension"):
            self.vec_available = False
            return False

        try:
            target.enable_load_extension(True)
        except (AttributeError, sqlite3.OperationalError, sqlite3.NotSupportedError):
            self.vec_available = False
            return False

        try:
            if vec_path:
                target.load_extension(vec_path)
            else:
                import sqlite_vec

                target.load_extension(sqlite_vec.loadable_path())
            self.vec_available = True
        except Exception:
            self.vec_available = False
        finally:
            try:
                target.enable_load_extension(False)
            except Exception:
                pass
        return self.vec_available

    def init_schema(self) -> None:
        """Erstellt alle Tabellen gemaess schema.sql. Versucht vec0 zu erstellen."""
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connection(commit=True) as conn:
            # vec-Extension auf derselben Connection laden (optional)
            self.load_vec_extension(conn)

            # Basis-Schema ausfuehren (ohne vec0-Block — der ist auskommentiert)
            conn.executescript(ddl)

            # quote_embeddings via vec0 versuchen (nur wenn Extension geladen)
            if self.vec_available:
                try:
                    conn.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS quote_embeddings "
                        "USING vec0(quote_id TEXT PRIMARY KEY, embedding FLOAT[384])"
                    )
                    conn.execute(_CHUNK_VECTORS_DDL)
                except sqlite3.OperationalError:
                    self.vec_available = False

    # ------------------------------------------------------------------
    # Papers CRUD
    # ------------------------------------------------------------------

    def add_paper(
        self,
        paper_id: str,
        csl_json: str,
        doi: str | None = None,
        isbn: str | None = None,
        pdf_path: str | None = None,
        page_offset: int = 0,
        editor: str | None = None,
        chapter: str | None = None,
        page_first: int | None = None,
        page_last: int | None = None,
        container_title: str | None = None,
        parent_paper_id: str | None = None,
        provenance: str | None = None,
    ) -> None:
        """Upsert eines Papers in die papers-Tabelle.

        type wird aus csl_json extrahiert. Erlaubte Werte: article-journal, book, chapter.

        provenance: Herkunfts-Tag (z.B. "scihub", "oa") fuer Audit-Zwecke (#195).

        Malformed JSON wird NICHT mehr stillschweigend zu 'article-journal'
        defaulted (Issue #213, Security Round-2 M3), sondern als ValueError
        gemeldet. Fehlt das Feld 'type' komplett, gilt weiterhin der
        DB-Default 'article-journal'.
        """
        try:
            csl = json.loads(csl_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"csl_json ist kein valides JSON: {exc}") from exc
        if not isinstance(csl, dict):
            raise ValueError("csl_json muss ein JSON-Objekt sein.")
        paper_type = csl.get("type", "article-journal")

        if paper_type not in VALID_PAPER_TYPES:
            raise ValueError(
                f"Ungueltiger type '{paper_type}' -- erlaubt: {sorted(VALID_PAPER_TYPES)}"
            )

        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO papers
                  (paper_id, type, csl_json, doi, isbn, pdf_path, page_offset,
                   editor, chapter, page_first, page_last, container_title,
                   parent_paper_id, provenance,
                   added_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                  type            = excluded.type,
                  csl_json        = excluded.csl_json,
                  doi             = excluded.doi,
                  isbn            = excluded.isbn,
                  pdf_path        = excluded.pdf_path,
                  page_offset     = excluded.page_offset,
                  editor          = excluded.editor,
                  chapter         = excluded.chapter,
                  page_first      = excluded.page_first,
                  page_last       = excluded.page_last,
                  container_title = excluded.container_title,
                  parent_paper_id = excluded.parent_paper_id,
                  provenance      = excluded.provenance,
                  updated_at      = excluded.updated_at
                """,
                (
                    paper_id,
                    paper_type,
                    csl_json,
                    doi,
                    isbn,
                    pdf_path,
                    page_offset,
                    editor,
                    chapter,
                    page_first,
                    page_last,
                    container_title,
                    parent_paper_id,
                    provenance,
                    now,
                    now,
                ),
            )

    def get_paper(self, paper_id: str) -> dict | None:
        """Gibt Paper-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def set_file_id(self, paper_id: str, file_id: str, expires_at: int) -> None:
        """Setzt file_id und file_id_expires_at fuer ein Paper."""
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET file_id = ?, file_id_expires_at = ?, updated_at = ? "
                "WHERE paper_id = ?",
                (file_id, expires_at, int(time.time()), paper_id),
            )

    def set_page_offset(self, paper_id: str, offset: int) -> None:
        """Setzt page_offset fuer ein Paper."""
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET page_offset = ?, updated_at = ? WHERE paper_id = ?",
                (offset, int(time.time()), paper_id),
            )

    def get_page_offset(self, paper_id: str) -> int:
        """Gibt page_offset fuer ein Paper zurueck. Fallback: 0."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT page_offset FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        if row is None:
            return 0
        return int(row["page_offset"] or 0)

    def list_papers_by_provenance(self, provenance: str) -> list[dict]:
        """Gibt alle Papers mit dem angegebenen provenance-Tag zurueck (Audit, #195).

        Beispiel: ``list_papers_by_provenance("scihub")`` liefert alle aus dem
        SciHub-Tier bezogenen Papers fuer ein Provenance-Audit.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE provenance = ? ORDER BY added_at",
                (provenance,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Quotes CRUD
    # ------------------------------------------------------------------

    def add_quote(
        self,
        quote_id: str,
        paper_id: str,
        verbatim: str,
        extraction_method: str,
        api_response_id: str | None = None,
        pdf_page: int | None = None,
        printed_page: int | None = None,
        section: str | None = None,
        context_before: str | None = None,
        context_after: str | None = None,
    ) -> None:
        """INSERT eines Quotes in die quotes-Tabelle."""
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO quotes
                  (quote_id, paper_id, verbatim, pdf_page, printed_page,
                   section, context_before, context_after,
                   extraction_method, api_response_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote_id,
                    paper_id,
                    verbatim,
                    pdf_page,
                    printed_page,
                    section,
                    context_before,
                    context_after,
                    extraction_method,
                    api_response_id,
                    now,
                ),
            )

    def get_quote(self, quote_id: str) -> dict | None:
        """Gibt Quote-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
        return dict(row) if row is not None else None

    def search_quote_text(self, verbatim: str, k: int = 5) -> list[dict]:
        """LIKE-Suche in quotes.verbatim. Gibt [{quote_id, verbatim, paper_id}] zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quote_id, verbatim, paper_id FROM quotes "
                "WHERE verbatim LIKE ? ESCAPE '\\' LIMIT ?",
                (f"%{escape_like(verbatim)}%", k),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_quotes(
        self,
        paper_id: str,
        query: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Suche Quotes fuer ein Paper, optional per verbatim-LIKE-Filter."""
        with self._connection() as conn:
            if query:
                rows = conn.execute(
                    "SELECT * FROM quotes WHERE paper_id = ? "
                    "AND verbatim LIKE ? ESCAPE '\\' LIMIT ?",
                    (paper_id, f"%{escape_like(query)}%", k),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM quotes WHERE paper_id = ? LIMIT ?",
                    (paper_id, k),
                ).fetchall()
        return [dict(r) for r in rows]

    def set_ocr_done(self, paper_id: str, value: int = 1) -> None:
        """Setzt ocr_done-Flag fuer ein Paper."""
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET ocr_done = ?, updated_at = ? WHERE paper_id = ?",
                (value, int(time.time()), paper_id),
            )

    def update_pdf_path(self, paper_id: str, new_path: str) -> None:
        """Aktualisiert pdf_path fuer ein Paper."""
        with self._connection(commit=True) as conn:
            conn.execute(
                "UPDATE papers SET pdf_path = ?, updated_at = ? WHERE paper_id = ?",
                (new_path, int(time.time()), paper_id),
            )

    # ------------------------------------------------------------------
    # Volltext-Index (Issue #373)
    # ------------------------------------------------------------------

    def set_fulltext(self, paper_id: str, text: str, extractor: str = "pypdf") -> bool:
        """Persistiert den extrahierten PDF-Volltext und indiziert ihn in FTS5.

        Geschrieben wird an zwei Stellen in einer Transaktion: ``paper_fulltext``
        ist der kanonische Speicher (ueberlebt den Trigger-Rebuild von
        ``papers_au``), ``papers_fts.fulltext`` der Suchindex.

        Args:
            paper_id: Referenz auf ``papers.paper_id``.
            text: Extrahierter Volltext.
            extractor: Herkunft des Textes ("pypdf", "grobid", ...).

        Returns:
            ``True`` wenn geschrieben wurde, ``False`` bei leerem Text. Ein
            leerer Extraktionsversuch (Scan-PDF ohne Text-Layer) darf nicht als
            erledigt gelten, sonst wird er nach einem OCR-Lauf nie nachgeholt.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO paper_fulltext (paper_id, text, extractor, extracted_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                  text         = excluded.text,
                  extractor    = excluded.extractor,
                  extracted_at = excluded.extracted_at
                """,
                (paper_id, cleaned, extractor, now),
            )
            updated = conn.execute(
                "UPDATE papers_fts SET fulltext = ? WHERE paper_id = ?",
                (cleaned, paper_id),
            ).rowcount
            if updated == 0:
                # Kein FTS-Eintrag (z. B. DB aus einer Zeit vor den Triggern):
                # Zeile aus papers nachziehen, damit die Suche den Text sieht.
                row = conn.execute(
                    "SELECT csl_json FROM papers WHERE paper_id = ?", (paper_id,)
                ).fetchone()
                if row is not None:
                    conn.execute(
                        """
                        INSERT INTO papers_fts (paper_id, title, abstract, fulltext)
                        VALUES (?, json_extract(?, '$.title'), json_extract(?, '$.abstract'), ?)
                        """,
                        (paper_id, row["csl_json"], row["csl_json"], cleaned),
                    )
        return True

    def get_fulltext(self, paper_id: str) -> str | None:
        """Gibt den gespeicherten Volltext zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT text FROM paper_fulltext WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        return None if row is None else str(row["text"])

    def papers_missing_fulltext(self, limit: int | None = None) -> list[dict]:
        """Papers mit hinterlegtem PDF-Pfad, aber ohne Volltext-Eintrag.

        Kandidatenliste fuer den Backfill (``migrate.backfill_fulltext``).
        """
        sql = """
            SELECT p.paper_id, p.pdf_path
            FROM papers p
            LEFT JOIN paper_fulltext f ON f.paper_id = p.paper_id
            WHERE p.pdf_path IS NOT NULL AND trim(p.pdf_path) != ''
              AND f.paper_id IS NULL
            ORDER BY p.added_at, p.paper_id
        """
        params: list = []
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Figures CRUD
    # ------------------------------------------------------------------

    def add_figure(
        self,
        paper_id: str,
        page: int | None,
        caption: str | None,
        vlm_description: str | None,
        data_extracted_json: str | None,
    ) -> str:
        """INSERT einer Figure. Gibt figure_id (UUID) zurueck."""
        figure_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO figures
                  (figure_id, paper_id, page, caption, vlm_description, data_extracted_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (figure_id, paper_id, page, caption, vlm_description, data_extracted_json, now),
            )
        return figure_id

    def get_figure(self, figure_id: str) -> dict | None:
        """Gibt Figure-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM figures WHERE figure_id = ?", (figure_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_figures(self, paper_id: str) -> list[dict]:
        """Alle Figures fuer ein Paper, nach page sortiert."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM figures WHERE paper_id = ? ORDER BY page",
                (paper_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_figures_by_caption(
        self,
        caption_fragment: str,
        paper_id: str | None = None,
    ) -> list[dict]:
        """LIKE-Suche in figures.caption. Optionaler paper_id-Filter."""
        with self._connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM figures WHERE caption LIKE ? ESCAPE '\\' AND paper_id = ?",
                    (f"%{escape_like(caption_fragment)}%", paper_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM figures WHERE caption LIKE ? ESCAPE '\\'",
                    (f"%{escape_like(caption_fragment)}%",),
                ).fetchall()
        return [dict(r) for r in rows]

    def find_figures_by_reference(
        self,
        reference_text: str,
        paper_id: str | None = None,
    ) -> list[dict]:
        """Matcht ein In-Text-Referenz-Label (z. B. ``"Abb. 3.4"``) gegen
        Figure-Captions per Typ+Nummer-Vergleich (Issue #379).

        Anders als :meth:`find_figures_by_caption` (Freitext-LIKE-Suche,
        unveraendert fuer bestehende Aufrufer) parst diese Methode sowohl
        ``reference_text`` als auch jede Kandidaten-Caption strukturiert in
        ``(kind, number)`` und vergleicht diese Tupel. Das In-Text-Label ist
        selten wortidentischer Teilstring der vollen Caption (z. B. ist
        ``"Abb. 3.4"`` kein Teilstring von ``"Abbildung 3.4: ..."``), daher
        schlaegt reines LIKE-Matching hier praktisch immer fehl.

        Liefert ``[]`` wenn ``reference_text`` kein Typ+Nummer-Muster enthaelt
        oder kein Kandidat mit uebereinstimmendem Tupel existiert.
        """
        reference = _parse_figure_reference(reference_text)
        if reference is None:
            return []

        with self._connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM figures WHERE paper_id = ?", (paper_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM figures").fetchall()

        matches = []
        for row in rows:
            record = dict(row)
            caption = record.get("caption")
            if caption is None:
                continue
            if _parse_figure_reference(caption) == reference:
                matches.append(record)
        return matches

    # ------------------------------------------------------------------
    # Decisions CRUD (v6.4)
    # ------------------------------------------------------------------

    def add_decision(
        self,
        category: str | None,
        text: str,
        rationale: str | None = None,
    ) -> str:
        """INSERT einer Decision. Gibt decision_id (UUID) zurueck."""
        decision_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO decisions (decision_id, category, text, rationale, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (decision_id, category, text, rationale, now),
            )
        return decision_id

    def supersede_decision(self, decision_id: str, superseded_by: str) -> None:
        """Setzt superseded_by fuer eine Decision."""
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                "UPDATE decisions SET superseded_by = ? WHERE decision_id = ?",
                (superseded_by, decision_id),
            )

    def list_decisions(
        self,
        category: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """Gibt Decisions zurueck, optional nach Kategorie und/oder active gefiltert."""
        clauses = []
        params: list = []
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if active_only:
            clauses.append("superseded_by IS NULL")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM decisions {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Excluded Sources (v6.4)
    # ------------------------------------------------------------------

    def add_excluded_source(self, paper_id: str, reason: str | None = None) -> None:
        """INSERT or REPLACE eines excluded_source-Eintrags."""
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO excluded_sources (paper_id, reason, excluded_at)
                VALUES (?, ?, ?)
                """,
                (paper_id, reason, now),
            )

    def list_excluded_sources(self) -> list[dict]:
        """Gibt alle excluded_sources zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM excluded_sources ORDER BY excluded_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def is_excluded(self, paper_id: str) -> bool:
        """Prueft ob paper_id in excluded_sources ist."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM excluded_sources WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Risk-of-Bias Assessments (v6.4)
    # ------------------------------------------------------------------

    def add_risk_of_bias(
        self,
        paper_id: str,
        study_type: str,
        domain_scores_json: str,
    ) -> str:
        """INSERT eines RoB-Assessments. Gibt assessment_id (UUID) zurueck."""
        assessment_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO risk_of_bias_assessments
                  (assessment_id, paper_id, study_type, domain_scores_json, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (assessment_id, paper_id, study_type, domain_scores_json, now),
            )
        return assessment_id

    def list_risk_of_bias(
        self,
        paper_id: str | None = None,
    ) -> list[dict]:
        """Gibt RoB-Assessments zurueck, optional nach paper_id gefiltert."""
        with self._connection() as conn:
            if paper_id is not None:
                rows = conn.execute(
                    "SELECT * FROM risk_of_bias_assessments WHERE paper_id = ? ORDER BY ts DESC",
                    (paper_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM risk_of_bias_assessments ORDER BY ts DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Score History (v6.4)
    # ------------------------------------------------------------------

    def add_score_snapshot(
        self,
        paper_id: str,
        session_id: str,
        scores_json: str,
    ) -> str:
        """INSERT eines Score-Snapshots. Gibt snapshot_id (UUID) zurueck."""
        snapshot_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO score_history (snapshot_id, paper_id, session_id, ts, scores_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snapshot_id, paper_id, session_id, now, scores_json),
            )
        return snapshot_id

    def get_score_history(
        self,
        paper_id: str,
        k: int | None = None,
    ) -> list[dict]:
        """Gibt Score-History fuer ein Paper zurueck, nach ts DESC sortiert."""
        with self._connection() as conn:
            if k is not None:
                rows = conn.execute(
                    "SELECT * FROM score_history WHERE paper_id = ? ORDER BY ts DESC LIMIT ?",
                    (paper_id, k),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM score_history WHERE paper_id = ? ORDER BY ts DESC",
                    (paper_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Vault Lock (v6.4)
    # ------------------------------------------------------------------

    def _raise_if_locked(self, conn: sqlite3.Connection) -> None:
        """Wirft ``VaultLockedError``, falls der Material-Passport gesperrt ist.

        Bewusst *unscoped* (Issue #380): geprueft wird nur, ob ueberhaupt ein
        Eintrag in ``vault_locked_status`` existiert -- nicht slug-genau. Eine
        ``vault.db`` bedient in der Praxis genau ein Projekt (``db_path`` wird
        ueber ``project_slug()``/``--slug`` beim Anlegen fest verdrahtet) und
        die Schreib-Tools in ``server.py`` fuehren aktuell keinen
        ``slug``-Parameter. Das slug-scoped ``is_locked(slug)``/
        ``lock_vault(slug)`` bleibt fuer diesen Zweck unveraendert; dieser
        Guard ist ein separater, bewusst grober Mechanismus.

        Wird als erste Anweisung innerhalb des jeweiligen
        ``with self._connection(commit=True) as conn:``-Blocks der
        betroffenen Schreib-Methoden aufgerufen, damit Pruefung und
        INSERT/UPDATE atomar in derselben SQLite-Transaktion liegen (kein
        TOCTOU-Fenster, keine Teil-Schreibung bei Verstoss).
        """
        row = conn.execute("SELECT slug FROM vault_locked_status LIMIT 1").fetchone()
        if row is not None:
            raise VaultLockedError(
                f"Vault ist gesperrt (Material-Passport-Lock fuer Slug "
                f"'{row['slug']}') -- Schreiboperationen sind nicht mehr erlaubt."
            )

    # ------------------------------------------------------------------
    # Chunk Embeddings (v6.5 — Contextual Retrieval #109)
    # ------------------------------------------------------------------

    def add_chunk_embedding(
        self,
        paper_id: str,
        chunk_text: str,
        context_sentence: str,
        embedding_text: str,
        embedding_vector: bytes | None,
    ) -> str:
        """INSERT eines Chunk-Embeddings. Gibt chunk_id (UUID) zurueck.

        Args:
            paper_id: Referenz auf papers.paper_id.
            chunk_text: Originaler Chunk-Text.
            context_sentence: 1-Satz-Kontext generiert via Anthropic API.
            embedding_text: Kombinierter Text (context_sentence + chunk_text).
            embedding_vector: Serialisierter Embedding-Vektor (bytes) oder None.
        """
        chunk_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO chunk_embeddings
                  (chunk_id, paper_id, chunk_text, context_sentence, embedding_text,
                   embedding_vector, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    paper_id,
                    chunk_text,
                    context_sentence,
                    embedding_text,
                    embedding_vector,
                    now,
                ),
            )
            self._mirror_chunk_vector(conn, chunk_id, embedding_vector)
        return chunk_id

    def get_chunk_embeddings(self, paper_id: str) -> list[dict]:
        """Gibt alle Chunk-Embeddings fuer ein Paper zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM chunk_embeddings WHERE paper_id = ? ORDER BY created_at",
                (paper_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_chunk_embeddings(self, paper_id: str) -> int:
        """Loescht alle Chunks eines Papers (inkl. vec0-Spiegel). Gibt die Anzahl zurueck.

        Wird vom Ingest vor dem Neuschreiben aufgerufen, damit ein wiederholter
        ``add_paper``-Upsert die Chunk-Tabelle nicht endlos aufblaeht.
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            chunk_ids = [
                row["chunk_id"]
                for row in conn.execute(
                    "SELECT chunk_id FROM chunk_embeddings WHERE paper_id = ?", (paper_id,)
                ).fetchall()
            ]
            if not chunk_ids:
                return 0
            conn.execute("DELETE FROM chunk_embeddings WHERE paper_id = ?", (paper_id,))
            if self.load_vec_extension(conn):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.executemany(
                        "DELETE FROM chunk_vectors WHERE chunk_id = ?",
                        [(cid,) for cid in chunk_ids],
                    )
        return len(chunk_ids)

    # ------------------------------------------------------------------
    # Vektor-Suche ueber Chunks (Issue #372)
    # ------------------------------------------------------------------

    def _mirror_chunk_vector(
        self,
        conn: sqlite3.Connection,
        chunk_id: str,
        embedding_vector: bytes | None,
    ) -> bool:
        """Spiegelt einen Chunk-Vektor in die vec0-Tabelle. Best effort.

        Gibt False zurueck, wenn kein (passender) Vektor vorliegt oder die
        sqlite-vec-Extension nicht ladbar ist — dann uebernimmt der
        Python-Fallback in :meth:`knn_chunks` die Suche.
        """
        if not embedding_vector or len(embedding_vector) != EMBEDDING_DIM * 4:
            return False
        if not self.load_vec_extension(conn):
            return False
        try:
            conn.execute(_CHUNK_VECTORS_DDL)
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vectors (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, embedding_vector),
            )
        except sqlite3.OperationalError:
            return False
        return True

    def sync_chunk_vectors(self) -> int:
        """Legt die vec0-Tabelle an und spiegelt vorhandene Chunk-Vektoren hinein.

        Idempotent; ohne ladbare sqlite-vec-Extension ein No-op (Rueckgabe 0).
        Gibt die Anzahl gespiegelter Vektoren zurueck.
        """
        mirrored = 0
        with self._connection(commit=True) as conn:
            if not self.load_vec_extension(conn):
                return 0
            try:
                conn.execute(_CHUNK_VECTORS_DDL)
            except sqlite3.OperationalError:
                return 0
            rows = conn.execute(
                "SELECT chunk_id, embedding_vector FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (EMBEDDING_DIM * 4,),
            ).fetchall()
            for row in rows:
                if self._mirror_chunk_vector(conn, row["chunk_id"], row["embedding_vector"]):
                    mirrored += 1
        return mirrored

    def knn_chunks(self, query_vector: Sequence[float], k: int = 10) -> list[dict]:
        """K-Nearest-Neighbour-Suche ueber chunk_embeddings.

        Primaerpfad ist die vec0-Virtual-Table ``chunk_vectors``; ist die
        sqlite-vec-Extension nicht ladbar (Python-Builds ohne
        ``--enable-loadable-sqlite-extensions``, u. a. auf macOS) oder der
        vec0-Spiegel unvollstaendig, wird dieselbe Suche in Python ueber die
        BLOBs in ``chunk_embeddings`` gerechnet.

        Beide Pfade nutzen die euklidische Distanz. Da alle Vektoren
        L2-normalisiert gespeichert werden, ist deren Rangfolge identisch zur
        Kosinus-Rangfolge — und beide Pfade liefern dieselbe Reihenfolge.

        Returns:
            Liste aus ``{chunk_id, paper_id, chunk_text, distance}``,
            aufsteigend nach Distanz (nahester Treffer zuerst).
        """
        if not query_vector or k <= 0:
            return []
        dim = len(query_vector)
        with self._connection() as conn:
            total = conn.execute(
                "SELECT count(*) FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (dim * 4,),
            ).fetchone()[0]
            if total == 0:
                return []
            hits: list[dict] | None = None
            if dim == EMBEDDING_DIM and self.load_vec_extension(conn):
                hits = self._knn_chunks_vec0(conn, query_vector, k, total)
            if hits is None:
                hits = self._knn_chunks_python(conn, query_vector, k)
        return hits

    def _knn_chunks_vec0(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        k: int,
        expected_total: int,
    ) -> list[dict] | None:
        """vec0-KNN. Gibt None zurueck, wenn der Pfad nicht verlaesslich ist."""
        try:
            mirrored = conn.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0]
        except sqlite3.OperationalError:
            return None
        if mirrored < expected_total:
            # Spiegel unvollstaendig (z. B. DB aus einer Umgebung ohne
            # Extension): lieber vollstaendig in Python rechnen als still
            # Treffer verlieren. `migrate.add_chunk_vectors_table` repariert das.
            return None
        try:
            rows = conn.execute(
                "SELECT chunk_id, distance FROM chunk_vectors "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (serialize_f32(query_vector), k),
            ).fetchall()
        except sqlite3.OperationalError:
            return None

        hits: list[dict] = []
        for row in rows:
            meta = conn.execute(
                "SELECT paper_id, chunk_text FROM chunk_embeddings WHERE chunk_id = ?",
                (row["chunk_id"],),
            ).fetchone()
            if meta is None:
                continue
            hits.append(
                {
                    "chunk_id": row["chunk_id"],
                    "paper_id": meta["paper_id"],
                    "chunk_text": meta["chunk_text"],
                    "distance": float(row["distance"]),
                }
            )
        # Gleicher Tiebreaker wie im Python-Fallback: bei exakt gleicher Distanz
        # (z. B. zwei zur Query orthogonale Chunks) wuerde vec0 sonst nach
        # interner rowid ordnen und beide Pfade lieferten verschiedene
        # Reihenfolgen fuer dieselben Daten.
        hits.sort(key=lambda hit: (hit["distance"], hit["chunk_id"]))
        return hits

    def _knn_chunks_python(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        k: int,
    ) -> list[dict]:
        """Reiner Python-Fallback: euklidische Distanz ueber alle Chunk-BLOBs."""
        dim = len(query_vector)
        rows = conn.execute(
            "SELECT chunk_id, paper_id, chunk_text, embedding_vector FROM chunk_embeddings "
            "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
            (dim * 4,),
        ).fetchall()

        hits: list[dict] = []
        for row in rows:
            try:
                vector = deserialize_f32(row["embedding_vector"])
            except ValueError:
                continue
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(query_vector, vector, strict=True))
            )
            hits.append(
                {
                    "chunk_id": row["chunk_id"],
                    "paper_id": row["paper_id"],
                    "chunk_text": row["chunk_text"],
                    "distance": distance,
                }
            )
        # chunk_id als Tiebreaker: deterministische Reihenfolge bei Gleichstand.
        hits.sort(key=lambda hit: (hit["distance"], hit["chunk_id"]))
        return hits[:k]

    def lock_vault(self, slug: str) -> None:
        """Setzt Vault-Lock fuer einen Slug. Idempotent."""
        now = int(time.time())
        with self._connection(commit=True) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vault_locked_status (slug, locked_at)
                VALUES (?, ?)
                """,
                (slug, now),
            )

    def is_locked(self, slug: str) -> bool:
        """Prueft ob Vault-Lock fuer Slug gesetzt ist."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM vault_locked_status WHERE slug = ?", (slug,)
            ).fetchone()
        return row is not None
