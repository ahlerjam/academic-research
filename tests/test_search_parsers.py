"""Parser-Tests fuer die 7 Suchmodule (Issue #456).

AC3: je Suchmodul ein Test gegen eine eingefrorene echte Antwort
     (tests/fixtures/search/, siehe create_fixtures.py fuer Herkunft).
     6/7 Fixtures sind live von der echten API geholt; BASE ist
     registrierungspflichtig und deshalb aus keiner unregistrierten Umgebung
     live abrufbar -- dort ist die vom Betreiber selbst veroeffentlichte
     PerformSearch-Antwort eingefroren (Details im Provenienz-Block bei den
     BASE-Tests). test_ac3_real_fixture_tests_only_use_generated_fixtures
     (unten) haelt fest, dass keine dieser Fixtures von Hand entstehen kann.
AC1: ein fehlerhafter Einzeldatensatz wird uebersprungen, die uebrigen
     Treffer eines Moduls bleiben erhalten -- keine Exception propagiert.

Jeder Negativ-Test mutiert eine In-Memory-Kopie der echten Fixture (ein
Item wird kaputt gemacht) statt eine eigene kaputte Fixture-Datei
anzulegen.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
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
#
# Provenienz der Fixture (AC3): api.base-search.net ist kein oeffentlicher
# Endpunkt. Der BASE Interface Guide v1.27 (Maerz 2023), Abschnitt "BASE HTTP
# Interface", haelt fest: "The interface is IP controlled or with an apikey and
# interested users have to register". Ohne Registrierung antwortet der Endpunkt
# mit HTTP 200 + {"error": "Access denied for IP address ... and user agent
# ..."} -- am 2026-07-28 live gegengeprueft (curl und WebFetch). Ein Live-Pull
# ist damit in KEINER unregistrierten Umgebung moeglich, auch nicht in CI; die
# frueher hier dokumentierte "Sandbox-IP" war nicht die Ursache.
#
# Eingefroren ist deshalb die vom API-Betreiber selbst veroeffentlichte
# PerformSearch-Antwort aus dem BASE Interface Guide v1.27, Abschnitt
# "Example Response Format" (S. 6-8):
#   https://www.base-search.net/about/download/base_interface.pdf
#   Snapshot: https://web.archive.org/web/20250702101712/
#             https://www.base-search.net/about/download/base_interface.pdf
# -> tests/fixtures/search/base_documented_response.xml (Zeilenumbrueche des
#    PDF-Satzes rueckgaengig gemacht, Fortsetzungsmarker "(...)" hinter dem
#    einzigen abgedruckten <doc> entfernt, damit die Datei parst -- dieselbe
#    Art Kuerzung wie bei der EconStor-OAI-Fixture).
#
# Der enthaltene Datensatz ist echt und unabhaengig gegengeprueft gegen
# pub.uni-bielefeld.de/record/2710028: "10 years BASE: A contribution to the
# worldwide development of repositories", Pieper/Summann, 2014.
#
# search_base() ruft format=json ab. base_response.json wird daher mechanisch
# aus dem XML erzeugt (create_fixtures.py::solr_xml_to_json, Solr-XML-Writer ->
# JSON-Writer); test_base_json_fixture_is_derived_from_documented_xml haelt das
# fest. An der Fixture ist damit nichts von Hand erfunden -- der frueher hier
# aus dem Parser-Feldschema rekonstruierte Datensatz war zirkulaer (er konnte
# den Parser nicht widerlegen) und hat einen echten Feldfehler verdeckt, siehe
# test_base_reads_abstract_from_documented_dcdescription_field.
# ---------------------------------------------------------------------------


def _create_fixtures_module():
    """create_fixtures.py als Modul laden (kein Package, daher per Pfad)."""
    spec = importlib.util.spec_from_file_location(
        "search_create_fixtures", FIXTURES / "create_fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_base_json_fixture_is_derived_from_documented_xml():
    """base_response.json muss exakt die mechanische Solr-XML->JSON-Umsetzung
    der eingefrorenen Betreiber-Antwort sein -- so kann sich keine von Hand
    erfundene Struktur einschleichen (Review-Finding zu PR #477)."""
    solr_xml_to_json = _create_fixtures_module().solr_xml_to_json

    derived = solr_xml_to_json((FIXTURES / "base_documented_response.xml").read_bytes())
    checked_in = json.loads((FIXTURES / "base_response.json").read_bytes())

    assert derived == checked_in


def test_base_parses_real_fixture(monkeypatch):
    body = (FIXTURES / "base_response.json").read_bytes()
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_base("climate change", limit=3)

    assert len(results) == 1
    paper = results[0]
    assert paper["title"] == (
        "10 years BASE: A contribution to the worldwide development of repositories"
    )
    assert paper["authors"] == ["Pieper, Dirk", "Summann, Friedrich"]
    assert paper["year"] == 2014
    assert paper["url"] == "https://pub.uni-bielefeld.de/record/2710028"
    assert paper["source_module"] == "base"


def test_base_reads_abstract_from_documented_dcdescription_field(monkeypatch):
    """BASE kennt kein Feld 'dcabstract'. Laut Interface Guide v1.27,
    Appendix 2 ("Fields"), heisst das Abstract-Feld 'dcdescription' (single);
    'dcabstract' kommt im gesamten Guide nicht vor und steht auch nicht in der
    'fl'-Feldliste der Betreiber-Beispielantwort. Der Parser las bisher
    'dcabstract' -- BASE-Treffer hatten daher immer abstract=None."""
    payload = json.loads((FIXTURES / "base_response.json").read_bytes())
    abstract = "A short abstract as delivered by BASE in the dcdescription field."
    payload["response"]["docs"][0]["dcdescription"] = abstract
    body = json.dumps(payload).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_base("climate change", limit=3)

    assert results[0]["abstract"] == abstract


def test_base_skips_non_dict_item_keeps_rest(monkeypatch):
    payload = json.loads((FIXTURES / "base_response.json").read_bytes())
    docs = payload["response"]["docs"]
    assert len(docs) == 1
    payload["response"]["docs"] = ["not-a-dict-doc-entry", *docs]
    payload["response"]["numFound"] = 2
    body = json.dumps(payload).encode("utf-8")
    _patch_client(monkeypatch, _json_handler(body))

    results = search.search_base("climate change", limit=3)

    assert len(results) == 1
    assert results[0]["title"].startswith("10 years BASE")


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


def test_arxiv_parses_iso8859_1_response_without_charset_header(monkeypatch):
    """Issue #464 AC1: eine XML-Antwort mit abweichender Zeichenkodierung
    (ISO-8859-1) und OHNE charset-Angabe im HTTP-Content-Type muss anhand
    der im XML-Prolog deklarierten Kodierung korrekt dekodiert werden.

    Vor dem Fix wird resp.text (immer UTF-8-dekodiert von httpx mangels
    charset-Header) an ET.fromstring() uebergeben -- der Umlaut wird dabei
    zu Mojibake. Nach dem Fix gehen die rohen Bytes (resp.content) an
    ET.fromstring(), Expat wertet die Prolog-Deklaration selbst aus."""
    body = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
        f'<feed xmlns="{ARXIV_NS}">\n'
        "  <entry>\n"
        "    <id>http://arxiv.org/abs/2401.00001v1</id>\n"
        "    <title>Über Klimaänderungen in Süddeutschland</title>\n"
        "    <summary>Zusammenfassung mit Umlauten: Größe, Wärme.</summary>\n"
        "    <author><name>Müller, Jürgen</name></author>\n"
        "    <published>2024-01-01T00:00:00Z</published>\n"
        '    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v1"/>\n'
        "  </entry>\n"
        "</feed>\n"
    ).encode("iso-8859-1")
    _patch_client(monkeypatch, _xml_handler(body))

    results = search.search_arxiv("climate change", limit=3)

    assert len(results) == 1
    assert results[0]["title"] == "Über Klimaänderungen in Süddeutschland"
    assert results[0]["authors"] == ["Müller, Jürgen"]


