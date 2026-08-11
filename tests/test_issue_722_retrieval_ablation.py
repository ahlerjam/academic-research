"""Regressionstests fuer den Ablations-Harness aus #722.

Hermetisch (kein Live-Modell) -- die Suite laeuft unter dem
``block_real_embedding_backend``-Guard aus ``tests/conftest.py``:
``get_embedder()`` liefert ``None`` (Degradationspfad), ``_vec0_search``
faellt auf ``[]`` zurueck, und der lokale Reranker wird ueber
``VAULT_RERANK_LOCAL_DISABLE`` deaktiviert, statt ein echtes Modell zu laden.
Der volle Live-Lauf (echte e5-/bge-reranker-Vektoren) ist manuell:

    VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/run_retrieval_ablation_722.py
"""

from __future__ import annotations

import json

import pytest
from academic_vault.db import VaultDB
from academic_vault.retrieval import ENV_LOCAL_RERANKER_DISABLE, apply_reranker
from scripts.eval.run_retrieval_ablation_722 import (
    build_paper_relevance,
    compute_deltas,
    search_papers_pre_702,
)
from scripts.eval.run_retrieval_chunk_goldset import GOLDSET_PATH, load_goldset


def test_build_paper_relevance_aggregates_chunks_to_papers() -> None:
    """Ein Paper ist relevant, sobald EIN Chunk der Query relevant ist."""
    goldset = {
        "chunks": [
            {"chunk_id": "d1#0", "doc_id": "d1"},
            {"chunk_id": "d1#1", "doc_id": "d1"},
            {"chunk_id": "d2#0", "doc_id": "d2"},
        ],
        "queries": [
            {"query_id": "q1", "relevant_chunk_ids": ["d1#0"]},
            {"query_id": "q2", "relevant_chunk_ids": ["d1#0", "d1#1", "d2#0"]},
            {"query_id": "q3", "relevant_chunk_ids": []},
        ],
    }
    relevance = build_paper_relevance(goldset)
    assert relevance == {"q1": {"d1"}, "q2": {"d1", "d2"}, "q3": set()}


def test_compute_deltas_flags_negative_delta_as_regression() -> None:
    """Eine Aenderung, die eine Metrik VERSCHLECHTERT, hat ein negatives Delta."""
    results = {
        "baseline_nach": {"overall": {"recall_at_10": 0.8, "ndcg_at_10": 0.7, "mrr": 0.6}},
        "nach_minus_ctx_meta": {"overall": {"recall_at_10": 0.8, "ndcg_at_10": 0.75, "mrr": 0.6}},
        "nach_minus_fts_text_fix": {
            "overall": {"recall_at_10": 0.8, "ndcg_at_10": 0.7, "mrr": 0.6}
        },
        "nach_minus_trigram": {"overall": {"recall_at_10": 0.8, "ndcg_at_10": 0.7, "mrr": 0.6}},
        "nach_minus_local_rerank": {
            "overall": {"recall_at_10": 0.8, "ndcg_at_10": 0.7, "mrr": 0.6}
        },
    }
    deltas = compute_deltas(results)
    # ohne ctx_meta ist nDCG HOEHER (0.75) als mit (0.7) -> ctx_meta HILFT NICHT,
    # das Delta (nach - ohne) ist negativ.
    assert deltas["ctx_meta"]["ndcg_at_10"] == pytest.approx(-0.05)
    assert deltas["fts_text_fix"]["ndcg_at_10"] == pytest.approx(0.0)


def _build_single_paper_db(tmp_path, title: str, chunk_text: str, fulltext: str) -> str:
    db_path = str(tmp_path / "ablation.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id="p1", csl_json=json.dumps({"title": title, "type": "article-journal"}))
    db.set_fulltext("p1", fulltext)
    # Kein echter Vektor noetig (die Suite blockt den Embedder ohnehin) --
    # embedding_vector=None ist gueltig (siehe VaultDB.add_chunk_embedding),
    # der Chunk-Text bleibt trotzdem ueber get_chunk_embeddings() abrufbar,
    # genau der Pfad, den server._fill_missing_reranker_text nutzt.
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text=chunk_text,
        context_sentence="ctx",
        embedding_text=f"ctx {chunk_text}",
        embedding_vector=None,
    )
    return db_path


