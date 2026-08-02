"""Issue #629: VAULT_EMBEDDING_MODEL jenseits von 384 Dimensionen.

Ausgangslage (vor diesem Issue empirisch festgestellt, `academic_vault` auf
main): ein Embedder mit abweichender Dimension laeuft **still** durch.

    384d-Ingest -> 1 Chunk, BLOB-Laenge 1536
    1024d-Ingest -> 1 Chunk, BLOB-Laenge 4096   (keine Exception)
    knn_chunks(384d-Query) -> nur das 384d-Paper
    knn_chunks(1024d-Query) -> nur das 1024d-Paper

Der Vault enthaelt danach zwei unvergleichbare Vektorraeume, und jede Suche
sieht nur den zufaellig passenden Teilbestand -- ohne Fehlermeldung. Die Tests
hier fixieren das Gegenteil: eine Dimension, die vom geladenen Modell kommt,
ein Mismatch, der scheitert statt zu degradieren, und einen Re-Index-Pfad, der
einen Bestand auf ein neues Modell umstellt.
"""

import hashlib
import json
import math
import re
import sqlite3
import struct

import pytest
from academic_vault import migrate
from academic_vault.db import CURRENT_SCHEMA_VERSION, VaultDB
from academic_vault.embedding_model import (
    DEFAULT_EMBEDDING_DIM,
    EmbeddingDimensionMismatchError,
)
from academic_vault.ingest import ingest_paper_embeddings


class SizedEmbedder:
    """Deterministischer Embedder beliebiger Breite -- laedt nie Gewichte (AC6)."""

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


