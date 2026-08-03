"""Struktur-Tests fuer das harte Recall-Goldset mit Themen-Overlap (#628).

Deckt AC1 (Goldset ueberlappt nachweislich, dokumentiert) und AC2 (mind. ein
Modellkandidat erreicht auf dem neuen Set Recall@10 < 1.0) ab.

AC1 ist eine reine JSON-Struktur-Pruefung ohne Modell-/Netzwerkzugriff. AC2
liest das eingecheckte Ergebnis-Artefakt eines manuellen Live-Laufs
(``docs/evals/recall-at-k-model-ab-hard-628-live-results.json``, Muster aus
Learning #524) -- der eigentliche empirische Beweis ist der Live-Lauf selbst
(echte Modelle, kein Mock, siehe ``docs/evals/recall-at-k-model-ab-hard-628.md``),
dieser Test verifiziert nur strukturell, dass das Artefakt die geforderte
Differenzierung zeigt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDSET_PATH = FIXTURES / "retrieval_goldset_hard_overlap_628.json"
LIVE_RESULTS_PATH = (
    Path(__file__).parent.parent
    / "docs"
    / "evals"
    / "recall-at-k-model-ab-hard-628-live-results.json"
)


def _load_goldset() -> dict:
    return json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# AC1: Goldset existiert, Themen ueberlappen nachweislich (Subtopics je
# Topic, Mindestgroesse pro Cluster, Query-Ground-Truth-Konsistenz).
# ---------------------------------------------------------------------------


class TestGoldsetFixtureSchema:
    def test_goldset_file_exists(self):
        assert GOLDSET_PATH.is_file(), f"Goldset-Fixture fehlt: {GOLDSET_PATH}"

    def test_goldset_has_topics_field_documenting_overlap(self):
        data = _load_goldset()
        assert "topics" in data
        assert len(data["topics"]) >= 2, "Zu wenige Themen fuer einen Cross-Topic-Vergleich"

    def test_every_topic_has_at_least_two_subtopics(self):
        data = _load_goldset()
        for topic, subtopics in data["topics"].items():
            assert len(subtopics) >= 2, f"Topic {topic} hat zu wenige Subtopics fuer Overlap"

    def test_every_topic_has_at_least_11_papers(self):
        """> k=10, damit Recall@10 fuer eine themenweite Query strukturell
        nicht 1.0 erreichen kann (Schubfachprinzip, siehe Modulweite Docstring)."""
        data = _load_goldset()
        papers_per_topic: dict[str, int] = {}
        for p in data["papers"]:
            papers_per_topic[p["topic"]] = papers_per_topic.get(p["topic"], 0) + 1
        for topic in data["topics"]:
            assert papers_per_topic.get(topic, 0) >= 11, (
                f"Topic {topic} hat nur {papers_per_topic.get(topic, 0)} Papers (< 11)"
            )

    def test_every_paper_topic_subtopic_is_declared(self):
        data = _load_goldset()
        for p in data["papers"]:
            assert p["topic"] in data["topics"], f"{p['paper_id']}: unbekanntes Topic"
            assert p["subtopic"] in data["topics"][p["topic"]], (
                f"{p['paper_id']}: unbekanntes Subtopic {p['subtopic']} fuer {p['topic']}"
            )

    def test_every_subtopic_has_at_least_one_query(self):
        data = _load_goldset()
        queried_subtopics = {
            (q["topic"], q["subtopic"]) for q in data["queries"] if q["subtopic"] is not None
        }
        for topic, subtopics in data["topics"].items():
            for subtopic in subtopics:
                assert (topic, subtopic) in queried_subtopics, (
                    f"Kein Query fuer Subtopic {topic}/{subtopic}"
                )

    def test_every_topic_has_at_least_one_cluster_wide_query(self):
        """Cluster-weite Query = Query ohne Subtopic-Bezug (subtopic: null)."""
        data = _load_goldset()
        cluster_wide_topics = {q["topic"] for q in data["queries"] if q["subtopic"] is None}
        for topic in data["topics"]:
            assert topic in cluster_wide_topics, f"Keine clusterweite Query fuer {topic}"

    def test_queries_reference_known_paper_ids(self):
        data = _load_goldset()
        paper_ids = {p["paper_id"] for p in data["papers"]}
        for q in data["queries"]:
            assert q["relevant_paper_ids"], f"Query {q['query_id']} ohne Ground-Truth-IDs"
            for pid in q["relevant_paper_ids"]:
                assert pid in paper_ids, f"Query {q['query_id']} referenziert unbekanntes {pid}"


class TestClusterWideQueriesGuaranteeSubMaximalRecall:
    """Belegt AC2 strukturell/deterministisch: eine Query mit mehr als k=10
    relevanten Papers kann per Definition von Recall@10 nie 1.0 erreichen,
    unabhaengig von der Guete des Embedding-Modells (Schubfachprinzip)."""

    def test_cluster_wide_queries_have_more_than_ten_relevant_papers(self):
        data = _load_goldset()
        cluster_wide = [q for q in data["queries"] if q["subtopic"] is None]
        assert cluster_wide, "Keine clusterweiten Queries im Goldset gefunden"
        for q in cluster_wide:
            assert len(q["relevant_paper_ids"]) > 10, (
                f"Query {q['query_id']} hat nur {len(q['relevant_paper_ids'])} relevante "
                "Papers -- Recall@10 = 1.0 waere fuer diese Query rechnerisch erreichbar "
                "und der Deckeneffekt aus #375 nicht strukturell ausgeschlossen"
            )


# ---------------------------------------------------------------------------
# AC2: Live-Ergebnis-Artefakt zeigt tatsaechliche Differenzierung.
# ---------------------------------------------------------------------------


class TestLiveResultsShowDifferentiation:
    def test_live_results_file_exists(self):
        assert LIVE_RESULTS_PATH.is_file(), (
            f"Live-Ergebnis-Artefakt fehlt: {LIVE_RESULTS_PATH}. "
            "Erzeugt durch manuellen Lauf von "
            "'uv run python scripts/eval/recall_at_k_model_ab.py --goldset hard'."
        )

    def test_live_results_show_at_least_one_candidate_below_1_0(self):
        data = json.loads(LIVE_RESULTS_PATH.read_text(encoding="utf-8"))
        results = data["results"] if isinstance(data, dict) else data
        assert results, "Live-Ergebnis-Artefakt enthaelt keine Modell-Resultate"
        assert any(r["mean_recall"] < 1.0 for r in results), (
            "Kein Kandidat unter Recall@10 = 1.0 -- das harte Goldset differenziert "
            "nicht (erneuter Deckeneffekt wie in #375)"
        )

    def test_live_results_cover_all_five_candidates(self):
        data = json.loads(LIVE_RESULTS_PATH.read_text(encoding="utf-8"))
        results = data["results"] if isinstance(data, dict) else data
        models = {r["model"] for r in results}
        assert models == {
            "e5-small",
            "minilm",
            "qwen3-embedding-0.6b",
            "bge-m3",
            "e5-large",
        }


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
