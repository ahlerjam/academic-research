"""Regressionstests fuer den Ablations-Harness aus #729.

Vollstaendig hermetisch -- anders als #722 braucht dieser Lauf kein
``VAULT_E5_LIVE_TEST=1``: weder #701 (Kontextsatz) noch der Reranker
(#702/#703/#714, in #722 separat vermessen) sind Teil des #726/#727-Umbaus.
AC1/AC2 laufen mit einem Playback-Embedder ueber die eingecheckte
#708-Fixture, AC3 mit einem deterministischen Fake-Embedder ueber einen
synthetischen >=50-Paper-Korpus. Beide Embedder werden direkt ueber
``embedding_model._EMBEDDER_CACHE`` vorbelegt (kein echtes Modell, kein
Netzzugriff, funktioniert unter ``block_real_embedding_backend`` genauso wie
standalone).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from academic_vault import embedding_model
from academic_vault.db import VaultDB
from academic_vault.retrieval import ENV_LOCAL_RERANKER_DISABLE, apply_reranker
from scripts.eval.run_retrieval_ablation_722 import build_db
from scripts.eval.run_retrieval_ablation_729 import (
    AC3_PAPER_COUNT,
    AC3_QUERIES,
    _chunk_fts_hits_paper_level,
    _DeterministicEmbedder,
    _env_guard,
    _paper_id_rrf,
    _vec0_search_paper_level,
    build_ac3_corpus,
    build_paper_relevance,
    compute_deltas,
    measure_index_growth,
    measure_search_latency,
    run_quality_ablation,
    run_search,
    search_papers_paper_level,
)
from scripts.eval.run_retrieval_chunk_goldset import (
    GOLDSET_PATH,
    build_playback_embedder,
    load_goldset,
    load_vectors,
)


# ---------------------------------------------------------------------------
# build_paper_relevance: reine Delegation an #722, kein zweiter Aggregations-Code
# ---------------------------------------------------------------------------
def test_build_paper_relevance_delegates_to_722_aggregation() -> None:
    goldset = {
        "chunks": [
            {"chunk_id": "d1#0", "doc_id": "d1"},
            {"chunk_id": "d2#0", "doc_id": "d2"},
        ],
        "queries": [{"query_id": "q1", "relevant_chunk_ids": ["d1#0"]}],
    }
    assert build_paper_relevance(goldset) == {"q1": {"d1"}}


# ---------------------------------------------------------------------------
# _paper_id_rrf: differenzieller Beweis gegen den historischen Stand vor #727
# (Commit a32f570^:academic_vault/retrieval.py::reciprocal_rank_fusion)
# ---------------------------------------------------------------------------
def test_paper_id_rrf_keys_on_paper_id_not_chunk_id() -> None:
    """Zwei Chunks DESSELBEN Papers verdraengen sich (das war der #727-Fund)."""
    vec_results = [
        {"paper_id": "p1", "chunk_id": "c1", "distance": 0.1},
        {"paper_id": "p1", "chunk_id": "c2", "distance": 0.2},
        {"paper_id": "p2", "chunk_id": "c3", "distance": 0.3},
    ]
    fused = _paper_id_rrf(vec_results, [], k=60)
    # Nur EIN Eintrag je paper_id -- die zweite p1-Zeile ueberschreibt die erste
    # beim dict-update, das rrf_score bleibt trotzdem korrekt (ein Rang je Paper).
    paper_ids = [f["paper_id"] for f in fused]
    assert paper_ids.count("p1") == 1
    assert set(paper_ids) == {"p1", "p2"}


def test_paper_id_rrf_metadata_merge_fts_wins_on_collision() -> None:
    """Bei Schluesselkollision gewinnt FTS (identisch zum historischen Code)."""
    vec_results = [{"paper_id": "p1", "chunk_id": "c1", "distance": 0.1, "snippet": "vec"}]
    fts_results = [{"paper_id": "p1", "score": -5.0, "snippet": "fts"}]
    fused = _paper_id_rrf(vec_results, fts_results, k=60)
    assert fused[0]["snippet"] == "fts"
    assert fused[0]["distance"] == 0.1  # vec-Feld bleibt erhalten
    assert fused[0]["score"] == -5.0


def test_paper_id_rrf_sorts_descending_and_truncates_top_n() -> None:
    vec_results = [
        {"paper_id": "p1", "chunk_id": "c1", "distance": 0.1},
        {"paper_id": "p2", "chunk_id": "c2", "distance": 0.2},
        {"paper_id": "p3", "chunk_id": "c3", "distance": 0.3},
    ]
    fused = _paper_id_rrf(vec_results, [], k=60, top_n=2)
    assert len(fused) == 2
    assert fused[0]["paper_id"] == "p1"  # bester Vektor-Rang -> hoechster Score
    assert fused[0]["rrf_score"] >= fused[1]["rrf_score"]


# ---------------------------------------------------------------------------
# _vec0_search_paper_level: Paper-Dedup wie vor #727
# ---------------------------------------------------------------------------
def _build_two_paper_db(tmp_path) -> str:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.register_embedding_inventory("intfloat/multilingual-e5-small", 4)
    for paper_id, title in (("p1", "Paper One"), ("p2", "Paper Two")):
        db.add_paper(
            paper_id=paper_id, csl_json=json.dumps({"title": title, "type": "article-journal"})
        )
    from academic_vault.embedding_model import l2_normalize, serialize_f32

    # p1 hat zwei Chunks (best-per-paper muss den naeheren waehlen), p2 einen.
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text="p1 chunk far",
        context_sentence="ctx",
        embedding_text="ctx p1 chunk far",
        embedding_vector=serialize_f32(l2_normalize([1.0, 0.0, 0.0, 0.0])),
    )
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text="p1 chunk near",
        context_sentence="ctx",
        embedding_text="ctx p1 chunk near",
        embedding_vector=serialize_f32(l2_normalize([0.9, 0.1, 0.0, 0.0])),
    )
    db.add_chunk_embedding(
        paper_id="p2",
        chunk_text="p2 chunk",
        context_sentence="ctx",
        embedding_text="ctx p2 chunk",
        embedding_vector=serialize_f32(l2_normalize([0.0, 1.0, 0.0, 0.0])),
    )
    return db_path


