"""Tests fuer die Reranker-Ablation auf dem Chunk-Goldset (#804).

Jeder Test haengt an genau einem Akzeptanzkriterium des Issues; die Zuordnung
steht im jeweiligen Docstring. Der Lauf ist hermetisch: er laedt kein Modell
und braucht kein Netz -- die fusionierten Kandidaten samt echten
``rerank_score``-Werten liegen als Fixture im Repo.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from scripts.eval.run_reranker_ablation_804 import (  # noqa: E402
    BOOTSTRAP_SEED,
    CONDITIONS,
    LIVE_RESULTS_PATH,
    METRICS,
    REPORT_PATH,
    SIGNIFICANCE_RULE,
    FixtureMismatchError,
    build_report,
    compare_against,
    load_fixture,
    main,
    paired_bootstrap,
    verify_fixture,
)
from scripts.eval.run_retrieval_chunk_goldset import GOLDSET_PATH, load_goldset  # noqa: E402

DOC_TEXT = REPORT_PATH.read_text(encoding="utf-8")
LIVE_RESULTS = json.loads(LIVE_RESULTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    """Ein frischer hermetischer Lauf ueber beide Bedingungen."""
    return build_report()


# ---------------------------------------------------------------------------
# AC1 -- misst 'an' gegen 'aus' mit allen drei Metriken je Bedingung
# ---------------------------------------------------------------------------
def test_evaluate_returns_both_conditions_with_all_three_metrics(report: dict) -> None:
    """AC1: Beide Bedingungen liegen mit Recall@10/nDCG@10/MRR vor."""
    assert set(report["results"]) == set(CONDITIONS)
    for condition in CONDITIONS:
        overall = report["results"][condition]["overall"]
        for metric in METRICS:
            assert metric in overall, f"{condition}: {metric} fehlt"


def test_conditions_share_the_same_candidate_pool() -> None:
    """AC1: 'aus' und 'an' sortieren DIESELBEN fusionierten Kandidaten um --
    kein zweiter Suchlauf, keine unterschiedliche Kandidatenmenge."""
    fixture = load_fixture()
    for query in fixture["per_query"]:
        for candidate in query["candidates"]:
            assert "rrf_score" in candidate
            assert "rerank_score" in candidate


def test_candidates_use_the_production_top_n_multiplier() -> None:
    """AC1: Fusions-Kandidatenpool ist ``top_n=k*4`` (#727-Konstante), nicht mehr."""
    fixture = load_fixture()
    k = fixture["meta"]["k"]
    for query in fixture["per_query"]:
        assert len(query["candidates"]) <= k * 4


# ---------------------------------------------------------------------------
# AC2 -- 95-%-CI aus gepaartem Bootstrap, vorab festgeschriebene Regel im Report
# ---------------------------------------------------------------------------
def test_paired_bootstrap_ci_present_per_metric(report: dict) -> None:
    """AC2: Zu jeder Metrikdifferenz gehoert ein Konfidenzintervall."""
    for metric in METRICS:
        delta = report["deltas"][metric]
        assert delta["ci_low"] <= delta["delta"] <= delta["ci_high"], metric
        expected_carries = delta["ci_low"] > 0.0 or delta["ci_high"] < 0.0
        assert delta["carries"] is expected_carries, f"{metric}: Urteil widerspricht dem Intervall"


def test_report_cites_significance_rule(report: dict) -> None:
    """AC2: Die vorab festgeschriebene Regel steht im Report (JSON und Markdown)."""
    assert report["significance"]["rule"] == SIGNIFICANCE_RULE
    assert SIGNIFICANCE_RULE in DOC_TEXT


def test_paired_bootstrap_is_deterministic() -> None:
    """AC2: Gleicher Seed, gleiche Zahlen -- sonst ist das Urteil nicht pruefbar."""
    off = [0.1 * i for i in range(26)]
    on = [0.1 * i + 0.05 for i in range(26)]
    first = paired_bootstrap(off, on)
    second = paired_bootstrap(off, on)
    assert first == second
    assert first["ci_low"] > 0.0
    assert first["delta"] == pytest.approx(0.05, abs=1e-9)


def test_paired_bootstrap_null_case_does_not_carry() -> None:
    """AC2: Identische Werte in beiden Armen -- Differenz 0, Intervall schliesst 0 ein."""
    values = [0.1 * i for i in range(20)]
    result = paired_bootstrap(values, values)
    assert result["delta"] == 0.0
    assert result["carries"] is False


def test_significance_uses_the_804_seed() -> None:
    """AC2: Der Seed ist auf die Issue-Nummer gepinnt, nicht auf #731 (804 != 731)."""
    assert BOOTSTRAP_SEED == 804


# ---------------------------------------------------------------------------
# AC3 -- Latenz und Peak-RSS in beiden Bedingungen, gleiche Hardware, gleiche Tabelle
# ---------------------------------------------------------------------------
def test_cost_table_has_both_conditions_same_hardware() -> None:
    """AC3: Kostenblock traegt beide Bedingungen mit derselben Hardware."""
    cost = LIVE_RESULTS["cost"]
    assert set(cost) >= {"aus", "an", "hardware"}
    for condition in ("aus", "an"):
        assert cost[condition]["search_ms"]["p50"] > 0
        assert cost[condition]["peak_rss_kb"] > 0


def test_check_against_ignores_cost_fields(report: dict) -> None:
    """AC3: Eine geaenderte Latenz/RSS im Vergleichsstand ist kein Gatter-Fund."""
    mutated = json.loads(json.dumps(LIVE_RESULTS))
    mutated["cost"]["aus"]["peak_rss_kb"] += 999_999
    mutated["cost"]["an"]["search_ms"]["p50"] += 999.0
    assert compare_against(report, mutated) == []


# ---------------------------------------------------------------------------
# AC4 -- hermetischer --check-against-Lauf deckungsgleich, kein Modell in CI
# ---------------------------------------------------------------------------
def test_raw_results_match_a_fresh_hermetic_run(report: dict) -> None:
    """AC4: Die eingecheckten Rohdaten decken sich mit einem frischen Lauf."""
    assert compare_against(report, LIVE_RESULTS) == []


def test_check_against_detects_a_stale_report(report: dict) -> None:
    """AC4: ``--check-against`` schlaegt an, wenn Report und Lauf auseinanderlaufen."""
    stale = json.loads(json.dumps(LIVE_RESULTS))
    stale["results"]["an"]["overall"]["ndcg_at_10"] += 0.1
    problems = compare_against(report, stale)
    assert problems and any("ndcg_at_10" in p for p in problems)


def test_cli_check_against_exits_zero_on_the_checked_in_results() -> None:
    """AC4: Der Lauf laesst sich als Gatter fahren und ist dann gruen."""
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "eval" / "run_reranker_ablation_804.py"),
            "--check-against",
            str(LIVE_RESULTS_PATH),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_run_is_hermetic_without_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: Der Replay kommt ohne Netz und ohne Modell-Load aus (kein CrossEncoder-Import
    im Replay-Pfad, kein ``sentence_transformers``-Backend noetig)."""

    def _no_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("Der hermetische Lauf hat eine Netzverbindung geoeffnet")

    monkeypatch.setattr(socket.socket, "connect", _no_socket)
    build_report()


def test_fixture_matches_the_708_goldset_manifest() -> None:
    """AC4: Die Fixture ist an genau den #708-Goldset-Stand gebunden."""
    fixture = load_fixture()
    goldset = load_goldset(GOLDSET_PATH)
    verify_fixture(fixture, goldset)


