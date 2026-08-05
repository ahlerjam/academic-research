"""Akzeptanz-Guards fuer Issue #614 -- Baseline-Skript fuer die Trigger-Evals.

Testet die reine Logik des Baseline-Skripts (Fallsammlung, Aggregation,
Fehlerbehandlung) hermetisch -- ohne echten claude-CLI-Aufruf. Der reale Lauf
(871 Live-Klassifikationen) ist kein pytest-Test, sondern ein manueller
Skript-Aufruf (docs/evals/README.md, Konvention "Reports entstehen manuell").
"""

from __future__ import annotations

from scripts.dev.run_trigger_baseline import (
    CaseResult,
    aggregate,
    classify_case,
    collect_cases,
)

from tests.evals.eval_runner import ClaudeCliError
from tests.evals.test_triggers import ALL_SKILLS, _load_trigger_evals


def test_collect_cases_matches_live_trigger_evals_count():
    """Nachzaehlen statt hartkodieren (Plan-Risiko 2): Faelle nie aus einer
    Konstante uebernehmen, immer live aus evals/*/trigger_evals.json lesen."""
    cases = collect_cases(ALL_SKILLS)
    expected_total = 0
    expected_skills_with_evals = 0
    for skill in ALL_SKILLS:
        evals = _load_trigger_evals(skill)
        if not evals:
            continue
        expected_skills_with_evals += 1
        expected_total += len(evals.get("should_trigger", []))
        expected_total += len(evals.get("should_not_trigger", []))
    assert len(cases) == expected_total
    assert expected_skills_with_evals > 0
    # AC7-Vorbedingung: Skript zaehlt selbst, kodiert keine Zahl aus Issue/Plan.
    assert len(cases) != 765, "765 ist die veraltete Issue-Zahl -- darf nicht zufaellig stimmen"


def test_collect_cases_returns_skill_kind_prompt_tuples():
    cases = collect_cases(["literature-excel"])
    assert cases, "literature-excel sollte trigger_evals.json haben"
    for skill, kind, prompt in cases:
        assert skill == "literature-excel"
        assert kind in {"should_trigger", "should_not_trigger"}
        assert isinstance(prompt, str) and prompt


def test_collect_cases_skips_skills_without_trigger_evals():
    cases = collect_cases(["not-a-real-skill-xyz"])
    assert cases == []


def test_classify_case_wraps_cli_error_without_raising(monkeypatch):
    """ClaudeCliError darf nicht als Fehlklassifikation in Recall/FPR
    einfliessen (Plan-Risiko 6) -- sie muss getrennt sichtbar bleiben."""

    def _boom(*, system: str, user: str, model: str):
        raise ClaudeCliError("Rate limit", exit_code=1, api_error_status=429)

    monkeypatch.setattr(
        "scripts.dev.run_trigger_baseline.call_claude_with_tokens",
        _boom,
    )
    result = classify_case("literature-excel", "should_trigger", "irgendein Prompt")
    assert result.error is not None
    assert "Rate limit" in result.error
    assert result.classification is None


def test_classify_case_returns_normalized_classification(monkeypatch):
    def _fake(*, system: str, user: str, model: str):
        return " LITERATURE-EXCEL \n", 42, 7

    monkeypatch.setattr(
        "scripts.dev.run_trigger_baseline.call_claude_with_tokens",
        _fake,
    )
    result = classify_case("literature-excel", "should_trigger", "mach das xlsx")
    assert result.classification == "literature-excel"
    assert result.tokens_in == 42
    assert result.tokens_out == 7
    assert result.error is None


def test_classify_case_empty_output_becomes_none(monkeypatch):
    def _fake(*, system: str, user: str, model: str):
        return "", 1, 0

    monkeypatch.setattr(
        "scripts.dev.run_trigger_baseline.call_claude_with_tokens",
        _fake,
    )
    result = classify_case("literature-excel", "should_not_trigger", "irrelevanter Prompt")
    assert result.classification == "none"


def test_aggregate_computes_recall_and_fpr():
    results = [
        CaseResult("skill-a", "should_trigger", "p1", "skill-a", None, 10, 5),
        CaseResult("skill-a", "should_trigger", "p2", "none", None, 10, 5),
        CaseResult("skill-a", "should_not_trigger", "p3", "skill-a", None, 10, 5),
        CaseResult("skill-a", "should_not_trigger", "p4", "none", None, 10, 5),
    ]
    agg = aggregate(results)
    st = agg["skill-a"]
    assert st["should_trigger_total"] == 2
    assert st["should_trigger_hits"] == 1
    assert st["recall"] == 0.5
    assert st["should_not_trigger_total"] == 2
    assert st["should_not_trigger_false_pos"] == 1
    assert st["fpr"] == 0.5
    assert st["tokens_in"] == 40
    assert st["tokens_out"] == 20


def test_aggregate_lists_misclassified_prompts_individually():
    """AC3: Fehlklassifikationen einzeln benannt, nicht nur gezaehlt."""
    results = [
        CaseResult("skill-a", "should_trigger", "verpasster Prompt", "none", None, 1, 1),
        CaseResult(
            "skill-a", "should_not_trigger", "faelschlich getriggert", "skill-a", None, 1, 1
        ),
    ]
    agg = aggregate(results)
    misclassified = agg["skill-a"]["misclassified"]
    assert {"kind": "should_trigger", "prompt": "verpasster Prompt", "got": "none"} in misclassified
    assert {
        "kind": "should_not_trigger",
        "prompt": "faelschlich getriggert",
        "got": "skill-a",
    } in misclassified


def test_aggregate_keeps_cli_errors_separate_from_misclassifications():
    results = [
        CaseResult("skill-a", "should_trigger", "p1", None, "Rate limit", 0, 0),
    ]
    agg = aggregate(results)
    st = agg["skill-a"]
    assert st["should_trigger_total"] == 0, "Fehler duerfen nicht in die Recall-Quote einfliessen"
    assert len(st["errors"]) == 1
    assert st["errors"][0]["error"] == "Rate limit"
    assert st["misclassified"] == []


def test_aggregate_handles_skill_with_only_should_trigger_cases():
    results = [CaseResult("skill-b", "should_trigger", "p1", "skill-b", None, 1, 1)]
    agg = aggregate(results)
    assert agg["skill-b"]["recall"] == 1.0
    assert agg["skill-b"]["fpr"] is None
