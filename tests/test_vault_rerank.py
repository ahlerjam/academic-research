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
# Tests: Reranker-Integration (lokaler bge-reranker-v2-m3, #715)
# ---------------------------------------------------------------------------


class TestRerankerIntegration:
    """Tests fuer den lokalen Reranker in apply_reranker (#715, vormals Cloud-Kette #376)."""

    def test_rerank_uses_local_bge(self):
        """apply_reranker() nutzt den lokalen bge-reranker-v2-m3-Fallback (#376, AC2; #715).

        Gemockt wird nur das Backend (`_get_local_reranker`), damit der Test
        ohne Modell-Download deterministisch bleibt.
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
            result = apply_reranker(query="test query", candidates=candidates)

        assert result[0]["paper_id"] == "p002", "lokaler Reranker hat Rangfolge nicht angewendet"
        assert result[1]["paper_id"] == "p001"
        assert all(r["reranked"] is True for r in result)
        assert all(r["reranker"] == "local-bge" for r in result)

    def test_rerank_fallback_when_no_reranker_available_returns_unranked(self, caplog):
        """Kein lokales Backend verfuegbar -> unveraenderte RRF-Reihenfolge (Fixrunde #422; #715).

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
            result = apply_reranker(query="test query", candidates=candidates)

        assert [r["paper_id"] for r in result] == ["p001", "p002"], (
            "RRF-Reihenfolge muss unveraendert bleiben, wenn kein Reranker verfuegbar ist"
        )
        assert all(r["reranked"] is False for r in result), (
            "reranked muss False sein, wenn kein lokaler Reranker verfuegbar ist"
        )
        assert all(r["reranker"] == "none" for r in result)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("lokaler reranker" in r.message.lower() for r in warnings), (
            f"Kein sichtbarer Log-Hinweis fuer den blockierten lokalen Reranker: "
            f"{[r.message for r in warnings]}"
        )

    def test_local_rerank_result_is_independent_of_leftover_env_keys(self, monkeypatch):
        """Leftover VOYAGE_API_KEY/COHERE_API_KEY (z.B. aus einer alten .env)
        beeinflussen das lokale Reranking-Ergebnis nicht.

        Beweist NICHT AC5 (#715, 'apply_reranker() liest diese Keys nie') --
        das ruft apply_reranker() ohne die Kwargs auf und waere auch auf dem
        alten Code (vor #715) gruen. Der eigentliche AC5-Beweis ist
        test_search_papers_never_reads_voyage_cohere_env_keys weiter unten.
        """
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "text": "Unrelated snippet.", "rrf_score": 0.02},
            {"paper_id": "p002", "text": "Highly relevant snippet.", "rrf_score": 0.015},
        ]

        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.1, 0.9]

        with patch("academic_vault.retrieval._get_local_reranker", return_value=mock_reranker):
            monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
            monkeypatch.delenv("COHERE_API_KEY", raising=False)
            result_without_keys = apply_reranker(query="test query", candidates=candidates)

            monkeypatch.setenv("VOYAGE_API_KEY", "leftover-voyage-key")
            monkeypatch.setenv("COHERE_API_KEY", "leftover-cohere-key")
            result_with_keys = apply_reranker(query="test query", candidates=candidates)

        assert [r["paper_id"] for r in result_with_keys] == [
            r["paper_id"] for r in result_without_keys
        ]
        assert all(r["reranked"] is True for r in result_with_keys)
        assert all(r["reranker"] == "local-bge" for r in result_with_keys)

    def test_apply_reranker_signature_has_no_cloud_key_params(self):
        """AC5 (#715): apply_reranker() akzeptiert keine Voyage-/Cohere-Keys mehr.

        Der obige Test ruft apply_reranker() ohne voyage_api_key/cohere_api_key
        auf und beweist damit nichts: er laeuft auch auf dem alten Code (vor
        #715) gruen, weil dort die Cloud-Kwargs auf None defaulten, sobald sie
        nicht explizit uebergeben werden -- apply_reranker() selbst hat
        os.environ nie gelesen, das tat nur server.py als Kwarg-Uebergabe.
        Diese strukturelle Pruefung verhindert eine Wiedereinfuehrung der
        Kwargs (und damit der Cloud-Kette) direkt an der Signatur.
        """
        import inspect

        from academic_vault.retrieval import apply_reranker

        params = set(inspect.signature(apply_reranker).parameters)
        assert params == {"query", "candidates"}, (
            f"apply_reranker() hat unerwartete Parameter {params - {'query', 'candidates'}} "
            "-- Cloud-Reranker-Kwargs duerfen nicht wieder auftauchen (#715)."
        )

    def test_search_papers_never_reads_voyage_cohere_env_keys(self, tmp_path, monkeypatch):
        """AC5 (#715): der eigentliche Aufrufpfad liest die Cloud-Keys nicht mehr.

        Vor #715 las NICHT apply_reranker(), sondern server.search_papers()
        VOYAGE_API_KEY/COHERE_API_KEY aus os.environ und reichte sie als Kwarg
        durch. Dieser Test faengt os.environ.get am echten Einstiegspunkt ab
        und beweist, dass diese beiden Keys beim Reranking-Aufruf nie
        abgefragt werden -- der Regressionsfall, den ein reiner
        Ergebnisvergleich (siehe Test oben) nicht abdeckt.
        """
        from academic_vault import server

        db_path = _make_db(tmp_path)
        _add_paper(
            db_path,
            "p001",
            "Hybrid Retrieval BM25 Dense",
            "Combining sparse and dense methods.",
        )

        monkeypatch.setenv("VOYAGE_API_KEY", "leftover-voyage-key")
        monkeypatch.setenv("COHERE_API_KEY", "leftover-cohere-key")

        queried_keys: list[str] = []
        real_environ_get = os.environ.get

        def spy_get(name, *args, **kwargs):
            if name in ("VOYAGE_API_KEY", "COHERE_API_KEY"):
                queried_keys.append(name)
            return real_environ_get(name, *args, **kwargs)

        monkeypatch.setattr(os.environ, "get", spy_get)

        results = server.search_papers(db_path, "hybrid retrieval dense sparse", k=10, rerank=True)

        assert queried_keys == [], (
            f"os.environ.get wurde fuer {queried_keys} aufgerufen -- "
            "search_papers() darf Cloud-Reranker-Keys nicht mehr lesen (#715)."
        )
        assert results, "search_papers() sollte Treffer liefern"
        assert all(r.get("reranker") in ("local-bge", "none") for r in results)


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
            result = apply_reranker(query="test query", candidates=candidates)

        # Fallback-Pfad muss enriched-Struktur liefern: text-Feld vorhanden
        by_id = {e["paper_id"]: e for e in result}
        for entry in result:
            assert "text" in entry, "Fallback-Kandidat ohne text-Feld (#233)"
        assert by_id["p001"]["text"] == "Transformer networks."
        assert by_id["p002"]["text"] == "Convolutional networks."

    def test_local_bge_exception_returns_text_field(self):
        """Wenn der lokale Reranker eine Exception wirft, muss der Fallback enriched liefern (#233)."""
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "snippet": "Dense retrieval.", "rrf_score": 0.02},
        ]

        with patch("academic_vault.retrieval._get_local_reranker") as mock_local:
            mock_instance = MagicMock()
            mock_instance.predict.side_effect = RuntimeError("Backend down")
            mock_local.return_value = mock_instance

            result = apply_reranker(query="test", candidates=candidates)

        assert "text" in result[0], "Exception-Fallback ohne text-Feld (#233)"
        assert result[0]["text"] == "Dense retrieval."


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


