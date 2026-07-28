#!/usr/bin/env python3
"""Erzeugt/aktualisiert die eingefrorenen echten API-Antworten fuer die
Parser-Tests der Suchmodule (Issue #456).

Aufruf: python tests/fixtures/search/create_fixtures.py

Fuer fuenf der sieben Quellen ruft dieses Skript die echte, oeffentliche API
live mit der Query "climate change" (limit 3) auf und speichert die
Roh-Antwort unveraendert. CI selbst bleibt danach offline/deterministisch,
da die Tests nur die Datei lesen (kein Netzwerk in Tests).

Ausnahmen:

- EconStor: der REST-Endpunkt (`find-by-metadata-field`) liefert bei einem
  einfachen GET-Request aktuell HTTP 405 (Method Not Allowed) -- production
  Code faellt dadurch immer auf den OAI-PMH-Fallback zurueck (siehe #236).
  Die eingefrorene "echte Antwort" fuer EconStor ist deshalb bewusst die
  OAI-PMH-ListRecords-Antwort (auf die ersten 3 Records gekuerzt), nicht die
  REST-Antwort -- das bildet den tatsaechlich durchlaufenen Pfad ab. Der
  REST-Pfad (isinstance(item, dict)-Check) wird in
  tests/test_search_parsers.py separat mit einer synthetischen Response
  abgedeckt, da er im Live-Betrieb aktuell nicht erreicht wird.

- BASE (api.base-search.net): der Endpunkt ist nicht oeffentlich. Der BASE
  Interface Guide v1.27 (Maerz 2023) haelt fest: "The interface is IP
  controlled or with an apikey and interested users have to register at
  https://www.base-search.net/about/en/contact.php". Nicht registrierte
  Aufrufer bekommen HTTP 200 + {"error": "Access denied for IP address ...
  and user agent ..."} -- am 2026-07-28 live gegengeprueft. Ein Live-Pull ist
  damit in KEINER unregistrierten Umgebung moeglich (auch nicht in CI), nicht
  bloss in einer Sandbox; ein "auf einer anderen IP nachziehen" gibt es ohne
  Registrierung nicht.

  Eingefroren wird deshalb die vom Betreiber selbst veroeffentlichte
  PerformSearch-Antwort aus dem Interface Guide, Abschnitt "Example Response
  Format" (S. 6-8):
    https://www.base-search.net/about/download/base_interface.pdf
    Snapshot: https://web.archive.org/web/20250702101712/
              https://www.base-search.net/about/download/base_interface.pdf
  -> `base_documented_response.xml` (Zeilenumbrueche des PDF-Satzes
  rueckgaengig gemacht, Fortsetzungsmarker "(...)" hinter dem einzigen
  abgedruckten <doc> entfernt, damit die Datei parst -- dieselbe Art Kuerzung
  wie oben bei EconStor). Der enthaltene Datensatz ist echt und unabhaengig
  gegengeprueft gegen pub.uni-bielefeld.de/record/2710028 ("10 years BASE: A
  contribution to the worldwide development of repositories",
  Pieper/Summann, 2014).

  `search_base()` ruft format=json ab; `base_response.json` wird daher hier
  mechanisch aus dem XML erzeugt (`solr_xml_to_json`), nicht von Hand
  geschrieben. tests/test_search_parsers.py::
  test_base_json_fixture_is_derived_from_documented_xml haelt das fest.

  Wer einen API-Key besitzt, kann die Fixture jederzeit durch einen echten
  Live-Pull ersetzen (dann `base_documented_response.xml` samt
  Provenienz-Test entfernen):

    curl "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi\
?func=PerformSearch&query=climate+change&format=json&hits=3&apikey=<KEY>" \
        -o tests/fixtures/search/base_response.json
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

OUT = Path(__file__).parent
QUERY = "climate change"
LIMIT = 3

# Solr-XML-Writer -> JSON-Writer. Nur diese Elementtypen kommen in einer
# BASE-PerformSearch-Antwort vor; alles andere ist ein Fehler statt einer
# stillen Annahme.
_SOLR_SCALARS: dict[str, Any] = {
    "str": lambda text: text,
    "date": lambda text: text,
    "int": int,
    "long": int,
    "float": float,
    "double": float,
    "bool": lambda text: text == "true",
}


def _solr_value(el: ET.Element) -> Any:
    tag = el.tag
    if tag in _SOLR_SCALARS:
        return _SOLR_SCALARS[tag](el.text or "")
    if tag == "null":
        return None
    if tag == "arr":
        return [_solr_value(child) for child in el]
    if tag in ("response", "lst", "doc"):
        # NamedList -> Objekt (Solr-Konvention json.nl=map).
        return {child.get("name"): _solr_value(child) for child in el}
    if tag == "result":
        out: dict[str, Any] = {
            "numFound": int(el.get("numFound", "0")),
            "start": int(el.get("start", "0")),
        }
        max_score = el.get("maxScore")
        if max_score is not None:
            out["maxScore"] = float(max_score)
        out["docs"] = [_solr_value(child) for child in el]
        return out
    raise ValueError(f"unbekanntes Solr-XML-Element: <{tag}>")


def solr_xml_to_json(xml_bytes: bytes) -> dict[str, Any]:
    """Eine Solr-XML-Writer-Antwort in die JSON-Writer-Form ueberfuehren.

    Deterministisch und ohne Handarbeit -- damit `base_response.json`
    nachweisbar aus `base_documented_response.xml` stammt. Konsumiert wird von
    `search_base()` ohnehin nur `response.docs`; die NamedList-Abbildung
    entspricht dort dem Solr-Default fuer Dokumente.
    """
    result = _solr_value(ET.fromstring(xml_bytes))
    assert isinstance(result, dict)
    return result


def fetch(name: str, url: str, params: dict) -> None:
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        (OUT / name).write_bytes(resp.content)
    print(f"geschrieben: {name}")


def fetch_econstor_oai() -> None:
    """OAI-PMH-ListRecords-Antwort holen und auf 3 Records kuerzen."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            "https://www.econstor.eu/oai/request",
            params={"verb": "ListRecords", "metadataPrefix": "oai_dc"},
        )
        resp.raise_for_status()

    ns_oai = "http://www.openarchives.org/OAI/2.0/"
    ET.register_namespace("", ns_oai)
    root = ET.fromstring(resp.content)
    list_records = root.find(f"{{{ns_oai}}}ListRecords")
    records = list_records.findall(f"{{{ns_oai}}}record")
    for rec in records[LIMIT:]:
        list_records.remove(rec)
    token = list_records.find(f"{{{ns_oai}}}resumptionToken")
    if token is not None:
        list_records.remove(token)
    ET.ElementTree(root).write(
        OUT / "econstor_oai_response.xml", encoding="UTF-8", xml_declaration=True
    )
    print("geschrieben: econstor_oai_response.xml")


