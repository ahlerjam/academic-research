"""Tests fuer den Embedding-Kandidaten-Vergleich auf dem Chunk-Goldset (#731).

Jeder Test haengt an genau einem Akzeptanzkriterium des Issues; die Zuordnung
steht im jeweiligen Docstring. Der Lauf ist hermetisch: er laedt kein Modell
und braucht kein Netz — die Vektoren liegen je Kandidat als Fixture im Repo.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from scripts.eval.run_embedding_candidates_731 import (  # noqa: E402
    BASELINE_KEY,
    CANDIDATES,
    FIXTURE_DIR,
    LIVE_RESULTS_PATH,
    METRICS,
    REPORT_PATH,
    ManifestMismatchError,
    build_report,
    compare_against,
    load_candidate_fixture,
    main,
    paired_bootstrap,
    verify_manifest,
)

DOC_TEXT = REPORT_PATH.read_text(encoding="utf-8")
LIVE_RESULTS = json.loads(LIVE_RESULTS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    """Ein frischer hermetischer Lauf ueber alle Kandidaten."""
    return build_report()


# ---------------------------------------------------------------------------
# AC1 — gemessen auf demselben Weg wie im Betrieb
# ---------------------------------------------------------------------------
def test_every_chunk_embedding_text_is_context_sentence_plus_chunk() -> None:
    """AC1: Der Embedding-Input je Chunk erfuellt den Produktionsvertrag."""
    from academic_vault.embeddings import build_contextual_embedding_text

    for key in CANDIDATES:
        goldset, _ = load_candidate_fixture(key)
        assert goldset["chunks"], f"{key}: keine Chunks in der Fixture"
        for chunk in goldset["chunks"]:
            assert chunk["embedding_text"] == build_contextual_embedding_text(
                chunk["context_sentence"], chunk["chunk_text"]
            ), f"{key}/{chunk['chunk_id']}: Embedding-Input weicht vom Produktionsvertrag ab"


def test_fixture_chunks_match_a_fresh_chunk_pages_run() -> None:
    """AC1: Die Chunks entstehen aus ``chunk_pages`` mit den Produktionsdefaults.

    Der je Kandidat eingefrorene Tokenizer wird als ``token_counter`` injiziert
    (Tokenzahl je Chunk-Text liegt in der Fixture), damit der Vergleich ohne
    Modell-Download auskommt.
    """
    from scripts.eval.run_embedding_candidates_731 import rechunk_from_frozen_token_counts

    for key in CANDIDATES:
        goldset, _ = load_candidate_fixture(key)
        rebuilt = rechunk_from_frozen_token_counts(goldset)
        assert [c["chunk_id"] for c in rebuilt] == [c["chunk_id"] for c in goldset["chunks"]], (
            f"{key}: Chunkgrenzen weichen von einem frischen chunk_pages-Lauf ab"
        )
        assert [c["chunk_text"] for c in rebuilt] == [c["chunk_text"] for c in goldset["chunks"]], (
            f"{key}: Chunk-Texte weichen von einem frischen chunk_pages-Lauf ab"
        )


def test_e5_family_uses_query_and_passage_prefix() -> None:
    """AC1: Fuer die e5-Familie bleibt das ``query:``/``passage:``-Schema erhalten."""
    from academic_vault.embedding_model import PASSAGE_PREFIX, QUERY_PREFIX

    for key in ("e5-small", "e5-large"):
        cfg = CANDIDATES[key]
        assert cfg.passage_prefix == PASSAGE_PREFIX
        assert cfg.query_prefix == QUERY_PREFIX


def test_every_candidate_declares_its_prompting_scheme() -> None:
    """AC1: Jeder Kandidat fuehrt sein Prompting mit; Abweichungen sind markiert."""
    for key, cfg in CANDIDATES.items():
        assert cfg.prompting_note, f"{key}: kein Prompting-Vermerk"
        stored = LIVE_RESULTS["candidates"][key]["prompting"]
        assert stored["query_prefix"] == cfg.query_prefix
        assert stored["passage_prefix"] == cfg.passage_prefix
        assert stored["query_prompt_name"] == cfg.query_prompt_name
        assert stored["note"] == cfg.prompting_note
    assert "passage: " not in LIVE_RESULTS["candidates"]["bge-m3"]["prompting"]["passage_prefix"]


def test_report_documents_the_prompting_deviation() -> None:
    """AC1: Die Abweichung vom ``passage:``-Wortlaut steht im Report."""
    assert "Prompting" in DOC_TEXT
    assert "BGE-M3" in DOC_TEXT and "Qwen3" in DOC_TEXT


# ---------------------------------------------------------------------------
# AC2 — nDCG@10, MRR, Recall@10 je Kandidat
# ---------------------------------------------------------------------------
def test_all_three_metrics_present_for_every_candidate(report: dict) -> None:
    """AC2: Alle drei Metriken liegen gesamt und je Teilmenge vor."""
    for key in CANDIDATES:
        entry = report["candidates"][key]
        for metric in METRICS:
            assert metric in entry["overall"], f"{key}: {metric} fehlt"
        assert set(entry["subsets"]) == {"same-language", "language-gap", "cross-language"}
        for case, values in entry["subsets"].items():
            for metric in METRICS:
                assert metric in values, f"{key}/{case}: {metric} fehlt"


def test_raw_results_match_a_fresh_hermetic_run(report: dict) -> None:
    """AC2/AC6: Die eingecheckten Rohdaten decken sich mit einem frischen Lauf."""
    assert compare_against(report, LIVE_RESULTS) == []


def test_baseline_candidate_reproduces_the_708_numbers(report: dict) -> None:
    """AC2: Die Baseline trifft die aus #708 bekannten Werte.

    Weicht sie ab, misst dieser Pfad etwas anderes als das etablierte Goldset —
    dann sind auch alle Kandidatenzahlen wertlos.
    """
    overall = report["candidates"][BASELINE_KEY]["overall"]
    assert overall["recall_at_10"] == pytest.approx(0.8167, abs=5e-4)
    assert overall["ndcg_at_10"] == pytest.approx(0.7097, abs=5e-4)
    assert overall["mrr"] == pytest.approx(0.6764, abs=5e-4)


# ---------------------------------------------------------------------------
# AC3 — CPU-Zeiten und Messhardware
# ---------------------------------------------------------------------------
def test_timing_block_names_hardware_and_cpu_only() -> None:
    """AC3: Die Messhardware ist benannt und der Lauf lief nachweislich auf CPU."""
    hardware = LIVE_RESULTS["hardware"]
    for field in ("cpu", "cpu_cores", "ram_gb", "python", "torch", "platform"):
        assert hardware.get(field), f"Hardware-Block: {field} fehlt"
    assert hardware["device"] == "cpu"
    assert hardware["cuda_available"] is False
    assert hardware["mps_used"] is False


def test_index_ms_per_chunk_and_search_latency_present_per_candidate() -> None:
    """AC3: Indexierungszeit je Chunk und Suchlatenz liegen je Kandidat vor."""
    for key in CANDIDATES:
        entry = LIVE_RESULTS["candidates"][key]
        for block in ("index_ms_per_chunk", "search_ms_per_query"):
            values = entry[block]
            assert values["p50"] > 0, f"{key}.{block}.p50 ist nicht gemessen"
            assert values["p95"] >= values["p50"], f"{key}.{block}: p95 < p50"


def test_download_size_matches_the_730_order_of_magnitude() -> None:
    """AC3: Die Download-Groesse je Kandidat passt zur Erhebung aus #730."""
    expected_gb = {
        "e5-small": 0.5,
        "qwen3-384": 1.3,
        "qwen3-1024": 1.3,
        "bge-m3": 2.4,
        "e5-large": 2.3,
    }
    for key, upper in expected_gb.items():
        gb = LIVE_RESULTS["candidates"][key]["download_bytes"] / 1e9
        assert 0.0 < gb <= upper, f"{key}: Download-Groesse {gb:.2f} GB passt nicht zu #730"


