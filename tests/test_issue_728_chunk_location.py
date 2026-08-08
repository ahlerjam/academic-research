"""Tests fuer Issue #728: Fundstelle (Sektion + Seitenbereich) des Gewinner-Chunks
in der paperzentrierten Ausgabe von vault.search.

TDD: Tests werden zuerst geschrieben (RED), dann Implementierung (GREEN).
"""

import json
import sqlite3
from pathlib import Path


def _make_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "vault.db")
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    db.init_schema()
    return db_path


# ---------------------------------------------------------------------------
# Schema/Migration
# ---------------------------------------------------------------------------


class TestChunkLocationSchema:
    """chunk_embeddings traegt section_title/page_start/page_end (additiv)."""

    def test_fresh_db_has_location_columns(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunk_embeddings)")}
        finally:
            conn.close()
        assert {"section_title", "page_start", "page_end"} <= columns

    def test_migration_adds_columns_to_legacy_db_idempotently(self, tmp_path):
        """migrate.add_chunk_location_columns() ist mehrfach aufrufbar (Idempotenz)."""
        from academic_vault import migrate

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

        migrate.add_chunk_location_columns(db_path)
        migrate.add_chunk_location_columns(db_path)  # zweiter Aufruf darf nicht crashen

        conn = sqlite3.connect(db_path)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunk_embeddings)")}
        finally:
            conn.close()
        assert {"section_title", "page_start", "page_end"} <= columns


# ---------------------------------------------------------------------------
# db.VaultDB.add_chunk_embedding()
# ---------------------------------------------------------------------------


class TestAddChunkEmbeddingLocation:
    def test_add_chunk_embedding_stores_location(self, tmp_path):
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        db = VaultDB(db_path)
        csl = {"type": "article-journal", "title": "T"}
        db.add_paper("p1", json.dumps(csl))

        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Text",
            context_sentence="Kontext",
            embedding_text="Kontext Text",
            embedding_vector=None,
            section_title="Methodik",
            page_start=3,
            page_end=4,
        )

        stored = db.get_chunk_embeddings("p1")[0]
        assert stored["chunk_id"] == chunk_id
        assert stored["section_title"] == "Methodik"
        assert stored["page_start"] == 3
        assert stored["page_end"] == 4

    def test_add_chunk_embedding_location_defaults_to_none(self, tmp_path):
        """Rueckwaertskompatibilitaet: bestehende Aufrufer ohne Lokation."""
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        db = VaultDB(db_path)
        csl = {"type": "article-journal", "title": "T"}
        db.add_paper("p1", json.dumps(csl))

        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Text",
            context_sentence="Kontext",
            embedding_text="Kontext Text",
            embedding_vector=None,
        )

        stored = db.get_chunk_embeddings("p1")[0]
        assert stored["section_title"] is None
        assert stored["page_start"] is None
        assert stored["page_end"] is None


# ---------------------------------------------------------------------------
# ingest.ingest_paper_embeddings() schreibt Lokation
# ---------------------------------------------------------------------------


class TestIngestWritesLocation:
    def test_ingest_writes_chunk_location(self, tmp_path):
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings

        db_path = _make_db(tmp_path)
        db = VaultDB(db_path)
        csl = {"type": "article-journal", "title": "Attention Is All You Need"}
        db.add_paper("p1", json.dumps(csl))

        class FakeEmbedder:
            dim = 8
            model_id = "fake"

            def embed_documents(self, texts):
                return [[0.1] * 8 for _ in texts]

        text = " ".join(f"wort{i}" for i in range(400))
        count = ingest_paper_embeddings(db_path, "p1", text=text, embedder=FakeEmbedder())
        assert count > 0

        chunks = db.get_chunk_embeddings("p1")
        assert chunks
        for chunk in chunks:
            assert chunk["section_title"]
            assert chunk["page_start"] is not None
            assert chunk["page_end"] is not None


# ---------------------------------------------------------------------------
# server._aggregate_chunks_to_papers() spiegelt Fundstelle des Gewinners
# ---------------------------------------------------------------------------


class TestAggregateChunksToPapersLocation:
    def test_aggregate_exposes_winner_location(self):
        """AC2: Sektion + Seitenbereich des besten Chunks landen im Paper-Dict."""
        from academic_vault.server import _aggregate_chunks_to_papers

        chunk_results = [
            {
                "chunk_id": "c1",
                "paper_id": "p001",
                "rrf_score": 0.5,
                "section_title": "Methodik",
                "page_start": 5,
                "page_end": 7,
            },
        ]

        aggregated = _aggregate_chunks_to_papers(chunk_results, k=10)

        assert aggregated[0]["section"] == "Methodik"
        assert aggregated[0]["page_start"] == 5
        assert aggregated[0]["page_end"] == 7

    def test_aggregate_keeps_winner_own_location_not_merged(self):
        """AC4-Variante: der MAX-Gewinner behaelt seine EIGENE Fundstelle,

        nicht eine aus mehreren Chunks gemergte.
        """
        from academic_vault.server import _aggregate_chunks_to_papers

        chunk_results = [
            {
                "chunk_id": "c_low",
                "paper_id": "p001",
                "rrf_score": 0.2,
                "section_title": "Einleitung",
                "page_start": 1,
                "page_end": 2,
            },
            {
                "chunk_id": "c_high",
                "paper_id": "p001",
                "rrf_score": 0.9,
                "section_title": "Ergebnisse",
                "page_start": 12,
                "page_end": 13,
            },
        ]

        aggregated = _aggregate_chunks_to_papers(chunk_results, k=10)

        assert len(aggregated) == 1
        assert aggregated[0]["section"] == "Ergebnisse"
        assert aggregated[0]["page_start"] == 12
        assert aggregated[0]["page_end"] == 13

    def test_aggregate_location_none_safe_when_chunk_has_no_location(self):
        """Bestands-Chunks vor der Migration/Fallback-Kandidaten ohne Lokation

        duerfen nicht crashen -- 'section' bleibt None.
        """
        from academic_vault.server import _aggregate_chunks_to_papers

        chunk_results = [
            {"chunk_id": "c1", "paper_id": "p001", "rrf_score": 0.5},
        ]

        aggregated = _aggregate_chunks_to_papers(chunk_results, k=10)

        assert aggregated[0].get("section") is None
        assert aggregated[0].get("page_start") is None
        assert aggregated[0].get("page_end") is None

    def test_aggregate_keeps_paper_centric_contract_minimal_reader(self):
        """AC1: ein Aufrufer, der nur paper_id/title liest, bleibt unberuehrt."""
        from academic_vault.server import _aggregate_chunks_to_papers

        chunk_results = [
            {
                "chunk_id": "c1",
                "paper_id": "p001",
                "rrf_score": 0.5,
                "section_title": "Methodik",
                "page_start": 5,
                "page_end": 7,
            },
            {
                "chunk_id": "c2",
                "paper_id": "p001",
                "rrf_score": 0.3,
                "section_title": "Diskussion",
                "page_start": 9,
                "page_end": 10,
            },
        ]

        aggregated = _aggregate_chunks_to_papers(chunk_results, k=10)

        assert len(aggregated) == 1
        assert aggregated[0]["paper_id"] == "p001"
