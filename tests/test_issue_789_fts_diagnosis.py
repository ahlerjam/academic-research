"""Regressionstests fuer die Nullbefund-Diagnose aus Issue #789.

#711-A Kind-Issue, Nachfolger von #729 (PR #781). Der #729-Report erklaerte
den Nullbefund (alle drei Retrieval-Zustaende liefern query-fuer-query
identische Ergebnisse) mit "Korpus zu klein / gesaettigt". Diese Diagnose ist
unvollstaendig: die eigentliche Ursache ist eine strukturell tote
lexikalische Seite im #708-Goldset (nur 1 von 26 Queries erzielt ueberhaupt
einen ``papers_fts``-Treffer, 0 bei ``papers_trgm``).

Zwei Kernbelege (Issue-Tasks):

1. :func:`test_empty_fts_makes_chunk_and_paper_level_fusion_order_equivalent`
   -- formaler Beleg, dass bei leerer FTS-Trefferliste Paper-Ebene-Fusion und
   Chunk-Ebene-Fusion + MAX-Aggregation ordnungsgleich sind, direkt gegen
   ``academic_vault.retrieval.reciprocal_rank_fusion`` und
   ``academic_vault.server._aggregate_chunks_to_papers`` (kein Mock der
   Kernlogik, kein DB-Fixture noetig).
2. :func:`test_708_goldset_lexical_side_is_structurally_dead` -- dokumentiert
   die tote lexikalische Seite des #708-Goldsets als Zahl statt Prosa.

Der Rest der Datei deckt die neuen Diagnose-Bausteine aus
``scripts/eval/run_retrieval_ablation_729.py`` ab (:func:`diagnose_query`,
:func:`run_diagnostics`, ``_aggregate_by_case``, ``_diagnostics_by_case``).
"""

from __future__ import annotations

import json
import random
import sqlite3
import tempfile
from pathlib import Path

import pytest
from academic_vault.db import VaultDB
from academic_vault.retrieval import ENV_LOCAL_RERANKER_DISABLE, reciprocal_rank_fusion
from academic_vault.server import _aggregate_chunks_to_papers, _fts_exact_hits, _fts_trigram_hits
from scripts.eval.run_retrieval_ablation_722 import build_db
from scripts.eval.run_retrieval_ablation_729 import (
    _aggregate_by_case,
    _diagnostics_by_case,
    diagnose_query,
    run_diagnostics,
)
from scripts.eval.run_retrieval_chunk_goldset import GOLDSET_PATH, load_goldset, load_vectors

pytestmark = pytest.mark.usefixtures("_reset_local_reranker_env")


@pytest.fixture
def _reset_local_reranker_env(monkeypatch):
    """Reranker konstant AUS -- dieses Issue misst Fusion/Index, nicht Reranking."""
    monkeypatch.setenv(ENV_LOCAL_RERANKER_DISABLE, "1")


# ---------------------------------------------------------------------------
# Task 1 (AC): formaler Beleg der Ordnungsgleichheit bei leerer FTS-Liste
# ---------------------------------------------------------------------------
def test_empty_fts_makes_chunk_and_paper_level_fusion_order_equivalent() -> None:
    """#789 Kernaussage: ``1/(60+r)`` ist streng monoton, MAX ueber
    Chunk-Raenge je Paper reproduziert deshalb exakt die Paper-Dedup-Ordnung
    -- unabhaengig von Korpusgroesse. Direkt gegen die Produktionsfunktionen,
    kein DB-Fixture, kein Mock der Kernlogik."""
    vec_results = [
        {"paper_id": "p1", "chunk_id": "p1-a", "distance": 0.10},
        {"paper_id": "p2", "chunk_id": "p2-a", "distance": 0.15},
        {"paper_id": "p1", "chunk_id": "p1-b", "distance": 0.20},  # zweiter Chunk von p1
        {"paper_id": "p3", "chunk_id": "p3-a", "distance": 0.30},
        {"paper_id": "p2", "chunk_id": "p2-b", "distance": 0.35},
        {"paper_id": "p1", "chunk_id": "p1-c", "distance": 0.40},  # dritter Chunk von p1
    ]
    fused = reciprocal_rank_fusion(vec_results, [], k=60, top_n=len(vec_results))
    aggregated = _aggregate_chunks_to_papers(fused, k=10)

    # 'vorher' (Paper-Ebene-Fusion vor #726/#727): best-per-paper nach
    # Vektor-Rang (kleinste Distanz gewinnt), sortiert nach diesem besten Rang.
    # p1 bester Chunk 0.10, p2 bester Chunk 0.15, p3 einziger Chunk 0.30.
    assert [e["paper_id"] for e in aggregated] == ["p1", "p2", "p3"]
    # Der Gewinner-Chunk je Paper ist tatsaechlich der naechste Chunk desselben Papers.
    winner_by_paper = {e["paper_id"]: e["chunk_id"] for e in aggregated}
    assert winner_by_paper["p1"] == "p1-a"
    assert winner_by_paper["p2"] == "p2-a"
    assert winner_by_paper["p3"] == "p3-a"


