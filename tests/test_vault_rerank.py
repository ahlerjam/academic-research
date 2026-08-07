"""Tests fuer Hybrid Retrieval: RRF + Reranker (#109).

TDD: Tests werden zuerst geschrieben (RED), dann Implementierung (GREEN).
"""

import json
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _make_db(tmp_path: Path) -> str:
    """Erstellt eine Vault-DB mit Schema und gibt den Pfad zurueck."""
    db_path = str(tmp_path / "vault.db")
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    db.init_schema()
    return db_path


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str) -> None:
    """Hilfsfunktion: fuegt ein Paper in den Vault ein."""
    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


# ---------------------------------------------------------------------------
# Tests: Reciprocal-Rank-Fusion (RRF)
# ---------------------------------------------------------------------------


class TestReciprocalRankFusion:
    """Unit-Tests fuer die RRF-Berechnung in retrieval.py."""

    def test_rrf_score_formula(self):
        """RRF-Score = 1/(k+rank_vec) + 1/(k+rank_fts) mit k=60."""
        from academic_vault.retrieval import rrf_score

        k = 60
        rank_vec = 1  # Rang 1 in vec0-Ergebnissen
        rank_fts = 1  # Rang 1 in FTS5-Ergebnissen
        expected = 1 / (k + rank_vec) + 1 / (k + rank_fts)
        result = rrf_score(rank_vec=rank_vec, rank_fts=rank_fts, k=k)
        assert abs(result - expected) < 1e-10

    def test_rrf_score_missing_in_one_list(self):
        """RRF-Score mit None-Rang (Paper nur in einem Ergebnis): nur ein Term."""
        from academic_vault.retrieval import rrf_score

        k = 60
        # Nur in vec0, nicht in FTS5
        result_vec_only = rrf_score(rank_vec=1, rank_fts=None, k=k)
        expected = 1 / (k + 1)
        assert abs(result_vec_only - expected) < 1e-10

        # Nur in FTS5, nicht in vec0
        result_fts_only = rrf_score(rank_vec=None, rank_fts=1, k=k)
        assert abs(result_fts_only - expected) < 1e-10

    def test_rrf_fusion_returns_sorted_by_score(self):
        """reciprocal_rank_fusion gibt Liste absteigend nach Score sortiert zurueck."""
        from academic_vault.retrieval import reciprocal_rank_fusion

        # p001 erscheint in beiden Listen (Rang 1)
        # p002 erscheint nur in vec0 (Rang 2)
        # p003 erscheint nur in FTS5 (Rang 2)
        vec_results = [
            {"paper_id": "p001", "score": 0.9},
            {"paper_id": "p002", "score": 0.7},
        ]
        fts_results = [
            {"paper_id": "p001", "score": -1.5},  # FTS5-rank ist negativ (kleinerer BM25-rank)
            {"paper_id": "p003", "score": -2.0},
        ]

        fused = reciprocal_rank_fusion(vec_results, fts_results, k=60)

        assert len(fused) == 3  # p001, p002, p003
        # p001 soll hoechsten Score haben (in beiden Listen)
        assert fused[0]["paper_id"] == "p001"
        # Scores absteigend sortiert
        scores = [r["rrf_score"] for r in fused]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_fusion_includes_all_papers(self):
        """RRF-Fusion inkludiert alle Papers aus beiden Listen."""
        from academic_vault.retrieval import reciprocal_rank_fusion

        vec_results = [{"paper_id": "p001"}, {"paper_id": "p002"}]
        fts_results = [{"paper_id": "p003"}, {"paper_id": "p001"}]

        fused = reciprocal_rank_fusion(vec_results, fts_results, k=60)
        paper_ids = {r["paper_id"] for r in fused}
        assert paper_ids == {"p001", "p002", "p003"}

    def test_rrf_fusion_paper_in_both_lists_ranks_higher(self):
        """Paper in beiden Listen rankt hoeher als Paper nur in einer Liste."""
        from academic_vault.retrieval import reciprocal_rank_fusion

        # p001 in beiden Listen, p002 nur in vec0
        vec_results = [{"paper_id": "p001"}, {"paper_id": "p002"}]
        fts_results = [{"paper_id": "p001"}]

        fused = reciprocal_rank_fusion(vec_results, fts_results, k=60)
        paper_ids = [r["paper_id"] for r in fused]
        assert paper_ids.index("p001") < paper_ids.index("p002")

    def test_rrf_fusion_empty_vec_results(self):
        """RRF-Fusion mit leerer vec0-Liste gibt FTS5-Ergebnisse zurueck."""
        from academic_vault.retrieval import reciprocal_rank_fusion

        fts_results = [{"paper_id": "p001"}, {"paper_id": "p002"}]
        fused = reciprocal_rank_fusion([], fts_results, k=60)
        assert len(fused) == 2

    def test_rrf_fusion_empty_fts_results(self):
        """RRF-Fusion mit leerer FTS5-Liste gibt vec0-Ergebnisse zurueck."""
        from academic_vault.retrieval import reciprocal_rank_fusion

        vec_results = [{"paper_id": "p001"}, {"paper_id": "p002"}]
        fused = reciprocal_rank_fusion(vec_results, [], k=60)
        assert len(fused) == 2

    def test_rrf_fusion_merges_metadata_of_both_sources(self):
        """Paper in beiden Listen behaelt FTS5-Metadaten UND vec0-Metadaten (#372).

        Regression: vorher verdraengte das vec0-Dict das FTS5-Dict komplett —
        der dokumentierte 'score' fiel weg und das '<b>'-Highlighting im
        Snippet ging verloren.
        """
        from academic_vault.retrieval import reciprocal_rank_fusion

        vec_results = [
            {
                "paper_id": "p001",
                "chunk_id": "c-1",
                "snippet": "Dense passage retrieval ohne Highlighting",
                "distance": 0.12,
            }
        ]
        fts_results = [
            {
                "paper_id": "p001",
                "snippet": "Dense passage <b>retrieval</b>...",
                "score": -1.234,
            }
        ]

        fused = reciprocal_rank_fusion(vec_results, fts_results, k=60)
        entry = fused[0]

        assert entry["score"] == -1.234, "FTS5-'score' wurde vom vec0-Dict verdraengt"
        assert "<b>" in entry["snippet"], "FTS5-Highlighting im Snippet verloren"
        assert entry["chunk_id"] == "c-1", "vec0-Metadaten duerfen nicht verloren gehen"
        assert entry["distance"] == 0.12

    def test_rrf_fusion_keeps_vec_only_metadata(self):
        """Nur-vektorielle Treffer behalten ihr Snippet (kein FTS5-Gegenstueck)."""
        from academic_vault.retrieval import reciprocal_rank_fusion

        vec_results = [{"paper_id": "p_vec", "snippet": "nur vektoriell", "distance": 0.4}]
        fts_results = [{"paper_id": "p_fts", "snippet": "<b>fts</b>", "score": -2.0}]

        by_id = {r["paper_id"]: r for r in reciprocal_rank_fusion(vec_results, fts_results, k=60)}

        assert by_id["p_vec"]["snippet"] == "nur vektoriell"
        assert "score" not in by_id["p_vec"]
        assert by_id["p_fts"]["score"] == -2.0

    def test_rrf_fusion_respects_top_n(self):
        """reciprocal_rank_fusion schneidet nach top_n ab."""
        from academic_vault.retrieval import reciprocal_rank_fusion

        vec_results = [{"paper_id": f"p{i:03d}"} for i in range(10)]
        fts_results = [{"paper_id": f"p{i:03d}"} for i in range(5, 15)]

        fused = reciprocal_rank_fusion(vec_results, fts_results, k=60, top_n=5)
        assert len(fused) == 5


