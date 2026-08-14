"""Volltext-Aggregat: ``paper_fulltext`` + ``papers_fts``-Index (Issue #373).

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import time

from ._base import ConnectionHost


class FulltextRepo(ConnectionHost):
    """Volltext-Index eines Papers (``paper_fulltext``/``papers_fts``, Issue #373)."""

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

    def papers_with_fulltext(self, limit: int | None = None) -> list[dict]:
        """Papers mit hinterlegtem PDF-Pfad UND bereits vorhandenem Volltext-Eintrag.

        Pendant zu :meth:`papers_missing_fulltext`: Kandidatenliste fuer den
        Re-Extraktions-Nachlauf (``migrate.reextract_fulltext``, Issue #897),
        der bereits im Vault liegende (ggf. mit Silbentrennungs-Artefakten
        behaftete) Volltexte ueberschreibt statt nur Luecken zu fuellen.
        """
        sql = """
            SELECT p.paper_id, p.pdf_path
            FROM papers p
            JOIN paper_fulltext f ON f.paper_id = p.paper_id
            WHERE p.pdf_path IS NOT NULL AND trim(p.pdf_path) != ''
            ORDER BY p.added_at, p.paper_id
        """
        params: list = []
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
