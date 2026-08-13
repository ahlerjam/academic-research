"""Tests fuer die Autorennamen-Normalisierung (Issue #908).

Wurzelursache: Suchmodule liefern Autoren in zwei unvereinbaren Formen
(CrossRef: "Given Family", EconStor/BASE dccreator: rohes Dublin-Core
"Family, Given"). Ein naives "letztes Wort = Nachname" trifft bei der
zweiten Form den Vornamen. `parse_author_name()`/`parse_author_names()`
erkennen das Komma-Format zuverlaessig und raten nicht bei unklaren Faellen.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import search
from text_utils import (
    ParsedAuthorName,
    csl_authors_to_parsed,
    parse_author_name,
    parse_author_names,
)

FIXTURES = Path(__file__).parent / "fixtures" / "search"


def test_econstor_crossref_same_family() -> None:
    """EconStor-dccreator-String und CrossRef given/family-Paar derselben
    Arbeit fuehren zum selben Nachnamen."""
    econstor = parse_author_name("Snell, Charlie")
    # CrossRef liefert given/family bereits getrennt -- wird direkt in
    # denselben Rueckgabetyp gemappt (kein String-Parsing noetig).
    crossref = ParsedAuthorName(given="Charlie", family="Snell", parsed=True)

    assert econstor.family == crossref.family == "Snell"


@pytest.mark.parametrize(
    "raw,expected_family",
    [
        ("Snell, Charlie", "Snell"),
        ("Huang, Dong", "Huang"),
        ("Yang, Yingxuan", "Yang"),
    ],
)
def test_regression_20260812_cases(raw: str, expected_family: str) -> None:
    """Die drei Faelle aus dem Lauf vom 12.08.2026 werden korrekt aufgeloest."""
    parsed = parse_author_name(raw)
    assert parsed.family == expected_family
    assert parsed.parsed is True


def test_unparseable_name_marked() -> None:
    """Ein Name ohne Komma (z.B. Organisation) wird nicht geraten."""
    parsed = parse_author_name("Deutsche Bundesbank")

    assert parsed.parsed is False
    assert parsed.family is None
    assert parsed.literal == "Deutsche Bundesbank"


def test_implausible_split_warns() -> None:
    """Taucht ein ermittelter Nachname als Vorname im selben Datensatz auf,
    wird gewarnt (nicht blockiert)."""
    parsed = parse_author_names(["Miller, Peter", "Peter, Someone"])

    assert parsed[0].warning is None
    assert parsed[1].warning is not None
    assert "Peter" in parsed[1].warning


def test_plausible_split_no_warning() -> None:
    """Ein unauffaelliges Datenset erzeugt keine Warnung."""
    parsed = parse_author_names(["Snell, Charlie", "Huang, Dong"])

    assert all(p.warning is None for p in parsed)


def test_display_name_formats_given_family() -> None:
    parsed = parse_author_name("Snell, Charlie")
    assert parsed.display_name() == "Charlie Snell"


def test_display_name_falls_back_to_literal() -> None:
    parsed = parse_author_name("Deutsche Bundesbank")
    assert parsed.display_name() == "Deutsche Bundesbank"


def test_main_bundles_author_warnings_into_status_sidecar(monkeypatch, tmp_path) -> None:
    """Issue #908: Warnungen aus einzelnen Modulen (hier: BASE, implausible
    Vor-/Nachnamen-Zerlegung im selben Treffer) landen gebuendelt im
    additiven Feld ``author_name_warnings`` der Sidecar-Statusdatei."""
    payload = json.loads((FIXTURES / "base_response.json").read_bytes())
    payload["response"]["docs"][0]["dccreator"] = ["Miller, Peter", "Peter, Someone"]
    body = json.dumps(payload).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(search.httpx, "Client", fake_client)

    output_path = tmp_path / "results.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "search.py",
            "--query",
            "climate change",
            "--modules",
            "base",
            "--limit",
            "3",
            "--output",
            str(output_path),
        ],
    )

    exit_code = search.main()

    assert exit_code == 0
    status = json.loads((tmp_path / "results_status.json").read_text(encoding="utf-8"))
    assert status["author_name_warnings"]
    assert "Peter" in status["author_name_warnings"][0]["warnings"][0]


def test_csl_authors_to_parsed_flags_implausible_bestand() -> None:
    """Issue #908 AC5-Baustein: derselbe Plausibilitaetscheck greift auf
    bereits zerlegten CSL-JSON-Autoren (Bestand im Vault), nicht nur auf
    Roh-Strings."""
    csl_authors = [
        {"family": "Miller", "given": "Peter"},
        {"family": "Peter", "given": "Someone"},
    ]

    parsed = csl_authors_to_parsed(csl_authors)

    assert parsed[0].warning is None
    assert parsed[1].warning is not None


def test_csl_authors_to_parsed_handles_literal_entries() -> None:
    csl_authors = [{"literal": "Deutsche Bundesbank"}]

    parsed = csl_authors_to_parsed(csl_authors)

    assert parsed[0].parsed is False
    assert parsed[0].literal == "Deutsche Bundesbank"
