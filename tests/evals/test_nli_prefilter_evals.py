"""Opt-in-Wrapper fuer den NLI-Vorfilter-Eval (Issue #524).

``evals/524-nli-prefilter/runner.py`` laedt zwei Hugging-Face-Modelle
(HHEM-2.1-Open, mDeBERTa-XNLI) und braucht dafuer Netzzugriff fuer den
initialen Modell-Download (~0.1B + ~0.3B Parameter). Das verletzt die
Grundregel der CI-blockierenden ``pytest tests/``-Suite ("ohne Netz, ohne
API-Key bei jedem Lauf" — ``docs/evals/STRATEGY.md``), darum bleibt dieser
Test ohne explizites Opt-in ein ``pytest.skip`` — kein stiller Download in
jedem CI-Lauf, kein Netz-Flake, der die Pipeline faelschlich rot faerbt.

Aufruf mit echten Modellen:
    RUN_LIVE_NLI_PREFILTER=1 uv run pytest tests/evals/test_nli_prefilter_evals.py

Ohne das Gate wird nur die Struktur gegen ``cases.json`` geprueft (Anzahl,
Label-Verteilung, Sprachkennzeichnung) — das kostet kein Netz und laeuft
immer mit.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNNER_PATH = REPO_ROOT / "evals" / "524-nli-prefilter" / "runner.py"
CASES_PATH = REPO_ROOT / "evals" / "524-nli-prefilter" / "cases.json"

RUN_LIVE_ENV = "RUN_LIVE_NLI_PREFILTER"


def _load_runner():
    """Laedt evals/524-nli-prefilter/runner.py als Modul (Verzeichnisname mit Ziffer/Bindestrich)."""
    assert RUNNER_PATH.exists(), f"Runner fehlt: {RUNNER_PATH}"
    spec = importlib.util.spec_from_file_location("nli_prefilter_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return _load_cases()


# ---------------------------------------------------------------------------
# Struktur-Checks: laufen IMMER, ohne Netz (AC "mind. 30 gelabelte Paare").
# ---------------------------------------------------------------------------


def test_runner_is_importable_via_pytest(runner):
    assert hasattr(runner, "run_eval_cases"), (
        "runner.py muss eine importierbare run_eval_cases()-Funktion exportieren "
        "(Issue #524, Praezedenz Issue #241)."
    )


def test_at_least_thirty_cases(cases):
    assert len(cases) >= 30, f"AC verlangt >= 30 gelabelte Paare, gefunden: {len(cases)}."


def test_both_labels_represented(cases):
    labels = {c["label"] for c in cases}
    assert labels == {"faithful", "verzerrend"}, (
        f"Beide Klassen muessen vertreten sein, gefunden: {sorted(labels)}."
    )
    faithful = sum(1 for c in cases if c["label"] == "faithful")
    verzerrend = sum(1 for c in cases if c["label"] == "verzerrend")
    assert faithful > 0 and verzerrend > 0


def test_all_cases_are_crosslingual_de_en(cases):
    """AC: DE-Kapitelbehauptung + EN-Quellkontext, explizit gekennzeichnet."""
    for case in cases:
        assert case["claim_lang"] == "de", f"{case['id']}: claim_lang muss 'de' sein."
        assert case["context_lang"] == "en", f"{case['id']}: context_lang muss 'en' sein."
        assert case["chapter_claim"].strip(), f"{case['id']}: chapter_claim fehlt."
        assert case["verbatim"].strip(), f"{case['id']}: verbatim fehlt."


def test_verzerrend_cases_carry_a_subtype(cases):
    """AC-Motivation: 'verzerrend' buendelt die vier Negativ-Verdicts des
    quote-fidelity-auditor-Schemas (overstated/context-stripped/polarity-flip/
    unsupported, Issue #523) — jeder verzerrend-Case muss einen davon tragen."""
    allowed = {"overstated", "context-stripped", "polarity-flip", "unsupported"}
    for case in cases:
        if case["label"] != "verzerrend":
            continue
        assert case.get("verzerrend_type") in allowed, (
            f"{case['id']}: verzerrend_type fehlt oder ungueltig "
            f"({case.get('verzerrend_type')!r}), erlaubt: {sorted(allowed)}."
        )


def test_case_ids_are_unique(cases):
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "Case-IDs muessen eindeutig sein."


# ---------------------------------------------------------------------------
# Live-Lauf: nur mit RUN_LIVE_NLI_PREFILTER=1 (Netz + Modell-Download).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_results(runner):
    if os.environ.get(RUN_LIVE_ENV) != "1":
        pytest.skip(
            f"Live-NLI-Lauf uebersprungen (Modell-Download braucht Netz). "
            f"Mit {RUN_LIVE_ENV}=1 pytest ausfuehren, um die echten Modelle zu laden."
        )
    return runner.run_eval_cases()


def test_live_both_models_score_all_cases(live_results, cases):
    assert len(live_results["models"]) == 2, "Erwartet HHEM + mDeBERTa-XNLI."
    for model_result in live_results["models"]:
        assert len(model_result["details"]) == len(cases), (
            f"{model_result['model']}: nicht alle Cases wurden gescort."
        )


def test_live_precision_recall_are_reported_per_model(live_results):
    for model_result in live_results["models"]:
        assert 0.0 <= model_result["precision"] <= 1.0
        assert 0.0 <= model_result["recall"] <= 1.0
