"""Quotes-Aggregat: CRUD der ``quotes``-Tabelle, Audit-Historie und
die vec0-Embeddings verifizierter Zitate (Issue #521).

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import logging
import sqlite3
import time

from ..embedding_model import deserialize_f32
from ..vault_schema import (
    VALID_AUDIT_SEVERITIES,
    VALID_AUDIT_VERDICTS,
    VALID_STANCES,
    _quote_embeddings_ddl,
)
from ..vault_text import escape_like
from ._base import ConnectionHost

logger = logging.getLogger(__name__)


class QuotesRepo(ConnectionHost):
    """Quotes-CRUD, Audit-Historie und die vec0-Zitat-Embeddings (Issue #521)."""

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
        stance: str | None = None,
    ) -> None:
        """INSERT eines Quotes in die quotes-Tabelle.

        Args:
            stance: Optionale Haltung des Zitats zur zitierenden Aussage
                (`VALID_STANCES`), sonst `None` (Issue #400). Die Validierung
                liegt hier statt allein im CHECK-Constraint, damit jeder
                Aufrufweg (MCP-Tool wie direkte ``VaultDB``-Nutzung) dieselbe
                lesbare Meldung bekommt statt eines rohen
                ``sqlite3.IntegrityError``.

        Raises:
            ValueError: Wenn ``stance`` weder ``None`` noch einer der Werte aus
                ``VALID_STANCES`` ist.
        """
        if stance is not None and stance not in VALID_STANCES:
            raise ValueError(
                f"Ungueltiger stance '{stance}' -- erlaubt: {sorted(VALID_STANCES)} oder None"
            )

        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO quotes
                  (quote_id, paper_id, verbatim, pdf_page, printed_page,
                   section, context_before, context_after,
                   extraction_method, api_response_id, created_at, stance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    stance,
                ),
            )

    def update_quote_context(
        self,
        quote_id: str,
        context_before: str,
        context_after: str,
        context_source: str,
    ) -> None:
        """Schreibt echten Quellkontext auf einen bestehenden Quote (Issue #520).

        Wird ausschliesslich von :func:`academic_vault.server.resolve_quote_context`
        aufgerufen, NACHDEM eine Fundstelle im ``paper_fulltext`` nachgewiesen
        wurde -- kein Aufrufweg hier rate irgendetwas, das ist Aufgabe des
        Aufrufers. ``context_source`` wird bewusst nicht gegen
        ``VALID_...``-Konstante validiert (analog zu ``extraction_method``):
        der CHECK-Constraint auf ``quotes.context_source`` ist die zweite
        Verteidigungslinie fuer unbekannte Werte.

        Raises:
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                UPDATE quotes
                SET context_before = ?, context_after = ?, context_source = ?
                WHERE quote_id = ?
                """,
                (context_before, context_after, context_source, quote_id),
            )

    def get_quote(self, quote_id: str) -> dict | None:
        """Gibt Quote-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
        return dict(row) if row is not None else None

    def set_quote_stance(self, quote_id: str, stance: str) -> None:
        """Aktualisiert ``stance`` eines BESTEHENDEN Quotes (Issue #523).

        Ergaenzt ``add_quote(stance=...)`` um einen nachtraeglichen
        Audit-Schreibpfad: der `quote-fidelity-auditor`-Agent legt keine neuen
        Zitate an, sondern urteilt ueber bereits im Vault vorhandene.

        Args:
            quote_id: Referenz auf ``quotes.quote_id``.
            stance: Einer der Werte aus ``VALID_STANCES`` (``None`` ist hier
                bewusst NICHT erlaubt -- ein Audit-Urteil loescht keine
                bestehende Einstufung, das waere ein stiller Datenverlust).

        Raises:
            ValueError: Wenn ``stance`` nicht in ``VALID_STANCES`` liegt, oder
                wenn ``quote_id`` auf kein bestehendes Zitat verweist.
        """
        if stance not in VALID_STANCES:
            raise ValueError(f"Ungueltiger stance '{stance}' -- erlaubt: {sorted(VALID_STANCES)}")
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            cursor = conn.execute(
                "UPDATE quotes SET stance = ? WHERE quote_id = ?",
                (stance, quote_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"vault.set_quote_stance: Quote '{quote_id}' nicht gefunden")

    def record_quote_audit(
        self,
        quote_id: str,
        verdict: str,
        severity: str | None = None,
    ) -> None:
        """Protokolliert ein Audit-Urteil eines BESTEHENDEN Quotes (Issue #737).

        Additiver Schreibpfad zusaetzlich zu :meth:`set_quote_stance` -- der
        `quote-fidelity-auditor`-Agent ruft beide auf, nie nur einen: `stance`
        ist lossy (bei `unsupported` wird dort gar nichts persistiert) und
        kann "geprueft & unauffaellig" nicht von "nie geprueft" unterscheiden.
        `audited_at` (Unix-Epoch) ist die einzige verlaessliche Grundlage
        dafuer, siehe Kommentar bei `quotes.stance`/`quotes.audited_at` in
        schema.sql.

        Args:
            quote_id: Referenz auf ``quotes.quote_id``.
            verdict: Einer der Werte aus ``VALID_AUDIT_VERDICTS``.
            severity: Einer der Werte aus ``VALID_AUDIT_SEVERITIES`` fuer
                jeden Negativ-Verdict (Pflicht dort), ``None`` AUSSCHLIESSLICH
                fuer ``verdict == "faithful"`` (kein Befund -- siehe
                Verdict->Schweregrad-Tabelle in
                agents/quote-fidelity-auditor.md).

        Raises:
            ValueError: Wenn ``verdict`` nicht in ``VALID_AUDIT_VERDICTS``
                liegt, wenn ``severity`` bei ``faithful`` gesetzt ist, wenn
                ``severity`` bei jedem anderen Verdict fehlt oder nicht in
                ``VALID_AUDIT_SEVERITIES`` liegt, oder wenn ``quote_id`` auf
                kein bestehendes Zitat verweist.
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
        """
        if verdict not in VALID_AUDIT_VERDICTS:
            raise ValueError(
                f"Ungueltiger verdict '{verdict}' -- erlaubt: {sorted(VALID_AUDIT_VERDICTS)}"
            )
        if verdict == "faithful":
            if severity is not None:
                raise ValueError("severity muss None sein bei verdict='faithful' (kein Befund)")
        elif severity not in VALID_AUDIT_SEVERITIES:
            raise ValueError(
                f"Ungueltiger severity '{severity}' fuer verdict '{verdict}' -- "
                f"erlaubt: {sorted(VALID_AUDIT_SEVERITIES)}"
            )
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            cursor = conn.execute(
                "UPDATE quotes SET audited_at = ?, audit_verdict = ?, audit_severity = ? "
                "WHERE quote_id = ?",
                (int(time.time()), verdict, severity, quote_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"vault.record_quote_audit: Quote '{quote_id}' nicht gefunden")

    def search_quote_text(self, verbatim: str, k: int = 5) -> list[dict]:
        """LIKE-Suche in quotes.verbatim. Gibt [{quote_id, verbatim, paper_id}] zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quote_id, verbatim, paper_id FROM quotes "
                "WHERE verbatim LIKE ? ESCAPE '\\' LIMIT ?",
                (f"%{escape_like(verbatim)}%", k),
            ).fetchall()
        return [dict(r) for r in rows]

    def quotes_snapshot_for_wording(self, min_length: int = 0, limit: int = 5000) -> list[dict]:
        """Liest Zitate EINMAL fuer den Wortlaut-Abgleich eines Writes (Issue #846).

        Gegenstueck zu :meth:`_papers_snapshot` fuer die ``quotes``-Tabelle,
        aber bewusst OEFFENTLICH: :func:`academic_vault.server.match_quote_wording`
        liegt in einem anderen Modul, und ein Zugriff auf einen unterstrichenen
        Namen von aussen war genau die Falle aus #501.

        ``min_length`` filtert Zitate weg, die kuerzer sind als der kuerzeste
        Kandidat des Writes -- sie koennen ihn weder enthalten noch ihm
        aehneln. ``limit`` deckelt die je Write gelesene Menge, damit ein sehr
        grosser Vault den Hook-Zeitrahmen nicht sprengt. Die Sortierung ueber
        ``quote_id`` haelt das Ergebnis bei erreichtem Limit deterministisch.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quote_id, paper_id, verbatim FROM quotes "
                "WHERE verbatim IS NOT NULL AND length(verbatim) >= ? "
                "ORDER BY quote_id LIMIT ?",
                (int(min_length), int(limit)),
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

    # ------------------------------------------------------------------
    # Quote-Embeddings (Issue #521)
    # ------------------------------------------------------------------

    def vec_extension_loadable(self) -> bool:
        """Prueft, ob die sqlite-vec-Extension in diesem Prozess ladbar ist.

        Oeffnet dafuer kurz eine eigene Connection (ueber ``_connection()``,
        die sie garantiert wieder schliesst) -- fuer Aufrufer, die VOR einer
        teuren Operation (Embedding-Modell-Load) pruefen wollen, ob am Ende
        ueberhaupt gespeichert werden koennte (Plan-Risiko #521/4).
        """
        with self._connection() as conn:
            return self.load_vec_extension(conn)

    def add_quote_embedding(self, quote_id: str, embedding_vector: bytes) -> bool:
        """Schreibt (oder ersetzt) den Embedding-Vektor eines Quotes in vec0.

        Best effort in einer Hinsicht (Issue #521, bewusste
        Scope-Entscheidung): bei leerem Vektor oder ohne ladbare
        sqlite-vec-Extension ist der Aufruf ein No-Op mit Rueckgabe ``False``
        -- anders als bei Chunks gibt es fuer Quotes keine BLOB-Basistabelle.

        NICHT mehr best effort ist die Dimension (Issue #629): ein Vektor
        fremder Breite wurde frueher stillschweigend verworfen und der Quote
        blieb ohne Embedding, ohne dass die Ursache irgendwo auftauchte.

        Raises:
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
            EmbeddingDimensionMismatchError: Vektorbreite passt nicht zum
                Bestand (``embedding_meta``).
        """
        if not embedding_vector:
            return False
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            self._assert_vector_dim(conn, embedding_vector)
            if not self.load_vec_extension(conn):
                return False
            try:
                conn.execute(_quote_embeddings_ddl(self._expected_embedding_dim(conn)))
                conn.execute(
                    "INSERT OR REPLACE INTO quote_embeddings (quote_id, embedding) VALUES (?, ?)",
                    (quote_id, embedding_vector),
                )
            except sqlite3.OperationalError:
                return False
        return True

    def get_quote_embedding(self, quote_id: str) -> list[float] | None:
        """Liest den gespeicherten Embedding-Vektor eines Quotes (Issue #522).

        Rein lesendes Gegenstueck zu :meth:`add_quote_embedding`. ``None``
        bedeutet in jedem Fall "keine Zahl verfuegbar" und nie "Aehnlichkeit
        null": fehlende sqlite-vec-Extension, fehlende ``quote_embeddings``-
        Tabelle oder kein Eintrag zu dieser ``quote_id``. Aufrufer duerfen
        daraus nichts ableiten (Muster :meth:`quotes_missing_embedding`).
        """
        with self._connection() as conn:
            if not self.load_vec_extension(conn):
                return None
            try:
                row = conn.execute(
                    "SELECT embedding FROM quote_embeddings WHERE quote_id = ?",
                    (quote_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if row is None:
            return None
        blob = row["embedding"]
        if not isinstance(blob, bytes | bytearray):
            return None
        try:
            return deserialize_f32(bytes(blob))
        except ValueError:
            # Abgeschnittener Altbestand: lieber "keine Zahl" als halbe Floats.
            logger.warning(
                "vault.get_quote_embedding: Embedding von Quote '%s' ist beschaedigt (#522).",
                quote_id,
            )
            return None

    def quotes_missing_embedding(self, limit: int | None = None) -> list[dict]:
        """Quotes ohne Eintrag in ``quote_embeddings``. Kandidatenliste fuer den Backfill.

        Leere Liste, wenn die sqlite-vec-Extension in diesem Prozess nicht
        ladbar ist -- sonst wuerde der LEFT JOIN gegen die fehlende Virtual
        Table mit ``sqlite3.OperationalError: no such table`` abbrechen
        (Plan-Risiko #521/5), statt sauber zu degradieren.
        """
        with self._connection() as conn:
            if not self.load_vec_extension(conn):
                return []
            try:
                conn.execute(_quote_embeddings_ddl(self._expected_embedding_dim(conn)))
            except sqlite3.OperationalError:
                return []
            sql = """
                SELECT q.quote_id, q.paper_id, q.verbatim, q.context_before, q.context_after
                FROM quotes q
                LEFT JOIN quote_embeddings e ON e.quote_id = q.quote_id
                WHERE e.quote_id IS NULL
                ORDER BY q.created_at, q.quote_id
            """
            params: list = []
            if limit is not None and limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(r) for r in rows]
