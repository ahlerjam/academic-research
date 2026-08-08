"""Issue #732: Modellwechsel e5-small (384d) -> BAAI/bge-m3 (1024d), erprobt.

AC3 aus #732 verlangt den Migrationsweg samt Reindex-Aufwand fuer
Bestands-Vaults, "an einem Vault erprobt" -- nicht neu gebaut: der
Re-Index-Mechanismus (``migrate.reindex_embeddings``) existiert bereits aus
Issue #629 und ist dort ausfuehrlich mit einem synthetischen
``SizedEmbedder`` durchgetestet (Dimensionswechsel, Mischbestand, gesperrter
Vault, CLI-Flag -- siehe ``tests/test_issue_629_embedding_dim.py::TestReindex``).

Was dort FEHLT und dieser Test nachtraegt: ein Lauf mit dem ECHTEN, neuen
Default-Modell (``BAAI/bge-m3``, seit #732) statt einer synthetischen
Breiten-Attrappe -- also der Beleg, dass der bestehende Mechanismus fuer den
tatsaechlichen Kandidaten aus #731/#732 funktioniert, nicht nur strukturell
fuer eine beliebige Dimension.

Live-gated wie alle echten Modell-Tests im Repo (``VAULT_E5_LIVE_TEST=1``,
siehe ``tests/conftest.py::block_real_embedding_backend`` und
``tests/test_vault_embeddings_ingest.py::test_default_embedder_real_model_roundtrip``):
laedt bge-m3 (~2,3 GB, gecacht nach dem ersten Lauf) und rechnet auf CPU --
zu teuer fuer den Standard-Gate-Lauf, aber reproduzierbar und dokumentiert der
tatsaechliche Beleg fuer AC3.

Ergebnis eines echten Laufs (2026-08-08, Apple M4 Pro, CPU, drei synthetische
Papers / 3 Chunks / 1 Zitat, ~0,3-0,7s gesamt inkl. Modell-Load, je nach
Cache-Warmzustand): Re-Index
vollstaendig, ``embedding_meta`` zeigt danach ``BAAI/bge-m3``/1024, die
vec0-Spalten sind auf ``FLOAT[1024]`` verbreitert, und die KNN-Suche findet
nach dem Wechsel wieder das inhaltlich passende Paper. Dokumentiert in
``docs/evals/2026-08-08-embedding-model-decision-732.md``, Abschnitt
"Migrationsprobe".
"""

import json
import os
import sqlite3
import time

import pytest
from academic_vault import migrate
from academic_vault.db import VaultDB
from academic_vault.ingest import ingest_paper_embeddings

pytestmark = pytest.mark.skipif(
    os.environ.get("VAULT_E5_LIVE_TEST") != "1",
    reason="Live-Modelltest nur mit VAULT_E5_LIVE_TEST=1 (laedt BAAI/bge-m3, ~2,3 GB)",
)


class _SizedLegacyEmbedder:
    """Simuliert einen Bestands-Vault von VOR #732: 384d, e5-small-artig.

    Deterministisch statt echtem e5-small-Download -- der Punkt dieses Tests
    ist der Re-Index-Weg AUF das neue Modell, nicht ein zweiter Live-Download
    des alten. Modell-ID ist absichtlich die echte e5-small-ID, damit
    ``embedding_meta`` exakt wie ein realer Bestands-Vault aussieht.
    """

    dim = 384
    model_id = "intfloat/multilingual-e5-small"

    def _vector(self, text: str) -> list[float]:
        import hashlib
        import math
        import re

        vec = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            idx = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


_PAPERS = {
    "retrieval": (
        "Hybride Retrieval-Systeme in akademischen Vaults",
        "Dieser Beitrag untersucht, wie sich lexikalische und semantische Suche "
        "in wissenschaftlichen Literaturverwaltungen kombinieren lassen. Im "
        "Zentrum steht die Fusion von Volltextindex und dichten "
        "Vektorrepraesentationen ueber Reciprocal-Rank-Fusion, um sowohl exakte "
        "Fachbegriffe als auch semantisch verwandte Formulierungen zu finden. "
        "Die Evaluation erfolgt auf einem eigens erstellten Chunk-Goldset mit "
        "Fragen in deutscher und englischer Sprache.",
    ),
    "catering": (
        "Logistikoptimierung in der Grossgastronomie",
        "Der Artikel beschreibt ein Modell zur Tourenplanung fuer "
        "Cateringbetriebe mit schwankender Nachfrage. Betrachtet werden "
        "Lieferzeitfenster, Kuehlkettenanforderungen und die Auslastung "
        "mobiler Kuechen bei Grossveranstaltungen.",
    ),
    "climate": (
        "Anpassungsstrategien an den Klimawandel in Kuestenregionen",
        "Untersucht werden bauliche und planerische Massnahmen zur Anpassung "
        "an steigende Meeresspiegel in europaeischen Kuestenstaedten, "
        "einschliesslich Deichbau, Rueckzugsraeumen und Fruehwarnsystemen.",
    ),
}


def _seed_legacy_vault(db_path: str) -> None:
    """Baut einen Vault, der wie ein echter Bestand von VOR #732 aussieht."""
    db = VaultDB(db_path)
    db.init_schema()
    for paper_id, (title, abstract) in _PAPERS.items():
        db.add_paper(paper_id, json.dumps({"title": title, "abstract": abstract}))
        ingest_paper_embeddings(db_path, paper_id, text=abstract, embedder=_SizedLegacyEmbedder())
    db.add_quote(
        quote_id="q1",
        paper_id="retrieval",
        verbatim="Fusion von Volltextindex und dichten Vektorrepraesentationen ueber "
        "Reciprocal-Rank-Fusion",
        extraction_method="manual",
    )
    from academic_vault.server import embed_quote

    embed_quote(db_path, "q1", embedder=_SizedLegacyEmbedder())


