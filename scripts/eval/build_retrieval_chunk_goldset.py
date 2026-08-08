#!/usr/bin/env python3
"""Generator fuer das Chunk-Retrieval-Goldset aus Issue #708.

Erzeugt aus ``tests/fixtures/retrieval_goldset_chunks_708/sources.json``:

* ``goldset.json``  — Chunks (ueber ``chunking.chunk_pages`` mit Kontextsatz)
  und Queries mit aufgeloesten ``relevant_chunk_ids``
* ``vectors.json``  — base64-kodierte float32-Vektoren fuer Chunks (Praefix
  ``passage: ``) und Queries (Praefix ``query: ``)

Dieses Skript laeuft **nicht** hermetisch: es laedt den echten e5-Tokenizer
(fuer exakte Chunkgrenzen) und das echte Embedding-Modell. Es ist deshalb
bewusst kein pytest-Test, sondern wird manuell ausgefuehrt — analog zu
``scripts/eval/recall_at_k_model_ab.py`` (#375/#628)::

    VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_retrieval_chunk_goldset.py

Der hermetische Lauf gegen das Ergebnis ist
``scripts/eval/run_retrieval_chunk_goldset.py``.

Relevanzurteile stehen in ``sources.json`` nicht als Chunk-Indizes, sondern als
woertliche ``anchors``. Verschieben sich Chunkgrenzen (anderer Tokenizer,
anderes Tokenbudget), bleiben die Urteile damit gueltig; ein Anker, der in
keinem Chunk mehr auftaucht, ist ein harter Fehler statt einer stillen
Fehlmessung.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    GOLDSET_PATH,
    METRICS,
    SOURCES_PATH,
    THRESHOLDS_PATH,
    VECTORS_PATH,
    compute_manifest_sha256,
    encode_vector,
    load_sources,
)

# Marge zwischen gemessenem Wert und hinterlegter Schwelle. Klein, weil der
# Lauf bei fixen Vektoren deterministisch ist (beide knn_chunks-Pfade liefern
# dieselbe Reihenfolge); sie faengt nur Rundungsunterschiede zwischen
# Plattformen ab, keine echte Qualitaetsschwankung.
DEFAULT_MARGIN = 0.02

# Das #708-Goldset ist ausdruecklich das e5-small-Chunk-Goldset (siehe
# docs/evals/retrieval-chunk-goldset-708.md, "Historisches Dokument") --
# gepinnt statt ``DEFAULT_MODEL_ID`` zu folgen (PR-Review zu #732: seit der
# Default auf BAAI/bge-m3 zeigt, wuerde ein Lauf ohne diese Pin-Konstante
# heimlich mit dem bge-m3-Tokenizer chunken und mit e5-Praefixen ("passage: "/
# "query: ") auf bge-m3-Gewichten embedden -- genau die "falsch bediente
# Schnittstelle", die #731 und BgeM3Embedder ausschliessen wollen. #722 und
# #733 bauen auf diesem Goldset auf und teilen dieselbe Annahme.
LEGACY_EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"


def build_chunks(sources: dict) -> list[dict[str, Any]]:
    """Zerlegt jedes Quelldokument ueber ``chunk_pages`` in Goldset-Chunks.

    Nutzt bewusst die Produktionsdefaults (``TARGET_TOKENS``, ``OVERLAP_RATIO``,
    ``default_context_sentence``) und den echten Tokenizer von
    ``LEGACY_EMBEDDING_MODEL_ID`` (nicht ``DEFAULT_MODEL_ID`` -- dieses Goldset
    ist auf e5-small gepinnt, s. o.), sofern ladbar.
    """
    from academic_vault.chunking import chunk_pages, model_token_counter

    counter = model_token_counter(LEGACY_EMBEDDING_MODEL_ID)
    records: list[dict[str, Any]] = []
    for document in sources["documents"]:
        pages = [(int(number), text) for number, text in document["pages"]]
        for chunk in chunk_pages(pages, token_counter=counter):
            records.append(
                {
                    "chunk_id": f"{document['doc_id']}#{chunk.chunk_index}",
                    "doc_id": document["doc_id"],
                    "lang": document["lang"],
                    "chunk_index": chunk.chunk_index,
                    "chunk_text": chunk.chunk_text,
                    "context_sentence": chunk.context_sentence,
                    "embedding_text": chunk.embedding_text,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section_title": chunk.section_title,
                    "word_count": len(chunk.chunk_text.split()),
                }
            )
    return records


def _normalize(text: str) -> str:
    """Whitespace vereinheitlichen — ``chunk_pages`` normalisiert Zeilenumbrueche."""
    return " ".join(text.split())


def resolve_anchors(chunks: list[dict], sources: dict) -> list[dict[str, Any]]:
    """Loest die ``anchors`` jeder Query auf die Chunks auf, die sie enthalten.

    Ein Anker landet regelmaessig in ZWEI benachbarten Chunks, weil sich die
    Fenster ueberlappen. Beide gelten dann als relevant — der Text beantwortet
    die Frage in beiden Faellen, und ein Ranking dafuer zu bestrafen, welchen
    der beiden Ausschnitte es gefunden hat, waere Willkuer.

    Raises:
        ValueError: Ein Anker taucht in keinem Chunk auf (Quelltext geaendert,
            Anker nicht nachgezogen).
    """
    normalized = [(c["chunk_id"], _normalize(c["chunk_text"])) for c in chunks]
    queries: list[dict[str, Any]] = []
    for query in sources["queries"]:
        relevant: list[str] = []
        for anchor in query["anchors"]:
            needle = _normalize(anchor)
            hits = [cid for cid, text in normalized if needle in text]
            if not hits:
                raise ValueError(
                    f"Query {query['query_id']}: Anker {anchor!r} kommt in keinem Chunk vor. "
                    "sources.json und die Anker sind auseinandergelaufen."
                )
            relevant.extend(cid for cid in hits if cid not in relevant)
        queries.append(
            {
                "query_id": query["query_id"],
                "lang": query["lang"],
                "case": query["case"],
                "query": query["query"],
                "anchors": list(query["anchors"]),
                "relevant_chunk_ids": relevant,
            }
        )
    return queries


def embed_all(
    chunks: list[dict], queries: list[dict]
) -> tuple[dict[str, str], dict[str, str], int]:
    """Embeddet Chunks (``passage: ``) und Queries (``query: ``) mit dem echten Modell.

    Gepinnt auf ``LEGACY_EMBEDDING_MODEL_ID`` ueber :func:`embedder_for`, NICHT
    auf ``DEFAULT_MODEL_ID`` -- siehe Kommentar dort.
    """
    from academic_vault.embedding_model import embedder_for

    embedder = embedder_for(LEGACY_EMBEDDING_MODEL_ID)
    chunk_vectors = embedder.embed_documents([c["embedding_text"] for c in chunks])
    encoded_chunks = {
        c["chunk_id"]: encode_vector(v) for c, v in zip(chunks, chunk_vectors, strict=True)
    }
    encoded_queries = {
        q["query_id"]: encode_vector(embedder.embed_query(q["query"])) for q in queries
    }
    return encoded_chunks, encoded_queries, embedder.dim


def build(sources: dict) -> tuple[dict, dict]:
    """Baut ``goldset.json``- und ``vectors.json``-Inhalt aus den Quelltexten."""
    from academic_vault.embedding_model import PASSAGE_PREFIX, QUERY_PREFIX

    chunks = build_chunks(sources)
    queries = resolve_anchors(chunks, sources)
    encoded_chunks, encoded_queries, dim = embed_all(chunks, queries)

    meta = {
        "issue": 708,
        "model_id": LEGACY_EMBEDDING_MODEL_ID,
        "dim": dim,
        "passage_prefix": PASSAGE_PREFIX,
        "query_prefix": QUERY_PREFIX,
        "generator": "scripts/eval/build_retrieval_chunk_goldset.py",
        "manifest_sha256": compute_manifest_sha256(
            [c["embedding_text"] for c in chunks],
            [q["query"] for q in queries],
            LEGACY_EMBEDDING_MODEL_ID,
            dim,
        ),
    }
    goldset = {
        "meta": meta,
        "documents": [
            {"doc_id": d["doc_id"], "lang": d["lang"], "title": d["title"]}
            for d in sources["documents"]
        ],
        "chunks": chunks,
        "queries": queries,
    }
    vectors = {
        "model_id": LEGACY_EMBEDDING_MODEL_ID,
        "dim": dim,
        "manifest_sha256": meta["manifest_sha256"],
        "chunks": encoded_chunks,
        "queries": encoded_queries,
    }
    return goldset, vectors


def derive_thresholds(report: dict, margin: float = DEFAULT_MARGIN) -> dict:
    """Leitet Schwellen aus einem gemessenen Report ab: Messwert minus Marge."""

    def _floor(values: dict) -> dict[str, float]:
        return {metric: round(max(0.0, values[metric] - margin), 4) for metric in METRICS}

    return {
        "_comment": (
            "Erzeugt aus dem gemessenen Lauf minus einer Marge von "
            f"{margin}. Neu ableiten: build_retrieval_chunk_goldset.py --write-thresholds"
        ),
        "k": report["k"],
        "margin": margin,
        "measured_at_model": report["model_id"],
        "overall": _floor(report["overall"]),
        "subsets": {case: _floor(values) for case, values in report["subsets"].items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--goldset-out", type=Path, default=GOLDSET_PATH)
    parser.add_argument("--vectors-out", type=Path, default=VECTORS_PATH)
    parser.add_argument("--thresholds-out", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument(
        "--write-thresholds",
        action="store_true",
        help="Schwellen aus dem frisch gemessenen Lauf neu ableiten (ueberschreibt!).",
    )
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    args = parser.parse_args(argv)

    if os.environ.get("VAULT_E5_LIVE_TEST") != "1":
        print(
            "VAULT_E5_LIVE_TEST=1 setzen — dieses Skript laedt Tokenizer und "
            "Embedding-Modell und laeuft bewusst nicht hermetisch.",
            file=sys.stderr,
        )
        return 2

    sources = load_sources(args.sources)
    goldset, vectors = build(sources)

    args.goldset_out.parent.mkdir(parents=True, exist_ok=True)
    args.goldset_out.write_text(
        json.dumps(goldset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.vectors_out.write_text(json.dumps(vectors, indent=2) + "\n", encoding="utf-8")

    print(
        f"{len(goldset['chunks'])} Chunks, {len(goldset['queries'])} Queries, "
        f"Modell {goldset['meta']['model_id']} ({goldset['meta']['dim']}d), "
        f"manifest_sha256={goldset['meta']['manifest_sha256'][:16]}...",
        file=sys.stderr,
    )

    from scripts.eval.run_retrieval_chunk_goldset import evaluate, load_vectors

    report = evaluate(goldset, load_vectors(args.vectors_out))
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.write_thresholds:
        args.thresholds_out.write_text(
            json.dumps(derive_thresholds(report, args.margin), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Schwellen geschrieben: {args.thresholds_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
