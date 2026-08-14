"""Tests fuer Issue #783 (Teilschritt A von Epic #710): Kontextsatz-Schreibweg.

Neue Spalte ``chunk_embeddings.context_source``, zwei neue MCP-Tools
(``vault.pending_context_chunks``, ``vault.enrich_chunk_contexts``) und der
Carry-over-Schutz gegen Verlust einer Anreicherung bei einem erneuten
``add_paper()``-Upsert.

TDD: RED zuerst (dieser Testlauf gegen den main-Stand vor #783 schlaegt fehl),
dann GREEN durch die Implementierung in schema.sql/migrate.py/db.py/server.py/
ingest.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3

import pytest
from academic_vault import migrate, server
from academic_vault.db import VaultDB
from academic_vault.embedding_model import (
    DEFAULT_EMBEDDING_DIM,
    EmbeddingDimensionMismatchError,
    serialize_f32,
)
from academic_vault.ingest import ingest_paper_embeddings


class SizedEmbedder:
    """Deterministischer Embedder beliebiger Breite -- laedt nie Gewichte."""

    def __init__(self, dim: int, model_id: str = "test/sized") -> None:
        self.dim = dim
        self.model_id = f"{model_id}-{dim}d"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            idx = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def _make_db(db_path: str) -> VaultDB:
    db = VaultDB(db_path)
    db.init_schema()
    return db


def _seed_paper(db_path: str, paper_id: str, title: str = "T", abstract: str = "Ein Text.") -> None:
    db = _make_db(db_path)
    db.add_paper(
        paper_id, json.dumps({"type": "article-journal", "title": title, "abstract": abstract})
    )


# ---------------------------------------------------------------------------
# AC1 -- Schema/Migration
# ---------------------------------------------------------------------------


class TestSchemaMigration:
    def test_fresh_db_has_context_source_column(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _make_db(db_path)
        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunk_embeddings)")}
        finally:
            conn.close()
        assert "context_source" in columns

    def test_fresh_db_schema_version_matches_current(self, tmp_path):
        """War fest auf 15 gepinnt; seit Issue #847 (paper_tables.confidence/
        detection) ist die aktuelle Version 16 -- der Test prueft die
        eigentliche Zusicherung (frische DB steht auf CURRENT_SCHEMA_VERSION),
        nicht eine feste Zahl, die bei jeder neuen additiven Migration
        wieder anzupassen waere."""
        from academic_vault.db import CURRENT_SCHEMA_VERSION

        db_path = str(tmp_path / "vault.db")
        _make_db(db_path)
        conn = sqlite3.connect(db_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert version == CURRENT_SCHEMA_VERSION

    def test_migration_adds_column_to_legacy_db_idempotently(self, tmp_path):
        """migrate.add_chunk_context_source_column() ist mehrfach aufrufbar."""
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE chunk_embeddings (
                  chunk_id TEXT PRIMARY KEY,
                  paper_id TEXT NOT NULL,
                  chunk_text TEXT NOT NULL,
                  context_sentence TEXT NOT NULL,
                  embedding_text TEXT NOT NULL,
                  embedding_vector BLOB,
                  created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

        migrate.add_chunk_context_source_column(db_path)
        migrate.add_chunk_context_source_column(db_path)  # zweiter Aufruf darf nicht crashen

        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunk_embeddings)")}
        finally:
            conn.close()
        assert "context_source" in columns

    def test_legacy_db_migrates_via_init_schema(self, tmp_path):
        """Der reguläre Pfad: eine Bestands-DB unter Schema 15 migriert über
        VaultDB.init_schema() automatisch (Issue #368-Muster)."""
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE papers (
                  paper_id TEXT PRIMARY KEY,
                  type TEXT NOT NULL DEFAULT 'article-journal',
                  csl_json TEXT NOT NULL,
                  doi TEXT, isbn TEXT, pdf_path TEXT,
                  file_id TEXT, file_id_expires_at INTEGER,
                  page_offset INTEGER DEFAULT 0, ocr_done INTEGER DEFAULT 0
                );
                CREATE TABLE chunk_embeddings (
                  chunk_id TEXT PRIMARY KEY,
                  paper_id TEXT NOT NULL,
                  chunk_text TEXT NOT NULL,
                  context_sentence TEXT NOT NULL,
                  embedding_text TEXT NOT NULL,
                  embedding_vector BLOB,
                  created_at INTEGER NOT NULL
                );
                """
            )
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
        finally:
            conn.close()

        db = VaultDB(db_path)
        db.init_schema()

        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunk_embeddings)")}
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert "context_source" in columns
        # War fest auf 15 gepinnt; seit Issue #847 ist CURRENT_SCHEMA_VERSION 16
        # (siehe test_fresh_db_schema_version_matches_current).
        from academic_vault.db import CURRENT_SCHEMA_VERSION

        assert version == CURRENT_SCHEMA_VERSION


def _degrade_chunk_embeddings_to_schema_14(db_path: str) -> None:
    """Simuliert eine Bestands-DB unter Schema 15: ``chunk_embeddings`` OHNE
    ``context_source``, ``user_version`` auf 14 zurueckgesetzt. Alle Tabellen
    aus ``server._READ_REQUIRED_TABLES`` bleiben unangetastet vorhanden -- der
    Read-Guard ``_ensure_schema_for_read()`` prueft laut eigenem Docstring nur
    fehlende TABELLEN, nie Spalten-Drift, wuerde diese DB also faelschlich als
    "vollstaendig" ansehen (Review-Fund P1 zu PR #786/#783).

    ``ALTER TABLE ... DROP COLUMN`` scheitert hier an SQLites eigener
    Einschraenkung (keine Spalte droppen, die in einem CHECK-Constraint
    steht) -- deshalb Tabellen-Rebuild auf die tatsaechliche Schema-14-Form
    (mit ``section_title``/``page_start``/``page_end`` aus #728, noch ohne
    ``context_source`` aus #783), Daten unveraendert uebernommen.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM chunk_embeddings").fetchall()]
        conn.execute("DROP TABLE chunk_embeddings")
        conn.execute(
            """
            CREATE TABLE chunk_embeddings (
              chunk_id         TEXT PRIMARY KEY,
              paper_id         TEXT NOT NULL REFERENCES papers(paper_id),
              chunk_text       TEXT NOT NULL,
              context_sentence TEXT NOT NULL,
              embedding_text   TEXT NOT NULL,
              embedding_vector BLOB,
              created_at       INTEGER NOT NULL,
              section_title    TEXT,
              page_start       INTEGER,
              page_end         INTEGER
            )
            """
        )
        for row in rows:
            conn.execute(
                "INSERT INTO chunk_embeddings "
                "(chunk_id, paper_id, chunk_text, context_sentence, embedding_text, "
                " embedding_vector, created_at, section_title, page_start, page_end) "
                "VALUES (:chunk_id, :paper_id, :chunk_text, :context_sentence, "
                " :embedding_text, :embedding_vector, :created_at, :section_title, "
                " :page_start, :page_end)",
                row,
            )
        conn.execute("PRAGMA user_version = 14")
        conn.commit()
    finally:
        conn.close()


class TestServerReadPathMigratesLegacySchema14Db:
    """Regressionstest (Review-Fund P1, PR #786): ``server.pending_context_chunks()``

    darf auf einer Schema-14-Bestands-DB nicht mit
    ``sqlite3.OperationalError: no such column: ce.context_source`` abstuerzen.
    ``_ensure_schema_for_read()`` deckt das NICHT ab (nur Tabellen-Drift,
    s. Docstring dort) -- der Lesepfad muss deshalb unbedingt
    ``VaultDB.init_schema()`` aufrufen, wie die Schreibpfade es bereits tun.
    """

    def test_read_guard_alone_would_not_have_caught_the_drift(self, tmp_path):
        """Vorbedingung/Beweis: der (unveraenderte) Tabellen-Guard allein reicht
        hier nicht -- sonst waere die Regression nie aufgetreten."""
        from academic_vault.server import _ensure_schema_for_read

        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        VaultDB(db_path).add_chunk_embedding(
            paper_id="p1",
            chunk_text="Bestandstext",
            context_sentence="Alter Kontext.",
            embedding_text="Alter Kontext. Bestandstext",
            embedding_vector=None,
        )
        _degrade_chunk_embeddings_to_schema_14(db_path)

        _ensure_schema_for_read(db_path)  # der alte Guard allein

        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunk_embeddings)")}
        finally:
            conn.close()
        assert "context_source" not in columns, (
            "Testannahme verletzt: _ensure_schema_for_read() hat die Spalte "
            "doch repariert -- dann waere dieser Regressionstest gegenstandslos."
        )

    def test_pending_context_chunks_does_not_crash_on_legacy_db(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Bestandstext",
            context_sentence="Alter Kontext.",
            embedding_text="Alter Kontext. Bestandstext",
            embedding_vector=None,
        )
        _degrade_chunk_embeddings_to_schema_14(db_path)

        result = server.pending_context_chunks(db_path, paper_id="p1")

        assert [c["chunk_text"] for c in result] == ["Bestandstext"]

        # Server-Aufruf muss die DB dabei tatsaechlich migriert haben.
        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunk_embeddings)")}
        finally:
            conn.close()
        assert "context_source" in columns

    def test_enrich_chunk_contexts_already_migrates_legacy_db(self, tmp_path):
        """Gegenprobe (Review-Auftrag): enrich_chunk_contexts() ruft bereits

        unbedingt db.init_schema() auf und hat denselben Fund NICHT."""
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Bestandstext",
            context_sentence="Alter Kontext.",
            embedding_text="Alter Kontext. Bestandstext",
            embedding_vector=None,
        )
        _degrade_chunk_embeddings_to_schema_14(db_path)

        result = server.enrich_chunk_contexts(
            db_path,
            items=[{"chunk_id": chunk_id, "context_sentence": "Ein inhaltlicher Satz."}],
            embedder=SizedEmbedder(8),
        )

        assert result["updated"] == [chunk_id]


