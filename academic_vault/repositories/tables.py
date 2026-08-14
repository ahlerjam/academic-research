"""Tabellen-Aggregat: strukturerhaltend extrahierte ``paper_tables``
(Issue #630) und die daraus belegten ``table_values`` (Issue #741).

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import json
import sqlite3
import time
from uuid import uuid4

from ..vault_text import format_table_evidence
from ._base import ConnectionHost


class TablesRepo(ConnectionHost):
    """Extrahierte ``paper_tables`` (#630) und belegte ``table_values`` (#741)."""

    # ------------------------------------------------------------------
    # Strukturerhaltend extrahierte Tabellen (Issue #630)
    # ------------------------------------------------------------------

    def set_paper_tables(self, paper_id: str, tables: list[dict], backend: str) -> int:
        """Ersetzt die gespeicherten Tabellen eines Papers. Gibt deren Anzahl zurueck.

        Ersetzen statt Anhaengen: eine zweite Extraktion desselben PDFs soll
        denselben Stand ergeben und nicht die alte Fassung daneben stehen
        lassen. ``papers``, ``paper_fulltext`` und ``papers_fts`` werden dabei
        nicht angefasst -- der FTS5-Volltext bleibt byteweise unveraendert.

        Args:
            paper_id: Referenz auf ``papers.paper_id``.
            tables: Tabellen aus :func:`academic_vault.tables.extract_tables`.
            backend: Herkunft der Struktur (z. B. ``"pdfplumber"``).

        Returns:
            Anzahl geschriebener Tabellen.
        """
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute("DELETE FROM paper_tables WHERE paper_id = ?", (paper_id,))
            for table in tables:
                conn.execute(
                    """
                    INSERT INTO paper_tables
                      (table_id, paper_id, page, table_index, backend,
                       n_rows, n_cols, bbox_json, rows_json, cells_json, extracted_at,
                       confidence, detection)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        paper_id,
                        int(table["page"]),
                        int(table["table_index"]),
                        backend,
                        int(table["n_rows"]),
                        int(table["n_cols"]),
                        json.dumps(table["bbox"]),
                        json.dumps(table["rows"], ensure_ascii=False),
                        json.dumps(table["cells"], ensure_ascii=False),
                        now,
                        table.get("confidence", "high"),
                        table.get("detection", "lines"),
                    ),
                )
        return len(tables)

    def list_paper_tables(self, paper_id: str, page: int | None = None) -> list[dict]:
        """Gibt die gespeicherten Tabellen eines Papers zurueck (Struktur inklusive).

        Auf einer Bestands-DB ohne ``paper_tables`` ist das Ergebnis eine leere
        Liste statt eines ``sqlite3.OperationalError``: ein Vault, in dem nie
        eine Tabelle extrahiert wurde, hat schlicht keine.
        """
        sql = "SELECT * FROM paper_tables WHERE paper_id = ?"
        params: list = [paper_id]
        if page is not None:
            sql += " AND page = ?"
            params.append(int(page))
        sql += " ORDER BY page, table_index"
        with self._connection() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        return [self._table_row_to_dict(row) for row in rows]

    @staticmethod
    def _table_row_to_dict(row: sqlite3.Row) -> dict:
        record = dict(row)
        record["rows"] = json.loads(record.pop("rows_json"))
        record["cells"] = json.loads(record.pop("cells_json"))
        record["bbox"] = json.loads(record.pop("bbox_json"))
        return record

    def get_table_cell(
        self,
        paper_id: str,
        page: int,
        table_index: int,
        row: int,
        col: int,
    ) -> dict | None:
        """Loest eine einzelne Zelle zu Wert **und** Beleg auf (Issue #630 AC2).

        Returns:
            ``{"paper_id", "page", "table_index", "row", "col", "value", "bbox",
            "backend", "confidence", "detection", "evidence"}`` oder ``None``,
            wenn es die Zelle nicht gibt. ``None`` statt eines Naeherungstreffers:
            ein geratener Beleg
            waere schlimmer als gar keiner.
        """
        with self._connection() as conn:
            try:
                found = conn.execute(
                    """
                    SELECT * FROM paper_tables
                    WHERE paper_id = ? AND page = ? AND table_index = ?
                    """,
                    (paper_id, int(page), int(table_index)),
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if found is None:
            return None

        for cell in json.loads(found["cells_json"]):
            if cell["row"] != row or cell["col"] != col:
                continue
            # Platzhalter-Zellen (geschluckt durch merging) haben kein Beleg-Recht —
            # ein Beleg ohne Koordinaten ist keiner (Issue #630 AC2). Diese Zellen
            # signalisieren nur die Lücke; sie sind nicht anquotierbar.
            if cell.get("merged_into") is not None:
                return None
            # Defensiv lesen: auf älteren DBs ohne confidence/detection Spalten sind
            # die Defaults "high"/"lines" (Migration Add­schema_for_read setzt das)
            record = dict(found)
            return {
                "paper_id": paper_id,
                "page": int(record["page"]),
                "table_index": int(record["table_index"]),
                "row": row,
                "col": col,
                "value": cell["value"],
                "bbox": cell["bbox"],
                "backend": str(record["backend"]),
                "confidence": str(record.get("confidence", "high")),
                "detection": str(record.get("detection", "lines")),
                "evidence": format_table_evidence(
                    paper_id, int(record["page"]), int(record["table_index"]), row, col
                ),
            }
        return None

    def add_table_value(
        self,
        table_value_id: str,
        paper_id: str,
        page: int,
        table_index: int,
        row: int,
        col: int,
        claimed_value: str,
        cell_value: str,
        evidence: str,
    ) -> None:
        """INSERT einer belegten Kennzahl (Issue #741).

        Reiner Schreibpfad OHNE eigene Pruefung -- die Verifikation gegen die
        tatsaechliche Zelle (:func:`academic_vault.numbers.numbers_equivalent`
        gegen :meth:`get_table_cell`) liegt beim Aufrufer
        (:func:`academic_vault.server.add_table_value`), analog zu
        ``_verify_local_verbatim`` vor ``VaultDB.add_quote``. ``INSERT OR
        REPLACE`` macht das erneute Erfassen derselben Zelle idempotent
        (``UNIQUE(paper_id, page, table_index, row, col)``, schema.sql).

        Raises:
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
        """
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO table_values
                  (table_value_id, paper_id, page, table_index, row, col,
                   claimed_value, cell_value, evidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    table_value_id,
                    paper_id,
                    page,
                    table_index,
                    row,
                    col,
                    claimed_value,
                    cell_value,
                    evidence,
                    now,
                ),
            )

    def list_table_values(self, paper_id: str | None = None) -> list[dict]:
        """Gibt erfasste Kennzahlen zurueck, optional nach Paper gefiltert (#741).

        Auf einer Bestands-DB ohne ``table_values`` ist das Ergebnis eine
        leere Liste statt eines ``sqlite3.OperationalError`` -- ein Vault, in
        dem nie eine Kennzahl erfasst wurde, hat schlicht keine (Muster
        analog ``list_paper_tables``).
        """
        sql = "SELECT * FROM table_values"
        params: list = []
        if paper_id is not None:
            sql += " WHERE paper_id = ?"
            params.append(paper_id)
        sql += " ORDER BY created_at"
        with self._connection() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        return [dict(row) for row in rows]
