"""Tests fuer Issue #622: disable-model-invocation nur mess-basiert markieren.

Deckt die Akzeptanzkriterien des Issues ab, nicht eine bestimmte Anzahl
markierter Skills -- das Ergebnis (aktuell: 0 markierte Skills, siehe
docs/evals/2026-08-05-disable-model-invocation-622.md) ist laut Issue-Scope
ein zulaessiger, mess-basierter Ausgang.

- AC1/AC2 (mess-basiert, begruendet): jeder markierte Skill muss im
  Ergebnis-Report mit seiner #614-Recall-Zahl referenziert sein.
- AC3 (weiter per /name erreichbar): kein markierter Skill setzt zusaetzlich
  user-invocable:false (die Gegenrichtung, Issue-Scope "Out").
- AC4 (Listing-Groesse vorher/nachher gemessen): Summe der description-Laenge
  ueber alle NICHT markierten Skills wird gegen eine gepflegte Baseline-Datei
  geprueft (Pattern wie tests/baselines/skill_sizes.json).
- AC5 (kein Skill mit relevanter Auslöserate markiert): kein markierter Skill
  liegt bei einer #614-Recall >= Schwelle aus tests/evals/test_triggers.py.
"""

import json
import re
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).parent.parent / "skills"
BASELINE_JSON = (
    Path(__file__).parent.parent
    / "docs"
    / "evals"
    / "2026-08-04-trigger-baseline-614-live-results.json"
)
REPORT_PATH = (
    Path(__file__).parent.parent / "docs" / "evals" / "2026-08-05-disable-model-invocation-622.md"
)
CHARS_BASELINE = Path(__file__).parent / "baselines" / "description_chars_622.json"

# Identisch mit der Recall-Schwelle in tests/evals/test_triggers.py -- ein
# Skill mit Recall >= Schwelle wird zuverlaessig automatisch gefunden und
# darf laut AC5 nicht markiert werden.
RECALL_FLOOR = 0.85

ALL_SKILL_MDS = sorted(SKILLS_DIR.glob("*/SKILL.md"))

# Vorab-Befund aus dem Plan-Kommentar (<!-- plan:v1 -->, Issue #622): die drei
# im Issue genannten Kandidaten, mit ihrer #614-Baseline-Recall.
ISSUE_CANDIDATES = {
    "cluster-visualizer": 1.0,
    "citation-style-import": 0.9,
    "notebook-bundle": 0.8,
}


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


def _description(fm: str) -> str:
    dm = re.search(r"^description:\s*(.*?)(?=^[a-zA-Z_][a-zA-Z0-9_-]*:|\Z)", fm, re.DOTALL | re.M)
    return " ".join(dm.group(1).split()) if dm else ""


def _has_disable_model_invocation(fm: str) -> bool:
    return bool(re.search(r"^disable-model-invocation:\s*true\s*$", fm, re.M))


def _has_user_invocable_false(fm: str) -> bool:
    return bool(re.search(r"^user-invocable:\s*false\s*$", fm, re.M))


def _marked_skills() -> list[str]:
    return [p.parent.name for p in ALL_SKILL_MDS if _has_disable_model_invocation(_frontmatter(p))]


def _baseline_recall() -> dict[str, float]:
    data = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    return {name: entry["recall"] for name, entry in data["per_skill"].items()}


def test_baseline_and_report_exist():
    assert BASELINE_JSON.exists(), "#614-Rohdaten fehlen -- Grundlage fuer die Messung"
    assert REPORT_PATH.exists(), "Ergebnis-Report fuer #622 fehlt"


def test_marked_skills_keep_user_invocable():
    """Kein markierter Skill darf zusaetzlich user-invocable:false setzen.

    Das waere die Gegenrichtung (Issue-Scope "Out") und wuerde die
    Erreichbarkeit per /name aufheben.
    """
    for name in _marked_skills():
        fm = _frontmatter(SKILLS_DIR / name / "SKILL.md")
        assert not _has_user_invocable_false(fm), (
            f"{name}: user-invocable:false widerspricht Issue #622 "
            "(nur disable-model-invocation, Skill muss per /name erreichbar bleiben)"
        )


def test_marked_skill_has_documented_recall_in_report():
    """Jeder markierte Skill muss im Ergebnis-Report mit seiner #614-Recall referenziert sein."""
    report = REPORT_PATH.read_text(encoding="utf-8")
    for name in _marked_skills():
        assert name in report, f"{name} ist markiert, aber nicht im Report #622 belegt (AC1/AC2)"


def test_no_marked_skill_exceeds_recall_floor():
    """Kein Skill mit relevanter (>= Schwelle) #614-Auslöserate ist markiert (AC5)."""
    recall = _baseline_recall()
    for name in _marked_skills():
        assert name in recall, f"{name} fehlt in der #614-Baseline -- Markierung nicht mess-basiert"
        assert recall[name] < RECALL_FLOOR, (
            f"{name}: Recall {recall[name]:.0%} >= {RECALL_FLOOR:.0%} -- wird zuverlaessig "
            "automatisch gefunden, Markierung widerspricht AC5"
        )


def test_candidate_skills_show_relevant_recall_and_stay_unmarked():
    """Regressions-Guard fuer den Vorab-Befund: alle drei Issue-Kandidaten zeigen
    hohe #614-Recall-Werte (>= 80%) und bleiben deshalb unmarkiert.

    Aendert sich die Baseline-Zahl (neuer Lauf) oder wird einer der Kandidaten
    trotzdem markiert, muss die Entscheidung explizit neu getroffen werden --
    dieser Test soll dann bewusst fehlschlagen statt still zu drften.
    """
    recall = _baseline_recall()
    for name, expected in ISSUE_CANDIDATES.items():
        assert recall[name] == pytest.approx(expected), (
            f"{name}: Baseline-Recall hat sich seit dem Plan-Kommentar geaendert "
            f"({recall[name]:.0%} statt {expected:.0%}) -- Entscheidung neu pruefen"
        )
        fm = _frontmatter(SKILLS_DIR / name / "SKILL.md")
        assert not _has_disable_model_invocation(fm), (
            f"{name}: hohe Recall ({recall[name]:.0%}) widerspricht einer Markierung (AC5)"
        )


def test_listing_size_reduction_is_measured_against_baseline():
    """AC4: Summe der description-Laenge ueber alle NICHT markierten Skills
    wird gegen eine gepflegte Baseline-Datei geprueft (Pattern wie
    tests/baselines/skill_sizes.json). Weicht die Live-Zahl ab, muss die
    Baseline (und der Report) bewusst aktualisiert werden.
    """
    baseline = json.loads(CHARS_BASELINE.read_text(encoding="utf-8"))

    total_chars = 0
    count = 0
    for path in ALL_SKILL_MDS:
        fm = _frontmatter(path)
        if _has_disable_model_invocation(fm):
            continue
        total_chars += len(_description(fm))
        count += 1

    assert count == baseline["skill_count_without_flag"], (
        f"Anzahl automatisch waehlbarer Skills hat sich geaendert "
        f"({count} statt {baseline['skill_count_without_flag']}) -- "
        "tests/baselines/description_chars_622.json aktualisieren"
    )
    assert total_chars == baseline["total_description_chars"], (
        f"Listing-Zeichenzahl hat sich geaendert ({total_chars} statt "
        f"{baseline['total_description_chars']}) -- Baseline und Report (#622) aktualisieren"
    )

    report = REPORT_PATH.read_text(encoding="utf-8")
    assert str(baseline["total_description_chars"]) in report, (
        "Report muss die Vorher/Nachher-Zeichenzahl aus der Baseline-Datei nennen"
    )