class _FixedVectorEmbedder:
    """Minimaler Embedder: liefert fuer JEDE Query denselben Vektor."""

    model_id = "intfloat/multilingual-e5-small"
    dim = 4

    def __init__(self, vector: list[float]) -> None:
        from academic_vault.embedding_model import l2_normalize

        self._vector = l2_normalize(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector


def test_vec0_search_paper_level_keeps_only_best_chunk_per_paper(tmp_path) -> None:
    db_path = _build_two_paper_db(tmp_path)
    embedder = _FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0])
    prior = dict(embedding_model._EMBEDDER_CACHE)
    embedding_model._EMBEDDER_CACHE[embedder.model_id] = embedder
    try:
        results = _vec0_search_paper_level(db_path, "irrelevant query text", k=10)
    finally:
        embedding_model._EMBEDDER_CACHE.clear()
        embedding_model._EMBEDDER_CACHE.update(prior)

    paper_ids = [r["paper_id"] for r in results]
    assert paper_ids.count("p1") == 1  # nicht zwei Eintraege trotz zwei Chunks
    assert set(paper_ids) == {"p1", "p2"}
    # p1 ("chunk near", 0.9/0.1) liegt naeher am Query-Vektor (1,0,0,0) als p2
    # (0,1,0,0) -- p1 muss vor p2 stehen.
    assert paper_ids[0] == "p1"


def test_vec0_search_paper_level_truncates_to_k(tmp_path) -> None:
    db_path = _build_two_paper_db(tmp_path)
    embedder = _FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0])
    prior = dict(embedding_model._EMBEDDER_CACHE)
    embedding_model._EMBEDDER_CACHE[embedder.model_id] = embedder
    try:
        results = _vec0_search_paper_level(db_path, "q", k=1)
    finally:
        embedding_model._EMBEDDER_CACHE.clear()
        embedding_model._EMBEDDER_CACHE.update(prior)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# _chunk_fts_hits_paper_level: Chunk-FTS (#726), aber auf Paper-Ebene aggregiert
