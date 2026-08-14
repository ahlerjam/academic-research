"""Figures-Aggregat: CRUD der ``figures``-Tabelle und ihre Referenzsuche.

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import time
from uuid import uuid4

from ..vault_text import _parse_figure_reference, escape_like
from ._base import ConnectionHost


class FiguresRepo(ConnectionHost):
    """Figures-CRUD samt Caption- und Referenzsuche (Issue #379)."""

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
