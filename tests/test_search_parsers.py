"""Parser-Tests fuer die 7 Suchmodule (Issue #456).

AC3: je Suchmodul ein Test gegen eine eingefrorene echte Antwort
     (tests/fixtures/search/, siehe create_fixtures.py fuer Herkunft).
AC1: ein fehlerhafter Einzeldatensatz wird uebersprungen, die uebrigen
     Treffer eines Moduls bleiben erhalten -- keine Exception propagiert.

Jeder Negativ-Test mutiert eine In-Memory-Kopie der echten Fixture (ein
Item wird kaputt gemacht) statt eine eigene kaputte Fixture-Datei
anzulegen.
"""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

import search

FIXTURES = Path(__file__).parent / "fixtures" / "search"
ARXIV_NS = "http://www.w3.org/2005/Atom"


def _patch_client(monkeypatch, handler) -> None:
    """httpx.Client durch einen MockTransport ersetzen (Praezedenzfall #236)."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def patched_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(search.httpx, "Client", patched_client)
    monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)


def _json_handler(body: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    return handler


def _xml_handler(body: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/xml"})

    return handler


# ---------------------------------------------------------------------------
# CrossRef
# ---------------------------------------------------------------------------


def test_crossref_parses_real_fixture(monkeypatch):
    body = (FIXTURES / "crossref_response.json").read_bytes()
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_crossref("climate change", limit=3)

    assert len(results) == 3
    assert all(r["title"] for r in results)
    assert all(r["source_module"] == "crossref" for r in results)


def test_crossref_skips_broken_item_keeps_rest(monkeypatch):
    payload = json.loads((FIXTURES / "crossref_response.json").read_bytes())
    items = payload["message"]["items"]
    assert len(items) >= 2
    broken = copy.deepcopy(items[0])
    broken["published-print"] = {"date-parts": [["not-a-year"]]}
    broken.pop("published-online", None)
    mutated_items = [broken, *items[1:]]
    payload["message"]["items"] = mutated_items
    body = json.dumps(payload).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_crossref("climate change", limit=3)

    assert len(results) == len(items) - 1
    titles = {r["title"] for r in results}
    assert broken.get("title", [None])[0] not in titles


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def test_openalex_parses_real_fixture(monkeypatch):
    body = (FIXTURES / "openalex_response.json").read_bytes()
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_openalex("climate change", limit=3)

    assert len(results) == 3
    assert all(r["title"] for r in results)
    assert all(r["source_module"] == "openalex" for r in results)


def test_openalex_skips_broken_item_keeps_rest(monkeypatch):
    payload = json.loads((FIXTURES / "openalex_response.json").read_bytes())
    items = payload["results"]
    assert len(items) >= 2
    broken = copy.deepcopy(items[0])
    broken["authorships"] = "not-a-list"  # bricht a.get(...) im Autoren-Loop
    mutated_items = [broken, *items[1:]]
    payload["results"] = mutated_items
    body = json.dumps(payload).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_openalex("climate change", limit=3)

    assert len(results) == len(items) - 1
    titles = {r["title"] for r in results}
    assert broken.get("title") not in titles


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------


def test_semantic_scholar_parses_real_fixture(monkeypatch):
    body = (FIXTURES / "semantic_scholar_response.json").read_bytes()
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_semantic_scholar("climate change", limit=3)

    assert len(results) == 3
    assert all(r["title"] for r in results)
    assert all(r["source_module"] == "semantic_scholar" for r in results)


def test_semantic_scholar_skips_broken_item_keeps_rest(monkeypatch):
    payload = json.loads((FIXTURES / "semantic_scholar_response.json").read_bytes())
    items = payload["data"]
    assert len(items) >= 2
    broken = copy.deepcopy(items[0])
    broken["authors"] = "not-a-list"  # bricht a.get("name") im Autoren-Loop
    mutated_items = [broken, *items[1:]]
    payload["data"] = mutated_items
    body = json.dumps(payload).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_semantic_scholar("climate change", limit=3)

    assert len(results) == len(items) - 1
    titles = {r["title"] for r in results}
    assert broken.get("title") not in titles


# ---------------------------------------------------------------------------
# BASE
# ---------------------------------------------------------------------------


def test_base_parses_real_fixture(monkeypatch):
    body = (FIXTURES / "base_response.json").read_bytes()
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_base("climate change", limit=3)

    assert len(results) == 3
    assert all(r["title"] for r in results)
    assert all(r["source_module"] == "base" for r in results)


def test_base_skips_non_dict_item_keeps_rest(monkeypatch):
    payload = json.loads((FIXTURES / "base_response.json").read_bytes())
    docs = payload["response"]["docs"]
    assert len(docs) >= 2
    mutated_docs = ["not-a-dict-doc-entry", *docs[1:]]
    payload["response"]["docs"] = mutated_docs
    payload["response"]["numFound"] = len(mutated_docs)
    body = json.dumps(payload).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_base("climate change", limit=3)

    assert len(results) == len(docs) - 1


# ---------------------------------------------------------------------------
# EconBiz
# ---------------------------------------------------------------------------


def test_econbiz_parses_real_fixture(monkeypatch):
    body = (FIXTURES / "econbiz_response.json").read_bytes()
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_econbiz("climate change", limit=3)

    assert len(results) == 3
    assert all(r["title"] for r in results)
    assert all(r["source_module"] == "econbiz" for r in results)


def test_econbiz_skips_non_dict_item_keeps_rest(monkeypatch):
    payload = json.loads((FIXTURES / "econbiz_response.json").read_bytes())
    hits = payload["hits"]["hits"]
    assert len(hits) >= 2
    mutated_hits = ["not-a-dict-hit", *hits[1:]]
    payload["hits"]["hits"] = mutated_hits
    body = json.dumps(payload).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_econbiz("climate change", limit=3)

    assert len(results) == len(hits) - 1


# ---------------------------------------------------------------------------
# EconStor (REST-Pfad -- der OAI-Fallback-Pfad ist bereits durch
# tests/test_issue_236_econstor_limit.py abgedeckt; hier: Nicht-Dict-Items
# im REST-Pfad werden uebersprungen UND geloggt, siehe #456-Plan Punkt 5)
# ---------------------------------------------------------------------------


def test_econstor_rest_parses_real_shaped_items(monkeypatch):
    # EconStor's REST-Endpunkt liefert bei einfachem GET aktuell HTTP 405
    # (siehe create_fixtures.py) -- production Code faellt dadurch immer auf
    # OAI-PMH zurueck. Der REST-Pfad selbst wird hier isoliert mit einem
    # Response-Shape getestet, das der DSpace-REST-API (find-by-metadata-field)
    # entspricht (dieselbe Form, die der bestehende Parser-Code erwartet).
    items = [
        {"doi": "10.1234/a", "title": "Paper A", "authors": ["Autor A"], "year": 2020},
        {"doi": "10.1234/b", "title": "Paper B", "authors": ["Autor B"], "year": 2021},
    ]
    body = json.dumps(items).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_econstor("climate change", limit=3)

    assert len(results) == 2
    assert all(r["source_module"] == "econstor" for r in results)


def test_econstor_rest_skips_non_dict_item_and_logs(monkeypatch, caplog):
    items = [
        {"doi": "10.1234/a", "title": "Paper A", "authors": ["Autor A"], "year": 2020},
        "not-a-dict-item",
        {"doi": "10.1234/b", "title": "Paper B", "authors": ["Autor B"], "year": 2021},
    ]
    body = json.dumps(items).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    with caplog.at_level("WARNING"):
        results = search.search_econstor("climate change", limit=3)

    assert len(results) == 2
    assert any("econstor" in rec.message.lower() for rec in caplog.records)


def test_econstor_oai_parses_real_fixture(monkeypatch):
    # Realer OAI-PMH-Fallback-Response (der Pfad, der im Live-Betrieb
    # tatsaechlich durchlaufen wird, siehe create_fixtures.py-Docstring).
    oai_body = (FIXTURES / "econstor_oai_response.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "find-by-metadata-field" in url:
            return httpx.Response(503, text="upstream down")
        if "oai/request" in url:
            return httpx.Response(200, content=oai_body)
        return httpx.Response(404, text="")

    _patch_client(monkeypatch, handler)

    results = search.search_econstor("Knowledge", limit=3)

    assert len(results) >= 1
    assert all(r["source_module"] == "econstor" for r in results)


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------


def test_arxiv_parses_real_fixture(monkeypatch):
    body = (FIXTURES / "arxiv_response.xml").read_bytes()
    _patch_client(monkeypatch, _xml_handler(body))

    results = search.search_arxiv("climate change", limit=3)

    assert len(results) == 3
    assert all(r["title"] for r in results)
    assert all(r["source_module"] == "arxiv" for r in results)


def test_arxiv_skips_broken_item_keeps_rest(monkeypatch):
    raw = (FIXTURES / "arxiv_response.xml").read_text(encoding="utf-8")
    ET.register_namespace("", ARXIV_NS)
    root = ET.fromstring(raw)
    entries = root.findall(f"{{{ARXIV_NS}}}entry")
    assert len(entries) >= 2
    published_el = entries[0].find(f"{{{ARXIV_NS}}}published")
    assert published_el is not None
    published_el.text = "not-a-year"  # len >= 4, aber int() bricht
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    _patch_client(monkeypatch, _xml_handler(body))

    results = search.search_arxiv("climate change", limit=3)

    assert len(results) == len(entries) - 1