# ---------------------------------------------------------------------------
def test_chunk_fts_hits_paper_level_dedupes_and_caps_at_k(tmp_path) -> None:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id="p1", csl_json=json.dumps({"title": "x", "type": "article-journal"}))
    db.add_paper(paper_id="p2", csl_json=json.dumps({"title": "y", "type": "article-journal"}))
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text="zebra migration patterns across the savanna",
        context_sentence="ctx",
        embedding_text="ctx zebra migration patterns across the savanna",
        embedding_vector=None,
    )
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text="a second zebra chunk about migration too",
        context_sentence="ctx",
        embedding_text="ctx a second zebra chunk about migration too",
        embedding_vector=None,
    )
    db.add_chunk_embedding(
        paper_id="p2",
        chunk_text="zebra herds and migration behaviour",
        context_sentence="ctx",
        embedding_text="ctx zebra herds and migration behaviour",
        embedding_vector=None,
    )
    conn = VaultDB._open(db_path)
    try:
        hits = _chunk_fts_hits_paper_level(conn, "zebra migration", k=10)
    finally:
        conn.close()
    paper_ids = [h["paper_id"] for h in hits]
    assert len(paper_ids) == len(set(paper_ids))  # keine Dubletten
    assert set(paper_ids) == {"p1", "p2"}
    for h in hits:
        assert h["text"]  # voller Chunk-Text, kein Snippet-Fallback noetig


def test_chunk_fts_hits_paper_level_respects_k_cap(tmp_path) -> None:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    for i in range(3):
        pid = f"p{i}"
        db.add_paper(paper_id=pid, csl_json=json.dumps({"title": pid, "type": "article-journal"}))
        db.add_chunk_embedding(
            paper_id=pid,
            chunk_text="zebra migration text",
            context_sentence="ctx",
            embedding_text=f"ctx zebra migration text {i}",
            embedding_vector=None,
        )
    conn = VaultDB._open(db_path)
    try:
        hits = _chunk_fts_hits_paper_level(conn, "zebra", k=2)
    finally:
        conn.close()
    assert len(hits) == 2


# ---------------------------------------------------------------------------
# search_papers_paper_level: Shim-Zusammenspiel (fts_source-Umschaltung)
# ---------------------------------------------------------------------------
def test_search_papers_paper_level_empty_query_returns_empty(tmp_path) -> None:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    assert search_papers_paper_level(db_path, "   ", k=5, fts_source="papers_fts") == []
    assert search_papers_paper_level(db_path, "   ", k=5, fts_source="chunk_fts") == []


def test_search_papers_paper_level_rejects_unknown_fts_source(tmp_path) -> None:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id="p1", csl_json=json.dumps({"title": "x", "type": "article-journal"}))
    with pytest.raises(ValueError):
        search_papers_paper_level(db_path, "zebra", k=5, fts_source="bogus")


# ---------------------------------------------------------------------------
# run_search: Precondition chunk_fusion=True -> chunk_fts_index=True
# ---------------------------------------------------------------------------
def test_run_search_rejects_chunk_fusion_without_chunk_fts_index(tmp_path) -> None:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    with pytest.raises(ValueError):
        run_search(db_path, "zebra", k=5, chunk_fts_index=False, chunk_fusion=True)


# ---------------------------------------------------------------------------
# _env_guard: Reranker aus, Cloud-Keys neutralisiert, alles beim Verlassen
# wiederhergestellt (Regression gegen den #722-Fund: Tippfehler im Env-Namen
# wuerde denselben Zustand zweimal messen).
# ---------------------------------------------------------------------------
def test_env_guard_disables_local_reranker(monkeypatch) -> None:
    monkeypatch.delenv(ENV_LOCAL_RERANKER_DISABLE, raising=False)
    with _env_guard():
        candidates = [{"paper_id": "p1", "text": "irrelevant"}]
        result = apply_reranker(query="q", candidates=candidates)
        assert result[0]["reranked"] is False
        assert result[0]["reranker"] == "none"
    # Nach dem Guard: Umgebungsvariable wieder entfernt (Ausgangszustand).
    import os

    assert os.environ.get(ENV_LOCAL_RERANKER_DISABLE) is None


