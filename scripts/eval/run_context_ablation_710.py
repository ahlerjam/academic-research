#!/usr/bin/env python3
"""Hermetischer Vier-Arme-Vergleich: hilft ein inhaltlicher Kontextsatz? (#785/#710-C).

Misst ``nDCG@10``, ``MRR`` und ``Recall@10`` auf dem Chunk-Goldset aus #708 --
in der **bge-m3-Fassung aus #731** (``tests/fixtures/embedding_candidates_731/bge-m3/``),
nicht der aelteren e5-Fassung: #732 hat den produktiven Embedding-Default auf
``BAAI/bge-m3`` umgestellt, gegen das e5-Set zu messen wuerde einen Effekt auf
einem nicht mehr laufenden Modell belegen.

Vier Arme, alle auf demselben echten Suchpfad (``VaultDB.add_chunk_embedding``
+ ``VaultDB.knn_chunks``) wie #708/#729/#731:

* ``no_context``        -- nur ``chunk_text``, kein Kontextsatz.
* ``metadata_context``  -- der deterministische Produktionszustand
  (``chunking.default_context_sentence()``), UNVERAENDERT aus dem #731-Goldset
  uebernommen -- Grundlage des Kontrolltests unten.
* ``model_context``     -- ein echter, modellgeschriebener inhaltlicher Satz
  in der Sprache des Chunks (aus ``build_context_sentences_710.py --stage
  sentences``).
* ``model_context_de``  -- DERSELBE Inhalt wie ``model_context``, aber auf
  Deutsch erzwungen. Isoliert den Sprach-Confound: der Metadaten-Satz ist
  IMMER deutsch: ein inhaltlicher Satz in Chunk-Sprache unterscheidet sich von
  ihm sonst gleichzeitig in Inhalt UND Sprache. ``model_context_de`` haelt den
  Inhalt fest und variiert nur die Sprache; ``model_context`` haelt (relativ
  zu ``model_context_de``) die Sprache fest und variiert den Inhalt.

**Kontrolltest (zwingend):** ``metadata_context`` benutzt fuer Chunks UND
Queries exakt dieselben, bereits eingecheckten #731-bge-m3-Vektoren (kein
erneutes Embedding) -- der einzige Unterschied zum #731-Lauf ist die
Durchleitung durch DIESEN Harness statt durch
``run_embedding_candidates_731.py``. Stimmen die Zahlen nicht ueberein (Toleranz
1e-9), misst dieser Harness nicht denselben Suchpfad.

Nutzung::

    uv run python scripts/eval/run_context_ablation_710.py
    uv run python scripts/eval/run_context_ablation_710.py \\
        --check-against docs/evals/2026-08-08-context-ablation-710-live-results.json

Exit-Code 1, wenn ein frischer Lauf von den eingecheckten Rohdaten abweicht,
Exit-Code 2 bei Fixture-Drift (Manifest passt nicht zu den Texten) oder wenn
der Kontrolltest fehlschlaegt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_embedding_candidates_731 import (  # noqa: E402
    evaluate_candidate,
    load_candidate_fixture,
    paired_bootstrap,
)
from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    ManifestMismatchError,
    PlaybackEmbedder,
    _populate_vault,
    decode_vector,
    diverged_metrics,
    diverged_per_query,
)

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "context_sentences_710"
SENTENCES_PATH = FIXTURE_DIR / "sentences.json"
VECTORS_PATH = FIXTURE_DIR / "vectors.json"

BGE_M3_CANDIDATE = "bge-m3"
BGE_M3_GOLDSET_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "embedding_candidates_731" / "bge-m3" / "goldset.json"
)

REPORT_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-08-context-ablation-710.md"
LIVE_RESULTS_PATH = (
    REPO_ROOT / "docs" / "evals" / "2026-08-08-context-ablation-710-live-results.json"
)

MODEL_ID = "BAAI/bge-m3"
DEFAULT_K = 10
METRICS = ("recall_at_10", "ndcg_at_10", "mrr")

#: Reihenfolge ist Teil des Vertrags -- der Manifest-Hash haengt an ihr.
ARMS: tuple[str, ...] = ("no_context", "metadata_context", "model_context", "model_context_de")

#: Vorgabe aus dem #710-Plan-Kommentar: ein inhaltlicher Kontextsatz darf
#: hoechstens 25 Woerter lang sein.
MAX_SENTENCE_WORDS = 25

#: Vergleiche, die die eigentliche Fragestellung beantworten -- siehe
#: Modul-Docstring fuer die Begruendung von model_context_de.
DELTA_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("model_context", "no_context", "Inhalt vs. gar kein Kontextsatz"),
    ("model_context", "metadata_context", "Inhalt vs. Produktionszustand (Metadaten)"),
    ("model_context_de", "metadata_context", "Inhalt (Sprache DE gehalten) vs. Metadaten"),
    ("model_context", "model_context_de", "Sprache (Inhalt gehalten): Chunk-Sprache vs. DE"),
)

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 785
BOOTSTRAP_CI = 0.95
SIGNIFICANCE_RULE = (
    "Ein Abstand zwischen zwei Armen traegt genau dann, wenn das 95-%-Intervall der "
    "gepaarten Bootstrap-Differenz (10 000 Resamples, Seed 785, ueber die Queries "
    "gepaart) die Null nicht enthaelt."
)

REBUILD_HINT = (
    "VAULT_CONTEXT_LIVE_TRANSFORM=1 uv run python scripts/eval/build_context_sentences_710.py "
    "--stage sentences && VAULT_E5_LIVE_TEST=1 uv run python "
    "scripts/eval/build_context_sentences_710.py --stage vectors"
)

CONTROL_TOLERANCE = 1e-9

# Der Vergleichsstand des Kontrolltests ist kein eingecheckter Report, sondern
# ein zweiter, frisch gerechneter #731-Lauf -- die gemeinsamen Vergleichshelfer
# benennen ihn ueber ``source`` entsprechend.
REFERENCE_SOURCE = "der #731-Referenz"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Basis-Goldset (#731, bge-m3-Fassung)
# ---------------------------------------------------------------------------
def load_base_goldset() -> dict:
    """Laedt das bge-m3-Chunk-Goldset aus #731 und prueft seinen eigenen Fingerabdruck.

    ``load_candidate_fixture`` (aus #731) verifiziert bereits
    ``manifest_sha256`` gegen die Chunk-/Query-Texte -- ein zweiter,
    redundanter Check hier wuerde nur denselben Fehler doppelt melden.
    """
    goldset, _vectors = load_candidate_fixture(BGE_M3_CANDIDATE)
    return goldset


def load_sentences(path: Path = SENTENCES_PATH) -> dict:
    """Modellgeschriebene Kontextsaetze aus ``build_context_sentences_710.py --stage sentences``."""
    return _read_json(path)


def sentences_by_chunk(sentences: dict) -> dict[str, dict[str, str]]:
    """Mapping ``chunk_id -> {"sentence": ..., "sentence_de": ...}``."""
    return {
        entry["chunk_id"]: {"sentence": entry["sentence"], "sentence_de": entry["sentence_de"]}
        for entry in sentences["sentences"]
    }


def verify_sentence_coverage(goldset: dict, sentences: dict) -> None:
    """Jeder Goldset-Chunk hat genau einen Modellsatz -- nicht mehr, nicht weniger."""
    goldset_ids = {c["chunk_id"] for c in goldset["chunks"]}
    sentence_ids = {e["chunk_id"] for e in sentences["sentences"]}
    if goldset_ids != sentence_ids:
        missing = goldset_ids - sentence_ids
        extra = sentence_ids - goldset_ids
        raise ManifestMismatchError(
            f"sentences.json deckt nicht dieselben Chunks wie das Goldset ab. "
            f"Fehlend: {sorted(missing)}. Ueberzaehlig: {sorted(extra)}. Neu erzeugen "
            f"mit: {REBUILD_HINT}"
        )
    for entry in sentences["sentences"]:
        for field in ("sentence", "sentence_de"):
            words = len(entry[field].split())
            if words > MAX_SENTENCE_WORDS:
                raise ManifestMismatchError(
                    f"{entry['chunk_id']}.{field}: {words} Woerter > {MAX_SENTENCE_WORDS} "
                    f"(Vorgabe aus dem #710-Plan). Fixture ist nicht kontraktkonform."
                )


# ---------------------------------------------------------------------------
# Embedding-Texte je Arm
# ---------------------------------------------------------------------------
def build_contextual_embedding_text(context_sentence: str, chunk_text: str) -> str:
    """Bewusst re-implementiert statt importiert.

    ``academic_vault.embeddings.build_contextual_embedding_text`` ist
    Produktionscode (``area/vault``, geschuetzter Scope fuer dieses Issue) --
    dieser Harness darf ihn LESEN und nachbilden, aber nicht importieren und
    damit stillschweigend an Aenderungen dort koppeln. Die Formel ist eine
    Zeile und mit einem Test gegen das Original abgesichert
    (``test_matches_production_concatenation_formula``).
    """
    return f"{context_sentence} {chunk_text}"


def arm_embedding_text(
    arm: str, chunk: dict, sentence_pair: dict[str, str] | None
) -> tuple[str, str]:
    """Liefert ``(context_sentence, embedding_text)`` fuer einen Chunk in einem Arm."""
    if arm == "no_context":
        return "", chunk["chunk_text"]
    if arm == "metadata_context":
        # Unveraendert aus dem #731-Goldset -- Grundlage des Kontrolltests.
        return chunk["context_sentence"], chunk["embedding_text"]
    if sentence_pair is None:
        raise KeyError(f"Kein Modellsatz fuer Chunk {chunk['chunk_id']!r} (Arm {arm!r})")
    if arm == "model_context":
        sentence = sentence_pair["sentence"]
    elif arm == "model_context_de":
        sentence = sentence_pair["sentence_de"]
    else:
        raise ValueError(f"Unbekannter Arm: {arm!r}")
    return sentence, build_contextual_embedding_text(sentence, chunk["chunk_text"])


def build_arm_texts(goldset: dict, sentences: dict) -> dict[str, dict[str, tuple[str, str]]]:
    """``{arm: {chunk_id: (context_sentence, embedding_text)}}`` fuer alle vier Arme."""
    by_chunk = sentences_by_chunk(sentences)
    result: dict[str, dict[str, tuple[str, str]]] = {arm: {} for arm in ARMS}
    for chunk in goldset["chunks"]:
        pair = by_chunk.get(chunk["chunk_id"])
        for arm in ARMS:
            result[arm][chunk["chunk_id"]] = arm_embedding_text(arm, chunk, pair)
    return result


# ---------------------------------------------------------------------------
# Manifest / Drift-Schutz
# ---------------------------------------------------------------------------
def compute_context_manifest_sha256(
    arm_texts: dict[str, dict[str, tuple[str, str]]],
    goldset_chunk_order: Sequence[str],
    query_texts: dict[str, str],
    query_order: Sequence[str],
    model_id: str,
    dim: int,
) -> str:
    """Fingerabdruck ueber alle vier Arme plus die Queries.

    Wie ``run_retrieval_chunk_goldset.compute_manifest_sha256``: geht ein Text,
    die Modell-ID oder die Dimension irgendwo auseinander, faellt es hier auf
    statt an einer leise verschobenen Metrik. Gehasht wird nur ``embedding_text``
    (Index 1) -- der ``context_sentence``-Teil steckt bereits in ihm.
    """
    digest = hashlib.sha256()
    digest.update(f"{model_id}\n{dim}\n".encode())
    for arm in ARMS:
        digest.update(f"ARM\x00{arm}\n".encode())
        for chunk_id in goldset_chunk_order:
            digest.update(b"P\x00")
            digest.update(arm_texts[arm][chunk_id][1].encode("utf-8"))
            digest.update(b"\n")
    for query_id in query_order:
        digest.update(b"Q\x00")
        digest.update(query_texts[query_id].encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_manifest(
    goldset: dict, sentences: dict, vectors_meta: dict
) -> dict[str, dict[str, tuple[str, str]]]:
    """Baut die Arm-Texte und wirft :class:`ManifestMismatchError` bei Drift.

    Returns:
        Die Arm-Texte (damit Aufrufer sie nicht ein zweites Mal bauen muessen).
    """
    verify_sentence_coverage(goldset, sentences)
    arm_texts = build_arm_texts(goldset, sentences)
    chunk_order = [c["chunk_id"] for c in goldset["chunks"]]
    query_order = [q["query_id"] for q in goldset["queries"]]
    query_texts = {q["query_id"]: q["query"] for q in goldset["queries"]}
    recomputed = compute_context_manifest_sha256(
        arm_texts,
        chunk_order,
        query_texts,
        query_order,
        vectors_meta["model_id"],
        vectors_meta["dim"],
    )
    if recomputed != vectors_meta["manifest_sha256"]:
        raise ManifestMismatchError(
            "manifest_sha256 passt nicht zu den Texten der vier Arme: erwartet "
            f"{vectors_meta['manifest_sha256']}, berechnet {recomputed}. Die eingecheckten "
            f"Vektoren gehoeren zu einem anderen Textstand -- neu erzeugen mit: {REBUILD_HINT}"
        )
    return arm_texts


# ---------------------------------------------------------------------------
# Vektoren laden
# ---------------------------------------------------------------------------
def load_vectors(path: Path = VECTORS_PATH) -> dict[str, dict[str, list[float]]]:
    """``{arm: {id -> Vektor}}`` (Chunks und Queries im selben Namensraum je Arm)."""
    raw = _read_json(path)
    flat: dict[str, dict[str, list[float]]] = {}
    for arm in ARMS:
        arm_raw = raw["arms"][arm]
        arm_flat: dict[str, list[float]] = {}
        for section in ("chunks", "queries"):
            for key, encoded in arm_raw.get(section, {}).items():
                arm_flat[key] = decode_vector(encoded)
        flat[arm] = arm_flat
    return flat


def load_vectors_meta(path: Path = VECTORS_PATH) -> dict:
    raw = _read_json(path)
    return {
        "model_id": raw["model_id"],
        "dim": raw["dim"],
        "manifest_sha256": raw["manifest_sha256"],
    }


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


def evaluate_arm(
    arm: str,
    goldset: dict,
    arm_texts: dict[str, tuple[str, str]],
    vectors: dict[str, list[float]],
    k: int = DEFAULT_K,
) -> dict:
    """Fuehrt EINEN Arm gegen den echten Vault-KNN-Pfad aus -- Chunk-Ebene, nicht Paper-aggregiert."""
    embedder = PlaybackEmbedder(
        vectors, {"model_id": MODEL_ID, "dim": len(next(iter(vectors.values())))}
    )
    arm_chunks = []
    for chunk in goldset["chunks"]:
        context_sentence, embedding_text = arm_texts[chunk["chunk_id"]]
        embedder.register(chunk["chunk_id"], embedding_text)
        arm_chunks.append(
            {**chunk, "embedding_text": embedding_text, "context_sentence": context_sentence}
        )
    for query in goldset["queries"]:
        embedder.register(query["query_id"], query["query"])

    arm_goldset = {"documents": goldset["documents"], "chunks": arm_chunks}

    per_query: list[dict] = []
    with tempfile.TemporaryDirectory(prefix=f"context-710-{arm}-") as tmpdir:
        db_path = str(Path(tmpdir) / "context.db")
        id_map = _populate_vault(db_path, arm_goldset, embedder)
        from academic_vault.db import VaultDB
        from academic_vault.retrieval import (
            compute_ndcg_at_k,
            compute_recall_at_k,
            compute_reciprocal_rank_at_k,
        )

        db = VaultDB(db_path)
        for query in goldset["queries"]:
            hits = db.knn_chunks(embedder.embed_query(query["query"]), k=k)
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
    subset_counts = {case: len([r for r in per_query if r["case"] == case]) for case in subsets}
    return {
        "arm": arm,
        "overall": _aggregate(per_query),
        "subsets": subsets,
        "subset_counts": subset_counts,
        "per_query": per_query,
    }


# ---------------------------------------------------------------------------
# Kontrolltest: metadata_context reproduziert #731
# ---------------------------------------------------------------------------
def control_check(metadata_report: dict, tolerance: float = CONTROL_TOLERANCE) -> dict:
    """Vergleicht den ``metadata_context``-Arm gegen den frischen #731-bge-m3-Lauf.

    #731s ``evaluate_candidate`` laeuft unabhaengig ueber ``run_embedding_candidates_731``
    auf denselben, eingecheckten bge-m3-Vektoren -- kein Vorgriff auf gespeicherte
    Zahlen, sondern ein zweiter, frischer Lauf desselben Suchpfads.
    """
    goldset, vectors = load_candidate_fixture(BGE_M3_CANDIDATE)
    reference = evaluate_candidate(goldset, vectors, k=DEFAULT_K)

    problems: list[str] = []
    problems += diverged_metrics(
        metadata_report["overall"],
        reference["overall"],
        "overall",
        tolerance=tolerance,
        source=REFERENCE_SOURCE,
    )
    for case, values in metadata_report["subsets"].items():
        problems += diverged_metrics(
            values,
            reference["subsets"].get(case),
            f"subsets.{case}",
            tolerance=tolerance,
            source=REFERENCE_SOURCE,
        )
    problems += diverged_per_query(
        metadata_report["per_query"],
        reference["per_query"],
        "per_query",
        source=REFERENCE_SOURCE,
    )

    return {
        "reference": "run_embedding_candidates_731.evaluate_candidate('bge-m3')",
        "tolerance": tolerance,
        "passed": not problems,
        "problems": problems,
        "reference_overall": reference["overall"],
        "reference_subsets": reference["subsets"],
    }


# ---------------------------------------------------------------------------
# Deltas zwischen Armen
# ---------------------------------------------------------------------------
_PER_QUERY_METRIC = {
    "recall_at_10": "recall_at_10",
    "ndcg_at_10": "ndcg_at_10",
    "mrr": "reciprocal_rank",
}


def compute_arm_deltas(reports: dict[str, dict]) -> dict[str, dict]:
    """Gepaarte Bootstrap-Abstaende fuer die in :data:`DELTA_PAIRS` benannten Vergleiche.

    Overall UND je Teilmenge -- die Teilmengen sind der eigentliche Punkt
    dieses Laufs, das Gesamtmittel ist auf 11 Dokumenten gesaettigt.
    """
    deltas: dict[str, dict] = {}
    for candidate, baseline, label in DELTA_PAIRS:
        key = f"{candidate}_vs_{baseline}"
        cand_rows = {r["query_id"]: r for r in reports[candidate]["per_query"]}
        base_rows = {r["query_id"]: r for r in reports[baseline]["per_query"]}
        order = [r["query_id"] for r in reports[baseline]["per_query"]]

        overall = _scope_delta(order, base_rows, cand_rows, case=None)
        subsets = {
            case: _scope_delta(order, base_rows, cand_rows, case=case)
            for case in sorted({r["case"] for r in base_rows.values()})
        }
        deltas[key] = {"label": label, "overall": overall, "subsets": subsets}
    return deltas


def _scope_delta(
    order: Sequence[str],
    base_rows: dict[str, dict],
    cand_rows: dict[str, dict],
    case: str | None,
) -> dict[str, dict]:
    """Gepaarter Bootstrap je Metrik, gefiltert auf ``case`` (``None`` = alle Queries)."""
    filtered_order = [qid for qid in order if case is None or base_rows[qid]["case"] == case]
    result: dict[str, dict] = {}
    for metric, field in _PER_QUERY_METRIC.items():
        if not filtered_order:
            result[metric] = {"delta": 0.0, "ci_low": 0.0, "ci_high": 0.0, "carries": False, "n": 0}
            continue
        outcome = paired_bootstrap(
            [base_rows[q][field] for q in filtered_order],
            [cand_rows[q][field] for q in filtered_order],
            resamples=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            confidence=BOOTSTRAP_CI,
        )
        result[metric] = {**outcome, "n": len(filtered_order)}
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def build_report(
    k: int = DEFAULT_K,
    sentences_path: Path = SENTENCES_PATH,
    vectors_path: Path = VECTORS_PATH,
) -> dict:
    goldset = load_base_goldset()
    sentences = load_sentences(sentences_path)
    vectors_meta = load_vectors_meta(vectors_path)
    arm_texts = verify_manifest(goldset, sentences, vectors_meta)
    vectors = load_vectors(vectors_path)

    reports: dict[str, dict] = {}
    for arm in ARMS:
        reports[arm] = evaluate_arm(arm, goldset, arm_texts[arm], vectors[arm], k=k)

    control = control_check(reports["metadata_context"])

    return {
        "issue": 785,
        "epic": 710,
        "k": k,
        "goldset": {
            "source": str(BGE_M3_GOLDSET_PATH.relative_to(REPO_ROOT)),
            "manifest_sha256": goldset["meta"]["manifest_sha256"],
            "chunk_count": len(goldset["chunks"]),
            "query_count": len(goldset["queries"]),
            "document_count": len(goldset["documents"]),
        },
        "model_id": vectors_meta["model_id"],
        "dim": vectors_meta["dim"],
        "manifest_sha256": vectors_meta["manifest_sha256"],
        "arms": ARMS,
        "control_check": control,
        "significance": {
            "method": "paired bootstrap, percentile CI",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "confidence": BOOTSTRAP_CI,
            "rule": SIGNIFICANCE_RULE,
        },
        "reports": reports,
        "deltas": compute_arm_deltas(reports),
    }


def compare_against(report: dict, stored: dict, tolerance: float = CONTROL_TOLERANCE) -> list[str]:
    """Vergleicht einen frischen Lauf mit eingecheckten Rohdaten (Reproduzierbarkeit)."""
    problems: list[str] = []
    for arm in ARMS:
        fresh = report["reports"][arm]
        old = stored.get("reports", {}).get(arm)
        if old is None:
            problems.append(f"{arm}: fehlt in den eingecheckten Rohdaten")
            continue
        problems += diverged_metrics(
            fresh["overall"], old.get("overall"), f"{arm}.overall", tolerance=tolerance
        )
        old_subsets = old.get("subsets")
        for case, values in fresh["subsets"].items():
            problems += diverged_metrics(
                values,
                old_subsets.get(case) if isinstance(old_subsets, dict) else old_subsets,
                f"{arm}.subsets.{case}",
                tolerance=tolerance,
            )
        # Die Trefferlisten gehoeren mit ins Gatter: verschiebt sich die
        # Rangfolge, waehrend die Mittelwerte innerhalb der Toleranz bleiben
        # (Permutation gleich relevanter Treffer), dokumentierten die
        # eingecheckten Rohdaten sonst weiter eine Reihenfolge, die der Code
        # nicht mehr erzeugt. control_check deckt nur metadata_context ab.
        problems += diverged_per_query(fresh["per_query"], old.get("per_query"), f"{arm}.per_query")
    if not report["control_check"]["passed"]:
        problems.append("control_check: metadata_context reproduziert #731 nicht mehr")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--sentences", type=Path, default=SENTENCES_PATH)
    parser.add_argument("--vectors", type=Path, default=VECTORS_PATH)
    parser.add_argument(
        "--check-against", type=Path, help="Exit 1 bei Abweichung von diesen Rohdaten."
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(k=args.k, sentences_path=args.sentences, vectors_path=args.vectors)
    except ManifestMismatchError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not report["control_check"]["passed"]:
        print(
            "Kontext-Ablation (#785): Kontrolltest fehlgeschlagen -- metadata_context "
            "reproduziert die #731-Zahlen nicht mehr:\n  "
            + "\n  ".join(report["control_check"]["problems"]),
            file=sys.stderr,
        )
        return 2

    if args.check_against is None:
        return 0

    problems = compare_against(report, _read_json(args.check_against))
    if problems:
        print(
            "Kontext-Ablation (#785): Lauf und eingecheckte Rohdaten weichen ab\n  "
            + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    print("Kontext-Ablation (#785): Lauf deckt sich mit den Rohdaten.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
