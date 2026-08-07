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
REAL_CASES_PATH = REPO_ROOT / "evals" / "524-nli-prefilter" / "real-cases.json"
REAL_RESULTS_PATH = REPO_ROOT / "evals" / "524-nli-prefilter" / "real-validation-results.json"
NLI_README_PATH = REPO_ROOT / "evals" / "524-nli-prefilter" / "README.md"
EXTENDED_CASES_PATH = REPO_ROOT / "evals" / "524-nli-prefilter" / "extended-cases.json"
FETCH_ABSTRACTS_PATH = REPO_ROOT / "evals" / "524-nli-prefilter" / "fetch_abstracts.py"
EXTENDED_REPORT_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-06-extended-nli-goldset-721.md"

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


# ---------------------------------------------------------------------------
# Validierung an ECHTEM Zitatmaterial (Issue #592-AC) -- laeuft IMMER, ohne
# Netz: prueft nur das bereits committete Artefakt, kein Live-Modell-Aufruf.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_cases() -> list[dict]:
    return json.loads(REAL_CASES_PATH.read_text(encoding="utf-8"))["cases"]


def test_real_cases_file_has_at_least_fifty_pairs(real_cases):
    assert len(real_cases) >= 50, (
        f"Issue #592-AC verlangt >= 50 ECHTE Zitat-Paare, gefunden: {len(real_cases)}."
    )


def test_real_cases_are_traceable_to_a_real_published_source(real_cases):
    """'ECHT' heisst hier: jedes Zitat traegt eine verifizierbare Quelle --
    kein frei erfundenes Textbeispiel wie in cases.json (#524)."""
    for case in real_cases:
        source = case.get("source")
        assert source, f"{case['id']}: source-Feld fehlt (Nachweis der Echtheit)."
        assert source.get("url", "").startswith("https://arxiv.org/abs/"), (
            f"{case['id']}: source.url fehlt oder verweist nicht auf eine echte Quelle."
        )
        assert source.get("arxiv_id"), f"{case['id']}: source.arxiv_id fehlt."


def test_real_cases_both_labels_represented(real_cases):
    labels = {c["label"] for c in real_cases}
    assert labels == {"faithful", "verzerrend"}
    faithful = sum(1 for c in real_cases if c["label"] == "faithful")
    verzerrend = sum(1 for c in real_cases if c["label"] == "verzerrend")
    assert faithful > 0 and verzerrend > 0


def test_real_cases_verzerrend_carry_a_valid_subtype(real_cases):
    allowed = {"overstated", "context-stripped", "polarity-flip", "unsupported"}
    for case in real_cases:
        if case["label"] != "verzerrend":
            continue
        assert case.get("verzerrend_type") in allowed, (
            f"{case['id']}: verzerrend_type fehlt oder ungueltig ({case.get('verzerrend_type')!r})."
        )


def test_real_cases_ids_are_unique(real_cases):
    ids = [c["id"] for c in real_cases]
    assert len(ids) == len(set(ids))


def test_real_validation_results_document_fp_rate():
    """AC: Validierungsergebnis weist die Rate falsch durchgewunkener
    Verzerrungen (FP) explizit aus."""
    assert REAL_RESULTS_PATH.exists(), (
        f"Validierungsergebnis fehlt: {REAL_RESULTS_PATH} "
        "(evals/524-nli-prefilter/run_real_validation.py ausfuehren)."
    )
    data = json.loads(REAL_RESULTS_PATH.read_text(encoding="utf-8"))
    result = data["result"]
    assert isinstance(result["fp"], int)
    assert 0.0 <= result["fp_rate"] <= 1.0
    assert result["n_cases"] >= 50


def test_real_validation_readme_references_result_file_and_rule_of_three():
    """AC: README verweist auf das Validierungsergebnis; bei FP=0 bleibt der
    Rule-of-Three-Vorbehalt trotzdem genannt (kein impliziter Nullbeweis)."""
    readme = NLI_README_PATH.read_text(encoding="utf-8")
    assert "real-validation-results.json" in readme
    assert "real-cases.json" in readme
    assert "Rule-of-Three" in readme


def test_real_validation_documents_threshold_decision_when_fp_is_positive():
    """AC6: liegt die FP-Rate ueber 0, muss eine begruendete Einschalt-
    Entscheidung dokumentiert sein. Bei FP=0 ist dieser Test vacuously
    erfuellt -- die Empfehlung steht trotzdem im README (siehe Test oben)."""
    data = json.loads(REAL_RESULTS_PATH.read_text(encoding="utf-8"))
    fp = data["result"]["fp"]
    readme = NLI_README_PATH.read_text(encoding="utf-8")
    if fp > 0:
        assert "Einschalt-Empfehlung" in readme
        assert len(readme.split("Einschalt-Empfehlung", 1)[1].strip()) > 200
    else:
        # FP = 0: trotzdem muss eine (ggf. vorsichtige) Empfehlung stehen.
        assert "Einschalt-Empfehlung" in readme


