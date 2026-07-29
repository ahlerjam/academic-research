"""Regression tests for issue #465.

`run_search()` blockiert bisher unbegrenzt ueber `as_completed()`, bis alle
Modul-Futures fertig sind -- eine einzelne langsame Quelle (insbesondere der
EconStor-OAI-PMH-Fallback aus #236) kann den gesamten Lauf um Minuten
verzoegern. `run_search()` bekommt dafuer einen optionalen `time_budget`-
Parameter, `search_econstor()` zusaetzlich ein engeres, eigenes
`fallback_time_budget` fuer seine resumptionToken-Schleife.

Akzeptanzkriterien (#465):
- AC1: Gesamtlauf ist ueber einen konfigurierbaren Wert begrenzt und haelt
  ihn ein.
- AC2: Eine Quelle, die das Budget ueberschreitet, wird uebersprungen und im
  Ergebnis als uebersprungen ausgewiesen (getrennt von echten Fehlern).
- AC3: Die Treffer der uebrigen Quellen bleiben vollstaendig erhalten.
- AC4: Ein Test mit einer kuenstlich verzoegerten Quelle belegt das
  Verhalten (hier + der enge EconStor-Fallback-Test).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

import search

FIXTURES = Path(__file__).parent / "fixtures" / "search"


def _patch_client(monkeypatch, handler, real_sleep: bool = False) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def patched_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(search.httpx, "Client", patched_client)
    if not real_sleep:
        monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)


def _fixture_response(name: str, content_type: str = "application/json") -> httpx.Response:
    body = (FIXTURES / name).read_bytes()
    return httpx.Response(200, content=body, headers={"content-type": content_type})


def _slow_module_handler(slow_delay: float):
    """MockTransport-Handler: `crossref` ist kuenstlich verzoegert, `openalex`
    und `arxiv` antworten sofort mit echten, eingefrorenen Fixtures."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.crossref.org" in url:
            time.sleep(slow_delay)
            return _fixture_response("crossref_response.json")
        if "api.openalex.org" in url:
            return _fixture_response("openalex_response.json")
        if "export.arxiv.org" in url:
            return _fixture_response("arxiv_response.xml", "text/xml")
        return httpx.Response(404, text="unknown host in test handler")

    return handler


# ---------------------------------------------------------------------------
# Modul-Konstanten
# ---------------------------------------------------------------------------


def test_time_budget_constants_exist():
    assert hasattr(search, "DEFAULT_TIME_BUDGET_S")
    assert hasattr(search, "ECONSTOR_FALLBACK_TIME_BUDGET_S")
    assert isinstance(search.DEFAULT_TIME_BUDGET_S, float) and search.DEFAULT_TIME_BUDGET_S > 0
    assert (
        isinstance(search.ECONSTOR_FALLBACK_TIME_BUDGET_S, float)
        and search.ECONSTOR_FALLBACK_TIME_BUDGET_S > 0
    )
    # Rueckfallpfad-Budget ist per Definition enger als das Gesamtbudget.
    assert search.ECONSTOR_FALLBACK_TIME_BUDGET_S < search.DEFAULT_TIME_BUDGET_S


# ---------------------------------------------------------------------------
# AC1 + AC4: Gesamtlauf haelt das Budget ein, trotz kuenstlich verzoegerter Quelle
# ---------------------------------------------------------------------------


