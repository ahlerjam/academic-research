"""Rangbewusste Retrieval-Metriken: nDCG@k, Reciprocal Rank, MRR (Issue #708).

Jeder Fall in diesem Modul ist von Hand nachgerechnet; die Rechnung steht im
jeweiligen Docstring. Das ist Absicht: eine Metrik, die nur gegen ihre eigene
Implementierung geprueft wird, belegt nichts.
"""

import math

import pytest
from academic_vault.retrieval import (
    compute_ndcg_at_k,
    compute_recall_at_k,
    compute_reciprocal_rank_at_k,
    mean_reciprocal_rank,
)


class TestNdcgAtK:
    """nDCG@k mit binaerer Relevanz: DCG = sum(rel_i / log2(i+1)), i ab 1."""

    def test_perfect_ranking_is_one(self):
        """Beide Relevanten auf Rang 1 und 2 -> DCG == IDCG -> 1.0."""
        retrieved = ["c1", "c2", "c3", "c4"]
        assert compute_ndcg_at_k(retrieved, ["c1", "c2"], k=10) == pytest.approx(1.0)

    def test_single_hit_at_rank_three(self):
        """Ein Treffer auf Rang 3: DCG = 1/log2(4) = 0.5, IDCG = 1 -> 0.5."""
        retrieved = ["x1", "x2", "c1", "x3"]
        assert compute_ndcg_at_k(retrieved, ["c1"], k=10) == pytest.approx(0.5)

    def test_two_hits_at_rank_one_and_four(self):
        """Treffer auf Rang 1 und 4.

        DCG  = 1/log2(2) + 1/log2(5) = 1 + 0.4306766 = 1.4306766
        IDCG = 1/log2(2) + 1/log2(3) = 1 + 0.6309298 = 1.6309298
        nDCG = 1.4306766 / 1.6309298 = 0.8772153
        """
        retrieved = ["c1", "x1", "x2", "c2", "x3"]
        assert compute_ndcg_at_k(retrieved, ["c1", "c2"], k=10) == pytest.approx(
            0.8772153, abs=1e-6
        )

    def test_idcg_is_capped_at_k(self):
        """Drei Relevante, k=2, Treffer auf Rang 1+2.

        IDCG darf nur die ersten k Idealpositionen zaehlen (1 + 1/log2(3)),
        sonst kaeme selbst ein perfektes Top-2 nie auf 1.0.
        """
        retrieved = ["c1", "c2", "c3"]
        assert compute_ndcg_at_k(retrieved, ["c1", "c2", "c3"], k=2) == pytest.approx(1.0)

    def test_no_hit_in_top_k_is_zero(self):
        retrieved = ["x1", "x2", "x3"]
        assert compute_ndcg_at_k(retrieved, ["c1"], k=3) == 0.0

    def test_hit_beyond_k_does_not_count(self):
        """Treffer auf Rang 3, aber k=2 -> 0.0."""
        retrieved = ["x1", "x2", "c1"]
        assert compute_ndcg_at_k(retrieved, ["c1"], k=2) == 0.0

    def test_empty_relevant_ids_is_one(self):
        """Gleiche Konvention wie compute_recall_at_k: nichts zu finden = erfuellt."""
        assert compute_ndcg_at_k(["x1"], [], k=10) == 1.0
        assert compute_recall_at_k(["x1"], [], k=10) == 1.0

    def test_duplicate_retrieved_ids_count_once(self):
        """Dubletten im Ranking zaehlen nur an ihrer ERSTEN Position.

        ["c1", "c1", "c2"] wird zu ["c1", "c2"] entdubliziert: DCG = 1 + 1/log2(3),
        IDCG identisch -> 1.0. Wuerde die zweite Nennung mitzaehlen, ergaebe sich
        ein hoeherer DCG als der Idealwert (nDCG > 1) -- ein Retriever koennte
        seine Metrik durch Wiederholen desselben Treffers schoenen.
        """
        assert compute_ndcg_at_k(["c1", "c1", "c2"], ["c1", "c2"], k=10) == pytest.approx(1.0)

    def test_non_positive_k_is_zero(self):
        assert compute_ndcg_at_k(["c1"], ["c1"], k=0) == 0.0


