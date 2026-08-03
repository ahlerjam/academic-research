#!/usr/bin/env python3
"""Validierungslauf des NLI-Vorfilters gegen ECHTES Zitatmaterial (Issue #592-AC).

Anders als ``runner.py`` (32 KONSTRUIERTE Faelle, Issue #524, Modellvergleich
HHEM vs. mDeBERTa) laeuft dieses Skript AUSSCHLIESSLICH ``MDebertaScorer``
(der einzige nicht verworfene Kandidat, siehe README) gegen ``real-cases.json``
-- mindestens 50 Zitat-Kapitel-Paare, deren ``verbatim``-Feld ein woertliches
Fair-Use-Zitat aus einem real veroeffentlichten, oeffentlich zugaenglichen
Paper ist (Quelle je Case in ``source``).

Aufruf:
    uv run python evals/524-nli-prefilter/run_real_validation.py

Schreibt ``real-validation-results.json`` (Format analog
``live-verification.json``, Issue #524) mit TP/FP/FN/TN, Precision/Recall/
Accuracy und der fuer AC6 entscheidenden FP-Rate (falsch durchgewunkene
Verzerrungen).
"""

from __future__ import annotations

import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from academic_vault.nli_prefilter import MDebertaScorer, build_premise  # noqa: E402

CASES_PATH = Path(__file__).parent / "real-cases.json"
RESULTS_PATH = Path(__file__).parent / "real-validation-results.json"


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


def run(cases: list[dict]) -> dict:
    scorer = MDebertaScorer()
    details = []
    total_latency = 0.0
    for case in cases:
        premise = build_premise(
            case.get("context_before"), case["verbatim"], case.get("context_after")
        )
        hypothesis = case["chapter_claim"]
        start = time.monotonic()
        verdict, raw = scorer.predict(premise, hypothesis)
        elapsed = time.monotonic() - start
        total_latency += elapsed
        details.append(
            {
                "id": case["id"],
                "expected": case["label"],
                "actual": verdict,
                "raw_score": raw,
                "latency_s": elapsed,
                "verzerrend_type": case.get("verzerrend_type"),
                "source_url": case.get("source", {}).get("url"),
            }
        )

    tp = sum(1 for d in details if d["expected"] == "faithful" and d["actual"] == "faithful")
    fp = sum(1 for d in details if d["expected"] == "verzerrend" and d["actual"] == "faithful")
    fn = sum(1 for d in details if d["expected"] == "faithful" and d["actual"] == "verzerrend")
    tn = sum(1 for d in details if d["expected"] == "verzerrend" and d["actual"] == "verzerrend")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    accuracy = (tp + tn) / len(details) if details else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    fp_examples = [
        d for d in details if d["expected"] == "verzerrend" and d["actual"] == "faithful"
    ]

    return {
        "model": scorer.name,
        "n_cases": len(details),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "accuracy": accuracy,
        "fp_rate": fp_rate,
        "avg_latency_s": total_latency / len(details) if details else 0.0,
        "fp_examples": fp_examples,
        "details": details,
    }


def main() -> None:
    import torch
    import transformers

    cases = load_cases()
    result = run(cases)

    payload = {
        "run_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": {
            "transformers_version": transformers.__version__,
            "torch_version": torch.__version__,
            "python_version": platform.python_version(),
            "device": "cpu",
        },
        "n_source_papers": len({c["source"]["arxiv_id"] for c in cases if "source" in c}),
        "result": result,
    }
    RESULTS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Cases: {result['n_cases']}")
    print(f"TP={result['tp']} FP={result['fp']} FN={result['fn']} TN={result['tn']}")
    print(
        f"Precision: {result['precision']:.3f}  Recall: {result['recall']:.3f}  "
        f"Accuracy: {result['accuracy']:.3f}  FP-Rate: {result['fp_rate']:.3f}"
    )
    print(f"Ergebnis geschrieben: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