def test_run_search_returns_within_time_budget(monkeypatch):
    """crossref haengt 2s real (Handler) + 0.5s internes time.sleep() = 2.5s.
    openalex/arxiv sind real, aber schnell (nur ihr eigenes internes
    time.sleep(0.5), kein Handler-Delay) und bleiben unter dem Budget.
    time_budget=1.0 liegt klar zwischen beiden Werten -- run_search() muss
    deutlich unter den 2.5s des langsamen Moduls zurueckkehren."""
    _patch_client(monkeypatch, _slow_module_handler(2.0), real_sleep=True)
    # search.time.sleep bewusst NICHT mocken (real_sleep=True): sowohl der
    # kuenstliche Handler-Delay als auch das interne time.sleep(0.5) jeder
    # search_*-Funktion nutzen dasselbe globale time-Modul wie search.py.

    start = time.monotonic()
    papers, failed = search.run_search(
        "climate change",
        ["crossref", "openalex", "arxiv"],
        limit=3,
        time_budget=1.0,
    )
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"run_search() dauerte {elapsed:.2f}s, Budget war 1.0s"
    assert failed == []  # crossref ist "skipped", nicht "failed"
    assert {p["source_module"] for p in papers} == {"openalex", "arxiv"}


# ---------------------------------------------------------------------------
# AC2: Skip ist getrennt von Fail ausgewiesen
# ---------------------------------------------------------------------------


def test_slow_module_marked_skipped_not_generic_failure(monkeypatch):
    """Das langsame Modul landet in skipped_out, NICHT in failed."""
    _patch_client(monkeypatch, _slow_module_handler(2.0), real_sleep=True)

    skipped: list[str] = []
    _, failed = search.run_search(
        "climate change",
        ["crossref", "openalex", "arxiv"],
        limit=3,
        time_budget=1.0,
        skipped_out=skipped,
    )

    assert skipped == ["crossref"]
    assert "crossref" not in failed


# ---------------------------------------------------------------------------
# AC3: Treffer der uebrigen (schnellen) Module bleiben vollstaendig erhalten
# ---------------------------------------------------------------------------


def test_other_modules_results_unaffected_by_skip(monkeypatch):
    """Trefferzahl/-inhalt der schnellen Module ist identisch zu einem Lauf
    ohne Budget und ohne das langsame Modul."""
    skipped: list[str] = []
    _patch_client(monkeypatch, _slow_module_handler(2.0), real_sleep=True)
    with_budget_papers, _ = search.run_search(
        "climate change",
        ["crossref", "openalex", "arxiv"],
        limit=3,
        time_budget=1.0,
        skipped_out=skipped,
    )

    def fast_only_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.openalex.org" in url:
            return _fixture_response("openalex_response.json")
        if "export.arxiv.org" in url:
            return _fixture_response("arxiv_response.xml", "text/xml")
        return httpx.Response(404, text="unknown host in test handler")

    _patch_client(monkeypatch, fast_only_handler)
    baseline_papers, baseline_failed = search.run_search(
        "climate change", ["openalex", "arxiv"], limit=3
    )

    assert skipped == ["crossref"]
    assert baseline_failed == []
    with_budget_sources = sorted(p["source_module"] for p in with_budget_papers)
    baseline_sources = sorted(p["source_module"] for p in baseline_papers)
    assert with_budget_sources == baseline_sources
    assert len(with_budget_papers) == len(baseline_papers) > 0


# ---------------------------------------------------------------------------
# AC4: EconStor-OAI-PMH-Fallback respektiert sein eigenes, engeres Budget
# ---------------------------------------------------------------------------


def _oai_record_xml(idx: int) -> str:
    ns_dc = "http://purl.org/dc/elements/1.1/"
    return (
        "<record><metadata>"
        f'<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:dc="{ns_dc}">'
        f"<dc:title>budgettest paper {idx}</dc:title>"
        f"<dc:description>budgettest abstract {idx}</dc:description>"
        f"<dc:creator>Author {idx}</dc:creator>"
        "<dc:date>2020-01-01</dc:date>"
        "</oai_dc:dc>"
        "</metadata></record>"
    )


def _oai_list_records_response() -> str:
    ns = "http://www.openarchives.org/OAI/2.0/"
    record = _oai_record_xml(0)
    token = "<resumptionToken>tok-next</resumptionToken>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<OAI-PMH xmlns="{ns}">'
        f"<ListRecords>{record}{token}</ListRecords>"
        "</OAI-PMH>"
    )