# ---------------------------------------------------------------------------
# AC3-Provenienz-Guard (Review-Finding zu PR #477 / Issue #456): ein Test darf
# sich nur dann "..._parses_real_fixture" nennen, wenn die benutzte Fixture
# nachweislich von create_fixtures.py stammt -- also entweder live von der
# echten API geholt (6 Module) oder mechanisch aus der eingefrorenen
# Betreiber-Antwort abgeleitet (BASE, siehe Provenienz-Block oben). Eine von
# Hand geschriebene Datei ins Fixture-Verzeichnis zu legen und den Test
# "real_fixture" zu nennen, faellt damit auf -- genau der Fehler, den die
# frueher hier eingefrorene BASE-Ausnahme festgehalten hat.
# ---------------------------------------------------------------------------


def test_ac3_real_fixture_tests_only_use_generated_fixtures():
    source = Path(__file__).read_text(encoding="utf-8")
    generator = (FIXTURES / "create_fixtures.py").read_text(encoding="utf-8")

    pattern = re.compile(
        r"^def (test_\w+_parses_real_fixture)\(.*?(?=^def |\Z)", re.MULTILINE | re.DOTALL
    )
    matches = list(pattern.finditer(source))
    assert len(matches) == 7, (
        f"AC3 verlangt je Suchmodul einen Test gegen eine eingefrorene echte "
        f"Antwort -- gefunden: {[m.group(1) for m in matches]}"
    )

    for match in matches:
        func_name, body = match.group(1), match.group(0)
        used = re.findall(r'FIXTURES / "([^"]+)"', body)
        assert used, f"{func_name} liest keine Fixture-Datei -- Name ist irrefuehrend."
        for fixture_name in used:
            assert (FIXTURES / fixture_name).exists(), f"{func_name}: {fixture_name} fehlt."
            assert fixture_name in generator, (
                f"{func_name} nennt sich 'real_fixture', aber '{fixture_name}' wird von "
                "create_fixtures.py nicht erzeugt -- die Herkunft der Datei ist damit "
                "unbelegt. Entweder in create_fixtures.py aufnehmen (Live-Pull oder "
                "dokumentierte Ableitung) oder den Test umbenennen (Praezedenzfall: "
                "test_econstor_rest_parses_real_shaped_items)."
            )
