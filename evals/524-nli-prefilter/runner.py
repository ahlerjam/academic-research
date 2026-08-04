#!/usr/bin/env python3
"""Eval-Runner fuer den NLI-Batch-Vorfilter (Issue #524).

Prueft, ob ein lokales NLI-Modell taugt, um Zitat-Kapitel-Paare VOR dem
Richter-Subagenten (``quote-fidelity-auditor``, Issue #523, aktuell
**reverted** nach PR #582/#584) grob vorzufiltern. Getestet werden zwei
Modelle gegen ``cases.json`` (32 synthetische DE-Kapitelbehauptung / EN-
Quellkontext-Paare):

* ``vectara/hallucination_evaluation_model`` (HHEM-2.1-Open, Apache-2.0) —
  ``model.predict([(premise, hypothesis), ...])`` liefert einen
  Konsistenz-Score in [0, 1]. Ladepfad braucht ``trust_remote_code=True``
  (Modell liefert eigenen Inferenzcode mit) — siehe README, Abschnitt Risiken.
* ``MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`` (MIT) —
  klassische NLI-Klassifikation (entailment/neutral/contradiction) ueber
  ``AutoModelForSequenceClassification``.

Beide Modelle werden lazy geladen (Cache-Dir-Pattern wie
``academic_vault/embedding_model.py``, Issue #372) und liegen NICHT in der
CI-blockierenden ``pytest tests/``-Kernsuite — der Download braucht Netz.
Aufruf: ``python3 evals/524-nli-prefilter/runner.py`` oder ueber
``tests/evals/test_nli_prefilter_evals.py`` mit ``RUN_LIVE_NLI_PREFILTER=1``.

``MDebertaScorer`` ist seit Issue #592 kanonisch in
``academic_vault/nli_prefilter.py`` beheimatet (dort auch der produktive
Batch-Vorfilter vor ``quote-fidelity-auditor``) und wird hier importiert statt
dupliziert. Der Validierungslauf gegen ECHTES Zitatmaterial (AC aus #592)
liegt in ``real-cases.json`` / ``run_real_validation.py`` in diesem
Verzeichnis, getrennt von den 32 konstruierten Faellen unten.

Premise/Hypothesis-Konvention: ``premise`` ist der englische Quellkontext
(``context_before`` + ``verbatim`` + ``context_after``), ``hypothesis`` ist
die deutsche Kapitelbehauptung (``chapter_claim``). Das ist die eigentliche
Kernfrage des Issues: traegt Cross-Lingual-NLI (EN-Praemisse, DE-Hypothese)
ueberhaupt, oder ist das Ergebnis bloss Zufall?
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CASES_PATH = Path(__file__).parent / "cases.json"

sys.path.insert(0, str(REPO_ROOT))
from academic_vault.nli_prefilter import (  # noqa: E402
    MDebertaScorer,
    build_premise as _build_premise_ctx,
    default_cache_dir,
)

ENV_CACHE_DIR = "NLI_PREFILTER_MODEL_CACHE"

HHEM_MODEL_ID = "vectara/hallucination_evaluation_model"
MDEBERTA_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

# HHEM-Score-Schwelle: >= HHEM_THRESHOLD gilt als "faithful" (Modellkarte:
# Scores nahe 1 = konsistent, nahe 0 = halluziniert).
HHEM_THRESHOLD = 0.5


def build_premise(case: dict) -> str:
    """Baut die englische Praemisse aus Kontext + Zitat (Vault-Quote-Format).

    Duenner Wrapper um ``academic_vault.nli_prefilter.build_premise`` fuer
    das hiesige Case-dict-Format (kein Duplikat der eigentlichen Logik).
    """
    return _build_premise_ctx(
        case.get("context_before", ""), case["verbatim"], case.get("context_after", "")
    )


class NliScorer(Protocol):
    """Minimales Interface: ein scorbares (premise, hypothesis)-Paar rein,
    ein binaeres Urteil + Rohwert raus."""

    name: str

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        """Gibt (``"faithful"``/``"verzerrend"``, Rohwert fuer den Report) zurueck."""
        ...


class HhemScorer:
    """HHEM-2.1-Open ueber ``AutoModelForSequenceClassification.predict()``."""

    name = "hhem-2.1-open"

    def __init__(self, cache_dir: str | None = None, model: Any | None = None) -> None:
        self.cache_dir = cache_dir if cache_dir is not None else default_cache_dir()
        self._model = model

    def load(self) -> Any:
        if self._model is None:
            # Lazy Import: zieht transformers/torch nach, nicht beim Modul-Import.
            from transformers import AutoModelForSequenceClassification

            self._model = AutoModelForSequenceClassification.from_pretrained(
                HHEM_MODEL_ID,
                trust_remote_code=True,
                cache_dir=self.cache_dir,
            )
        return self._model

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        model = self.load()
        scores = model.predict([(premise, hypothesis)])
        score = float(scores[0])
        verdict = "faithful" if score >= HHEM_THRESHOLD else "verzerrend"
        return verdict, score


# MDebertaScorer ist kanonisch in academic_vault.nli_prefilter (Issue #592,
# oben importiert) -- hier keine zweite Implementierung.


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


def _score_model(scorer: NliScorer, cases: list[dict]) -> dict:
    details = []
    total_latency = 0.0
    for case in cases:
        premise = build_premise(case)
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
                "claim_lang": case["claim_lang"],
                "context_lang": case["context_lang"],
            }
        )

    tp = sum(1 for d in details if d["expected"] == "faithful" and d["actual"] == "faithful")
    fp = sum(1 for d in details if d["expected"] == "verzerrend" and d["actual"] == "faithful")
    fn = sum(1 for d in details if d["expected"] == "faithful" and d["actual"] == "verzerrend")
    tn = sum(1 for d in details if d["expected"] == "verzerrend" and d["actual"] == "verzerrend")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    accuracy = (tp + tn) / len(details) if details else 0.0
    avg_latency = total_latency / len(details) if details else 0.0

    return {
        "model": scorer.name,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "accuracy": accuracy,
        "avg_latency_s": avg_latency,
        "details": details,
    }


def run_eval_cases(scorers: list[NliScorer] | None = None) -> dict:
    """Fuehrt beide (oder injizierte) Scorer gegen alle Cases aus.

    Importierbar (z. B. aus pytest), ohne zu printen oder ``sys.exit`` zu rufen.

    Rueckgabe: dict mit Schluessel ``"models"`` -> Liste von Ergebnis-dicts
    (eines pro Scorer, Format siehe :func:`_score_model`) und ``"cases"``
    (Roh-Case-Liste, fuer AC-Zaehlungen in Tests).
    """
    cases = _load_cases()
    if scorers is None:
        scorers = [HhemScorer(), MDebertaScorer()]

    results = [_score_model(scorer, cases) for scorer in scorers]
    return {"models": results, "cases": cases}


def run_eval() -> None:
    """CLI-Einstiegspunkt: fuehrt den Eval aus, printet Report."""
    summary = run_eval_cases()

    print(f"Cases: {len(summary['cases'])}")
    for model_result in summary["models"]:
        print(f"\n{'=' * 60}")
        print(f"Modell: {model_result['model']}")
        print(
            f"  TP={model_result['tp']} FP={model_result['fp']} "
            f"FN={model_result['fn']} TN={model_result['tn']}"
        )
        print(f"  Precision: {model_result['precision']:.3f}")
        print(f"  Recall:    {model_result['recall']:.3f}")
        print(f"  Accuracy:  {model_result['accuracy']:.3f}")
        print(f"  Ø Latenz/Paar: {model_result['avg_latency_s'] * 1000:.0f} ms")


if __name__ == "__main__":
    run_eval()
