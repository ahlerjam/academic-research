#!/usr/bin/env python3
"""Ablationslauf: traegt der Umbau auf Chunk-Ebene? (#729)

#726 (PR #770) fuegte den chunk-level FTS5-Index ``chunk_fts`` hinzu. #727
(PR #777) stellte ``reciprocal_rank_fusion()`` von ``paper_id``- auf
``chunk_id``-Schluesselung um und verschob die Paper-Aggregation NACH die
Fusion. Beide Aenderungen sind strukturell begruendet, aber nicht gegen das
Chunk-Goldset aus #708 gemessen. Dieses Skript misst drei Zustaende:

- **vorher** (``chunk_fts_index=False, chunk_fusion=False``): lexikalische
  Seite ueber ``papers_fts``/``papers_trgm`` (Titel/Abstract, wie vor #726),
  Fusion auf ``paper_id`` (wie vor #727). Kein Produktionsschalter mehr
  vorhanden (beide Pfade wurden ersetzt) -- Shim, dokumentiert und
  differenziell gegen den historischen Code (Commit ``a32f570^``) geprueft in
  ``tests/test_issue_729_chunk_fusion_ablation.py``.
- **Zwischenzustand A** (``chunk_fts_index=True, chunk_fusion=False``):
  WICHTIG -- ``chunk_fts`` ist im echten Produktionscode NIE eine eigene
  Kandidatenquelle (das war ein Fehler in einer frueheren Fassung dieses
  Skripts, PR-Review-Fund). Die lexikalische KandidatenSUCHE bleibt in JEDEM
  gemessenen Zustand ``papers_fts``/``papers_trgm`` (unveraendert seit #703,
  siehe ``server.search_papers`` Zeilen 1011-1024). Was #726 tatsaechlich
  liefert, ist ein Chunk-LOOKUP fuer einen bereits gefundenen Paper-Treffer:
  ``server._attach_chunk_to_fts_hit`` (#727, nutzt intern den #726-Index)
  ordnet jedem ``papers_fts``/``papers_trgm``-Treffer seinen best-passenden
  Chunk zu. Zwischenzustand A ruft exakt diese reale Produktionsfunktion auf,
  haelt die Fusion aber auf Paper-Ebene (wie vor #727) -- isoliert damit, was
  eine chunk-Anreicherung *ohne* Aenderung der Fusionsgranularitaet bewirken
  wuerde.
- **nachher** (``chunk_fts_index=True, chunk_fusion=True``): der aktuelle
  Produktionscode, unveraendert ueber ``academic_vault.server.search_papers``.

Delta(A - vorher) = Beitrag der Chunk-Anreicherung (#726 ueber
``_attach_chunk_to_fts_hit``) OHNE Fusionsaenderung. Bei deaktiviertem
Reranker (siehe unten) ist dieser Beitrag NULL per Konstruktion: Paper-Ebene-
RRF schluesselt auf ``paper_id`` und ignoriert ``chunk_id``/``text`` voll-
staendig -- eine Chunk-Anreicherung kann die Rangfolge erst beeinflussen,
sobald ein Reranker das angereicherte ``text``-Feld tatsaechlich liest. Das
ist eine mathematische Eigenschaft der Paper-Ebene-Fusion, kein empirischer
Befund -- siehe Report fuer die Einordnung.
Delta(nachher - A) = Beitrag der Chunk-Ebene-Fusion (#727) selbst.
Delta(nachher - vorher) = Gesamtbeitrag des Umbaus (nicht notwendig additiv).

Zwei Messteile:

1. **Retrieval-Qualitaet (AC1/AC2)**: gegen das Chunk-Goldset aus #708, MIT
   Paper-Aggregation (ein Paper gilt als relevant, wenn mindestens ein
   relevanter Chunk der Query enthalten ist -- Konsum der #708-Fixture wie in
   #722, keine Goldset-Erweiterung). Vollstaendig HERMETISCH: weder #701 noch
   der Reranker (#702/#703/#714, bereits in #722 separat vermessen) sind Teil
   dieses Umbaus, daher genuegt es, den lokalen Reranker abzuschalten
   (``VAULT_RERANK_LOCAL_DISABLE=1``) und die Query-/Chunk-Vektoren aus der
   eingecheckten #708-Fixture ueber einen Playback-Embedder zu bedienen
   (``embedding_model._EMBEDDER_CACHE`` wird dafuer vorbelegt, kein Modell-
   Download noetig). Kein ``VAULT_E5_LIVE_TEST=1`` erforderlich.
2. **Index- und Laufzeitkosten (AC3)**: an einem synthetischen Vault mit
   MINDESTENS 50 Papern. Auch hier hermetisch -- Index-Groesse und
   Suchlatenz haengen von Text-/Chunk-VOLUMEN und der SQL-/vec0-Mechanik ab,
   nicht von der semantischen Qualitaet der Vektoren. Ein deterministischer
   Fake-Embedder (``_DeterministicEmbedder``, seed-basiert, L2-normalisiert)
   ersetzt das echte e5-Modell; die Chunks selbst laufen ueber die echte
   ``chunking.chunk_pages()`` mit ``approximate_token_count`` statt dem
   echten Tokenizer (kein Netzzugriff noetig, siehe
   ``tests/conftest.py::block_real_embedding_backend`` fuer dasselbe Muster
   in der Testsuite).

3. **Nullbefund-Diagnose (Issue #789)**: :func:`run_diagnostics` rechnet je
   Query mechanistisch gegen die echten Produktionsfunktionen
   (``retrieval.reciprocal_rank_fusion``, ``server._attach_chunk_to_fts_hit``,
   ``server._vec0_search``) nach, WARUM alle drei oben gemessenen Zustaende
   query-fuer-query identische Ergebnisse liefern: die lexikalische Seite des
   #708-Goldsets ist strukturell tot (ausgeschriebene Saetze mit implizitem
   AND ueber alle Tokens treffen ``papers_fts``/``papers_trgm`` fast nie),
   nicht "Korpus zu klein" wie im urspruenglichen #729-Report vermutet --
   siehe Nachtrag in ``docs/evals/2026-08-08-chunk-fusion-ablation-729.md``.
   ``--goldset``/``--vectors`` gelten fuer alle drei Messteile gleichermassen.

Nutzung::

    uv run python scripts/eval/run_retrieval_ablation_729.py \\
      --out docs/evals/2026-08-08-chunk-fusion-ablation-729-live-results.json

    # Nur die Diagnose (Issue #789), gegen ein alternatives Goldset:
    uv run python scripts/eval/run_retrieval_ablation_729.py \\
      --goldset pfad/zu/goldset.json --vectors pfad/zu/vectors.json \\
      --skip-cost
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_retrieval_ablation_722 import build_db  # noqa: E402
from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    GOLDSET_PATH,
    VECTORS_PATH,
    ManifestMismatchError,
    build_playback_embedder,
    diverged_mapping,
    diverged_metrics,
    diverged_per_query,
    load_goldset,
    load_vectors,
    verify_manifest,
)

DEFAULT_K = 10
METRICS = ("recall_at_10", "ndcg_at_10", "mrr")

# Vault-Groesse fuer AC3 ("mindestens 50 Paper" laut Akzeptanzkriterium) --
# etwas Marge ueber dem Minimum, damit ein einzelner unguenstig gechunkter
# Ausreisser die Schwelle nicht unterschreitet.
AC3_PAPER_COUNT = 60
AC3_SEED = 729


# ---------------------------------------------------------------------------
# Paper-Ebene-Aggregation: Wiederverwendung aus #722 (keine Goldset-Erweiterung,
# keine zweite Implementierung derselben Aggregationsregel).
# ---------------------------------------------------------------------------
def build_paper_relevance(goldset: dict) -> dict[str, set[str]]:
    """Delegiert an ``run_retrieval_ablation_722.build_paper_relevance``.

    Eigener Name hier beibehalten (statt Re-Export), damit dieses Modul ohne
    Blick in #722 lesbar bleibt -- die Aggregationsregel selbst (>=1
    relevanter Chunk macht das Paper relevant) ist in #722 bereits erprobt
    und getestet.
    """
    from scripts.eval.run_retrieval_ablation_722 import build_paper_relevance as _impl

    return _impl(goldset)


# ---------------------------------------------------------------------------
# 'vorher'/Zwischenzustand-A-Shim: Fusion auf paper_id (wie vor #727)
# ---------------------------------------------------------------------------
def _paper_id_rrf(
    vec_results: list[dict],
    fts_results: list[dict],
    k: int = 60,
    top_n: int | None = None,
) -> list[dict]:
    """Reimplementiert ``retrieval.reciprocal_rank_fusion()`` wie vor #727.

    Bitgleich zur historischen Fassung (Commit ``a32f570^:academic_vault/retrieval.py``,
    vor PR #777): Schluessel ist ``paper_id`` statt ``chunk_id``, Metadaten
    beider Quellen werden zusammengefuehrt (FTS gewinnt bei Kollision), sortiert
    absteigend nach ``rrf_score``. Reimplementiert statt importiert, weil die
    Produktionsfunktion seit #727 zwingend ``chunk_id`` erwartet (KeyError bei
    ``paper_id``-only Eintraegen) -- differenziell gegen den historischen Stand
    geprueft in ``tests/test_issue_729_chunk_fusion_ablation.py``.
    """
    from academic_vault.retrieval import rrf_score

    vec_ranks: dict[str, int] = {r["paper_id"]: idx + 1 for idx, r in enumerate(vec_results)}
    fts_ranks: dict[str, int] = {r["paper_id"]: idx + 1 for idx, r in enumerate(fts_results)}
    all_paper_ids = set(vec_ranks) | set(fts_ranks)

    paper_data: dict[str, dict] = {}
    for r in vec_results:
        paper_data.setdefault(r["paper_id"], {}).update(r)
    for r in fts_results:
        paper_data.setdefault(r["paper_id"], {}).update(r)

    fused: list[dict] = []
    for pid in all_paper_ids:
        entry = dict(paper_data.get(pid, {"paper_id": pid}))
        entry["rrf_score"] = rrf_score(vec_ranks.get(pid), fts_ranks.get(pid), k=k)
        fused.append(entry)

    fused.sort(key=lambda x: x["rrf_score"], reverse=True)
    if top_n is not None:
        fused = fused[:top_n]
    return fused


def _vec0_search_paper_level(db_path: str, query: str, k: int) -> list[dict]:
    """Reimplementiert die Paper-Dedup, die ``server._vec0_search()`` vor #727
    selbst durchfuehrte (Commit ``a32f570^``).

    Ruft den heutigen (chunk-level, #727) ``_vec0_search`` mit dem
    UNVERAENDERTEN ``k`` auf -- der historische Code rief
    ``knn_chunks(k=max(k*4, k))`` GENAU EINMAL auf; die heutige
    ``_vec0_search`` wendet dieselbe ``max(k*4, k)``-Multiplikation intern
    SELBST an. Wuerde diese Funktion hier zusaetzlich ``k*4`` uebergeben,
    verdoppelte sich die Multiplikation (``max((k*4)*4, k*4)`` -> ein 16-facher
    statt 4-facher Pool, PR-Review-Fund) -- der zugrunde liegende
    KNN-Mechanismus (``VaultDB.knn_chunks``) ist seit #727 unveraendert, nur
    die Aggregation wurde AUS der Funktion heraus verschoben, und wird hier
    wieder auf bestes Chunk je Paper (nach Distanz aufsteigend) aggregiert,
    genau wie der historische Code.
    """
    from academic_vault import server as _server

    chunk_hits = _server._vec0_search(db_path, query, k=k)
    best_per_paper: dict[str, dict] = {}
    for hit in chunk_hits:  # bereits aufsteigend nach Distanz sortiert
        pid = hit["paper_id"]
        if pid in best_per_paper:
            continue
        best_per_paper[pid] = dict(hit)
    ranked = sorted(best_per_paper.values(), key=lambda e: e["distance"])
    return ranked[:k]


def _papers_fts_hits(conn, query: str, k: int) -> list[dict]:
    """Die reale, UNVERAENDERTE lexikalische Kandidatenquelle (``papers_fts``/
    ``papers_trgm``, seit #703 unangetastet) -- identisch fuer 'vorher' UND
    Zwischenzustand A. Zeile-fuer-Zeile dasselbe Verfahren wie in
    ``server.search_papers`` vor dem ``rerank``-Zweig (Zeilen 1011-1024).
    """
    from academic_vault import server as _server

    fts_results = _server._fts_exact_hits(conn, query, None, k)
    if len(fts_results) < k:
        seen = {r["paper_id"] for r in fts_results}
        for row in _server._fts_trigram_hits(conn, query, None, k):
            if row["paper_id"] in seen:
                continue
            fts_results.append(row)
            seen.add(row["paper_id"])
            if len(fts_results) >= k:
                break
    return fts_results


def search_papers_paper_level(db_path: str, query: str, k: int, attach_chunk: bool) -> list[dict]:
    """'vorher' (``attach_chunk=False``) bzw. Zwischenzustand A
    (``attach_chunk=True``): Fusion auf ``paper_id`` (Shim, wie vor #727).

    Die lexikalische KandidatenSUCHE ist in BEIDEN Faellen
    ``papers_fts``/``papers_trgm`` (:func:`_papers_fts_hits`) -- ``chunk_fts``
    ist in der echten Produktion NIE eine eigene Suchquelle (PR-Review-Fund an
    einer frueheren Fassung dieses Skripts, die ``chunk_fts`` faelschlich
    direkt befragte). ``attach_chunk=True`` reichert jeden gefundenen
    Paper-Treffer zusaetzlich per ``server._attach_chunk_to_fts_hit`` (#727,
    die REALE Produktionsfunktion, die den #726-Index als Chunk-LOOKUP fuer
    ein bereits gefundenes Paper nutzt) um ``chunk_id``/``text`` an.

    Beide Zweige nutzen denselben paper-level Vektorpfad
    (:func:`_vec0_search_paper_level`) und dieselbe paper_id-Fusion
    (:func:`_paper_id_rrf`), genau das historische Verhalten vor #727.
    """
    from academic_vault import server as _server
    from academic_vault.db import VaultDB
    from academic_vault.retrieval import apply_reranker

    raw_query = query
    sanitized = _server._sanitize_fts5_query(query)
    if not sanitized:
        return []

    _server._ensure_schema_for_read(db_path)
    conn = VaultDB._open(db_path)
    try:
        fts_results = _papers_fts_hits(conn, sanitized, k)
        if attach_chunk:
            fts_results = [
                _server._attach_chunk_to_fts_hit(conn, r, sanitized) for r in fts_results
            ]
    finally:
        conn.close()

    vec_results = _vec0_search_paper_level(db_path, raw_query, k)
    fused = _paper_id_rrf(vec_results, fts_results, k=60, top_n=k)
    _server._fill_missing_reranker_text(db_path, fused)
    return apply_reranker(query=raw_query, candidates=fused)


# ---------------------------------------------------------------------------
# Suche + Metrik je Kombination (AC1/AC2, hermetisch, Chunk-Goldset #708)
# ---------------------------------------------------------------------------
def _env_guard():
    """Neutralisiert Cloud-Reranker-Keys und deaktiviert den lokalen Reranker.

    Reranking (#702/#703/#714) ist bereits in #722 separat vermessen und kein
    Teil des #726/#727-Umbaus -- konstant AUS in allen drei Zustaenden macht
    den Lauf hermetisch (kein CrossEncoder-Modell noetig) UND isoliert exakt
    den Beitrag von Index/Fusion.
    """
    from academic_vault.retrieval import ENV_LOCAL_RERANKER_DISABLE

    class _Guard:
        def __enter__(self):
            self._prior_local = os.environ.get(ENV_LOCAL_RERANKER_DISABLE)
            self._prior_voyage = os.environ.pop("VOYAGE_API_KEY", None)
            self._prior_cohere = os.environ.pop("COHERE_API_KEY", None)
            os.environ[ENV_LOCAL_RERANKER_DISABLE] = "1"
            return self

        def __exit__(self, *exc):
            if self._prior_local is None:
                os.environ.pop(ENV_LOCAL_RERANKER_DISABLE, None)
            else:
                os.environ[ENV_LOCAL_RERANKER_DISABLE] = self._prior_local
            if self._prior_voyage is not None:
                os.environ["VOYAGE_API_KEY"] = self._prior_voyage
            if self._prior_cohere is not None:
                os.environ["COHERE_API_KEY"] = self._prior_cohere

    return _Guard()


def run_search(
    db_path: str, query: str, k: int, chunk_fts_index: bool, chunk_fusion: bool
) -> list[str]:
    """Fuehrt EINE Suche fuer die gewuenschte Kombination aus, gibt Paper-IDs zurueck.

    ``chunk_fts_index`` steuert hier, ob die Paper-Ebene-Fusion (``chunk_fusion=False``)
    jeden Treffer per ``server._attach_chunk_to_fts_hit`` (#727, nutzt den
    #726-Index als Chunk-LOOKUP, siehe :func:`search_papers_paper_level`) um
    einen Chunk anreichert -- NICHT, ob ``chunk_fts`` als eigene Suchquelle
    dient (das tut sie in der echten Produktion nie).
    """
    from academic_vault.server import search_papers

    with _env_guard():
        if chunk_fusion:
            if not chunk_fts_index:
                raise ValueError(
                    "chunk_fusion=True setzt chunk_fts_index=True voraus (#727 baut auf #726 auf)"
                )
            results = search_papers(db_path, query, k=k, rerank=True)
        else:
            results = search_papers_paper_level(db_path, query, k, attach_chunk=chunk_fts_index)

    seen: list[str] = []
    for r in results:
        pid = r["paper_id"]
        if pid not in seen:
            seen.append(pid)
    return seen[:k]


def _aggregate_by_case(per_query: list[dict]) -> dict[str, dict]:
    """Gruppiert die per-Query-Metriken aus :func:`evaluate_combo` nach dem
    ``case``-Feld des Goldsets (``same-language``/``cross-language``/
    ``language-gap``, Issue #789).

    Ein einzelnes Gesamtmittel (``overall`` in :func:`evaluate_combo`)
    verdeckt, ob eine schwaechere Fallgruppe (z. B. ``language-gap``) von
    einer staerkeren aufgewogen wird -- dieselbe Kritik, die #789 an der
    pauschalen "Korpus zu klein"-Diagnose im #729-Report uebt, gilt auch
    fuer ein einzelnes Gesamtmittel ueber alle drei Faelle.
    """
    by_case: dict[str, list[dict]] = {}
    for entry in per_query:
        by_case.setdefault(entry["case"], []).append(entry)
    return {
        case: {
            "query_count": len(entries),
            "recall_at_10": round(sum(e["recall_at_10"] for e in entries) / len(entries), 4),
            "ndcg_at_10": round(sum(e["ndcg_at_10"] for e in entries) / len(entries), 4),
            "mrr": round(sum(e["reciprocal_rank"] for e in entries) / len(entries), 4),
        }
        for case, entries in sorted(by_case.items())
    }


def evaluate_combo(
    db_path: str,
    goldset: dict,
    relevance: dict[str, set[str]],
    chunk_fts_index: bool,
    chunk_fusion: bool,
    k: int = DEFAULT_K,
) -> dict:
    """Fuehrt alle Queries fuer EINE Kombination aus und aggregiert (Muster: #722).

    Derselbe vorbestehende FTS5-Komma-Defekt wie in #722 (``db._sanitize_fts5_query``
    haertet kein Komma ab, ``papers_fts``/``papers_trgm``/``chunk_fts`` MATCH
    bricht dann mit ``sqlite3.OperationalError`` ab) wird identisch behandelt:
    betroffene Query zaehlt als leerer Treffer, wird namentlich unter
    ``fts5_syntax_errors`` gefuehrt, kein Laufabbruch.
    """
    import sqlite3

    from academic_vault.retrieval import (
        compute_ndcg_at_k,
        compute_recall_at_k,
        compute_reciprocal_rank_at_k,
    )

    per_query: list[dict] = []
    fts5_syntax_errors: list[str] = []
    for query in goldset["queries"]:
        try:
            ranked = run_search(
                db_path,
                query["query"],
                k=k,
                chunk_fts_index=chunk_fts_index,
                chunk_fusion=chunk_fusion,
            )
        except sqlite3.OperationalError as exc:
            fts5_syntax_errors.append(query["query_id"])
            print(
                f"  [FTS5-Sanitize-Defekt, unabhaengig von #729] {query['query_id']}: {exc}",
                file=sys.stderr,
            )
            ranked = []
        relevant = sorted(relevance[query["query_id"]])
        reciprocal = compute_reciprocal_rank_at_k(ranked, relevant, k=k)
        per_query.append(
            {
                "query_id": query["query_id"],
                "case": query["case"],
                "recall_at_10": compute_recall_at_k(ranked, relevant, k=k),
                "ndcg_at_10": compute_ndcg_at_k(ranked, relevant, k=k),
                "reciprocal_rank": reciprocal,
                "retrieved": ranked,
            }
        )

    overall = {
        "recall_at_10": sum(r["recall_at_10"] for r in per_query) / len(per_query),
        "ndcg_at_10": sum(r["ndcg_at_10"] for r in per_query) / len(per_query),
        "mrr": sum(r["reciprocal_rank"] for r in per_query) / len(per_query),
    }
    return {
        "chunk_fts_index": chunk_fts_index,
        "chunk_fusion": chunk_fusion,
        "overall": overall,
        "by_case": _aggregate_by_case(per_query),
        "per_query": per_query,
        "fts5_syntax_errors": fts5_syntax_errors,
    }


def _delta(a: dict, b: dict) -> dict[str, float]:
    """b - a, je Metrik (positiv = b ist besser als a)."""
    return {m: round(b["overall"][m] - a["overall"][m], 4) for m in METRICS}


def compute_deltas(results: dict[str, dict]) -> dict[str, dict[str, float]]:
    """Trennt den Beitrag des Chunk-FTS-Index von dem der Chunk-Fusion (AC1).

    - ``chunk_fts_index_beitrag`` = Zwischenzustand A minus 'vorher' (Fusion
      bleibt in beiden Faellen auf Paper-Ebene -- isoliert NUR den Index).
    - ``chunk_fusion_beitrag`` = 'nachher' minus Zwischenzustand A (der
      Chunk-FTS-Index ist in beiden Faellen da -- isoliert NUR die
      Fusionsgranularitaet).
    - ``gesamt`` = 'nachher' minus 'vorher'. Nicht notwendig gleich der Summe
      der beiden Einzelbeitraege (Interaktionseffekte moeglich, Muster #722).
    """
    return {
        "chunk_fts_index_beitrag": _delta(results["vorher"], results["zwischenzustand_a"]),
        "chunk_fusion_beitrag": _delta(results["zwischenzustand_a"], results["nachher"]),
        "gesamt": _delta(results["vorher"], results["nachher"]),
    }


def compute_deltas_by_case(results: dict[str, dict]) -> dict[str, dict[str, dict[str, float]]]:
    """Dieselben drei Beitraege wie :func:`compute_deltas`, aber je ``case`` (#790).

    Das Probe-Goldset aus #790 fuehrt seine vier Familien als eigene ``case``-
    Werte (``probe-gain``/``probe-crowding``/``probe-harm``/``probe-control``).
    Ein Gesamtmittel ueber 38 Queries verduennt einen Effekt, der bauartbedingt
    nur an 12 davon auftreten kann -- und ein Set, dessen Gewinn- und
    Schadensfaelle sich im Aggregat gegenseitig aufheben, saehe dort aus wie
    ein Nullbefund.
    """
    cases = sorted({case for result in results.values() for case in result.get("by_case", {})})

    def _case_delta(a: dict, b: dict, case: str) -> dict[str, float]:
        return {
            metric: round(b["by_case"][case][metric] - a["by_case"][case][metric], 4)
            for metric in METRICS
        }

    return {
        case: {
            "query_count": results["nachher"]["by_case"][case]["query_count"],
            "chunk_fts_index_beitrag": _case_delta(
                results["vorher"], results["zwischenzustand_a"], case
            ),
            "chunk_fusion_beitrag": _case_delta(
                results["zwischenzustand_a"], results["nachher"], case
            ),
            "gesamt": _case_delta(results["vorher"], results["nachher"], case),
        }
        for case in cases
    }


@contextmanager
def hermetic_goldset_db(goldset: dict, vectors: dict[str, list[float]], name: str = "goldset"):
    """Wegwerf-Vault-DB aus einem eingecheckten Fixture-Paar, Playback-Embedder aktiv.

    Kein Netzzugriff, kein ``VAULT_E5_LIVE_TEST=1``: die Vektoren kommen aus
    der Fixture, der Playback-Embedder erfuellt dasselbe Embedder-Protokoll
    (``embed_query``/``embed_documents``) wie das echte Modell (siehe
    ``run_retrieval_chunk_goldset.py``).

    ``VAULT_EMBEDDING_MODEL`` wird zusaetzlich zum Cache-Key gesetzt (PR-Review
    zu #732): ``server._vec0_search`` ruft ``get_embedder()`` OHNE ``model_id``
    auf, die also ueber ``DEFAULT_MODEL_ID`` aufloest -- seit #732 (bge-m3)
    nicht mehr dieselbe ID wie ``embedder.model_id`` (die Chunk-Goldsets sind
    e5-small). Ohne den Env-Override traefe der Cache nie, ``get_embedder()``
    versuchte bge-m3 zu laden (im Testlauf geblockt) und der Lauf misste
    FTS5-only.

    In #790 herausgezogen, weil inzwischen drei Aufrufer denselben Aufbau
    brauchen: Qualitaetsablation, Diagnoseblock (#789) und die
    Probe-Vorbedingungspruefung im Goldset-Generator.
    """
    import tempfile

    from academic_vault import embedding_model

    doc_titles = {d["doc_id"]: d["title"] for d in goldset["documents"]}
    chunk_vectors = {c["chunk_id"]: vectors[c["chunk_id"]] for c in goldset["chunks"]}
    embedding_texts = {c["chunk_id"]: c["embedding_text"] for c in goldset["chunks"]}
    embedder = build_playback_embedder(goldset, vectors)

    with tempfile.TemporaryDirectory(prefix=f"{name}-") as tmp:
        db_path = build_db(
            Path(tmp), name, goldset, doc_titles, chunk_vectors, embedding_texts, trigram=True
        )
        prior_cache = dict(embedding_model._EMBEDDER_CACHE)
        embedding_model._EMBEDDER_CACHE[embedder.model_id] = embedder
        prior_env_model = os.environ.get("VAULT_EMBEDDING_MODEL")
        os.environ["VAULT_EMBEDDING_MODEL"] = embedder.model_id
        try:
            yield db_path
        finally:
            embedding_model._EMBEDDER_CACHE.clear()
            embedding_model._EMBEDDER_CACHE.update(prior_cache)
            if prior_env_model is None:
                os.environ.pop("VAULT_EMBEDDING_MODEL", None)
            else:
                os.environ["VAULT_EMBEDDING_MODEL"] = prior_env_model


def run_quality_ablation(
    goldset: dict, vectors: dict[str, list[float]], k: int = DEFAULT_K
) -> dict:
    """AC1/AC2: die drei Zustaende gegen das #708-Goldset, hermetisch."""
    doc_titles = {d["doc_id"]: d["title"] for d in goldset["documents"]}
    relevance = build_paper_relevance(goldset)

    with hermetic_goldset_db(goldset, vectors, name="ablation-729") as db_path:
        combos = {
            "vorher": {"chunk_fts_index": False, "chunk_fusion": False},
            "zwischenzustand_a": {"chunk_fts_index": True, "chunk_fusion": False},
            "nachher": {"chunk_fts_index": True, "chunk_fusion": True},
        }
        results = {
            name: evaluate_combo(db_path, goldset, relevance, k=k, **flags)
            for name, flags in combos.items()
        }

    deltas = compute_deltas(results)
    deltas_by_case = compute_deltas_by_case(results)
    regressions = {
        name: delta for name, delta in deltas.items() if any(v < 0 for v in delta.values())
    }
    return {
        "k": k,
        "chunk_count": len(goldset["chunks"]),
        "query_count": len(goldset["queries"]),
        "paper_count": len(doc_titles),
        "results": results,
        "deltas": deltas,
        "deltas_by_case": deltas_by_case,
        "regressions": regressions,
    }


# ---------------------------------------------------------------------------
# Nullbefund-Diagnose (Issue #789): mechanistische Nachrechnung je Query
# gegen die ECHTEN Produktionsfunktionen -- nicht gegen den 'vorher'/
# Zwischenzustand-A-Shim oben (der historisches Verhalten reimplementiert),
# sondern gegen exakt den Pfad, den 'nachher' (server.search_papers)
# tatsaechlich durchlaeuft: papers_fts/papers_trgm als lexikalische
# Kandidatenquelle, _attach_chunk_to_fts_hit fuer den Chunk-Lookup, der
# echte chunk-level _vec0_search fuer die Vektorseite.
# ---------------------------------------------------------------------------
def diagnose_query(db_path: str, query: str, k: int = DEFAULT_K) -> dict:
    """Diagnoseblock fuer EINE Query (Issue #789).

    Felder:

    - ``papers_fts_hit_count``/``papers_trgm_hit_count``: die beiden
      lexikalischen Quellen GETRENNT gezaehlt (``_papers_fts_hits`` oben
      mischt beide bereits fuer die Kandidatenliste -- hier bewusst
      aufgespalten, weil der #789-Befund lautet, dass ``papers_trgm`` NIE
      beitraegt und ``papers_fts`` fast nie).
    - ``fts_hit_count``: kombiniert, identisch zur Kandidatenzahl, die die
      Fusion tatsaechlich sieht (``papers_fts_hit_count`` +
      ``papers_trgm_hit_count``).
    - ``fts_ranking``: Paper-IDs in der Reihenfolge von ``_papers_fts_hits``
      (Rang 1 zuerst).
    - ``attached_chunk``: je Paper-ID der von ``server._attach_chunk_to_fts_hit``
      (#727) zugeordnete Chunk, ``None`` bei synthetischem Schluessel
      ``fts-paper::<pid>`` (kein lexikalisch treffender Chunk gefunden).
    - ``vec_paper_rank``/``vec_chunk_rank``: 1-basierte Raenge aus dem echten
      chunk-level ``server._vec0_search`` -- Paper-Rang ist der Rang des
      ERSTEN (naechsten) Chunks je Paper, Chunk-Rang je einzelnem Chunk.
    - ``attach_equals_vec_best``: je Paper-ID, ob der von
      ``_attach_chunk_to_fts_hit`` als FUSIONSSCHLUESSEL zugeordnete Chunk mit
      dem vektoriell besten Chunk desselben Papers uebereinstimmt -- also ob
      derselbe Chunk aus beiden Quellen kommt und den kombinierten RRF-Rang
      bekommt. Bleibt bei fehlgeschlagenem lexikalischem Chunk-Lookup auch
      nach dem #791-Fix ``False``: der Fix uebernimmt dort Text und Fundstelle
      des Vektor-Chunks, aber bewusst nicht dessen ``chunk_id`` (sonst
      entstuende eine chunk-level Ko-Okkurrenz, die es nicht gibt -- siehe
      ``server._attach_chunk_to_fts_hit``). ``False`` heisst hier also
      unveraendert: kein Hybrid-Rang fuer diesen Chunk, nicht "kein
      Chunk-Text".
    - ``min_score_gap_at_k``: kleinster Abstand zwischen zwei aufeinander-
      folgenden ``rrf_score``-Werten in den fusionierten Top-``k`` -- nahe 0
      markiert einen Tie, Vorbedingung fuer Folge-Issue 2 (nichtdeterministischer
      Tie-Break in ``reciprocal_rank_fusion`` bei exakt gleichem Score).
    - ``fts5_syntax_error``: derselbe vorbestehende Komma-Defekt wie in
      #722/#729 (``str(exc)`` statt Laufabbruch); alle uebrigen Felder bleiben
      dann auf ihrem Leerwert.
    """
    import sqlite3

    from academic_vault import server as _server
    from academic_vault.db import VaultDB
    from academic_vault.retrieval import reciprocal_rank_fusion

    sanitized = _server._sanitize_fts5_query(query)
    result: dict = {
        "query": query,
        "sanitized_query": sanitized,
        "papers_fts_hit_count": 0,
        "papers_trgm_hit_count": 0,
        "fts_hit_count": 0,
        "fts_ranking": [],
        "attached_chunk": {},
        "vec_paper_rank": {},
        "vec_chunk_rank": {},
        "attach_equals_vec_best": {},
        "min_score_gap_at_k": None,
        "fts5_syntax_error": None,
    }
    if not sanitized:
        return result

    _server._ensure_schema_for_read(db_path)
    conn = VaultDB._open(db_path)
    try:
        try:
            exact = _server._fts_exact_hits(conn, sanitized, None, k)
            trigram_rows = _server._fts_trigram_hits(conn, sanitized, None, k)
        except sqlite3.OperationalError as exc:
            # Fruehausstieg VOR der vec0-Beschaffung (bewusst, unveraendert seit
            # #789): ein Query-Syntaxdefekt soll 'vec_paper_rank'/'vec_chunk_rank'
            # nicht befuellen -- die Diagnose bricht denselben lexikalischen
            # Fehler nach, den auch server.search_papers fuer diese Query
            # geworfen haette, bevor der vec0-Pfad ueberhaupt zum Zug kaeme.
            result["fts5_syntax_error"] = str(exc)
            return result

        seen = {r["paper_id"] for r in exact}
        trigram_extra = [row for row in trigram_rows if row["paper_id"] not in seen]
        result["papers_fts_hit_count"] = len(exact)
        result["papers_trgm_hit_count"] = len(trigram_extra)

        fts_results = exact + trigram_extra
        result["fts_hit_count"] = len(fts_results)
        result["fts_ranking"] = [r["paper_id"] for r in fts_results]

        # Vec0-Beschaffung VOR dem FTS-Chunk-Attach (Issue #791, spiegelt die
        # Reihenfolge in server.search_papers): 'best_chunk_per_paper' dient
        # gleichzeitig als 'vec_best_by_paper'-Inhaltsfallback fuer
        # _attach_chunk_to_fts_hit, damit diese Diagnose exakt den reparierten
        # Produktionspfad nachrechnet statt eines Vor-#791-Zwischenstands.
        # Auf 'attached_chunk'/'attach_equals_vec_best' wirkt sich das NICHT
        # aus -- der Fusionsschluessel bleibt bei fehlgeschlagenem Lookup der
        # synthetische, nur Text/Fundstelle kommen aus dem Vektor-Chunk.
        vec_results = _server._vec0_search(db_path, query, k=k)
        best_chunk_per_paper: dict[str, dict] = {}
        for idx, r in enumerate(vec_results):
            pid, cid = r["paper_id"], r["chunk_id"]
            result["vec_chunk_rank"][cid] = idx + 1
            if pid not in result["vec_paper_rank"]:
                result["vec_paper_rank"][pid] = idx + 1
                best_chunk_per_paper[pid] = r

        fts_chunk_results = []
        for r in fts_results:
            attached = _server._attach_chunk_to_fts_hit(
                conn, r, sanitized, vec_best_by_paper=best_chunk_per_paper
            )
            chunk_id = attached["chunk_id"]
            is_synthetic = chunk_id.startswith("fts-paper::")
            result["attached_chunk"][attached["paper_id"]] = None if is_synthetic else chunk_id
            fts_chunk_results.append(attached)
    finally:
        conn.close()

    for pid, attached_cid in result["attached_chunk"].items():
        best = best_chunk_per_paper.get(pid)
        best_chunk_id = best["chunk_id"] if best is not None else None
        result["attach_equals_vec_best"][pid] = (
            attached_cid is not None and best_chunk_id is not None and attached_cid == best_chunk_id
        )

    fused = reciprocal_rank_fusion(vec_results, fts_chunk_results, k=60, top_n=k)
    scores = [entry["rrf_score"] for entry in fused]
    gaps = [scores[i] - scores[i + 1] for i in range(len(scores) - 1)]
    result["min_score_gap_at_k"] = min(gaps) if gaps else None
    return result


def _diagnostics_by_case(per_query: list[dict]) -> dict[str, dict]:
    """Aggregiert den Diagnoseblock nach ``case`` (Issue #789-Task, analog zu
    :func:`_aggregate_by_case`)."""
    by_case: dict[str, list[dict]] = {}
    for entry in per_query:
        by_case.setdefault(entry["case"], []).append(entry)
    result: dict[str, dict] = {}
    for case, entries in sorted(by_case.items()):
        non_error = [e for e in entries if e["fts5_syntax_error"] is None]
        result[case] = {
            "query_count": len(entries),
            "fts5_syntax_errors": len(entries) - len(non_error),
            "queries_with_any_fts_hit": sum(1 for e in non_error if e["fts_hit_count"] > 0),
            "queries_with_papers_fts_hit": sum(
                1 for e in non_error if e["papers_fts_hit_count"] > 0
            ),
            "queries_with_papers_trgm_hit": sum(
                1 for e in non_error if e["papers_trgm_hit_count"] > 0
            ),
        }
    return result


def run_diagnostics(goldset: dict, vectors: dict[str, list[float]], k: int = DEFAULT_K) -> dict:
    """Diagnoseblock fuer das gesamte Goldset (Issue #789).

    Baut dieselbe hermetische Wegwerf-DB wie :func:`run_quality_ablation`
    (Playback-Embedder aus der eingecheckten #708-Fixture, kein Netzzugriff)
    und ruft :func:`diagnose_query` je Query gegen die reale Produktions-DB
    auf. ``--goldset``/``--vectors`` (siehe ``main()``) steuern, welches
    Fixture-Paar hier einlaeuft -- Default bleibt das bestehende #708-Set.
    """
    with hermetic_goldset_db(goldset, vectors, name="diagnostics-789") as db_path:
        per_query = [
            {
                **diagnose_query(db_path, q["query"], k=k),
                "query_id": q["query_id"],
                "case": q["case"],
            }
            for q in goldset["queries"]
        ]

    non_error = [q for q in per_query if q["fts5_syntax_error"] is None]
    summary = {
        "query_count": len(per_query),
        "fts5_syntax_errors": [
            q["query_id"] for q in per_query if q["fts5_syntax_error"] is not None
        ],
        "queries_with_any_fts_hit": sum(1 for q in non_error if q["fts_hit_count"] > 0),
        "queries_with_papers_fts_hit": sum(1 for q in non_error if q["papers_fts_hit_count"] > 0),
        "queries_with_papers_trgm_hit": sum(1 for q in non_error if q["papers_trgm_hit_count"] > 0),
        "by_case": _diagnostics_by_case(per_query),
    }
    return {"per_query": per_query, "summary": summary}


# ---------------------------------------------------------------------------
# AC3: Index-Groesse und Suchlatenz an einem Vault mit >=50 Papern
# ---------------------------------------------------------------------------
class _DeterministicEmbedder:
    """Seed-basierter Fake-Embedder fuer AC3 (kein Modell, kein Netzzugriff).

    Index-Groesse und Suchlatenz haengen von Text-/Chunk-VOLUMEN und der
    SQL-/vec0-Mechanik ab, nicht von der semantischen Qualitaet der Vektoren
    -- ein deterministischer Hash-Vektor ist fuer diese Messung ausreichend
    und macht AC3 vollstaendig hermetisch. Fuer AC1/AC2 (Retrieval-QUALITAET)
    wird stattdessen die echte #708-Fixture ueber ``build_playback_embedder``
    verwendet, siehe :func:`run_quality_ablation`.
    """

    model_id = "deterministic-fake-729"

    def __init__(self, dim: int = 384, seed: int = AC3_SEED) -> None:
        self.dim = dim
        self._seed = seed

    def _vector(self, text: str) -> list[float]:
        from academic_vault.embedding_model import l2_normalize

        digest = hashlib.sha256(f"{self._seed}:{text}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        raw = [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
        return l2_normalize(raw)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


# Domaenen-flavourtes, aber bedeutungsloses Vokabular: nur Volumen und
# Wortwiederholung zaehlen fuer FTS5-/Trigram-Treffer, nicht der Inhalt.
_AC3_WORD_BANK: tuple[str, ...] = (
    "governance",
    "compliance",
    "oversight",
    "framework",
    "audit",
    "policy",
    "pipeline",
    "deployment",
    "infrastructure",
    "provisioning",
    "resilience",
    "observability",
    "telemetry",
    "incident",
    "mitigation",
    "remediation",
    "stakeholder",
    "accountability",
    "transparency",
    "regulation",
    "assessment",
    "benchmark",
    "throughput",
    "latency",
    "scalability",
    "architecture",
    "orchestration",
    "automation",
    "continuous",
    "integration",
    "delivery",
    "reliability",
    "availability",
    "vulnerability",
    "encryption",
    "authentication",
    "authorization",
    "monitoring",
    "escalation",
    "documentation",
)

# Feste Query-Stichprobe fuer die Latenzmessung: Woerter aus dem Vokabular
# oben, garantiert reale FTS5-/Trigram-/Vektor-Treffer im Korpus (anders als
# Goldset-Queries auf einem inhaltlich unverwandten Vault).
AC3_QUERIES: tuple[str, ...] = (
    "governance framework",
    "compliance audit",
    "incident mitigation",
    "deployment pipeline",
    "observability telemetry",
    "stakeholder accountability",
    "scalability architecture",
    "vulnerability remediation",
    "continuous delivery",
    "authentication authorization",
    "documentation onboarding",
    "resilience oversight",
)


def _synthetic_paper_pages(rng: random.Random, n_pages: int) -> list[tuple[int, str]]:
    """Baut ``n_pages`` seitenweise Texte aus dem Vokabular (bedeutungslos, AC3)."""
    pages: list[tuple[int, str]] = []
    for page_no in range(1, n_pages + 1):
        n_sentences = rng.randint(4, 7)
        sentences = []
        for _ in range(n_sentences):
            n_words = rng.randint(10, 18)
            words = [rng.choice(_AC3_WORD_BANK) for _ in range(n_words)]
            sentences.append(" ".join(words).capitalize() + ".")
        pages.append((page_no, " ".join(sentences)))
    return pages


def build_ac3_corpus(n_papers: int = AC3_PAPER_COUNT, seed: int = AC3_SEED) -> list[dict]:
    """Synthetischer Korpus fuer AC3: mindestens ``n_papers`` Paper mit mehreren Seiten.

    >>> corpus = build_ac3_corpus(n_papers=5)
    >>> len(corpus)
    5
    >>> all(len(p["pages"]) >= 2 for p in corpus)
    True
    """
    rng = random.Random(seed)
    corpus = []
    for i in range(n_papers):
        n_pages = rng.randint(2, 5)
        corpus.append(
            {
                "paper_id": f"ac3-paper-{i:03d}",
                "title": f"Synthetic Governance Paper {i:03d}",
                "pages": _synthetic_paper_pages(rng, n_pages),
            }
        )
    return corpus


def _build_ac3_db(tmpdir: Path, name: str, corpus: list[dict], with_chunk_fts: bool) -> str:
    """Baut eine Wegwerf-Vault-DB aus dem AC3-Korpus (echtes Chunking, Fake-Vektoren)."""
    from academic_vault.chunking import approximate_token_count, chunk_pages
    from academic_vault.db import VaultDB
    from academic_vault.embedding_model import DEFAULT_MODEL_ID, serialize_f32

    db_path = str(tmpdir / f"{name}.db")
    db = VaultDB(db_path)
    db.init_schema()
    embedder = _DeterministicEmbedder()
    db.register_embedding_inventory(DEFAULT_MODEL_ID, embedder.dim)

    for paper in corpus:
        db.add_paper(
            paper_id=paper["paper_id"],
            csl_json=json.dumps({"title": paper["title"], "type": "article-journal"}),
        )
        chunks = chunk_pages(paper["pages"], token_counter=approximate_token_count)
        for chunk in chunks:
            vector = embedder.embed_documents([chunk.embedding_text])[0]
            db.add_chunk_embedding(
                paper_id=paper["paper_id"],
                chunk_text=chunk.chunk_text,
                context_sentence=chunk.context_sentence,
                embedding_text=chunk.embedding_text,
                embedding_vector=serialize_f32(vector),
                section_title=chunk.section_title,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )

    if not with_chunk_fts:
        # Bildet den Zustand VOR #726 nach: Tabelle + Trigger existierten
        # nicht. Drop NACH der Befuellung (die Insert-Trigger duerfen beim
        # Aufbau nicht brechen, Muster wie papers_trgm in #722).
        conn = VaultDB._open(db_path)
        try:
            conn.execute("DROP TRIGGER IF EXISTS chunk_ai")
            conn.execute("DROP TRIGGER IF EXISTS chunk_ad")
            conn.execute("DROP TRIGGER IF EXISTS chunk_au")
            conn.execute("DROP TABLE IF EXISTS chunk_fts")
            conn.commit()
        finally:
            conn.close()

    # VACUUM in JEDEM Fall (PR-Review-Fund: vorher nur im with_chunk_fts=False-
    # Zweig, das machte den Groessenvergleich asymmetrisch -- eine kompaktierte
    # gegen eine unkompaktierte DB). Die Dateigroesse soll den tatsaechlichen
    # Platzbedarf zeigen, nicht den durch SQLite freigegebenen, aber nicht
    # zurueckgegebenen Space, UND beide Varianten muessen gleich behandelt
    # werden, damit die Differenz ausschliesslich auf chunk_fts zurueckgeht.
    conn = VaultDB._open(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    finally:
        conn.close()
    return db_path


def measure_index_growth(tmpdir: Path, corpus: list[dict]) -> dict:
    """AC3: Dateigroesse mit vs. ohne ``chunk_fts``, identischer Chunk-Bestand."""
    without_path = _build_ac3_db(tmpdir, "without-chunk-fts", corpus, with_chunk_fts=False)
    with_path = _build_ac3_db(tmpdir, "with-chunk-fts", corpus, with_chunk_fts=True)
    size_without = os.path.getsize(without_path)
    size_with = os.path.getsize(with_path)
    growth = size_with - size_without
    return {
        "bytes_without_chunk_fts": size_without,
        "bytes_with_chunk_fts": size_with,
        "growth_bytes": growth,
        "growth_pct": round(growth / size_without * 100, 2) if size_without else None,
        "db_path_with_chunk_fts": with_path,
    }


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50_ms": round(statistics.median(ordered) * 1000, 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 3),
        "mean_ms": round(statistics.fmean(ordered) * 1000, 3),
        "n": len(ordered),
    }


def measure_search_latency(
    db_path: str, queries: Sequence[str] = AC3_QUERIES, k: int = DEFAULT_K, repeats: int = 3
) -> dict:
    """AC3: p50/p95-Suchlatenz je Zustand am >=50-Paper-Vault, Reranker aus.

    Reranker deaktiviert (:func:`_env_guard`): gemessen wird die Kosten von
    Index und Fusion, nicht die des (unveraenderten, in #722 separat
    vermessenen) Rerankers.
    """
    from academic_vault import embedding_model
    from academic_vault import server as _server

    embedder = _DeterministicEmbedder()
    prior_cache = dict(embedding_model._EMBEDDER_CACHE)
    embedding_model._EMBEDDER_CACHE[embedder.model_id] = embedder
    prior_env_model = os.environ.get("VAULT_EMBEDDING_MODEL")
    os.environ["VAULT_EMBEDDING_MODEL"] = embedder.model_id
    try:
        timings: dict[str, list[float]] = {"vorher": [], "zwischenzustand_a": [], "nachher": []}
        with _env_guard():
            for _ in range(repeats):
                for q in queries:
                    t0 = time.perf_counter()
                    search_papers_paper_level(db_path, q, k, attach_chunk=False)
                    timings["vorher"].append(time.perf_counter() - t0)

                    t0 = time.perf_counter()
                    search_papers_paper_level(db_path, q, k, attach_chunk=True)
                    timings["zwischenzustand_a"].append(time.perf_counter() - t0)

                    t0 = time.perf_counter()
                    _server.search_papers(db_path, q, k=k, rerank=True)
                    timings["nachher"].append(time.perf_counter() - t0)
    finally:
        embedding_model._EMBEDDER_CACHE.clear()
        embedding_model._EMBEDDER_CACHE.update(prior_cache)
        if prior_env_model is None:
            os.environ.pop("VAULT_EMBEDDING_MODEL", None)
        else:
            os.environ["VAULT_EMBEDDING_MODEL"] = prior_env_model

    return {state: _percentiles(vals) for state, vals in timings.items()}


def run_cost_measurement(n_papers: int = AC3_PAPER_COUNT) -> dict:
    """AC3 komplett: Korpus bauen, Index-Groesse + Suchlatenz messen."""
    import tempfile

    from academic_vault.chunking import approximate_token_count, chunk_pages

    corpus = build_ac3_corpus(n_papers=n_papers)
    chunk_counts = [
        len(chunk_pages(p["pages"], token_counter=approximate_token_count)) for p in corpus
    ]
    with tempfile.TemporaryDirectory(prefix="ablation-729-ac3-") as tmp:
        tmpdir = Path(tmp)
        growth = measure_index_growth(tmpdir, corpus)
        latency = measure_search_latency(growth["db_path_with_chunk_fts"])
    return {
        "paper_count": len(corpus),
        "chunk_count": sum(chunk_counts),
        "chunk_count_min": min(chunk_counts),
        "chunk_count_max": max(chunk_counts),
        "index_growth": {k: v for k, v in growth.items() if k != "db_path_with_chunk_fts"},
        "search_latency": latency,
    }


# ---------------------------------------------------------------------------
# Orchestrierung
# ---------------------------------------------------------------------------
def run_ablation(goldset: dict, vectors: dict[str, list[float]], k: int = DEFAULT_K) -> dict:
    quality = run_quality_ablation(goldset, vectors, k=k)
    diagnostics = run_diagnostics(goldset, vectors, k=k)
    cost = run_cost_measurement()
    return {"quality": quality, "diagnostics": diagnostics, "cost": cost}


def compare_against(report: dict, stored: dict, tolerance: float = 1e-9) -> list[str]:
    """Vergleicht einen frischen Lauf mit den eingecheckten Rohdaten (#790).

    Muster wie ``run_embedding_candidates_731.compare_against`` und
    ``run_hyde_multiquery_eval.compare_against``: gegattert wird nicht die
    QUALITAET (dafuer gibt es hier keine Schwelle), sondern die
    Deckungsgleichheit von Lauf und Report -- sonst altert der Report
    unbemerkt, sobald jemand am Suchpfad oder an der Fusion dreht. Die
    Vergleichsmechanik teilen sich alle drei ueber
    :func:`~scripts.eval.run_retrieval_chunk_goldset.diverged_per_query` und
    :func:`~scripts.eval.run_retrieval_chunk_goldset.diverged_mapping`.

    Der Kostenblock (``cost``) bleibt bewusst aussen vor: Latenz und
    Dateigroessen haengen an der Maschine und waeren als Gatter nur eine Quelle
    roter CI-Laeufe ohne Aussage -- dieselbe Abgrenzung wie in #731.

    WICHTIG fuer den Vergleich von ``per_query.retrieved``: das Goldset darf
    keine exakt gleichen ``rrf_score``-Werte enthalten. ``reciprocal_rank_fusion``
    iteriert ueber ein ``set`` von ``chunk_id``s, und die Chunk-IDs sind UUID4,
    die bei jedem Aufbau der Wegwerf-DB neu vergeben werden -- bei einem
    Gleichstand ist die Reihenfolge deshalb von Lauf zu Lauf verschieden, und
    zwar auch bei gepinntem ``PYTHONHASHSEED`` (Folge-Issue #792; das Pinnen
    hilft nur, wenn die Schluessel selbst konstant sind, was sie hier nicht
    sind). Das #790-Probe-Goldset ist deshalb tie-frei konstruiert, geprueft in
    ``tests/test_issue_790_probe_goldset.py::test_ranking_is_reproducible_across_runs``.
    """
    problems: list[str] = []

    def _compare_block(fresh_block: dict, old_block: dict, prefix: str) -> None:
        fresh_quality = fresh_block["quality"]
        old_quality = old_block.get("quality", {})
        for state, fresh in fresh_quality["results"].items():
            old = old_quality.get("results", {}).get(state)
            if old is None:
                problems.append(
                    f"{prefix}quality.results.{state}: fehlt in den eingecheckten Rohdaten"
                )
                continue
            scope = f"{prefix}quality.results.{state}"
            problems.extend(
                diverged_metrics(
                    fresh["overall"], old.get("overall"), f"{scope}.overall", tolerance=tolerance
                )
            )
            problems.extend(
                diverged_per_query(fresh["per_query"], old.get("per_query"), f"{scope}.per_query")
            )
            problems.extend(
                diverged_mapping(fresh["by_case"], old.get("by_case"), f"{scope}.by_case")
            )
        for block in ("deltas", "deltas_by_case"):
            if fresh_quality.get(block) != old_quality.get(block):
                problems.append(f"{prefix}quality.{block}: gemessen {fresh_quality.get(block)!r}")
        if "diagnostics" in fresh_block:
            fresh_summary = fresh_block["diagnostics"]["summary"]
            old_summary = old_block.get("diagnostics", {}).get("summary")
            if fresh_summary != old_summary:
                problems.append(
                    f"{prefix}diagnostics.summary: weicht von den eingecheckten Rohdaten ab"
                )
        elif "diagnostics" in old_block:
            # Dieselbe Asymmetrie wie beim baseline-Block unten: laesst jemand
            # --skip-diagnostics in den CI-Schritt einlaufen, altert der im
            # Report zitierte Diagnoseblock ab da unbemerkt weiter.
            problems.append(
                f"{prefix}diagnostics: die eingecheckten Rohdaten fuehren einen "
                "Diagnoseblock, dieser Lauf nicht -- --skip-diagnostics ist gesetzt"
            )

    _compare_block(report, stored, "")
    if "baseline" in report:
        _compare_block(report["baseline"], stored.get("baseline", {}), "baseline.")
    elif "baseline" in stored:
        # Umgekehrter Fall, sonst stillschweigend gruen: die Rohdaten fuehren
        # einen Regressionsanker, der frische Lauf nicht. Wer
        # --baseline-goldset/--baseline-vectors aus dem CI-Schritt streicht,
        # laesst damit die Haelfte der eingecheckten Daten ungeprueft altern.
        problems.append(
            "baseline: die eingecheckten Rohdaten fuehren einen Regressionsanker, "
            "dieser Lauf nicht -- --baseline-goldset/--baseline-vectors fehlen"
        )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--goldset", type=Path, default=GOLDSET_PATH, help="Goldset-JSON (Default: #708-Set)."
    )
    parser.add_argument(
        "--vectors", type=Path, default=VECTORS_PATH, help="Vektor-JSON (Default: #708-Set)."
    )
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--skip-cost", action="store_true", help="AC3 (Index/Latenz) auslassen.")
    parser.add_argument(
        "--skip-diagnostics",
        action="store_true",
        help="Nullbefund-Diagnoseblock (Issue #789) auslassen.",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional: Report als JSON schreiben."
    )
    parser.add_argument(
        "--check-against",
        type=Path,
        default=None,
        help="Exit 1 bei Abweichung von diesen Rohdaten (Kostenblock ausgenommen).",
    )
    parser.add_argument(
        "--baseline-goldset",
        type=Path,
        default=None,
        help=(
            "Zweites Goldset, das im selben Report unter 'baseline' mitlaeuft "
            "(Issue #790: das #708-Set als Regressionsanker neben der Hauptmessung)."
        ),
    )
    parser.add_argument(
        "--baseline-vectors",
        type=Path,
        default=None,
        help="Vektor-JSON zu --baseline-goldset.",
    )
    args = parser.parse_args(argv)
    if bool(args.baseline_goldset) != bool(args.baseline_vectors):
        parser.error("--baseline-goldset und --baseline-vectors nur gemeinsam")

    goldset = load_goldset(args.goldset)
    try:
        verify_manifest(goldset)
    except ManifestMismatchError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        vectors_raw = load_vectors(args.vectors)
        vectors: dict[str, list[float]] = dict(vectors_raw)

        quality = run_quality_ablation(goldset, vectors, k=args.k)
        report: dict = {"goldset": str(args.goldset), "quality": quality}
        if not args.skip_diagnostics:
            report["diagnostics"] = run_diagnostics(goldset, vectors, k=args.k)

        if args.baseline_goldset is not None:
            baseline_goldset = load_goldset(args.baseline_goldset)
            try:
                verify_manifest(baseline_goldset)
            except ManifestMismatchError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            baseline_vectors = dict(load_vectors(args.baseline_vectors))
            baseline: dict = {
                "goldset": str(args.baseline_goldset),
                "quality": run_quality_ablation(baseline_goldset, baseline_vectors, k=args.k),
            }
            if not args.skip_diagnostics:
                baseline["diagnostics"] = run_diagnostics(
                    baseline_goldset, baseline_vectors, k=args.k
                )
            report["baseline"] = baseline

        if not args.skip_cost:
            report["cost"] = run_cost_measurement()

        text = json.dumps(report, indent=2, ensure_ascii=False)
        print(text)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
            print(f"Report geschrieben: {args.out}", file=sys.stderr)

        if args.check_against is not None:
            stored = json.loads(args.check_against.read_text(encoding="utf-8"))
            problems = compare_against(report, stored)
            if problems:
                print(f"Lauf und {args.check_against} laufen auseinander:", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            print(f"Deckungsgleich mit {args.check_against}.", file=sys.stderr)
        return 0
    except Exception as exc:
        # Aeusserster Fang: beide ManifestMismatchError-Stellen (Haupt- und
        # Baseline-Goldset) sind oben bereits spezifisch behandelt (#798).
        print(f"Retrieval-Ablation (#729): unerwarteter Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