# ---------------------------------------------------------------------------
# Erweitertes Goldset (Issue #721): 186 Faelle, 30 echte Paper, acht Faecher
# -- laeuft IMMER, ohne Netz: prueft nur das committete Artefakt.
# ---------------------------------------------------------------------------

EXTENDED_VERZERREND_TYPES = {
    "overgeneralization",
    "condition-stripped",
    "causal-overreach",
    "magnitude-inflation",
    "significance-flip",
}


@pytest.fixture(scope="module")
def extended_cases() -> list[dict]:
    return json.loads(EXTENDED_CASES_PATH.read_text(encoding="utf-8"))["cases"]


def test_extended_cases_has_exactly_186_entries(extended_cases):
    assert len(extended_cases) == 186, (
        f"AC verlangt 186 Faelle (30 Paper, 8 Faecher), gefunden: {len(extended_cases)}."
    )


def test_extended_cases_have_real_cases_field_structure(extended_cases):
    required = {
        "id",
        "claim_lang",
        "context_lang",
        "verzerrend_type",
        "chapter_claim",
        "context_before",
        "verbatim",
        "context_after",
        "label",
    }
    for case in extended_cases:
        missing = required - set(case)
        assert not missing, f"{case.get('id')}: fehlende Felder {missing}."
        assert case["claim_lang"] == "de"
        assert case["context_lang"] == "en"
        assert case["chapter_claim"].strip()
        assert case["verbatim"].strip()


def test_extended_cases_are_traceable_via_doi(extended_cases):
    """AC2: jeder Fall ist ueber DOI auf sein Quellpaper rueckfuehrbar."""
    for case in extended_cases:
        source = case.get("source")
        assert source, f"{case['id']}: source-Feld fehlt."
        doi = source.get("doi", "")
        assert doi.startswith("https://doi.org/"), f"{case['id']}: source.doi ungueltig ({doi!r})."


def test_extended_cases_ids_are_unique(extended_cases):
    ids = [c["id"] for c in extended_cases]
    assert len(ids) == len(set(ids)), "Case-IDs muessen eindeutig sein."


def test_extended_cases_label_balance_is_92_faithful_94_verzerrend(extended_cases):
    faithful = sum(1 for c in extended_cases if c["label"] == "faithful")
    verzerrend = sum(1 for c in extended_cases if c["label"] == "verzerrend")
    assert (faithful, verzerrend) == (92, 94), (
        f"Balance laut Issue #721: 92 faithful / 94 verzerrend, gefunden: "
        f"{faithful} faithful / {verzerrend} verzerrend."
    )


def test_extended_cases_cover_all_five_verzerrend_types(extended_cases):
    """AC: hermetischer Strukturtest prueft die Abdeckung aller fuenf
    Verzerrungstypen (eigenes Vokabular, getrennt vom 4-Typen-Schema aus
    cases.json/real-cases.json -- Risiko 4 im Plan)."""
    seen = {c["verzerrend_type"] for c in extended_cases if c["label"] == "verzerrend"}
    assert seen == EXTENDED_VERZERREND_TYPES, (
        f"Erwartet alle fuenf Typen, gefunden: {sorted(seen)}."
    )
    for vtype in EXTENDED_VERZERREND_TYPES:
        count = sum(1 for c in extended_cases if c["verzerrend_type"] == vtype)
        assert count > 0, f"Verzerrungstyp {vtype!r} kommt kein einziges Mal vor."
    for case in extended_cases:
        if case["label"] == "faithful":
            assert case["verzerrend_type"] is None, f"{case['id']}: faithful-Fall traegt einen Typ."


def test_fetch_abstracts_script_present_in_repo():
    """AC: der OpenAlex-Abrufweg ist als Skript im Repo, nicht nur als
    Issue-Kommentar-Rohtext."""
    assert FETCH_ABSTRACTS_PATH.exists(), f"Skript fehlt: {FETCH_ABSTRACTS_PATH}"
    text = FETCH_ABSTRACTS_PATH.read_text(encoding="utf-8")
    assert "api.openalex.org" in text
    assert "def reconstruct" in text


def test_fetch_abstracts_reconstruct_is_hermetic():
    """Prueft reconstruct() (OpenAlex-Inverted-Index -> Fliesstext) gegen ein
    kleines Fixture-Dict -- kein Live-Netzaufruf im Gate."""
    # fetch_abstracts.py fuehrt beim Modul-Import den eigentlichen
    # Netzabruf aus (Skriptkoerper, kein `if __name__ == "__main__"`-Gate)
    # -- ein exec_module() wuerde ihn ausloesen. Stattdessen wird das Modul
    # textuell nach der reinen Funktion durchsucht und isoliert ausgefuehrt.
    import ast

    tree = ast.parse(FETCH_ABSTRACTS_PATH.read_text(encoding="utf-8"))
    func_source = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "reconstruct":
            func_source = ast.get_source_segment(
                FETCH_ABSTRACTS_PATH.read_text(encoding="utf-8"), node
            )
            break
    assert func_source is not None, "reconstruct() nicht gefunden."
    namespace: dict = {}
    exec(func_source, namespace)  # noqa: S102 -- isolierte, hermetische Funktionsdefinition
    reconstruct = namespace["reconstruct"]

    inv = {"Hello": [0], "world": [1], "again": [2]}
    assert reconstruct(inv) == "Hello world again"
    assert reconstruct({}) == ""
    assert reconstruct(None) == ""