def test_empty_fts_order_equivalence_holds_for_randomized_chunk_layouts() -> None:
    """Wiederholung des obigen Beweises ueber viele zufaellige Chunk-Layouts
    (fester Seed, deterministisch) -- ``rrf_score`` ist bei leerer FTS-Liste
    ausschliesslich eine Funktion des Vektor-Rangs, die Paper-Reihenfolge nach
    Chunk-Fusion+MAX-Aggregation muss deshalb IMMER mit der Paper-Reihenfolge
    nach purer Vektor-Bestchunk-Dedup uebereinstimmen, unabhaengig von der
    Anzahl Chunks je Paper."""
    rng = random.Random(789)
    for _ in range(25):
        n_papers = rng.randint(2, 8)
        vec_results = []
        used_distances: set[float] = set()
        for p in range(n_papers):
            n_chunks = rng.randint(1, 4)
            for c in range(n_chunks):
                while True:
                    distance = round(rng.uniform(0.0, 1.0), 6)
                    if distance not in used_distances:
                        used_distances.add(distance)
                        break
                vec_results.append(
                    {
                        "paper_id": f"p{p}",
                        "chunk_id": f"p{p}-c{c}",
                        "distance": distance,
                    }
                )
        rng.shuffle(vec_results)  # _vec0_search liefert aufsteigend, hier bewusst NICHT sortiert
        # 'vorher': aufsteigend nach Distanz sortieren, bestes (kleinstes) je Paper behalten.
        vec_results_sorted = sorted(vec_results, key=lambda e: e["distance"])
        expected_best: dict[str, dict] = {}
        for r in vec_results_sorted:
            expected_best.setdefault(r["paper_id"], r)
        expected_order = [
            r["paper_id"] for r in sorted(expected_best.values(), key=lambda e: e["distance"])
        ]

        fused = reciprocal_rank_fusion(vec_results_sorted, [], k=60, top_n=len(vec_results_sorted))
        aggregated = _aggregate_chunks_to_papers(fused, k=len(expected_order))

        assert [e["paper_id"] for e in aggregated] == expected_order
        for e in aggregated:
            assert e["chunk_id"] == expected_best[e["paper_id"]]["chunk_id"]


