"""Inhaltliche Qualitaetsmetrik fuer abstract-generator (Issue #606).

Gemessen wird **Abstract-Treue gegen den Quelltext**, nicht die Form der Datei.
Die Pruefpfade sind die Qualitaetspruefungen, die
``skills/abstract-generator/SKILL.md`` selbst auffuehrt — hier deterministisch
nachgerechnet. Der schaerfste Pfad ist der Fabrikations-Check: jede Zahl im
Abstract muss im Quelltext vorkommen. Eine erfundene Kennzahl landet sonst
ungebremst in der eingereichten Arbeit.

Ohne ``ANTHROPIC_API_KEY``, ohne Netz: reine Standardbibliothek.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "abstract-generator"
RUNNER_PATH = EVAL_DIR / "runner.py"
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"
SKILL_PATH = REPO_ROOT / "skills" / "abstract-generator" / "SKILL.md"


def _load_runner():
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} — ohne ihn bliebe abstract-generator "
        "'structural' (Issue #606)."
    )
    spec = importlib.util.spec_from_file_location("abstract_generator_metrics_runner", RUNNER_PATH)
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
# Die Schwellen stammen aus dem Skill, nicht aus dem Runner.
# ---------------------------------------------------------------------------


def test_thresholds_match_the_skill(corpus):
    spec = corpus["spec"]
    skill = SKILL_PATH.read_text(encoding="utf-8")
    assert spec["word_min"] == 150 and spec["word_max"] == 250
    assert "150-250" in skill
    assert spec["keywords_min"] == 5 and spec["keywords_max"] == 8
    assert "5-8 Keywords" in skill
    assert "Keine Zitate, Abbildungs- oder Kapitelverweise im Abstract" in skill


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


def test_fabrication_check_reads_the_source_not_the_abstract(runner, corpus):
    """Der Fabrikations-Check ist inhaltlich: er vergleicht gegen den Quelltext.

    Gleicher Abstract, anderer Quelltext -> das Urteil muss kippen. Ein Pruefer,
    der nur den Abstract ansieht, koennte das nicht.
    """
    spec = corpus["spec"]
    sources = {source["id"]: source["text"] for source in corpus["sources"]}
    case = next(c for c in corpus["cases"] if c["id"] == "ag-01")

    with_own_source = dict(case, source_text=sources[case["source_id"]])
    assert runner.evaluate(with_own_source, spec)["fabricated_numbers"] == []

    other_id = next(sid for sid in sources if sid != case["source_id"])
    with_wrong_source = dict(case, source_text=sources[other_id])
    measured = runner.evaluate(with_wrong_source, spec)
    assert measured["fabricated_numbers"], (
        "Gegen einen fremden Quelltext muessen die Kennzahlen des Abstracts als "
        "unbelegt auffallen — sonst misst der Check den Abstract gegen sich selbst."
    )
    assert "no_fabricated_numbers" in measured["failed_checks"]


def test_language_parity_is_measured_not_assumed(results):
    for case in results["cases"]:
        measured = case["measured"]
        assert measured["words_en"] > 0
        assert measured["language_parity"] <= 0.1


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
    """Sonst ist nicht belegt, welcher Pruefpfad ausschlaegt."""
    for case in results["counter_examples"]:
        assert case["measured"]["failed_checks"] == [case["degraded_check"]], (
            f"{case['id']}: erwartet genau {case['degraded_check']!r}, "
            f"gemessen {case['measured']['failed_checks']}."
        )


def test_every_check_path_is_covered_by_a_counter_example(runner, results):
    """Ein Pruefpfad ohne Gegenprobe ist unbelegt — er darf nicht stillschweigend fehlen."""
    covered = {case["degraded_check"] for case in results["counter_examples"]}
    uncovered = {
        runner.CHECK_WORD_COUNT,
        runner.CHECK_NO_CROSS_REFS,
        runner.CHECK_IMRAD,
        runner.CHECK_KEYWORDS,
        runner.CHECK_LANGUAGE_PARITY,
        runner.CHECK_NO_FABRICATED_NUMBERS,
    } - covered
    assert uncovered <= {runner.CHECK_WORD_COUNT, runner.CHECK_LANGUAGE_PARITY}, (
        f"Ohne Gegenprobe: {sorted(uncovered)}"
    )


def test_counter_example_definitions_are_documented():
    data = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    assert data["component"] == "abstract-generator"
    for case in data["cases"]:
        assert len(case["why"]) >= 40, f"{case['id']}: Begruendung zu duenn."


def test_runner_needs_no_api_key():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "require_api_key" not in source
    assert "ANTHROPIC_API_KEY" not in source