def test_env_guard_restores_prior_local_rerank_value(monkeypatch) -> None:
    monkeypatch.setenv(ENV_LOCAL_RERANKER_DISABLE, "prior-value")
    with _env_guard():
        pass
    import os

    assert os.environ.get(ENV_LOCAL_RERANKER_DISABLE) == "prior-value"


def test_env_guard_restores_cloud_keys(monkeypatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "secret")
    with _env_guard():
        import os

        assert "VOYAGE_API_KEY" not in os.environ
    import os

    assert os.environ.get("VOYAGE_API_KEY") == "secret"


# ---------------------------------------------------------------------------
# compute_deltas: Vorzeichen-/Trennungslogik (Muster #722)
# ---------------------------------------------------------------------------
def test_compute_deltas_separates_index_and_fusion_contribution() -> None:
    results = {
        "vorher": {"overall": {"recall_at_10": 0.7, "ndcg_at_10": 0.60, "mrr": 0.55}},
        "zwischenzustand_a": {"overall": {"recall_at_10": 0.7, "ndcg_at_10": 0.65, "mrr": 0.55}},
        "nachher": {"overall": {"recall_at_10": 0.7, "ndcg_at_10": 0.63, "mrr": 0.58}},
    }
    deltas = compute_deltas(results)
    # A gegenueber 'vorher': Index-Beitrag +0.05 nDCG
    assert deltas["chunk_fts_index_beitrag"]["ndcg_at_10"] == pytest.approx(0.05)
    # 'nachher' gegenueber A: Fusions-Beitrag NEGATIV (-0.02) -- muss als
    # Regression sichtbar sein, nicht wegkompensiert werden.
    assert deltas["chunk_fusion_beitrag"]["ndcg_at_10"] == pytest.approx(-0.02)
    assert deltas["gesamt"]["ndcg_at_10"] == pytest.approx(0.03)
    assert deltas["chunk_fusion_beitrag"]["mrr"] == pytest.approx(0.03)


def test_run_quality_ablation_flags_regression_when_a_metric_worsens() -> None:
    """Smoke: ``regressions`` im finalen Report-Dict wird aus negativen Deltas abgeleitet."""
    results = {
        "vorher": {"overall": {"recall_at_10": 0.7, "ndcg_at_10": 0.60, "mrr": 0.55}},
        "zwischenzustand_a": {"overall": {"recall_at_10": 0.7, "ndcg_at_10": 0.65, "mrr": 0.55}},
        "nachher": {"overall": {"recall_at_10": 0.7, "ndcg_at_10": 0.63, "mrr": 0.58}},
    }
    deltas = compute_deltas(results)
    regressions = {name: d for name, d in deltas.items() if any(v < 0 for v in d.values())}
    assert "chunk_fusion_beitrag" in regressions
    assert "chunk_fts_index_beitrag" not in regressions


# ---------------------------------------------------------------------------
# run_quality_ablation: Ende-zu-Ende, hermetisch, gegen die echte #708-Fixture
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_run_quality_ablation_is_hermetic_and_returns_three_states() -> None:
    """Kein VAULT_E5_LIVE_TEST=1 noetig -- laeuft unter block_real_embedding_backend."""
    goldset = load_goldset()
    vectors = dict(load_vectors())
    report = run_quality_ablation(goldset, vectors, k=10)

    assert set(report["results"].keys()) == {"vorher", "zwischenzustand_a", "nachher"}
    assert set(report["deltas"].keys()) == {
        "chunk_fts_index_beitrag",
        "chunk_fusion_beitrag",
        "gesamt",
    }
    for result in report["results"].values():
        assert len(result["per_query"]) == len(goldset["queries"])
        for metric in ("recall_at_10", "ndcg_at_10", "mrr"):
            assert 0.0 <= result["overall"][metric] <= 1.0