def build_base_from_documented_xml() -> None:
    """base_response.json aus der eingefrorenen Betreiber-Antwort ableiten.

    Kein Netzwerkzugriff: der BASE-Endpunkt ist registrierungspflichtig (siehe
    Modul-Docstring), die Quelle ist deshalb `base_documented_response.xml`.
    """
    payload = solr_xml_to_json((OUT / "base_documented_response.xml").read_bytes())
    (OUT / "base_response.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("geschrieben: base_response.json (abgeleitet aus base_documented_response.xml)")


def main() -> None:
    fetch(
        "crossref_response.json",
        "https://api.crossref.org/works",
        {"query": QUERY, "rows": LIMIT},
    )
    fetch(
        "openalex_response.json",
        "https://api.openalex.org/works",
        {"search": QUERY, "per-page": LIMIT},
    )
    fetch(
        "semantic_scholar_response.json",
        "https://api.semanticscholar.org/graph/v1/paper/search",
        {
            "query": QUERY,
            "limit": LIMIT,
            "fields": "paperId,title,authors,year,abstract,venue,citationCount,"
            "openAccessPdf,externalIds",
        },
    )
    fetch(
        "econbiz_response.json",
        "https://api.econbiz.de/v1/search",
        {"q": QUERY, "size": LIMIT},
    )
    fetch(
        "arxiv_response.xml",
        "https://export.arxiv.org/api/query",
        {
            "search_query": f"all:{QUERY}",
            "start": 0,
            "max_results": LIMIT,
            "sortBy": "relevance",
            "sortOrder": "descending",
        },
    )
    fetch_econstor_oai()
    build_base_from_documented_xml()


if __name__ == "__main__":
    main()
