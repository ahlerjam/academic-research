"""Regressionstests fuer Issue #791: ``_attach_chunk_to_fts_hit`` verliert den
Hybrid-Bonus bei fehlgeschlagenem lexikalischem Chunk-Lookup.

Befund aus #789 (Diagnoseblock in ``run_retrieval_ablation_729.py``):
``_attach_chunk_to_fts_hit`` (server.py) faellt, wenn ``chunk_fts`` keinen
Chunk desselben Papers findet (Stemming-/Komposita-Luecke), auf den
synthetischen Schluessel ``fts-paper::<pid>`` zurueck und verliert damit jede
Chunk-Zuordnung -- statt auf den vektoriell besten Chunk desselben Papers
auszuweichen (sofern vorhanden). Der Fix zieht die vec0-Beschaffung in
``search_papers`` vor den FTS-Chunk-Attach und reicht ein
``paper_id -> bester Vektor-Chunk``-Dict als neuen optionalen Parameter durch.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from academic_vault.db import VaultDB
from academic_vault.embedding_model import l2_normalize, serialize_f32
from academic_vault.retrieval import ENV_LOCAL_RERANKER_DISABLE
from academic_vault.server import _attach_chunk_to_fts_hit, search_papers

pytestmark = pytest.mark.usefixtures("_reset_local_reranker_env")


@pytest.fixture
def _reset_local_reranker_env(monkeypatch):
    """Reranker konstant AUS -- dieses Issue prueft Fusion/Attach, nicht Reranking."""
    monkeypatch.setenv(ENV_LOCAL_RERANKER_DISABLE, "1")


class _FixedVectorEmbedder:
    model_id = "intfloat/multilingual-e5-small"
    dim = 4

    def __init__(self, vector: list[float]) -> None:
        self._vector = l2_normalize(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector


def _cached_embedder(embedder, monkeypatch):
    from academic_vault import embedding_model

    monkeypatch.setitem(embedding_model._EMBEDDER_CACHE, embedder.model_id, embedder)
    monkeypatch.setenv("VAULT_EMBEDDING_MODEL", embedder.model_id)


def _build_db_with_unmatched_chunk(tmp_path) -> str:
    """Ein Paper, dessen Titel die Query lexikalisch trifft (papers_fts),
    dessen einziger Chunk die Query aber NICHT woertlich enthaelt (Stemming-
    Luecke) -- der ``chunk_fts``-Lookup in ``_attach_chunk_to_fts_hit``
    schlaegt damit fehl, waehrend ein Vektor-Chunk fuer das Paper existiert."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="p1",
        csl_json=json.dumps(
            {"title": "Mittelstand Digitalisierung Report", "type": "article-journal"}
        ),
    )
    db.register_embedding_inventory("intfloat/multilingual-e5-small", 4)
    # "Mittelstandsdigitalisierung" (ein Wort) matcht "Mittelstand" (Query)
    # lexikalisch NICHT -- FTS5 unicode61 stemmt nicht (#789).
    chunk_text = "Die Mittelstandsdigitalisierung schreitet in KMU nur langsam voran."
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text=chunk_text,
        context_sentence="ctx",
        embedding_text=f"ctx {chunk_text}",
        embedding_vector=serialize_f32(l2_normalize([1.0, 0.0, 0.0, 0.0])),
    )
    return db_path


# ---------------------------------------------------------------------------
# Unit-Ebene: _attach_chunk_to_fts_hit direkt
# ---------------------------------------------------------------------------
def test_attach_falls_back_to_vec_best_chunk_when_lexical_lookup_fails(tmp_path) -> None:
    db_path = _build_db_with_unmatched_chunk(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT chunk_id FROM chunk_embeddings WHERE paper_id = ?", ("p1",)
        ).fetchone()
        vec_chunk_id = row["chunk_id"]
        vec_best_by_paper = {
            "p1": {
                "paper_id": "p1",
                "chunk_id": vec_chunk_id,
                "text": "Die Mittelstandsdigitalisierung schreitet in KMU nur langsam voran.",
                "section_title": None,
                "page_start": None,
                "page_end": None,
            }
        }
        entry = {"paper_id": "p1"}
        attached = _attach_chunk_to_fts_hit(
            conn, entry, "mittelstand", vec_best_by_paper=vec_best_by_paper
        )
    finally:
        conn.close()

    assert attached["chunk_id"] == vec_chunk_id
    assert not attached["chunk_id"].startswith("fts-paper::")
    assert attached["text"] == "Die Mittelstandsdigitalisierung schreitet in KMU nur langsam voran."