def test_reindex_legacy_384d_vault_onto_real_bge_m3(tmp_path):
    """End-to-End-Beleg fuer AC3: 384d-Bestand -> echtes bge-m3 (1024d).

    Deckt strukturell dasselbe ab wie ``TestReindex`` in
    ``test_issue_629_embedding_dim.py``, aber mit dem tatsaechlichen Modell
    aus #732 statt einer synthetischen Breiten-Attrappe -- das ist der
    Unterschied, den AC3 ("an einem Vault erprobt") verlangt.
    """
    pytest.importorskip("sentence_transformers")
    from academic_vault.embedding_model import get_embedder, reset_embedder_cache

    db_path = str(tmp_path / "legacy_vault.db")
    _seed_legacy_vault(db_path)

    before = VaultDB(db_path).embedding_inventory()
    assert before is not None
    assert before["model_id"] == "intfloat/multilingual-e5-small"
    assert before["dim"] == 384

    reset_embedder_cache()
    real_embedder = get_embedder()
    assert real_embedder is not None, "bge-m3-Backend nicht ladbar -- Voraussetzung des Tests"

    start = time.perf_counter()
    stats = migrate.reindex_embeddings(db_path, embedder=real_embedder)
    elapsed = time.perf_counter() - start
    print(
        f"\n[#732] Re-Index von 384d (e5-small-artig) auf {stats['dim']}d "
        f"({stats['model_id']}): {stats['chunks']} Chunks, {stats['quotes']} Zitate "
        f"in {elapsed:.1f}s ({elapsed / max(stats['chunks'], 1) * 1000:.0f} ms/Chunk "
        "inkl. Modell-Load)."
    )

    assert stats["model_id"] == "BAAI/bge-m3"
    assert stats["dim"] == real_embedder.dim == 1024
    assert stats["chunks"] == 3, "drei kurze Abstracts -> je ein Chunk erwartet"
    assert stats["quotes"] == 1

    after = VaultDB(db_path).embedding_inventory()
    assert after is not None
    assert (after["model_id"], after["dim"]) == ("BAAI/bge-m3", 1024)

    conn = sqlite3.connect(db_path)
    try:
        chunk_vectors_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'chunk_vectors'"
        ).fetchone()
        quote_embeddings_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'quote_embeddings'"
        ).fetchone()
    finally:
        conn.close()
    if chunk_vectors_sql is not None:  # sqlite-vec optional (#372 Degradationspfad)
        assert "FLOAT[1024]" in chunk_vectors_sql[0]
        assert "FLOAT[1024]" in quote_embeddings_sql[0]

    # Inhaltliche Probe: nach dem Re-Index muss die semantische Suche wieder
    # das passende Paper finden -- nicht nur strukturell die richtige Breite.
    query_vector = real_embedder.embed_query(
        "Wie kombiniert man Volltextsuche mit Vektorsuche im Retrieval?"
    )
    hits = VaultDB(db_path).knn_chunks(query_vector, k=3)
    assert hits, "KNN-Suche liefert nach dem Re-Index keine Treffer"
    assert hits[0]["paper_id"] == "retrieval", (
        f"Bester Treffer sollte 'retrieval' sein, war {hits[0]['paper_id']!r} "
        f"(alle Treffer: {[h['paper_id'] for h in hits]})"
    )


def test_fresh_vault_self_heals_to_real_bge_m3_dimension(tmp_path):
    """Ein FRISCHER Vault braucht keinen Re-Index (#629-Selbstheilung, #732-Probe).

    Belegt, dass ``DEFAULT_EMBEDDING_DIM`` bewusst bei 384 bleibt (siehe
    Kommentar in ``embedding_model.py``): ein leerer Vault legt seine
    vec0-Tabellen zunaechst in dieser Legacy-Breite an
    (``VaultDB.init_schema()``), erkennt beim ERSTEN echten Embed mit dem
    neuen Default aber den leeren Bestand und baut sie selbstheilend in 1024d
    neu auf -- ohne ``migrate.reindex_embeddings`` und ohne dass die
    384-Annahme jemals sichtbar wird.
    """
    pytest.importorskip("sentence_transformers")
    from academic_vault.embedding_model import get_embedder, reset_embedder_cache

    db_path = str(tmp_path / "fresh_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    assert db.expected_embedding_dim() == 384, "Uebergangsbreite vor dem ersten Embed"

    db.add_paper("retrieval", json.dumps({"title": "t", "abstract": _PAPERS["retrieval"][1]}))

    reset_embedder_cache()
    real_embedder = get_embedder()
    assert real_embedder is not None
    assert real_embedder.dim == 1024

    n_chunks = ingest_paper_embeddings(
        db_path, "retrieval", text=_PAPERS["retrieval"][1], embedder=real_embedder
    )
    assert n_chunks >= 1

    assert VaultDB(db_path).expected_embedding_dim() == 1024
    lengths = {
        len(row["embedding_vector"])
        for row in VaultDB(db_path).get_chunk_embeddings("retrieval")
        if row["embedding_vector"]
    }
    assert lengths == {1024 * 4}