def test_report_table_matches_raw_timings() -> None:
    """AC3: Die Zeiten im Markdown stammen aus den Rohdaten."""
    for key in CANDIDATES:
        entry = LIVE_RESULTS["candidates"][key]
        index_p50 = f"{entry['index_ms_per_chunk']['p50']:.1f}".replace(".", ",")
        assert index_p50 in DOC_TEXT, f"{key}: Indexierungszeit {index_p50} ms fehlt im Report"
        search_p50 = f"{entry['search_ms_per_query']['p50']:.3f}".replace(".", ",")
        assert search_p50 in DOC_TEXT, f"{key}: Suchlatenz {search_p50} ms fehlt im Report"
        gigabytes = f"{entry['download_bytes'] / 1e9:.2f}".replace(".", ",")
        assert gigabytes in DOC_TEXT, f"{key}: Download-Groesse {gigabytes} GB fehlt im Report"


# ---------------------------------------------------------------------------
# AC4 — Schema-Migration je Kandidat
# ---------------------------------------------------------------------------
def test_migration_flag_matches_dimension_for_every_candidate(report: dict) -> None:
    """AC4: 384d heisst keine Migration, alles andere Migration + Neuindizierung."""
    for key in CANDIDATES:
        entry = report["candidates"][key]
        migration = entry["schema_migration"]
        assert migration["required"] is (entry["dim"] != 384), (
            f"{key}: Flag passt nicht zur Dimension"
        )
        if migration["required"]:
            assert "Neuindizierung" in migration["price"]
            assert f"FLOAT[{entry['dim']}]" in migration["price"]


