"""Empirie-Aggregat: Transkript-Segmente und Kodierungen des eigenen
Erhebungsmaterials (Issue #473).

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import time
from uuid import uuid4

from ..vault_schema import VALID_CATEGORY_ORIGINS
from ._base import ConnectionHost


class EmpiricsRepo(ConnectionHost):
    """Transkript-Segmente und Kodierungen des Erhebungsmaterials (Issue #473)."""

    # ------------------------------------------------------------------
    # Empirischer Teil: Transkript-Segmente + Kodierungen (Issue #473)
    # ------------------------------------------------------------------

    @staticmethod
    def _segment_id(paper_id: str, seq: int) -> str:
        """Deterministische ``segment_id`` aus (paper_id, seq).

        Bewusst kein ``uuid4()``: ein zweiter Import derselben Transkriptdatei
        muss dieselbe Stelle wiedertreffen statt eine zweite anzulegen -- die
        Stellenangabe "Abs. 12" waere sonst nicht mehr eindeutig.
        """
        return f"{paper_id}#seg-{seq}"

    def add_transcript_segment(
        self,
        paper_id: str,
        seq: int,
        text: str,
        speaker: str | None = None,
        timecode: str | None = None,
    ) -> str:
        """Upsert eines Transkript-Segments. Gibt die ``segment_id`` zurueck.

        ``seq`` ist die zitierfaehige Absatznummer innerhalb des Transkripts
        und zugleich der Idempotenz-Schluessel (UNIQUE(paper_id, seq)): ein
        erneuter Import derselben Datei aktualisiert die Zeile, statt eine
        zweite anzulegen.

        Raises:
            ValueError: Wenn ``seq`` kleiner als 1 ist -- eine Stellenangabe
                "Abs. 0" waere im Fliesstext nicht auffindbar.
        """
        if seq < 1:
            raise ValueError(f"seq muss >= 1 sein (bekommen: {seq})")

        segment_id = self._segment_id(paper_id, seq)
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO transcript_segments
                  (segment_id, paper_id, seq, speaker, timecode, text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id, seq) DO UPDATE SET
                  speaker  = excluded.speaker,
                  timecode = excluded.timecode,
                  text     = excluded.text
                """,
                (segment_id, paper_id, seq, speaker, timecode, text, now),
            )
        return segment_id

    def list_transcript_segments(self, paper_id: str) -> list[dict]:
        """Gibt alle Segmente eines Transkripts in ``seq``-Reihenfolge zurueck."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM transcript_segments WHERE paper_id = ? ORDER BY seq",
                (paper_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_coding(
        self,
        paper_id: str,
        category: str,
        category_origin: str,
        segment_id: str | None = None,
        quote_id: str | None = None,
        memo: str | None = None,
    ) -> str:
        """INSERT einer Kategorienzuordnung. Gibt ``coding_id`` (UUID) zurueck.

        Args:
            category_origin: ``"induktiv"`` (am Material entwickelt) oder
                ``"deduktiv"`` (aus der Theorie abgeleitet). Die Validierung
                liegt hier statt allein im CHECK-Constraint, damit jeder
                Aufrufweg dieselbe lesbare Meldung bekommt statt eines rohen
                ``sqlite3.IntegrityError`` (Muster ``add_quote(stance=...)``).
            quote_id: Ankerbeispiel. Bleibt ``None``, solange keines
                ausgewaehlt ist -- ein Ankerzitat wird nie erfunden.

        Raises:
            ValueError: Bei leerer ``category`` oder unbekannter
                ``category_origin``.
        """
        if not category.strip():
            raise ValueError("category darf nicht leer sein")
        if category_origin not in VALID_CATEGORY_ORIGINS:
            raise ValueError(
                f"Ungueltiger category_origin '{category_origin}' -- "
                f"erlaubt: {sorted(VALID_CATEGORY_ORIGINS)}"
            )

        coding_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT INTO codings
                  (coding_id, paper_id, segment_id, quote_id, category,
                   category_origin, memo, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    coding_id,
                    paper_id,
                    segment_id,
                    quote_id,
                    category.strip(),
                    category_origin,
                    memo,
                    now,
                ),
            )
        return coding_id

    def list_codings(
        self,
        paper_id: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Gibt Kodierungen zurueck, optional nach Paper und/oder Kategorie gefiltert."""
        clauses = []
        params: list = []
        if paper_id is not None:
            clauses.append("paper_id = ?")
            params.append(paper_id)
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM codings {where} ORDER BY category, created_at",
                params,
            ).fetchall()
        return [dict(r) for r in rows]