# ---------------------------------------------------------------------------
# Task 2 (AC): tote lexikalische Seite des #708-Goldsets als Zahl
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_708_goldset_lexical_side_is_structurally_dead() -> None:
    """Nur 1 von 60 Queries (26 vor #800) erzielt ueberhaupt einen
    ``papers_fts``-Treffer, 0 bei ``papers_trgm`` -- Zahl statt Prosa (die
    Ursache, die die "Korpus zu klein"-Diagnose im #729-Report korrigiert).
    Ausgeschriebene Saetze mit implizitem AND ueber alle Tokens sind die
    strukturelle Ursache: FTS5-MATCH
    ohne OR-Operator verlangt jedes Token im indizierten Feld."""
    goldset = load_goldset()
    vectors = dict(load_vectors())
    doc_titles = {d["doc_id"]: d["title"] for d in goldset["documents"]}
    chunk_vectors = {c["chunk_id"]: vectors[c["chunk_id"]] for c in goldset["chunks"]}
    embedding_texts = {c["chunk_id"]: c["embedding_text"] for c in goldset["chunks"]}

    with tempfile.TemporaryDirectory() as tmp:
        db_path = build_db(
            Path(tmp), "lex", goldset, doc_titles, chunk_vectors, embedding_texts, trigram=True
        )
        conn = VaultDB._open(db_path)
        try:
            from academic_vault.server import _sanitize_fts5_query

            exact_hit_queries = 0
            trigram_hit_queries = 0
            for query in goldset["queries"]:
                sanitized = _sanitize_fts5_query(query["query"])
                if not sanitized:
                    continue
                try:
                    exact = _fts_exact_hits(conn, sanitized, None, 10)
                    trigram = _fts_trigram_hits(conn, sanitized, None, 10)
                except sqlite3.OperationalError:
                    # Derselbe vorbestehende Komma-Defekt wie in #722/#729
                    # (db._sanitize_fts5_query haertet kein Komma ab) --
                    # eigener, bereits dokumentierter Befund, hier irrelevant
                    # fuer die Zaehlung der TATSAECHLICH ausgewerteten Queries.
                    continue
                if exact:
                    exact_hit_queries += 1
                if trigram:
                    trigram_hit_queries += 1
        finally:
            conn.close()

    assert len(goldset["queries"]) == 60
    assert exact_hit_queries == 1
    assert trigram_hit_queries == 0


# ---------------------------------------------------------------------------
# diagnose_query: Feld-fuer-Feld gegen eine kleine, kontrollierte DB
# ---------------------------------------------------------------------------
def _build_two_paper_lexical_db(tmp_path) -> str:
    """Ein Paper mit einem lexikalisch treffenden Chunk (fuer den echten
    ``_attach_chunk_to_fts_hit``-Pfad), ein zweites Paper, das nur ueber den
    Vektor gefunden wird."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="p1",
        csl_json=json.dumps({"title": "Zebra Migration Patterns", "type": "article-journal"}),
    )
    db.add_paper(
        paper_id="p2", csl_json=json.dumps({"title": "Giraffe Herds", "type": "article-journal"})
    )
    db.register_embedding_inventory("intfloat/multilingual-e5-small", 4)
    from academic_vault.embedding_model import l2_normalize, serialize_f32

    # Woertlich "zebra" (nicht "zebras"): FTS5 unicode61 stemmt nicht, ein
    # Plural-Token wuerde den chunk_fts-MATCH gegen die Query "zebra" NICHT
    # treffen und faelschlich den synthetischen-Schluessel-Pfad testen.
    chunk_text = "The zebra population roams across the savanna in long seasonal loops."
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text=chunk_text,
        context_sentence="ctx",
        embedding_text=f"ctx {chunk_text}",
        embedding_vector=serialize_f32(l2_normalize([1.0, 0.0, 0.0, 0.0])),
    )
    db.add_chunk_embedding(
        paper_id="p2",
        chunk_text="Giraffes browse acacia trees at dawn.",
        context_sentence="ctx",
        embedding_text="ctx Giraffes browse acacia trees at dawn.",
        embedding_vector=serialize_f32(l2_normalize([0.0, 1.0, 0.0, 0.0])),
    )
    return db_path


class _FixedVectorEmbedder:
    model_id = "intfloat/multilingual-e5-small"
    dim = 4

    def __init__(self, vector: list[float]) -> None:
        from academic_vault.embedding_model import l2_normalize

        self._vector = l2_normalize(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector


def _cached_embedder(embedder, monkeypatch):
    from academic_vault import embedding_model

    monkeypatch.setitem(embedding_model._EMBEDDER_CACHE, embedder.model_id, embedder)
    monkeypatch.setenv("VAULT_EMBEDDING_MODEL", embedder.model_id)


def test_diagnose_query_finds_real_fts_hit_and_attaches_matching_chunk(
    tmp_path, monkeypatch
) -> None:
    db_path = _build_two_paper_lexical_db(tmp_path)
    _cached_embedder(_FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0]), monkeypatch)

    result = diagnose_query(db_path, "zebra", k=5)

    assert result["fts5_syntax_error"] is None
    assert result["papers_fts_hit_count"] == 1
    assert result["papers_trgm_hit_count"] == 0
    assert result["fts_hit_count"] == 1
    assert result["fts_ranking"] == ["p1"]
    # Echter Chunk-Lookup (server._attach_chunk_to_fts_hit) statt synthetischem
    # Schluessel -- der Chunk enthaelt tatsaechlich "zebra".
    assert result["attached_chunk"]["p1"] is not None
    assert "p1" in result["vec_paper_rank"]
    assert "p2" in result["vec_paper_rank"]


def test_diagnose_query_reports_synthetic_key_as_none_attached_chunk(tmp_path, monkeypatch) -> None:
    """Query trifft den Papertitel nur ueber ein Token, das in KEINEM Chunk
    steht -- ``_attach_chunk_to_fts_hit`` faellt auf den synthetischen
    Schluessel ``fts-paper::<pid>`` zurueck, ``attached_chunk`` muss dafuer
    ``None`` zeigen (nicht den synthetischen String selbst)."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="p1",
        csl_json=json.dumps({"title": "Okapi Sightings", "type": "article-journal"}),
    )
    # Kein Chunk fuer p1 -- der Titel-Treffer hat keinen Chunk zum Zuordnen.
    _cached_embedder(_FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0]), monkeypatch)

    result = diagnose_query(db_path, "okapi", k=5)

    assert result["papers_fts_hit_count"] == 1
    assert result["attached_chunk"]["p1"] is None
    assert result["attach_equals_vec_best"]["p1"] is False


