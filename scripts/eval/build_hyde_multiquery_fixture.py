#!/usr/bin/env python3
"""Fixture-Generator fuer den HyDE-/Multi-Query-Messlauf (Issue #733).

Zwei Stufen, beide bewusst **nicht** hermetisch und deshalb opt-in:

``--stage transforms`` (Gate ``VAULT_HYDE_LIVE_TRANSFORM=1``)
    Ruft je Goldset-Query zweimal die eingeloggte ``claude``-CLI auf (einmal
    HyDE, einmal Multi-Query), misst die Wanduhrzeit jedes Aufrufs und schreibt
    ``transforms.json``. Der Aufruf laeuft ueber die OAuth-Sitzung der CLI;
    ein API-Schluessel ist weder noetig noch vorgesehen (#632).

``--stage vectors`` (Gate ``VAULT_E5_LIVE_TEST=1``)
    Embeddet alle Umformtexte mit dem echten e5-Modell, misst die Zeit je
    Embedding und schreibt ``vectors.json`` sowie ``manifest_sha256`` und die
    Embedding-Latenz zurueck in ``transforms.json``.

Der Messlauf gegen das Ergebnis ist ``scripts/eval/run_hyde_multiquery_eval.py``
und braucht weder Netz noch Modell.

Nutzung::

    VAULT_HYDE_LIVE_TRANSFORM=1 uv run python \\
        scripts/eval/build_hyde_multiquery_fixture.py --stage transforms
    VAULT_E5_LIVE_TEST=1 uv run python \\
        scripts/eval/build_hyde_multiquery_fixture.py --stage vectors
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval import query_expansion_prototypes as proto  # noqa: E402
from scripts.eval.run_hyde_multiquery_eval import (  # noqa: E402
    TRANSFORMS_PATH,
    VECTORS_PATH,
    compute_transform_manifest,
)
from scripts.eval.run_retrieval_chunk_goldset import encode_vector, load_goldset  # noqa: E402

TRANSFORM_ENV_GATE = "VAULT_HYDE_LIVE_TRANSFORM"
EMBED_ENV_GATE = "VAULT_E5_LIVE_TEST"

#: Modell fuer die Umformung. Bewusst festgehalten und in der Fixture
#: mitgeschrieben — eine Latenzzahl ohne Modellangabe ist wertlos.
DEFAULT_TRANSFORM_MODEL = "sonnet"

CLI_TIMEOUT_S = 240

#: Wiederholungen je Umformung, falls die Antwort den Prompt verfehlt.
MAX_ATTEMPTS = 3

#: Kuerzer als das ist keine Passage, sondern eine Fehlantwort.
MIN_HYDE_CHARS = 120

TRANSFORM_METHOD = (
    "Wanduhrzeit je `claude -p`-Aufruf (CLI-Subprozess, eingeloggte OAuth-Sitzung), "
    "serieller Lauf, ein Aufruf je Query; bei einer verworfenen Antwort zaehlt der "
    "erfolgreiche Versuch (Anzahl Versuche steht je Query unter `attempts`). Obere "
    "Schranke: der CLI-Start bringt Prozess- und Sitzungsaufbau mit, den eine "
    "Umformung innerhalb einer laufenden Sitzung nicht bezahlt."
)
EMBED_METHOD = (
    "Wanduhrzeit je Einzel-Embedding mit dem geladenen e5-Modell (Modellladen nicht "
    "eingerechnet), gemessen auf der Maschine des Generatorlaufs."
)


def _percentiles(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))], 2),
        "mean": round(statistics.fmean(ordered), 2),
        "max": round(ordered[-1], 2),
    }


def call_claude_cli(prompt: str, model: str) -> tuple[str, float]:
    """Einen Prompt ueber die eingeloggte ``claude``-CLI stellen.

    Returns:
        ``(Antworttext, Dauer in Millisekunden)``.

    Raises:
        RuntimeError: Die CLI endet mit einem Fehler oder liefert leeren Text.
    """
    started = time.perf_counter()
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", model],
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_S,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if proc.returncode != 0:
        raise RuntimeError(f"claude-CLI endete mit {proc.returncode}: {proc.stderr[-400:]}")
    answer = proc.stdout.strip()
    if not answer:
        raise RuntimeError("claude-CLI lieferte eine leere Antwort")
    return answer, elapsed_ms


def _attempt(prompt: str, model: str, validate: Any, what: str) -> tuple[Any, float, int]:
    """Ruft die CLI, bis die Antwort brauchbar ist — hoechstens ``MAX_ATTEMPTS``-mal.

    Die CLI liefert gelegentlich eine Antwort, die den Prompt verfehlt (im
    Referenzlauf einmal in 52 Aufrufen). Ein Abbruch des ganzen Generatorlaufs
    waere dafuer die falsche Antwort, ein stillschweigend uebernommener
    Fehlgriff die schlechtere: er stuende als Umformung in der Fixture und
    verschoebe die Messung.

    Returns:
        ``(geprueftes Ergebnis, Dauer des erfolgreichen Aufrufs in ms, Versuche)``.
    """
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        answer, elapsed_ms = call_claude_cli(prompt, model)
        result = validate(answer)
        if result is not None:
            return result, elapsed_ms, attempt
        last_error = answer
        print(f"  Versuch {attempt} fuer {what} verworfen: {last_error[:120]!r}", file=sys.stderr)
    raise RuntimeError(f"{what}: {MAX_ATTEMPTS} Versuche ohne brauchbare Antwort: {last_error!r}")


def _validated_hyde(answer: str) -> str | None:
    text = " ".join(answer.split())
    return text if len(text) >= MIN_HYDE_CHARS else None


def _validated_variants(answer: str) -> list[str] | None:
    variants = [" ".join(v.split()) for v in proto.parse_multi_query_response(answer)]
    return variants if len(variants) >= 2 else None


def transform_one(query: dict, model: str) -> dict[str, Any]:
    """Erzeugt HyDE-Passage und Umformulierungen fuer genau eine Query.

    Das Modell sieht ausschliesslich den Query-Text — kein Goldset, keine Anker,
    keinen Zieltext.
    """
    qid = query["query_id"]
    hyde_text, hyde_ms, hyde_tries = _attempt(
        proto.hyde_passage_prompt(query["query"]), model, _validated_hyde, f"{qid}/HyDE"
    )
    variants, mq_ms, mq_tries = _attempt(
        proto.multi_query_prompt(query["query"]), model, _validated_variants, f"{qid}/Multi-Query"
    )
    return {
        "query_id": qid,
        "query": query["query"],
        "lang": query["lang"],
        "case": query["case"],
        "hyde_text": hyde_text,
        "mq_variants": variants,
        "latency_ms": {"hyde": round(hyde_ms, 2), "multi_query": round(mq_ms, 2)},
        "attempts": {"hyde": hyde_tries, "multi_query": mq_tries},
    }


def build_transforms(goldset: dict, model: str, cache_path: Path | None = None) -> dict[str, Any]:
    """Erzeugt die Umformungen fuer alle Goldset-Queries.

    Fertige Queries landen sofort im Cache (eine JSON-Zeile je Query). Ein
    Abbruch nach zwanzig Minuten CLI-Zeit soll nicht bedeuten, dass alles von
    vorn beginnt.
    """
    done: dict[str, dict] = {}
    if cache_path is not None and cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["query_id"]] = record
        print(f"{len(done)} Umformungen aus dem Cache uebernommen.", file=sys.stderr)

    records: list[dict[str, Any]] = []
    for index, query in enumerate(goldset["queries"], start=1):
        qid = query["query_id"]
        cached = done.get(qid)
        if cached is not None and cached["query"] == query["query"]:
            records.append(cached)
            continue
        record = transform_one(query, model)
        records.append(record)
        if cache_path is not None:
            with cache_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            f"[{index}/{len(goldset['queries'])}] {qid}: "
            f"HyDE {record['latency_ms']['hyde'] / 1000:.1f}s, "
            f"Multi-Query {record['latency_ms']['multi_query'] / 1000:.1f}s",
            file=sys.stderr,
            flush=True,
        )

    hyde_latencies = [r["latency_ms"]["hyde"] for r in records]
    mq_latencies = [r["latency_ms"]["multi_query"] for r in records]

    return {
        "meta": {
            "issue": 733,
            "goldset_manifest_sha256": goldset["meta"]["manifest_sha256"],
            "transform_model": model,
            "hyde_prompt_id": proto.HYDE_PROMPT_ID,
            "multi_query_prompt_id": proto.MULTI_QUERY_PROMPT_ID,
            "multi_query_variants": proto.MULTI_QUERY_VARIANTS,
            "generator": "scripts/eval/build_hyde_multiquery_fixture.py",
            "transform_latency_ms": {
                "hyde": {"method": TRANSFORM_METHOD, **_percentiles(hyde_latencies)},
                "multi_query": {"method": TRANSFORM_METHOD, **_percentiles(mq_latencies)},
            },
        },
        "transforms": records,
    }


def build_vectors(transforms: dict) -> tuple[dict[str, str], dict[str, Any], str, int]:
    """Embeddet alle Umformtexte und misst die Zeit je Embedding.

    Die HyDE-Passage wird **zweimal** eingebettet: einmal mit ``query: ``,
    einmal mit ``passage: ``. Fuer e5 ist nicht dokumentiert, welches Praefix
    einer hypothetischen Antwortpassage gebuehrt; die Wahl vorwegzunehmen hiesse,
    womoeglich nur eine falsche Praefixwahl zu messen.
    """
    from academic_vault.embedding_model import DEFAULT_MODEL_ID, E5SmallEmbedder

    embedder = E5SmallEmbedder()
    embedder.load()

    encoded: dict[str, str] = {}
    durations: list[float] = []

    def _timed(key: str, fn: Any, text: str) -> None:
        started = time.perf_counter()
        vector = fn(text)
        durations.append((time.perf_counter() - started) * 1000.0)
        encoded[key] = encode_vector(vector)

    for entry in transforms["transforms"]:
        qid = entry["query_id"]
        _timed(f"{qid}::hyde::query", embedder.embed_query, entry["hyde_text"])
        _timed(
            f"{qid}::hyde::passage", lambda t: embedder.embed_documents([t])[0], entry["hyde_text"]
        )
        for idx, variant in enumerate(entry["mq_variants"]):
            _timed(f"{qid}::mq::{idx}", embedder.embed_query, variant)

    latency = {"method": EMBED_METHOD, **_percentiles(durations)}
    return encoded, latency, DEFAULT_MODEL_ID, embedder.dim


def _require_gate(name: str, hint: str) -> None:
    if os.environ.get(name) != "1":
        print(f"{name}=1 setzen — {hint}", file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("transforms", "vectors"), required=True)
    parser.add_argument("--transforms-out", type=Path, default=TRANSFORMS_PATH)
    parser.add_argument("--vectors-out", type=Path, default=VECTORS_PATH)
    parser.add_argument("--model", default=DEFAULT_TRANSFORM_MODEL)
    args = parser.parse_args(argv)

    args.transforms_out.parent.mkdir(parents=True, exist_ok=True)

    if args.stage == "transforms":
        _require_gate(
            TRANSFORM_ENV_GATE,
            "diese Stufe ruft die claude-CLI je Query auf und laeuft mehrere Minuten.",
        )
        cache_path = args.transforms_out.with_suffix(".partial.jsonl")
        payload = build_transforms(load_goldset(), args.model, cache_path=cache_path)
        args.transforms_out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        cache_path.unlink(missing_ok=True)
        print(
            f"{len(payload['transforms'])} Umformungen geschrieben: {args.transforms_out}",
            file=sys.stderr,
        )
        return 0

    _require_gate(EMBED_ENV_GATE, "diese Stufe laedt das echte Embedding-Modell.")
    transforms = json.loads(args.transforms_out.read_text(encoding="utf-8"))
    encoded, embed_latency, model_id, dim = build_vectors(transforms)

    transforms["meta"]["embedding_model_id"] = model_id
    transforms["meta"]["dim"] = dim
    transforms["meta"]["embedding_latency_ms"] = embed_latency
    transforms["meta"].pop("manifest_sha256", None)
    transforms["meta"]["manifest_sha256"] = compute_transform_manifest(transforms)

    args.transforms_out.write_text(
        json.dumps(transforms, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.vectors_out.write_text(
        json.dumps(
            {
                "model_id": model_id,
                "dim": dim,
                "manifest_sha256": transforms["meta"]["manifest_sha256"],
                "vectors": encoded,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"{len(encoded)} Vektoren geschrieben: {args.vectors_out} "
        f"(manifest_sha256={transforms['meta']['manifest_sha256'][:16]}...)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
