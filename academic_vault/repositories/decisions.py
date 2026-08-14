"""Decisions-Aggregat: das Entscheidungsprotokoll des Vaults.

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import time
from uuid import uuid4

from ._base import ConnectionHost


class DecisionsRepo(ConnectionHost):
    """Das Entscheidungsprotokoll des Vaults."""

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
