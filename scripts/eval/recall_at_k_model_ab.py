#!/usr/bin/env python3
"""A/B-Vergleich von Embedding-Modellkandidaten auf einem Recall@k-Goldset.

Vergleicht Recall@k von:
  - intfloat/multilingual-e5-small              (aktueller Default, 384d nativ)
  - paraphrase-multilingual-MiniLM-L12-v2       (Alternative, 384d nativ)
  - Qwen/Qwen3-Embedding-0.6B (truncate_dim=384) (dokumentierter Upgrade-Pfad)
  - BAAI/bge-m3                                  (1024d nativ, 8192 Tokens, #628)
  - intfloat/multilingual-e5-large               (1024d nativ, 512 Tokens, #628)

Dies laeuft NICHT hermetisch (fuenf echte Modell-Downloads von HuggingFace,
CPU-Inferenzzeit) und ist deshalb bewusst kein pytest-Test, sondern ein
manuell/einmalig auszufuehrendes Skript -- analog zum bestehenden
env-gated-Live-Test-Muster (``VAULT_E5_LIVE_TEST=1`` in
``tests/test_vault_embeddings_ingest.py``). Das Ergebnis wird als statische
Tabelle in ``docs/evals/recall-at-k-model-ab-375.md`` (Default-Goldset) bzw.
``docs/evals/recall-at-k-model-ab-hard-628.md`` (hartes Goldset, ``--goldset
hard``) dokumentiert.

Jedes Modell nutzt sein jeweils korrektes Query/Passage-Prompting:
  - e5-Familie (e5-small, e5-large): "query: "/"passage: "-Praefixe (Teil des
    Trainings-Setups; fuer e5-large auf der Modellkarte verifiziert -- "Each
    input text should start with 'query: ' or 'passage: ', even for
    non-English texts").
  - MiniLM:      symmetrisches Modell, kein Praefix/Prompt noetig.
  - Qwen3-Embedding: ``prompt_name="query"`` fuer Queries (im Modell
    hinterlegter Prompt), Dokumente ohne Prompt (siehe sentence-transformers-
    Doku, verifiziert via Context7).
  - BGE-M3:      kein Praefix/Prompt noetig (Modellkarte: "the BGE-M3 model
    no longer requires adding instructions to the queries", anders als
    fruehere BGE-Generationen).

Nutzung:
    uv run python scripts/eval/recall_at_k_model_ab.py
    uv run python scripts/eval/recall_at_k_model_ab.py --model e5-small
    uv run python scripts/eval/recall_at_k_model_ab.py --goldset hard
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

GOLDSET_PATH = REPO_ROOT / "tests" / "fixtures" / "retrieval_goldset_de_en.json"
HARD_GOLDSET_PATH = REPO_ROOT / "tests" / "fixtures" / "retrieval_goldset_hard_overlap_628.json"
GOLDSET_PATHS: dict[str, Path] = {
    "default": GOLDSET_PATH,
    "hard": HARD_GOLDSET_PATH,
}


@dataclass
class ModelConfig:
    key: str
    model_id: str
    truncate_dim: int | None
    query_prefix: str = ""
    passage_prefix: str = ""
    query_prompt_name: str | None = None
    trust_remote_code: bool = False


MODEL_CONFIGS: dict[str, ModelConfig] = {
    "e5-small": ModelConfig(
        key="e5-small",
        model_id="intfloat/multilingual-e5-small",
        truncate_dim=None,
        query_prefix="query: ",
        passage_prefix="passage: ",
    ),
    "minilm": ModelConfig(
        key="minilm",
        model_id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        truncate_dim=None,
    ),
    "qwen3-embedding-0.6b": ModelConfig(
        key="qwen3-embedding-0.6b",
        model_id="Qwen/Qwen3-Embedding-0.6B",
        truncate_dim=384,
        query_prompt_name="query",
    ),
    "bge-m3": ModelConfig(
        key="bge-m3",
        model_id="BAAI/bge-m3",
        truncate_dim=None,
    ),
    "e5-large": ModelConfig(
        key="e5-large",
        model_id="intfloat/multilingual-e5-large",
        truncate_dim=None,
        query_prefix="query: ",
        passage_prefix="passage: ",
    ),
}


def _load_goldset(path: Path = GOLDSET_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _l2_normalize_rows(matrix):
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return matrix / norms


def run_model_ab(cfg: ModelConfig, data: dict, k: int = 10) -> dict:
    """Encodet Goldset-Papers+Queries mit ``cfg`` und berechnet Recall@k je Query.

    Returns:
        {"model": cfg.key, "model_id": cfg.model_id, "per_query": [...],
         "mean_recall": float}
    """
    import numpy as np
    from academic_vault.retrieval import compute_recall_at_k
    from sentence_transformers import SentenceTransformer

    load_kwargs: dict = {}
    if cfg.truncate_dim is not None:
        load_kwargs["truncate_dim"] = cfg.truncate_dim
    if cfg.trust_remote_code:
        load_kwargs["trust_remote_code"] = True

    model = SentenceTransformer(cfg.model_id, **load_kwargs)

    papers = data["papers"]
    paper_ids = [p["paper_id"] for p in papers]
    doc_texts = [cfg.passage_prefix + f"{p['title']}. {p['abstract']}" for p in papers]

    doc_embeddings = np.asarray(
        model.encode(doc_texts, normalize_embeddings=True, show_progress_bar=False)
    )
    doc_embeddings = _l2_normalize_rows(doc_embeddings)

    queries = data["queries"]
    query_texts = [cfg.query_prefix + q["query"] for q in queries]
    encode_kwargs: dict = {"normalize_embeddings": True, "show_progress_bar": False}
    if cfg.query_prompt_name:
        encode_kwargs["prompt_name"] = cfg.query_prompt_name
    query_embeddings = np.asarray(model.encode(query_texts, **encode_kwargs))
    query_embeddings = _l2_normalize_rows(query_embeddings)

    per_query = []
    recalls = []
    similarities = query_embeddings @ doc_embeddings.T
    for i, q in enumerate(queries):
        ranking = np.argsort(-similarities[i])
        retrieved_ids = [paper_ids[j] for j in ranking[:k]]
        recall = compute_recall_at_k(retrieved_ids, q["relevant_paper_ids"], k=k)
        recalls.append(recall)
        per_query.append({"query_id": q["query_id"], "lang": q["lang"], "recall_at_k": recall})

    mean_recall = sum(recalls) / len(recalls) if recalls else 0.0
    return {
        "model": cfg.key,
        "model_id": cfg.model_id,
        "k": k,
        "per_query": per_query,
        "mean_recall": mean_recall,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        choices=sorted(MODEL_CONFIGS),
        action="append",
        dest="models",
        help="Nur dieses Modell laufen lassen (mehrfach angebbar). Default: alle fuenf.",
    )
    parser.add_argument("--k", type=int, default=10, help="Recall@k Cutoff (Default: 10).")
    parser.add_argument(
        "--goldset",
        choices=sorted(GOLDSET_PATHS),
        default="default",
        help=(
            "'default' = 24 Papers/6 scharf getrennte Cluster (#375), "
            "'hard' = 24 Papers/2 Themen mit ueberlappenden Subtopics (#628). "
            "Default: default."
        ),
    )
    args = parser.parse_args()

    keys = args.models or list(MODEL_CONFIGS)
    data = _load_goldset(GOLDSET_PATHS[args.goldset])

    results = []
    for key in keys:
        cfg = MODEL_CONFIGS[key]
        print(f"--- {cfg.key} ({cfg.model_id}) ---", file=sys.stderr)
        result = run_model_ab(cfg, data, k=args.k)
        results.append(result)
        print(f"mean_recall@{args.k} = {result['mean_recall']:.4f}", file=sys.stderr)

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
