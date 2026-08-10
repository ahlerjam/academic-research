#!/usr/bin/env python3
"""Hermetischer Reranker-Ablationslauf (#804): traegt der aktive Reranker?

#722 bezifferte den Reranker-Beitrag per Leave-one-out mit +0,0000 Recall@10,
+0,0107 nDCG@10 und +0,0144 MRR -- beide Nicht-Null-Werte unter dem im Repo
festgelegten Rauschband von 0,02 (#708), ohne Signifikanzaussage. Dieses
Skript liefert die Signifikanzaussage: gepaarter Bootstrap ueber genau die
Kandidaten, die der Produktionscode fusioniert -- einmal in RRF-Reihenfolge
("aus"), einmal nach ``rerank_score`` sortiert ("an").

Die Kandidaten (samt echten ``rerank_score``-Werten aus dem lokalen
``bge-reranker-v2-m3``) liegen als Fixture unter
``tests/fixtures/reranker_ablation_804/candidates.json``, erzeugt vom
Live-Generator ``scripts/eval/build_reranker_ablation_804.py``. Dieser Lauf
hier braucht **kein Netz und kein Modell** -- er sortiert nur zweimal um.

Nutzung::

    uv run python scripts/eval/run_reranker_ablation_804.py
    uv run python scripts/eval/run_reranker_ablation_804.py \\
        --check-against docs/evals/2026-08-10-reranker-ablation-804-live-results.json

Exit-Code 1, wenn der frische Lauf von den eingecheckten Rohdaten abweicht
(Latenz/Peak-RSS/Hardware bewusst ausgenommen, Muster #731), Exit-Code 2 bei
Fixture-Drift (``fixture_sha256``/``goldset_manifest_sha256`` passen nicht).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    GOLDSET_PATH,
    ManifestMismatchError,
    diverged_metrics,
    diverged_per_query,
    load_goldset,
)

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "reranker_ablation_804" / "candidates.json"
COST_PATH = REPO_ROOT / "tests" / "fixtures" / "reranker_ablation_804" / "cost.json"
REPORT_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-10-reranker-ablation-804.md"
LIVE_RESULTS_PATH = (
    REPO_ROOT / "docs" / "evals" / "2026-08-10-reranker-ablation-804-live-results.json"
)

DEFAULT_K = 10
METRICS = ("recall_at_10", "ndcg_at_10", "mrr")
CONDITIONS = ("aus", "an")

#: Vorab festgeschriebene Signifikanzregel -- identisch zum #731-Muster:
#: bewusst vor dem ersten Messwert fixiert, damit das Urteil nicht nachtraeglich
#: an das Wunschergebnis angepasst werden kann.
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 804
BOOTSTRAP_CI = 0.95
SIGNIFICANCE_RULE = (
    "Ein Abstand zwischen 'an' und 'aus' traegt genau dann, wenn das "
    "95-%-Intervall der gepaarten Bootstrap-Differenz (10 000 Resamples, "
    "Seed 804, ueber die Queries gepaart) die Null nicht enthaelt."
)

REBUILD_HINT = "VAULT_RERANK_LIVE_TEST=1 uv run python scripts/eval/build_reranker_ablation_804.py"


class FixtureMismatchError(RuntimeError):
    """Fixture und #708-Goldset gehoeren nicht zusammen, oder die Fixture ist beschaedigt."""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture(path: Path = FIXTURE_PATH) -> dict:
    return _read_json(path)


