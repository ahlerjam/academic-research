"""Fehlerfall-Tests fuer die Suchmodule (Issue #456).

- Rate-Limit (429) und Serverausfall (5xx) auf `_run_module`-Ebene,
  parametrisiert ueber alle 7 Module.
- AC2: Ausfall einer Quelle ist im Ergebnis sichtbar (Sidecar-Statusdatei
  `<output-stem>_status.json` + WARNING-Log-Zeile mit explizitem Modulnamen),
  statt als leeres Resultat unterzugehen.
- AC4: Fallen alle Quellen aus, ist das am Exitcode (1) erkennbar; faellt
  mindestens ein Modul nicht aus, bleibt der Exitcode 0.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

import search

FIXTURES = Path(__file__).parent / "fixtures" / "search"
ALL_MODULES = sorted(search.MODULES.keys())


def _patch_client(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def patched_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(search.httpx, "Client", patched_client)
    monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Rate-Limit / Serverausfall auf _run_module-Ebene, alle 7 Module
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_run_module_rate_limited_reports_failure(monkeypatch, module_name):
    """Dauerhaftes 429 fuehrt zu (name, [], True) -- keine Exception nach aussen."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    _patch_client(monkeypatch, handler)

    name, papers, failed = search._run_module(module_name, "climate change", 3)

    assert name == module_name
    assert papers == []
    assert failed is True


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_run_module_server_error_reports_failure(monkeypatch, module_name):
    """Dauerhaftes HTTP 500 fuehrt zu (name, [], True) -- keine Exception nach aussen."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    _patch_client(monkeypatch, handler)

    name, papers, failed = search._run_module(module_name, "climate change", 3)

    assert name == module_name
    assert papers == []
    assert failed is True


# ---------------------------------------------------------------------------
# main()/CLI-Ebene: Sichtbarkeit (AC2) + Exitcode (AC4)
# ---------------------------------------------------------------------------


def _fixture_response(name: str, content_type: str = "application/json") -> httpx.Response:
    body = (FIXTURES / name).read_bytes()
    return httpx.Response(200, content=body, headers={"content-type": content_type})


def _make_main_handler(failing_modules: set[str]):
    """MockTransport-Handler: `failing_modules` liefern durchgaengig HTTP 500,
    alle anderen Module echte, eingefrorene 200-Antworten (siehe fixtures)."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.crossref.org" in url:
            if "crossref" in failing_modules:
                return httpx.Response(500, text="down")
            return _fixture_response("crossref_response.json")
        if "api.openalex.org" in url:
            if "openalex" in failing_modules:
                return httpx.Response(500, text="down")
            return _fixture_response("openalex_response.json")
        if "api.semanticscholar.org" in url:
            if "semantic_scholar" in failing_modules:
                return httpx.Response(500, text="down")
            return _fixture_response("semantic_scholar_response.json")
        if "api.base-search.net" in url:
            if "base" in failing_modules:
                return httpx.Response(500, text="down")
            return _fixture_response("base_response.json")
        if "api.econbiz.de" in url:
            if "econbiz" in failing_modules:
                return httpx.Response(500, text="down")
            return _fixture_response("econbiz_response.json")
        if "find-by-metadata-field" in url:
            if "econstor" in failing_modules:
                return httpx.Response(500, text="down")
            return httpx.Response(503, text="upstream down")  # -> OAI-Fallback
        if "oai/request" in url:
            if "econstor" in failing_modules:
                return httpx.Response(500, text="down")
            return _fixture_response("econstor_oai_response.xml", "text/xml")
        if "export.arxiv.org" in url:
            if "arxiv" in failing_modules:
                return httpx.Response(500, text="down")
            return _fixture_response("arxiv_response.xml", "text/xml")
        return httpx.Response(404, text="unknown host in test handler")

    return handler


def test_one_module_fails_visible_and_exit_code_zero(monkeypatch, tmp_path, caplog):
    """AC2 + AC4-Gegenprobe: ein Modul faellt aus, bleibt aber sichtbar; da
    andere Module erfolgreich sind, ist der Exitcode weiterhin 0."""
    output_path = tmp_path / "results.json"
    _patch_client(monkeypatch, _make_main_handler({"crossref"}))
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
            "--output",
            str(output_path),
        ],
    )

    with caplog.at_level(logging.WARNING):
        exit_code = search.main()

    assert exit_code == 0

    status_path = tmp_path / "results_status.json"
    assert status_path.exists(), "Sidecar-Statusdatei fehlt"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["failed_modules"] == ["crossref"]
    assert set(status["requested_modules"]) == {"crossref", "openalex", "arxiv"}
    assert "openalex" in status["papers_per_module"]
    assert status["papers_per_module"]["openalex"] > 0

    warning_messages = " ".join(
        rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING
    )
    assert "crossref" in warning_messages


def test_all_modules_fail_exit_code_one(monkeypatch, tmp_path):
    """AC4: fallen alle angefragten Quellen aus, ist Exitcode 1."""
    output_path = tmp_path / "results.json"
    modules = "crossref,openalex,arxiv"
    _patch_client(monkeypatch, _make_main_handler({"crossref", "openalex", "arxiv"}))
    monkeypatch.setattr(
        "sys.argv",
        [
            "search.py",
            "--query",
            "climate change",
            "--modules",
            modules,
            "--limit",
            "3",
            "--output",
            str(output_path),
        ],
    )

    exit_code = search.main()

    assert exit_code == 1
    status = json.loads((tmp_path / "results_status.json").read_text(encoding="utf-8"))
    assert set(status["failed_modules"]) == {"crossref", "openalex", "arxiv"}


def test_at_least_one_success_exit_code_zero(monkeypatch, tmp_path):
    """Gegenprobe zu AC4: mindestens ein erfolgreiches Modul -> Exitcode 0."""
    output_path = tmp_path / "results.json"
    _patch_client(monkeypatch, _make_main_handler({"crossref", "openalex"}))
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
            "--output",
            str(output_path),
        ],
    )

    exit_code = search.main()

    assert exit_code == 0
