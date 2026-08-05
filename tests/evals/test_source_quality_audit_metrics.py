"""Inhaltliche Qualitaetsmetrik fuer source-quality-audit (Issue #606).

Gemessen wird **der Audit-Report gegen den Quellenbestand**: Der Runner rechnet
die fuenf gewichteten Dimensionen aus ``skills/source-quality-audit/SKILL.md``
aus dem Inventar nach und prueft, ob der zugehoerige Report dieselben Zahlen und
denselben Status nennt.

Das ist bewusst nicht „die Rubrik gegen sich selbst": Bezugspunkt ist der
Bestand, nicht der Report. Ein Report, der einen Score behauptet, den das
Inventar nicht hergibt, faellt durch — genau der Fehler, der sonst ungeprueft
in die Arbeit wandert.

Ohne ``ANTHROPIC_API_KEY``, ohne Netz: reine Standardbibliothek.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "source-quality-audit"
RUNNER_PATH = EVAL_DIR / "runner.py"
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"
SKILL_PATH = REPO_ROOT / "skills" / "source-quality-audit" / "SKILL.md"


def _load_runner():
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} — ohne ihn bliebe source-quality-audit "
        "'structural' (Issue #606)."
    )
    spec = importlib.util.spec_from_file_location(
        "source_quality_audit_metrics_runner", RUNNER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def results(runner):
    assert hasattr(runner, "run_eval_cases"), "runner.py muss run_eval_cases() exportieren."
    return runner.run_eval_cases()


@pytest.fixture(scope="module")
def corpus():
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Die Rubrik stammt aus dem Skill, nicht aus dem Runner.
# ---------------------------------------------------------------------------


def test_weights_and_thresholds_match_the_skill(runner):
    skill = SKILL_PATH.read_text(encoding="utf-8")
    assert (
        "0.25*peer_review + 0.20*recency + 0.20*diversity + 0.15*web_ratio + 0.20*coverage" in skill
    )
    assert runner.WEIGHTS == {
        "peer_review": 0.25,
        "recency": 0.20,
        "diversity": 0.20,
        "web_ratio": 0.15,
        "coverage": 0.20,
    }
    assert abs(sum(runner.WEIGHTS.values()) - 1.0) < 1e-9
    assert "Status-Schwellen: OK >= 70, WARN 50-69, FAIL < 50" in skill
    assert runner.STATUS_OK_MIN == 70
    assert runner.STATUS_WARN_MIN == 50


def test_foundational_works_are_exempt_from_recency(runner, corpus):
    """SKILL.md nimmt Grundlagenwerke ausdruecklich von Aktualitaetsabzuegen aus."""
    skill = SKILL_PATH.read_text(encoding="utf-8")
    assert "Grundlagenwerk" in skill
    inventory = next(inv for inv in corpus["inventories"] if inv["id"] == "inv-strong")
    assert any(src.get("foundational") for src in inventory["sources"]), (
        "Ohne ein Grundlagenwerk im Bestand ist die Ausnahme nicht belegt."
    )
    without_exemption = dict(inventory)
    without_exemption["sources"] = [
        {k: v for k, v in src.items() if k != "foundational"} for src in inventory["sources"]
    ]
    assert (
        runner.score_inventory(without_exemption)["dimensions"]["recency"]
        < runner.score_inventory(inventory)["dimensions"]["recency"]
    ), "Die Ausnahme fuer Grundlagenwerke wirkt nicht — sie ist dann nur behauptet."


# ---------------------------------------------------------------------------
# AC: Die Metrik bewertet Inhalt und laeuft offline durch.
# ---------------------------------------------------------------------------


def test_corpus_matches_expected_scores(results, corpus):
    """Jeder committete Sollwert wird exakt reproduziert."""
    by_id = {case["id"]: case for case in results["cases"]}
    assert set(by_id) == {case["id"] for case in corpus["cases"]}
    for case in corpus["cases"]:
        measured = by_id[case["id"]]["measured"]
        for key, expected in case["expected"].items():
            assert measured[key] == expected, (
                f"{case['id']}: {key} gemessen {measured[key]!r}, committed {expected!r}."
            )
        assert measured["verdict"] == "PASS"


def test_corpus_covers_both_a_strong_and_a_weak_inventory(results):
    """Eine Metrik, die nur gute Bestaende kennt, hat keine Spannweite."""
    statuses = {case["measured"]["computed_status"] for case in results["cases"]}
    assert "OK" in statuses and ("WARN" in statuses or "FAIL" in statuses), (
        f"Nur {statuses} im Korpus — ohne schwachen Bestand misst die Skala nichts."
    )


def test_report_is_checked_against_the_inventory_not_against_itself(runner, corpus):
    """Derselbe Report, anderer Bestand -> das Urteil muss kippen."""
    inventories = {inv["id"]: inv for inv in corpus["inventories"]}
    case = next(c for c in corpus["cases"] if c["id"] == "sqa-01")

    own = runner.evaluate(case, inventories[case["inventory_id"]], corpus["spec"])
    assert own["verdict"] == "PASS"

    other_id = next(i for i in inventories if i != case["inventory_id"])
    swapped = runner.evaluate(case, inventories[other_id], corpus["spec"])
    assert swapped["verdict"] == "FAIL", (
        "Gegen einen fremden Bestand muss derselbe Report durchfallen — sonst "
        "prueft die Metrik den Report gegen sich selbst (Issue #606, Risiko Tautologie)."
    )


# ---------------------------------------------------------------------------
# AC: Gegenprobe — jede Verschlechterung schlaegt aus.
# ---------------------------------------------------------------------------


def test_counter_examples_are_rejected(results):
    cases = results["counter_examples"]
    assert len(cases) >= 3, "Weniger als drei Gegenproben belegen keine Trennschaerfe."
    for case in cases:
        assert case["rejected"], (
            f"{case['id']} ({case['label']}) bleibt PASS — die Metrik zeigt die "
            f"Verschlechterung nicht an (Issue #606, AC3)."
        )
        assert case["matches_expected"], f"{case['id']}: {case['measured']}"


def test_each_counter_example_fails_exactly_its_own_check(results):
    for case in results["counter_examples"]:
        assert case["measured"]["failed_checks"] == [case["degraded_check"]], (
            f"{case['id']}: erwartet genau {case['degraded_check']!r}, "
            f"gemessen {case['measured']['failed_checks']}."
        )


def test_inflated_report_is_caught_even_though_it_looks_well_formed(results):
    """Der 85-statt-40-Fall: strukturell tadellos, inhaltlich falsch."""
    inflated = next(case for case in results["counter_examples"] if case["id"] == "ce-sqa-01")
    measured = inflated["measured"]
    assert measured["reported_overall"] - measured["computed_overall"] >= 20
    assert measured["verdict"] == "FAIL"


def test_counter_example_definitions_are_documented():
    data = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    assert data["component"] == "source-quality-audit"
    for case in data["cases"]:
        assert len(case["why"]) >= 40, f"{case['id']}: Begruendung zu duenn."


def test_runner_needs_no_api_key():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "require_api_key" not in source
    assert "ANTHROPIC_API_KEY" not in source
