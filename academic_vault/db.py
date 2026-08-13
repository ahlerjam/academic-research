"""VaultDB — Fassade der SQLite-Datenbankschicht fuer academic_vault.

Haelt Connection-, Transaktions- und Lock-Handling sowie die
Schema-Initialisierung. Die CRUD-Methoden der einzelnen Aggregate liegen seit
Issue #841 als Mixins unter ``academic_vault/repositories/`` und werden hier zu
``VaultDB`` komponiert -- jede Methode bleibt dadurch direkt an der Klasse
erreichbar, kein Aufrufer aendert sich.

Alle Namen, die frueher aus diesem Modul importierbar waren, bleiben es: die
Konstanten liegen jetzt in :mod:`academic_vault.vault_schema`, die reinen
Text-/Pfad-Helfer in :mod:`academic_vault.vault_text` und werden unten
re-exportiert.
"""

import contextlib
import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

from .embedding_model import DEFAULT_EMBEDDING_DIM, dimension_mismatch_error
from .repositories import (
    AppraisalRepo,
    ChunksRepo,
    ConnectionHost,
    DecisionsRepo,
    EmpiricsRepo,
    FiguresRepo,
    FulltextRepo,
    NotesRepo,
    PapersRepo,
    QuotesRepo,
    TablesRepo,
    VectorsRepo,
)
from .vault_schema import (
    _LEGACY_MIGRATION_COLUMNS,
    _OPTIONAL_PAPER_COLUMNS,
    _OPTIONAL_PAPER_DEFAULTS,
    _REQUIRED_MIGRATION_TABLES,
    _UNSET,
    CURRENT_SCHEMA_VERSION,
    SCIHUB_PROVENANCE_SIDECAR_SUFFIX,
    VALID_AUDIT_SEVERITIES,
    VALID_AUDIT_VERDICTS,
    VALID_CATEGORY_ORIGINS,
    VALID_CHUNK_CONTEXT_SOURCES,
    VALID_EXTRACTION_METHODS,
    VALID_PAPER_TYPES,
    VALID_SOURCE_KINDS,
    VALID_STANCES,
    _chunk_vectors_ddl,
    _quote_embeddings_ddl,
    _Unset,
)
from .vault_text import (
    _parse_figure_reference,
    _sanitize_fts5_query,
    csl_families,
    csl_title,
    csl_year,
    default_db_path,
    escape_like,
    family_names_match,
    format_table_evidence,
    normalize_family_name,
    paper_cited_in_chapters,
    project_slug,
)

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class VaultLockedError(RuntimeError):
    """Material-Passport ist gesperrt -- Schreiboperation wurde verweigert.

    Wird geworfen sobald ein Eintrag in ``vault_locked_status`` existiert
    (siehe ``VaultDB._raise_if_locked``, Issue #380).
    """


