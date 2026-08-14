"""Bewertungs-Aggregat: ausgeschlossene Quellen, Risk-of-Bias-Assessments
und Score-Historie.

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import time
from uuid import uuid4

from ._base import ConnectionHost


class AppraisalRepo(ConnectionHost):
    """Ausgeschlossene Quellen, Risk-of-Bias-Assessments und Score-Historie."""

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