def test_pre_702_shim_leaves_fts_only_candidate_with_raw_snippet(tmp_path, monkeypatch) -> None:
    """Differenzieller Beweis fuer den #702-Shim (Commit 68f2ed8).

    Ohne Vektor-Treffer (Embedder ist im Testlauf geblockt) ist jeder
    Kandidat FTS5-only. Der AKTUELLE Code (``server.search_papers``) ergaenzt
    ihn ueber ``_fill_missing_reranker_text`` um den vollen Chunk-Text; der
    #702-Shim laesst ihn bewusst weg -- der Kandidat traegt dann nur noch
    sein FTS5-Snippet (gekuerzt, vormals mit ``<b>``-Markup, das
    ``apply_reranker`` haertungshalber immer strippt).
    """
    monkeypatch.setenv(ENV_LOCAL_RERANKER_DISABLE, "1")
    chunk_text = (
        "Zebras migrate across the savanna in long seasonal loops that follow "
        "the rains, covering distances far beyond what casual observers assume."
    )
    db_path = _build_single_paper_db(
        tmp_path, title="Zebra Migration Patterns", chunk_text=chunk_text, fulltext=chunk_text
    )

    from academic_vault.server import search_papers

    current = search_papers(db_path, "zebra migration", k=5, rerank=True)
    shim = search_papers_pre_702(db_path, "zebra migration", k=5)

    assert current and shim
    assert current[0]["paper_id"] == "p1"
    assert shim[0]["paper_id"] == "p1"

    # AKTUELL: voller Chunk-Text (aus _fill_missing_reranker_text).
    assert current[0]["text"] == chunk_text
    # VOR #702: nur das gekuerzte FTS5-Snippet -- kuerzer und NICHT identisch
    # mit dem vollen Chunk-Text.
    assert shim[0]["text"] != chunk_text
    assert len(shim[0]["text"]) < len(chunk_text)
    # Der Haertungs-Fallback in apply_reranker() (Teil desselben #702-Commits,
    # aber nicht Teil des Flags) strippt trotzdem jedes verbliebene Markup.
    assert "<b>" not in shim[0]["text"]


def test_trigram_hits_return_empty_without_table_no_crash(tmp_path) -> None:
    """#703 'vor': fehlende papers_trgm-Tabelle ist ein echtes Bestands-Vault-

    Verhalten (kein Shim), _fts_trigram_hits faengt es ab statt zu crashen.
    """
    from academic_vault.server import _fts_trigram_hits

    db_path = str(tmp_path / "notrig.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="p1",
        csl_json=json.dumps({"title": "Mittelstandsdigitalisierung", "type": "article-journal"}),
    )
    conn = VaultDB._open(db_path)
    try:
        conn.execute("DROP TABLE papers_trgm")
        conn.commit()
        hits = _fts_trigram_hits(conn, "Mittelstand", None, 5)
    finally:
        conn.close()
    assert hits == []


def test_trigram_hits_find_compound_substring_when_table_present(tmp_path) -> None:
    """#703 'nach': mit intakter papers_trgm-Tabelle findet ein Teilwort-Treffer

    den Titel, auch wenn nur ein Bestandteil des Komposita gesucht wird.
    """
    from academic_vault.server import _fts_trigram_hits

    db_path = str(tmp_path / "trig.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="p1",
        csl_json=json.dumps({"title": "Mittelstandsdigitalisierung", "type": "article-journal"}),
    )
    conn = VaultDB._open(db_path)
    try:
        hits = _fts_trigram_hits(conn, "Mittelstand", None, 5)
    finally:
        conn.close()
    assert [h["paper_id"] for h in hits] == ["p1"]