# ---------------------------------------------------------------------------
# AC2 -- db.VaultDB.pending_context_chunks()
# ---------------------------------------------------------------------------


class TestPendingContextChunks:
    def test_orders_by_rowid_document_order(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)

        # Bewusst in umgekehrter "logischer" Reihenfolge chunk_id-maessig
        # anlegen (UUIDs sind nicht sortierbar) -- die Reihenfolge muss trotzdem
        # der Einfuegereihenfolge (rowid) entsprechen.
        for text in ("erster Chunk", "zweiter Chunk", "dritter Chunk"):
            db.add_chunk_embedding(
                paper_id="p1",
                chunk_text=text,
                context_sentence="Kontext.",
                embedding_text=f"Kontext. {text}",
                embedding_vector=None,
            )

        pending = db.pending_context_chunks(paper_id="p1")
        texts = [c["chunk_text"] for c in pending]
        assert texts == ["erster Chunk", "zweiter Chunk", "dritter Chunk"]

    def test_excludes_already_enriched_chunks(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)

        c1 = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="pending chunk",
            context_sentence="Kontext.",
            embedding_text="Kontext. pending chunk",
            embedding_vector=None,
        )
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="enriched chunk",
            context_sentence="Modellsatz.",
            embedding_text="Modellsatz. enriched chunk",
            embedding_vector=None,
            context_source="model",
        )

        pending = db.pending_context_chunks(paper_id="p1")
        assert [c["chunk_id"] for c in pending] == [c1]

    def test_null_context_source_counts_as_pending(self, tmp_path):
        """Bestandschunks vor Schema 15 haben context_source IS NULL -- pending."""
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO chunk_embeddings "
                "(chunk_id, paper_id, chunk_text, context_sentence, embedding_text, "
                " embedding_vector, created_at, context_source) "
                "VALUES ('legacy1', 'p1', 'alter Chunk', 'alter Kontext', "
                " 'alter Kontext alter Chunk', NULL, 1, NULL)"
            )
            conn.commit()
        finally:
            conn.close()

        db = VaultDB(db_path)
        pending = db.pending_context_chunks(paper_id="p1")
        assert [c["chunk_id"] for c in pending] == ["legacy1"]

    def test_includes_title_and_year_from_csl_json(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1", title="Attention Is All You Need")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Text",
            context_sentence="Kontext.",
            embedding_text="Kontext. Text",
            embedding_vector=None,
        )

        pending = db.pending_context_chunks(paper_id="p1")
        assert pending[0]["title"] == "Attention Is All You Need"

    def test_respects_limit(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        for i in range(5):
            db.add_chunk_embedding(
                paper_id="p1",
                chunk_text=f"chunk {i}",
                context_sentence="Kontext.",
                embedding_text=f"Kontext. chunk {i}",
                embedding_vector=None,
            )

        pending = db.pending_context_chunks(paper_id="p1", limit=2)
        assert len(pending) == 2

    def test_paper_id_none_is_vault_wide(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        _seed_paper(db_path, "p2")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="chunk p1",
            context_sentence="Kontext.",
            embedding_text="Kontext. chunk p1",
            embedding_vector=None,
        )
        db.add_chunk_embedding(
            paper_id="p2",
            chunk_text="chunk p2",
            context_sentence="Kontext.",
            embedding_text="Kontext. chunk p2",
            embedding_vector=None,
        )

        pending = db.pending_context_chunks()
        assert {c["paper_id"] for c in pending} == {"p1", "p2"}


# ---------------------------------------------------------------------------
# AC3 -- db.VaultDB.update_chunk_context() / server.enrich_chunk_contexts()
# ---------------------------------------------------------------------------


class TestUpdateChunkContext:
    def test_writes_sentence_text_vector_source_as_one_triple(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Originaltext",
            context_sentence="Metadaten-Satz.",
            embedding_text="Metadaten-Satz. Originaltext",
            embedding_vector=None,
        )

        vector = serialize_f32([0.1] * DEFAULT_EMBEDDING_DIM)
        db.update_chunk_context(
            chunk_id,
            context_sentence="Inhaltlicher Satz.",
            embedding_text="Inhaltlicher Satz. Originaltext",
            embedding_vector=vector,
            context_source="model",
        )

        row = db.get_chunk_by_id(chunk_id)
        assert row["context_sentence"] == "Inhaltlicher Satz."
        assert row["embedding_text"] == "Inhaltlicher Satz. Originaltext"
        assert row["embedding_vector"] == vector
        assert row["context_source"] == "model"
        # chunk_text bleibt unangetastet -- kein Re-Chunking ueber diesen Weg.
        assert row["chunk_text"] == "Originaltext"

    def test_unknown_chunk_id_raises(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _make_db(db_path)
        db = VaultDB(db_path)
        with pytest.raises(ValueError):
            db.update_chunk_context(
                "does-not-exist",
                context_sentence="X",
                embedding_text="X",
                embedding_vector=None,
            )

    def test_invalid_context_source_raises(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Text",
            context_sentence="Kontext.",
            embedding_text="Kontext. Text",
            embedding_vector=None,
        )
        with pytest.raises(ValueError):
            db.update_chunk_context(
                chunk_id,
                context_sentence="X",
                embedding_text="X",
                embedding_vector=None,
                context_source="not-a-real-source",
            )


class TestEnrichChunkContexts:
    def _seed_pending_chunk(self, db_path: str, chunk_text: str = "Originaltext") -> str:
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        return db.add_chunk_embedding(
            paper_id="p1",
            chunk_text=chunk_text,
            context_sentence="Metadaten-Satz.",
            embedding_text=f"Metadaten-Satz. {chunk_text}",
            embedding_vector=None,
        )

    def test_writes_triple_and_mirrors_vec0(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        chunk_id = self._seed_pending_chunk(db_path)

        result = server.enrich_chunk_contexts(
            db_path,
            items=[{"chunk_id": chunk_id, "context_sentence": "Ein inhaltlicher Satz."}],
            embedder=SizedEmbedder(8),
        )

        assert result["status"] == "ok"
        assert result["updated"] == [chunk_id]
        assert result["skipped"] == []

        db = VaultDB(db_path)
        row = db.get_chunk_by_id(chunk_id)
        assert row["context_sentence"] == "Ein inhaltlicher Satz."
        assert row["embedding_text"] == "Ein inhaltlicher Satz. Originaltext"
        assert row["context_source"] == "model"
        assert row["embedding_vector"] is not None
        assert len(row["embedding_vector"]) == 8 * 4  # float32

        if db.vec_extension_loadable():
            conn = sqlite3.connect(db_path)
            try:
                db.load_vec_extension(conn)
                count = conn.execute(
                    "SELECT count(*) FROM chunk_vectors WHERE chunk_id = ?", (chunk_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            assert count == 1

    def test_second_identical_call_is_idempotent(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        chunk_id = self._seed_pending_chunk(db_path)
        items = [{"chunk_id": chunk_id, "context_sentence": "Ein inhaltlicher Satz."}]

        first = server.enrich_chunk_contexts(db_path, items=items, embedder=SizedEmbedder(8))
        db = VaultDB(db_path)
        row_after_first = db.get_chunk_by_id(chunk_id)

        second = server.enrich_chunk_contexts(db_path, items=items, embedder=SizedEmbedder(8))
        row_after_second = db.get_chunk_by_id(chunk_id)

        assert first["updated"] == second["updated"] == [chunk_id]
        assert row_after_first["context_sentence"] == row_after_second["context_sentence"]
        assert row_after_first["embedding_text"] == row_after_second["embedding_text"]
        assert row_after_first["embedding_vector"] == row_after_second["embedding_vector"]
        assert row_after_first["context_source"] == row_after_second["context_source"] == "model"

    def test_mixed_batch_empty_and_too_long_are_skipped_rest_written(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        good_id = self._seed_pending_chunk(db_path, chunk_text="guter chunk")
        _seed_second = VaultDB(db_path).add_chunk_embedding(
            paper_id="p1",
            chunk_text="leerer chunk",
            context_sentence="Metadaten-Satz.",
            embedding_text="Metadaten-Satz. leerer chunk",
            embedding_vector=None,
        )
        too_long_id = VaultDB(db_path).add_chunk_embedding(
            paper_id="p1",
            chunk_text="zu langer chunk",
            context_sentence="Metadaten-Satz.",
            embedding_text="Metadaten-Satz. zu langer chunk",
            embedding_vector=None,
        )

        too_long_sentence = " ".join(["Wort"] * 200)  # weit ueber dem Token-Budget
        result = server.enrich_chunk_contexts(
            db_path,
            items=[
                {"chunk_id": good_id, "context_sentence": "Ein guter, kurzer Satz."},
                {"chunk_id": _seed_second, "context_sentence": ""},
                {"chunk_id": too_long_id, "context_sentence": too_long_sentence},
            ],
            embedder=SizedEmbedder(8),
        )

        assert result["updated"] == [good_id]
        skipped_ids = {s["chunk_id"]: s["reason"] for s in result["skipped"]}
        assert skipped_ids[_seed_second] == "empty"
        assert skipped_ids[too_long_id] == "too-long"

        db = VaultDB(db_path)
        # Der gute Chunk wurde geschrieben ...
        assert db.get_chunk_by_id(good_id)["context_source"] == "model"
        # ... die uebersprungenen Zeilen bleiben unangetastet.
        assert db.get_chunk_by_id(_seed_second)["context_source"] == "metadata"
        assert db.get_chunk_by_id(_seed_second)["context_sentence"] == "Metadaten-Satz."
        assert db.get_chunk_by_id(too_long_id)["context_source"] == "metadata"
        assert db.get_chunk_by_id(too_long_id)["context_sentence"] == "Metadaten-Satz."

    def test_unknown_chunk_id_is_skipped_not_found(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")

        result = server.enrich_chunk_contexts(
            db_path,
            items=[{"chunk_id": "ghost-chunk", "context_sentence": "Ein Satz."}],
            embedder=SizedEmbedder(8),
        )

        assert result["updated"] == []
        assert result["skipped"] == [{"chunk_id": "ghost-chunk", "reason": "not-found"}]

    def test_no_embedder_returns_embedder_unavailable_and_writes_nothing(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        chunk_id = self._seed_pending_chunk(db_path)

        result = server.enrich_chunk_contexts(
            db_path,
            items=[{"chunk_id": chunk_id, "context_sentence": "Ein Satz."}],
            embedder=None,  # kein injizierter Embedder; get_embedder() ist in Tests geblockt
        )

        assert result == {"status": "embedder-unavailable", "updated": [], "skipped": []}

        db = VaultDB(db_path)
        row = db.get_chunk_by_id(chunk_id)
        assert row["context_source"] == "metadata"
        assert row["context_sentence"] == "Metadaten-Satz."

    def test_dimension_mismatch_raises_and_writes_nothing(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)

        # Bestand mit einem ECHTEN 384d-Vektor anlegen -- ein leerer Bestand
        # (embedding_vector=None ueberall) wuerde jede Dimension anstandslos
        # uebernehmen (siehe register_embedding_inventory-Docstring), der
        # Mismatch braucht also einen tatsaechlich befuellten Bestand.
        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Text",
            context_sentence="Metadaten-Satz.",
            embedding_text="Metadaten-Satz. Text",
            embedding_vector=serialize_f32([0.1] * 384),
        )
        db.register_embedding_inventory("test/sized-384d", 384)

        with pytest.raises(EmbeddingDimensionMismatchError):
            server.enrich_chunk_contexts(
                db_path,
                items=[{"chunk_id": chunk_id, "context_sentence": "Ein Satz."}],
                embedder=SizedEmbedder(1024),
            )

        row = db.get_chunk_by_id(chunk_id)
        assert row["context_source"] == "metadata"
        assert row["context_sentence"] == "Metadaten-Satz."


# ---------------------------------------------------------------------------
# AC -- add_paper()/ingest ohne jede Anreicherung bleibt unveraendert
# ---------------------------------------------------------------------------


class TestIngestWithoutEnrichmentUnchanged:
    def test_ingest_writes_metadata_context_source_by_default(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1", title="Ein Titel")

        text = " ".join(f"wort{i}" for i in range(400))
        count = ingest_paper_embeddings(db_path, "p1", text=text, embedder=SizedEmbedder(8))
        assert count > 0

        db = VaultDB(db_path)
        for chunk in db.get_chunk_embeddings("p1"):
            assert chunk["context_source"] == "metadata"

    def test_add_chunk_embedding_default_context_source_is_metadata(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Text",
            context_sentence="Kontext.",
            embedding_text="Kontext. Text",
            embedding_vector=None,
        )
        assert db.get_chunk_by_id(chunk_id)["context_source"] == "metadata"


# ---------------------------------------------------------------------------
# AC -- Carry-over: eine Anreicherung ueberlebt einen zweiten add_paper()
# ---------------------------------------------------------------------------


class TestCarryOverAcrossReingest:
    def test_model_context_survives_second_ingest_with_identical_chunk_text(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1", title="Ein Titel")

        text = " ".join(f"wort{i}" for i in range(400))
        count = ingest_paper_embeddings(db_path, "p1", text=text, embedder=SizedEmbedder(8))
        assert count > 0

        db = VaultDB(db_path)
        pending = db.pending_context_chunks(paper_id="p1")
        assert pending
        target_chunk_id = pending[0]["chunk_id"]
        target_chunk_text = pending[0]["chunk_text"]

        enrich_result = server.enrich_chunk_contexts(
            db_path,
            items=[{"chunk_id": target_chunk_id, "context_sentence": "Ein inhaltlicher Satz."}],
            embedder=SizedEmbedder(8),
        )
        assert enrich_result["updated"] == [target_chunk_id]

        # Zweiter Ingest desselben Papers, identischer Text -- der Normalfall
        # bei einem erneuten add_paper()-Upsert (Metadaten-Korrektur).
        count2 = ingest_paper_embeddings(db_path, "p1", text=text, embedder=SizedEmbedder(8))
        assert count2 == count

        chunks_after = db.get_chunk_embeddings("p1")
        matching = [c for c in chunks_after if c["chunk_text"] == target_chunk_text]
        assert matching, "Chunk mit identischem Text muss nach dem Re-Ingest weiter existieren"
        carried = matching[0]
        assert carried["context_source"] == "model"
        assert carried["context_sentence"] == "Ein inhaltlicher Satz."
        # chunk_id darf sich aendern (delete+reinsert), der INHALT muss ueberleben.

    def test_changed_chunk_text_does_not_carry_over_stale_context(self, tmp_path):
        """Aendert sich der Chunk-Text, gibt es keinen sicheren Bezugspunkt mehr --
        der neue Chunk bleibt beim Metadaten-Default (kein falscher Carry-over)."""
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1", title="Ein Titel")

        text_v1 = " ".join(f"alpha{i}" for i in range(400))
        ingest_paper_embeddings(db_path, "p1", text=text_v1, embedder=SizedEmbedder(8))

        db = VaultDB(db_path)
        pending = db.pending_context_chunks(paper_id="p1")
        target_chunk_id = pending[0]["chunk_id"]
        server.enrich_chunk_contexts(
            db_path,
            items=[{"chunk_id": target_chunk_id, "context_sentence": "Ein inhaltlicher Satz."}],
            embedder=SizedEmbedder(8),
        )

        # Komplett anderer Text -> kein chunk_text matcht mehr.
        text_v2 = " ".join(f"beta{i}" for i in range(400))
        ingest_paper_embeddings(db_path, "p1", text=text_v2, embedder=SizedEmbedder(8))

        chunks_after = db.get_chunk_embeddings("p1")
        assert all(c["context_source"] == "metadata" for c in chunks_after)
        assert all("alpha" not in c["chunk_text"] for c in chunks_after)


# ---------------------------------------------------------------------------
# AC -- Bestandschunks bleiben nach Migration ohne Reindex durchsuchbar
# ---------------------------------------------------------------------------


class TestPreMigrationChunksRemainSearchable:
    def test_legacy_chunk_without_context_source_is_returned_by_get_chunk_embeddings(
        self, tmp_path
    ):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO chunk_embeddings "
                "(chunk_id, paper_id, chunk_text, context_sentence, embedding_text, "
                " embedding_vector, created_at) "
                "VALUES ('legacy1', 'p1', 'Bestandstext', 'Alter Kontext', "
                " 'Alter Kontext Bestandstext', NULL, 1)"
            )
            conn.commit()
        finally:
            conn.close()

        db = VaultDB(db_path)
        chunks = db.get_chunk_embeddings("p1")
        assert len(chunks) == 1
        assert chunks[0]["chunk_text"] == "Bestandstext"
        assert chunks[0]["context_source"] is None


# ---------------------------------------------------------------------------
# add_chunk_embedding() -- context_source-Parameter
# ---------------------------------------------------------------------------


class TestAddChunkEmbeddingContextSource:
    def test_explicit_context_source_is_stored(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Text",
            context_sentence="Kontext.",
            embedding_text="Kontext. Text",
            embedding_vector=None,
            context_source="model",
        )
        assert db.get_chunk_by_id(chunk_id)["context_source"] == "model"

    def test_invalid_context_source_raises(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "p1")
        db = VaultDB(db_path)
        with pytest.raises(ValueError):
            db.add_chunk_embedding(
                paper_id="p1",
                chunk_text="Text",
                context_sentence="Kontext.",
                embedding_text="Kontext. Text",
                embedding_vector=None,
                context_source="garbage",
            )
