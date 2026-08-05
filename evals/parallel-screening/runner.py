#!/usr/bin/env python3
"""Offline-Qualitaetsmetrik fuer parallel-screening (Issue #606).

Gemessen wird die **Ausbeute des Rankings**, nicht die Formtreue einer Ausgabe:
``skills/parallel-screening/scripts/active_learning.py::validate_ranking()``
faehrt ein Screening gegen ein Gold-Set mit bekannten Urteilen und liefert die
Recall-Kurve. Die Zufallsbaseline ist die Diagonale (nach 30 % der Liste 30 %
der Treffer); die Ausgangsreihenfolge des Gold-Sets ist bewusst schlechter als
Zufall (nur 3 von 15 Treffern in den ersten 10 Positionen). Der Runner haelt
beides dagegen.

Kein Netz, kein Modell-Download, kein API-Schluessel: ``active_learning`` ist
reine Standardbibliothek (multinomialer Naive Bayes mit Laplace-Glaettung).

Gegenprobe (``counter_examples.json``): Jede Mutation des Gold-Sets, die dem
Ranking die Information entzieht, MUSS die Schwelle reissen. Ohne diese
Gegenprobe waere nicht belegt, dass die Metrik ueberhaupt ausschlagen kann.

Aufruf: python3 evals/parallel-screening/runner.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "parallel-screening" / "scripts"
GOLD_PATH = Path(__file__).parent / "gold_screening.json"
COUNTER_PATH = Path(__file__).parent / "counter_examples.json"

sys.path.insert(0, str(SCRIPTS_DIR))

from active_learning import validate_ranking  # noqa: E402

#: Die Schwellen, an denen sich der Nutzen des Rankings entscheidet. Die
#: Diagonale (= Zufall) liegt bei 30.0 bzw. 50.0 — die Schwellen liegen
#: deutlich darueber, sonst waere die Metrik durch blosses Nichtstun erfuellbar.
RECALL_AT_30_MIN = 60.0
RECALL_AT_50_MIN = 95.0
CHECKPOINTS = (10.0, 20.0, 30.0, 50.0, 75.0, 100.0)
RETRAIN_INTERVAL = 10


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _recall_at(curve: list[dict[str, Any]], share_pct: float) -> float:
    for point in curve:
        if abs(point["share_pct"] - share_pct) < 1e-9:
            return float(point["recall_pct"])
    raise KeyError(f"Kein Checkpoint bei {share_pct} % in der Kurve.")


def initial_order_curve(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recall-Kurve OHNE Umsortierung — die Kontrolle gegen die Placebo-Metrik.

    Liegt die gemessene Kurve nicht ueber dieser hier, misst der Runner nicht
    das Ranking, sondern nur die Ausgangsreihenfolge des Korpus.
    """
    n_total = len(records)
    n_relevant = sum(1 for record in records if record.get("relevant"))
    curve = []
    for share in CHECKPOINTS:
        n_screened = min(n_total, max(1, int(round(n_total * share / 100.0))))
        n_found = sum(1 for record in records[:n_screened] if record.get("relevant"))
        curve.append(
            {
                "share_pct": round(float(share), 1),
                "n_screened": n_screened,
                "n_found": n_found,
                "recall_pct": round(100.0 * n_found / n_relevant, 1) if n_relevant else 0.0,
            }
        )
    return curve


def _apply_mutation(records: list[dict[str, Any]], case: dict[str, Any]) -> list[dict[str, Any]]:
    """Erzeugt aus dem Gold-Set die absichtlich verschlechterte Variante."""
    mutated = [dict(record) for record in records]
    mutation = case["mutation"]
    if mutation == "permute_labels":
        shift = int(case["shift"])
        labels = [bool(record.get("relevant")) for record in mutated]
        rotated = labels[shift:] + labels[:shift]
        for record, label in zip(mutated, rotated):
            record["relevant"] = label
    elif mutation == "blank_text":
        filler = case["filler"]
        for record in mutated:
            record["title"] = filler
            record["abstract"] = filler
    else:  # pragma: no cover - Schutz gegen Tippfehler im Korpus
        raise ValueError(f"Unbekannte Mutation {mutation!r} in counter_examples.json.")
    return mutated


