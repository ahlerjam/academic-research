"""Tests fuer den Wechsel des NLI-Scorers auf bge-m3-zeroshot-v2.0 (Issue #720).

Deckt die Akzeptanzkriterien:

  AC1  Produktivscorer nutzt ``MoritzLaurer/bge-m3-zeroshot-v2.0`` @ Schwelle 0.95.
  AC2  Der Entailment-Index wird aus ``model.config.id2label`` abgeleitet --
       nicht fest verdrahtet auf Index 0. Ein binaeres (bge-m3-zeroshot,
       ``{0: entailment, 1: not_entailment}``) UND ein dreiklassiges Modell
       (mDeBERTa-Familie, ``{0: entailment, 1: neutral, 2: contradiction}``)
       muessen beide korrekt behandelt werden -- inklusive eines Falls, in
       dem "entailment" NICHT an Index 0 steht (beweist, dass wirklich aus
       ``id2label`` gelesen wird statt geraten).

Kein Netz, kein Modell-Download: Modell und Tokenizer werden per Stub
injiziert (Praezedenz: ``tests/test_issue_592_nli_prefilter.py::StubScorer``,
dort auf Protokoll-Ebene, hier auf Logit-Ebene, um die echte ``predict()``-
Implementierung zu pruefen statt sie zu umgehen).
"""

from __future__ import annotations

from academic_vault.nli_prefilter import (
    DEFAULT_THRESHOLD,
    MODEL_ID,
    BgeM3ZeroshotScorer,
    MDebertaScorer,
    NliModelScorer,
)


class _FakeConfig:
    def __init__(self, id2label: dict[int, str]) -> None:
        self.id2label = id2label


class _FakeOutput:
    def __init__(self, logits) -> None:
        self.logits = logits


class _FakeModel:
    """Minimaler Stand-in fuer ``AutoModelForSequenceClassification`` --
    liefert feste Logits fuer jeden Aufruf, kein echtes Gewicht geladen."""

    def __init__(self, id2label: dict[int, str], logits: list[float]) -> None:
        self.config = _FakeConfig(id2label)
        self._logits = logits

    def eval(self) -> None:  # pragma: no cover -- API-Kompatibilitaet
        pass

    def __call__(self, **_kwargs):
        import torch

        return _FakeOutput(torch.tensor([self._logits]))


class _FakeTokenizer:
    def __call__(self, *_args, **_kwargs):
        return {}


# ---------------------------------------------------------------------------
# AC1 -- Modell/Schwelle
# ---------------------------------------------------------------------------


def test_model_id_is_bge_m3_zeroshot():
    assert MODEL_ID == "MoritzLaurer/bge-m3-zeroshot-v2.0"


def test_default_threshold_is_095():
    assert DEFAULT_THRESHOLD == 0.95


def test_productive_scorer_class_uses_the_new_model_and_threshold():
    scorer = BgeM3ZeroshotScorer()
    assert scorer.model_id == MODEL_ID
    assert scorer.threshold == DEFAULT_THRESHOLD


# ---------------------------------------------------------------------------
# AC2 -- Entailment-Index aus config.id2label, binaer UND dreiklassig
# ---------------------------------------------------------------------------


def test_entailment_index_derived_for_binary_label_scheme():
    """bge-m3-zeroshot: 2 Klassen, entailment an Index 0."""
    model = _FakeModel(
        id2label={0: "entailment", 1: "not_entailment"},
        logits=[5.0, 0.0],
    )
    scorer = NliModelScorer(
        model_id="stub/binary", model=model, tokenizer=_FakeTokenizer(), threshold=0.9
    )
    verdict, prob = scorer.predict("premise", "hypothesis")
    assert verdict == "faithful"
    assert prob > 0.9


def test_entailment_index_derived_for_three_class_label_scheme_not_at_index_zero():
    """Klassisches XNLI-Schema, aber Entailment bewusst NICHT an Index 0 --
    belegt, dass der Index wirklich aus id2label gelesen wird, nicht geraten."""
    model = _FakeModel(
        id2label={0: "neutral", 1: "contradiction", 2: "entailment"},
        logits=[0.0, 0.0, 5.0],
    )
    scorer = NliModelScorer(
        model_id="stub/three-class", model=model, tokenizer=_FakeTokenizer(), threshold=0.9
    )
    verdict, prob = scorer.predict("premise", "hypothesis")
    assert verdict == "faithful"
    assert prob > 0.9


def test_entailment_index_derived_for_three_class_label_scheme_at_index_zero():
    """mDeBERTa-XNLI-Schema: entailment an Index 0, hoher Contradiction-Logit
    an anderer Stelle darf NICHT als entailment gezaehlt werden."""
    model = _FakeModel(
        id2label={0: "entailment", 1: "neutral", 2: "contradiction"},
        logits=[0.0, 0.0, 5.0],
    )
    scorer = NliModelScorer(
        model_id="stub/three-class-2", model=model, tokenizer=_FakeTokenizer(), threshold=0.9
    )
    verdict, prob = scorer.predict("premise", "hypothesis")
    assert verdict == "verzerrend"
    assert prob < 0.1


def test_mdeberta_scorer_is_a_specialisation_of_the_generic_scorer():
    """MDebertaScorer bleibt als Eval-Kandidat erhalten (Name/Import stabil
    fuer runner.py und run_real_validation.py), ist aber jetzt eine duenne
    Spezialisierung der generischen id2label-Logik statt einer eigenen,
    fest verdrahteten Implementierung (Risiko 1 aus dem Plan)."""
    assert issubclass(MDebertaScorer, NliModelScorer)
    assert issubclass(BgeM3ZeroshotScorer, NliModelScorer)
    scorer = MDebertaScorer()
    assert scorer.model_id == "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