@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_run_quality_ablation_matches_pre_708_baseline_values() -> None:
    """'vorher' (paper_id-Fusion, papers_fts, Reranker aus) reproduziert die
    im #708-Report/#722-Lauf dokumentierte Baseline (Recall/nDCG/MRR ohne
    jede der vier #722-Aenderungen UND ohne #726/#727)."""
    goldset = load_goldset()
    vectors = dict(load_vectors())
    report = run_quality_ablation(goldset, vectors, k=10)
    vorher = report["results"]["vorher"]["overall"]
    assert vorher["recall_at_10"] == pytest.approx(0.7308, abs=0.001)


@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_run_quality_ablation_leaves_embedder_cache_clean() -> None:
    """Nach dem Lauf ist der Embedder-Cache-Zustand wiederhergestellt (kein Leck
    in andere Tests der Suite, die denselben Cache teilen)."""
    prior = dict(embedding_model._EMBEDDER_CACHE)
    goldset = load_goldset()
    vectors = dict(load_vectors())
    run_quality_ablation(goldset, vectors, k=10)
    assert embedding_model._EMBEDDER_CACHE == prior


@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_fts5_comma_defect_affects_both_fts_sources_identically() -> None:
    """Derselbe vorbestehende Defekt wie in #722 (Komma nicht sanitisiert,
    sqlite3.OperationalError) betrifft chunk_fts UND papers_fts gleichermassen
    -- kein #729-spezifisches Verhalten, nur die gemeinsame Ursache in
    ``db._sanitize_fts5_query``."""
    goldset = load_goldset()
    vectors = dict(load_vectors())
    doc_titles = {d["doc_id"]: d["title"] for d in goldset["documents"]}
    chunk_vectors = {c["chunk_id"]: vectors[c["chunk_id"]] for c in goldset["chunks"]}
    embedding_texts = {c["chunk_id"]: c["embedding_text"] for c in goldset["chunks"]}
    embedder = build_playback_embedder(goldset, vectors)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = build_db(
            Path(tmp), "x", goldset, doc_titles, chunk_vectors, embedding_texts, trigram=True
        )
        prior = dict(embedding_model._EMBEDDER_CACHE)
        embedding_model._EMBEDDER_CACHE[embedder.model_id] = embedder
        try:
            with pytest.raises(sqlite3.OperationalError):
                search_papers_paper_level(
                    db_path, "wie erkennt man frueh, dass etwas fehlt", k=5, fts_source="papers_fts"
                )
            with pytest.raises(sqlite3.OperationalError):
                search_papers_paper_level(
                    db_path, "wie erkennt man frueh, dass etwas fehlt", k=5, fts_source="chunk_fts"
                )
        finally:
            embedding_model._EMBEDDER_CACHE.clear()
            embedding_model._EMBEDDER_CACHE.update(prior)


# ---------------------------------------------------------------------------
# AC3: deterministischer Fake-Embedder
# ---------------------------------------------------------------------------
def test_deterministic_embedder_is_deterministic() -> None:
    e = _DeterministicEmbedder(dim=8, seed=1)
    assert e.embed_query("hello") == e.embed_query("hello")


def test_deterministic_embedder_differs_per_text() -> None:
    e = _DeterministicEmbedder(dim=8, seed=1)
    assert e.embed_query("hello") != e.embed_query("world")


def test_deterministic_embedder_is_l2_normalized() -> None:
    import math

    e = _DeterministicEmbedder(dim=16, seed=1)
    vec = e.embed_query("some text")
    norm = math.sqrt(sum(v * v for v in vec))
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_deterministic_embedder_seed_changes_vector() -> None:
    a = _DeterministicEmbedder(dim=8, seed=1).embed_query("hello")
    b = _DeterministicEmbedder(dim=8, seed=2).embed_query("hello")
    assert a != b


# ---------------------------------------------------------------------------
# AC3: Korpusgroesse (Akzeptanzkriterium: mindestens 50 Paper)
# ---------------------------------------------------------------------------
def test_ac3_paper_count_constant_meets_acceptance_criterion() -> None:
    assert AC3_PAPER_COUNT >= 50


