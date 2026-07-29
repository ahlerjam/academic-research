"""Recall@k-Goldset DE/EN gegen ein reales Fixture-Vault (Issue #375).

Abgrenzung zu ``test_vault_rerank.py::TestRecallEval``: dort laeuft
``retrieval_eval_set.json`` (200 rein-englische Mock-Papers) nur FTS5-only
ohne rerank=True. Dieses Modul nutzt das neue, bewusst kleine DE/EN-Goldset
(``tests/fixtures/retrieval_goldset_de_en.json``) und ruft den kompletten
Hybrid-Pfad (RRF aus FTS5 + vec0-KNN via ``search_papers(..., rerank=True)``)
real auf -- mit dem deterministischen ``fake_embedder`` aus
``tests/conftest.py`` injiziert statt des echten e5-Modells (kein
Netzwerk/API-Key noetig, siehe autouse-Guard ``block_real_embedding_backend``).

Die zurueckgegebenen ``retrieved_ids`` kommen aus dem echten
``search_papers``-Aufruf, nicht aus dem Goldset-JSON kopiert -- ``compute_recall_at_k``
rechnet also gegen echte Suchergebnisse (AC2).
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDSET_PATH = FIXTURES / "retrieval_goldset_de_en.json"


def _load_goldset() -> dict:
    return json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))


def _make_db(tmp_path: Path) -> str:
    """Erstellt eine Vault-DB mit Schema und gibt den Pfad zurueck."""
    db_path = str(tmp_path / "vault.db")
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    db.init_schema()
    return db_path


def _use_embedder(monkeypatch, embedder) -> None:
    """Injiziert den Test-Embedder in Ingest- UND Suchpfad (Muster aus #372)."""
    monkeypatch.setattr("academic_vault.ingest.get_embedder", lambda *a, **kw: embedder)
    monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: embedder)


def _build_goldset_vault(db_path: str, data: dict) -> None:
    """Laedt alle Goldset-Papers per echtem ``add_paper`` in die Vault-DB."""
    from academic_vault.server import add_paper

    for p in data["papers"]:
        csl = {
            "type": "article-journal",
            "title": p["title"],
            "abstract": p["abstract"],
        }
        add_paper(db_path, p["paper_id"], json.dumps(csl))


# ---------------------------------------------------------------------------
# AC1: Goldset-Fixture existiert, 10-20 Queries, DE+EN gemischt.
# ---------------------------------------------------------------------------


class TestGoldsetFixtureSchema:
    """Struktur-/Schema-Checks fuer das eingecheckte DE/EN-Goldset (AC1)."""

    def test_goldset_file_exists(self):
        assert GOLDSET_PATH.is_file(), f"Goldset-Fixture fehlt: {GOLDSET_PATH}"

    def test_goldset_has_10_to_20_queries(self):
        data = _load_goldset()
        assert 10 <= len(data["queries"]) <= 20

    def test_goldset_has_de_and_en_queries(self):
        data = _load_goldset()
        langs = {q["lang"] for q in data["queries"]}
        assert "de" in langs, "Kein deutschsprachiges Query im Goldset"
        assert "en" in langs, "Kein englischsprachiges Query im Goldset"

    def test_goldset_queries_have_nonempty_relevant_ids(self):
        data = _load_goldset()
        paper_ids = {p["paper_id"] for p in data["papers"]}
        for q in data["queries"]:
            assert q["relevant_paper_ids"], f"Query {q['query_id']} ohne Ground-Truth-IDs"
            for pid in q["relevant_paper_ids"]:
                assert pid in paper_ids, f"Query {q['query_id']} referenziert unbekanntes {pid}"

    def test_goldset_has_reasonable_paper_count(self):
        """20-30 Fixture-Papers laut Plan, klar in Themencluster gruppiert."""
        data = _load_goldset()
        assert 20 <= len(data["papers"]) <= 30
        topics = {p["topic"] for p in data["papers"]}
        assert len(topics) >= 4, "Zu wenige Themencluster fuer trennbares Retrieval"


# ---------------------------------------------------------------------------
# AC2: pytest fuehrt vault.search real gegen das Fixture-Vault aus und
# berechnet compute_recall_at_k mit den echten Suchergebnissen.
# ---------------------------------------------------------------------------