def test_extended_report_documents_construction_rule_and_boundary():
    """AC: Eval-Report haelt fest, dass Labels aus Transformationsregeln
    stammen (nicht Einzelurteil), und benennt die Grenze: konstruierte
    Verzerrungen != im Feld beobachtete."""
    assert EXTENDED_REPORT_PATH.exists(), f"Eval-Report fehlt: {EXTENDED_REPORT_PATH}"
    report = EXTENDED_REPORT_PATH.read_text(encoding="utf-8")
    assert "Transformationsregel" in report or "Konstruktionsregel" in report
    assert "konstruiert" in report.lower()
    assert "im Feld beobachtet" in report or "im Feld beobachteten" in report


# ---------------------------------------------------------------------------
# Live-Reproduktion der #720-Schwellenkurve (278 Faelle, 32+60+186) -- nur
# mit RUN_LIVE_NLI_PREFILTER=1 (Netz + Modell-Download).
# ---------------------------------------------------------------------------


class _BgeM3ZeroshotScorer:
    """bge-m3-zeroshot-v2.0 -- binaeres Label-Schema (0=entailment,
    1=not_entailment), im Unterschied zu mDeBERTas drei Klassen. Gleiche
    Entscheidungsregel wie ``run_big.py``/``MDebertaScorer``: faithful nur bei
    Entailment-Argmax UND Score >= Schwelle."""

    name = "bge-m3-zeroshot"

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self._model = None
        self._tokenizer = None
        self._entailment_idx = 0

    def load(self):
        if self._model is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            model_id = "MoritzLaurer/bge-m3-zeroshot-v2.0"
            self._tokenizer = AutoTokenizer.from_pretrained(model_id)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_id)
            self._model.eval()
            id2label = {int(k): v for k, v in self._model.config.id2label.items()}
            self._entailment_idx = next(
                (i for i, lab in id2label.items() if lab.lower().startswith("entail")), 0
            )
        return self._model, self._tokenizer

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        import torch

        model, tokenizer = self.load()
        inputs = tokenizer(
            premise, hypothesis, truncation=True, max_length=512, return_tensors="pt"
        )
        with torch.no_grad():
            logits = model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=-1).tolist()
        entailment_prob = float(probs[self._entailment_idx])
        argmax_idx = max(range(len(probs)), key=lambda i: probs[i])
        verdict = (
            "faithful"
            if argmax_idx == self._entailment_idx and entailment_prob >= self.threshold
            else "verzerrend"
        )
        return verdict, entailment_prob


@pytest.fixture(scope="module")
def all_278_cases(cases, real_cases, extended_cases) -> list[dict]:
    return list(cases) + list(real_cases) + list(extended_cases)


def test_live_threshold_curve_matches_720_report(runner, all_278_cases):
    """AC4: der bestehende Runner laeuft gegen das neue Set und reproduziert
    die in #720 dokumentierten Zahlen -- Schwelle 0,95 ueber alle 278 Faelle:
    bge-m3-zeroshot 1 Durchrutscher, mDeBERTa-XNLI 10 Durchrutscher."""
    if os.environ.get(RUN_LIVE_ENV) != "1":
        pytest.skip(
            f"Live-Schwellenkurve uebersprungen (Modell-Download braucht Netz). "
            f"Mit {RUN_LIVE_ENV}=1 pytest ausfuehren."
        )

    from academic_vault.nli_prefilter import MDebertaScorer

    assert len(all_278_cases) == 278

    def slip_throughs(scorer) -> int:
        count = 0
        for case in all_278_cases:
            premise = runner.build_premise(case)
            verdict, _ = scorer.predict(premise, case["chapter_claim"])
            if case["label"] == "verzerrend" and verdict == "faithful":
                count += 1
        return count

    bge_m3_slips = slip_throughs(_BgeM3ZeroshotScorer(threshold=0.95))
    mdeberta_slips = slip_throughs(MDebertaScorer(threshold=0.95))

    assert bge_m3_slips == 1, (
        f"bge-m3-zeroshot @0.95: erwartet 1 Durchrutscher, gefunden {bge_m3_slips}."
    )
    assert mdeberta_slips == 10, (
        f"mDeBERTa-XNLI @0.95: erwartet 10 Durchrutscher, gefunden {mdeberta_slips}."
    )
