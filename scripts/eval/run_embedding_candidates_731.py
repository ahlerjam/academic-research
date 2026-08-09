#!/usr/bin/env python3
"""Hermetischer Kandidatenvergleich fuer Embedding-Modelle (#731).

Misst ``nDCG@10``, ``MRR`` und ``Recall@10`` je Embedding-Kandidat auf dem
Chunk-Goldset aus #708 — auf demselben Weg wie im Betrieb: die Chunks sind mit
``chunking.chunk_pages`` und dem **jeweils eigenen** Tokenizer des Kandidaten
entstanden, der Kontextsatz steckt im Embedding-Input, und gerankt wird ueber
``VaultDB.knn_chunks``.

Wie der #708- und der #733-Lauf braucht dieser Lauf **kein Netz und kein
Modell**: die Vektoren liegen je Kandidat als Fixture unter
``tests/fixtures/embedding_candidates_731/<key>/``. Erzeugt werden sie vom
Live-Generator ``scripts/eval/build_embedding_candidates_731.py`` (rund 7 GB
Modelle, CPU-Inferenz, env-gated).

Nutzung::

    uv run python scripts/eval/run_embedding_candidates_731.py
    uv run python scripts/eval/run_embedding_candidates_731.py \\
        --check-against docs/evals/2026-08-08-embedding-candidates-731-live-results.json

Exit-Code 1, wenn der frische Lauf von den eingecheckten Rohdaten abweicht,
Exit-Code 2 bei Fixture-Drift (``manifest_sha256`` passt nicht zu den Texten).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    ManifestMismatchError,
    build_playback_embedder,
    compute_manifest_sha256,
    decode_vector,
    diverged_per_query,
)

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "embedding_candidates_731"
REPORT_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-08-embedding-candidates-731.md"
LIVE_RESULTS_PATH = (
    REPO_ROOT / "docs" / "evals" / "2026-08-08-embedding-candidates-731-live-results.json"
)

DEFAULT_K = 10
METRICS = ("recall_at_10", "ndcg_at_10", "mrr")
BASELINE_KEY = "e5-small"

#: Dimension, mit der ``chunk_vectors`` in ``academic_vault/db.py`` heute
#: angelegt wird. Alles darueber heisst Schema-Migration.
PRODUCTION_DIM = 384

#: Vorab festgeschriebene Signifikanzregel — bewusst vor dem ersten Messwert
#: fixiert, damit das Urteil nicht nachtraeglich an das Wunschergebnis
#: angepasst werden kann.
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 731
BOOTSTRAP_CI = 0.95
SIGNIFICANCE_RULE = (
    "Ein Abstand zur Baseline traegt genau dann, wenn das 95-%-Intervall der "
    "gepaarten Bootstrap-Differenz (10 000 Resamples, Seed 731, ueber die "
    "Queries gepaart) die Null nicht enthaelt."
)

REBUILD_HINT = "VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_embedding_candidates_731.py"


# ---------------------------------------------------------------------------
# Kandidaten
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CandidateConfig:
    """Ein Embedding-Kandidat samt seinem korrekten Prompting.

    ``prompting_note`` ist Pflicht: AC1 des Issues nennt woertlich den
    ``passage:``-Praefix, der aber nur fuer die e5-Familie Teil des
    Trainings-Setups ist. Wer BGE-M3 oder Qwen3 ein ``passage: `` aufzwingt,
    misst nicht ihre Qualitaet, sondern eine falsch bediente Schnittstelle —
    also steht je Kandidat da, warum sein Prompting so aussieht.
    """

    key: str
    model_id: str
    truncate_dim: int | None
    prompting_note: str
    query_prefix: str = ""
    passage_prefix: str = ""
    query_prompt_name: str | None = None
    trust_remote_code: bool = False
    load_kwargs: dict[str, Any] = field(default_factory=dict)


CANDIDATES: dict[str, CandidateConfig] = {
    "e5-small": CandidateConfig(
        key="e5-small",
        model_id="intfloat/multilingual-e5-small",
        truncate_dim=None,
        query_prefix="query: ",
        passage_prefix="passage: ",
        prompting_note=(
            "e5-Familie: 'query: '/'passage: ' sind Teil des Trainings-Setups "
            "(Modellkarte: \"Each input text should start with 'query: ' or "
            "'passage: ', even for non-English texts\"). Entspricht dem "
            "Produktivpfad in academic_vault/embedding_model.py."
        ),
    ),
    "qwen3-384": CandidateConfig(
        key="qwen3-384",
        model_id="Qwen/Qwen3-Embedding-0.6B",
        truncate_dim=384,
        query_prompt_name="query",
        prompting_note=(
            "Abweichung vom AC1-Wortlaut: Qwen3-Embedding nutzt den im Modell "
            "hinterlegten Prompt (prompt_name='query') fuer Queries und "
            "KEINEN Praefix fuer Dokumente. Ein aufgezwungenes 'passage: ' "
            "waere kein Betriebspfad, sondern eine falsch bediente "
            "Schnittstelle. truncate_dim=384 ist der laut #730 einzige "
            "migrationsfreie Pfad (MRL Support: Yes, 32-1024)."
        ),
    ),
    "qwen3-1024": CandidateConfig(
        key="qwen3-1024",
        model_id="Qwen/Qwen3-Embedding-0.6B",
        truncate_dim=None,
        query_prompt_name="query",
        prompting_note=(
            "Wie qwen3-384, aber mit nativer Dimension (1024). Zweite Variante "
            "desselben Modells, weil sich der Preis einer Schema-Migration nur "
            "beziffern laesst, wenn danebensteht, was die Kuerzung auf 384d "
            "kostet."
        ),
    ),
    "bge-m3": CandidateConfig(
        key="bge-m3",
        model_id="BAAI/bge-m3",
        truncate_dim=None,
        prompting_note=(
            "Abweichung vom AC1-Wortlaut: BGE-M3 verlangt ausdruecklich keine "
            'Instruktion (Modellkarte: "the BGE-M3 model no longer requires '
            'adding instructions to the queries"). Weder Query- noch '
            "Passage-Praefix."
        ),
    ),
    "e5-large": CandidateConfig(
        key="e5-large",
        model_id="intfloat/multilingual-e5-large",
        truncate_dim=None,
        query_prefix="query: ",
        passage_prefix="passage: ",
        prompting_note=(
            "e5-Familie, identisches Praefixschema wie e5-small — auf der "
            "Modellkarte von multilingual-e5-large ausdruecklich bestaetigt."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Fixture laden
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_dir(key: str) -> Path:
    """Fixture-Verzeichnis eines Kandidaten."""
    return FIXTURE_DIR / key


def verify_manifest(goldset: dict) -> None:
    """Wirft :class:`ManifestMismatchError`, wenn Texte und Hash auseinanderlaufen.

    Derselbe harte Abbruch wie in #708: ein editierter ``embedding_text`` mit
    altem Vektor faellt sonst nirgends auf und verschiebt nur die Metrik.
    """
    meta = goldset["meta"]
    recomputed = compute_manifest_sha256(
        [c["embedding_text"] for c in goldset["chunks"]],
        [q["query"] for q in goldset["queries"]],
        meta["model_id"],
        meta["dim"],
    )
    if recomputed != meta["manifest_sha256"]:
        raise ManifestMismatchError(
            f"{meta['candidate']}: manifest_sha256 passt nicht zu den Texten — erwartet "
            f"{meta['manifest_sha256']}, berechnet {recomputed}. Die eingecheckten Vektoren "
            f"gehoeren zu einem anderen Textstand. Neu erzeugen mit: {REBUILD_HINT}"
        )


def load_candidate_fixture(key: str) -> tuple[dict, dict[str, list[float]]]:
    """Laedt Goldset und Vektoren eines Kandidaten und prueft den Fingerabdruck."""
    directory = candidate_dir(key)
    goldset = _read_json(directory / "goldset.json")
    verify_manifest(goldset)
    raw = _read_json(directory / "vectors.json")
    flat: dict[str, list[float]] = {}
    for section in ("chunks", "queries"):
        for vector_id, encoded in raw.get(section, {}).items():
            flat[vector_id] = decode_vector(encoded)
    return goldset, flat


# ---------------------------------------------------------------------------
# Chunkgrenzen ohne Tokenizer nachrechnen
# ---------------------------------------------------------------------------
def token_key(text: str) -> str:
    """Kurzer, stabiler Schluessel fuer einen eingefrorenen Tokenizer-Aufruf."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class FrozenTokenCounter:
    """Spielt die Tokenzaehlungen eines Kandidaten aus der Fixture ab.

    ``chunk_pages`` fragt den Tokenizer waehrend der Fenstersuche fuer viele
    Zwischenstaende; der Generator zeichnet jeden dieser Aufrufe auf. Ein Text
    ohne aufgezeichnete Zaehlung ist ein ``KeyError`` und ausdruecklich kein
    Naeherungswert: still auf ``approximate_token_count`` zurueckzufallen wuerde
    andere Chunkgrenzen erzeugen und trotzdem gruen aussehen.
    """

    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def __call__(self, text: str) -> int:
        try:
            return self._counts[token_key(text)]
        except KeyError as exc:
            raise KeyError(
                f"Keine aufgezeichnete Tokenzahl fuer {text[:60]!r}. Fixture und Chunker "
                f"laufen auseinander — neu erzeugen mit: {REBUILD_HINT}"
            ) from exc


