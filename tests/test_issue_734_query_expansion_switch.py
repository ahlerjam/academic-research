"""Tests fuer die produktive Anbindung der Query-Umformung (Issue #734).

AC -> Testfall (siehe Issue #734 / Plan-Kommentar):
  AC1 (aktiv + abschaltbar ueber dokumentierten Schalter) ->
      :func:`test_query_expansion_switch_precedence_argument_wins`,
      :func:`test_query_expansion_switch_precedence_env_wins_over_config`,
      :func:`test_query_expansion_switch_precedence_config_wins_over_default`,
      :func:`test_query_expansion_switch_default_is_off`,
      :func:`test_search_papers_calls_vec0_search_four_times_when_enabled`
  AC2 (aus = bytegleich wie vorher) ->
      :func:`test_query_expansion_disabled_matches_baseline`
  AC3 (tatsaechliche Query sichtbar) ->
      :func:`test_search_result_reports_queries_used_when_enabled`,
      :func:`test_search_result_reports_queries_used_when_disabled`
  AC4 (Fehlerpfad bricht nicht ab, wird einmal gemeldet) ->
      :func:`test_expand_query_failure_falls_back_to_raw_query`,
      :func:`test_expand_query_cli_not_found_returns_error`,
      :func:`test_expand_query_timeout_returns_error`
  AC6 (gleicher Vorrang wie #719) -> alle Praezedenz-Tests nutzen denselben
      ``resolve_bool_switch`` wie in ``test_issue_719_config_switches.py``.

Rot->Gruen-Beweis: Diese Datei importiert ``academic_vault.query_expansion``,
das vor #734 nicht existiert -- der Import schlaegt mit
``ModuleNotFoundError`` fehl; auf diesem Branch gruen.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

from academic_vault.query_expansion import (
    CONFIG_KEY,
    ENV_QUERY_EXPANSION_ENABLED,
    expand_query,
    resolve_query_expansion_enabled,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_db(tmp_path: Path) -> str:
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    return db_path


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str) -> None:
    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


# ---------------------------------------------------------------------------
# AC1/AC6 -- Vorrang Argument > Env > Config > Default (#719-Muster)
# ---------------------------------------------------------------------------


def test_query_expansion_switch_precedence_argument_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_QUERY_EXPANSION_ENABLED, "0")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({CONFIG_KEY: False}), encoding="utf-8")
    assert resolve_query_expansion_enabled(True, config) is True


def test_query_expansion_switch_precedence_env_wins_over_config(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_QUERY_EXPANSION_ENABLED, "1")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({CONFIG_KEY: False}), encoding="utf-8")
    assert resolve_query_expansion_enabled(None, config) is True


def test_query_expansion_switch_precedence_config_wins_over_default(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_QUERY_EXPANSION_ENABLED, raising=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({CONFIG_KEY: True}), encoding="utf-8")
    assert resolve_query_expansion_enabled(None, config) is True


def test_query_expansion_switch_default_is_off(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_QUERY_EXPANSION_ENABLED, raising=False)
    missing_config = tmp_path / "does-not-exist.json"
    assert resolve_query_expansion_enabled(None, missing_config) is False


def test_query_expansion_default_config_file_is_off():
    """Der ausgelieferte config/parallel_agents.json-Wert ist konsistent aus (Risiko im Plan)."""
    assert resolve_query_expansion_enabled() is False


# ---------------------------------------------------------------------------
# AC4 -- expand_query(): Fehlerpfad statt Exception
# ---------------------------------------------------------------------------


def test_expand_query_cli_not_found_returns_error():
    with patch("academic_vault.query_expansion.subprocess.run", side_effect=FileNotFoundError):
        variants, error = expand_query("wie misst man DevOps-Erfolg")
    assert variants == []
    assert error is not None
    assert "PATH" in error or "nicht gefunden" in error


def test_expand_query_timeout_returns_error():
    with patch(
        "academic_vault.query_expansion.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=240),
    ):
        variants, error = expand_query("wie misst man DevOps-Erfolg")
    assert variants == []
    assert error is not None
    assert "Timeout" in error


def test_expand_query_nonzero_exit_returns_error():
    fake_proc = type("P", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
    with patch("academic_vault.query_expansion.subprocess.run", return_value=fake_proc):
        variants, error = expand_query("wie misst man DevOps-Erfolg")
    assert variants == []
    assert error is not None
    assert "1" in error


def test_expand_query_empty_response_returns_error():
    fake_proc = type("P", (), {"returncode": 0, "stdout": "   \n  ", "stderr": ""})()
    with patch("academic_vault.query_expansion.subprocess.run", return_value=fake_proc):
        variants, error = expand_query("wie misst man DevOps-Erfolg")
    assert variants == []
    assert error is not None


def test_expand_query_success_returns_variants():
    fake_proc = type(
        "P",
        (),
        {
            "returncode": 0,
            "stdout": "one\ntwo\nthree\n",
            "stderr": "",
        },
    )()
    with patch("academic_vault.query_expansion.subprocess.run", return_value=fake_proc):
        variants, error = expand_query("wie misst man DevOps-Erfolg")
    assert error is None
    assert variants == ["one", "two", "three"]


# ---------------------------------------------------------------------------
# AC2/AC3/AC4 -- Integration ueber server.search_papers()
# ---------------------------------------------------------------------------


def test_query_expansion_disabled_matches_baseline(tmp_path, monkeypatch):
    """AC2: bei abgeschaltetem Schalter genau EIN _vec0_search-Aufruf."""
    from academic_vault import server

    monkeypatch.delenv(ENV_QUERY_EXPANSION_ENABLED, raising=False)
    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p001", "Hybrid Retrieval BM25 Dense", "Combining sparse and dense.")

    with patch("academic_vault.server._vec0_search", wraps=server._vec0_search) as spy_vec0:
        results = server.search_papers(db_path, "hybrid retrieval", k=5, rerank=True)

    assert spy_vec0.call_count == 1
    assert results
    assert all(r["queries_used"] == ["hybrid retrieval"] for r in results)


def test_search_papers_calls_vec0_search_four_times_when_enabled(tmp_path, monkeypatch):
    """AC1: bei aktivem Schalter ein _vec0_search-Aufruf je Query-Variante (4 gesamt)."""
    from academic_vault import server

    monkeypatch.setenv(ENV_QUERY_EXPANSION_ENABLED, "1")
    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p001", "Hybrid Retrieval BM25 Dense", "Combining sparse and dense.")

    # expand_query wird innerhalb von search_papers lazy importiert
    # (`from .query_expansion import expand_query, ...`); gepatcht wird daher
    # die Quelle selbst, damit der lazy Import den Mock zieht.
    with (
        patch(
            "academic_vault.query_expansion.expand_query",
            return_value=(["variant one", "variant two", "variant three"], None),
        ),
        patch("academic_vault.server._vec0_search", wraps=server._vec0_search) as spy_vec0,
    ):
        results = server.search_papers(db_path, "hybrid retrieval", k=5, rerank=True)

    assert spy_vec0.call_count == 4
    called_queries = [call.args[1] for call in spy_vec0.call_args_list]
    assert called_queries == [
        "hybrid retrieval",
        "variant one",
        "variant two",
        "variant three",
    ]
    assert results
    for r in results:
        assert r["queries_used"] == [
            "hybrid retrieval",
            "variant one",
            "variant two",
            "variant three",
        ]


def test_search_result_reports_queries_used_when_enabled(tmp_path, monkeypatch):
    from academic_vault import server

    monkeypatch.setenv(ENV_QUERY_EXPANSION_ENABLED, "1")
    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p001", "Hybrid Retrieval BM25 Dense", "Combining sparse and dense.")

    with patch(
        "academic_vault.query_expansion.expand_query",
        return_value=(["v1", "v2", "v3"], None),
    ):
        results = server.search_papers(db_path, "hybrid retrieval", k=5, rerank=True)

    assert results
    for r in results:
        assert r["queries_used"] == ["hybrid retrieval", "v1", "v2", "v3"]


def test_search_result_reports_queries_used_when_disabled(tmp_path, monkeypatch):
    from academic_vault import server

    monkeypatch.delenv(ENV_QUERY_EXPANSION_ENABLED, raising=False)
    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p001", "Hybrid Retrieval BM25 Dense", "Combining sparse and dense.")

    results = server.search_papers(db_path, "hybrid retrieval", k=5, rerank=True)

    assert results
    for r in results:
        assert r["queries_used"] == ["hybrid retrieval"]


def test_expand_query_failure_falls_back_to_raw_query(tmp_path, monkeypatch, caplog):
    """AC4: Umformung schlaegt fehl -> Suche liefert dennoch Ergebnis, eine Warnung."""
    from academic_vault import server

    monkeypatch.setenv(ENV_QUERY_EXPANSION_ENABLED, "1")
    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p001", "Hybrid Retrieval BM25 Dense", "Combining sparse and dense.")

    with (
        patch(
            "academic_vault.query_expansion.expand_query",
            return_value=([], "claude-CLI nicht gefunden (nicht im PATH)"),
        ),
        patch("academic_vault.server._vec0_search", wraps=server._vec0_search) as spy_vec0,
        caplog.at_level(logging.WARNING, logger="academic_vault.server"),
    ):
        results = server.search_papers(db_path, "hybrid retrieval", k=5, rerank=True)

    assert results, "Suche darf trotz fehlgeschlagener Umformung nicht leer/abgebrochen sein"
    assert all(r["queries_used"] == ["hybrid retrieval"] for r in results)
    assert spy_vec0.call_count == 1

    warnings = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING and rec.name == "academic_vault.server"
    ]
    assert len(warnings) == 1
    assert "fehlgeschlagen" in warnings[0].getMessage()
