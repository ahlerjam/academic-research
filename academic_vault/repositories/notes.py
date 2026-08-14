"""Notes-Aggregat: CRUD der ``notes``-Tabelle und ihre FTS5-Suche (Issue #462).

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import time
from uuid import uuid4

from ..vault_text import _sanitize_fts5_query, escape_like
from ._base import ConnectionHost


class NotesRepo(ConnectionHost):
    """Notes-CRUD samt FTS5-Suche (Issue #462)."""

    # ------------------------------------------------------------------
    # Notes CRUD + FTS5-Suche (Issue #462)
    # ------------------------------------------------------------------

    def add_note(
        self,
        paper_id: str,
        text: str,
        tags: str | None = None,
        page: int | None = None,
    ) -> str:
        """INSERT einer Notiz/eines Exzerpts. Gibt note_id (UUID) zurueck.

        Args:
            page: Optionale Seitenangabe (AC2) -- Notizen ohne konkreten
                Seitenbezug (z. B. quellenuebergreifende Synthese) bleiben
                zulaessig, ``page`` defaultet auf ``None``.
        """
        note_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO notes (note_id, paper_id, text, tags, created_at, page)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (note_id, paper_id, text, tags, now, page),
            )
        return note_id

    def get_note(self, note_id: str) -> dict | None:
        """Gibt Note-Record als dict zurueck oder None."""
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
        return dict(row) if row is not None else None

    def find_notes(
        self,
        paper_id: str,
        query: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Notizen fuer ein Paper, optional per text-LIKE-Filter (Muster find_quotes)."""
        with self._connection() as conn:
            if query:
                rows = conn.execute(
                    "SELECT * FROM notes WHERE paper_id = ? "
                    "AND text LIKE ? ESCAPE '\\' ORDER BY created_at LIMIT ?",
                    (paper_id, f"%{escape_like(query)}%", k),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notes WHERE paper_id = ? ORDER BY created_at LIMIT ?",
                    (paper_id, k),
                ).fetchall()
        return [dict(r) for r in rows]

    def search_notes(self, query: str, k: int = 5) -> list[dict]:
        """FTS5-Volltextsuche in notes_fts. Gibt [{note_id, paper_id, snippet, score}] zurueck.

        Analog zu ``server.search_papers()``, aber ohne Rerank-/Hybrid-Pfad
        (Issue #462 AC3+AC4): Notizen sind kurze, manuell verfasste
        Exzerpte -- BM25 allein deckt "Exzerpte beim Kapitelschreiben
        auffindbar" bereits ab, eine vec0-Embedding-Pipeline waere hier
        unverhaeltnismaessig. Leere/rein aus FTS5-Sonderzeichen bestehende
        Queries liefern ``[]`` statt ``sqlite3.OperationalError`` (Muster
        Issue #369).
        """
        sanitized = _sanitize_fts5_query(query)
        if not sanitized:
            return []
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT note_id,
                       paper_id,
                       snippet(notes_fts, -1, '<b>', '</b>', '...', 10) AS snippet,
                       rank AS score
                FROM notes_fts
                WHERE notes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (sanitized, k),
            ).fetchall()
        return [dict(r) for r in rows]