def test_build_ac3_corpus_returns_requested_paper_count() -> None:
    corpus = build_ac3_corpus(n_papers=55, seed=1)
    assert len(corpus) == 55
    assert len({p["paper_id"] for p in corpus}) == 55  # eindeutige IDs


def test_build_ac3_corpus_is_deterministic_given_same_seed() -> None:
    a = build_ac3_corpus(n_papers=5, seed=42)
    b = build_ac3_corpus(n_papers=5, seed=42)
    assert a == b


def test_build_ac3_corpus_every_paper_has_pages() -> None:
    corpus = build_ac3_corpus(n_papers=5, seed=1)
    for paper in corpus:
        assert len(paper["pages"]) >= 2
        for page_no, text in paper["pages"]:
            assert isinstance(page_no, int)
            assert text.strip()


# ---------------------------------------------------------------------------
# AC3: Index-Groesse (kleine Stichprobe fuer Testlaufzeit, echte Messung im
# Live-Report nutzt AC3_PAPER_COUNT >= 50)
# ---------------------------------------------------------------------------
def test_measure_index_growth_shows_chunk_fts_adds_bytes(tmp_path) -> None:
    corpus = build_ac3_corpus(n_papers=8, seed=1)
    growth = measure_index_growth(tmp_path, corpus)
    assert growth["bytes_with_chunk_fts"] > growth["bytes_without_chunk_fts"]
    assert growth["growth_bytes"] > 0
    assert growth["growth_pct"] is not None and growth["growth_pct"] > 0


def test_measure_index_growth_same_paper_and_chunk_content_both_dbs(tmp_path) -> None:
    """Beide DBs enthalten denselben Chunk-Bestand -- der einzige Unterschied
    ist die An-/Abwesenheit von ``chunk_fts`` (isoliert den Index-Beitrag)."""
    corpus = build_ac3_corpus(n_papers=5, seed=1)
    from scripts.eval.run_retrieval_ablation_729 import _build_ac3_db

    with_path = _build_ac3_db(tmp_path, "w", corpus, with_chunk_fts=True)
    without_path = _build_ac3_db(tmp_path, "wo", corpus, with_chunk_fts=False)

    conn_w = VaultDB._open(with_path)
    conn_wo = VaultDB._open(without_path)
    try:
        count_w = conn_w.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        count_wo = conn_wo.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        assert count_w == count_wo
        assert count_w > 0
        tables = {
            r[0] for r in conn_wo.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "chunk_fts" not in tables
    finally:
        conn_w.close()
        conn_wo.close()


# ---------------------------------------------------------------------------
# AC3: Suchlatenz (Shape-Test, keine harten Zeitschwellen -- Timing ist
# maschinenabhaengig, siehe Report fuer die tatsaechlichen Messwerte)
# ---------------------------------------------------------------------------
def test_measure_search_latency_returns_all_three_states(tmp_path) -> None:
    corpus = build_ac3_corpus(n_papers=8, seed=1)
    from scripts.eval.run_retrieval_ablation_729 import _build_ac3_db

    db_path = _build_ac3_db(tmp_path, "latency", corpus, with_chunk_fts=True)
    latency = measure_search_latency(db_path, queries=AC3_QUERIES[:2], repeats=1)
    assert set(latency.keys()) == {"vorher", "zwischenzustand_a", "nachher"}
    for stats in latency.values():
        assert stats["p50_ms"] > 0.0
        assert stats["p95_ms"] >= stats["p50_ms"]
        assert stats["n"] == 2


def test_measure_search_latency_restores_embedder_cache_and_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("VAULT_EMBEDDING_MODEL", raising=False)
    corpus = build_ac3_corpus(n_papers=5, seed=1)
    from scripts.eval.run_retrieval_ablation_729 import _build_ac3_db

    db_path = _build_ac3_db(tmp_path, "latency2", corpus, with_chunk_fts=True)
    prior_cache = dict(embedding_model._EMBEDDER_CACHE)
    measure_search_latency(db_path, queries=AC3_QUERIES[:1], repeats=1)
    assert embedding_model._EMBEDDER_CACHE == prior_cache
    import os

    assert "VAULT_EMBEDDING_MODEL" not in os.environ