class TestRecallGoldsetRealSearch:
    """Realer Hybrid-Suchlauf (RRF + vec0) ueber das DE/EN-Goldset (AC2)."""

    def test_hybrid_search_recall_at_10_on_goldset(self, tmp_path, fake_embedder, monkeypatch):
        """search_papers(..., rerank=True) real aufgerufen, Recall@10 > 0.

        Mean-Recall wird ueber ALLE Goldset-Queries gemittelt. Da die 6
        Themencluster im Goldset klar getrennt sind (Transformer/Attention,
        Klimawandel, Hybrid-Retrieval, Computer Vision, Quantencomputing,
        Bibliometrie), sollte der Hybrid-Pfad deutlich mehr als triviale
        0-Treffer erzielen -- die Schwelle bleibt bewusst moderat (kein
        exakter Fixwert), um nicht an Embedder-/RRF-Feinheiten zu haengen.
        """
        from academic_vault.retrieval import compute_recall_at_k
        from academic_vault.server import search_papers

        data = _load_goldset()
        db_path = _make_db(tmp_path)
        _use_embedder(monkeypatch, fake_embedder)
        _build_goldset_vault(db_path, data)

        recalls = []
        for q in data["queries"]:
            results = search_papers(db_path, q["query"], k=10, rerank=True)
            retrieved_ids = [r["paper_id"] for r in results]
            recall = compute_recall_at_k(retrieved_ids, q["relevant_paper_ids"], k=10)
            recalls.append(recall)

        mean_recall = sum(recalls) / len(recalls)
        assert mean_recall > 0.0, "Hybrid-Recall@10 ist 0.0 -- Retrieval liefert keine Treffer"
        assert mean_recall >= 0.4, (
            f"Hybrid-Recall@10 ({mean_recall:.2f}) unerwartet niedrig fuer klar "
            "getrennte Themencluster"
        )

    def test_hybrid_search_matches_correct_cluster_for_broad_queries(
        self, tmp_path, fake_embedder, monkeypatch
    ):
        """Fuer die 6 breiten Cluster-Queries (4 relevante Papers) liefert die
        Hybrid-Suche mindestens ein Paper aus dem richtigen Cluster in Top-10 --
        Sanity-Check, dass die Cluster tatsaechlich trennbar sind (Plan-Risiko 2)."""
        from academic_vault.server import search_papers

        data = _load_goldset()
        db_path = _make_db(tmp_path)
        _use_embedder(monkeypatch, fake_embedder)
        _build_goldset_vault(db_path, data)

        broad_queries = [q for q in data["queries"] if len(q["relevant_paper_ids"]) == 4]
        assert len(broad_queries) >= 4, "Zu wenige breite Cluster-Queries im Goldset"

        for q in broad_queries:
            results = search_papers(db_path, q["query"], k=10, rerank=True)
            retrieved_ids = {r["paper_id"] for r in results}
            hit = retrieved_ids & set(q["relevant_paper_ids"])
            assert hit, f"Query {q['query_id']} findet kein relevantes Paper des Clusters"

    def test_recall_uses_real_retrieved_ids_not_goldset_copy(
        self, tmp_path, fake_embedder, monkeypatch
    ):
        """Stellt sicher, dass Recall aus echten Suchergebnissen kommt (AC2):

        wird nur die IRRELEVANTE Haelfte der Papers indexiert, muss der
        Recall fuer davon betroffene Queries sinken -- waere ``retrieved_ids``
        aus dem Goldset kopiert (synthetisch), bliebe der Wert unveraendert.
        """
        from academic_vault.retrieval import compute_recall_at_k
        from academic_vault.server import add_paper, search_papers

        data = _load_goldset()
        db_path = _make_db(tmp_path)
        _use_embedder(monkeypatch, fake_embedder)

        # Nur die Haelfte der Papers indexieren (gerade Positionen ueberspringen).
        indexed_papers = data["papers"][::2]
        for p in indexed_papers:
            csl = {"type": "article-journal", "title": p["title"], "abstract": p["abstract"]}
            add_paper(db_path, p["paper_id"], json.dumps(csl))
        indexed_ids = {p["paper_id"] for p in indexed_papers}

        query = next(q for q in data["queries"] if len(q["relevant_paper_ids"]) == 4)
        results = search_papers(db_path, query["query"], k=10, rerank=True)
        retrieved_ids = [r["paper_id"] for r in results]

        # Keine der zurueckgegebenen IDs darf ausserhalb der indexierten Papers liegen.
        assert set(retrieved_ids) <= indexed_ids

        recall_partial = compute_recall_at_k(retrieved_ids, query["relevant_paper_ids"], k=10)
        expected_max = len(set(query["relevant_paper_ids"]) & indexed_ids) / len(
            query["relevant_paper_ids"]
        )
        assert recall_partial <= expected_max + 1e-9


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
