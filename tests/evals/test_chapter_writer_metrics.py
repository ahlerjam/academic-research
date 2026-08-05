"""Inhaltliche Qualitaetsmetrik fuer chapter-writer (Issue #606).

Bis #606 galt fuer ``evals/chapter-writer/`` ``structural``: gruen hiess „das
Schema stimmt", nicht „der Entwurf taugt". Diese Suite misst stattdessen
**Zitatintegritaet am Kapitelentwurf** — der Defekt, der ungeprueft in die
abgegebene Arbeit wandert:

- loest jeder Klammer- oder Narrativbeleg gegen ein Vault-Paper auf,
- ist jedes Direktzitat woertlich im Vault auffindbar,
- wird ueberhaupt dicht genug belegt (>= 5 Quellen/1000 Woerter, Schwelle aus
  ``skills/chapter-writer/references/quality-review-config.md``).

Ohne ``ANTHROPIC_API_KEY``, ohne Netz: der Vault ist eine temporaere
SQLite-Datei, gefahren werden die Produktionsfunktionen
``verify_citations()`` und ``search_quote_text()``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "chapter-writer"
RUNNER_PATH = EVAL_DIR / "runner.py"
CORPUS_PATH = EVAL_DIR / "corpus.json"
COUNTER_PATH = EVAL_DIR / "counter_examples.json"


def _load_runner():
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} — ohne ihn bliebe chapter-writer 'structural' (Issue #606)."
    )
    spec = importlib.util.spec_from_file_location("chapter_writer_metrics_runner", RUNNER_PATH)
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
# Der Korpus: Sollwerte committed, Entwuerfe vorhanden.
# ---------------------------------------------------------------------------


def test_corpus_drafts_exist_and_are_substantial(corpus):
    for case in corpus["cases"]:
        draft = EVAL_DIR / case["draft"]
        assert draft.exists(), f"{case['id']}: Entwurf {case['draft']} fehlt."
        assert len(draft.read_text(encoding="utf-8").split()) >= 100, (
            f"{case['id']}: Entwurf zu kurz, um eine Zitatdichte sinnvoll zu messen."
        )


def test_threshold_is_sourced_from_the_skill(corpus):
    """Die Schwelle stammt aus der Skill-Konfiguration, nicht aus dem Runner."""
    assert corpus["thresholds"]["citation_density_per_1000_min"] == 5.0
    source = corpus["thresholds"]["source"]
    assert "quality-review-config.md" in source
    assert (REPO_ROOT / "skills/chapter-writer/references/quality-review-config.md").exists()


# ---------------------------------------------------------------------------
# AC: Die Metrik bewertet Inhalt und laeuft offline durch.
# ---------------------------------------------------------------------------


def test_corpus_matches_expected_scores(results, corpus):
    """Jeder Sollwert aus corpus.json wird exakt reproduziert (#628-Lehre)."""
    by_id = {case["id"]: case for case in results["cases"]}
    assert set(by_id) == {case["id"] for case in corpus["cases"]}
    for case in corpus["cases"]:
        measured = by_id[case["id"]]["measured"]
        for key, expected in case["expected"].items():
            assert measured[key] == expected, (
                f"{case['id']}: {key} gemessen {measured[key]!r}, "
                f"committed {expected!r} (Issue #606)."
            )


def test_clean_drafts_pass(results):
    """Alle Referenz-Entwuerfe bestehen — sonst misst die Metrik nur Rauschen."""
    assert results["passed"] == results["total"] == 3
    for case in results["cases"]:
        assert case["measured"]["verdict"] == "PASS", case["measured"]["failures"]


def test_both_citation_forms_are_recognised(runner):
    """Narrativ UND klammernd — nur eine Form zu kennen misst die Dichte zu niedrig."""
    text = "Bauer (2021) zeigt das; ein zweiter Beleg steht am Satzende (Weiss, 2018)."
    citations = runner.extract_citations(text)
    assert [(c["family"], c["year"]) for c in citations] == [("Bauer", 2021), ("Weiss", 2018)]


def test_word_count_excludes_headings_and_citation_parentheses(runner):
    """Die Zaehlregel ist dokumentiert und nachrechenbar."""
    text = "## Ueberschrift mit vier Woertern\n\nEin Satz mit Beleg (Weiss, 2018).\n"
    assert runner.count_words(text) == 4


# ---------------------------------------------------------------------------
# AC: Gegenprobe — jede Verschlechterung schlaegt aus.
# ---------------------------------------------------------------------------


def test_counter_examples_are_rejected(results):
    cases = results["counter_examples"]
    assert len(cases) == 3, "Drei Defekte, drei Gegenproben (Issue #606, AC3)."
    for case in cases:
        assert case["rejected"], (
            f"Gegenprobe {case['id']} ({case['label']}) wurde NICHT als FAIL erkannt — "
            f"die Metrik zeigt eine Verschlechterung nicht an (Issue #606, AC3)."
        )
        assert case["matches_expected"], (
            f"{case['id']}: gemessene Werte weichen vom committeten Sollergebnis ab: "
            f"{case['measured']}"
        )


def test_each_defect_path_is_covered_exactly_once(results):
    """Drei getrennte Pruefpfade — nicht ein scharfer Check, der alles faengt."""
    defects = sorted(case["defect"] for case in results["counter_examples"])
    assert defects == [
        "citation_density_per_1000",
        "citations_unresolved",
        "quotes_not_verbatim",
    ]
    for case in results["counter_examples"]:
        assert len(case["measured"]["failures"]) == 1, (
            f"{case['id']}: {len(case['measured']['failures'])} Befunde statt genau einem — "
            f"dann ist nicht belegt, welcher Pruefpfad ausschlaegt: "
            f"{case['measured']['failures']}"
        )


def test_counter_example_definitions_are_documented():
    data = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    assert data["component"] == "chapter-writer"
    for case in data["cases"]:
        assert len(case["why"]) >= 40, f"{case['id']}: Begruendung zu duenn."


def test_runner_needs_no_api_key():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "require_api_key" not in source
    assert "ANTHROPIC_API_KEY" not in source