def evaluate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Faehrt das Screening und bewertet die Kurve gegen die Schwellen."""
    result = validate_ranking(records, interval=RETRAIN_INTERVAL, checkpoints=CHECKPOINTS)
    recall_30 = _recall_at(result["curve"], 30.0)
    recall_50 = _recall_at(result["curve"], 50.0)
    failures = []
    if recall_30 < RECALL_AT_30_MIN:
        failures.append(f"Recall bei 30 % der Liste: {recall_30} < {RECALL_AT_30_MIN}")
    if recall_50 < RECALL_AT_50_MIN:
        failures.append(f"Recall bei 50 % der Liste: {recall_50} < {RECALL_AT_50_MIN}")
    return {
        "n_total": result["n_total"],
        "n_relevant": result["n_relevant"],
        "interval": result["interval"],
        "curve": result["curve"],
        "recall_at_30_pct": recall_30,
        "recall_at_50_pct": recall_50,
        "ok": not failures,
        "failures": failures,
    }


def run_eval_cases() -> dict[str, Any]:
    """Fuehrt Gold-Lauf und alle Gegenproben aus. Importierbar, ohne Seiteneffekte."""
    gold = _load(GOLD_PATH)
    records = gold["records"]
    expected = gold.get("expected", {})

    measured = evaluate(records)
    baseline = initial_order_curve(records)

    counter_results = []
    for case in _load(COUNTER_PATH)["cases"]:
        mutated = _apply_mutation(records, case)
        outcome = evaluate(mutated)
        counter_results.append(
            {
                "id": case["id"],
                "label": case["label"],
                "recall_at_30_pct": outcome["recall_at_30_pct"],
                "recall_at_50_pct": outcome["recall_at_50_pct"],
                "rejected": not outcome["ok"],
                "failures": outcome["failures"],
            }
        )

    return {
        "component": "parallel-screening",
        "screening_question": gold["screening_question"],
        "expected": expected,
        "measured": measured,
        "initial_order_curve": baseline,
        "initial_order_recall_at_30_pct": _recall_at(baseline, 30.0),
        "thresholds": {
            "recall_at_30_pct_min": RECALL_AT_30_MIN,
            "recall_at_50_pct_min": RECALL_AT_50_MIN,
        },
        "counter_examples": counter_results,
    }


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report drucken, Exit 1 bei gerissener Schwelle."""
    summary = run_eval_cases()
    measured = summary["measured"]
    print(f"Gold-Set: {measured['n_total']} Quellen, {measured['n_relevant']} relevant")
    print(f"Retrain-Intervall: {measured['interval']}")
    for point in measured["curve"]:
        print(
            f"  {point['share_pct']:5.1f} % der Liste -> "
            f"{point['n_found']}/{measured['n_relevant']} Treffer "
            f"({point['recall_pct']} % Recall)"
        )
    print(f"\nOhne Umsortierung bei 30 %: {summary['initial_order_recall_at_30_pct']} % Recall")
    print(f"Mit Umsortierung  bei 30 %: {measured['recall_at_30_pct']} % Recall")

    print("\nGegenproben:")
    for case in summary["counter_examples"]:
        mark = "OK" if case["rejected"] else "NICHT ERKANNT"
        print(f"  [{mark}] {case['id']} ({case['label']}): recall@30 %={case['recall_at_30_pct']}")

    ok = measured["ok"] and all(case["rejected"] for case in summary["counter_examples"])
    if not ok:
        for reason in measured["failures"]:
            print(f"  FAIL: {reason}")
        sys.exit(1)
    print("\nAlle Schwellen gehalten, alle Gegenproben ausgeschlagen.")


if __name__ == "__main__":
    run_eval()
