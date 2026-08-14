"""Vektor-Aggregat: Embedding-Bestand (``embedding_meta``, Issue #629),
der vec0-Spiegel der Chunk-Vektoren und die KNN-Suche (Issue #372).

Reiner Move aus der frueheren ``academic_vault/db.py`` (Issue #841) --
die Methodenkoerper sind unveraendert.
"""

import contextlib
import math
import sqlite3
import time
from collections.abc import Sequence

from ..embedding_model import (
    DEFAULT_EMBEDDING_DIM,
    deserialize_f32,
    dimension_mismatch_error,
    serialize_f32,
)
from ..vault_schema import _chunk_vectors_ddl, _quote_embeddings_ddl
from ._base import ConnectionHost


class VectorsRepo(ConnectionHost):
    """Embedding-Bestand (#629), vec0-Spiegel und KNN-Suche ueber Chunks (#372)."""

    # ------------------------------------------------------------------
    # Embedding-Bestand: Modell-ID + Dimension (Issue #629)
    # ------------------------------------------------------------------

    def expected_embedding_dim(self) -> int:
        """Dimension, die dieser Vault von einem Embedder erwartet (#629)."""
        with self._connection() as conn:
            return self._expected_embedding_dim(conn)

    def embedding_inventory(self) -> dict | None:
        """Modell-ID, Dimension und Zeitstempel des Bestands -- oder ``None``.

        ``None`` heisst "noch nie ein Embedding geschrieben" (bzw. Bestands-DB
        vor Schema 8), nicht "Dimension unbekannt": die erwartete Breite
        liefert in dem Fall :meth:`expected_embedding_dim`.
        """
        with self._connection() as conn:
            try:
                row = conn.execute(
                    "SELECT model_id, dim, updated_at FROM embedding_meta WHERE id = 1"
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        return dict(row) if row is not None else None

    def _embedding_inventory_is_empty(self, conn: sqlite3.Connection) -> bool:
        """Ob im Vault ueberhaupt Vektoren liegen, die ein Wechsel entwerten koennte."""
        row = conn.execute(
            "SELECT 1 FROM chunk_embeddings WHERE embedding_vector IS NOT NULL LIMIT 1"
        ).fetchone()
        if row is not None:
            return False
        if not self.load_vec_extension(conn):
            return True
        try:
            return conn.execute("SELECT count(*) FROM quote_embeddings").fetchone()[0] == 0
        except sqlite3.OperationalError:
            return True

    def _write_embedding_meta(
        self, conn: sqlite3.Connection, model_id: str | None, dim: int
    ) -> None:
        """Schreibt die Singleton-Zeile in ``embedding_meta`` (Upsert)."""
        conn.execute(
            "INSERT INTO embedding_meta (id, model_id, dim, updated_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET model_id = excluded.model_id, "
            "dim = excluded.dim, updated_at = excluded.updated_at",
            (model_id, dim, int(time.time())),
        )

    def _rebuild_vector_tables(self, conn: sqlite3.Connection, dim: int) -> None:
        """Legt die vec0-Tabellen in neuer Breite an (DROP + CREATE).

        vec0 kann die Spaltenbreite nicht aendern, also ist der Neuaufbau der
        einzige Weg. Aufrufer muessen sicherstellen, dass der Inhalt entweder
        leer oder rekonstruierbar ist (``migrate.reindex_embeddings``).
        """
        if not self.load_vec_extension(conn):
            return
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("DROP TABLE IF EXISTS chunk_vectors")
            conn.execute("DROP TABLE IF EXISTS quote_embeddings")
            conn.execute(_chunk_vectors_ddl(dim))
            conn.execute(_quote_embeddings_ddl(dim))

    def register_embedding_inventory(self, model_id: str | None, dim: int) -> None:
        """Meldet Modell und Dimension an, bevor Vektoren geschrieben werden (#629).

        Drei Ausgaenge:

        * **Leerer Bestand** -- die Dimension wird uebernommen, die vec0-Tabellen
          werden in dieser Breite neu angelegt. Ein frischer Vault laesst sich so
          ohne Re-Index mit jedem Modell betreiben.
        * **Gleiche Dimension** -- nur die Modell-ID wird nachgefuehrt.
        * **Abweichende Dimension bei vorhandenem Bestand** --
          ``EmbeddingDimensionMismatchError``. Das ist der Fall, den #629
          adressiert: stillschweigend weiterzuschreiben ergaebe zwei
          unvergleichbare Vektorraeume in derselben Tabelle.

        Raises:
            ValueError: ``dim`` ist kein positiver Wert.
            EmbeddingDimensionMismatchError: Bestand hat eine andere Breite.
            VaultLockedError: Vault ist gesperrt (nur wenn geschrieben wuerde).
        """
        if dim <= 0:
            raise ValueError(f"Embedding-Dimension muss positiv sein, war {dim}")
        with self._connection(commit=True) as conn:
            try:
                row = conn.execute(
                    "SELECT model_id, dim FROM embedding_meta WHERE id = 1"
                ).fetchone()
            except sqlite3.OperationalError:
                # Bestands-DB vor Schema 8: init_schema() legt die Tabelle an.
                return
            vault_dim = int(row["dim"]) if row is not None and row["dim"] else None
            if vault_dim is None:
                # Kein Bestandsnachweis: Legacy-Vaults sind per Definition in
                # DEFAULT_EMBEDDING_DIM gebaut -- alles andere braucht einen
                # leeren Bestand oder einen Re-Index.
                vault_dim = DEFAULT_EMBEDDING_DIM
                inventory_empty = self._embedding_inventory_is_empty(conn)
            else:
                inventory_empty = (
                    self._embedding_inventory_is_empty(conn) if dim != vault_dim else False
                )

            if dim != vault_dim and not inventory_empty:
                raise dimension_mismatch_error(
                    model_id=model_id,
                    model_dim=dim,
                    vault_dim=vault_dim,
                    vault_model_id=row["model_id"] if row is not None else None,
                )

            if row is not None and int(row["dim"] or 0) == dim and row["model_id"] == model_id:
                return  # nichts zu tun -- kein Schreibzugriff, kein Lock-Check

            self._raise_if_locked(conn)
            if dim != vault_dim:
                self._rebuild_vector_tables(conn, dim)
            self._write_embedding_meta(conn, model_id, dim)

    def raise_if_locked(self) -> None:
        """Oeffentlicher Lock-Check ohne Schreibzugriff (Issue #629).

        Fuer Ablaeufe, die VOR der ersten Aenderung wissen muessen, ob sie
        ueberhaupt schreiben duerfen -- ``migrate.reindex_embeddings()`` raeumt
        vec0-Tabellen ab und darf einen gesperrten Vault nicht halb
        abgeraeumt zuruecklassen.
        """
        with self._connection() as conn:
            self._raise_if_locked(conn)

    def all_chunk_embedding_texts(self) -> list[dict]:
        """``chunk_id`` + ``embedding_text`` aller Chunks (Re-Index-Quelle, #629)."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT chunk_id, embedding_text FROM chunk_embeddings ORDER BY created_at, chunk_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def all_quotes_for_embedding(self) -> list[dict]:
        """Alle Quotes mit ihrem Kontext (Re-Index-Quelle fuer ``quote_embeddings``)."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT quote_id, verbatim, context_before, context_after FROM quotes "
                "ORDER BY created_at, quote_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def replace_chunk_vectors(
        self,
        vectors: Sequence[tuple[str, bytes]],
        model_id: str | None,
        dim: int,
    ) -> int:
        """Ersetzt ALLE Chunk-Vektoren durch die uebergebenen (Issue #629).

        Ein Transaktionsblock: Bestand leeren, vec0-Tabellen in der neuen
        Breite neu anlegen, neue Vektoren schreiben und spiegeln,
        ``embedding_meta`` fortschreiben. Chunks, fuer die kein Vektor
        uebergeben wurde, bleiben bewusst ohne (``NULL``) -- ein Vektor aus dem
        alten Modell waere nach dem Wechsel schlicht falsch.

        Returns:
            Anzahl geschriebener Vektoren.
        """
        with self._connection(commit=True) as conn:
            self._raise_if_locked(conn)
            for _, blob in vectors:
                if len(blob) != dim * 4:
                    raise dimension_mismatch_error(
                        model_id=model_id,
                        model_dim=len(blob) // 4,
                        vault_dim=dim,
                    )
            conn.execute("UPDATE chunk_embeddings SET embedding_vector = NULL")
            self._rebuild_vector_tables(conn, dim)
            self._write_embedding_meta(conn, model_id, dim)
            for chunk_id, blob in vectors:
                conn.execute(
                    "UPDATE chunk_embeddings SET embedding_vector = ? WHERE chunk_id = ?",
                    (blob, chunk_id),
                )
                self._mirror_chunk_vector(conn, chunk_id, blob)
        return len(vectors)

    # ------------------------------------------------------------------
    # Vektor-Suche ueber Chunks (Issue #372)
    # ------------------------------------------------------------------

    def _mirror_chunk_vector(
        self,
        conn: sqlite3.Connection,
        chunk_id: str,
        embedding_vector: bytes | None,
    ) -> bool:
        """Spiegelt einen Chunk-Vektor in die vec0-Tabelle. Best effort.

        Gibt False zurueck, wenn kein (passender) Vektor vorliegt oder die
        sqlite-vec-Extension nicht ladbar ist — dann uebernimmt der
        Python-Fallback in :meth:`knn_chunks` die Suche. Die Breite wird gegen
        den Bestand geprueft, nicht gegen eine Konstante (#629); der laute
        Fehler bei Abweichung kommt von den aufrufenden Schreibpfaden.
        """
        if not embedding_vector:
            return False
        dim = self._expected_embedding_dim(conn)
        if len(embedding_vector) != dim * 4:
            return False
        if not self.load_vec_extension(conn):
            return False
        try:
            conn.execute(_chunk_vectors_ddl(dim))
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vectors (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, embedding_vector),
            )
        except sqlite3.OperationalError:
            return False
        return True

    def sync_chunk_vectors(self) -> int:
        """Legt die vec0-Tabelle an und spiegelt vorhandene Chunk-Vektoren hinein.

        Idempotent; ohne ladbare sqlite-vec-Extension ein No-op (Rueckgabe 0).
        Gibt die Anzahl gespiegelter Vektoren zurueck.
        """
        mirrored = 0
        with self._connection(commit=True) as conn:
            if not self.load_vec_extension(conn):
                return 0
            dim = self._expected_embedding_dim(conn)
            try:
                conn.execute(_chunk_vectors_ddl(dim))
            except sqlite3.OperationalError:
                return 0
            rows = conn.execute(
                "SELECT chunk_id, embedding_vector FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (dim * 4,),
            ).fetchall()
            for row in rows:
                if self._mirror_chunk_vector(conn, row["chunk_id"], row["embedding_vector"]):
                    mirrored += 1
        return mirrored

    def knn_chunks(self, query_vector: Sequence[float], k: int = 10) -> list[dict]:
        """K-Nearest-Neighbour-Suche ueber chunk_embeddings.

        Primaerpfad ist die vec0-Virtual-Table ``chunk_vectors``; ist die
        sqlite-vec-Extension nicht ladbar (Python-Builds ohne
        ``--enable-loadable-sqlite-extensions``, u. a. auf macOS) oder der
        vec0-Spiegel unvollstaendig, wird dieselbe Suche in Python ueber die
        BLOBs in ``chunk_embeddings`` gerechnet.

        Beide Pfade nutzen die euklidische Distanz. Da alle Vektoren
        L2-normalisiert gespeichert werden, ist deren Rangfolge identisch zur
        Kosinus-Rangfolge — und beide Pfade liefern dieselbe Reihenfolge.

        Passt die Breite des Query-Vektors nicht zum Bestand, wirft die Methode
        ``EmbeddingDimensionMismatchError`` (Issue #629), statt lautlos eine
        leere Trefferliste zu liefern: beide Pfade filtern die Kandidaten nach
        Byte-Laenge, ein 1024d-Query auf einem 384d-Bestand haette also
        schlicht "nichts gefunden" gemeldet -- ununterscheidbar von "es gibt
        keine passenden Chunks".

        Returns:
            Liste aus ``{chunk_id, paper_id, chunk_text, distance}``,
            aufsteigend nach Distanz (nahester Treffer zuerst).

        Raises:
            EmbeddingDimensionMismatchError: Query-Dimension passt nicht zum
                Bestand.
        """
        if not query_vector or k <= 0:
            return []
        dim = len(query_vector)
        with self._connection() as conn:
            expected = self._expected_embedding_dim(conn)
            if dim != expected and not self._embedding_inventory_is_empty(conn):
                inventory = conn.execute(
                    "SELECT model_id FROM embedding_meta WHERE id = 1"
                ).fetchone()
                raise dimension_mismatch_error(
                    model_id=None,
                    model_dim=dim,
                    vault_dim=expected,
                    vault_model_id=inventory["model_id"] if inventory is not None else None,
                )
            total = conn.execute(
                "SELECT count(*) FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (dim * 4,),
            ).fetchone()[0]
            if total == 0:
                return []
            hits: list[dict] | None = None
            if dim == expected and self.load_vec_extension(conn):
                hits = self._knn_chunks_vec0(conn, query_vector, k, total)
            if hits is None:
                hits = self._knn_chunks_python(conn, query_vector, k)
        return hits

    def _knn_chunks_vec0(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        k: int,
        expected_total: int,
    ) -> list[dict] | None:
        """vec0-KNN. Gibt None zurueck, wenn der Pfad nicht verlaesslich ist."""
        try:
            mirrored = conn.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0]
        except sqlite3.OperationalError:
            return None
        if mirrored < expected_total:
            # Spiegel unvollstaendig (z. B. DB aus einer Umgebung ohne
            # Extension): lieber vollstaendig in Python rechnen als still
            # Treffer verlieren. `migrate.add_chunk_vectors_table` repariert das.
            return None
        try:
            rows = conn.execute(
                "SELECT chunk_id, distance FROM chunk_vectors "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (serialize_f32(query_vector), k),
            ).fetchall()
        except sqlite3.OperationalError:
            return None

        hits: list[dict] = []
        for row in rows:
            # Versuche, Lokationsspalten zu lesen; fallback auf Basis-Spalten für v13.
            try:
                meta = conn.execute(
                    "SELECT paper_id, chunk_text, section_title, page_start, page_end "
                    "FROM chunk_embeddings WHERE chunk_id = ?",
                    (row["chunk_id"],),
                ).fetchone()
            except sqlite3.OperationalError:
                # v13-Datenbank: section_title/page_start/page_end Spalten existieren nicht.
                meta = conn.execute(
                    "SELECT paper_id, chunk_text FROM chunk_embeddings WHERE chunk_id = ?",
                    (row["chunk_id"],),
                ).fetchone()
            if meta is None:
                continue
            hit = {
                "chunk_id": row["chunk_id"],
                "paper_id": meta["paper_id"],
                "chunk_text": meta["chunk_text"],
                "distance": float(row["distance"]),
            }
            # Lokationsspalten nur setzen, wenn sie existieren (bei v13 fallback oben).
            if "section_title" in meta.keys():
                hit["section_title"] = meta["section_title"]
                hit["page_start"] = meta["page_start"]
                hit["page_end"] = meta["page_end"]
            hits.append(hit)
        # Gleicher Tiebreaker wie im Python-Fallback: bei exakt gleicher Distanz
        # (z. B. zwei zur Query orthogonale Chunks) wuerde vec0 sonst nach
        # interner rowid ordnen und beide Pfade lieferten verschiedene
        # Reihenfolgen fuer dieselben Daten.
        hits.sort(key=lambda hit: (hit["distance"], hit["chunk_id"]))
        return hits

    def _knn_chunks_python(
        self,
        conn: sqlite3.Connection,
        query_vector: Sequence[float],
        k: int,
    ) -> list[dict]:
        """Reiner Python-Fallback: euklidische Distanz ueber alle Chunk-BLOBs."""
        dim = len(query_vector)
        # Versuche mit allen Spalten (aktuelles Schema), fallback auf Basis-Spalten
        # fuer v13-Datenbanken (Issue #728, graceful degradation).
        try:
            rows = conn.execute(
                "SELECT chunk_id, paper_id, chunk_text, embedding_vector, "
                "section_title, page_start, page_end FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (dim * 4,),
            ).fetchall()
        except sqlite3.OperationalError:
            # v13-Datenbank: section_title/page_start/page_end Spalten existieren nicht.
            rows = conn.execute(
                "SELECT chunk_id, paper_id, chunk_text, embedding_vector "
                "FROM chunk_embeddings "
                "WHERE embedding_vector IS NOT NULL AND length(embedding_vector) = ?",
                (dim * 4,),
            ).fetchall()

        hits: list[dict] = []
        for row in rows:
            try:
                vector = deserialize_f32(row["embedding_vector"])
            except ValueError:
                continue
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(query_vector, vector, strict=True))
            )
            hit = {
                "chunk_id": row["chunk_id"],
                "paper_id": row["paper_id"],
                "chunk_text": row["chunk_text"],
                "distance": distance,
            }
            # Lokationsspalten abgesichert setzen (v13-Fallback oben).
            if "section_title" in row.keys():
                hit["section_title"] = row["section_title"]
                hit["page_start"] = row["page_start"]
                hit["page_end"] = row["page_end"]
            hits.append(hit)
        # chunk_id als Tiebreaker: deterministische Reihenfolge bei Gleichstand.
        hits.sort(key=lambda hit: (hit["distance"], hit["chunk_id"]))
        return hits[:k]