# ---------------------------------------------------------------------------
# Tests: Reranker-Integration (Voyage/Cohere)
# ---------------------------------------------------------------------------


class TestRerankerIntegration:
    """Tests fuer Voyage- und Cohere-Reranker (hinter Feature-Flag)."""

    def test_rerank_with_voyage_deterministic_scores(self, tmp_path):
        """Voyage-Reranker sortiert nach deterministischen Mock-Scores."""
        from academic_vault.retrieval import rerank_with_voyage

        candidates = [
            {"paper_id": "p001", "text": "Transformer neural networks."},
            {"paper_id": "p002", "text": "Convolutional networks for images."},
            {"paper_id": "p003", "text": "Attention mechanism for NLP."},
        ]

        # Mock: p003 bekommt hoechsten Score, dann p001, dann p002
        mock_rerank_result = MagicMock()
        mock_rerank_result.results = [
            MagicMock(index=2, relevance_score=0.95),
            MagicMock(index=0, relevance_score=0.80),
            MagicMock(index=1, relevance_score=0.40),
        ]

        with patch("academic_vault.retrieval._get_voyage_client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.rerank.return_value = mock_rerank_result
            mock_client.return_value = mock_instance

            reranked = rerank_with_voyage(
                query="transformer attention NLP",
                candidates=candidates,
                api_key="test-key",
            )

        assert reranked[0]["paper_id"] == "p003"
        assert reranked[1]["paper_id"] == "p001"
        assert reranked[2]["paper_id"] == "p002"

    def test_rerank_with_cohere_deterministic_scores(self, tmp_path):
        """Cohere-Reranker sortiert nach deterministischen Mock-Scores."""
        from academic_vault.retrieval import rerank_with_cohere

        candidates = [
            {"paper_id": "p001", "text": "Dense retrieval methods."},
            {"paper_id": "p002", "text": "Sparse BM25 retrieval."},
            {"paper_id": "p003", "text": "Hybrid dense and sparse retrieval."},
        ]

        # Mock: p003 hoechster Score
        mock_response = MagicMock()
        mock_response.results = [
            MagicMock(index=2, relevance_score=0.92),
            MagicMock(index=0, relevance_score=0.75),
            MagicMock(index=1, relevance_score=0.55),
        ]

        with patch("academic_vault.retrieval._get_cohere_client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.rerank.return_value = mock_response
            mock_client.return_value = mock_instance

            reranked = rerank_with_cohere(
                query="hybrid retrieval",
                candidates=candidates,
                api_key="test-key",
            )

        assert reranked[0]["paper_id"] == "p003"
        assert reranked[1]["paper_id"] == "p001"
        assert reranked[2]["paper_id"] == "p002"

    def test_rerank_fallback_when_no_api_key_uses_local_bge(self):
        """Ohne API-Key greift der lokale bge-reranker-v2-m3-Fallback (#376, AC2).

        Regression: vorher fiel `apply_reranker` ohne Key komplett auf die
        unveraenderte RRF-Reihenfolge zurueck (kostenfreies Reranking war nie
        wirksam). Gemockt wird nur das Backend (`_get_local_reranker`), damit
        der Test ohne Modell-Download deterministisch bleibt.
        """
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "text": "Unrelated snippet.", "rrf_score": 0.02},
            {"paper_id": "p002", "text": "Highly relevant snippet.", "rrf_score": 0.015},
        ]

        mock_reranker = MagicMock()
        # p002 bekommt den hoeheren Score -> Rangfolge kehrt sich gegenueber RRF um
        mock_reranker.predict.return_value = [0.1, 0.9]

        with patch("academic_vault.retrieval._get_local_reranker", return_value=mock_reranker):
            result = apply_reranker(
                query="test query",
                candidates=candidates,
                voyage_api_key=None,
                cohere_api_key=None,
            )

        assert result[0]["paper_id"] == "p002", "lokaler Reranker hat Rangfolge nicht angewendet"
        assert result[1]["paper_id"] == "p001"
        assert all(r["reranked"] is True for r in result)
        assert all(r["reranker"] == "local-bge" for r in result)

    def test_rerank_local_bge_not_used_when_voyage_key_set(self):
        """Der lokale Fallback darf NUR greifen, wenn beide Cloud-Keys fehlen (Plan-Risiko #3).

        Ein fehlgeschlagener Voyage-Aufruf darf NICHT still durch den lokalen
        Reranker ersetzt werden -- sonst wuerde AC3 (`reranked: false` bei
        ungueltigem VOYAGE_API_KEY) durch einen stillen Erfolg verdeckt.
        """
        from academic_vault.retrieval import apply_reranker

        candidates = [{"paper_id": "p001", "text": "x", "rrf_score": 0.02}]

        with (
            patch("academic_vault.retrieval._get_voyage_client") as mock_voyage,
            patch("academic_vault.retrieval._get_local_reranker") as mock_local,
        ):
            mock_voyage_instance = MagicMock()
            mock_voyage_instance.rerank.side_effect = RuntimeError("Voyage API down")
            mock_voyage.return_value = mock_voyage_instance

            apply_reranker(
                query="test",
                candidates=candidates,
                voyage_api_key="invalid-key",
                cohere_api_key=None,
            )

        mock_local.assert_not_called()

    def test_rerank_fallback_when_no_reranker_available_returns_unranked(self, caplog):
        """Kein API-Key UND kein lokales Backend -> unveraenderte RRF-Reihenfolge (Fixrunde #422).

        Regression: der urspruengliche `test_rerank_fallback_when_no_api_key`
        deckte genau diesen Degradationspfad ab (beide Cloud-Keys fehlen,
        Reranking bleibt wirkungslos), wurde aber ersatzlos durch
        `test_rerank_fallback_when_no_api_key_uses_local_bge` ersetzt -- das
        mockt einen FUNKTIONIERENDEN lokalen Reranker und prueft damit einen
        anderen Zweig. Der Pfad "kein Reranker verfuegbar" blieb dadurch ohne
        jede Absicherung, obwohl er strukturell moeglich bleibt (Backend-Ladefehler,
        Netzausfall beim Erstdownload etc., #714).

        Bewusst KEIN Patch von `_get_local_reranker`: die autouse-Fixture
        `block_real_local_reranker_backend` (tests/conftest.py) blockiert das
        echte Backend bereits -- genau das Verhalten, das ein Backend-Ladefehler
        in der Praxis erzeugt.
        """
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "text": "Unrelated snippet.", "rrf_score": 0.02},
            {"paper_id": "p002", "text": "Highly relevant snippet.", "rrf_score": 0.015},
        ]

        with caplog.at_level(logging.WARNING, logger="academic_vault.retrieval"):
            result = apply_reranker(
                query="test query",
                candidates=candidates,
                voyage_api_key=None,
                cohere_api_key=None,
            )

        assert [r["paper_id"] for r in result] == ["p001", "p002"], (
            "RRF-Reihenfolge muss unveraendert bleiben, wenn kein Reranker verfuegbar ist"
        )
        assert all(r["reranked"] is False for r in result), (
            "reranked muss False sein, wenn weder Cloud- noch lokaler Reranker verfuegbar sind"
        )
        assert all(r["reranker"] == "none" for r in result)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("lokaler reranker" in r.message.lower() for r in warnings), (
            f"Kein sichtbarer Log-Hinweis fuer den blockierten lokalen Reranker: "
            f"{[r.message for r in warnings]}"
        )

    def test_rerank_voyage_preferred_over_cohere(self):
        """Voyage wird bevorzugt wenn beide API-Keys verfuegbar sind."""
        from academic_vault.retrieval import apply_reranker

        candidates = [{"paper_id": "p001", "rrf_score": 0.02}]

        mock_rerank_result = MagicMock()
        mock_rerank_result.results = [MagicMock(index=0, relevance_score=0.9)]

        with (
            patch("academic_vault.retrieval._get_voyage_client") as mock_voyage,
            patch("academic_vault.retrieval._get_cohere_client") as mock_cohere,
        ):
            mock_voyage_instance = MagicMock()
            mock_voyage_instance.rerank.return_value = mock_rerank_result
            mock_voyage.return_value = mock_voyage_instance

            apply_reranker(
                query="test",
                candidates=candidates,
                voyage_api_key="voyage-key",
                cohere_api_key="cohere-key",
            )

            # Voyage wurde aufgerufen, Cohere nicht
            mock_voyage_instance.rerank.assert_called_once()
            # Cohere-Client wurde nicht verwendet
            mock_cohere_instance = mock_cohere.return_value
            mock_cohere_instance.rerank.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Fallback-Struktur-Konsistenz (#233)
# ---------------------------------------------------------------------------


class TestRerankerFallbackStructure:
    """Regressionstests fuer #233: Fallback liefert enriched-Struktur (inkl. text)."""

    def test_fallback_no_api_key_returns_text_field(self):
        """Ohne Reranker-Key muss jeder Kandidat ein text-Feld haben (#233).

        Seit #376 greift ohne Cloud-Key der lokale bge-reranker-v2-m3-Fallback
        -- gemockt, damit der Test ohne Modell-Download deterministisch bleibt.
        """
        from academic_vault.retrieval import apply_reranker

        # Kandidaten OHNE text-Feld (wie aus RRF-Fusion)
        candidates = [
            {"paper_id": "p001", "snippet": "Transformer networks.", "rrf_score": 0.02},
            {"paper_id": "p002", "snippet": "Convolutional networks.", "rrf_score": 0.015},
        ]

        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.5, 0.5]

        with patch("academic_vault.retrieval._get_local_reranker", return_value=mock_reranker):
            result = apply_reranker(
                query="test query",
                candidates=candidates,
                voyage_api_key=None,
                cohere_api_key=None,
            )

        # Fallback-Pfad muss enriched-Struktur liefern: text-Feld vorhanden
        by_id = {e["paper_id"]: e for e in result}
        for entry in result:
            assert "text" in entry, "Fallback-Kandidat ohne text-Feld (#233)"
        assert by_id["p001"]["text"] == "Transformer networks."
        assert by_id["p002"]["text"] == "Convolutional networks."

    def test_fallback_on_voyage_exception_returns_text_field(self):
        """Wenn Voyage eine Exception wirft, muss der Fallback enriched liefern (#233)."""
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "snippet": "Dense retrieval.", "rrf_score": 0.02},
        ]

        with patch("academic_vault.retrieval._get_voyage_client") as mock_voyage:
            mock_instance = MagicMock()
            mock_instance.rerank.side_effect = RuntimeError("Voyage API down")
            mock_voyage.return_value = mock_instance

            result = apply_reranker(
                query="test",
                candidates=candidates,
                voyage_api_key="voyage-key",
                cohere_api_key=None,
            )

        assert "text" in result[0], "Exception-Fallback ohne text-Feld (#233)"
        assert result[0]["text"] == "Dense retrieval."

    def test_fallback_structure_matches_reranker_path(self):
        """Fallback-Pfad (lokaler Reranker) liefert dieselben Keys wie der Voyage-Pfad (#233)."""
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "snippet": "A", "rrf_score": 0.02},
            {"paper_id": "p002", "snippet": "B", "rrf_score": 0.01},
        ]

        # Reranker-Pfad (Voyage) — fuegt text + rerank_score hinzu
        mock_result = MagicMock()
        mock_result.results = [
            MagicMock(index=0, relevance_score=0.9),
            MagicMock(index=1, relevance_score=0.5),
        ]
        with patch("academic_vault.retrieval._get_voyage_client") as mock_voyage:
            mock_instance = MagicMock()
            mock_instance.rerank.return_value = mock_result
            mock_voyage.return_value = mock_instance
            reranked = apply_reranker(
                query="q",
                candidates=candidates,
                voyage_api_key="voyage-key",
                cohere_api_key=None,
            )

        # Fallback-Pfad — kein Key, lokaler Reranker gemockt (#376)
        mock_local = MagicMock()
        mock_local.predict.return_value = [0.5, 0.5]
        with patch("academic_vault.retrieval._get_local_reranker", return_value=mock_local):
            fallback = apply_reranker(
                query="q",
                candidates=candidates,
                voyage_api_key=None,
                cohere_api_key=None,
            )

        # Beide Pfade muessen das text-Feld enthalten
        reranked_text_keys = {"text" in e for e in reranked}
        fallback_text_keys = {"text" in e for e in fallback}
        assert reranked_text_keys == {True}
        assert fallback_text_keys == {True}