def rechunk_from_frozen_token_counts(goldset: dict) -> list[dict[str, Any]]:
    """Rechnet die Chunks eines Kandidaten aus den Quelltexten neu nach.

    Nutzt ``chunk_pages`` mit den Produktionsdefaults und dem eingefrorenen
    Tokenizer des Kandidaten. Damit ist ohne Modell-Download belegt, dass die
    Fixture-Chunks aus dem Betriebspfad stammen und nicht aus einer
    Sonderbehandlung.
    """
    from academic_vault.chunking import chunk_pages

    from scripts.eval.run_retrieval_chunk_goldset import load_sources

    counter = FrozenTokenCounter(goldset["meta"]["token_counts"])
    sources = load_sources()
    records: list[dict[str, Any]] = []
    for document in sources["documents"]:
        pages = [(int(number), text) for number, text in document["pages"]]
        for chunk in chunk_pages(pages, token_counter=counter):
            records.append(
                {
                    "chunk_id": f"{document['doc_id']}#{chunk.chunk_index}",
                    "chunk_text": chunk.chunk_text,
                    "embedding_text": chunk.embedding_text,
                }
            )
    return records


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------
def _aggregate(rows: Sequence[dict]) -> dict[str, float]:
    if not rows:
        return dict.fromkeys(METRICS, 0.0)
    return {
        "recall_at_10": sum(r["recall_at_10"] for r in rows) / len(rows),
        "ndcg_at_10": sum(r["ndcg_at_10"] for r in rows) / len(rows),
        "mrr": sum(r["reciprocal_rank"] for r in rows) / len(rows),
    }