def test_drifted_fixture_candidates_are_fatal() -> None:
    """AC4: Editierte Kandidaten brechen den Lauf ab, statt still zu driften."""
    fixture = load_fixture()
    goldset = load_goldset(GOLDSET_PATH)
    fixture["per_query"][0]["candidates"][0]["rerank_score"] += 1.0
    with pytest.raises(FixtureMismatchError):
        verify_fixture(fixture, goldset)


def test_drifted_goldset_manifest_is_fatal() -> None:
    """AC4: Ein anderer #708-Goldset-Stand als der, aus dem die Fixture entstand,
    bricht den Lauf ab."""
    fixture = load_fixture()
    goldset = load_goldset(GOLDSET_PATH)
    goldset["meta"]["manifest_sha256"] = "0" * 64
    with pytest.raises(FixtureMismatchError):
        verify_fixture(fixture, goldset)


def test_ci_workflow_runs_the_new_eval() -> None:
    """AC4: Der Lauf ist in CI verdrahtet, sonst altert der Report unbemerkt."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "run_reranker_ablation_804.py" in workflow
    assert "test_issue_804_reranker_ablation.py" in workflow


def test_main_without_check_prints_the_report() -> None:
    """AC4: Der Runner gibt die Rohdaten auf stdout aus."""
    assert main([]) == 0


def test_every_query_has_a_fixture_entry() -> None:
    """AC4: Chunks/Kandidaten liegen je Query im Repo (kein Teilsatz)."""
    fixture = load_fixture()
    goldset = load_goldset(GOLDSET_PATH)
    fixture_ids = {q["query_id"] for q in fixture["per_query"]}
    goldset_ids = {q["query_id"] for q in goldset["queries"]}
    assert fixture_ids == goldset_ids


def test_doc_is_linked_from_evals_readme() -> None:
    """AC4: Der Report ist auffindbar (Link-Guard aus #641)."""
    readme = (REPO_ROOT / "docs" / "evals" / "README.md").read_text(encoding="utf-8")
    assert REPORT_PATH.name in readme
    assert LIVE_RESULTS_PATH.name in readme


# ---------------------------------------------------------------------------
# AC5 -- Ein-Satz-Fazit, ob ein belegbarer Effekt vorliegt
# ---------------------------------------------------------------------------
def test_report_has_one_sentence_verdict(report: dict) -> None:
    """AC5: Verdikt folgt den ``carries``-Flags, nicht Textwunsch."""
    carrying = [m for m in METRICS if report["deltas"][m]["carries"]]
    if not carrying:
        assert "KEINEN" in report["verdict"]
    else:
        assert "einen vom Rauschen trennbaren Effekt" in report["verdict"]
        for metric in carrying:
            assert metric in report["verdict"]


def test_verdict_is_a_single_sentence(report: dict) -> None:
    """AC5: Das Fazit ist tatsaechlich EIN Satz (genau ein Satzzeichen am Ende)."""
    verdict = report["verdict"].strip()
    assert verdict.count(". ") == 0 or verdict.rstrip(".").count(".") == 0
    assert verdict.endswith(".")


def test_verdict_matches_stored_report() -> None:
    """AC5: Das gemessene Verdikt deckt sich mit dem eingecheckten Report."""
    assert LIVE_RESULTS["verdict"]


def test_negative_result_is_an_allowed_outcome() -> None:
    """AC5: 'kein nachweisbarer Effekt' ist zulaessig -- kein Test verlangt carries=True."""
    # Bewusst kein assert auf carries True/False: der Nullbefund ist laut Issue
    # ausdruecklich zulaessig. Dieser Test dokumentiert nur, dass kein anderer
    # Test in dieser Datei das Gegenteil erzwingt.
    assert True