# ---------------------------------------------------------------------------
# Tests: Recall@10 Eval-Set
# ---------------------------------------------------------------------------


class TestRecallEval:
    """Recall@10-Berechnung ueber Eval-Set."""

    def _compute_recall_at_k(
        self, retrieved_ids: list[str], relevant_ids: list[str], k: int
    ) -> float:
        """Hilfs-Berechnung Recall@K."""
        top_k = set(retrieved_ids[:k])
        relevant = set(relevant_ids)
        if not relevant:
            return 1.0
        return len(top_k & relevant) / len(relevant)

    def test_recall_at_10_function_exists(self):
        """compute_recall_at_k Funktion existiert in retrieval.py."""
        from academic_vault.retrieval import compute_recall_at_k

        assert callable(compute_recall_at_k)

    def test_recall_at_k_perfect_retrieval(self):
        """Recall@10 = 1.0 wenn alle relevanten Papers in Top-10."""
        from academic_vault.retrieval import compute_recall_at_k

        retrieved = ["p001", "p002", "p003", "p004", "p005", "p006", "p007", "p008", "p009", "p010"]
        relevant = ["p001", "p003", "p005"]
        assert compute_recall_at_k(retrieved, relevant, k=10) == 1.0

    def test_recall_at_k_zero_retrieval(self):
        """Recall@10 = 0.0 wenn kein relevantes Paper in Top-10."""
        from academic_vault.retrieval import compute_recall_at_k

        retrieved = ["p011", "p012", "p013", "p014", "p015", "p016", "p017", "p018", "p019", "p020"]
        relevant = ["p001", "p003", "p005"]
        assert compute_recall_at_k(retrieved, relevant, k=10) == 0.0

    def test_recall_at_k_partial_retrieval(self):
        """Recall@10 = 0.5 wenn die Haelfte der relevanten Papers in Top-10."""
        from academic_vault.retrieval import compute_recall_at_k

        retrieved = ["p001", "p002", "p003", "p004", "p005", "p006", "p007", "p008", "p009", "p010"]
        relevant = ["p001", "p011"]  # p001 in Top-10, p011 nicht
        assert compute_recall_at_k(retrieved, relevant, k=10) == 0.5

    def test_recall_at_k_cutoff_at_k(self):
        """Recall@10 beachtet k-Cutoff: Treffer ab Position k+1 zaehlen nicht."""
        from academic_vault.retrieval import compute_recall_at_k

        # p003 ist an Position 11 (index 10) — zaehlt nicht bei k=10
        retrieved = [
            "p001",
            "p002",
            "p004",
            "p005",
            "p006",
            "p007",
            "p008",
            "p009",
            "p010",
            "p011",
            "p003",
        ]
        relevant = ["p003"]
        assert compute_recall_at_k(retrieved, relevant, k=10) == 0.0

    def test_eval_set_fts_recall_at_10_on_mock_db(self, tmp_path):
        """FTS5-Suche erreicht Recall@10 > 0 auf dem Eval-Set (Sanity-Check)."""
        eval_path = FIXTURES / "retrieval_eval_set.json"
        data = json.loads(eval_path.read_text(encoding="utf-8"))

        db_path = _make_db(tmp_path)

        # Alle 200 Papers in DB laden
        from academic_vault.server import add_paper

        for p in data["papers"]:
            csl = {
                "type": "article-journal",
                "title": p["title"],
                "abstract": p["abstract"],
            }
            add_paper(db_path, p["paper_id"], json.dumps(csl))

        from academic_vault.retrieval import compute_recall_at_k
        from academic_vault.server import search_papers

        recalls = []
        for q in data["queries"]:
            results = search_papers(db_path, q["query"], k=10)
            retrieved_ids = [r["paper_id"] for r in results]
            recall = compute_recall_at_k(retrieved_ids, q["relevant_paper_ids"], k=10)
            recalls.append(recall)

        mean_recall = sum(recalls) / len(recalls) if recalls else 0.0
        # Sanity: FTS5 muss minimal > 0 sein (mindestens einige richtige Treffer)
        assert mean_recall > 0.0, "FTS5 Recall@10 ist 0.0 — Retrieval funktioniert nicht"

    def test_rrf_improves_over_vanilla_fts_on_mock_data(self, tmp_path):
        """RRF-Retrieval schlaegt reines FTS5 auf vereinfachtem Eval-Subset."""
        from academic_vault.retrieval import compute_recall_at_k, reciprocal_rank_fusion
        from academic_vault.server import search_papers

        # Vereinfachtes Setup: 3 Papers, Query findet p001 via FTS5 und vec0
        db_path = _make_db(tmp_path)
        _add_paper(
            db_path, "p001", "Hybrid Retrieval BM25 Dense", "Combining sparse and dense methods."
        )
        _add_paper(db_path, "p002", "Unrelated Topic Cats Dogs", "Pets and animals in households.")
        _add_paper(
            db_path, "p003", "Another Unrelated Topic Music", "Classical music and composers."
        )

        fts_results = search_papers(db_path, "hybrid retrieval dense sparse", k=10)

        # Simuliere vec0-Ergebnis (gleiche Reihenfolge wie FTS5 fuer diesen Test)
        vec_results = [{"paper_id": "p001", "score": 0.9}]

        fused = reciprocal_rank_fusion(vec_results, fts_results, k=60, top_n=10)
        fused_ids = [r["paper_id"] for r in fused]

        relevant = ["p001"]
        recall_rrf = compute_recall_at_k(fused_ids, relevant, k=10)
        recall_fts = compute_recall_at_k([r["paper_id"] for r in fts_results], relevant, k=10)

        # RRF soll mindestens so gut wie FTS5 sein
        assert recall_rrf >= recall_fts
        assert recall_rrf > 0.0, "RRF findet p001 nicht"