def test_migration_claim_cites_the_truncatability_report() -> None:
    """AC4: Jede Migrationsaussage verweist auf die Vorarbeit aus #730."""
    for key in CANDIDATES:
        evidence = LIVE_RESULTS["candidates"][key]["schema_migration"]["evidence"]
        assert "730" in evidence, f"{key}: Migrationsaussage ohne Beleg aus #730"
    assert "embedding-truncatability-730.md" in DOC_TEXT


def test_report_names_the_migration_price_for_every_candidate() -> None:
    """AC4: Der Report benennt den Preis je Kandidat, in beide Richtungen."""
    migration_rows = [
        line
        for line in DOC_TEXT.splitlines()
        if line.startswith("| `") and ("Migration" in line or "migration" in line)
    ]
    for key in CANDIDATES:
        required = LIVE_RESULTS["candidates"][key]["schema_migration"]["required"]
        row = next((line for line in migration_rows if f"`{key}`" in line), None)
        assert row is not None, f"{key}: keine Zeile in der Migrationstabelle"
        if required:
            assert "FLOAT[384] → FLOAT[1024]" in row, f"{key}: DDL-Aenderung nicht benannt"
            assert "Neuindizierung" in row, f"{key}: Neuindizierung nicht benannt"
        else:
            assert "keine Migration" in row, f"{key}: als migrationsfrei nicht ausgewiesen"


# ---------------------------------------------------------------------------
# AC5 — Abstand und Tragfaehigkeit
# ---------------------------------------------------------------------------
def test_paired_bootstrap_interval_present_for_every_delta(report: dict) -> None:
    """AC5: Zu jedem Abstand gegen die Baseline gehoert ein Konfidenzintervall."""
    for key in CANDIDATES:
        if key == BASELINE_KEY:
            continue
        for metric in METRICS:
            delta = report["deltas"][key][metric]
            assert delta["ci_low"] <= delta["delta"] <= delta["ci_high"], f"{key}/{metric}"


def test_significance_verdict_matches_the_declared_rule(report: dict) -> None:
    """AC5: Das Urteil folgt der vorab festgeschriebenen Regel, nicht dem Wunsch."""
    for key in CANDIDATES:
        if key == BASELINE_KEY:
            continue
        for metric in METRICS:
            delta = report["deltas"][key][metric]
            expected = delta["ci_low"] > 0.0 or delta["ci_high"] < 0.0
            assert delta["carries"] is expected, (
                f"{key}/{metric}: Urteil widerspricht dem Intervall"
            )


def test_paired_bootstrap_is_deterministic() -> None:
    """AC5: Gleicher Seed, gleiche Zahlen — sonst ist das Urteil nicht pruefbar."""
    baseline = [0.1 * i for i in range(26)]
    other = [0.1 * i + 0.05 for i in range(26)]
    first = paired_bootstrap(baseline, other)
    second = paired_bootstrap(baseline, other)
    assert first == second
    assert first["ci_low"] > 0.0


