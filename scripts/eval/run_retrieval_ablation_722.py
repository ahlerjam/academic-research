#!/usr/bin/env python3
"""Ablationslauf: wirken #701/#702/#703/#714 zusammen auf die Hybrid-Suche? (#722)

Vier Retrieval-Aenderungen sind unabhaengig voneinander gemerged:

- **#701** (PR #771): Kontextsatz vor dem Chunk-Text traegt jetzt Paper-Titel
  (``chunking.PaperMeta`` -> ``default_context_sentence``) statt reiner
  Sektions-/Seitenangabe.
- **#702** (PR #768): ``server.search_papers(..., rerank=True)`` ergaenzt
  fehlenden Reranker-Text fuer FTS5-only-Treffer (``_fill_missing_reranker_text``)
  und ruft ``apply_reranker`` mit der rohen statt der FTS5-sanitisierten Query.
- **#703** (PR #767): ``papers_trgm`` (Trigram-Index) findet Komposita-Teilworte,
  die ``papers_fts`` (unicode61) nicht trifft.
- **#714** (PR #772): der lokale ``bge-reranker-v2-m3``-Fallback laeuft jetzt
  per Default, sobald keine Cloud-Reranker-Keys gesetzt sind.

Jede fuer sich plausibel, aber keine gegen den Endzustand gemessen. Dieser
Harness misst alle vier gemeinsam UND einzeln (Leave-one-out ab dem aktuellen
Stand) gegen das Chunk-Goldset aus #708
(``tests/fixtures/retrieval_goldset_chunks_708/``), aggregiert auf Paper-Ebene:
ein Paper gilt als relevant, wenn es mindestens einen relevanten Chunk der
Query enthaelt. Das ist Konsum der bestehenden #708-Fixture (Chunks, Anker,
Relevanzurteile) auf einer anderen Auswertungseinheit -- keine
Goldset-Erweiterung (Out-of-Scope-Grenze von #722).

Gemessen wird die ECHTE Pipeline (keine Nachbildung): FTS5 + Vektor-KNN + RRF
+ ``apply_reranker`` laufen ueber ``academic_vault.server.search_papers`` bzw.
(fuer den #702-'vor'-Zustand) ueber den in diesem Skript dokumentierten Shim
:func:`search_papers_pre_702`. Drei der vier "vor"-Zustaende sind KEIN Shim,
sondern echte Produktions-Stellschrauben:

- #701 'vor' = ``chunk_pages``/``default_context_sentence`` mit
  ``paper_meta=None`` (unveraenderter Produktionspfad ohne Metadaten). Die im
  #708-Goldset eingecheckten ``context_sentence``-Werte sind bereits dieser
  Zustand (das Set wurde 2026-08-07 gebaut, #701 landete 2026-08-08) -- fuer
  'vor' werden die Fixture-Vektoren direkt wiederverwendet (hermetisch, kein
  Modell-Download). Fuer 'nach' baut dieses Skript den Kontextsatz aus
  ``PaperMeta(title=...)`` neu und embeddet ihn live neu.
- #703 'vor' = ``DROP TABLE papers_trgm`` auf der Wegwerf-DB, NACH dem
  Befuellen (die Insert-Trigger schreiben ``papers_trgm`` mit fort; sie duerfen
  beim Aufbau nicht brechen). ``server._fts_trigram_hits`` faengt die fehlende
  Tabelle ab und liefert ``[]`` -- exakt das reale Verhalten eines
  Bestands-Vaults ohne die #703-Migration.
- #714 'vor' = Env-Var ``VAULT_RERANK_LOCAL_DISABLE`` gesetzt (der echte
  Opt-out-Schalter aus #714, PR #772).

Nur #702 hat keinen Produktions-Schalter mehr (der alte Pfad wurde ersetzt,
nicht konfigurierbar gemacht) -- dafuer gibt es den Shim
:func:`search_papers_pre_702`, dokumentiert und gegen das reale Verhalten des
Diffs (Commit 68f2ed8) in ``tests/test_issue_722_retrieval_ablation.py``
differenzial geprueft.

Nicht hermetisch (laedt e5-Tokenizer/-Modell und optional den lokalen
bge-reranker-v2-m3 -- analog ``scripts/eval/recall_at_k_model_ab.py``,
#375/#628, und ``scripts/eval/build_retrieval_chunk_goldset.py``, #708)::

    VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/run_retrieval_ablation_722.py

Modell und Tokenizer werden aus dem lokalen HuggingFace-Cache geladen, sofern
vorhanden (kein Download noetig, sobald einmal geladen).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Modell/Tokenizer sind bereits im lokalen Cache (~/.academic-research/models);
# ohne diese beiden Schalter macht jeder CrossEncoder-Aufruf einen HTTP-HEAD an
# huggingface.co, um auf Aenderungen zu pruefen -- bei 26 Queries x mehreren
# Flag-Kombinationen dominiert das die Laufzeit. Nur gesetzt, wenn noch nicht
# vom Aufrufer vorgegeben.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    GOLDSET_PATH,
    VECTORS_PATH,
    ManifestMismatchError,
    load_goldset,
    load_vectors,
    verify_manifest,
)

DEFAULT_K = 10
METRICS = ("recall_at_10", "ndcg_at_10", "mrr")

# Eine Zeile je Aenderung: (Flag-Name, Issue, PR, Kurzbeschreibung "nach").
CHANGES: tuple[tuple[str, int, int, str], ...] = (
    ("ctx_meta", 701, 771, "Kontextsatz traegt Paper-Titel"),
    ("fts_text_fix", 702, 768, "Reranker bekommt echten Chunk-/Abstract-Text"),
    ("trigram", 703, 767, "papers_trgm findet Komposita-Teilworte"),
    ("local_rerank", 714, 772, "lokaler bge-reranker-v2-m3 laeuft per Default"),
)
FLAG_NAMES = tuple(c[0] for c in CHANGES)


# ---------------------------------------------------------------------------
# Paper-Ebene-Aggregation (Konsum der #708-Fixture, keine Erweiterung)
# ---------------------------------------------------------------------------
def build_paper_relevance(goldset: dict) -> dict[str, set[str]]:
    """Query-ID -> Menge relevanter ``doc_id``s (>=1 relevanter Chunk).

    >>> gs = {
    ...     "chunks": [{"chunk_id": "d1#0", "doc_id": "d1"},
    ...                {"chunk_id": "d2#0", "doc_id": "d2"}],
    ...     "queries": [{"query_id": "q1", "relevant_chunk_ids": ["d1#0"]}],
    ... }
    >>> build_paper_relevance(gs) == {"q1": {"d1"}}
    True
    """
    chunk_to_doc = {c["chunk_id"]: c["doc_id"] for c in goldset["chunks"]}
    return {
        q["query_id"]: {chunk_to_doc[cid] for cid in q["relevant_chunk_ids"]}
        for q in goldset["queries"]
    }


# ---------------------------------------------------------------------------
# #702-Shim: search_papers(rerank=True) VOR PR #768 / Commit 68f2ed8
# ---------------------------------------------------------------------------
def search_papers_pre_702(db_path: str, query: str, k: int = DEFAULT_K) -> list[dict]:
    """Rekonstruiert ``server.search_papers(..., rerank=True)`` vor #702.

    Zwei Unterschiede zum jetzigen Code (siehe Modul-Docstring):

    1. Kein Aufruf von ``server._fill_missing_reranker_text`` -- ein
       FTS5-only-Treffer behaelt sein rohes ``snippet`` (mit ``<b>``-Markup,
       auf ~10 Token gekuerzt) als einzige Textquelle statt Abstract/Chunk-Text.
    2. ``apply_reranker`` bekommt die FTS5-SANITISIERTE Query statt der rohen
       Nutzereingabe (der Vektorpfad bekam schon vor #702 die rohe Query --
       das war in Commit 68f2ed8 unveraendert).

    ``retrieval.apply_reranker`` selbst (inkl. seines HTML-Strip-Haertungs-
    fallbacks) ist NICHT Teil dieses Shims -- der Strip kam zwar im selben
    Commit wie #702, gehoert aber zur ``retrieval.py``-Haelfte des Diffs, die
    dieses Flag nicht abbildet (``retrieval.py`` ist ausserhalb der
    Ablations-Flags dieses Skripts; die anderen drei Aenderungen sind
    Produktions-Stellschrauben, #702 ist der einzige Shim). Die messbare
    Groesse ist die *Textquelle* und die *Query*, nicht das Markup-Stripping.
    """
    from academic_vault import server as _server
    from academic_vault.db import VaultDB
    from academic_vault.retrieval import apply_reranker, reciprocal_rank_fusion

    raw_query = query
    sanitized = _server._sanitize_fts5_query(query)
    if not sanitized:
        return []

    _server._ensure_schema_for_read(db_path)
    conn = VaultDB._open(db_path)
    try:
        fts_results = _server._fts_exact_hits(conn, sanitized, None, k)
        if len(fts_results) < k:
            seen = {r["paper_id"] for r in fts_results}
            for row in _server._fts_trigram_hits(conn, sanitized, None, k):
                if row["paper_id"] in seen:
                    continue
                fts_results.append(row)
                seen.add(row["paper_id"])
                if len(fts_results) >= k:
                    break
        # Chunk-Zuordnung (#727, wie server.search_papers): reciprocal_rank_fusion
        # schluesselt seit #727 auf 'chunk_id' statt 'paper_id' -- ohne diesen
        # Schritt fehlt jedem paper-level FTS5-Treffer der Schluessel und die
        # Fusion wirft KeyError. Kein #702-Verhalten (die Textquelle bleibt das
        # rohe Snippet, siehe Docstring), nur die Fusion muss mit dem aktuellen
        # Vertrag mithalten koennen.
        fts_chunk_results = [
            _server._attach_chunk_to_fts_hit(conn, r, sanitized) for r in fts_results
        ]
    finally:
        conn.close()

    fused = reciprocal_rank_fusion(
        _server._vec0_search(db_path, raw_query, k=k), fts_chunk_results, k=60, top_n=k
    )
    # PRE-#702: bewusst KEIN _fill_missing_reranker_text(db_path, fused).
    return apply_reranker(
        query=sanitized, candidates=fused, voyage_api_key=None, cohere_api_key=None
    )


# ---------------------------------------------------------------------------
# #701-Variante: Kontextsatz mit/ohne PaperMeta, live neu embedden
# ---------------------------------------------------------------------------
def build_ctx_meta_vectors(
    goldset: dict, doc_titles: dict[str, str]
) -> tuple[dict[str, str], dict[str, list[float]]]:
    """Baut fuer JEDEN Chunk den 'nach'-Kontextsatz (PaperMeta mit Titel) und

    embeddet ihn live neu. Gibt ``(chunk_id -> embedding_text, chunk_id ->
    vektor)`` zurueck. Nur die Chunk-Vektoren aendern sich durch #701 -- die
    Query-Vektoren bleiben identisch mit der eingecheckten #708-Fixture.
    """
    from academic_vault.chunking import PaperMeta, default_context_sentence, resolve_token_counter
    from academic_vault.embedding_model import E5SmallEmbedder
    from academic_vault.embeddings import build_contextual_embedding_text

    counter = resolve_token_counter()
    embedder = E5SmallEmbedder()

    embedding_texts: dict[str, str] = {}
    for chunk in goldset["chunks"]:
        meta = PaperMeta(title=doc_titles[chunk["doc_id"]])
        context_sentence = default_context_sentence(
            chunk["section_title"],
            chunk["chunk_index"],
            chunk["page_start"],
            chunk["page_end"],
            paper_meta=meta,
            token_counter=counter,
        )
        embedding_texts[chunk["chunk_id"]] = build_contextual_embedding_text(
            context_sentence, chunk["chunk_text"]
        )

    ids = list(embedding_texts.keys())
    vectors = embedder.embed_documents([embedding_texts[i] for i in ids])
    return embedding_texts, dict(zip(ids, vectors, strict=True))


# ---------------------------------------------------------------------------
# Wegwerf-Vault-DB je (ctx_meta, trigram)-Kombination
# ---------------------------------------------------------------------------
def build_db(
    tmpdir: Path,
    name: str,
    goldset: dict,
    doc_titles: dict[str, str],
    chunk_vectors: dict[str, list[float]],
    embedding_texts: dict[str, str],
    trigram: bool,
) -> str:
    """Baut eine Wegwerf-Vault-DB mit allen Papers/Chunks aus der Fixture.

    ``chunk_vectors``/``embedding_texts`` sind bereits fuer die gewuenschte
    #701-Variante (vor/nach) aufgeloest -- diese Funktion selbst kennt #701
    nicht.
    """
    from academic_vault.db import VaultDB
    from academic_vault.embedding_model import DEFAULT_MODEL_ID, serialize_f32

    db_path = str(tmpdir / f"{name}.db")
    db = VaultDB(db_path)
    db.init_schema()

    sources_by_doc: dict[str, list[str]] = {}
    for chunk in goldset["chunks"]:
        sources_by_doc.setdefault(chunk["doc_id"], []).append(chunk["chunk_text"])

    for doc_id, title in doc_titles.items():
        db.add_paper(
            paper_id=doc_id, csl_json=json.dumps({"title": title, "type": "article-journal"})
        )
        fulltext = " ".join(sources_by_doc.get(doc_id, []))
        if fulltext.strip():
            db.set_fulltext(doc_id, fulltext)

    db.register_embedding_inventory(DEFAULT_MODEL_ID, len(next(iter(chunk_vectors.values()))))

    id_map: dict[str, str] = {}
    for chunk in goldset["chunks"]:
        cid = chunk["chunk_id"]
        vault_id = db.add_chunk_embedding(
            paper_id=chunk["doc_id"],
            chunk_text=chunk["chunk_text"],
            context_sentence=chunk.get("context_sentence", ""),
            embedding_text=embedding_texts[cid],
            embedding_vector=serialize_f32(chunk_vectors[cid]),
        )
        id_map[vault_id] = cid

    if not trigram:
        conn = VaultDB._open(db_path)
        try:
            conn.execute("DROP TABLE IF EXISTS papers_trgm")
            conn.commit()
        finally:
            conn.close()

    return db_path


# ---------------------------------------------------------------------------
# Suche + Metrik je Flag-Kombination
# ---------------------------------------------------------------------------
def run_search(
    db_path: str, query: str, k: int, fts_text_fix: bool, local_rerank: bool
) -> list[str]:
    """Fuehrt EINE Suche ueber die gewuenschte Flag-Kombination aus.

    ``local_rerank`` steuert ``VAULT_RERANK_LOCAL_DISABLE`` (#714, echter
    Produktions-Schalter). ``fts_text_fix`` waehlt zwischen
    ``server.search_papers`` (aktueller Code) und dem #702-Shim.

    Cloud-Reranker-Keys (VOYAGE_API_KEY, COHERE_API_KEY) werden neutralisiert,
    um sicherzustellen, dass alle Arme denselben Reranker-Zustand haben
    (entweder Shim oder lokaler Fallback je nach Flags, nie Cloud).
    """
    from academic_vault.retrieval import ENV_LOCAL_RERANKER_DISABLE
    from academic_vault.server import search_papers

    prior_local = os.environ.get(ENV_LOCAL_RERANKER_DISABLE)
    prior_voyage = os.environ.pop("VOYAGE_API_KEY", None)
    prior_cohere = os.environ.pop("COHERE_API_KEY", None)
    try:
        if local_rerank:
            os.environ.pop(ENV_LOCAL_RERANKER_DISABLE, None)
        else:
            os.environ[ENV_LOCAL_RERANKER_DISABLE] = "1"

        if fts_text_fix:
            results = search_papers(db_path, query, k=k, rerank=True)
        else:
            results = search_papers_pre_702(db_path, query, k=k)
    finally:
        if prior_local is None:
            os.environ.pop(ENV_LOCAL_RERANKER_DISABLE, None)
        else:
            os.environ[ENV_LOCAL_RERANKER_DISABLE] = prior_local
        if prior_voyage is not None:
            os.environ["VOYAGE_API_KEY"] = prior_voyage
        if prior_cohere is not None:
            os.environ["COHERE_API_KEY"] = prior_cohere

    seen: list[str] = []
    for r in results:
        pid = r["paper_id"]
        if pid not in seen:
            seen.append(pid)
    return seen[:k]


def evaluate_combo(
    dbs: dict[tuple[bool, bool], str],
    goldset: dict,
    relevance: dict[str, set[str]],
    flags: dict[str, bool],
    k: int = DEFAULT_K,
) -> dict:
    """Fuehrt alle Queries fuer EINE Flag-Kombination aus und aggregiert.

    Ein Teil der #708-Queries enthaelt Kommas ("wie erkennt man frueh, dass
    ...") -- ``db._sanitize_fts5_query`` haertet FTS5-Sonderzeichen ab, aber
    NICHT das Komma, und ``papers_fts``/``papers_trgm`` MATCH bricht darauf
    mit ``sqlite3.OperationalError`` ab. Das ist ein vorbestehender
    Produktionsdefekt (ausserhalb der vier #722-Aenderungen, ``area/vault``
    ist geschuetzt -- kein Fix hier), keine Eigenschaft dieses Harness. Eine
    betroffene Query zaehlt als vollstaendiger Treffer-Ausfall (leere
    Trefferliste) und wird namentlich unter ``fts5_syntax_errors`` im Report
    gefuehrt, statt den Lauf abzubrechen oder die Query stillschweigend zu
    umgehen.
    """
    from academic_vault.retrieval import (
        compute_ndcg_at_k,
        compute_recall_at_k,
        compute_reciprocal_rank_at_k,
    )

    db_path = dbs[(flags["ctx_meta"], flags["trigram"])]
    per_query: list[dict] = []
    fts5_syntax_errors: list[str] = []
    for query in goldset["queries"]:
        try:
            ranked = run_search(
                db_path,
                query["query"],
                k=k,
                fts_text_fix=flags["fts_text_fix"],
                local_rerank=flags["local_rerank"],
            )
        except sqlite3.OperationalError as exc:
            fts5_syntax_errors.append(query["query_id"])
            print(
                f"  [FTS5-Sanitize-Defekt, unabhaengig von #722] {query['query_id']}: {exc}",
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
        "flags": dict(flags),
        "overall": overall,
        "per_query": per_query,
        "fts5_syntax_errors": fts5_syntax_errors,
    }


def leave_one_out_combos() -> dict[str, dict[str, bool]]:
    """baseline_vor, baseline_nach + je eine Aenderung einzeln zurueckgeschaltet."""
    nach = dict.fromkeys(FLAG_NAMES, True)
    vor = dict.fromkeys(FLAG_NAMES, False)
    combos = {"baseline_vor": vor, "baseline_nach": nach}
    for flag in FLAG_NAMES:
        combo = dict(nach)
        combo[flag] = False
        combos[f"nach_minus_{flag}"] = combo
    return combos


def compute_deltas(results: dict[str, dict]) -> dict[str, dict[str, float]]:
    """Delta je Aenderung: baseline_nach minus 'nach_minus_<flag>' (positiv = die

    Aenderung hilft). Summe der Einzeldeltas wird bewusst NICHT dem
    Gesamtdelta (baseline_nach - baseline_vor) gleichgesetzt --
    Interaktionseffekte zwischen den vier Aenderungen bleiben moeglich.
    """
    nach = results["baseline_nach"]["overall"]
    deltas: dict[str, dict[str, float]] = {}
    for flag in FLAG_NAMES:
        without = results[f"nach_minus_{flag}"]["overall"]
        deltas[flag] = {m: round(nach[m] - without[m], 4) for m in METRICS}
    return deltas


# ---------------------------------------------------------------------------
# Orchestrierung
# ---------------------------------------------------------------------------
def run_ablation(goldset: dict, vectors: dict[str, list[float]], k: int = DEFAULT_K) -> dict:
    doc_titles = {d["doc_id"]: d["title"] for d in goldset["documents"]}
    relevance = build_paper_relevance(goldset)

    # 'vor'-Vektoren (ohne PaperMeta): direkt aus der #708-Fixture -- das ist
    # der Zustand, in dem das Set vor #701 gebaut wurde.
    vor_texts = {c["chunk_id"]: c["embedding_text"] for c in goldset["chunks"]}
    vor_vectors = {c["chunk_id"]: vectors[c["chunk_id"]] for c in goldset["chunks"]}

    # 'nach'-Vektoren (mit PaperMeta(title=...)): live neu gebaut.
    nach_texts, nach_vectors = build_ctx_meta_vectors(goldset, doc_titles)

    with tempfile.TemporaryDirectory(prefix="ablation-722-") as tmp:
        tmpdir = Path(tmp)
        dbs = {
            (False, True): build_db(
                tmpdir, "vor-trig", goldset, doc_titles, vor_vectors, vor_texts, True
            ),
            (False, False): build_db(
                tmpdir, "vor-notrig", goldset, doc_titles, vor_vectors, vor_texts, False
            ),
            (True, True): build_db(
                tmpdir, "nach-trig", goldset, doc_titles, nach_vectors, nach_texts, True
            ),
            (True, False): build_db(
                tmpdir, "nach-notrig", goldset, doc_titles, nach_vectors, nach_texts, False
            ),
        }

        combos = leave_one_out_combos()
        results = {
            name: evaluate_combo(dbs, goldset, relevance, flags, k=k)
            for name, flags in combos.items()
        }

    deltas = compute_deltas(results)
    regressions = {
        flag: delta for flag, delta in deltas.items() if any(v < 0 for v in delta.values())
    }
    return {
        "k": k,
        "chunk_count": len(goldset["chunks"]),
        "query_count": len(goldset["queries"]),
        "paper_count": len(doc_titles),
        "changes": [{"flag": f, "issue": i, "pr": p, "description": d} for f, i, p, d in CHANGES],
        "results": results,
        "deltas_vs_current": deltas,
        "regressions": regressions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goldset", type=Path, default=GOLDSET_PATH)
    parser.add_argument("--vectors", type=Path, default=VECTORS_PATH)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional: Report als JSON schreiben."
    )
    args = parser.parse_args(argv)

    if os.environ.get("VAULT_E5_LIVE_TEST") != "1":
        print(
            "VAULT_E5_LIVE_TEST=1 setzen -- dieses Skript laedt Tokenizer/Modelle und "
            "laeuft bewusst nicht hermetisch.",
            file=sys.stderr,
        )
        return 2

    goldset = load_goldset(args.goldset)
    try:
        verify_manifest(goldset)
    except ManifestMismatchError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    vectors_raw = load_vectors(args.vectors)
    vectors: dict[str, list[float]] = dict(vectors_raw)

    report = run_ablation(goldset, vectors, k=args.k)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"Report geschrieben: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