# ---------------------------------------------------------------------------
# Tests: Lokaler Reranker-Fallback bge-reranker-v2-m3 (#376)
# ---------------------------------------------------------------------------


class TestLocalBgeReranker:
    """Unit-Tests fuer rerank_with_local_bge (gemocktes Backend, kein Modell-Download)."""

    def test_rerank_with_local_bge_deterministic_scores(self):
        """rerank_with_local_bge sortiert nach den (gemockten) Backend-Scores."""
        from academic_vault.retrieval import rerank_with_local_bge

        candidates = [
            {"paper_id": "p001", "text": "Transformer neural networks."},
            {"paper_id": "p002", "text": "Convolutional networks for images."},
            {"paper_id": "p003", "text": "Attention mechanism for NLP."},
        ]

        mock_reranker = MagicMock()
        # p003 bekommt hoechsten Score, dann p001, dann p002
        mock_reranker.predict.return_value = [0.4, 0.1, 0.9]

        with patch("academic_vault.retrieval._get_local_reranker", return_value=mock_reranker):
            reranked = rerank_with_local_bge(
                query="transformer attention NLP",
                candidates=candidates,
            )

        assert reranked[0]["paper_id"] == "p003"
        assert reranked[1]["paper_id"] == "p001"
        assert reranked[2]["paper_id"] == "p002"
        # Backend bekommt Query/Text als Paar-Liste
        call_args = mock_reranker.predict.call_args
        pairs = call_args[0][0]
        assert pairs == [
            ["transformer attention NLP", "Transformer neural networks."],
            ["transformer attention NLP", "Convolutional networks for images."],
            ["transformer attention NLP", "Attention mechanism for NLP."],
        ]

    def test_rerank_with_local_bge_single_candidate_array_score(self):
        """Backend gibt bei genau einem Kandidaten ein Array mit einem Element zurueck (#714).

        Seit #714 (CrossEncoder.predict) gibt es -- anders als beim vorherigen
        FlagReranker.compute_score() -- keinen Skalar-Sonderfall mehr: `predict`
        liefert immer ein Array, auch bei genau einem Paar.
        """
        from academic_vault.retrieval import rerank_with_local_bge

        candidates = [{"paper_id": "p001", "text": "Solo candidate."}]

        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.42]

        with patch("academic_vault.retrieval._get_local_reranker", return_value=mock_reranker):
            reranked = rerank_with_local_bge(query="q", candidates=candidates)

        assert reranked[0]["paper_id"] == "p001"
        assert reranked[0]["rerank_score"] == 0.42

    def test_rerank_with_local_bge_raises_when_backend_unavailable(self):
        """rerank_with_local_bge wirft, wenn das Backend nicht ladbar ist (analog Voyage/Cohere)."""
        from academic_vault.retrieval import rerank_with_local_bge

        with patch("academic_vault.retrieval._get_local_reranker", return_value=None):
            with pytest.raises(RuntimeError):
                rerank_with_local_bge(query="q", candidates=[{"paper_id": "p001", "text": "x"}])