def test_econstor_fallback_respects_narrower_budget(monkeypatch):
    """REST liefert 503 (erzwingt OAI-Fallback); jede OAI-Seite ist real um
    0.3s verzoegert und liefert IMMER ein resumptionToken (ohne Budget also
    OAI_MAX_PAGES=5 Runden = >=1.5s). Mit fallback_time_budget=0.2 muss die
    Schleife deutlich frueher abbrechen und die bis dahin gesammelten Treffer
    zurueckgeben."""
    request_count = {"oai": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "find-by-metadata-field" in url:
            return httpx.Response(503, text="upstream down")
        if "oai/request" in url:
            request_count["oai"] += 1
            time.sleep(0.3)
            return httpx.Response(200, text=_oai_list_records_response())
        return httpx.Response(404, text="")

    _patch_client(monkeypatch, handler, real_sleep=True)

    start = time.monotonic()
    results = search.search_econstor("budgettest", limit=100, fallback_time_budget=0.2)
    elapsed = time.monotonic() - start

    assert elapsed < 1.2, f"search_econstor() dauerte {elapsed:.2f}s trotz 0.2s Fallback-Budget"
    assert request_count["oai"] < search.OAI_MAX_PAGES, (
        "Budget haette die Schleife vor Erreichen von OAI_MAX_PAGES abbrechen muessen"
    )
    assert isinstance(results, list)
    assert len(results) >= 1  # mind. die eine bereits geparste Seite bleibt erhalten


# ---------------------------------------------------------------------------
# AC1 + AC2 auf CLI-Ebene: Sidecar-Statusdatei weist Skip sichtbar aus
# ---------------------------------------------------------------------------


def test_cli_status_json_reports_skipped_module(monkeypatch, tmp_path, caplog):
    output_path = tmp_path / "results.json"
    _patch_client(monkeypatch, _slow_module_handler(2.0), real_sleep=True)
    monkeypatch.setattr(
        "sys.argv",
        [
            "search.py",
            "--query",
            "climate change",
            "--modules",
            "crossref,openalex,arxiv",
            "--limit",
            "3",
            "--time-budget",
            "1.0",
            "--output",
            str(output_path),
        ],
    )

    with caplog.at_level(logging.WARNING):
        exit_code = search.main()

    assert exit_code == 0  # openalex/arxiv erfolgreich -> kein Totalausfall

    status_path = tmp_path / "results_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["skipped_modules"] == ["crossref"]
    assert status["failed_modules"] == []
    assert status["papers_per_module"]["openalex"] > 0
    assert status["papers_per_module"]["arxiv"] > 0

    warning_messages = " ".join(
        rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING
    )
    assert "crossref" in warning_messages
    assert "skip" in warning_messages.lower()


def test_cli_time_budget_flags_have_defaults(monkeypatch):
    """Smoke-Test: --time-budget/--fallback-time-budget sind optional und
    greifen mit den Default-Konstanten, wenn nicht angegeben."""
    monkeypatch.setattr(
        "sys.argv",
        ["search.py", "--query", "x", "--modules", "crossref"],
    )
    args = search.parse_args()
    assert args.time_budget == search.DEFAULT_TIME_BUDGET_S
    assert args.fallback_time_budget == search.ECONSTOR_FALLBACK_TIME_BUDGET_S


@pytest.mark.parametrize("module_name", sorted(search.MODULES.keys()))
def test_run_search_without_time_budget_is_unchanged(monkeypatch, module_name):
    """Regressionsschutz: time_budget=None (impliziter Default) reproduziert
    exakt das alte, unbegrenzte Blockierverhalten -- Aufrufer wie
    anchor_paper.py, die run_search() ohne time_budget aufrufen, sind
    unveraendert."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    _patch_client(monkeypatch, handler)

    papers, failed = search.run_search("x", [module_name], limit=3)

    assert papers == []
    assert failed == [module_name]