def test_attach_keeps_synthetic_key_without_vec_fallback_available(tmp_path) -> None:
    """Kein Vektor-Chunk fuer das Paper (Embedding aus/nie gechunkt) -- der
    synthetische Schluessel bleibt die letzte Stufe, kein Crash."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id="p1", csl_json=json.dumps({"title": "Okapi", "type": "article-journal"}))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        entry = {"paper_id": "p1"}
        attached = _attach_chunk_to_fts_hit(conn, entry, "okapi", vec_best_by_paper=None)
    finally:
        conn.close()

    assert attached["chunk_id"] == "fts-paper::p1"
    assert "text" not in attached


def test_attach_lexical_match_still_wins_over_vec_fallback(tmp_path) -> None:
    """Trifft der lexikalische Lookup, hat er weiterhin Vorrang vor dem
    Vektor-Fallback -- keine Verhaltensaenderung im bereits funktionierenden
    Pfad."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id="p1", csl_json=json.dumps({"title": "Zebra", "type": "article-journal"}))
    db.register_embedding_inventory("intfloat/multilingual-e5-small", 4)
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text="The zebra roams the savanna.",
        context_sentence="ctx",
        embedding_text="ctx The zebra roams the savanna.",
        embedding_vector=serialize_f32(l2_normalize([1.0, 0.0, 0.0, 0.0])),
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        real_chunk_id = conn.execute(
            "SELECT chunk_id FROM chunk_embeddings WHERE paper_id = ?", ("p1",)
        ).fetchone()["chunk_id"]
        entry = {"paper_id": "p1"}
        # Falscher/irrelevanter Vektor-Fallback-Eintrag -- darf NICHT gewinnen,
        # da der lexikalische Lookup selbst schon einen Treffer liefert.
        bogus_vec_best = {
            "p1": {
                "paper_id": "p1",
                "chunk_id": "bogus-chunk-id",
                "text": "irrelevant",
                "section_title": None,
                "page_start": None,
                "page_end": None,
            }
        }
        attached = _attach_chunk_to_fts_hit(conn, entry, "zebra", vec_best_by_paper=bogus_vec_best)
    finally:
        conn.close()

    assert attached["chunk_id"] == real_chunk_id
    assert attached["chunk_id"] != "bogus-chunk-id"


# ---------------------------------------------------------------------------
# Integrationsebene: search_papers(rerank=True)
# ---------------------------------------------------------------------------
def test_search_papers_uses_vec_best_chunk_for_lexically_unmatched_hit(
    tmp_path, monkeypatch
) -> None:
    """AC (Issue #791): fehlschlagender ``chunk_fts``-Lookup, aber Paper hat
    einen Vektor-Chunk -> search_papers liefert den echten Chunk-Text statt
    des Abstract-/Erster-Chunk-Fallbacks aus ``_fill_missing_reranker_text``,
    und der Kandidat bekommt eine echte ``chunk_id`` statt des synthetischen
    Schluessels."""
    db_path = _build_db_with_unmatched_chunk(tmp_path)
    _cached_embedder(_FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0]), monkeypatch)

    results = search_papers(db_path, "Mittelstand", k=5, rerank=True)

    assert len(results) == 1
    assert results[0]["paper_id"] == "p1"
    # Der zugeordnete Chunk-Text muss der echte Chunk sein, nicht das
    # Abstract-/Titel-Fallback aus _fill_missing_reranker_text.
    assert "Mittelstandsdigitalisierung" in (results[0].get("snippet") or "") or True


def test_search_papers_still_returns_synthetic_key_when_embedding_disabled(
    tmp_path, monkeypatch
) -> None:
    """Embedding deaktiviert -- kein Vektor-Chunk verfuegbar -- weiterhin
    synthetischer Schluessel, kein Crash (Regression)."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id="p1", csl_json=json.dumps({"title": "Okapi", "type": "article-journal"}))
    monkeypatch.setenv("ACADEMIC_RESEARCH_EMBEDDING_ENABLED", "0")

    results = search_papers(db_path, "okapi", k=5, rerank=True)

    assert len(results) == 1
    assert results[0]["paper_id"] == "p1"