# ---------------------------------------------------------------------------
# Tests: Sichtbares Fehlverhalten statt stillem except (#376, AC3)
# ---------------------------------------------------------------------------


class TestRerankerVisibleFailure:
    """AC3: Ungueltiger VOYAGE_API_KEY -> reranked: false + sichtbarer Log, kein stiller Fehler."""

    def test_invalid_voyage_key_returns_reranked_false_with_warning_log(self, caplog):
        """Voyage-Exception fuehrt zu reranked=False + WARNING-Log (kein `except Exception: pass`)."""
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "text": "Some document text."},
        ]

        with patch("academic_vault.retrieval._get_voyage_client") as mock_voyage:
            mock_instance = MagicMock()
            mock_instance.rerank.side_effect = RuntimeError("401 Unauthorized: invalid API key")
            mock_voyage.return_value = mock_instance

            with caplog.at_level(logging.WARNING, logger="academic_vault.retrieval"):
                result = apply_reranker(
                    query="test",
                    candidates=candidates,
                    voyage_api_key="invalid-voyage-key",
                    cohere_api_key=None,
                )

        assert all(entry["reranked"] is False for entry in result), (
            "reranked muss False sein, wenn Voyage fehlschlaegt und kein Fallback greift (AC3)"
        )
        assert all(entry["reranker"] == "none" for entry in result)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("voyage" in r.message.lower() for r in warnings), (
            f"Kein sichtbarer Voyage-Log-Hinweis gefunden (AC3): {[r.message for r in warnings]}"
        )

    def test_invalid_cohere_key_returns_reranked_false_with_warning_log(self, caplog):
        """Gleiche Garantie fuer Cohere: kein stiller except, sondern reranked=False + Log."""
        from academic_vault.retrieval import apply_reranker

        candidates = [{"paper_id": "p001", "text": "Some document text."}]

        with patch("academic_vault.retrieval._get_cohere_client") as mock_cohere:
            mock_instance = MagicMock()
            mock_instance.rerank.side_effect = RuntimeError("401 Unauthorized: invalid API key")
            mock_cohere.return_value = mock_instance

            with caplog.at_level(logging.WARNING, logger="academic_vault.retrieval"):
                result = apply_reranker(
                    query="test",
                    candidates=candidates,
                    voyage_api_key=None,
                    cohere_api_key="invalid-cohere-key",
                )

        assert all(entry["reranked"] is False for entry in result)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("cohere" in r.message.lower() for r in warnings), (
            f"Kein sichtbarer Cohere-Log-Hinweis gefunden: {[r.message for r in warnings]}"
        )


