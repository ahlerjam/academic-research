"""Inhaltliche Qualitaetsmetrik fuer parallel-screening (Issue #606).

Bis #606 war ``evals/parallel-screening/`` ``structural``: gepruefte Struktur,
ungepruefter Nutzen. Diese Suite misst stattdessen die **Ausbeute des
Rankings** — wie viele der bekannten Treffer nach 30 % bzw. 50 % der Liste
gefunden sind — gegen ein Gold-Set mit committeten Urteilen.

Kein ``ANTHROPIC_API_KEY``, kein Netz, kein Modell-Download: gemessen wird die
Produktionsfunktion ``active_learning.validate_ranking()``, reine
Standardbibliothek.

Drei Kontrollen halten die Metrik davon ab, ein Placebo zu sein:

1. **Gegenprobe** (``counter_examples.json``): rotierte Labels und entleerte
   Texte muessen die Schwelle reissen.
2. **Detection-Floor**: die gemessene Kurve muss ueber der Kurve OHNE
   Umsortierung liegen — sonst misst der Runner die Ausgangsreihenfolge.
3. **Zufallsbaseline**: die Schwelle liegt ueber der Diagonalen, sonst waere
   sie durch blosses Nichtstun erfuellt.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "parallel-screening"
RUNNER_PATH = EVAL_DIR / "runner.py"
GOLD_PATH = EVAL_DIR / "gold_screening.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"


def _load_runner():
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} — ohne ihn bliebe parallel-screening "
        f"'structural' (Issue #606)."
    )
    spec = importlib.util.spec_from_file_location("parallel_screening_metrics_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def results(runner):
    assert hasattr(runner, "run_eval_cases"), (
        "runner.py muss run_eval_cases() exportieren (Muster: evals/verbatim-guard/runner.py)."
    )
    return runner.run_eval_cases()


@pytest.fixture(scope="module")
def gold():
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Der Korpus selbst: Sollwerte sind committed, nicht aus dem Code hergeleitet.
# ---------------------------------------------------------------------------


def test_gold_set_is_labelled_and_hard(gold):
    """Ohne schwere Ausgangsreihenfolge waere ein hoher Recall nichts wert."""
    records = gold["records"]
    assert len(records) == gold["expected"]["n_total"]
    ids = [record["paper_id"] for record in records]
    assert len(set(ids)) == len(ids), "Doppelte paper_id im Gold-Set."
    relevant = [record for record in records if record["relevant"]]
    assert len(relevant) == gold["expected"]["n_relevant"]
    for record in records:
        assert record["title"].strip(), f"{record['paper_id']}: leerer Titel."
        assert record["abstract"].strip(), f"{record['paper_id']}: leerer Abstract."
        assert isinstance(record["relevant"], bool)


def test_expected_values_are_committed(gold):
    """#628-Lehre: exakte Sollwerte im Korpus, keine blossen Plausibilitaetsspannen."""
    expected = gold["expected"]
    for key in (
        "recall_at_30_pct",
        "recall_at_50_pct",
        "initial_order_recall_at_30_pct",
        "random_baseline_recall_at_30_pct",
    ):
        assert isinstance(expected[key], (int, float)), f"Sollwert {key} fehlt im Korpus."


# ---------------------------------------------------------------------------
# AC: Die Metrik bewertet Inhalt und laeuft offline durch.
# ---------------------------------------------------------------------------


def test_corpus_matches_expected_scores(results, gold):
    """Der gemessene Recall entspricht exakt dem committeten Sollwert."""
    expected = gold["expected"]
    measured = results["measured"]
    assert measured["n_total"] == expected["n_total"]
    assert measured["n_relevant"] == expected["n_relevant"]
    assert measured["interval"] == expected["interval"]
    assert measured["recall_at_30_pct"] == pytest.approx(expected["recall_at_30_pct"], abs=0.05), (
        f"Recall bei 30 % der Liste: gemessen {measured['recall_at_30_pct']}, "
        f"committed {expected['recall_at_30_pct']} (Issue #606)."
    )
    assert measured["recall_at_50_pct"] == pytest.approx(expected["recall_at_50_pct"], abs=0.05)


def test_ranking_beats_the_random_baseline(results, gold):
    """Die Schwelle liegt ueber der Diagonalen — Nichtstun reicht nicht."""
    diagonal = gold["expected"]["random_baseline_recall_at_30_pct"]
    assert results["thresholds"]["recall_at_30_pct_min"] > diagonal, (
        "Die Schwelle liegt auf oder unter der Zufallsdiagonale und misst damit nichts."
    )
    assert results["measured"]["recall_at_30_pct"] > diagonal
    assert results["measured"]["ok"], results["measured"]["failures"]


def test_detection_floor_against_unsorted_order(results, gold):
    """Negativkontrolle: ohne Umsortierung ist der Recall messbar schlechter."""
    unsorted_recall = results["initial_order_recall_at_30_pct"]
    assert unsorted_recall == pytest.approx(
        gold["expected"]["initial_order_recall_at_30_pct"], abs=0.05
    )
    assert unsorted_recall < gold["expected"]["random_baseline_recall_at_30_pct"], (
        "Die Ausgangsreihenfolge ist nicht schlechter als Zufall — der gemessene "
        "Lift koennte aus dem Korpusaufbau statt aus dem Ranking stammen."
    )
    assert results["measured"]["recall_at_30_pct"] > unsorted_recall + 20.0, (
        f"Umsortierung bringt nur {results['measured']['recall_at_30_pct'] - unsorted_recall} "
        f"Prozentpunkte — zu wenig, um von einer Wirkung zu sprechen."
    )


# ---------------------------------------------------------------------------
# AC: Gegenprobe — die Metrik schlaegt bei verschlechtertem Ergebnis aus.
# ---------------------------------------------------------------------------


def test_counter_examples_are_rejected(results):
    """Jede committete Verschlechterung muss die Schwelle reissen."""
    cases = results["counter_examples"]
    assert len(cases) >= 2, "Mindestens zwei Gegenproben (Issue #606, AC3)."
    for case in cases:
        assert case["rejected"], (
            f"Gegenprobe {case['id']} ({case['label']}) wurde NICHT erkannt: "
            f"recall@30 %={case['recall_at_30_pct']} — die Metrik zeigt eine "
            f"Verschlechterung nicht an und ist damit keine (Issue #606, AC3)."
        )
        assert case["failures"], f"{case['id']}: als abgelehnt gemeldet, aber ohne Begruendung."


def test_counter_example_definitions_are_documented():
    """Jede Gegenprobe traegt eine Begruendung, wozu sie da ist."""
    data = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    assert data["component"] == "parallel-screening"
    for case in data["cases"]:
        assert case["id"] and case["label"]
        assert len(case["why"]) >= 40, f"{case['id']}: Begruendung zu duenn."


def test_runner_needs_no_api_key():
    """Belegt am Quelltext, dass die Metrik offline laeuft (Issue #606, AC2)."""
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "require_api_key" not in source
    assert "ANTHROPIC_API_KEY" not in source
