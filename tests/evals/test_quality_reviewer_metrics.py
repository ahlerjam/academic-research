"""Inhaltliche Qualitaetsmetrik fuer quality-reviewer (Issue #606).

Der Agent ist selbst ein LLM-Judge; ihn offline nachzubauen waere eine
Scheinmetrik. Gemessen wird deshalb die **Trennschaerfe der Kriterien**, gegen
die er urteilt: Der Runner rechnet die vier Metriken exakt nach den
``Metrik-Hinweise``n aus ``agents/quality-reviewer.md`` nach und leitet das
Verdict nach der dort dokumentierten Regel ab.

Der Nachweis, dass das etwas unterscheidet, liegt in den Gegenproben: derselbe
Text, je auf genau einer Achse verschlechtert, muss von PASS auf REVISE kippen —
und zwar ueber genau das verschlechterte Kriterium.

Ohne ``ANTHROPIC_API_KEY``, ohne Netz: reine Standardbibliothek.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "quality-reviewer"
RUNNER_PATH = EVAL_DIR / "runner.py"
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"
AGENT_PATH = REPO_ROOT / "agents" / "quality-reviewer.md"


def _load_runner():
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} — ohne ihn bliebe quality-reviewer 'structural' (Issue #606)."
    )
    spec = importlib.util.spec_from_file_location("quality_reviewer_metrics_runner", RUNNER_PATH)
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
# Die Regeln stammen aus dem Agent, nicht aus dem Runner.
# ---------------------------------------------------------------------------


def test_thresholds_match_the_skill_configuration(corpus):
    """Die Schwellen stehen so in der Konfiguration, die den Agent aufruft."""
    thresholds = corpus["thresholds"]
    assert thresholds["median_sentence_words_min"] == 15
    assert thresholds["median_sentence_words_max"] == 25
    assert thresholds["passive_share_pct_max"] == 30.0
    assert thresholds["nominal_share_pct_max"] == 40.0
    assert thresholds["sources_per_1000_min"] == 5.0
    config = (REPO_ROOT / "skills/chapter-writer/references/quality-review-config.md").read_text(
        encoding="utf-8"
    )
    assert "15-25 Woerter" in config
    assert "< 30%" in config
    assert "< 40%" in config
    assert ">= 5" in config


def test_passive_regex_is_the_one_documented_in_the_agent(runner):
    """Der Runner erfindet keine eigene Regel — er faehrt die des Agents."""
    agent_text = AGENT_PATH.read_text(encoding="utf-8")
    assert r"\bwerd(en|est|et)\b.*?(ge\w+|\w+iert)\b" in agent_text
    assert runner.PASSIVE_RE.pattern == r"\bwerd(en|est|et)\b.*?(ge\w+|\w+iert)\b"


# ---------------------------------------------------------------------------
# AC: Die Metrik bewertet Inhalt und laeuft offline durch.
# ---------------------------------------------------------------------------


def test_corpus_matches_expected_scores(results, corpus):
    """Jeder von Hand ausgezaehlte Sollwert wird exakt reproduziert."""
    by_id = {case["id"]: case for case in results["cases"]}
    assert set(by_id) == {case["id"] for case in corpus["cases"]}
    for case in corpus["cases"]:
        measured = by_id[case["id"]]["measured"]
        for key, expected in case["expected"].items():
            assert measured[key] == expected, (
                f"{case['id']}: {key} gemessen {measured[key]!r}, committed {expected!r}."
            )


def test_verdict_rule_covers_all_three_outcomes(results):
    """PASS, REVISE und ESCALATE muessen im Korpus tatsaechlich vorkommen."""
    verdicts = {case["measured"]["verdict"] for case in results["cases"]}
    assert verdicts == {"PASS", "REVISE", "ESCALATE"}


def test_escalate_requires_both_iteration_and_open_failure(results):
    """Regel 5 des Agents: iteration >= 2 allein reicht NICHT fuer ESCALATE."""
    by_id = {case["id"]: case for case in results["cases"]}
    escalated = by_id["qr-03"]["measured"]
    assert escalated["verdict"] == "ESCALATE"
    assert escalated["blocked_by"] == "iteration-limit"
    assert escalated["failed_criteria"], "ESCALATE ohne offenes FAIL waere ein Fehlurteil."

    still_passing = by_id["qr-04"]
    assert still_passing["iteration"] == 2
    assert still_passing["measured"]["verdict"] == "PASS", (
        "Bei iteration >= 2 ohne offenes FAIL bleibt es laut Agent bei PASS — "
        "ein Automatik-ESCALATE waere ein Fehlurteil."
    )
    assert still_passing["measured"]["blocked_by"] == "none"


def test_documented_blind_spot_is_committed_not_smoothed(corpus, results):
    """Die dokumentierte Passiv-Regel erkennt 'wird'-Passiv nicht — das steht so im Korpus."""
    blind = next(case for case in corpus["cases"] if case.get("blind_spot"))
    assert blind["expected"]["passive_share_pct"] == 0.0
    assert "wird" in blind["note"]
    measured = next(case for case in results["cases"] if case["id"] == blind["id"])["measured"]
    assert measured["passive_share_pct"] == 0.0
    assert measured["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# AC: Gegenprobe — jede Verschlechterung kippt das Verdict.
# ---------------------------------------------------------------------------


def test_counter_examples_flip_the_verdict(results):
    baseline = next(case for case in results["cases"] if case["id"] == results["baseline_case"])
    assert baseline["measured"]["verdict"] == "PASS"
    cases = results["counter_examples"]
    assert len(cases) == 3
    for case in cases:
        assert case["flipped"], (
            f"{case['id']} ({case['label']}) bleibt bei "
            f"{case['measured']['verdict']} — die Kriterien unterscheiden nicht "
            f"(Issue #606, AC3)."
        )
        assert case["matches_expected"], f"{case['id']}: {case['measured']}"


def test_each_counter_example_fails_exactly_its_own_criterion(results):
    """Sonst ist nicht belegt, welches Kriterium ausschlaegt."""
    for case in results["counter_examples"]:
        assert case["measured"]["failed_criteria"] == [case["degraded_criterion"]], (
            f"{case['id']}: erwartet genau {case['degraded_criterion']!r}, "
            f"gemessen {case['measured']['failed_criteria']}."
        )


def test_counter_example_definitions_are_documented():
    data = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    assert data["component"] == "quality-reviewer"
    for case in data["cases"]:
        assert len(case["why"]) >= 40, f"{case['id']}: Begruendung zu duenn."


def test_runner_needs_no_api_key():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "require_api_key" not in source
    assert "ANTHROPIC_API_KEY" not in source