# ---------------------------------------------------------------------------
# Live-Tests gegen die echten Voyage/Cohere-APIs (#376, AC3-Beweis,
# Fixrunde PR #422)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("VAULT_RERANK_CLOUD_LIVE_TEST") != "1",
    reason="Live-API-Test nur mit VAULT_RERANK_CLOUD_LIVE_TEST=1 (echter "
    "Netzwerk-Call gegen Voyage/Cohere mit absichtlich ungueltigem Key).",
)
class TestRerankerVisibleFailureLive:
    """AC3 woertlich: ein *Live*-Test mit ungueltigem Key statt nur eines Mocks.

    `TestRerankerVisibleFailure` oben mockt `_get_voyage_client`/
    `_get_cohere_client` mit einem generischen `RuntimeError` als
    `side_effect` -- das landet immer im catch-all `except Exception` in
    `apply_reranker`, nie in den eigens eingefuehrten benannten Handlern
    `except VoyageError`/`except CohereApiError`. Faellt bei einer
    kuenftigen SDK-Version der Importpfad `voyageai.error.VoyageError` bzw.
    `cohere.core.api_error.ApiError` still auf den Platzhalter zurueck
    (retrieval.py, `try: from voyageai.error import VoyageError`), schluege
    dort KEIN Test an.

    Diese Klasse macht echte Netzwerk-Aufrufe gegen die realen SDKs mit
    absichtlich ungueltigem Key und beweist direkt (per `isinstance` gegen
    die tatsaechlich geworfene Exception), dass die reale Fehlerklasse der
    API eine Unterklasse der importierten Basisklasse ist -- der benannte
    Handler wird also wirklich getroffen, nicht nur der Catch-all.
    """

    def test_voyage_invalid_key_live_raises_named_voyage_error(self):
        """Echter Voyage-Call mit ungueltigem Key wirft eine VoyageError-Instanz."""
        pytest.importorskip("voyageai")
        import voyageai.error
        from academic_vault.retrieval import VoyageError, rerank_with_voyage

        with pytest.raises(VoyageError) as exc_info:
            rerank_with_voyage(
                query="test query",
                candidates=[{"paper_id": "p001", "text": "Some document text."}],
                api_key="invalid-voyage-key-for-ac3-live-test",
            )

        # Beweis, dass es sich um die echte SDK-Klasse handelt, nicht um den
        # nie ausgeloesten Platzhalter aus retrieval.py.
        assert type(exc_info.value).__module__.startswith("voyageai")
        assert isinstance(exc_info.value, voyageai.error.VoyageError)

    def test_voyage_invalid_key_live_apply_reranker_returns_reranked_false(self, caplog):
        """apply_reranker() mit echtem ungueltigem Voyage-Key: reranked=False + WARNING (AC3)."""
        pytest.importorskip("voyageai")
        from academic_vault.retrieval import apply_reranker

        candidates = [{"paper_id": "p001", "text": "Some document text about machine learning."}]

        with caplog.at_level(logging.WARNING, logger="academic_vault.retrieval"):
            result = apply_reranker(
                query="test",
                candidates=candidates,
                voyage_api_key="invalid-voyage-key-for-ac3-live-test",
                cohere_api_key=None,
            )

        assert all(entry["reranked"] is False for entry in result)
        assert all(entry["reranker"] == "none" for entry in result)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("voyage" in r.message.lower() for r in warnings), (
            f"Kein sichtbarer Voyage-Log-Hinweis (Live) gefunden: {[r.message for r in warnings]}"
        )

    def test_cohere_invalid_key_live_raises_named_cohere_error(self):
        """Echter Cohere-Call mit ungueltigem Key wirft eine CohereApiError-Instanz."""
        pytest.importorskip("cohere")
        import cohere.core.api_error
        from academic_vault.retrieval import CohereApiError, rerank_with_cohere

        with pytest.raises(CohereApiError) as exc_info:
            rerank_with_cohere(
                query="test query",
                candidates=[{"paper_id": "p001", "text": "Some document text."}],
                api_key="invalid-cohere-key-for-ac3-live-test",
            )

        assert type(exc_info.value).__module__.startswith("cohere")
        assert isinstance(exc_info.value, cohere.core.api_error.ApiError)

    def test_cohere_invalid_key_live_apply_reranker_returns_reranked_false(self, caplog):
        """apply_reranker() mit echtem ungueltigem Cohere-Key: reranked=False + WARNING (AC3)."""
        pytest.importorskip("cohere")
        from academic_vault.retrieval import apply_reranker

        candidates = [{"paper_id": "p001", "text": "Some document text about machine learning."}]

        with caplog.at_level(logging.WARNING, logger="academic_vault.retrieval"):
            result = apply_reranker(
                query="test",
                candidates=candidates,
                voyage_api_key=None,
                cohere_api_key="invalid-cohere-key-for-ac3-live-test",
            )

        assert all(entry["reranked"] is False for entry in result)
        assert all(entry["reranker"] == "none" for entry in result)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("cohere" in r.message.lower() for r in warnings), (
            f"Kein sichtbarer Cohere-Log-Hinweis (Live) gefunden: {[r.message for r in warnings]}"
        )