class VaultDB(
    PapersRepo,
    QuotesRepo,
    NotesRepo,
    FulltextRepo,
    TablesRepo,
    FiguresRepo,
    EmpiricsRepo,
    DecisionsRepo,
    AppraisalRepo,
    ChunksRepo,
    VectorsRepo,
    ConnectionHost,
):
    """SQLite-Datenbankzugriff fuer den academic_vault MCP-Server.

    Fassade: haelt die Connection (``_connection``, WAL, ``__enter__``/
    ``__exit__``), das Schema (``init_schema``), den Vault-Lock-Guard und die
    Vektorbreite des Bestands. Die CRUD-Methoden kommen aus den
    Aggregat-Mixins in :mod:`academic_vault.repositories` -- ``VaultDB`` steht
    in der MRO vor ihnen und erfuellt damit den Kontrakt
    :class:`~academic_vault.repositories._base.ConnectionHost`.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.vec_available: bool = False
        # Fehlerursache des letzten load_vec_extension()-Fehlschlags (Issue
        # #624): vorher wurde die Exception in zwei der drei Fehlschlagszweigen
        # stillschweigend verschluckt. ``None`` heisst "kein Fehler bekannt" --
        # entweder laedt die Extension, oder es gab noch keinen Ladeversuch.
        self.vec_unavailable_reason: str | None = None
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
            self.vec_unavailable_reason = (
                "Python-Interpreter unterstuetzt keine ladbaren SQLite-Erweiterungen "
                "(kein enable_load_extension) -- typisch fuer System-Python ohne "
                "--enable-loadable-sqlite-extensions."
            )
            return False

        try:
            target.enable_load_extension(True)
        except (AttributeError, sqlite3.OperationalError, sqlite3.NotSupportedError) as exc:
            self.vec_available = False
            self.vec_unavailable_reason = (
                f"enable_load_extension() nicht nutzbar ({type(exc).__name__}: {exc})"
            )
            return False

        try:
            if vec_path:
                target.load_extension(vec_path)
            else:
                import sqlite_vec

                target.load_extension(sqlite_vec.loadable_path())
            self.vec_available = True
            self.vec_unavailable_reason = None
        except Exception as exc:
            self.vec_available = False
            self.vec_unavailable_reason = (
                f"sqlite-vec-Extension nicht ladbar ({type(exc).__name__}: {exc})"
            )
        finally:
            try:
                target.enable_load_extension(False)
            except Exception:
                pass
        return self.vec_available

    def init_schema(self) -> None:
        """Erstellt alle Tabellen gemaess schema.sql, migriert Bestands-DBs (#368).

        `CREATE TABLE IF NOT EXISTS` (schema.sql) deckt neue Tabellen und
        frische DBs bereits vollstaendig ab, kann aber bestehende Tabellen
        nicht um neue Spalten erweitern. Ein Versions-Gate ueber
        `PRAGMA user_version` schliesst diese Luecke: Eine DB, deren
        `papers`-Tabelle schon vor dem DDL-Lauf existierte (Legacy-Schema,
        z.B. prae-#195 ohne `parent_paper_id`/`provenance`) und deren
        `user_version` noch unter `CURRENT_SCHEMA_VERSION` liegt, bekommt
        einmalig die additiven `migrate.py`-Helfer nachgezogen -- statt bei
        `add_paper()` mit `sqlite3.OperationalError` abzustuerzen. Ueber
        dieselbe Schleuse laeuft seit #539 auch der eine subtraktive Schritt
        (`migrate.drop_dead_v64_tables()`).

        Bei bereits aktueller `user_version` ist der Aufruf ein billiger
        PRAGMA-Read ohne weitere Schreiboperation: `init_schema()` ist ein
        Hot-Path (server.py ruft ihn ~17x auf), wiederholte Aufrufe duerfen
        keine ALTER-Versuche o.ae. wiederholen.
        """
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connection(commit=True) as conn:
            # vec-Extension auf derselben Connection laden (optional)
            self.load_vec_extension(conn)

            # Fresh-DB-Erkennung *vor* dem DDL-Lauf: existierte "papers" schon,
            # koennte es sich um ein Legacy-Schema handeln, das Migrationshelfer
            # braucht. Eine echte Neuanlage bekommt schema.sql komplett (inkl.
            # aller Spalten) und braucht keine Helfer.
            papers_existed_before = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='papers'"
                ).fetchone()
                is not None
            )

            # Basis-Schema ausfuehren (ohne vec0-Block — der ist auskommentiert)
            conn.executescript(ddl)

            # quote_embeddings via vec0 versuchen (nur wenn Extension geladen).
            # Breite aus dem Bestand (embedding_meta), nicht aus dem
            # Modell-Default: eine DB, die per Re-Index auf ein 1024d-Modell
            # umgestellt wurde, bekaeme sonst bei jedem init_schema()-Aufruf
            # wieder 384er-Tabellen angeboten (#629).
            if self.vec_available:
                dim = self._expected_embedding_dim(conn)
                try:
                    conn.execute(_quote_embeddings_ddl(dim))
                    conn.execute(_chunk_vectors_ddl(dim))
                except sqlite3.OperationalError:
                    self.vec_available = False

        if not papers_existed_before:
            # Echte Neuanlage: schema.sql deckt alle Spalten bereits ab,
            # Migrationshelfer sind nicht noetig -- Version direkt setzen.
            with self._connection(commit=True) as conn:
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            return

        with self._connection() as conn:
            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version >= CURRENT_SCHEMA_VERSION:
            return  # bereits migriert -- kein weiterer Schreibzugriff

        # Legacy-DB unter der aktuellen Schema-Version: Migrationshelfer
        # ausserhalb jeder offenen self._connection() ausfuehren. Die Helfer
        # oeffnen ihre eigenen kurzlebigen sqlite3-Connections (migrate.py);
        # das darf sich nicht mit einer hier noch offenen Schreibtransaktion
        # ueberschneiden (Issue #368, Plan-Risikonotiz).
        from . import migrate

        migrate.apply_pending_migrations(self.db_path)

        # Nicht blind vertrauen: apply_pending_migrations() gibt kein
        # Erfolgssignal zurueck, und jeder Helfer schluckt *jeden*
        # sqlite3.OperationalError (nicht nur "duplicate column name") als
        # vermeintliche Idempotenz. Erst per PRAGMA table_info(papers)
        # verifizieren, dass die Migration tatsaechlich gegriffen hat, bevor
        # der Stempel gesetzt wird -- sonst schliesst sich das Versions-Gate
        # unwiderruflich (Review-Fund PR #427: user_version wuerde auch nach
        # fehlgeschlagener Migration gestempelt, AC1 dauerhaft verletzt).
        with self._connection(commit=True) as conn:
            missing: list[str] = []
            for table, required in _LEGACY_MIGRATION_COLUMNS.items():
                present = {
                    row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                missing += [f"{table}.{col}" for col in sorted(required - present)]

            # Symmetrisch zur Spalten-Verifikation, nur andersherum (#539):
            # `migrate.drop_dead_v64_tables()` laesst eine tote Tabelle bewusst
            # stehen, wenn sie wider Erwarten Zeilen enthaelt -- dann darf auch
            # nicht gestempelt werden, sonst bliebe sie fuer immer liegen.
            existing_tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            undropped = sorted(migrate.DEAD_TABLES & existing_tables)

            # Vierte Verifikationsart (#629): `add_embedding_meta_table()` legt
            # eine ganze Tabelle an. Fehlt sie hinterher, darf nicht gestempelt
            # werden -- sonst bliebe der Bestandsnachweis fuer immer aus und
            # jeder Modellwechsel liefe wieder ins Stille.
            uncreated = sorted(_REQUIRED_MIGRATION_TABLES - existing_tables)

            # Dritte Verifikationsart (#512): `widen_extraction_method_check()`
            # aendert einen CHECK-Constraint statt eine Spalte -- ein
            # fehlgeschlagener Tabellen-Rebuild waere ueber
            # `PRAGMA table_info()` unsichtbar und wuerde trotzdem gestempelt
            # (exakt der Review-Fund aus PR #427, nur eine Ebene tiefer).
            quotes_sql_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='quotes'"
            ).fetchone()
            unwidened = (
                []
                if migrate.quotes_check_accepts_local_verbatim(
                    quotes_sql_row["sql"] if quotes_sql_row is not None else None
                )
                else ["quotes.extraction_method CHECK ohne 'local-verbatim'"]
            )

            if not missing and not undropped and not unwidened and not uncreated:
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            else:
                # Stempel bewusst auslassen: user_version bleibt unter
                # CURRENT_SCHEMA_VERSION, damit der naechste init_schema()-Aufruf
                # die Migration erneut versucht statt sie faelschlich als
                # erledigt zu betrachten. Kein `raise` -- eine Exception aus
                # init_schema() wuerde den kompletten MCP-Server lahmlegen.
                logger.warning(
                    "Migration auf Schema-Version %d nicht verifizierbar -- "
                    "es fehlen weiterhin Spalten %s, diese toten Tabellen "
                    "sind nicht leer und daher nicht gedroppt: %s, diese "
                    "Constraints wurden nicht erweitert: %s, und diese Tabellen "
                    "fehlen weiterhin: %s. user_version bleibt unveraendert, "
                    "naechster init_schema()-Aufruf migriert erneut "
                    "(#368, #539, #512, #629).",
                    CURRENT_SCHEMA_VERSION,
                    missing,
                    undropped,
                    unwidened,
                    uncreated,
                )

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

    def _expected_embedding_dim(self, conn: sqlite3.Connection) -> int:
        """Dimension des Bestands auf einer bestehenden Connection.

        Quelle ist ``embedding_meta``; fehlt die Zeile (frischer Vault) oder
        die Tabelle (Bestands-DB vor der Migration auf Schema 8), gilt die
        Breite, in der vec0-Tabellen bislang angelegt wurden:
        ``DEFAULT_EMBEDDING_DIM``. Bewusst ohne jeden Embedder-Zugriff -- ein
        Modell-Load haengt hier an jedem Lesepfad (u. a.
        ``quote_context_similarity`` im PreToolUse-Hook) und waere ein
        Timeout-Kandidat.
        """
        try:
            row = conn.execute("SELECT dim FROM embedding_meta WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            return DEFAULT_EMBEDDING_DIM
        if row is None or not row["dim"]:
            return DEFAULT_EMBEDDING_DIM
        return int(row["dim"])

    def _assert_vector_dim(self, conn: sqlite3.Connection, embedding_vector: bytes) -> None:
        """Wirft, wenn ein Vektor nicht die Breite des Bestands hat (#629).

        Zweite Verteidigungslinie hinter :meth:`register_embedding_inventory`:
        greift auch fuer Aufrufer, die direkt schreiben, und kennt dafuer nur
        die Byte-Laenge -- die Modell-ID steht in der Meldung nur, wenn sie im
        Bestand hinterlegt ist.
        """
        if len(embedding_vector) % 4 != 0:
            raise ValueError(
                f"Embedding-BLOB hat Laenge {len(embedding_vector)} (kein Vielfaches von 4 Bytes)"
            )
        dim = len(embedding_vector) // 4
        expected = self._expected_embedding_dim(conn)
        if dim == expected:
            return
        try:
            row = conn.execute("SELECT model_id FROM embedding_meta WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            row = None
        raise dimension_mismatch_error(
            model_id=None,
            model_dim=dim,
            vault_dim=expected,
            vault_model_id=row["model_id"] if row is not None else None,
        )

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


# Re-Exports: alles, was vor der Aufteilung (#841) aus diesem Modul importierbar
# war, bleibt es. ``__all__`` haelt zugleich ruff F401 von den reinen
# Weiterreichungen fern.
__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DEFAULT_EMBEDDING_DIM",
    "SCIHUB_PROVENANCE_SIDECAR_SUFFIX",
    "VALID_AUDIT_SEVERITIES",
    "VALID_AUDIT_VERDICTS",
    "VALID_CATEGORY_ORIGINS",
    "VALID_CHUNK_CONTEXT_SOURCES",
    "VALID_EXTRACTION_METHODS",
    "VALID_PAPER_TYPES",
    "VALID_SOURCE_KINDS",
    "VALID_STANCES",
    "VaultDB",
    "VaultLockedError",
    "_LEGACY_MIGRATION_COLUMNS",
    "_OPTIONAL_PAPER_COLUMNS",
    "_OPTIONAL_PAPER_DEFAULTS",
    "_REQUIRED_MIGRATION_TABLES",
    "_UNSET",
    "_Unset",
    "_chunk_vectors_ddl",
    "_parse_figure_reference",
    "_quote_embeddings_ddl",
    "_sanitize_fts5_query",
    "csl_families",
    "csl_title",
    "csl_year",
    "default_db_path",
    "dimension_mismatch_error",
    "escape_like",
    "family_names_match",
    "format_table_evidence",
    "normalize_family_name",
    "paper_cited_in_chapters",
    "project_slug",
]
