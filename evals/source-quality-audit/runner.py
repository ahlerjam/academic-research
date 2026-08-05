#!/usr/bin/env python3
"""Offline-Qualitaetsmetrik fuer source-quality-audit (Issue #606).

Gemessen wird **der Audit-Report gegen den Quellenbestand**. Der Runner rechnet
die fuenf gewichteten Dimensionen aus ``skills/source-quality-audit/SKILL.md``
aus dem Inventar nach und vergleicht das Ergebnis mit dem, was der zugehoerige
Report behauptet:

1. **Dimensionsscores** — jede der fuenf Zahlen in der Ergebnis-Uebersicht muss
   dem aus dem Bestand berechneten Wert entsprechen (Toleranz aus ``spec``).
2. **Gesamtscore** — ``0.25*peer_review + 0.20*recency + 0.20*diversity +
   0.15*web_ratio + 0.20*coverage``.
3. **Status** — abgeleitet nach den Schwellen des Skills (OK >= 70, WARN 50-69,
   FAIL < 50); ein Report darf sich den Status nicht aussuchen.
4. **Quellenzahl** — die im Report genannte Gesamtzahl muss dem Inventar
   entsprechen.

Bezugspunkt ist damit der Bestand, nicht der Report. Gemessen wird Fabrikation
im Ergebnis, nicht die Rubrik gegen sich selbst.

Die Bandzuordnungen operationalisieren die im Skill in Prosa gegebenen Baender
linear; die Baender selbst sind unveraendert uebernommen.

Kein Netz, kein Schluessel: reine Standardbibliothek.

Aufruf: python3 evals/source-quality-audit/runner.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"

WEIGHTS = {
    "peer_review": 0.25,
    "recency": 0.20,
    "diversity": 0.20,
    "web_ratio": 0.15,
    "coverage": 0.20,
}

STATUS_OK_MIN = 70
STATUS_WARN_MIN = 50

# Baender aus SKILL.md, Abschnitt "Scoring-Dimensionen".
# (untere Anteilsgrenze, obere Anteilsgrenze, unterer Score, oberer Score)
PEER_REVIEW_BANDS = [
    (0.00, 0.15, 0, 29),
    (0.15, 0.30, 30, 49),
    (0.30, 0.50, 50, 69),
    (0.50, 0.70, 70, 89),
    (0.70, 1.00, 90, 100),
]
RECENCY_BANDS = [
    (0.00, 0.10, 0, 29),
    (0.10, 0.25, 30, 49),
    (0.25, 0.40, 50, 69),
    (0.40, 0.60, 70, 89),
    (0.60, 1.00, 90, 100),
]
# Web-Anteil ist invers: je hoeher der Anteil, desto niedriger der Score.
WEB_BANDS = [
    (0.00, 0.10, 100, 90),
    (0.10, 0.20, 89, 70),
    (0.20, 0.30, 69, 50),
    (0.30, 0.50, 49, 30),
    (0.50, 1.00, 29, 0),
]
# Diversitaets-Score nach Zahl der gerissenen Subdimensionen (SKILL.md, Dim. 3).
DIVERSITY_BY_FLAGS = {0: 95, 1: 80, 2: 60, 3: 40}
DIVERSITY_FLOOR = 20

CHECK_DIMENSION_SCORES = "dimension_scores"
CHECK_OVERALL_SCORE = "overall_score"
CHECK_STATUS = "status"
CHECK_SOURCE_COUNT = "source_count"

DIMENSION_LABELS = {
    "Peer-Review-Anteil": "peer_review",
    "Aktualität": "recency",
    "Quellen-Diversität": "diversity",
    "Web-Quellen-Anteil": "web_ratio",
    "Thematische Abdeckung": "coverage",
}

ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*\**\s*(\d+)\s*\**\s*\|\s*\**\s*([A-Z]+)\s*\**\s*\|")
TOTAL_RE = re.compile(r"^\|\s*\*\*Gesamt\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|\s*\*\*([A-Z]+)\*\*\s*\|")
SOURCE_COUNT_RE = re.compile(r"\*\*Quellen gesamt:\*\*\s*(\d+)")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _round_half_up(value: float) -> int:
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _band_score(share: float, bands: list[tuple[float, float, int, int]]) -> int:
    for low, high, low_score, high_score in bands:
        if low <= share <= high:
            span = high - low
            position = (share - low) / span if span else 0.0
            return _round_half_up(low_score + position * (high_score - low_score))
    return 0


def status_for(score: int) -> str:
    if score >= STATUS_OK_MIN:
        return "OK"
    if score >= STATUS_WARN_MIN:
        return "WARN"
    return "FAIL"


def score_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    """Rechnet die fuenf Dimensionen und den Gesamtscore aus dem Bestand."""
    sources = inventory["sources"]
    total = len(sources)

    peer_share = sum(1 for src in sources if src.get("peer_reviewed")) / total
    peer_review = _band_score(peer_share, PEER_REVIEW_BANDS)

    # Grundlagenwerke sind laut SKILL.md von der Aktualitaetsanforderung
    # ausgenommen — sie fallen aus Zaehler UND Nenner.
    current_year = inventory["current_year"]
    dated = [src for src in sources if not src.get("foundational")]
    recent_share = (
        sum(1 for src in dated if current_year - src["year"] <= 5) / len(dated) if dated else 1.0
    )
    recency = _band_score(recent_share, RECENCY_BANDS)

    web_share = sum(1 for src in sources if src["type"] == "web") / total
    web_ratio = _band_score(web_share, WEB_BANDS)

    author_counts = Counter(src["authors"][0] for src in sources)
    venue_counts = Counter(src["venue"] for src in sources)
    flags = {
        "author_concentration": max(author_counts.values()) > 3,
        "venue_concentration": max(venue_counts.values()) > 5,
        "single_country": len({src["country"] for src in sources}) == 1,
        "single_stance": len({src["stance"] for src in sources}) == 1,
        "thin_type_mix": len({src["type"] for src in sources}) < 3,
    }
    raised = sorted(name for name, hit in flags.items() if hit)
    diversity = DIVERSITY_BY_FLAGS.get(len(raised), DIVERSITY_FLOOR)

    concepts = inventory["key_concepts"]
    per_concept = {
        concept: sum(1 for src in sources if concept in src.get("concepts", []))
        for concept in concepts
    }
    coverage = _round_half_up(
        100 * sum(min(count, 3) for count in per_concept.values()) / (3 * len(concepts))
    )

    dimensions = {
        "peer_review": peer_review,
        "recency": recency,
        "diversity": diversity,
        "web_ratio": web_ratio,
        "coverage": coverage,
    }
    overall = _round_half_up(sum(dimensions[name] * weight for name, weight in WEIGHTS.items()))

    return {
        "source_count": total,
        "shares": {
            "peer_reviewed": round(peer_share, 3),
            "recent": round(recent_share, 3),
            "web": round(web_share, 3),
        },
        "diversity_flags": raised,
        "concept_coverage": per_concept,
        "dimensions": dimensions,
        "overall": overall,
        "status": status_for(overall),
    }


def parse_report(report: str) -> dict[str, Any]:
    """Liest Dimensionsscores, Gesamtscore, Status und Quellenzahl aus dem Report."""
    dimensions: dict[str, int] = {}
    statuses: dict[str, str] = {}
    overall: int | None = None
    overall_status: str | None = None

    for line in report.splitlines():
        total_match = TOTAL_RE.match(line)
        if total_match:
            overall = int(total_match.group(1))
            overall_status = total_match.group(2)
            continue
        row_match = ROW_RE.match(line)
        if row_match:
            label = row_match.group(1).strip()
            key = DIMENSION_LABELS.get(label)
            if key:
                dimensions[key] = int(row_match.group(2))
                statuses[key] = row_match.group(3)

    count_match = SOURCE_COUNT_RE.search(report)
    return {
        "dimensions": dimensions,
        "dimension_statuses": statuses,
        "overall": overall,
        "overall_status": overall_status,
        "source_count": int(count_match.group(1)) if count_match else None,
    }


def evaluate(
    case: dict[str, Any], inventory: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Prueft einen Audit-Report gegen den Bestand, auf dem er beruht."""
    computed = score_inventory(inventory)
    reported = parse_report(case["report"])
    tolerance = spec["score_tolerance"]

    drift = {
        name: reported["dimensions"][name] - computed["dimensions"][name]
        for name in WEIGHTS
        if name in reported["dimensions"]
    }
    missing = sorted(set(WEIGHTS) - set(reported["dimensions"]))
    off_dimensions = sorted(name for name, delta in drift.items() if abs(delta) > tolerance)

    overall_delta = (
        abs(reported["overall"] - computed["overall"]) if reported["overall"] is not None else 999
    )

    expected_statuses = {name: status_for(score) for name, score in reported["dimensions"].items()}
    wrong_statuses = sorted(
        name
        for name, status in reported["dimension_statuses"].items()
        if status != expected_statuses[name]
    )
    if reported["overall_status"] != status_for(reported["overall"] or 0):
        wrong_statuses.append("overall")

    checks = {
        CHECK_DIMENSION_SCORES: not off_dimensions and not missing,
        CHECK_OVERALL_SCORE: overall_delta <= tolerance,
        CHECK_STATUS: not wrong_statuses,
        CHECK_SOURCE_COUNT: reported["source_count"] == computed["source_count"],
    }
    failed = sorted(name for name, ok in checks.items() if not ok)

    return {
        "computed_dimensions": computed["dimensions"],
        "computed_overall": computed["overall"],
        "computed_status": computed["status"],
        "diversity_flags": computed["diversity_flags"],
        "reported_dimensions": reported["dimensions"],
        "reported_overall": reported["overall"],
        "reported_status": reported["overall_status"],
        "missing_dimensions": missing,
        "off_dimensions": off_dimensions,
        "overall_delta": overall_delta,
        "wrong_statuses": sorted(wrong_statuses),
        "reported_source_count": reported["source_count"],
        "checks": checks,
        "failed_checks": failed,
        "verdict": "PASS" if not failed else "FAIL",
    }


def run_eval_cases() -> dict[str, Any]:
    """Fuehrt Korpus und Gegenproben aus. Importierbar, ohne Seiteneffekte."""
    corpus = _load(CORPUS_PATH)
    counter = _load(COUNTER_PATH)
    spec = corpus["spec"]
    inventories = {inv["id"]: inv for inv in corpus["inventories"]}

    cases = []
    for case in corpus["cases"]:
        measured = evaluate(case, inventories[case["inventory_id"]], spec)
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
        measured = evaluate(case, inventories[case["inventory_id"]], spec)
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
        "component": "source-quality-audit",
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
            f"  [{'OK' if good else 'FAIL'}] {case['id']}: berechnet "
            f"{measured['computed_overall']} ({measured['computed_status']}), "
            f"Report nennt {measured['reported_overall']} "
            f"({measured['reported_status']}) -> {measured['verdict']} "
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