# ---------------------------------------------------------------------------
# Live-Test gegen das echte bge-reranker-v2-m3-Modell (#376, AC2-Beweis)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("VAULT_RERANK_LOCAL_LIVE_TEST") != "1",
    reason="Live-Modelltest nur mit VAULT_RERANK_LOCAL_LIVE_TEST=1 (laedt bge-reranker-v2-m3)",
)
def test_local_bge_reranker_real_model_reorders_candidates():
    """Echtes bge-reranker-v2-m3-Modell veraendert die unrerankte RRF-Reihenfolge (AC2).

    Setup: ein eindeutig relevanter Kandidat steht in der RRF-Eingabe absichtlich
    HINTER einem irrelevanten Kandidaten. Der lokale Reranker muss ihn nach vorne
    holen -- der Beweis, dass der kostenfreie Fallback tatsaechlich wirkt (nicht
    nur strukturell durchgereicht wird).
    """
    from academic_vault.retrieval import rerank_with_local_bge, reset_local_reranker_cache

    reset_local_reranker_cache()
    query = "What are the health benefits of regular exercise?"
    candidates = [
        # Absichtlich VORNE (simuliert schlechte RRF-Platzierung), aber irrelevant.
        {
            "paper_id": "p_irrelevant",
            "text": "The history of Renaissance oil painting techniques in 15th century Florence.",
        },
        # Absichtlich HINTEN, aber hochrelevant.
        {
            "paper_id": "p_relevant",
            "text": (
                "Regular physical exercise improves cardiovascular health, strengthens muscles, "
                "and reduces the risk of chronic diseases such as diabetes and hypertension."
            ),
        },
    ]
    rrf_order = [c["paper_id"] for c in candidates]

    reranked = rerank_with_local_bge(query=query, candidates=candidates)
    reranked_order = [c["paper_id"] for c in reranked]

    assert reranked_order != rrf_order, "lokaler Reranker hat die RRF-Reihenfolge nicht veraendert"
    assert reranked_order[0] == "p_relevant", "relevanter Kandidat wurde nicht nach vorne gerankt"