class TestReciprocalRankAtK:
    """RR@k = 1 / Rang des ERSTEN Treffers, 0.0 wenn keiner in den Top-k liegt."""

    def test_hit_at_rank_one(self):
        assert compute_reciprocal_rank_at_k(["c1", "x1"], ["c1"], k=10) == pytest.approx(1.0)

    def test_hit_at_rank_four(self):
        """Erster Treffer auf Rang 4 -> 1/4 = 0.25."""
        retrieved = ["x1", "x2", "x3", "c1", "c2"]
        assert compute_reciprocal_rank_at_k(retrieved, ["c1", "c2"], k=10) == pytest.approx(0.25)

    def test_no_hit_in_top_k(self):
        """Treffer erst auf Rang 4, aber k=3 -> 0.0."""
        retrieved = ["x1", "x2", "x3", "c1"]
        assert compute_reciprocal_rank_at_k(retrieved, ["c1"], k=3) == 0.0

    def test_only_first_hit_counts(self):
        """Rang 2 und 3 relevant -> 1/2, nicht 1/2 + 1/3."""
        retrieved = ["x1", "c1", "c2"]
        assert compute_reciprocal_rank_at_k(retrieved, ["c1", "c2"], k=10) == pytest.approx(0.5)

    def test_empty_relevant_ids_is_one(self):
        assert compute_reciprocal_rank_at_k(["x1"], [], k=10) == 1.0

    def test_duplicate_retrieved_ids_count_once(self):
        """["x1", "x1", "c1"] entdubliziert zu ["x1", "c1"] -> Rang 2 -> 0.5."""
        assert compute_reciprocal_rank_at_k(["x1", "x1", "c1"], ["c1"], k=10) == pytest.approx(0.5)


class TestMeanReciprocalRank:
    def test_mean_over_three_queries(self):
        """Raenge 1, 4 und "nicht gefunden": (1.0 + 0.25 + 0.0) / 3 = 0.4166667."""
        rankings = [
            (["c1", "x1", "x2", "x3"], ["c1"]),
            (["x1", "x2", "x3", "c2"], ["c2"]),
            (["x1", "x2", "x3", "x4"], ["c3"]),
        ]
        assert mean_reciprocal_rank(rankings, k=10) == pytest.approx(0.4166667, abs=1e-6)

    def test_empty_input_is_zero(self):
        assert mean_reciprocal_rank([], k=10) == 0.0

    def test_respects_cutoff(self):
        """k=3 blendet den Treffer auf Rang 4 aus: (1.0 + 0.0) / 2 = 0.5."""
        rankings = [
            (["c1", "x1", "x2", "x3"], ["c1"]),
            (["x1", "x2", "x3", "c2"], ["c2"]),
        ]
        assert mean_reciprocal_rank(rankings, k=3) == pytest.approx(0.5)


class TestNdcgAgainstTextbookFormula:
    """Gegenprobe: unabhaengig ausformulierte Referenzrechnung, kein Shared Code."""

    @staticmethod
    def _reference_ndcg(retrieved, relevant, k):
        relevant_set = set(relevant)
        gains = [1.0 if doc in relevant_set else 0.0 for doc in retrieved[:k]]
        dcg = sum(g / math.log2(rank + 1) for rank, g in enumerate(gains, start=1))
        ideal = [1.0] * min(len(relevant_set), k)
        idcg = sum(g / math.log2(rank + 1) for rank, g in enumerate(ideal, start=1))
        return dcg / idcg if idcg else 0.0

    @pytest.mark.parametrize(
        "retrieved,relevant,k",
        [
            (["a", "b", "c", "d", "e"], ["c"], 5),
            (["a", "b", "c", "d", "e"], ["a", "e"], 5),
            (["a", "b", "c", "d", "e"], ["b", "c", "d"], 3),
            (["a", "b", "c"], ["z"], 10),
        ],
    )
    def test_matches_reference(self, retrieved, relevant, k):
        assert compute_ndcg_at_k(retrieved, relevant, k=k) == pytest.approx(
            self._reference_ndcg(retrieved, relevant, k)
        )