def test_report_states_the_resolution_limit_of_the_goldset(report: dict) -> None:
    """AC5: Der Report benennt, was die Queries ueberhaupt aufloesen koennen."""
    assert report["significance"]["query_count"] == 60
    assert "Auflösungsgrenze" in DOC_TEXT
    assert re.search(r"0,016[0-9]", DOC_TEXT), "Auflösungsgrenze je Query fehlt im Report"


def test_chunk_count_per_candidate_is_reported(report: dict) -> None:
    """AC5: Unterschiedliche Chunkzahlen sind ausgewiesen, nicht verschwiegen."""
    for key in CANDIDATES:
        assert report["candidates"][key]["chunk_count"] > 0
        assert str(report["candidates"][key]["chunk_count"]) in DOC_TEXT


# ---------------------------------------------------------------------------
# AC6 — Rohdaten im Repo, Lauf wiederholbar
# ---------------------------------------------------------------------------
def test_manifest_hash_binds_texts_model_and_dim() -> None:
    """AC6: Der Fingerabdruck deckt Texte, Modell-ID und Dimension ab."""
    for key in CANDIDATES:
        goldset, _ = load_candidate_fixture(key)
        verify_manifest(goldset)


def test_drifted_chunk_text_is_fatal() -> None:
    """AC6: Ein editierter Chunk-Text bricht den Lauf ab, statt still zu driften."""
    goldset, _ = load_candidate_fixture(BASELINE_KEY)
    goldset["chunks"][0]["embedding_text"] += " drift"
    with pytest.raises(ManifestMismatchError):
        verify_manifest(goldset)


def test_run_is_hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6: Der Lauf kommt ohne Netz und ohne Modell-Load aus."""

    def _no_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("Der hermetische Lauf hat eine Netzverbindung geoeffnet")

    monkeypatch.setattr(socket.socket, "connect", _no_socket)
    monkeypatch.setattr(
        "academic_vault.embedding_model._load_backend_model",
        lambda *a, **k: pytest.fail("Der hermetische Lauf hat ein Embedding-Modell geladen"),
    )
    build_report()


def test_hermetic_guard_would_catch_a_model_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6: Gegenprobe — die Sperre aus dem Hermetik-Test beisst tatsaechlich."""
    monkeypatch.setattr(
        "academic_vault.embedding_model._load_backend_model",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Modell geladen")),
    )
    from academic_vault.embedding_model import E5SmallEmbedder

    with pytest.raises(AssertionError):
        E5SmallEmbedder().load()


def test_check_against_detects_a_stale_report(report: dict) -> None:
    """AC6: ``--check-against`` schlaegt an, wenn Report und Lauf auseinanderlaufen."""
    stale = json.loads(json.dumps(LIVE_RESULTS))
    stale["candidates"][BASELINE_KEY]["overall"]["ndcg_at_10"] += 0.1
    problems = compare_against(report, stale)
    assert problems and any("ndcg_at_10" in p for p in problems)


def test_cli_check_against_exits_zero_on_the_checked_in_results() -> None:
    """AC6: Der Lauf laesst sich als Gatter fahren und ist dann gruen."""
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "eval" / "run_embedding_candidates_731.py"),
            "--check-against",
            str(LIVE_RESULTS_PATH),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_every_candidate_has_a_fixture_in_the_repo() -> None:
    """AC6: Chunks, Queries und Vektoren liegen je Kandidat im Repo."""
    for key in CANDIDATES:
        for name in ("goldset.json", "vectors.json"):
            assert (FIXTURE_DIR / key / name).is_file(), f"{key}/{name} fehlt"


def test_doc_is_linked_from_evals_readme() -> None:
    """AC6: Der Report ist auffindbar (Link-Guard aus #641)."""
    readme = (REPO_ROOT / "docs" / "evals" / "README.md").read_text(encoding="utf-8")
    assert REPORT_PATH.name in readme


def test_ci_workflow_runs_the_new_eval() -> None:
    """AC6: Der Lauf ist in CI verdrahtet, sonst altert der Report unbemerkt."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "run_embedding_candidates_731.py" in workflow
    assert "tests/test_issue_731_embedding_candidates.py" in workflow


def test_main_without_check_prints_the_report() -> None:
    """AC6: Der Runner gibt die Rohdaten auf stdout aus."""
    assert main([]) == 0