def test_diagnose_query_empty_query_returns_zeroed_result(tmp_path) -> None:
    db_path = str(tmp_path / "vault.db")
    VaultDB(db_path).init_schema()
    result = diagnose_query(db_path, "   ", k=5)
    assert result["fts_hit_count"] == 0
    assert result["fts_ranking"] == []
    assert result["vec_paper_rank"] == {}


def test_diagnose_query_surfaces_fts5_comma_defect_without_crashing(tmp_path, monkeypatch) -> None:
    """Derselbe vorbestehende Komma-Defekt wie in #722/#729 (nicht
    #789-spezifisch): die Diagnose darf daran nicht abstuerzen, sondern
    meldet ihn im Feld ``fts5_syntax_error``."""
    db_path = _build_two_paper_lexical_db(tmp_path)
    _cached_embedder(_FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0]), monkeypatch)

    result = diagnose_query(db_path, "zebra, giraffe", k=5)

    assert result["fts5_syntax_error"] is not None
    assert result["fts_hit_count"] == 0
    assert result["vec_paper_rank"] == {}


def test_diagnose_query_min_score_gap_is_positive_for_distinct_vec_ranks(
    tmp_path, monkeypatch
) -> None:
    db_path = _build_two_paper_lexical_db(tmp_path)
    _cached_embedder(_FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0]), monkeypatch)

    result = diagnose_query(db_path, "zebra", k=5)

    assert result["min_score_gap_at_k"] is not None
    assert result["min_score_gap_at_k"] >= 0.0


