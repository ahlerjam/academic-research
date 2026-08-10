"""Test fuer den Folge-Review-Fund an PR #831 (Issue #807).

Die "aus"-Bedingung der #804-Kostenmessung (``build_reranker_ablation_804.py
--cost-condition aus``) soll den ECHTEN Produktivpfad ohne gesetzten Schalter
messen (#807-Default). Vor diesem Fix setzte ``run_cost_condition`` fuer
``condition == "aus"`` weiterhin explizit ``VAULT_RERANK_LOCAL_DISABLE=1`` --
das misst den Alias-Disable-Pfad (#714) statt des Default-Pfads und
widerspricht der Behauptung "ohne gesetzten Schalter" in PR-Text und
Verifikations-Report.

Kein Modell-Load, kein Netz noetig: dieser Test prueft nur die
Env-Var-Manipulation vor dem eigentlichen Suchaufruf, nicht den vollen
Such-Pfad (der bleibt bewusst nicht pytest-abgedeckt, siehe Modul-Docstring
von ``build_reranker_ablation_804.py``).
"""

from __future__ import annotations

import os

import pytest
from academic_vault.retrieval import (
    ENV_LOCAL_RERANKER_DISABLE,
    ENV_RERANKER_ENABLED,
    resolve_reranker_enabled,
)
from scripts.eval.build_reranker_ablation_804 import _apply_condition_env


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_LOCAL_RERANKER_DISABLE, raising=False)
    monkeypatch.delenv(ENV_RERANKER_ENABLED, raising=False)


def test_aus_condition_sets_no_switch_at_all() -> None:
    """AC4: 'aus' darf WEDER den Alias noch den kanonischen Schalter setzen --
    sonst wird ein gesetzter Schalter statt des Default-Pfads gemessen."""
    # Simuliert den Zustand, den _CloudKeyGuard vorher hinterlaesst (erzwingt
    # ACADEMIC_RESEARCH_RERANKER_ENABLED=1), um zu beweisen, dass die
    # 'aus'-Bedingung das wieder zuruecknimmt statt nur den Alias zu setzen.
    os.environ[ENV_RERANKER_ENABLED] = "1"
    try:
        _apply_condition_env("aus")
        assert ENV_LOCAL_RERANKER_DISABLE not in os.environ
        assert ENV_RERANKER_ENABLED not in os.environ
    finally:
        os.environ.pop(ENV_RERANKER_ENABLED, None)


def test_aus_condition_measures_the_real_default_path() -> None:
    """AC4: Ohne gesetzten Schalter muss resolve_reranker_enabled() ueber den
    #807-Default (bzw. die Config) auf False landen -- das IST der Produktivpfad."""
    _apply_condition_env("aus")
    assert ENV_LOCAL_RERANKER_DISABLE not in os.environ
    assert ENV_RERANKER_ENABLED not in os.environ
    assert resolve_reranker_enabled() is False


def test_an_condition_still_sets_the_canonical_switch_explicitly() -> None:
    """AC4 (Regression): 'an' muss weiterhin explizit einschalten, weil der
    Produktivdefault seit #807 AUS ist -- sonst misst 'an' zweimal 'aus'."""
    _apply_condition_env("an")
    assert ENV_LOCAL_RERANKER_DISABLE not in os.environ
    assert os.environ.get(ENV_RERANKER_ENABLED) == "1"
    assert resolve_reranker_enabled() is True
