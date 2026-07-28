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

- BASE (api.base-search.net): der Endpunkt blockt Anfragen aus dieser
  Sandbox-Umgebung generell mit HTTP 200 + `{"error": "Access denied for IP
  address ..."}` (IP-basierter Block, unabhaengig vom User-Agent; die
  Hauptseite www.base-search.net ist dagegen erreichbar -- Stand 2026-07-28,
  nicht bei jedem Lauf erneut verifiziert). Ein echter Live-Pull ist aus
  dieser Umgebung daher nicht moeglich. Die Fixture `base_response.json` ist
  stattdessen von Hand aus dem in `search.py` bereits verwendeten
  Feldschema (dctitle/dccreator/dcyear/dcabstract/dcpublisher/dcidentifier)
  rekonstruiert -- NICHT verifiziert gegen eine aktuelle Live-Antwort. Wer
  Zugriff auf eine nicht geblockte IP hat, sollte sie durch einen echten
  Pull ersetzen:

    curl "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi\
?func=PerformSearch&query=climate+change&format=json&hits=3" \
        -o tests/fixtures/search/base_response.json
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

OUT = Path(__file__).parent
QUERY = "climate change"
LIMIT = 3


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
    print(
        "BASE (base_response.json) NICHT ueberschrieben -- Endpunkt blockt "
        "diese Sandbox-IP, siehe Docstring. Von Hand ersetzen, falls eine "
        "nicht-geblockte Umgebung verfuegbar ist."
    )


if __name__ == "__main__":
    main()