def evaluate_candidate(
    goldset: dict,
    vectors: dict[str, list[float]],
    k: int = DEFAULT_K,
) -> dict:
    """Fuehrt einen Kandidaten gegen den echten Vault-KNN-Pfad aus.

    Returns:
        Dict mit ``overall``, ``subsets`` (je ``case``), ``per_query`` und der
        in DIESEM Lauf gemessenen Suchlatenz.
    """
    import tempfile

    from academic_vault.db import VaultDB
    from academic_vault.retrieval import (
        compute_ndcg_at_k,
        compute_recall_at_k,
        compute_reciprocal_rank_at_k,
    )

    from scripts.eval.run_retrieval_chunk_goldset import _populate_vault

    embedder = build_playback_embedder(goldset, vectors)
    meta = goldset["meta"]

    per_query: list[dict] = []
    search_ms: list[float] = []
    with tempfile.TemporaryDirectory(prefix="candidates-731-") as tmpdir:
        db_path = str(Path(tmpdir) / "candidates.db")
        id_map = _populate_vault(db_path, goldset, embedder)
        db = VaultDB(db_path)

        for query in goldset["queries"]:
            vector = embedder.embed_query(query["query"])
            started = time.perf_counter()
            hits = db.knn_chunks(vector, k=k)
            search_ms.append((time.perf_counter() - started) * 1000.0)
            ranked = [id_map[hit["chunk_id"]] for hit in hits]
            relevant = query["relevant_chunk_ids"]
            reciprocal = compute_reciprocal_rank_at_k(ranked, relevant, k=k)
            per_query.append(
                {
                    "query_id": query["query_id"],
                    "lang": query["lang"],
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
        "model_id": meta["model_id"],
        "dim": meta["dim"],
        "truncate_dim": meta["truncate_dim"],
        "prompting": meta["prompting"],
        "chunk_count": len(goldset["chunks"]),
        "query_count": len(goldset["queries"]),
        "manifest_sha256": meta["manifest_sha256"],
        "download_bytes": meta["download_bytes"],
        "download_source": meta["download_source"],
        "index_ms_per_chunk": meta["index_ms_per_chunk"],
        "search_ms_per_query": _percentiles(search_ms),
        "schema_migration": schema_migration(meta["dim"]),
        "overall": _aggregate(per_query),
        "subsets": subsets,
        "per_query": per_query,
    }


def _percentiles(values: Sequence[float]) -> dict[str, float]:
    """p50/p95 einer Messreihe (nearest-rank, wie im Generator)."""
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0}

    def _at(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
        return round(ordered[index], 3)

    return {"p50": _at(0.50), "p95": _at(0.95)}


def schema_migration(dim: int) -> dict[str, Any]:
    """Der Preis eines Wechsels auf diese Dimension, gestuetzt auf #730.

    ``chunk_vectors`` wird in ``academic_vault/db.py`` mit fester Dimension
    angelegt (``vec0(... embedding FLOAT[dim])``). 384 ist der Bestand; jede
    andere Dimension bedeutet DDL-Aenderung plus vollstaendige Neuindizierung
    aller Bestands-Vaults.
    """
    if dim == PRODUCTION_DIM:
        return {
            "required": False,
            "price": "keine Migration (384d, Bestandsschema)",
            "evidence": (
                "docs/evals/embedding-truncatability-730.md — 384d nur fuer "
                "Qwen3-Embedding-0.6B vom Anbieter zugesichert (MRL Support: Yes, "
                "32-1024); e5-small ist nativ 384d."
            ),
        }
    return {
        "required": True,
        "price": (
            f"Schema-Migration FLOAT[{PRODUCTION_DIM}] -> FLOAT[{dim}] plus "
            "vollstaendige Neuindizierung aller Bestands-Vaults"
        ),
        "evidence": (
            "docs/evals/embedding-truncatability-730.md — fuer BGE-M3 und "
            "multilingual-e5-large ist eine Kuerzung auf 384d 'nicht belegt'; "
            "nativ bleiben 1024 Dimensionen."
        ),
    }


# ---------------------------------------------------------------------------
# Signifikanz
# ---------------------------------------------------------------------------
def paired_bootstrap(
    baseline: Sequence[float],
    candidate: Sequence[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = BOOTSTRAP_CI,
) -> dict[str, float | bool]:
    """Gepaarter Bootstrap ueber die Queries: Kandidat minus Baseline.

    Gepaart, weil beide Arme dieselben Queries beantworten — die
    Query-Schwierigkeit faellt damit aus der Varianz heraus. Fester Seed, damit
    das Urteil nachrechenbar bleibt statt bei jedem Lauf zu wackeln.

    Returns:
        ``delta`` (gemessener Mittelwertsunterschied), ``ci_low``/``ci_high``
        (Perzentilintervall) und ``carries`` (Regel: Intervall ohne Null).
    """
    if len(baseline) != len(candidate):
        raise ValueError("Gepaarter Bootstrap braucht gleich viele Werte je Arm")
    diffs = [c - b for b, c in zip(baseline, candidate, strict=True)]
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


def compute_deltas(candidates: dict[str, dict]) -> dict[str, dict[str, dict]]:
    """Gepaarte Abstaende jedes Kandidaten gegen die Baseline, je Metrik."""
    baseline_rows = {r["query_id"]: r for r in candidates[BASELINE_KEY]["per_query"]}
    order = [r["query_id"] for r in candidates[BASELINE_KEY]["per_query"]]

    deltas: dict[str, dict[str, dict]] = {}
    for key, entry in candidates.items():
        if key == BASELINE_KEY:
            continue
        rows = {r["query_id"]: r for r in entry["per_query"]}
        if set(rows) != set(baseline_rows):
            raise ValueError(f"{key}: andere Queries als die Baseline — nicht paarbar")
        deltas[key] = {
            metric: paired_bootstrap(
                [baseline_rows[q][field_name] for q in order],
                [rows[q][field_name] for q in order],
            )
            for metric, field_name in _PER_QUERY_METRIC.items()
        }
    return deltas


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def build_report(k: int = DEFAULT_K) -> dict:
    """Fuehrt alle Kandidaten aus und baut den vollstaendigen Report."""
    candidates: dict[str, dict] = {}
    hardware: dict | None = None
    for key in CANDIDATES:
        goldset, vectors = load_candidate_fixture(key)
        if hardware is None:
            hardware = goldset["meta"]["hardware"]
        elif goldset["meta"]["hardware"] != hardware:
            raise ValueError(
                f"{key}: andere Messhardware als die Baseline — die Zeiten waeren nicht "
                "vergleichbar. Alle Kandidaten muessen auf derselben Maschine laufen."
            )
        candidates[key] = evaluate_candidate(goldset, vectors, k=k)

    query_count = candidates[BASELINE_KEY]["query_count"]
    return {
        "issue": 731,
        "k": k,
        "baseline": BASELINE_KEY,
        "hardware": hardware,
        "significance": {
            "method": "paired bootstrap, percentile CI",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "confidence": BOOTSTRAP_CI,
            "rule": SIGNIFICANCE_RULE,
            "query_count": query_count,
            "resolution_per_query": round(1.0 / query_count, 4),
        },
        "candidates": candidates,
        "deltas": compute_deltas(candidates),
    }


# ---------------------------------------------------------------------------
# Vergleich gegen die eingecheckten Rohdaten
# ---------------------------------------------------------------------------
def compare_against(report: dict, stored: dict, tolerance: float = 1e-9) -> list[str]:
    """Vergleicht einen frischen Lauf mit den eingecheckten Rohdaten.

    Latenz und Hardware bleiben bewusst aussen vor: sie haengen an der Maschine
    und waeren als Gatter nur eine Quelle roter CI-Laeufe ohne Aussage. Alles
    andere — Metriken, Rangfolgen, Signifikanzurteile — muss sich decken.
    """
    problems: list[str] = []
    for key in CANDIDATES:
        fresh = report["candidates"][key]
        old = stored.get("candidates", {}).get(key)
        if old is None:
            problems.append(f"{key}: fehlt in den eingecheckten Rohdaten")
            continue
        scopes: list[tuple[str, dict, dict]] = [
            ("overall", fresh["overall"], old.get("overall", {}))
        ]
        scopes += [
            (f"subsets.{case}", values, old.get("subsets", {}).get(case, {}))
            for case, values in fresh["subsets"].items()
        ]
        for scope, fresh_values, old_values in scopes:
            for metric, value in fresh_values.items():
                other = old_values.get(metric)
                if other is None or abs(other - value) > tolerance:
                    problems.append(
                        f"{key}.{scope}.{metric}: gemessen {value!r}, im Report {other!r}"
                    )
        problems += diverged_per_query(
            fresh["per_query"], old.get("per_query", []), f"{key}.per_query"
        )
        for field_name in ("dim", "chunk_count", "schema_migration"):
            if fresh[field_name] != old.get(field_name):
                problems.append(
                    f"{key}.{field_name}: gemessen {fresh[field_name]!r}, "
                    f"im Report {old.get(field_name)!r}"
                )

    for key, metrics in report["deltas"].items():
        stored_metrics = stored.get("deltas", {}).get(key, {})
        for metric, values in metrics.items():
            other = stored_metrics.get(metric)
            if other != values:
                problems.append(f"deltas.{key}.{metric}: gemessen {values!r}, im Report {other!r}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="Cutoff aller drei Metriken.")
    parser.add_argument(
        "--check-against",
        type=Path,
        help="Exit 1, wenn der frische Lauf von diesen Rohdaten abweicht.",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(k=args.k)
    except ManifestMismatchError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.check_against is None:
        return 0

    problems = compare_against(report, _read_json(args.check_against))
    if problems:
        print(
            "Embedding-Kandidaten (#731): Lauf und eingecheckte Rohdaten weichen ab\n  "
            + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    print("Embedding-Kandidaten (#731): Lauf deckt sich mit den Rohdaten.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