@pytest.mark.skipif(
    os.environ.get("VAULT_RERANK_LOCAL_LIVE_TEST") != "1",
    reason="Live-Modelltest nur mit VAULT_RERANK_LOCAL_LIVE_TEST=1 (laedt bge-reranker-v2-m3)",
)
def test_local_bge_reranker_crossencoder_matches_flagembedding_baseline_order():
    """AC2: CrossEncoder-Pfad (#714) reproduziert die Rangfolge des alten FlagEmbedding-Pfads.

    Der bisherige Live-Test (``test_local_bge_reranker_real_model_reorders_candidates``)
    beweist nur, dass der neue CrossEncoder-Pfad *irgendeine* sinnvolle
    Umsortierung vornimmt -- nicht, dass sie mit dem VORHERIGEN
    ``FlagEmbedding.FlagReranker``-Pfad uebereinstimmt. Das ist AC2's
    eigentliche Behauptung ("Trefferreihenfolge gegenueber dem
    FlagEmbedding-Pfad unveraendert") und wurde im PR-Review (PR #772)
    zu Recht als Luecke markiert: kein Test verglich tatsaechlich gegen eine
    FlagEmbedding-Ausgabe.

    FlagEmbedding bleibt bewusst ausserhalb der uv-verwalteten Dependencies
    (AC5, siehe ``test_issue_376_reranker_extras.py``) und ist deshalb in
    KEINER CI-Umgebung dieses Repos installierbar/installiert. Ein Live-Test,
    der FlagEmbedding zur Laufzeit importiert, waere also nie gruen -- das
    ist der Grund, warum der PR-Autor einen solchen Test im Task-Kasten der
    PR-Beschreibung explizit uebersprungen hat.

    Statt eines Live-Imports von FlagEmbedding vergleicht dieser Test die
    reale CrossEncoder-Ausgabe (dieser Prozess, echtes bge-reranker-v2-m3,
    kein Mock) gegen eine EINMALIG aufgezeichnete FlagEmbedding-Baseline fuer
    denselben Query/Kandidaten-Satz. Die Baseline wurde ausserhalb dieses
    Repos erzeugt (separates venv, damit AC5 -- kein FlagEmbedding in
    pyproject.toml/uv.lock -- unangetastet bleibt):

        python3 -m venv /tmp/flagembedding-baseline-venv
        /tmp/flagembedding-baseline-venv/bin/pip install \
            'FlagEmbedding>=1.3,<2.0' 'transformers<5.0'
        # FlagEmbedding 1.4.0, transformers 4.57.6, torch 2.13.0
        /tmp/flagembedding-baseline-venv/bin/python - <<'PY'
        from FlagEmbedding import FlagReranker
        r = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=False)
        print(r.compute_score(PAIRS, normalize=True))
        PY

    Aufgezeichnete FlagEmbedding-Scores (normalize=True, identisch zur
    Sigmoid-Aktivierung von ``CrossEncoder.predict()``) fuer PAIRS = [[QUERY,
    c["text"]] for c in CANDIDATES] unten:

        p_relevant_primary     0.9964107162736381
        p_relevant_secondary   0.17979691103617984
        p_irrelevant_weather   1.6168727883409747e-05
        p_irrelevant_art       1.6107935622014048e-05
        p_irrelevant_finance   1.606611461875519e-05

    Diese Werte liegen bei einer unabhaengigen Reproduktion mit
    ``sentence_transformers.CrossEncoder`` (derselbe Prozess/dieselbe Suite
    wie dieser Test, gemessen beim Schreiben dieses Tests) auf < 1e-4 an den
    hier assertierten Toleranzen -- die Rangfolge ist exakt identisch, die
    Scores stimmen bis auf Backend-bedingte Gleitkomma-Rundung ueberein.
    """
    from academic_vault.retrieval import rerank_with_local_bge, reset_local_reranker_cache

    reset_local_reranker_cache()

    query = "What are the health benefits of regular exercise?"
    candidates = [
        {
            "paper_id": "p_irrelevant_art",
            "text": "The history of Renaissance oil painting techniques in 15th century Florence.",
        },
        {
            "paper_id": "p_relevant_primary",
            "text": (
                "Regular physical exercise improves cardiovascular health, strengthens "
                "muscles, and reduces the risk of chronic diseases such as diabetes and "
                "hypertension."
            ),
        },
        {
            "paper_id": "p_irrelevant_weather",
            "text": "Seasonal rainfall patterns across the Amazon basin over the last decade.",
        },
        {
            "paper_id": "p_relevant_secondary",
            "text": (
                "Moderate aerobic activity such as brisk walking has been shown to lower "
                "blood pressure and improve mental well-being in adults."
            ),
        },
        {
            "paper_id": "p_irrelevant_finance",
            "text": "An overview of quarterly earnings reports for publicly traded technology firms.",
        },
    ]

    # Baseline, aufgezeichnet mit FlagEmbedding.FlagReranker.compute_score(
    # ..., normalize=True) -- siehe Docstring fuer die exakte Reproduktion.
    flagembedding_baseline_scores = {
        "p_relevant_primary": 0.9964107162736381,
        "p_relevant_secondary": 0.17979691103617984,
        "p_irrelevant_weather": 1.6168727883409747e-05,
        "p_irrelevant_art": 1.6107935622014048e-05,
        "p_irrelevant_finance": 1.606611461875519e-05,
    }
    flagembedding_baseline_order = [
        "p_relevant_primary",
        "p_relevant_secondary",
        "p_irrelevant_weather",
        "p_irrelevant_art",
        "p_irrelevant_finance",
    ]

    reranked = rerank_with_local_bge(query=query, candidates=candidates)
    crossencoder_order = [c["paper_id"] for c in reranked]

    assert crossencoder_order == flagembedding_baseline_order, (
        "CrossEncoder-Rangfolge weicht von der aufgezeichneten FlagEmbedding-Rangfolge ab "
        f"(AC2) -- CrossEncoder: {crossencoder_order}, FlagEmbedding-Baseline: "
        f"{flagembedding_baseline_order}"
    )

    for entry in reranked:
        baseline_score = flagembedding_baseline_scores[entry["paper_id"]]
        assert entry["rerank_score"] == pytest.approx(baseline_score, abs=1e-3), (
            f"CrossEncoder-Score fuer {entry['paper_id']} ({entry['rerank_score']}) weicht "
            f"um mehr als 1e-3 von der FlagEmbedding-Baseline ({baseline_score}) ab -- "
            "AC2 verlangt Aequivalenz zum vorherigen Backend, nicht nur eine plausible "
            "eigene Umsortierung."
        )
