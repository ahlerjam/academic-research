#!/usr/bin/env python3
"""Offline-Qualitaetsmetrik fuer abstract-generator (Issue #606).

Gemessen wird **Abstract-Treue gegen den Quelltext**. Die Pruefpfade sind die
Qualitaetspruefungen, die ``skills/abstract-generator/SKILL.md`` selbst
auffuehrt — hier deterministisch nachgerechnet statt nur behauptet:

1. **Wortzahl** im vorgegebenen Rahmen (150-250).
2. **Keine Zitate, Kapitel- oder Abbildungsverweise** im Abstract. Ein Abstract
   steht allein; ein Verweis auf „Kapitel 4" ist ausserhalb der Arbeit wertlos.
3. **Vier IMRaD-Zuege vorhanden** (Hintergrund, Methode, Ergebnis, Einordnung).
4. **5-8 Keywords.**
5. **EN-Laenge innerhalb 10 % der DE-Laenge** — sonst ist eine der beiden
   Fassungen keine Uebersetzung, sondern eine Kuerzung.
6. **Fabrikations-Check:** jede Zahl im Abstract muss im Quelltext vorkommen.
   Das ist der einzige Pfad, der Erfindung sichtbar macht, ohne ein Modell zu
   befragen.

Kein Netz, kein Schluessel: reine Standardbibliothek.

Aufruf: python3 evals/abstract-generator/runner.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"

WORD_RE = re.compile(r"[0-9A-Za-zÄÖÜäöüß][0-9A-Za-zÄÖÜäöüß'’.,-]*")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
CITATION_RE = re.compile(r"\([^()]*,\s*\d{4}[a-z]?\)|\[\d+\]")
CROSS_REF_RE = re.compile(
    r"\b(?:Kapitel|Abschnitt|Abbildung|Tabelle|Anhang|Chapter|Section|Figure|Table|Appendix)"
    r"\s+\d+|\bsiehe\s+(?:oben|unten|Kapitel|Abschnitt)\b",
    re.I,
)

CHECK_WORD_COUNT = "word_count"
CHECK_NO_CROSS_REFS = "no_cross_references"
CHECK_IMRAD = "imrad_moves"
CHECK_KEYWORDS = "keyword_count"
CHECK_LANGUAGE_PARITY = "language_parity"
CHECK_NO_FABRICATED_NUMBERS = "no_fabricated_numbers"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def numbers_in(text: str) -> list[str]:
    """Zahlen normalisiert: Tausenderpunkte und Dezimalkomma vereinheitlicht."""
    return [match.group(0).replace(".", "").replace(",", ".") for match in NUMBER_RE.finditer(text)]


def imrad_moves(text: str, move_markers: dict[str, list[str]]) -> dict[str, bool]:
    lowered = text.lower()
    return {
        move: any(marker.lower() in lowered for marker in markers)
        for move, markers in move_markers.items()
    }


def evaluate(entry: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Prueft ein Abstract-Paar gegen seinen Quelltext."""
    source = entry["source_text"]
    abstract_de = entry["abstract_de"]
    abstract_en = entry["abstract_en"]
    keywords = entry["keywords_de"]

    words_de = count_words(abstract_de)
    words_en = count_words(abstract_en)
    moves = imrad_moves(abstract_de, spec["imrad_markers"])

    cross_refs = sorted(set(CROSS_REF_RE.findall(abstract_de)))

    # Querverweise vor dem Fabrikations-Check entfernen: die Zahl in
    # "Kapitel 5" ist ein Verweis, keine Kennzahl. Ohne diesen Schnitt wuerde
    # ein Verweis zwei Pruefpfade gleichzeitig reissen und die Gegenprobe
    # koennte nicht mehr zeigen, welcher Pfad ausschlaegt.
    body_for_numbers = CROSS_REF_RE.sub(" ", abstract_de)
    source_numbers = set(numbers_in(source))
    fabricated = sorted({n for n in numbers_in(body_for_numbers) if n not in source_numbers})

    citations = sorted(set(CITATION_RE.findall(abstract_de)))

    parity = abs(words_en - words_de) / words_de if words_de else 1.0

    checks = {
        CHECK_WORD_COUNT: spec["word_min"] <= words_de <= spec["word_max"],
        CHECK_NO_CROSS_REFS: not cross_refs and not citations,
        CHECK_IMRAD: all(moves.values()),
        CHECK_KEYWORDS: spec["keywords_min"] <= len(keywords) <= spec["keywords_max"],
        CHECK_LANGUAGE_PARITY: parity <= spec["language_parity_max"],
        CHECK_NO_FABRICATED_NUMBERS: not fabricated,
    }
    failed = sorted(name for name, ok in checks.items() if not ok)

    return {
        "words_de": words_de,
        "words_en": words_en,
        "language_parity": round(parity, 3),
        "keyword_count": len(keywords),
        "imrad_moves": moves,
        "imrad_missing": sorted(move for move, found in moves.items() if not found),
        "cross_references": cross_refs + citations,
        "fabricated_numbers": fabricated,
        "checks": checks,
        "failed_checks": failed,
        "verdict": "PASS" if not failed else "FAIL",
    }


