#!/usr/bin/env python3
"""Hermetischer Messlauf: HyDE und Multi-Query gegen das Chunk-Goldset (#733).

Vier Arme auf demselben Goldset aus #708 und ueber denselben Suchpfad
(``VaultDB.add_chunk_embedding`` -> ``VaultDB.knn_chunks``):

``baseline``
    Die unveraenderte Query, eingebettet mit ``query: ``. Dieser Arm **muss**
    die #708-Zahlen exakt reproduzieren — er ist die Kontrolle dafuer, dass hier
    dieselbe Strecke gemessen wird und kein Gewinn aus einem anderen Pfad kommt.
``hyde_query_prefix`` / ``hyde_passage_prefix``
    Statt der Query wird eine hypothetische Antwortpassage eingebettet, einmal
    mit ``query: ``, einmal mit ``passage: ``. Welches Praefix einer solchen
    Passage bei e5 gebuehrt, ist nicht dokumentiert; beide Varianten
    auszuweisen verhindert, dass am Ende nur eine falsche Praefixwahl gemessen
    wurde.
``multi_query``
    Die Query und ihre Umformulierungen suchen einzeln; die Ranglisten werden
    mit ``query_expansion_prototypes.fuse_rankings`` (RRF) fusioniert.

Wie #708 braucht der Lauf weder Netz noch Modell: alle Vektoren liegen
vorberechnet im Repo (``tests/fixtures/hyde_multiquery_733/``), erzeugt von
``scripts/eval/build_hyde_multiquery_fixture.py``.

Nutzung::

    uv run python scripts/eval/run_hyde_multiquery_eval.py
    uv run python scripts/eval/run_hyde_multiquery_eval.py \\
        --check-against docs/evals/2026-08-07-hyde-multiquery-733-live-results.json

Exit 1, wenn ein Vergleichslauf von den eingecheckten Rohdaten abweicht;
Exit 2 bei Fixture-Drift (``manifest_sha256`` passt nicht zu den Umformtexten).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval import query_expansion_prototypes as proto  # noqa: E402
from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    DEFAULT_K,
    METRICS,
    ManifestMismatchError,
    _populate_vault,
    build_playback_embedder,
    decode_vector,
    load_goldset,
    load_vectors,
)

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "hyde_multiquery_733"
TRANSFORMS_PATH = FIXTURE_DIR / "transforms.json"
VECTORS_PATH = FIXTURE_DIR / "vectors.json"

#: Wie viele Treffer jede einzelne Rangliste im Multi-Query-Arm beisteuert.
#: Bewusst ``DEFAULT_K``: jede Teilanfrage bringt genau das ein, was sie im
#: Betrieb auch anzeigen wuerde, die Fusion waehlt daraus die Top-``k``.
FUSION_FETCH_K = DEFAULT_K

REBUILD_HINT = (
    "VAULT_HYDE_LIVE_TRANSFORM=1 uv run python "
    "scripts/eval/build_hyde_multiquery_fixture.py --stage transforms && "
    "VAULT_E5_LIVE_TEST=1 uv run python "
    "scripts/eval/build_hyde_multiquery_fixture.py --stage vectors"
)


# ---------------------------------------------------------------------------
# Fixture laden und pruefen
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_transforms(path: Path = TRANSFORMS_PATH) -> dict:
    """Die eingefrorenen Umformungen je Query."""
    return _read_json(path)


def compute_transform_manifest(transforms: dict) -> str:
    """Fingerabdruck ueber alles, was die Umform-Vektoren bestimmt hat.

    Deckt Query, HyDE-Passage und jede Umformulierung ab, dazu Modell-ID und
    Dimension des Embedders. Wird ein Text nachtraeglich editiert, ohne die
    Vektoren neu zu rechnen, faellt das hier auf — und nicht erst an einer
    Metrik, die sich unerklaerlich verschoben hat.
    """
    meta = transforms["meta"]
    digest = hashlib.sha256()
    digest.update(f"{meta.get('embedding_model_id', '')}\n{meta.get('dim', '')}\n".encode())
    for entry in sorted(transforms["transforms"], key=lambda e: e["query_id"]):
        digest.update(b"Q\x00")
        digest.update(entry["query"].encode("utf-8"))
        digest.update(b"\nH\x00")
        digest.update(entry["hyde_text"].encode("utf-8"))
        for variant in entry["mq_variants"]:
            digest.update(b"\nM\x00")
            digest.update(variant.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_transform_manifest(transforms: dict, vectors_meta: dict) -> None:
    """Prueft Umformtexte gegen Manifest **und** Vektordatei.

    Raises:
        ManifestMismatchError: Texte, Manifest oder Vektordatei laufen
            auseinander.
    """
    recorded = transforms["meta"].get("manifest_sha256")
    recomputed = compute_transform_manifest(transforms)
    if recorded != recomputed:
        raise ManifestMismatchError(
            f"manifest_sha256 passt nicht zu den Umformtexten: erwartet {recorded}, "
            f"berechnet {recomputed}. Fixture neu erzeugen mit: {REBUILD_HINT}"
        )
    if vectors_meta.get("manifest_sha256") != recomputed:
        raise ManifestMismatchError(
            "vectors.json gehoert zu einem anderen Textstand als transforms.json "
            f"({vectors_meta.get('manifest_sha256')} != {recomputed}). "
            f"Fixture neu erzeugen mit: {REBUILD_HINT}"
        )


def load_transform_vectors(
    path: Path = VECTORS_PATH, transforms: dict | None = None
) -> dict[str, list[float]]:
    """Vektoren der Umformtexte, erst nach bestandener Manifest-Pruefung."""
    raw = _read_json(path)
    verify_transform_manifest(load_transforms() if transforms is None else transforms, raw)
    return {key: decode_vector(value) for key, value in raw["vectors"].items()}


# ---------------------------------------------------------------------------
# Messlauf
# ---------------------------------------------------------------------------
def _aggregate(rows: Sequence[dict]) -> dict[str, float]:
    if not rows:
        return {metric: 0.0 for metric in METRICS}
    return {
        "recall_at_10": sum(r["recall_at_10"] for r in rows) / len(rows),
        "ndcg_at_10": sum(r["ndcg_at_10"] for r in rows) / len(rows),
        "mrr": sum(r["reciprocal_rank"] for r in rows) / len(rows),
    }


def _score_row(query: dict, ranked: list[str], k: int) -> dict:
    from academic_vault.retrieval import (
        compute_ndcg_at_k,
        compute_recall_at_k,
        compute_reciprocal_rank_at_k,
    )

    relevant = query["relevant_chunk_ids"]
    reciprocal = compute_reciprocal_rank_at_k(ranked, relevant, k=k)
    return {
        "query_id": query["query_id"],
        "lang": query["lang"],
        "case": query["case"],
        "recall_at_10": compute_recall_at_k(ranked, relevant, k=k),
        "ndcg_at_10": compute_ndcg_at_k(ranked, relevant, k=k),
        "reciprocal_rank": reciprocal,
        "first_hit_rank": round(1 / reciprocal) if reciprocal else None,
        "retrieved": ranked,
    }


def _arm_query_vectors(
    arm: str,
    query: dict,
    goldset_vectors: dict[str, list[float]],
    transform_vectors: dict[str, list[float]],
    variant_count: int,
) -> list[list[float]]:
    """Die Vektoren, mit denen ein Arm fuer diese Query sucht (in Suchreihenfolge)."""
    qid = query["query_id"]
    if arm == "baseline":
        return [goldset_vectors[qid]]
    if arm == "hyde_query_prefix":
        return [transform_vectors[f"{qid}::hyde::query"]]
    if arm == "hyde_passage_prefix":
        return [transform_vectors[f"{qid}::hyde::passage"]]
    if arm == "multi_query":
        return [goldset_vectors[qid]] + [
            transform_vectors[f"{qid}::mq::{idx}"] for idx in range(variant_count)
        ]
    raise ValueError(f"unbekannter Arm: {arm}")


def evaluate_all_arms(
    goldset: dict,
    goldset_vectors: dict[str, list[float]],
    transforms: dict,
    transform_vectors: dict[str, list[float]],
    k: int = DEFAULT_K,
) -> dict:
    """Fuehrt alle Arme gegen denselben Vault-KNN-Pfad aus.

    Returns:
        Report-Dict mit ``arms`` (je Arm ``overall``, ``subsets``, ``per_query``
        und ``deltas`` gegen die Baseline) sowie einem ``latency``-Block.
    """
    from academic_vault.db import VaultDB

    embedder = build_playback_embedder(goldset, goldset_vectors)
    variants_by_query = {e["query_id"]: len(e["mq_variants"]) for e in transforms["transforms"]}

    per_arm_rows: dict[str, list[dict]] = {arm: [] for arm in proto.ARMS}
    search_ms: dict[str, float] = {arm: 0.0 for arm in proto.ARMS}
    embed_calls: dict[str, int] = {arm: 0 for arm in proto.ARMS}

    with tempfile.TemporaryDirectory(prefix="hyde-733-") as tmpdir:
        db_path = str(Path(tmpdir) / "goldset.db")
        id_map = _populate_vault(db_path, goldset, embedder)
        db = VaultDB(db_path)

        for query in goldset["queries"]:
            variant_count = variants_by_query[query["query_id"]]
            for arm in proto.ARMS:
                vectors = _arm_query_vectors(
                    arm, query, goldset_vectors, transform_vectors, variant_count
                )
                fetch_k = k if len(vectors) == 1 else FUSION_FETCH_K
                started = time.perf_counter()
                rankings = [
                    [id_map[hit["chunk_id"]] for hit in db.knn_chunks(vector, k=fetch_k)]
                    for vector in vectors
                ]
                search_ms[arm] += (time.perf_counter() - started) * 1000.0
                embed_calls[arm] += len(vectors)
                ranked = (
                    rankings[0][:k] if len(rankings) == 1 else proto.fuse_rankings(rankings)[:k]
                )
                row = _score_row(query, ranked, k)
                row["fused_rankings"] = len(rankings)
                per_arm_rows[arm].append(row)

    query_count = len(goldset["queries"])
    cases = sorted({q["case"] for q in goldset["queries"]})

    arms: dict[str, dict] = {}
    for arm in proto.ARMS:
        rows = per_arm_rows[arm]
        arms[arm] = {
            "overall": _aggregate(rows),
            "subsets": {case: _aggregate([r for r in rows if r["case"] == case]) for case in cases},
            "per_query": rows,
        }

    baseline = arms["baseline"]
    for payload in arms.values():
        payload["deltas"] = {
            "overall": {
                metric: payload["overall"][metric] - baseline["overall"][metric]
                for metric in METRICS
            },
            **{
                case: {
                    metric: payload["subsets"][case][metric] - baseline["subsets"][case][metric]
                    for metric in METRICS
                }
                for case in cases
            },
        }

    return {
        "k": k,
        "model_id": goldset["meta"]["model_id"],
        "dim": goldset["meta"]["dim"],
        "manifest_sha256": goldset["meta"]["manifest_sha256"],
        "transform_manifest_sha256": transforms["meta"]["manifest_sha256"],
        "query_count": query_count,
        "chunk_count": len(goldset["chunks"]),
        "transform_model": transforms["meta"]["transform_model"],
        "hyde_prompt_id": transforms["meta"]["hyde_prompt_id"],
        "multi_query_prompt_id": transforms["meta"]["multi_query_prompt_id"],
        "arms": arms,
        "latency": _latency_block(transforms, search_ms, embed_calls, query_count),
    }


def _latency_block(
    transforms: dict,
    search_ms: dict[str, float],
    embed_calls: dict[str, int],
    query_count: int,
) -> dict[str, dict[str, float]]:
    """Latenz je Arm und Query, in drei getrennt gemessenen Posten.

    Die drei Posten stammen aus verschiedenen Quellen, und das bleibt sichtbar:

    * ``transform_ms`` — Median der echten CLI-Aufrufe aus dem Generatorlauf
      (``transforms.json``, Methode dort dokumentiert). Hermetisch nicht
      messbar, weil der Lauf kein Modell aufruft.
    * ``embed_ms`` — Anzahl der Embeddings dieses Arms mal dem Median einer
      echten e5-Einbettung aus dem Generatorlauf. Der Playback-Embedder des
      Messlaufs ist ein Dict-Zugriff; seine Zeit als Embedding-Latenz
      auszugeben, waere eine erfundene Zahl.
    * ``search_ms`` — in diesem Lauf gemessen, ueber den echten
      ``knn_chunks``-Pfad.
    """
    meta = transforms["meta"]
    transform_p50 = {
        "baseline": 0.0,
        "hyde_query_prefix": meta["transform_latency_ms"]["hyde"]["p50"],
        "hyde_passage_prefix": meta["transform_latency_ms"]["hyde"]["p50"],
        "multi_query": meta["transform_latency_ms"]["multi_query"]["p50"],
    }
    embed_p50 = meta["embedding_latency_ms"]["p50"]

    block: dict[str, dict[str, float]] = {}
    for arm in proto.ARMS:
        transform = float(transform_p50[arm])
        embed = round(embed_calls[arm] / query_count * embed_p50, 3)
        search = round(search_ms[arm] / query_count, 3)
        block[arm] = {
            "transform_ms": transform,
            "embed_ms": embed,
            "search_ms": search,
            "total_ms": round(transform + embed + search, 3),
            "embed_calls_per_query": embed_calls[arm] / query_count,
        }
    return block


# ---------------------------------------------------------------------------
# Vergleich gegen die eingecheckten Rohdaten
# ---------------------------------------------------------------------------
def compare_against(report: dict, stored: dict, tolerance: float = 1e-9) -> list[str]:
    """Vergleicht einen frischen Lauf mit den eingecheckten Rohdaten.

    Latenz bleibt bewusst aussen vor: sie haengt an der Maschine und waere als
    Gatter nur eine Quelle roter CI-Laeufe ohne Aussage.

    Returns:
        Je Abweichung eine Zeile. Leere Liste = deckungsgleich.
    """
    problems: list[str] = []
    for arm in proto.ARMS:
        fresh_arm = report["arms"][arm]
        stored_arm = stored.get("arms", {}).get(arm)
        if stored_arm is None:
            problems.append(f"{arm}: fehlt in den eingecheckten Rohdaten")
            continue
        for scope in ("overall", *fresh_arm["subsets"]):
            fresh_values = (
                fresh_arm["overall"] if scope == "overall" else fresh_arm["subsets"][scope]
            )
            stored_values = (
                stored_arm.get("overall", {})
                if scope == "overall"
                else stored_arm.get("subsets", {}).get(scope, {})
            )
            for metric, value in fresh_values.items():
                other = stored_values.get(metric)
                if other is None or abs(other - value) > tolerance:
                    problems.append(
                        f"{arm}.{scope}.{metric}: gemessen {value!r}, im Report {other!r}"
                    )
        fresh_ranked = [r["retrieved"] for r in fresh_arm["per_query"]]
        stored_ranked = [r.get("retrieved") for r in stored_arm.get("per_query", [])]
        if fresh_ranked != stored_ranked:
            problems.append(f"{arm}.per_query.retrieved: Rangfolge weicht von den Rohdaten ab")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transforms", type=Path, default=TRANSFORMS_PATH)
    parser.add_argument("--transform-vectors", type=Path, default=VECTORS_PATH)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--check-against",
        type=Path,
        help="Exit 1, wenn der frische Lauf von diesen Rohdaten abweicht.",
    )
    args = parser.parse_args(argv)

    transforms = load_transforms(args.transforms)
    try:
        transform_vectors = load_transform_vectors(args.transform_vectors, transforms=transforms)
    except ManifestMismatchError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    goldset = load_goldset()
    report = evaluate_all_arms(
        goldset=goldset,
        goldset_vectors=load_vectors(),
        transforms=transforms,
        transform_vectors=transform_vectors,
        k=args.k,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.check_against is None:
        return 0

    problems = compare_against(report, _read_json(args.check_against))
    if problems:
        print(
            "HyDE/Multi-Query (#733): Lauf und eingecheckte Rohdaten weichen ab\n  "
            + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    print("HyDE/Multi-Query (#733): Lauf deckt sich mit den Rohdaten.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
