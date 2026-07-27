#!/usr/bin/env python3
"""Eval-Runner fuer humanizer-de-pipeline (Issue #390).

Misst deterministisch und offline, ob der humanizer-de-Pass die Dichte
KI-typischer Formulierungen senkt: fuer jedes der drei Vorher/Nachher-Draft-
Paare unter ``drafts/`` bzw. ``drafts-after/`` wird die Anzahl kuratierter
Tell-Marker pro 100 Woerter berechnet.

Warum nicht GPTZero? Der urspruengliche Messweg (README.md) verlangte einen
externen Detektor und manuelle Bewertung — deshalb lief dieses Eval-Set nie in
CI und war faktisch tot. Die Tell-Dichte ist ein bewusst schwaecherer, dafuer
reproduzierbarer Proxy: kein Netz, kein API-Key, keine Score-Schwankungen.
GPTZero bleibt als optionaler manueller Zusatzcheck dokumentiert.

Marker-Herkunft: kuratierte Teilmenge der 45 Muster aus
``skills/humanizer-de/references/patterns.md``. Jeder Marker ist unten seiner
Musternummer zugeordnet, damit die Auswahl nachvollziehbar bleibt.

Aufruf: python3 evals/humanizer-de-pipeline/runner.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
BEFORE_DIR = EVAL_DIR / "drafts"
AFTER_DIR = EVAL_DIR / "drafts-after"

DRAFT_IDS = ["draft-01-theorie", "draft-02-methodik", "draft-03-diskussion"]

# ---------------------------------------------------------------------------
# Marker-Katalog: Musternummer aus patterns.md -> Marker-Phrasen (lowercase).
#
# Bewusst konservativ gewaehlt: nur mehrwortige, eindeutig KI-typische Wendungen.
# Einzelwoerter wie "wurde" oder "zukuenftige Forschung" sind KEINE Marker — sie
# kommen auch in gutem Fachdeutsch vor und wuerden die Messung verrauschen.
# ---------------------------------------------------------------------------
TELL_MARKERS: dict[int, tuple[str, ...]] = {
    # 1 — Uebermaessige Betonung von Symbolik / Bedeutungsfloskeln
    1: (
        "spielt eine wichtige rolle",
        "spielt eine wesentliche rolle",
        "eine rolle spielen",
        "von entscheidender bedeutung",
        "von grosser wichtigkeit",
        "ein zentrales element",
        "sollte nicht unterschaetzt werden",
    ),
    # 3 — Redaktionelle Kommentare
    3: (
        "es ist wichtig zu betonen",
        "es ist wichtig zu bemerken",
        "es ist anzumerken",
        "es laesst sich festhalten",
        "ist zu beachten, dass",
        "es sei darauf hingewiesen",
    ),
    # 5 — Abschnitts-Zusammenfassungen
    5: (
        "zusammenfassend laesst sich sagen",
        "zusammenfassend kann gesagt werden",
        "insgesamt bietet",
        "kurz gesagt",
    ),
    # 9 — Trikolon / mechanische Aufzaehlung
    9: ("erstens", "zweitens", "drittens"),
    # 11 — Vage Autoritaeten
    11: (
        "die forschung zeigt",
        "studien zeigen",
        "in der wissenschaftlichen literatur findet sich",
        "eine vielzahl von untersuchungen",
        "es gibt verschiedene",
    ),
    # 39 — Passivkonstruktionen und subjektlose Fragmente
    39: (
        "es wurde ",
        "es wurden ",
        "wurde durchgefuehrt",
        "es wird empfohlen",
        "es ist sicherzustellen",
    ),
    # 41 — Fehlkalibriertes epistemisches Vertrauen (Hedging-Haeufung)
    41: (
        "moeglicherweise",
        "es scheint so zu sein",
        "es koennte sein",
        "in gewissem masse",
        "mit vorsicht zu geniessen",
        "deuten darauf hin, dass",
        "zu sein scheinen",
        "erforderlich sein koennte",
    ),
    # 44 — Standardkapitel ohne Substanz / Fuelltext-Rahmung
    44: (
        "im rahmen dieser",
        "in diesem kapitel werden",
        "der vorliegenden untersuchung",
        "die vorliegende studie",
        "zukuenftige forschung sollte",
        "weitere forschung erforderlich",
    ),
}

# Negativkontrolle: Ein Vorher-Draft muss diese Tell-Dichte (Marker/100 Woerter)
# UEBERSCHREITEN. Liegt er darunter, misst der Marker-Katalog die KI-Tells nicht
# und ein „Rueckgang" waere Rauschen statt Signal.
DETECTION_FLOOR = 1.5

# Zielwert des Eval-Sets (README.md): >= 20 % Reduktion pro Draft.
TARGET_REDUCTION_PCT = 20.0

# Anti-Gaming: Der Nachher-Draft muss mindestens diesen Anteil der Wortmenge des
# Vorher-Drafts behalten. Ohne diese Schranke liesse sich jede Tell-Dichte durch
# radikales Kuerzen auf 0 druecken, ohne dass umformuliert wurde.
MIN_SUBSTANCE_RATIO = 0.7

# Umlaut-Normalisierung, damit Marker ASCII-stabil bleiben (die Drafts nutzen
# echte Umlaute, der Katalog oben bewusst die ae/oe/ue/ss-Form).
_UMLAUT_MAP = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "ae", "Ö": "oe", "Ü": "ue", "ß": "ss"}
)


def normalize(text: str) -> str:
    """Kleinschreibung + Umlaut-Transliteration + Whitespace-Glaettung."""
    return re.sub(r"\s+", " ", text.lower().translate(_UMLAUT_MAP))


def strip_front_matter(raw: str) -> str:
    """Entfernt den Metadaten-Kopf bis zur ersten alleinstehenden ``---``-Zeile.

    Die Kopfzeilen ("Eval-Zweck: KI-typische Tells ...") beschreiben das Eval
    selbst und wuerden die Messung verfaelschen — gemessen wird nur der Fliesstext.
    """
    lines = raw.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[idx + 1 :])
    return raw


def count_words(text: str) -> int:
    return len(re.findall(r"[\wäöüßÄÖÜ]+", text))


def count_markers(text: str) -> dict[int, int]:
    """Zaehlt Marker-Treffer je Muster in bereits normalisiertem Text."""
    hits: dict[int, int] = {}
    for pattern_no, phrases in TELL_MARKERS.items():
        count = sum(text.count(phrase) for phrase in phrases)
        if count:
            hits[pattern_no] = count
    return hits


def score_draft(path: Path) -> dict:
    """Berechnet Tell-Dichte (Marker pro 100 Woerter) fuer eine Draft-Datei."""
    body = strip_front_matter(path.read_text(encoding="utf-8"))
    normalized = normalize(body)
    hits = count_markers(normalized)
    words = count_words(body)
    total = sum(hits.values())
    density = (total / words * 100) if words else 0.0
    return {"markers": total, "words": words, "density": density, "by_pattern": hits}


def run_eval_cases() -> dict:
    """Fuehrt alle Draft-Paare aus und gibt strukturierte Ergebnisse zurueck.

    Rueckgabe:
        dict mit Schluesseln:
          - ``passed`` / ``failed`` / ``total`` (int): Paare mit gesunkener Dichte
          - ``details`` (list[dict]): je Paar draft/density_before/density_after/
            markers_before/markers_after/reduction_pct/by_pattern_before
          - ``targets_met`` (int): Paare mit >= TARGET_REDUCTION_PCT Reduktion
    """
    details: list[dict] = []
    for draft_id in DRAFT_IDS:
        before = score_draft(BEFORE_DIR / f"{draft_id}.md")
        after = score_draft(AFTER_DIR / f"{draft_id}.md")
        reduction = (
            (before["density"] - after["density"]) / before["density"] * 100
            if before["density"]
            else 0.0
        )
        details.append(
            {
                "draft": draft_id,
                "density_before": before["density"],
                "density_after": after["density"],
                "markers_before": before["markers"],
                "markers_after": after["markers"],
                "words_before": before["words"],
                "words_after": after["words"],
                "substance_ratio": (after["words"] / before["words"]) if before["words"] else 0.0,
                "reduction_pct": reduction,
                "by_pattern_before": before["by_pattern"],
                "by_pattern_after": after["by_pattern"],
            }
        )

    passed = sum(1 for d in details if d["density_after"] < d["density_before"])
    return {
        "passed": passed,
        "failed": len(details) - passed,
        "total": len(details),
        "targets_met": sum(1 for d in details if d["reduction_pct"] >= TARGET_REDUCTION_PCT),
        "details": details,
    }


def run_eval() -> None:
    """CLI-Einstiegspunkt: Report auf stdout, Exit 1 bei Regression."""
    summary = run_eval_cases()
    for d in summary["details"]:
        status = "OK" if d["density_after"] < d["density_before"] else "FAIL"
        print(
            f"  [{status}] {d['draft']}: "
            f"{d['density_before']:.2f} -> {d['density_after']:.2f} Marker/100W "
            f"({d['reduction_pct']:.1f} % Reduktion; "
            f"{d['markers_before']} -> {d['markers_after']} Marker)"
        )
        print(f"          Muster vorher: {d['by_pattern_before']}")

    print(f"\n{'=' * 50}")
    print(f"Ergebnis: {summary['passed']}/{summary['total']} Drafts mit gesunkener Tell-Dichte")
    print(
        f"Ziel (>= {TARGET_REDUCTION_PCT:.0f} % Reduktion): "
        f"{summary['targets_met']}/{summary['total']} Drafts"
    )
    print(f"Detection-Floor (Negativkontrolle): {DETECTION_FLOOR} Marker/100W")

    if summary["failed"] > 0:
        sys.exit(1)
    print("\nAlle Draft-Paare bestanden.")


if __name__ == "__main__":
    run_eval()
