"""Chunk-Aggregat: ``chunk_embeddings`` samt Kontextsatz-Anreicherung
(Contextual Retrieval, Issue #109/#783).

Erbt von :class:`~academic_vault.repositories.vectors.VectorsRepo`, weil
jeder Chunk-Schreibpfad seinen Vektor ueber ``_mirror_chunk_vector()``
in die vec0-Tabelle spiegelt -- eine echte Abhaengigkeit, keine
Bequemlichkeit.

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import contextlib
import json
import sqlite3
import time
from uuid import uuid4

from ..vault_schema import VALID_CHUNK_CONTEXT_SOURCES
from ..vault_text import csl_title, csl_year
from .vectors import VectorsRepo


class ChunksRepo(VectorsRepo):
    """``chunk_embeddings`` samt Kontextsatz-Anreicherung (#109/#783)."""

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
        section_title: str | None = None,
        page_start: int | None = None,
        page_end: int | None = None,
        context_source: str = "metadata",
    ) -> str:
        """INSERT eines Chunk-Embeddings. Gibt chunk_id (UUID) zurueck.

        Args:
            paper_id: Referenz auf papers.paper_id.
            chunk_text: Originaler Chunk-Text.
            context_sentence: 1-Satz-Kontext.
            embedding_text: Kombinierter Text (context_sentence + chunk_text).
            embedding_vector: Serialisierter Embedding-Vektor (bytes) oder None.
            section_title: Abschnittstitel des Chunks (Issue #728). ``None``,
                wenn keine Lokation bekannt ist (z. B. Aufrufer aelter als
                #728).
            page_start: Erste Seite des Chunks (Issue #728). ``None`` wie oben.
            page_end: Letzte Seite des Chunks (Issue #728). ``None`` wie oben.
            context_source: Herkunft von ``context_sentence`` (Issue #783).
                Default ``"metadata"`` -- der deterministische Satz aus
                ``chunking.default_context_sentence()``, den JEDER bestehende
                Aufrufer bislang schreibt. ``"model"`` ist ausschliesslich dem
                Carry-over in ``ingest.py`` und dem direkten Aufbau eines
                Test-Fixtures vorbehalten -- der reguläre Anreicherungsweg
                laeuft ueber :meth:`update_chunk_context`.

        Raises:
            ValueError: ``context_source`` liegt nicht in
                ``VALID_CHUNK_CONTEXT_SOURCES``.
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
            EmbeddingDimensionMismatchError: ``embedding_vector`` hat nicht die
                Breite des Bestands (Issue #629). Frueher landete so ein Vektor
                in ``chunk_embeddings``, waehrend der vec0-Spiegel ihn still
                verwarf -- der Vault trug danach zwei unvergleichbare
                Vektorraeume, und jede Suche sah nur einen davon.
        """
        if context_source not in VALID_CHUNK_CONTEXT_SOURCES:
            raise ValueError(
                f"Ungueltiger context_source '{context_source}' -- erlaubt: "
                f"{sorted(VALID_CHUNK_CONTEXT_SOURCES)}"
            )
        chunk_id = str(uuid4())
        now = int(time.time())
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            if embedding_vector:
                self._assert_vector_dim(conn, embedding_vector)
            conn.execute(
                """
                INSERT INTO chunk_embeddings
                  (chunk_id, paper_id, chunk_text, context_sentence, embedding_text,
                   embedding_vector, created_at, section_title, page_start, page_end,
                   context_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    paper_id,
                    chunk_text,
                    context_sentence,
                    embedding_text,
                    embedding_vector,
                    now,
                    section_title,
                    page_start,
                    page_end,
                    context_source,
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

    def get_chunk_by_id(self, chunk_id: str) -> dict | None:
        """Gibt einen einzelnen Chunk-Embedding-Datensatz zurueck, oder ``None`` (#783).

        Grundlage fuer ``server.enrich_chunk_contexts()``: der Aufrufer
        uebergibt nur ``chunk_id`` + neuen Kontextsatz, ``chunk_text`` fuer den
        ``embedding_text``-Aufbau kommt aus dem Vault, nie vom Client
        uebernommen.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM chunk_embeddings WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def get_first_chunk_text(self, paper_id: str) -> str | None:
        """Gibt den chunk_text des ersten Chunks eines Papers zurueck (nach created_at, chunk_id).

        Laengst viel effizienter als get_chunk_embeddings, wenn nur der Text
        des ersten Chunks benoetigt wird — vermeidet das Laden von Vektor-BLOBs
        und anderen Spalten.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT chunk_text FROM chunk_embeddings WHERE paper_id = ? ORDER BY created_at, chunk_id LIMIT 1",
                (paper_id,),
            ).fetchone()
        return row["chunk_text"] if row else None

    def update_chunk_context(
        self,
        chunk_id: str,
        context_sentence: str,
        embedding_text: str,
        embedding_vector: bytes | None,
        context_source: str = "model",
    ) -> None:
        """Schreibt Kontextsatz + embedding_text + Vektor + vec0-Spiegel als EIN Tripel (#783).

        Nie ein Teil-Update: alle drei inhaltlich zusammenhaengenden Felder
        aendern sich in derselben Transaktion, sonst koennte ``embedding_text``
        von einem anderen Kontextsatz stammen als der gespeicherte Vektor.
        ``chunk_text`` selbst bleibt unangetastet -- dieser Weg embedded nur
        neu, re-chunked nie (kein FTS5-Trigger feuert, da ``chunk_text``
        unveraendert bleibt).

        Args:
            chunk_id: Referenz auf ``chunk_embeddings.chunk_id``.
            context_sentence: Neuer (i. d. R. inhaltlicher) Kontextsatz.
            embedding_text: ``context_sentence`` + ``chunk_text`` (Aufrufer
                baut das ueber ``embeddings.build_contextual_embedding_text``).
            embedding_vector: Serialisierter Vektor fuer ``embedding_text``,
                oder ``None``.
            context_source: Herkunft, Default ``"model"`` (Issue #783).

        Raises:
            ValueError: ``context_source`` ist ungueltig, oder ``chunk_id``
                verweist auf keinen bestehenden Chunk.
            VaultLockedError: Vault ist gesperrt (Material-Passport-Lock).
            EmbeddingDimensionMismatchError: ``embedding_vector`` hat nicht die
                Breite des Bestands (Issue #629).
        """
        if context_source not in VALID_CHUNK_CONTEXT_SOURCES:
            raise ValueError(
                f"Ungueltiger context_source '{context_source}' -- erlaubt: "
                f"{sorted(VALID_CHUNK_CONTEXT_SOURCES)}"
            )
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            if embedding_vector:
                self._assert_vector_dim(conn, embedding_vector)
            cursor = conn.execute(
                "UPDATE chunk_embeddings SET context_sentence = ?, embedding_text = ?, "
                "embedding_vector = ?, context_source = ? WHERE chunk_id = ?",
                (context_sentence, embedding_text, embedding_vector, context_source, chunk_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"vault.update_chunk_context: Chunk '{chunk_id}' nicht gefunden")
            self._mirror_chunk_vector(conn, chunk_id, embedding_vector)

    def pending_context_chunks(self, paper_id: str | None = None, limit: int = 64) -> list[dict]:
        """Chunks ohne inhaltliche Anreicherung, in Dokumentreihenfolge (#783).

        Sortiert nach ``rowid`` -- der tatsaechlichen Einfuegereihenfolge, die
        bei ``chunk_pages()`` der Reihenfolge im Dokument entspricht. NICHT
        nach ``created_at``/``chunk_id``: ``created_at`` hat nur Sekunden-
        Aufloesung (ein ganzes Paper wird i. d. R. innerhalb einer Sekunde
        eingebettet, die Sortierung waere dann zufaellig) und ``chunk_id`` ist
        eine UUID ohne jede Ordnungsbeziehung zum Text.

        Ein Chunk gilt als "pending", solange ``context_source`` NICHT
        ``'model'`` ist -- das schliesst sowohl den Default ``'metadata'`` als
        auch ``NULL`` (Bestandschunks vor Schema 15) ein.

        Args:
            paper_id: Nur Chunks dieses Papers. ``None`` = vault-weit (fuer
                einen Nachtrag auf einem Bestandsvault, s. Plan-Kommentar #710).
            limit: Obergrenze der zurueckgegebenen Chunks.

        Returns:
            ``list[dict]`` mit ``chunk_id``, ``paper_id``, ``chunk_text``,
            ``section_title``, ``page_start``, ``page_end``, sowie ``title``
            und ``year`` aus ``papers.csl_json`` (``None``, wenn nicht
            ermittelbar) -- fuer einen Agenten, der den Kontextsatz ohne
            weiteren ``vault.get_paper()``-Aufruf verfassen soll.
        """
        query = (
            "SELECT ce.chunk_id, ce.paper_id, ce.chunk_text, ce.section_title, "
            "ce.page_start, ce.page_end, p.csl_json "
            "FROM chunk_embeddings ce JOIN papers p ON p.paper_id = ce.paper_id "
            "WHERE ce.context_source IS NOT 'model'"
        )
        params: list[object] = []
        if paper_id is not None:
            query += " AND ce.paper_id = ?"
            params.append(paper_id)
        query += " ORDER BY ce.rowid LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()

        results: list[dict] = []
        for row in rows:
            try:
                csl = json.loads(row["csl_json"])
            except (json.JSONDecodeError, TypeError):
                csl = {}
            if not isinstance(csl, dict):
                csl = {}
            results.append(
                {
                    "chunk_id": row["chunk_id"],
                    "paper_id": row["paper_id"],
                    "chunk_text": row["chunk_text"],
                    "section_title": row["section_title"],
                    "page_start": row["page_start"],
                    "page_end": row["page_end"],
                    "title": csl_title(csl),
                    "year": csl_year(csl),
                }
            )
        return results

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
