"""Regressionstests fuer Issue #791: ``_attach_chunk_to_fts_hit`` verliert den
Hybrid-Bonus bei fehlgeschlagenem lexikalischem Chunk-Lookup.

Befund aus #789 (Diagnoseblock in ``run_retrieval_ablation_729.py``):
``_attach_chunk_to_fts_hit`` (server.py) sprang, wenn ``chunk_fts`` keinen
Chunk desselben Papers findet (Stemming-/Komposita-Luecke), direkt auf den
synthetischen Schluessel ``fts-paper::<pid>`` ohne ``text`` -- der Reranker
bekam daraufhin den Abstract statt des zur Query passenden Chunks, die
Ausgabe gar keine Fundstelle. Der Fix zieht die vec0-Beschaffung in
``search_papers`` vor den FTS-Chunk-Attach und reicht ein
``paper_id -> bester Vektor-Chunk``-Dict als neuen optionalen Parameter durch,
aus dem Text und Fundstelle kommen.

Zweite, gleichrangige Seite dieses Moduls: der Fallback liefert INHALT, nicht
RANG. Der Fusionsschluessel bleibt der synthetische -- sonst bekaeme ein
Chunk ohne chunk-level lexikalischen Treffer einen kombinierten RRF-Rang und
der Beitrag von #727 verschwindet (am #790-Probe-Goldset gemessen).
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
    """Der Vektor-Fallback liefert Text UND Fundstelle des vektoriell besten
    Chunks -- genau das, was der Reranker (und die Ausgabe, #728) bei
    fehlgeschlagenem ``chunk_fts``-Lookup bisher nicht bekam."""
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
                "section_title": "Ergebnisse",
                "page_start": 7,
                "page_end": 8,
            }
        }
        entry = {"paper_id": "p1"}
        attached = _attach_chunk_to_fts_hit(
            conn, entry, "mittelstand", vec_best_by_paper=vec_best_by_paper
        )
    finally:
        conn.close()

    assert attached["text"] == "Die Mittelstandsdigitalisierung schreitet in KMU nur langsam voran."
    assert attached["section_title"] == "Ergebnisse"
    assert attached["page_start"] == 7
    assert attached["page_end"] == 8


def test_attach_does_not_hijack_the_vec_chunk_fusion_key_on_lexical_miss(tmp_path) -> None:
    """Der Vektor-Fallback liefert Text/Fundstelle, uebernimmt aber NICHT die
    ``chunk_id`` des Vektor-Chunks.

    ``reciprocal_rank_fusion`` schluesselt seit #727 auf ``chunk_id``. Wuerde
    der lexikalische Kandidat unter der ``chunk_id`` des Vektor-Chunks
    einlaufen, erschiene derselbe Schluessel in BEIDEN Rangdicts und bekaeme
    einen kombinierten RRF-Rang -- obwohl dieser Chunk gar keinen
    chunk-level lexikalischen Treffer hat (der Lookup ist ja fehlgeschlagen).
    Genau diese erfundene Ko-Okkurrenz hebt die Praezision auf, die #727
    ueberhaupt erst herstellt (belegt am #790-Probe-Goldset, siehe
    ``test_split_document_does_not_overtake_the_coherent_document``).
    """
    db_path = _build_db_with_unmatched_chunk(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        vec_chunk_id = conn.execute(
            "SELECT chunk_id FROM chunk_embeddings WHERE paper_id = ?", ("p1",)
        ).fetchone()["chunk_id"]
        attached = _attach_chunk_to_fts_hit(
            conn,
            {"paper_id": "p1"},
            "mittelstand",
            vec_best_by_paper={"p1": {"paper_id": "p1", "chunk_id": vec_chunk_id, "text": "egal"}},
        )
    finally:
        conn.close()

    assert attached["chunk_id"] == "fts-paper::p1"
    assert attached["chunk_id"] != vec_chunk_id


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
ABSTRACT_P1 = "Ein allgemeiner Ueberblick ohne konkrete Fundstelle."
VEC_BEST_TEXT = "Die Mittelstandsdigitalisierung schreitet in KMU nur langsam voran."
FIRST_CHUNK_TEXT = "Der Anhang listet Tabellen und Abbildungen."


def _build_db_where_the_fts_candidate_wins(tmp_path) -> str:
    """Ein Paper, dessen FTS5-Kandidat die Paper-Aggregation gewinnt, dessen
    ``chunk_fts``-Lookup aber fehlschlaegt.

    Aufbau (deterministisch, ohne Tie): ``p2`` besetzt vec-Rang 1, damit der
    beste Vektor-Chunk von ``p1`` auf vec-Rang 2 landet (RRF 1/62) und der
    FTS5-Kandidat von ``p1`` (FTS-Rang 1, RRF 1/61) die MAX-Aggregation in
    ``_aggregate_chunks_to_papers`` gewinnt. Nur so ist ueberhaupt
    beobachtbar, welchen Text der FTS5-Kandidat traegt.

    ``p1`` hat einen Abstract -- ohne den #791-Fix greift die erste Stufe von
    ``_fill_missing_reranker_text`` und der Reranker sieht den Abstract statt
    des zur Query passenden Chunks (genau der in #791 gemeldete Defekt).
    """
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="p1",
        csl_json=json.dumps(
            {
                "title": "Mittelstand Digitalisierung Report",
                "abstract": ABSTRACT_P1,
                "type": "article-journal",
            }
        ),
    )
    db.add_paper(
        paper_id="p2",
        csl_json=json.dumps({"title": "Okapi Sichtungen", "type": "article-journal"}),
    )
    db.register_embedding_inventory("intfloat/multilingual-e5-small", 4)
    # p2 besetzt vec-Rang 1 (Distanz 0 zur Query).
    db.add_chunk_embedding(
        paper_id="p2",
        chunk_text="Okapis bewohnen den Ituri-Regenwald.",
        context_sentence="ctx",
        embedding_text="ctx",
        embedding_vector=serialize_f32(l2_normalize([1.0, 0.0, 0.0, 0.0])),
    )
    # p1, erster Chunk (get_first_chunk_text-Stufe) -- vektoriell irrelevant.
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text=FIRST_CHUNK_TEXT,
        context_sentence="ctx",
        embedding_text="ctx",
        embedding_vector=serialize_f32(l2_normalize([0.0, 0.0, 1.0, 0.0])),
    )
    # p1, vektoriell bester Chunk -- enthaelt "Mittelstand" NICHT als eigenes
    # Token (Komposita-Luecke, #789), der chunk_fts-Lookup schlaegt also fehl.
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text=VEC_BEST_TEXT,
        context_sentence="ctx",
        embedding_text="ctx",
        embedding_vector=serialize_f32(l2_normalize([0.9, 0.1, 0.0, 0.0])),
        section_title="Ergebnisse",
        page_start=7,
        page_end=8,
    )
    return db_path


def test_search_papers_uses_vec_best_chunk_for_lexically_unmatched_hit(
    tmp_path, monkeypatch
) -> None:
    """AC (Issue #791), end-to-end: fehlschlagender ``chunk_fts``-Lookup, aber
    das Paper hat einen Vektor-Chunk -> ``search_papers`` liefert den
    Hybrid-Bonus aus dem Issue-Text, naemlich FTS5-Metadaten UND den
    inhaltlich passenden Chunk (Text + Fundstelle) auf EINEM Ergebnis --
    statt des Abstract-Fallbacks aus ``_fill_missing_reranker_text``."""
    db_path = _build_db_where_the_fts_candidate_wins(tmp_path)
    _cached_embedder(_FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0]), monkeypatch)

    results = search_papers(db_path, "Mittelstand", k=5, rerank=True)

    p1 = next(r for r in results if r["paper_id"] == "p1")
    # FTS5-Seite des Hybrid-Bonus: Snippet mit Highlighting + BM25-Score.
    assert "<b>Mittelstand</b>" in (p1.get("snippet") or "")
    assert p1.get("score") is not None
    # Vektor-Seite: der zur Query passende Chunk, NICHT der Abstract und
    # NICHT der erste gespeicherte Chunk (beide Stufen von
    # _fill_missing_reranker_text).
    assert p1["text"] == VEC_BEST_TEXT
    assert p1["text"] != ABSTRACT_P1
    assert p1["text"] != FIRST_CHUNK_TEXT
    # Fundstelle (#728) kommt aus demselben Vektor-Chunk.
    assert p1["section"] == "Ergebnisse"
    assert p1["page_start"] == 7
    assert p1["page_end"] == 8
    # Der Kandidat behaelt seinen eigenen Fusionsschluessel: sein RRF-Score
    # bleibt der eines EINSEITIGEN Treffers (FTS-Rang 1 = 1/(60+1)). Ein
    # kombinierter Rang hier waere die erfundene Ko-Okkurrenz aus
    # test_attach_does_not_hijack_the_vec_chunk_fusion_key_on_lexical_miss.
    assert p1["rrf_score"] == pytest.approx(1 / 61)


def test_split_document_does_not_overtake_the_coherent_document(tmp_path, monkeypatch) -> None:
    """Regression zum #790-Probe-Goldset (Familie A) im Kleinen.

    ``split`` enthaelt beide Query-Begriffe, aber auf ZWEI Chunks verteilt --
    kein einzelner Chunk trifft die Query lexikalisch, der
    ``chunk_fts``-Lookup schlaegt fehl. ``coherent`` traegt beide Begriffe in
    EINEM Chunk, der zusaetzlich vektoriell gefunden wird: nur dieser Chunk
    hat echte Ko-Okkurrenz aus beiden Quellen und darf den kombinierten
    RRF-Rang bekommen. Genau diese Trennung ist der Beitrag von #727 -- ein
    Vektor-Fallback, der die ``chunk_id`` des Vektor-Chunks uebernimmt, gibt
    sie ``split`` unverdient auch und dreht die Reihenfolge um.
    """
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.register_embedding_inventory("intfloat/multilingual-e5-small", 4)
    for paper_id in ("split", "coherent"):
        db.add_paper(
            paper_id=paper_id,
            csl_json=json.dumps({"title": "dossier escrow custodian", "type": "article-journal"}),
        )
    # split: Begriffe auf zwei Chunks verteilt -> chunk_fts findet keinen
    # Chunk, der die ganze Query traegt.
    db.add_chunk_embedding(
        paper_id="split",
        chunk_text="The dossier lists every signature collected so far.",
        context_sentence="ctx",
        embedding_text="ctx",
        embedding_vector=serialize_f32(l2_normalize([1.0, 0.0, 0.0, 0.0])),
    )
    db.add_chunk_embedding(
        paper_id="split",
        chunk_text="An escrow custodian holds the material until release.",
        context_sentence="ctx",
        embedding_text="ctx",
        embedding_vector=serialize_f32(l2_normalize([0.8, 0.2, 0.0, 0.0])),
    )
    # coherent: beide Begriffe in EINEM Chunk -> chunk_fts trifft.
    db.add_chunk_embedding(
        paper_id="coherent",
        chunk_text="The release dossier names a single escrow custodian for the signing material.",
        context_sentence="ctx",
        embedding_text="ctx",
        embedding_vector=serialize_f32(l2_normalize([0.7, 0.3, 0.0, 0.0])),
    )
    _cached_embedder(_FixedVectorEmbedder([1.0, 0.0, 0.0, 0.0]), monkeypatch)

    results = search_papers(db_path, "dossier escrow custodian", k=5, rerank=True)

    ranking = [r["paper_id"] for r in results]
    assert ranking[0] == "coherent", ranking


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
