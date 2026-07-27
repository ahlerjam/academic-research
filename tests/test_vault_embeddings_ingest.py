"""Tests fuer die lokale Embedding-Pipeline + Ingest-Verdrahtung (#372).

Deckt den kompletten Pfad ab: Ingest -> chunk_embeddings -> KNN -> RRF.
Alle Kern-Tests injizieren den deterministischen ``fake_embedder`` aus
tests/conftest.py; es wird weder ein Modell heruntergeladen noch ein
Netzwerk-Call abgesetzt. Der Live-Test gegen das echte e5-Modell haengt hinter
``importorskip`` + Env-Gate.
"""

import json
import math
import os
import sqlite3
import struct

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str) -> None:
    """Legt ein Paper via server.add_paper an."""
    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


def _use_embedder(monkeypatch, embedder) -> None:
    """Injiziert den Test-Embedder in beide Aufrufstellen (ingest + server)."""
    monkeypatch.setattr("academic_vault.ingest.get_embedder", lambda *a, **kw: embedder)
    monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: embedder)


def _no_embedder(monkeypatch) -> None:
    """Erzwingt den Zustand 'kein Embedding-Backend installiert'."""
    monkeypatch.setattr("academic_vault.ingest.get_embedder", lambda *a, **kw: None)
    monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: None)