# ---------------------------------------------------------------------------
# run_diagnostics: Ende-zu-Ende gegen das echte #708-Goldset
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_run_diagnostics_confirms_almost_all_queries_have_no_fts_hit() -> None:
    """AC: "Der Diagnoseblock laeuft gegen das bestehende #708-Set und
    bestaetigt numerisch, dass die FTS-Seite bei fast allen Queries leer
    bleibt" (25 von 26 vor #800, 59 von 60 seit #800 -- die eine treffende
    Query ist unveraendert ``q-en-01``, siehe
    ``test_708_goldset_lexical_side_is_structurally_dead``)."""
    goldset = load_goldset()
    vectors = dict(load_vectors())
    report = run_diagnostics(goldset, vectors, k=10)

    assert report["summary"]["query_count"] == 60
    assert report["summary"]["queries_with_any_fts_hit"] == 1
    assert report["summary"]["queries_with_papers_trgm_hit"] == 0
    empty_count = report["summary"]["query_count"] - report["summary"]["queries_with_any_fts_hit"]
    assert empty_count == 59
    assert set(report["summary"]["by_case"].keys()) == {
        "cross-language",
        "language-gap",
        "same-language",
    }


@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_run_diagnostics_leaves_embedder_cache_clean() -> None:
    from academic_vault import embedding_model

    prior = dict(embedding_model._EMBEDDER_CACHE)
    goldset = load_goldset()
    vectors = dict(load_vectors())
    run_diagnostics(goldset, vectors, k=10)
    assert embedding_model._EMBEDDER_CACHE == prior


@pytest.mark.skipif(not GOLDSET_PATH.exists(), reason="#708-Fixture nicht vorhanden")
def test_run_quality_ablation_respects_goldset_and_vectors_flags(tmp_path) -> None:
    """`--goldset`/`--vectors` (Issue #789-Task): ein alternatives Fixture-Paar
    (hier: eine Teilmenge des #708-Sets) muss anstelle des Defaults einlaufen."""
    from scripts.eval.run_retrieval_ablation_729 import run_quality_ablation

    goldset = load_goldset()
    vectors = dict(load_vectors())
    subset_goldset = dict(goldset)
    subset_goldset["queries"] = goldset["queries"][:2]

    report = run_quality_ablation(subset_goldset, vectors, k=10)
    assert report["query_count"] == 2
    for result in report["results"].values():
        assert len(result["per_query"]) == 2


# ---------------------------------------------------------------------------
# _aggregate_by_case / _diagnostics_by_case: reine Gruppierungslogik
# ---------------------------------------------------------------------------
def test_aggregate_by_case_groups_and_averages_per_case() -> None:
    per_query = [
        {
            "case": "same-language",
            "recall_at_10": 1.0,
            "ndcg_at_10": 1.0,
            "reciprocal_rank": 1.0,
        },
        {
            "case": "same-language",
            "recall_at_10": 0.0,
            "ndcg_at_10": 0.0,
            "reciprocal_rank": 0.0,
        },
        {
            "case": "language-gap",
            "recall_at_10": 0.5,
            "ndcg_at_10": 0.5,
            "reciprocal_rank": 0.5,
        },
    ]
    result = _aggregate_by_case(per_query)
    assert result["same-language"]["query_count"] == 2
    assert result["same-language"]["recall_at_10"] == pytest.approx(0.5)
    assert result["language-gap"]["query_count"] == 1
    assert result["language-gap"]["mrr"] == pytest.approx(0.5)


def test_diagnostics_by_case_counts_hits_and_errors_per_case() -> None:
    per_query = [
        {
            "case": "same-language",
            "fts5_syntax_error": None,
            "fts_hit_count": 1,
            "papers_fts_hit_count": 1,
            "papers_trgm_hit_count": 0,
        },
        {
            "case": "same-language",
            "fts5_syntax_error": None,
            "fts_hit_count": 0,
            "papers_fts_hit_count": 0,
            "papers_trgm_hit_count": 0,
        },
        {
            "case": "language-gap",
            "fts5_syntax_error": "boom",
            "fts_hit_count": 0,
            "papers_fts_hit_count": 0,
            "papers_trgm_hit_count": 0,
        },
    ]
    result = _diagnostics_by_case(per_query)
    assert result["same-language"]["query_count"] == 2
    assert result["same-language"]["queries_with_any_fts_hit"] == 1
    assert result["same-language"]["fts5_syntax_errors"] == 0
    assert result["language-gap"]["fts5_syntax_errors"] == 1
    assert result["language-gap"]["queries_with_any_fts_hit"] == 0