def verify_fixture(fixture: dict, goldset: dict) -> None:
    """Haerteter Abbruch statt stiller Drift (Muster #708/#731).

    Prueft sowohl, dass die Fixture zum #708-Goldset passt (``goldset_manifest_sha256``),
    als auch, dass die Kandidaten selbst nicht nachtraeglich editiert wurden
    (``fixture_sha256`` ueber ``per_query``).
    """
    meta = fixture["meta"]
    if meta["goldset_manifest_sha256"] != goldset["meta"]["manifest_sha256"]:
        raise FixtureMismatchError(
            "Fixture gehoert zu einem anderen #708-Goldset-Stand -- "
            f"erwartet {goldset['meta']['manifest_sha256']}, Fixture traegt "
            f"{meta['goldset_manifest_sha256']}. Neu erzeugen mit: {REBUILD_HINT}"
        )
    import hashlib

    recomputed = hashlib.sha256(
        json.dumps(fixture["per_query"], sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if recomputed != meta["fixture_sha256"]:
        raise FixtureMismatchError(
            f"fixture_sha256 passt nicht zu den Kandidaten -- erwartet {meta['fixture_sha256']}, "
            f"berechnet {recomputed}. Neu erzeugen mit: {REBUILD_HINT}"
        )


def _condition_ranking(candidates: list[dict], condition: str, k: int) -> list[str | None]:
    """Sortiert dieselben Kandidaten nach ``rrf_score`` ("aus") oder ``rerank_score``
    ("an") und liefert die ersten ``k`` Goldset-Chunk-IDs (``None`` fuer
    synthetische FTS-only-Kandidaten ohne echten Chunk-Treffer -- zaehlt in der
    Metrik korrekt als Nicht-Treffer, ist aber kein Fehlerfall)."""
    key = "rrf_score" if condition == "aus" else "rerank_score"
    ranked = sorted(candidates, key=lambda c: c[key], reverse=True)
    return [c["goldset_chunk_id"] for c in ranked[:k]]


def _aggregate(rows: Sequence[dict]) -> dict[str, float]:
    if not rows:
        return dict.fromkeys(METRICS, 0.0)
    return {
        "recall_at_10": sum(r["recall_at_10"] for r in rows) / len(rows),
        "ndcg_at_10": sum(r["ndcg_at_10"] for r in rows) / len(rows),
        "mrr": sum(r["reciprocal_rank"] for r in rows) / len(rows),
    }


def evaluate_condition(fixture: dict, condition: str, k: int = DEFAULT_K) -> dict:
    from academic_vault.retrieval import (
        compute_ndcg_at_k,
        compute_recall_at_k,
        compute_reciprocal_rank_at_k,
    )

    per_query: list[dict] = []
    for query in fixture["per_query"]:
        ranked = [cid for cid in _condition_ranking(query["candidates"], condition, k) if cid]
        relevant = query["relevant_chunk_ids"]
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

    subsets = {
        case: _aggregate([r for r in per_query if r["case"] == case])
        for case in sorted({r["case"] for r in per_query})
    }
    return {
        "condition": condition,
        "query_count": len(per_query),
        "overall": _aggregate(per_query),
        "subsets": subsets,
        "per_query": per_query,
    }


def paired_bootstrap(
    off: Sequence[float],
    on: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = BOOTSTRAP_CI,
) -> dict[str, float | bool]:
    """Gepaarter Bootstrap ueber die Queries: 'an' minus 'aus' (Muster #731)."""
    if len(off) != len(on):
        raise ValueError("Gepaarter Bootstrap braucht gleich viele Werte je Bedingung")
    diffs = [a - o for o, a in zip(off, on, strict=True)]
    n = len(diffs)
    if n == 0:
        raise ValueError("Gepaarter Bootstrap ohne Werte")

    delta = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(resamples))
    tail = (1.0 - confidence) / 2.0
    low = means[max(0, int(tail * resamples) - 1)]
    high = means[min(resamples - 1, int((1.0 - tail) * resamples))]
    return {
        "delta": round(delta, 6),
        "ci_low": round(low, 6),
        "ci_high": round(high, 6),
        "carries": bool(low > 0.0 or high < 0.0),
    }


_PER_QUERY_METRIC = {
    "recall_at_10": "recall_at_10",
    "ndcg_at_10": "ndcg_at_10",
    "mrr": "reciprocal_rank",
}


def compute_deltas(results: dict[str, dict]) -> dict[str, dict]:
    """Gepaarte Abstaende 'an' minus 'aus', je Metrik."""
    off_rows = {r["query_id"]: r for r in results["aus"]["per_query"]}
    on_rows = {r["query_id"]: r for r in results["an"]["per_query"]}
    if set(off_rows) != set(on_rows):
        raise ValueError("'aus' und 'an' beantworten andere Queries -- nicht paarbar")
    order = [r["query_id"] for r in results["aus"]["per_query"]]
    return {
        metric: paired_bootstrap(
            [off_rows[q][field_name] for q in order],
            [on_rows[q][field_name] for q in order],
        )
        for metric, field_name in _PER_QUERY_METRIC.items()
    }


def one_sentence_verdict(deltas: dict[str, dict]) -> str:
    """AC5: ein Satz, ob ein belegbarer Effekt vorliegt -- aus den ``carries``-Flags,
    nicht aus Textwunsch (siehe Plan-Kommentar zu #804)."""
    carrying = [metric for metric, values in deltas.items() if values["carries"]]
    if not carrying:
        return (
            "Der aktive Reranker hat im heutigen Zustand KEINEN vom Rauschen "
            "trennbaren Effekt auf Recall@10, nDCG@10 oder MRR -- fuer keine der "
            "drei Metriken schliesst das 95-%-Intervall der gepaarten "
            "Bootstrap-Differenz die Null aus."
        )
    return (
        f"Der aktive Reranker hat einen vom Rauschen trennbaren Effekt auf "
        f"{', '.join(sorted(carrying))} -- das 95-%-Intervall der gepaarten "
        "Bootstrap-Differenz schliesst dort die Null aus."
    )


def build_report(
    k: int = DEFAULT_K, fixture_path: Path = FIXTURE_PATH, goldset_path: Path = GOLDSET_PATH
) -> dict:
    goldset = load_goldset(goldset_path)
    fixture = load_fixture(fixture_path)
    verify_fixture(fixture, goldset)

    results = {condition: evaluate_condition(fixture, condition, k=k) for condition in CONDITIONS}
    deltas = compute_deltas(results)

    report: dict[str, Any] = {
        "issue": 804,
        "k": k,
        "query_count": len(fixture["per_query"]),
        "reranker_model_id": fixture["meta"]["reranker_model_id"],
        "significance": {
            "method": "paired bootstrap, percentile CI",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "confidence": BOOTSTRAP_CI,
            "rule": SIGNIFICANCE_RULE,
        },
        "results": results,
        "deltas": deltas,
        "verdict": one_sentence_verdict(deltas),
    }
    if COST_PATH.exists():
        report["cost"] = _read_json(COST_PATH)
    return report


def compare_against(report: dict, stored: dict, tolerance: float = 1e-9) -> list[str]:
    """Vergleicht einen frischen Lauf mit den eingecheckten Rohdaten (Muster #731).

    Latenz/Peak-RSS/Hardware (``cost``) bleiben bewusst aussen vor: sie haengen
    an der Maschine und waeren als Gatter nur eine Quelle roter CI-Laeufe ohne
    Aussage.
    """
    problems: list[str] = []
    for condition in CONDITIONS:
        fresh = report["results"][condition]
        old = stored.get("results", {}).get(condition)
        if old is None:
            problems.append(f"results.{condition}: fehlt in den eingecheckten Rohdaten")
            continue
        problems += diverged_metrics(
            fresh["overall"],
            old.get("overall"),
            f"results.{condition}.overall",
            tolerance=tolerance,
        )
        problems += diverged_per_query(
            fresh["per_query"], old.get("per_query"), f"results.{condition}.per_query"
        )

    if report["deltas"] != stored.get("deltas"):
        problems.append(
            f"deltas: gemessen {report['deltas']!r}, im Report {stored.get('deltas')!r}"
        )
    if report["verdict"] != stored.get("verdict"):
        problems.append(
            f"verdict: gemessen {report['verdict']!r}, im Report {stored.get('verdict')!r}"
        )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--goldset", type=Path, default=GOLDSET_PATH)
    parser.add_argument(
        "--check-against",
        type=Path,
        default=None,
        help="Exit 1 bei Abweichung von diesen Rohdaten.",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(k=args.k, fixture_path=args.fixture, goldset_path=args.goldset)
    except (ManifestMismatchError, FixtureMismatchError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.check_against is None:
        return 0

    problems = compare_against(report, _read_json(args.check_against))
    if problems:
        print(
            "Reranker-Ablation (#804): Lauf und eingecheckte Rohdaten weichen ab\n  "
            + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    print("Reranker-Ablation (#804): Lauf deckt sich mit den Rohdaten.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