def _store_chunk(db_path: str, paper_id: str, text: str, embedder) -> str:
    """Schreibt einen Chunk inkl. Vektor direkt in chunk_embeddings."""
    from academic_vault.db import VaultDB
    from academic_vault.embedding_model import serialize_f32

    vector = embedder.embed_documents([text])[0]
    db = VaultDB(db_path)
    return db.add_chunk_embedding(
        paper_id=paper_id,
        chunk_text=text,
        context_sentence="",
        embedding_text=text,
        embedding_vector=serialize_f32(vector),
    )


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    """Kein Kontext-Satz-API-Call und keine Reranker-Keys in Tests."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("VAULT_CONTEXTUAL_EMBEDDING", raising=False)


# ---------------------------------------------------------------------------
# embedding_model.py — Serialisierung, Praefixe, Graceful Degradation
# ---------------------------------------------------------------------------


class TestEmbeddingModel:
    def test_embedding_dim_is_384(self):
        from academic_vault.embedding_model import EMBEDDING_DIM

        assert EMBEDDING_DIM == 384

    def test_default_model_is_multilingual_e5_small(self):
        from academic_vault.embedding_model import DEFAULT_MODEL_ID

        assert DEFAULT_MODEL_ID == "intfloat/multilingual-e5-small"

    def test_serialize_f32_is_little_endian_float32(self):
        from academic_vault.embedding_model import serialize_f32

        assert serialize_f32([1.0, -2.5, 0.25]) == struct.pack("<3f", 1.0, -2.5, 0.25)

    def test_serialize_deserialize_roundtrip(self):
        from academic_vault.embedding_model import deserialize_f32, serialize_f32

        vector = [i / 100.0 for i in range(384)]
        blob = serialize_f32(vector)
        assert len(blob) == 384 * 4
        restored = deserialize_f32(blob)
        assert len(restored) == 384
        for original, value in zip(vector, restored, strict=True):
            assert abs(original - value) < 1e-6

    def test_deserialize_rejects_truncated_blob(self):
        from academic_vault.embedding_model import deserialize_f32

        with pytest.raises(ValueError):
            deserialize_f32(b"\x00\x00\x00")

    def test_l2_normalize_returns_unit_vector(self):
        from academic_vault.embedding_model import l2_normalize

        normalized = l2_normalize([3.0, 4.0])
        assert abs(math.sqrt(sum(v * v for v in normalized)) - 1.0) < 1e-9

    def test_l2_normalize_keeps_zero_vector(self):
        from academic_vault.embedding_model import l2_normalize

        assert l2_normalize([0.0, 0.0]) == [0.0, 0.0]

    def test_embed_documents_uses_passage_prefix(self):
        """e5 verlangt das Praefix 'passage: ' fuer Dokumente."""
        from academic_vault.embedding_model import E5SmallEmbedder

        seen: list[list[str]] = []

        class _StubModel:
            def encode(self, texts, **kwargs):
                seen.append(list(texts))
                return [[1.0] + [0.0] * 383 for _ in texts]

        embedder = E5SmallEmbedder(model=_StubModel())
        embedder.embed_documents(["Erster Chunk", "Zweiter Chunk"])

        assert seen == [["passage: Erster Chunk", "passage: Zweiter Chunk"]]

    def test_embed_query_uses_query_prefix(self):
        """e5 verlangt das Praefix 'query: ' fuer Suchanfragen."""
        from academic_vault.embedding_model import E5SmallEmbedder

        seen: list[list[str]] = []

        class _StubModel:
            def encode(self, texts, **kwargs):
                seen.append(list(texts))
                return [[1.0] + [0.0] * 383 for _ in texts]

        embedder = E5SmallEmbedder(model=_StubModel())
        vector = embedder.embed_query("transformer attention")

        assert seen == [["query: transformer attention"]]
        assert len(vector) == 384

    def test_embed_query_normalizes_backend_output(self):
        from academic_vault.embedding_model import E5SmallEmbedder

        class _StubModel:
            def encode(self, texts, **kwargs):
                return [[3.0, 4.0] + [0.0] * 382 for _ in texts]

        vector = E5SmallEmbedder(model=_StubModel()).embed_query("x")
        assert abs(math.sqrt(sum(v * v for v in vector)) - 1.0) < 1e-6

    def test_get_embedder_returns_none_without_backend(self, monkeypatch):
        """Ohne installiertes Extra bleibt der Vault nutzbar (FTS5-only)."""
        import academic_vault.embedding_model as em

        def _boom(*_args, **_kwargs):
            raise ImportError("sentence-transformers fehlt")

        monkeypatch.setattr(em, "_load_backend_model", _boom)
        em.reset_embedder_cache()
        try:
            assert em.get_embedder() is None
        finally:
            em.reset_embedder_cache()

    def test_get_embedder_caches_negative_result(self, monkeypatch):
        """Fehlendes Backend wird gecacht — kein Import-Versuch pro add_paper."""
        import academic_vault.embedding_model as em

        calls = {"n": 0}

        def _boom(*_args, **_kwargs):
            calls["n"] += 1
            raise ImportError("sentence-transformers fehlt")

        monkeypatch.setattr(em, "_load_backend_model", _boom)
        em.reset_embedder_cache()
        try:
            em.get_embedder()
            em.get_embedder()
            assert calls["n"] == 1
        finally:
            em.reset_embedder_cache()


# ---------------------------------------------------------------------------
# db.py — vec0-Spiegel, KNN (vec0 + Python-Fallback)
# ---------------------------------------------------------------------------


class TestChunkVectorStorage:
    def test_init_schema_creates_chunk_vectors_table(self, temp_vault_db):
        from academic_vault.db import VaultDB

        db = VaultDB(temp_vault_db)
        db.init_schema()
        if not db.vec_available:
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")
        conn = sqlite3.connect(temp_vault_db)
        row = conn.execute("SELECT name FROM sqlite_master WHERE name='chunk_vectors'").fetchone()
        conn.close()
        assert row is not None, "vec0-Tabelle chunk_vectors fehlt"

    def test_add_chunk_embedding_mirrors_vector_into_vec0(self, temp_vault_db, fake_embedder):
        from academic_vault.db import VaultDB

        db = VaultDB(temp_vault_db)
        db.init_schema()
        if not db.vec_available:
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")
        _store_chunk(temp_vault_db, "p001", "Transformer attention", fake_embedder)

        conn = sqlite3.connect(temp_vault_db)
        conn.enable_load_extension(True)
        import sqlite_vec

        conn.load_extension(sqlite_vec.loadable_path())
        count = conn.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0]
        conn.close()
        assert count == 1

    def test_knn_chunks_returns_nearest_first(self, temp_vault_db, fake_embedder):
        from academic_vault.db import VaultDB

        _add_paper(temp_vault_db, "p001", "A", "A")
        _add_paper(temp_vault_db, "p002", "B", "B")
        _store_chunk(temp_vault_db, "p001", "Transformer attention mechanism", fake_embedder)
        _store_chunk(temp_vault_db, "p002", "Classical music baroque composers", fake_embedder)

        hits = VaultDB(temp_vault_db).knn_chunks(
            fake_embedder.embed_query("transformer attention"), k=5
        )

        assert [h["paper_id"] for h in hits][0] == "p001"
        assert len(hits) == 2
        distances = [h["distance"] for h in hits]
        assert distances == sorted(distances)
        assert hits[0]["chunk_text"]

    def test_knn_chunks_python_fallback_matches_vec0_order(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        """Ohne ladbare Extension (macOS-Matrix) muss dieselbe Reihenfolge kommen."""
        from academic_vault.db import VaultDB

        _add_paper(temp_vault_db, "p001", "A", "A")
        _add_paper(temp_vault_db, "p002", "B", "B")
        _add_paper(temp_vault_db, "p003", "C", "C")
        _store_chunk(temp_vault_db, "p001", "Transformer attention mechanism", fake_embedder)
        _store_chunk(temp_vault_db, "p002", "Classical music baroque composers", fake_embedder)
        _store_chunk(temp_vault_db, "p003", "Attention transformer language model", fake_embedder)

        query_vector = fake_embedder.embed_query("transformer attention")
        with_extension = [h["paper_id"] for h in VaultDB(temp_vault_db).knn_chunks(query_vector, 5)]

        monkeypatch.setattr(VaultDB, "load_vec_extension", lambda self, conn=None: False)
        fallback = [h["paper_id"] for h in VaultDB(temp_vault_db).knn_chunks(query_vector, 5)]

        assert fallback == with_extension
        assert fallback[0] in ("p001", "p003")

    def test_knn_chunks_skips_dimension_mismatch(self, temp_vault_db, fake_embedder):
        from academic_vault.db import VaultDB
        from academic_vault.embedding_model import serialize_f32

        _add_paper(temp_vault_db, "p001", "A", "A")
        _add_paper(temp_vault_db, "p002", "B", "B")
        db = VaultDB(temp_vault_db)
        db.add_chunk_embedding(
            paper_id="p002",
            chunk_text="Alt-Vektor aus einem anderen Modell",
            context_sentence="",
            embedding_text="Alt-Vektor",
            embedding_vector=serialize_f32([0.1] * 128),
        )
        _store_chunk(temp_vault_db, "p001", "Transformer attention", fake_embedder)

        hits = db.knn_chunks(fake_embedder.embed_query("transformer"), k=5)

        assert [h["paper_id"] for h in hits] == ["p001"]

    def test_knn_chunks_empty_table_returns_empty(self, temp_vault_db, fake_embedder):
        from academic_vault.db import VaultDB

        assert VaultDB(temp_vault_db).knn_chunks(fake_embedder.embed_query("x"), k=5) == []

    def test_delete_chunk_embeddings_removes_rows_and_vectors(self, temp_vault_db, fake_embedder):
        from academic_vault.db import VaultDB

        _add_paper(temp_vault_db, "p001", "A", "A")
        _store_chunk(temp_vault_db, "p001", "Erster Chunk", fake_embedder)
        _store_chunk(temp_vault_db, "p001", "Zweiter Chunk", fake_embedder)

        db = VaultDB(temp_vault_db)
        removed = db.delete_chunk_embeddings("p001")

        assert removed == 2
        assert db.get_chunk_embeddings("p001") == []
        assert db.knn_chunks(fake_embedder.embed_query("chunk"), k=5) == []

    def test_add_chunk_embedding_respects_vault_lock(self, temp_vault_db, fake_embedder):
        """Ein gesperrter Vault darf keine Chunk-Vektoren mehr aufnehmen (#380/#407)."""
        from academic_vault.db import VaultDB, VaultLockedError

        _add_paper(temp_vault_db, "p001", "A", "A")
        db = VaultDB(temp_vault_db)
        db.lock_vault("projekt")

        with pytest.raises(VaultLockedError):
            db.add_chunk_embedding(
                paper_id="p001",
                chunk_text="Chunk",
                context_sentence="",
                embedding_text="Chunk",
                embedding_vector=None,
            )


# ---------------------------------------------------------------------------
# ingest.py — Textquelle, Chunking, Schreiben
# ---------------------------------------------------------------------------


class TestIngest:
    def test_split_text_returns_single_chunk_for_short_text(self):
        from academic_vault.ingest import split_text

        assert split_text("Kurzer Text.") == ["Kurzer Text."]

    def test_split_text_respects_max_chars_and_overlaps(self):
        from academic_vault.ingest import split_text

        text = " ".join(f"wort{i}" for i in range(400))
        chunks = split_text(text, max_chars=200, overlap=50)

        assert len(chunks) > 1
        assert all(len(c) <= 200 for c in chunks)
        # Overlap: das Ende von Chunk n taucht am Anfang von Chunk n+1 wieder auf
        tail = chunks[0].split()[-1]
        assert tail in chunks[1].split()

    def test_split_text_empty_returns_empty_list(self):
        from academic_vault.ingest import split_text

        assert split_text("   ") == []

    def test_ingest_uses_title_and_abstract_when_no_fulltext(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Transformer Networks", "Self-attention fuer NLP.")
        _use_embedder(monkeypatch, fake_embedder)

        written = ingest_paper_embeddings(temp_vault_db, "p001")

        assert written >= 1
        rows = VaultDB(temp_vault_db).get_chunk_embeddings("p001")
        assert len(rows) == written
        assert "Transformer Networks" in rows[0]["chunk_text"]
        assert len(rows[0]["embedding_vector"]) == 384 * 4

    def test_ingest_prefers_explicit_text(self, temp_vault_db, fake_embedder, monkeypatch):
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")
        _use_embedder(monkeypatch, fake_embedder)

        ingest_paper_embeddings(temp_vault_db, "p001", text="Explizit uebergebener Volltext.")

        rows = VaultDB(temp_vault_db).get_chunk_embeddings("p001")
        assert rows[0]["chunk_text"] == "Explizit uebergebener Volltext."

    def test_ingest_prefers_fulltext_over_abstract(self, temp_vault_db, fake_embedder, monkeypatch):
        """Sobald #373 papers_fts.fulltext befuellt, nutzt der Ingest ihn automatisch."""
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")
        conn = sqlite3.connect(temp_vault_db)
        conn.execute(
            "UPDATE papers_fts SET fulltext = ? WHERE paper_id = ?",
            ("Der komplette Volltext des Papers.", "p001"),
        )
        conn.commit()
        conn.close()
        _use_embedder(monkeypatch, fake_embedder)

        ingest_paper_embeddings(temp_vault_db, "p001")

        rows = VaultDB(temp_vault_db).get_chunk_embeddings("p001")
        assert rows[0]["chunk_text"] == "Der komplette Volltext des Papers."

    def test_ingest_without_embedder_returns_zero(self, temp_vault_db, monkeypatch):
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")
        _no_embedder(monkeypatch)

        assert ingest_paper_embeddings(temp_vault_db, "p001") == 0
        assert VaultDB(temp_vault_db).get_chunk_embeddings("p001") == []

    def test_ingest_unknown_paper_returns_zero(self, temp_vault_db, fake_embedder, monkeypatch):
        from academic_vault.ingest import ingest_paper_embeddings

        _use_embedder(monkeypatch, fake_embedder)
        assert ingest_paper_embeddings(temp_vault_db, "gibt-es-nicht") == 0

    def test_ingest_twice_replaces_chunks(self, temp_vault_db, fake_embedder, monkeypatch):
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")
        _use_embedder(monkeypatch, fake_embedder)

        first = ingest_paper_embeddings(temp_vault_db, "p001")
        second = ingest_paper_embeddings(temp_vault_db, "p001")

        assert first == second
        assert len(VaultDB(temp_vault_db).get_chunk_embeddings("p001")) == second

    def test_ingest_honours_max_chunks(self, temp_vault_db, fake_embedder, monkeypatch):
        from academic_vault.ingest import ingest_paper_embeddings

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")
        _use_embedder(monkeypatch, fake_embedder)
        long_text = " ".join(f"wort{i}" for i in range(5000))

        written = ingest_paper_embeddings(temp_vault_db, "p001", text=long_text, max_chunks=3)

        assert written == 3


# ---------------------------------------------------------------------------
# AC 1: add_paper schreibt chunk_embeddings mit nicht-leerem Vektor
# ---------------------------------------------------------------------------


class TestAddPaperWiring:
    def test_add_paper_writes_chunk_embedding_with_vector(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.db import VaultDB

        _use_embedder(monkeypatch, fake_embedder)
        _add_paper(temp_vault_db, "p001", "Transformer Networks", "Self-attention fuer NLP.")

        rows = VaultDB(temp_vault_db).get_chunk_embeddings("p001")

        assert len(rows) >= 1
        assert rows[0]["embedding_vector"] is not None
        assert len(rows[0]["embedding_vector"]) == 384 * 4

    def test_add_paper_without_embedder_does_not_raise(self, temp_vault_db, monkeypatch):
        from academic_vault.db import VaultDB

        _no_embedder(monkeypatch)
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")

        assert VaultDB(temp_vault_db).get_paper("p001") is not None
        assert VaultDB(temp_vault_db).get_chunk_embeddings("p001") == []

    def test_add_paper_respects_vault_auto_embed_off(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.db import VaultDB

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _use_embedder(monkeypatch, fake_embedder)
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")

        assert VaultDB(temp_vault_db).get_chunk_embeddings("p001") == []

    def test_add_paper_survives_ingest_error(self, temp_vault_db, monkeypatch):
        """Ein Ingest-Fehler darf add_paper niemals scheitern lassen."""
        from academic_vault.db import VaultDB

        def _boom(*_args, **_kwargs):
            raise RuntimeError("Embedding-Backend kaputt")

        monkeypatch.setattr("academic_vault.ingest.ingest_paper_embeddings", _boom)
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")

        assert VaultDB(temp_vault_db).get_paper("p001") is not None


# ---------------------------------------------------------------------------
# AC 2: _vec0_search liefert echte Treffer (kein []-Stub mehr)
# ---------------------------------------------------------------------------


class TestVec0Search:
    def _seed(self, db_path, fake_embedder, monkeypatch):
        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(db_path, "p001", "A", "A")
        _add_paper(db_path, "p002", "B", "B")
        _add_paper(db_path, "p003", "C", "C")
        _store_chunk(db_path, "p001", "Transformer attention mechanism for NLP", fake_embedder)
        _store_chunk(db_path, "p002", "Convolutional networks classify images", fake_embedder)
        _store_chunk(db_path, "p003", "Classical music baroque composers", fake_embedder)

    def test_vec0_search_returns_ranked_hits(self, temp_vault_db, fake_embedder, monkeypatch):
        from academic_vault.server import _vec0_search

        self._seed(temp_vault_db, fake_embedder, monkeypatch)
        _use_embedder(monkeypatch, fake_embedder)

        hits = _vec0_search(temp_vault_db, "transformer attention", k=5)

        assert hits, "_vec0_search liefert immer noch den []-Stub"
        assert hits[0]["paper_id"] == "p001"
        assert [h["distance"] for h in hits] == sorted(h["distance"] for h in hits)
        for hit in hits:
            assert hit["paper_id"]
            assert hit["snippet"]

    def test_vec0_search_python_fallback_without_extension(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.db import VaultDB
        from academic_vault.server import _vec0_search

        self._seed(temp_vault_db, fake_embedder, monkeypatch)
        _use_embedder(monkeypatch, fake_embedder)
        with_extension = [h["paper_id"] for h in _vec0_search(temp_vault_db, "transformer", k=5)]

        monkeypatch.setattr(VaultDB, "load_vec_extension", lambda self, conn=None: False)
        fallback = [h["paper_id"] for h in _vec0_search(temp_vault_db, "transformer", k=5)]

        assert fallback == with_extension
        assert fallback[0] == "p001"

    def test_vec0_search_aggregates_chunks_per_paper(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.server import _vec0_search

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "A", "A")
        _store_chunk(temp_vault_db, "p001", "Transformer attention mechanism", fake_embedder)
        _store_chunk(temp_vault_db, "p001", "Transformer encoder decoder stack", fake_embedder)
        _use_embedder(monkeypatch, fake_embedder)

        hits = _vec0_search(temp_vault_db, "transformer attention", k=5)

        assert [h["paper_id"] for h in hits] == ["p001"], "Chunks nicht auf Paper-Ebene aggregiert"

    def test_vec0_search_empty_table_returns_empty(self, temp_vault_db, fake_embedder, monkeypatch):
        from academic_vault.server import _vec0_search

        _use_embedder(monkeypatch, fake_embedder)
        assert _vec0_search(temp_vault_db, "transformer", k=5) == []

    def test_vec0_search_without_embedder_returns_empty(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.server import _vec0_search

        self._seed(temp_vault_db, fake_embedder, monkeypatch)
        _no_embedder(monkeypatch)

        assert _vec0_search(temp_vault_db, "transformer", k=5) == []


# ---------------------------------------------------------------------------
# AC 3: rerank=True rankt messbar anders als FTS5-only
# ---------------------------------------------------------------------------


class TestRerankUsesRealVectors:
    def test_rerank_true_reorders_vs_fts_only(self, temp_vault_db, fake_embedder, monkeypatch):
        from academic_vault.server import search_papers

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(
            temp_vault_db,
            "p_bm25",
            "Retrieval retrieval retrieval",
            "retrieval retrieval retrieval",
        )
        _add_paper(temp_vault_db, "p_vec", "Dense passage encoders", "neural retrieval")

        fts_only = [r["paper_id"] for r in search_papers(temp_vault_db, "retrieval", k=5)]
        assert fts_only[0] == "p_bm25", "Setup-Annahme: BM25 bevorzugt p_bm25"

        _store_chunk(temp_vault_db, "p_vec", "Dense passage encoders retrieval", fake_embedder)
        _use_embedder(monkeypatch, fake_embedder)

        hybrid = search_papers(temp_vault_db, "retrieval", k=5, rerank=True)
        hybrid_ids = [r["paper_id"] for r in hybrid]

        assert hybrid_ids != fts_only, "rerank=True aendert die Rangfolge nicht"
        assert hybrid_ids[0] == "p_vec"
        assert all("rrf_score" in r for r in hybrid)

    def test_rerank_true_surfaces_vector_only_paper_with_snippet(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.server import search_papers

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p_fts", "Retrieval systems", "retrieval methods")
        _add_paper(temp_vault_db, "p_vec_only", "Katzen und Hunde", "Haustiere im Haushalt")
        _store_chunk(temp_vault_db, "p_vec_only", "Katzen und Hunde sind Haustiere", fake_embedder)
        _use_embedder(monkeypatch, fake_embedder)

        fts_only = {r["paper_id"] for r in search_papers(temp_vault_db, "retrieval", k=5)}
        hybrid = search_papers(temp_vault_db, "retrieval", k=5, rerank=True)
        by_id = {r["paper_id"]: r for r in hybrid}

        assert "p_vec_only" not in fts_only
        assert "p_vec_only" in by_id, "Nur-vektoriell gefundenes Paper fehlt in der RRF"
        assert by_id["p_vec_only"].get("snippet")

    def test_rerank_true_keeps_fts_score_and_highlighting(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        """rerank=True haelt den dokumentierten Rueckgabevertrag {paper_id, snippet, score}.

        Regression (#372): das vec0-Dict verdraengte in der RRF die
        FTS5-Metadaten — 'score' fehlte und das '<b>'-Highlighting im Snippet
        ging verloren, sobald ein Paper ueber beide Pfade gefunden wurde.
        """
        from academic_vault.server import search_papers

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p_both", "Retrieval systems", "retrieval methods")
        _store_chunk(temp_vault_db, "p_both", "Retrieval systems und Methoden", fake_embedder)
        _use_embedder(monkeypatch, fake_embedder)

        fts_only = {r["paper_id"]: r for r in search_papers(temp_vault_db, "retrieval", k=5)}
        assert "p_both" in fts_only, "Setup-Annahme: Paper wird auch per FTS5 gefunden"

        hybrid = {
            r["paper_id"]: r for r in search_papers(temp_vault_db, "retrieval", k=5, rerank=True)
        }
        entry = hybrid["p_both"]

        assert "score" in entry, "dokumentierter FTS5-'score' fehlt im Hybrid-Ergebnis"
        assert entry["score"] == fts_only["p_both"]["score"]
        assert "<b>" in entry["snippet"], "FTS5-'<b>'-Highlighting im Snippet verloren"
        assert entry["snippet"] == fts_only["p_both"]["snippet"]

    def test_rerank_true_keeps_chunk_text_for_reranker(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        """Der Reranker-Input bleibt der volle Chunk-Text, nicht das 10-Token-FTS-Snippet.

        Das FTS5-Snippet gewinnt fuer das Ausgabefeld 'snippet' (Vertrag +
        Highlighting) — der Reranker soll aber weiter den laengeren
        Chunk-Text sehen, den ``apply_reranker`` ueber 'text' konsumiert.
        """
        from academic_vault.server import _vec0_search, search_papers

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        chunk = "Retrieval systems und Methoden fuer dichte Passagen-Repraesentationen"
        _add_paper(temp_vault_db, "p_both", "Retrieval systems", "retrieval methods")
        _store_chunk(temp_vault_db, "p_both", chunk, fake_embedder)
        _use_embedder(monkeypatch, fake_embedder)

        hit = _vec0_search(temp_vault_db, "retrieval", k=5)[0]
        assert hit["text"] == chunk, "vec0-Treffer liefert keinen Reranker-Text"

        hybrid = {
            r["paper_id"]: r for r in search_papers(temp_vault_db, "retrieval", k=5, rerank=True)
        }
        assert hybrid["p_both"]["text"] == chunk, "Chunk-Text durch RRF-Merge verloren"

    def test_vec0_search_gets_unsanitized_query(self, temp_vault_db, monkeypatch):
        """FTS5-Sanitizing verfaelscht die Semantik — der Vektorpfad bekommt das Original."""
        import academic_vault.server as server

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Retrieval", "retrieval")
        seen: list[str] = []

        def _spy(db_path, query, k=10):
            seen.append(query)
            return []

        monkeypatch.setattr(server, "_vec0_search", _spy)
        server.search_papers(temp_vault_db, "cross-lingual NOT retrieval", k=5, rerank=True)

        assert seen == ["cross-lingual NOT retrieval"]


# ---------------------------------------------------------------------------
# Migration fuer Bestands-DBs
# ---------------------------------------------------------------------------


class TestMigration:
    def test_add_chunk_vectors_table_is_idempotent(self, tmp_path):
        from academic_vault.db import VaultDB
        from academic_vault.migrate import add_chunk_vectors_table

        db_path = str(tmp_path / "vault.db")
        db = VaultDB(db_path)
        db.init_schema()

        add_chunk_vectors_table(db_path)
        add_chunk_vectors_table(db_path)

        if not db.vec_available:
            pytest.skip("sqlite-vec-Extension nicht ladbar — Migration ist dann No-op")
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT name FROM sqlite_master WHERE name='chunk_vectors'").fetchone()
        conn.close()
        assert row is not None

    def test_add_chunk_vectors_table_survives_missing_extension(self, tmp_path, monkeypatch):
        from academic_vault.db import VaultDB
        from academic_vault.migrate import add_chunk_vectors_table

        db_path = str(tmp_path / "vault.db")
        VaultDB(db_path).init_schema()
        monkeypatch.setattr(VaultDB, "load_vec_extension", lambda self, conn=None: False)

        add_chunk_vectors_table(db_path)  # darf nicht werfen


# ---------------------------------------------------------------------------
# Live-Test gegen das echte Modell (nur mit Extra + Env-Gate)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("VAULT_E5_LIVE_TEST") != "1",
    reason="Live-Modelltest nur mit VAULT_E5_LIVE_TEST=1 (laedt ~500 MB Modell)",
)
def test_e5_small_real_model_roundtrip():
    pytest.importorskip("sentence_transformers")
    from academic_vault.embedding_model import EMBEDDING_DIM, get_embedder, reset_embedder_cache

    reset_embedder_cache()
    embedder = get_embedder()
    assert embedder is not None
    vector = embedder.embed_query("Wie funktioniert Retrieval-Augmented Generation?")
    assert len(vector) == EMBEDDING_DIM
    assert abs(math.sqrt(sum(v * v for v in vector)) - 1.0) < 1e-3


# ---------------------------------------------------------------------------
# Deklariertes Backend (#372, AC1)
# ---------------------------------------------------------------------------
#
# AC1 verlangt, dass ``chunk_embeddings`` nach ``add_paper`` einen Datensatz mit
# nicht-leerem ``embedding_vector`` enthaelt — und zwar in einer normalen
# Installation, nicht nur mit injiziertem Embedder. Notwendige und hinreichende
# Vorbedingung dafuer ist, dass das Backend, das ``_load_backend_model()``
# importiert, in BEIDEN dokumentierten Installationswegen wirklich deklariert
# und danach importierbar ist:
#
#   * Dev/CI      -> pyproject.toml [project].dependencies  + `uv sync --extra dev`
#   * Endnutzer   -> scripts/requirements.txt               + scripts/setup.sh
#
# War das Backend nur als Kommentar dokumentiert, lief ``get_embedder()`` in
# jeder realen Installation in den ImportError-Zweig und ``add_paper`` schrieb
# null Zeilen. Diese Tests halten genau diese Regression fest.


class TestEmbeddingBackendIsDeclaredDependency:
    """Das Embedding-Backend muss deklarierte Dependency sein, kein Kommentar."""

    BACKEND_DIST = "sentence-transformers"
    BACKEND_MODULE = "sentence_transformers"

    def test_pyproject_declares_embedding_backend(self):
        """`uv sync --extra dev` muss das Backend mitinstallieren."""
        import tomllib
        from pathlib import Path

        from packaging.requirements import Requirement

        root = Path(__file__).resolve().parent.parent
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        declared = {
            Requirement(dep).name.lower().replace("_", "-")
            for dep in data["project"]["dependencies"]
        }
        assert self.BACKEND_DIST in declared, (
            f"{self.BACKEND_DIST} fehlt in pyproject.toml [project].dependencies — "
            "ohne Deklaration liefert get_embedder() in der Dev-/CI-Umgebung None "
            "und add_paper schreibt keine chunk_embeddings (AC1 von #372)."
        )

    def test_requirements_txt_declares_embedding_backend(self):
        """Der Endnutzerweg (scripts/setup.sh -> pip) muss das Backend mitinstallieren."""
        from pathlib import Path

        from packaging.requirements import Requirement

        root = Path(__file__).resolve().parent.parent
        declared = set()
        for raw in (root / "scripts" / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            # Auskommentierte Zeilen zaehlen ausdruecklich NICHT als Deklaration.
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            declared.add(Requirement(line).name.lower().replace("_", "-"))
        assert self.BACKEND_DIST in declared, (
            f"{self.BACKEND_DIST} ist in scripts/requirements.txt nicht (oder nur "
            "auskommentiert) deklariert — der vom Vault-MCP-Server genutzte "
            "Endnutzer-venv bekommt dann kein Embedding-Backend (AC1 von #372)."
        )

    def test_declared_backend_is_importable(self):
        """Das deklarierte Backend muss in der synchronisierten Umgebung auffindbar sein.

        ``find_spec`` statt ``import``: der eigentliche Import zieht Torch nach
        (mehrere Sekunden) und wird fuer diese Aussage nicht gebraucht.
        """
        import importlib.util

        assert importlib.util.find_spec(self.BACKEND_MODULE) is not None, (
            f"{self.BACKEND_MODULE} ist nicht installiert. Umgebung mit "
            "`uv sync --extra dev` neu aufbauen; schlaegt das fehl, ist die "
            "Deklaration in pyproject.toml unvollstaendig."
        )


class TestSuiteStaysOffline:
    """Die Suite darf das echte Modell nicht laden — auch mit installiertem Backend.

    Seit das Backend eine harte Dependency ist, laeuft ``get_embedder()`` nicht
    mehr in einen ImportError. Ohne Schutz wuerde damit JEDER ``add_paper``-Aufruf
    der Suite ``intfloat/multilingual-e5-small`` (~470 MB) von HuggingFace ziehen
    und Tests netzabhaengig machen. Der Guard sitzt als autouse-Fixture in
    tests/conftest.py.
    """

    def test_backend_loader_is_blocked(self):
        import academic_vault.embedding_model as em

        with pytest.raises(RuntimeError, match="Testlauf"):
            em._load_backend_model("intfloat/multilingual-e5-small")

    def test_get_embedder_returns_none_under_guard(self):
        from academic_vault.embedding_model import get_embedder, reset_embedder_cache

        reset_embedder_cache()
        try:
            assert get_embedder() is None
        finally:
            reset_embedder_cache()

    def test_smoke_subprocess_env_disables_auto_embed(self):
        """Der E2E-Smoke-Test startet den Vault als Subprozess — dort greift der
        autouse-Guard nicht. Auf Entwicklermaschinen ist im Endnutzer-venv
        inzwischen ein echtes Backend installiert, also muss der Ingest fuer den
        Subprozess ueber die Env abgeschaltet sein."""
        from tests.helpers.smoke_core import _minimal_env

        assert _minimal_env().get("VAULT_AUTO_EMBED") == "0"

    def test_add_paper_degrades_gracefully_under_guard(self, temp_vault_db):
        """Ohne injizierten Embedder: keine Exception, keine Chunks, kein Download."""
        from academic_vault.db import VaultDB

        VaultDB(temp_vault_db).init_schema()
        _add_paper(temp_vault_db, "p_guard", "Attention", "Transformer-Architektur.")

        conn = sqlite3.connect(temp_vault_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM chunk_embeddings WHERE paper_id = ?", ("p_guard",)
        ).fetchone()[0]
        conn.close()
        assert count == 0
