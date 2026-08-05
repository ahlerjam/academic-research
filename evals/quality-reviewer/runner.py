#!/usr/bin/env python3
"""Offline-Qualitaetsmetrik fuer quality-reviewer (Issue #606).

Der Agent ist selbst ein LLM-Judge. Ihn offline zu *ersetzen* waere eine
Scheinmetrik — deshalb misst dieser Runner etwas anderes: die **Trennschaerfe
der Kriterien**, gegen die der Agent urteilt. Er rechnet die vier Metriken exakt
nach den ``Metrik-Hinweise``n aus ``agents/quality-reviewer.md`` nach und leitet
das Verdict nach der dort dokumentierten Regel ab:

- mindestens ein FAIL -> ``REVISE``
- mindestens ein FAIL **und** ``iteration >= 2`` -> ``ESCALATE`` mit
  ``BLOCKIERT_VON: iteration-limit``
- kein FAIL -> ``PASS``, auch bei ``iteration >= 2``

Die Gegenprobe faehrt denselben Text je auf einer Achse verschlechtert. Kippt das
Verdict dann nicht, unterscheiden die Kriterien nichts — der Defekt, den #454 bei
``sparring-partner`` freigelegt hat.

Kein Netz, kein Schluessel: reine Standardbibliothek.

Aufruf: python3 evals/quality-reviewer/runner.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"

#: ``Split-by-[.!?]\s+`` — woertlich der Hinweis aus agents/quality-reviewer.md.
SENTENCE_SPLIT_RE = re.compile(r"[.!?]\s+")
#: ``\bwerd(en|est|et)\b.*?(ge\w+|\w+iert)\b`` — ebenda.
PASSIVE_RE = re.compile(r"\bwerd(en|est|et)\b.*?(ge\w+|\w+iert)\b")
#: Substantive auf -ung/-heit/-keit/-ion; ab 2 je Satz gilt der Satz als nominal.
NOMINAL_RE = re.compile(r"\b[A-ZÄÖÜ][\wäöüß]*(ung|heit|keit|ion)\b")
#: Inline-Zitat-Marker ``(X, YYYY)`` oder ``[1]`` — ebenda.
CITATION_MARKER_RE = re.compile(r"\([^()]*,\s*\d{4}[a-z]?\)|\[\d+\]")
WORD_RE = re.compile(r"[0-9A-Za-zÄÖÜäöüß][0-9A-Za-zÄÖÜäöüß'-]*")

CRITERION_SENTENCE = "Satzlaenge Median"
CRITERION_PASSIVE = "Passiv-Quote"
CRITERION_NOMINAL = "Nominalstil"
CRITERION_SOURCES = "Quellen pro 1000 Woerter"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(text.strip())]
    return [part for part in parts if WORD_RE.search(part)]


def _sentence_word_count(sentence: str) -> int:
    """Woerter eines Satzes OHNE Zitat-Marker.

    Die Marker sind Belege, kein Fliesstext; wuerden sie mitzaehlen, waere ein
    stark belegter Satz automatisch laenger.
    """
    return len(WORD_RE.findall(CITATION_MARKER_RE.sub(" ", sentence)))


def measure(text: str) -> dict[str, Any]:
    """Rechnet die vier Kriterien nach den Metrik-Hinweisen des Agents nach."""
    sentences = split_sentences(text)
    lengths = [_sentence_word_count(sentence) for sentence in sentences]
    n_sentences = len(sentences)

    n_passive = sum(1 for sentence in sentences if PASSIVE_RE.search(sentence))
    n_nominal = sum(1 for sentence in sentences if len(NOMINAL_RE.findall(sentence)) >= 2)
    n_markers = len(CITATION_MARKER_RE.findall(text))
    n_words = sum(lengths)

    return {
        "n_sentences": n_sentences,
        "median_sentence_words": round(statistics.median(lengths), 1) if lengths else 0.0,
        "passive_share_pct": round(100.0 * n_passive / n_sentences, 1) if n_sentences else 0.0,
        "nominal_share_pct": round(100.0 * n_nominal / n_sentences, 1) if n_sentences else 0.0,
        "sources_per_1000": round(1000.0 * n_markers / n_words, 1) if n_words else 0.0,
        "n_words": n_words,
        "n_citation_markers": n_markers,
    }


def judge(measured: dict[str, Any], thresholds: dict[str, Any], iteration: int) -> dict[str, Any]:
    """Leitet das Verdict aus den Messwerten ab — die Regel steht im Agent."""
    failed = []
    median = measured["median_sentence_words"]
    if not (
        thresholds["median_sentence_words_min"] <= median <= thresholds["median_sentence_words_max"]
    ):
        failed.append(CRITERION_SENTENCE)
    if measured["passive_share_pct"] > thresholds["passive_share_pct_max"]:
        failed.append(CRITERION_PASSIVE)
    if measured["nominal_share_pct"] > thresholds["nominal_share_pct_max"]:
        failed.append(CRITERION_NOMINAL)
    if measured["sources_per_1000"] < thresholds["sources_per_1000_min"]:
        failed.append(CRITERION_SOURCES)

    if not failed:
        verdict, blocked_by = "PASS", "none"
    elif iteration >= 2:
        verdict, blocked_by = "ESCALATE", "iteration-limit"
    else:
        verdict, blocked_by = "REVISE", "none"
    return {"failed_criteria": failed, "verdict": verdict, "blocked_by": blocked_by}


def evaluate(text: str, thresholds: dict[str, Any], iteration: int) -> dict[str, Any]:
    measured = measure(text)
    measured.update(judge(measured, thresholds, iteration))
    return measured


def run_eval_cases() -> dict[str, Any]:
    """Fuehrt Korpus und Gegenproben aus. Importierbar, ohne Seiteneffekte."""
    corpus = _load(CORPUS_PATH)
    counter = _load(COUNTER_PATH)
    thresholds = corpus["thresholds"]

    cases = []
    for case in corpus["cases"]:
        measured = evaluate(case["text"], thresholds, int(case["iteration"]))
        cases.append(
            {
                "id": case["id"],
                "label": case["label"],
                "iteration": case["iteration"],
                "expected": case["expected"],
                "measured": measured,
                "matches_expected": all(
                    measured[key] == value for key, value in case["expected"].items()
                ),
            }
        )

    baseline_id = counter["baseline_case"]
    baseline = next(case for case in cases if case["id"] == baseline_id)

    counter_cases = []
    for case in counter["cases"]:
        measured = evaluate(case["text"], thresholds, int(case["iteration"]))
        counter_cases.append(
            {
                "id": case["id"],
                "label": case["label"],
                "degraded_criterion": case["degraded_criterion"],
                "expected": case["expected"],
                "measured": measured,
                "flipped": (
                    baseline["measured"]["verdict"] == "PASS" and measured["verdict"] != "PASS"
                ),
                "matches_expected": all(
                    measured[key] == value for key, value in case["expected"].items()
                ),
            }
        )

    return {
        "component": "quality-reviewer",
        "thresholds": thresholds,
        "baseline_case": baseline_id,
        "cases": cases,
        "counter_examples": counter_cases,
        "passed": sum(1 for case in cases if case["matches_expected"]),
        "total": len(cases),
    }


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report drucken, Exit 1 bei Abweichung."""
    summary = run_eval_cases()
    ok = True
    for case in summary["cases"]:
        measured = case["measured"]
        mark = "OK" if case["matches_expected"] else "FAIL"
        ok = ok and case["matches_expected"]
        print(
            f"  [{mark}] {case['id']} (iteration={case['iteration']}): "
            f"Median {measured['median_sentence_words']}, "
            f"Passiv {measured['passive_share_pct']} %, "
            f"Nominal {measured['nominal_share_pct']} %, "
            f"Quellen/1000 {measured['sources_per_1000']} -> "
            f"{measured['verdict']} ({measured['blocked_by']})"
        )
    print("\nGegenproben (Verdict muss von PASS abkippen):")
    for case in summary["counter_examples"]:
        good = case["flipped"] and case["matches_expected"]
        ok = ok and good
        mark = "OK" if good else "NICHT ERKANNT"
        print(
            f"  [{mark}] {case['id']} ({case['label']}): "
            f"{case['measured']['verdict']} — {case['measured']['failed_criteria']}"
        )
    if not ok:
        sys.exit(1)
    print("\nAlle Sollwerte reproduziert, alle Gegenproben kippen das Verdict.")


if __name__ == "__main__":
    run_eval()