def test_local_rerank_env_disable_short_circuits_without_loading_model(monkeypatch) -> None:
    """#714 'vor': VAULT_RERANK_LOCAL_DISABLE ist der echte Opt-out-Schalter.

    Regression gegen einen Tippfehler im Env-Var-Namen: schlaegt der Name in
    ``run_retrieval_ablation_722.py`` je vom echten Konstantennamen ab, greift
    der 'vor'-Zustand fuer #714 nicht mehr, und der Lauf misst versehentlich
    zweimal denselben ('nach'-)Zustand.
    """
    monkeypatch.setenv(ENV_LOCAL_RERANKER_DISABLE, "1")
    candidates = [{"paper_id": "p1", "text": "irrelevant"}]
    result = apply_reranker(query="q", candidates=candidates)
    assert result[0]["reranked"] is False
    assert result[0]["reranker"] == "none"


def test_goldset_context_sentences_are_the_701_vor_state() -> None:
    """Trag- und Grundannahme des Harness: die eingecheckte #708-Fixture

    (gebaut 2026-08-07, vor PR #771) entspricht Wort fuer Wort dem, was
    ``chunking.default_context_sentence(..., paper_meta=None)`` heute noch
    liefert. Bricht diese Annahme (z. B. weil #708 doch schon mit Metadaten
    gebaut wuerde, oder ``default_context_sentence`` den 'None'-Zweig
    aendert), darf der Harness die Fixture-Vektoren NICHT mehr als '#701 vor'
    wiederverwenden.
    """
    from academic_vault.chunking import default_context_sentence

    if not GOLDSET_PATH.exists():
        pytest.skip("#708-Fixture nicht vorhanden")
    goldset = load_goldset()
    for chunk in goldset["chunks"]:
        expected = default_context_sentence(
            chunk["section_title"], chunk["chunk_index"], chunk["page_start"], chunk["page_end"]
        )
        assert chunk["context_sentence"] == expected, chunk["chunk_id"]


def test_search_papers_pre_702_returns_empty_for_pure_operator_query(tmp_path) -> None:
    """Leere/operator-only Query bleibt leeres Ergebnis (kein OperationalError)."""
    db_path = str(tmp_path / "empty.db")
    db = VaultDB(db_path)
    db.init_schema()
    assert search_papers_pre_702(db_path, "   ", k=5) == []


def test_fts5_comma_defect_is_fixed_no_longer_a_production_bug(tmp_path) -> None:
    """Der in docs/evals/retrieval-ablation-722.md dokumentierte Fund
    (``db._sanitize_fts5_query`` haertete kein Komma ab, FTS5 MATCH brach mit
    ``sqlite3.OperationalError`` ab) ist seit #841 BEHOBEN: der Sanitizer
    quotet unsichere Tokens (u.a. das Komma-Token) als FTS5-Stringliteral
    statt sie unbehandelt durchzureichen. Dieser Test war urspruenglich ein
    Beleg-, kein Regressionstest (durfte laut eigenem Docstring rot werden,
    sobald der Defekt behoben ist -- das ist jetzt eingetreten) und wird hier
    zur Regressionsschranke umgedreht: ``search_papers`` (die
    PRODUKTIONSFUNKTION, nicht nur der #722-Harness) darf bei einer
    Komma-Query weder abstuerzen noch leer bleiben, wenn ein passendes Paper
    existiert -- der Treffer muss trotz Komma gefunden werden.
    """
    from academic_vault.server import search_papers

    db_path = str(tmp_path / "comma.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(paper_id="p1", csl_json=json.dumps({"title": "x", "type": "article-journal"}))
    db.set_fulltext("p1", "wie erkennt man frueh dass etwas fehlt")
    # Wirft NICHT mehr sqlite3.OperationalError -- das ist der eigentliche Test.
    results = search_papers(db_path, "wie erkennt man frueh, dass etwas fehlt", k=5, rerank=False)
    assert any(r["paper_id"] == "p1" for r in results)