def run_eval_cases() -> dict[str, Any]:
    """Fuehrt Korpus und Gegenproben aus. Importierbar, ohne Seiteneffekte."""
    corpus = _load(CORPUS_PATH)
    counter = _load(COUNTER_PATH)
    spec = corpus["spec"]
    sources = {source["id"]: source["text"] for source in corpus["sources"]}

    def _with_source(entry: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(entry)
        resolved["source_text"] = sources[entry["source_id"]]
        return resolved

    cases = []
    for case in corpus["cases"]:
        measured = evaluate(_with_source(case), spec)
        cases.append(
            {
                "id": case["id"],
                "label": case["label"],
                "expected": case["expected"],
                "measured": measured,
                "matches_expected": all(
                    measured[key] == value for key, value in case["expected"].items()
                ),
            }
        )

    counter_cases = []
    for case in counter["cases"]:
        measured = evaluate(_with_source(case), spec)
        counter_cases.append(
            {
                "id": case["id"],
                "label": case["label"],
                "degraded_check": case["degraded_check"],
                "expected": case["expected"],
                "measured": measured,
                "rejected": measured["verdict"] == "FAIL",
                "matches_expected": all(
                    measured[key] == value for key, value in case["expected"].items()
                ),
            }
        )

    return {
        "component": "abstract-generator",
        "spec": spec,
        "cases": cases,
        "counter_examples": counter_cases,
        "passed": sum(1 for case in cases if case["measured"]["verdict"] == "PASS"),
        "total": len(cases),
    }


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report drucken, Exit 1 bei Abweichung."""
    summary = run_eval_cases()
    ok = True
    for case in summary["cases"]:
        measured = case["measured"]
        good = case["matches_expected"] and measured["verdict"] == "PASS"
        ok = ok and good
        print(
            f"  [{'OK' if good else 'FAIL'}] {case['id']}: "
            f"{measured['words_de']} Woerter DE / {measured['words_en']} EN "
            f"(Abweichung {measured['language_parity']}), "
            f"{measured['keyword_count']} Keywords -> {measured['verdict']} "
            f"{measured['failed_checks']}"
        )
    print("\nGegenproben (muessen FAIL ergeben):")
    for case in summary["counter_examples"]:
        good = case["rejected"] and case["matches_expected"]
        ok = ok and good
        print(
            f"  [{'OK' if good else 'NICHT ERKANNT'}] {case['id']} ({case['label']}): "
            f"{case['measured']['failed_checks']}"
        )
    if not ok:
        sys.exit(1)
    print("\nAlle Sollwerte reproduziert, alle Gegenproben ausgeschlagen.")


if __name__ == "__main__":
    run_eval()