def _vec0_ddl(db_path: str, table: str) -> str:
    """DDL einer vec0-Tabelle -- zeigt die Spaltenbreite (``FLOAT[n]``)."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    finally:
        conn.close()
    return row[0] if row is not None else ""


def _seed_paper(db_path: str, paper_id: str, title: str, abstract: str) -> None:
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id, json.dumps({"title": title, "abstract": abstract}))


# ---------------------------------------------------------------------------
# AC2 -- die Dimension stammt vom geladenen Modell, nicht von einer Konstante
# ---------------------------------------------------------------------------


class TestDimComesFromBackend:
    def test_dim_reads_sentence_embedding_dimension_of_loaded_model(self):
        from academic_vault.embedding_model import E5SmallEmbedder

        class Backend:
            def get_sentence_embedding_dimension(self):
                return 1024

            def encode(self, texts, **_kwargs):  # pragma: no cover - hier ungenutzt
                raise AssertionError("dim darf ohne Not nicht encoden")

        embedder = E5SmallEmbedder(model_id="fake/large", model=Backend())

        assert embedder.dim == 1024

    def test_dim_falls_back_to_probe_encode_without_dimension_api(self):
        from academic_vault.embedding_model import E5SmallEmbedder

        class Backend:
            def encode(self, texts, **_kwargs):
                return [[0.0] * 768 for _ in texts]

        embedder = E5SmallEmbedder(model_id="fake/medium", model=Backend())

        assert embedder.dim == 768

    def test_default_dim_constant_is_only_the_fresh_vault_width(self):
        # Die 384 bleiben die Breite eines frischen Vaults -- aber eben nicht
        # mehr die Breite jedes Modells.
        assert DEFAULT_EMBEDDING_DIM == 384


# ---------------------------------------------------------------------------
# AC1 -- Mismatch scheitert hoerbar statt still zu degradieren
# ---------------------------------------------------------------------------


class TestWriteFailsLoudlyOnMismatch:
    def test_ingest_with_other_dimension_raises(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Anpassung an den Klimawandel", "Ein Text ueber Anpassung.")
        _seed_paper(db_path, "a2", "Zweites Paper", "Anderer Text ueber Anpassung.")

        assert ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384)) == 1

        with pytest.raises(EmbeddingDimensionMismatchError) as excinfo:
            ingest_paper_embeddings(db_path, "a2", embedder=SizedEmbedder(1024))

        message = str(excinfo.value)
        assert "1024" in message
        assert "384" in message
        assert "test/sized-1024d" in message
        assert "--reindex-embeddings" in message, "Meldung muss den Ausweg nennen"

    def test_mismatched_chunk_is_not_written(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text.")
        _seed_paper(db_path, "a2", "Zweites Paper", "Text.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))

        with pytest.raises(EmbeddingDimensionMismatchError):
            ingest_paper_embeddings(db_path, "a2", embedder=SizedEmbedder(1024))

        lengths = {
            len(row["embedding_vector"])
            for row in VaultDB(db_path).get_chunk_embeddings("a1")
            if row["embedding_vector"]
        }
        assert lengths == {384 * 4}
        assert VaultDB(db_path).get_chunk_embeddings("a2") == []

    def test_add_chunk_embedding_rejects_foreign_width(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text.")
        db = VaultDB(db_path)
        db.register_embedding_inventory("test/sized-384d", 384)

        with pytest.raises(EmbeddingDimensionMismatchError):
            db.add_chunk_embedding(
                paper_id="a1",
                chunk_text="Text",
                context_sentence="",
                embedding_text="Text",
                embedding_vector=struct.pack("<1024f", *([0.0] * 1024)),
            )

    def test_add_quote_embedding_rejects_foreign_width(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text.")
        db = VaultDB(db_path)
        db.register_embedding_inventory("test/sized-384d", 384)
        quote_id = db.add_quote(
            quote_id="q1",
            paper_id="a1",
            verbatim="Ein belegter Wortlaut.",
            extraction_method="manual",
        )

        with pytest.raises(EmbeddingDimensionMismatchError):
            db.add_quote_embedding(quote_id or "q1", struct.pack("<1024f", *([0.0] * 1024)))

    def test_auto_embed_path_of_add_paper_does_not_swallow_mismatch(self, tmp_path, monkeypatch):
        """Carve-out: der Catch-all in ``_maybe_ingest_embeddings`` darf den
        Mismatch nicht zur blossen Log-Zeile machen -- sonst waere AC1 formal
        erfuellt und praktisch wirkungslos."""
        from academic_vault import ingest as ingest_module
        from academic_vault import server as server_module

        db_path = str(tmp_path / "vault.db")
        monkeypatch.setattr(ingest_module, "get_embedder", lambda: SizedEmbedder(384))
        server_module.add_paper(
            db_path,
            "a1",
            json.dumps({"type": "article-journal", "title": "Erstes", "abstract": "Text."}),
        )

        monkeypatch.setattr(ingest_module, "get_embedder", lambda: SizedEmbedder(1024))
        with pytest.raises(EmbeddingDimensionMismatchError):
            server_module.add_paper(
                db_path,
                "a2",
                json.dumps({"type": "article-journal", "title": "Zweites", "abstract": "Text."}),
            )

    def test_add_quote_path_does_not_swallow_mismatch(self, tmp_path, monkeypatch):
        from academic_vault import ingest as ingest_module
        from academic_vault import server as server_module

        db_path = str(tmp_path / "vault.db")
        monkeypatch.setattr(ingest_module, "get_embedder", lambda: SizedEmbedder(384))
        monkeypatch.setattr(server_module, "get_embedder", lambda: SizedEmbedder(384))
        server_module.add_paper(
            db_path,
            "a1",
            json.dumps({"type": "article-journal", "title": "Erstes", "abstract": "Text."}),
        )

        monkeypatch.setattr(server_module, "get_embedder", lambda: SizedEmbedder(1024))
        with pytest.raises(EmbeddingDimensionMismatchError):
            server_module.add_quote(
                db_path,
                paper_id="a1",
                verbatim="Ein belegter Wortlaut.",
                extraction_method="manual",
            )

    def test_fresh_vault_adopts_any_dimension(self, tmp_path):
        """Ein leerer Bestand hat nichts zu verlieren: das erste Modell gibt die
        Breite vor, ein Re-Index ist dafuer nicht noetig."""
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Ein Text ueber Anpassung.")

        assert ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(1024)) == 1

        inventory = VaultDB(db_path).embedding_inventory()
        assert inventory is not None
        assert inventory["dim"] == 1024
        assert inventory["model_id"] == "test/sized-1024d"


# ---------------------------------------------------------------------------
# AC3/AC4 -- Re-Index-Pfad
# ---------------------------------------------------------------------------


class TestReindex:
    def test_reindex_recomputes_chunks_and_quotes_in_new_width(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Anpassung an den Klimawandel", "Ein Text ueber Anpassung.")
        db = VaultDB(db_path)
        db.add_quote(
            quote_id="q1",
            paper_id="a1",
            verbatim="Anpassung ist keine Alternative zur Vermeidung.",
            extraction_method="manual",
        )
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))
        assert VaultDB(db_path).expected_embedding_dim() == 384

        stats = migrate.reindex_embeddings(db_path, embedder=SizedEmbedder(1024))

        assert stats["dim"] == 1024
        assert stats["chunks"] >= 1
        lengths = {
            len(row["embedding_vector"])
            for row in VaultDB(db_path).get_chunk_embeddings("a1")
            if row["embedding_vector"]
        }
        assert lengths == {1024 * 4}
        inventory = VaultDB(db_path).embedding_inventory()
        assert inventory is not None
        assert (inventory["model_id"], inventory["dim"]) == ("test/sized-1024d", 1024)

    def test_reindex_widens_the_vec0_columns(self, tmp_path):
        """AC3: die Spaltenbreite wird mitgezogen.

        vec0 kann ``FLOAT[n]`` nicht per ALTER aendern -- ohne DROP + CREATE
        haette der Re-Index zwar neue BLOBs, aber einen Spiegel, der sie nicht
        aufnehmen kann.
        """
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Anpassung an den Klimawandel", "Ein Text ueber Anpassung.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))
        if not VaultDB(db_path).vec_extension_loadable():
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")
        assert "FLOAT[384]" in _vec0_ddl(db_path, "chunk_vectors")

        migrate.reindex_embeddings(db_path, embedder=SizedEmbedder(1024))

        assert "FLOAT[1024]" in _vec0_ddl(db_path, "chunk_vectors")
        assert "FLOAT[1024]" in _vec0_ddl(db_path, "quote_embeddings")

    def test_search_finds_hits_again_after_reindex(self, tmp_path, monkeypatch):
        from academic_vault import ingest as ingest_module
        from academic_vault import server as server_module

        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Anpassung an den Klimawandel", "Ein Text ueber Anpassung.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))

        # Modellwechsel: ohne Re-Index sieht der neue Embedder nichts.
        monkeypatch.setattr(server_module, "get_embedder", lambda: SizedEmbedder(1024))
        monkeypatch.setattr(ingest_module, "get_embedder", lambda: SizedEmbedder(1024))
        with pytest.raises(EmbeddingDimensionMismatchError):
            VaultDB(db_path).knn_chunks(SizedEmbedder(1024).embed_query("Anpassung"), k=5)

        migrate.reindex_embeddings(db_path, embedder=SizedEmbedder(1024))

        hits = VaultDB(db_path).knn_chunks(SizedEmbedder(1024).embed_query("Anpassung"), k=5)
        assert [hit["paper_id"] for hit in hits] == ["a1"]
        assert server_module.search_papers(db_path, "Anpassung", k=5, rerank=True)

    def test_reindex_overwrites_mixed_inventory_completely(self, tmp_path):
        """Ein Mischbestand aus zwei Modellen muss vollstaendig ersetzt werden --
        anders als ``backfill_quote_embeddings``, das nur Luecken fuellt."""
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text ueber Anpassung.")
        _seed_paper(db_path, "a2", "Zweites Paper", "Anderer Text ueber Anpassung.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))
        # Mischbestand von Hand herstellen (so sieht eine Bestands-DB aus, die
        # vor #629 mit zwei Modellen befuellt wurde).
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO chunk_embeddings (chunk_id, paper_id, chunk_text, "
                "context_sentence, embedding_text, embedding_vector, created_at) "
                "VALUES ('legacy', 'a2', 'Anderer Text ueber Anpassung.', '', "
                "'Anderer Text ueber Anpassung.', ?, 0)",
                (struct.pack("<1024f", *([0.5] * 1024)),),
            )
            conn.commit()
        finally:
            conn.close()

        migrate.reindex_embeddings(db_path, embedder=SizedEmbedder(1024))

        conn = sqlite3.connect(db_path)
        try:
            lengths = {
                len(row[0])
                for row in conn.execute(
                    "SELECT embedding_vector FROM chunk_embeddings "
                    "WHERE embedding_vector IS NOT NULL"
                )
            }
        finally:
            conn.close()
        assert lengths == {1024 * 4}, "nach dem Re-Index darf keine Fremdbreite uebrig sein"

    def test_reindex_refuses_locked_vault_before_touching_anything(self, tmp_path):
        from academic_vault.db import VaultLockedError

        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text ueber Anpassung.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))
        VaultDB(db_path).lock_vault("projekt")

        with pytest.raises(VaultLockedError):
            migrate.reindex_embeddings(db_path, embedder=SizedEmbedder(1024))

        lengths = {
            len(row["embedding_vector"])
            for row in VaultDB(db_path).get_chunk_embeddings("a1")
            if row["embedding_vector"]
        }
        assert lengths == {384 * 4}, "gesperrter Vault darf nicht halb abgeraeumt zurueckbleiben"

    def test_cli_flag_reindex_embeddings(self, tmp_path, monkeypatch, capsys):
        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text ueber Anpassung.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))

        monkeypatch.setattr(
            "academic_vault.embedding_model.get_embedder", lambda *a, **k: SizedEmbedder(1024)
        )
        monkeypatch.setattr(
            "sys.argv",
            ["migrate.py", "--db", db_path, "--reindex-embeddings"],
        )
        migrate.main()

        assert "1024" in capsys.readouterr().out
        assert VaultDB(db_path).expected_embedding_dim() == 1024


# ---------------------------------------------------------------------------
# AC5 -- Bestand ist ohne Blick in den Code ablesbar
# ---------------------------------------------------------------------------


class TestInventoryIsVisible:
    def test_stats_report_model_and_dim(self, tmp_path):
        from academic_vault.server import get_stats

        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text ueber Anpassung.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))

        stats = get_stats(db_path)

        assert stats["embedding_model"] == "test/sized-384d"
        assert stats["embedding_dim"] == 384

    def test_stats_report_none_for_empty_vault(self, tmp_path):
        from academic_vault.server import get_stats

        db_path = str(tmp_path / "vault.db")
        VaultDB(db_path).init_schema()

        stats = get_stats(db_path)

        assert stats["embedding_model"] is None
        assert stats["embedding_dim"] is None

    def test_reading_the_inventory_never_loads_a_model(self, tmp_path, monkeypatch):
        """Risiko aus dem Plan: die Bestandsdimension darf nie ueber den
        Embedder ermittelt werden -- im PreToolUse-Pfad waere ein Modell-Load
        ein Timeout-Kandidat."""
        import academic_vault.embedding_model as em

        db_path = str(tmp_path / "vault.db")
        _seed_paper(db_path, "a1", "Erstes Paper", "Text ueber Anpassung.")
        ingest_paper_embeddings(db_path, "a1", embedder=SizedEmbedder(384))

        def _explode(*_args, **_kwargs):
            raise AssertionError("Bestandsabfrage darf kein Backend laden (#629)")

        monkeypatch.setattr(em, "get_embedder", _explode)
        monkeypatch.setattr(em, "_load_backend_model", _explode)

        assert VaultDB(db_path).expected_embedding_dim() == 384


# ---------------------------------------------------------------------------
# Schema-Gate
# ---------------------------------------------------------------------------


def _user_version(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


class TestSchemaMigration:
    def test_schema_version_was_raised_for_embedding_meta(self):
        assert CURRENT_SCHEMA_VERSION >= 8

    def test_fresh_db_has_embedding_meta_table(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        VaultDB(db_path).init_schema()

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_meta'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert _user_version(db_path) == CURRENT_SCHEMA_VERSION

    def test_legacy_v7_db_gets_embedding_meta_and_is_stamped(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        VaultDB(db_path).init_schema()
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DROP TABLE embedding_meta")
            conn.execute("PRAGMA user_version = 7")
            conn.commit()
        finally:
            conn.close()

        VaultDB(db_path).init_schema()

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_meta'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert _user_version(db_path) == CURRENT_SCHEMA_VERSION

    def test_add_embedding_meta_table_is_idempotent(self, tmp_path):
        db_path = str(tmp_path / "vault.db")
        VaultDB(db_path).init_schema()

        migrate.add_embedding_meta_table(db_path)
        migrate.add_embedding_meta_table(db_path)  # darf nicht werfen
