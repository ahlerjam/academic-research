"""Tests fuer book_resolve.py — DNB/OL/GoogleBooks/DOAB Clients."""

from unittest.mock import MagicMock, patch

# Sicherstellen dass scripts/ im Pfad ist


# ---------------------------------------------------------------------------
# Hilfs-Fixtures
# ---------------------------------------------------------------------------

DNB_SRU_RESPONSE_ISBN = b"""<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
  <numberOfRecords>1</numberOfRecords>
  <records>
    <record>
      <recordData>
        <record xmlns="http://www.loc.gov/MARC21/slim">
          <datafield tag="245" ind1=" " ind2=" ">
            <subfield code="a">Werkzeugmaschinen</subfield>
            <subfield code="b">Grundlagen</subfield>
          </datafield>
          <datafield tag="100" ind1=" " ind2=" ">
            <subfield code="a">Tschaetsch, Heinz</subfield>
          </datafield>
          <datafield tag="264" ind1=" " ind2="1">
            <subfield code="b">Hanser</subfield>
            <subfield code="c">2014</subfield>
          </datafield>
          <datafield tag="020" ind1=" " ind2=" ">
            <subfield code="a">9783446461031</subfield>
          </datafield>
        </record>
      </recordData>
    </record>
  </records>
</searchRetrieveResponse>"""

DNB_SRU_EMPTY = b"""<?xml version="1.0"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
  <numberOfRecords>0</numberOfRecords>
  <records/>
</searchRetrieveResponse>"""

OL_RESPONSE = {
    "ISBN:9783446461031": {
        "title": "Werkzeugmaschinen Grundlagen",
        "authors": [{"name": "Tschätsch, Heinz"}],
        "publishers": [{"name": "Hanser"}],
        "publish_date": "2014",
        "isbn_13": ["9783446461031"],
    }
}

GB_RESPONSE = {
    "kind": "books#volumes",
    "totalItems": 1,
    "items": [
        {
            "volumeInfo": {
                "title": "Werkzeugmaschinen Grundlagen",
                "authors": ["Tschätsch, Heinz"],
                "publisher": "Hanser",
                "publishedDate": "2014",
                "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9783446461031"}],
            }
        }
    ],
}

DOAB_RESPONSE = [
    {
        "uuid": "abc123",
        "metadata": [
            {"key": "dc.title", "value": "Open Access Buch"},
            {"key": "dc.identifier.uri", "value": "https://oapen.org/record/12345"},
        ],
        "bitstreams": [
            {
                "bundleName": "ORIGINAL",
                "mimeType": "application/pdf",
                "retrieveLink": "/bitstream/handle/123/book.pdf",
            }
        ],
    }
]


def _make_mock_response(content: bytes, status: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.content = content
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ---------------------------------------------------------------------------
# DNB SRU Tests
# ---------------------------------------------------------------------------


def test_dnb_isbn_hit():
    """ISBN 9783446461031 liefert DNB-Treffer mit type=book und title."""
    import book_resolve

    with patch("book_resolve.requests.get") as mock_get:
        mock_get.return_value = _make_mock_response(DNB_SRU_RESPONSE_ISBN)
        result = book_resolve.resolve_dnb(isbn="9783446461031")

    assert result is not None
    assert result.get("type") == "book"
    assert "Werkzeugmaschinen" in result.get("title", "")
    assert result.get("ISBN") == "9783446461031"


# ---------------------------------------------------------------------------
# OpenLibrary Fallback Tests
# ---------------------------------------------------------------------------


def test_openlibrary_fallback():
    """DNB leer -> OpenLibrary liefert Daten."""
    import book_resolve

    def _make_json_response(data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("book_resolve.requests.get") as mock_get:

        def side_effect(url, **kwargs):
            if "dnb.de" in url:
                return _make_mock_response(DNB_SRU_EMPTY)
            elif "openlibrary.org" in url:
                return _make_json_response(OL_RESPONSE)
            else:
                # DOAB und andere: leer zurueckgeben
                return _make_json_response([])

        mock_get.side_effect = side_effect
        result = book_resolve.resolve(isbn="9783446461031")

    assert result is not None
    assert result.get("type") == "book"
    assert "Werkzeugmaschinen" in result.get("title", "")


# ---------------------------------------------------------------------------
# GoogleBooks Fallback Tests
# ---------------------------------------------------------------------------


def test_googlebooks_fallback():
    """DNB + OL leer -> GoogleBooks liefert Daten."""
    import book_resolve

    def _make_json_response(data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("book_resolve.requests.get") as mock_get:

        def side_effect(url, **kwargs):
            if "dnb.de" in url:
                return _make_mock_response(DNB_SRU_EMPTY)
            elif "openlibrary.org" in url:
                return _make_json_response({})
            elif "googleapis.com" in url:
                return _make_json_response(GB_RESPONSE)
            else:
                # DOAB: leer
                return _make_json_response([])

        mock_get.side_effect = side_effect
        result = book_resolve.resolve(isbn="9783446461031")

    assert result is not None
    assert result.get("type") == "book"
    assert result.get("ISBN") == "9783446461031"


# ---------------------------------------------------------------------------
# Buch-Identitaetspruefung (Issue #464 AC3): Google Books' q=isbn:... ist
# eine Volltextsuche, keine exakte Index-Abfrage -- items[0] kann ein
# Fremdtreffer sein. Vor dem Fix wurden dessen Metadaten ungeprueft
# uebernommen, obwohl die gelieferte industryIdentifiers/isbn_13-Kennung
# nicht zur angefragten ISBN passt.
# ---------------------------------------------------------------------------

GB_RESPONSE_MISMATCHED_ISBN = {
    "kind": "books#volumes",
    "totalItems": 1,
    "items": [
        {
            "volumeInfo": {
                "title": "Voellig anderes Buch",
                "authors": ["Fremdautor, Falsch"],
                "publisher": "Anderer Verlag",
                "publishedDate": "1999",
                "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9999999999999"}],
            }
        }
    ],
}

OL_RESPONSE_MISMATCHED_ISBN = {
    "ISBN:9783446461031": {
        "title": "Voellig anderes Buch",
        "authors": [{"name": "Fremdautor, Falsch"}],
        "publishers": [{"name": "Anderer Verlag"}],
        "publish_date": "1999",
        "isbn_13": ["9999999999999"],
    }
}


def test_googlebooks_rejects_mismatched_isbn_hit():
    """GoogleBooks liefert einen Treffer, dessen industryIdentifiers nicht
    zur angefragten ISBN passen -- resolve_googlebooks muss None liefern
    statt der Fremdtreffer-Metadaten (Issue #464 AC3)."""
    import book_resolve

    with patch("book_resolve.requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = GB_RESPONSE_MISMATCHED_ISBN
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = book_resolve.resolve_googlebooks(isbn="9783446461031")

    assert result is None, f"Erwartet None bei Fremdtreffer, erhalten {result}"


def test_openlibrary_rejects_mismatched_isbn_hit():
    """OpenLibrary liefert einen Treffer, dessen isbn_13 nicht zur
    angefragten ISBN passt -- resolve_openlibrary muss None liefern statt
    der Fremdtreffer-Metadaten (Issue #464 AC3)."""
    import book_resolve

    def _make_json_response(data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("book_resolve.requests.get") as mock_get:
        mock_get.return_value = _make_json_response(OL_RESPONSE_MISMATCHED_ISBN)

        result = book_resolve.resolve_openlibrary(isbn="9783446461031")

    assert result is None, f"Erwartet None bei Fremdtreffer, erhalten {result}"


def test_resolve_does_not_leak_mismatched_googlebooks_hit():
    """resolve() end-to-end: DNB + OL leer, GoogleBooks liefert nur einen
    Fremdtreffer -- die falschen Metadaten duerfen NICHT im Endergebnis
    landen (Issue #464 AC3)."""
    import book_resolve

    def _make_json_response(data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("book_resolve.requests.get") as mock_get:

        def side_effect(url, **kwargs):
            if "dnb.de" in url:
                return _make_mock_response(DNB_SRU_EMPTY)
            elif "openlibrary.org" in url:
                return _make_json_response({})
            elif "googleapis.com" in url:
                return _make_json_response(GB_RESPONSE_MISMATCHED_ISBN)
            else:
                # DOAB: leer
                return _make_json_response([])

        mock_get.side_effect = side_effect
        result = book_resolve.resolve(isbn="9783446461031")

    assert result.get("title") != "Voellig anderes Buch", (
        f"Fremdtreffer-Titel ist ins Ergebnis durchgesickert: {result}"
    )


# ---------------------------------------------------------------------------
# PR #489-Review-Nachbesserung zu Issue #464 AC3:
# _isbn_matches() verglich Kennungen bislang als exakte Rohstrings -- gueltige
# Treffer wurden verworfen, wenn sich Gross-/Kleinschreibung der 'X'-
# Pruefziffer unterschied oder eine Seite ISBN-10, die andere ISBN-13
# fuehrte. Beide Faelle sind in der Praxis haeufig (GoogleBooks liefert
# ISBN_10 z. B. als "038797627X", waehrend Nutzer haeufig kleingeschrieben
# anfragen).
# ---------------------------------------------------------------------------

GB_RESPONSE_ISBN10_UPPERCASE_X = {
    "kind": "books#volumes",
    "totalItems": 1,
    "items": [
        {
            "volumeInfo": {
                "title": "A Classical Introduction to Modern Number Theory",
                "authors": ["Ireland, Kenneth", "Rosen, Michael"],
                "publisher": "Springer",
                "publishedDate": "1990",
                "industryIdentifiers": [{"type": "ISBN_10", "identifier": "038797627X"}],
            }
        }
    ],
}

OL_RESPONSE_NESTED_IDENTIFIERS_MISMATCHED = {
    "ISBN:9783446461031": {
        "title": "Voellig anderes Buch",
        "authors": [{"name": "Fremdautor, Falsch"}],
        "publishers": [{"name": "Anderer Verlag"}],
        "publish_date": "1999",
        # Reales jscmd=data-Antwortformat (empirisch verifiziert gegen die
        # OpenLibrary-API): Kennungen stehen unter "identifiers", nicht auf
        # oberster Ebene der Antwort.
        "identifiers": {"isbn_13": ["9999999999999"]},
    }
}


def test_isbn_matches_is_case_insensitive_for_check_digit():
    """Die 'X'-Pruefziffer bei ISBN-10 muss unabhaengig von Gross-/
    Kleinschreibung als Treffer erkannt werden -- sonst verwirft
    _isbn_matches() gueltige Treffer (P1-Finding aus dem PR #489-Review)."""
    import book_resolve

    assert book_resolve._isbn_matches("038797627x", ["038797627X"]) is True
    assert book_resolve._isbn_matches("038797627X", ["038797627x"]) is True


def test_isbn_matches_recognizes_isbn10_isbn13_equivalence():
    """Eine angefragte ISBN-10 muss den semantisch identischen ISBN-13-
    Kandidaten (Praefix 978 + neu berechnete Pruefziffer) als Treffer
    erkennen -- und umgekehrt (P1-Finding aus dem PR #489-Review)."""
    import book_resolve

    isbn10 = "0387976272"
    isbn13 = "9780387976273"  # Praefix 978 + Kern von isbn10, neue Pruefziffer

    assert book_resolve._isbn_matches(isbn10, [isbn13]) is True
    assert book_resolve._isbn_matches(isbn13, [isbn10]) is True
    # Ein tatsaechlich abweichender Fremdtreffer muss weiterhin verworfen werden.
    assert book_resolve._isbn_matches(isbn10, ["9999999999999"]) is False
    assert book_resolve._isbn_matches(isbn13, ["9999999999"]) is False


def test_googlebooks_accepts_isbn10_hit_for_lowercase_x_request():
    """Reproduktion des im PR #489-Review konkret beschriebenen
    Fehlerszenarios: `--isbn 038797627x` (lowercase x) gegen einen
    GoogleBooks-Treffer mit ISBN_10 "038797627X" (uppercase). Vor dem Fix
    verwarf resolve_googlebooks() diesen korrekten Treffer als
    vermeintlichen Fremdtreffer."""
    import book_resolve

    with patch("book_resolve.requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = GB_RESPONSE_ISBN10_UPPERCASE_X
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = book_resolve.resolve_googlebooks(isbn="038797627x")

    assert result is not None, "Korrekter Treffer wurde faelschlich als Fremdtreffer verworfen"
    assert result["title"] == "A Classical Introduction to Modern Number Theory"


def test_openlibrary_rejects_mismatched_isbn_in_nested_identifiers():
    """OpenLibrarys reale jscmd=data-Antwort fuehrt Kennungen unter
    item["identifiers"]["isbn_13"], nicht auf oberster Ebene der Antwort
    (P2-Finding aus dem PR #489-Review). Ein Fremdtreffer in dieser Form
    muss weiterhin verworfen werden."""
    import book_resolve

    def _make_json_response(data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = data
        resp.raise_for_status = MagicMock()
        return resp

    with patch("book_resolve.requests.get") as mock_get:
        mock_get.return_value = _make_json_response(OL_RESPONSE_NESTED_IDENTIFIERS_MISMATCHED)

        result = book_resolve.resolve_openlibrary(isbn="9783446461031")

    assert result is None, f"Erwartet None bei Fremdtreffer, erhalten {result}"


# ---------------------------------------------------------------------------
# DOAB OA-Check Tests
# ---------------------------------------------------------------------------


def test_doab_oa_check():
    """DOAB-Check liefert OA-Flag und download_url."""
    import book_resolve

    with patch("book_resolve.requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = DOAB_RESPONSE
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        result = book_resolve.check_doab(isbn="9783446461031")

    assert result is not None
    assert result.get("open_access") is True
    assert "download_url" in result


def test_doab_doi_oapen_lookup():
    """DOAB-DOI-Lookup liefert open_access=True und OAPEN/DOAB-URL."""
    import book_resolve

    doi = "10.1007/978-3-658-12345-6"

    with patch("book_resolve.requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = DOAB_RESPONSE
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        result = book_resolve.check_doab(doi=doi)

    assert result is not None
    assert result.get("open_access") is True
    assert "download_url" in result
    url = result["download_url"]
    assert any(kw in url.lower() for kw in ("oapen", "doab", "/bitstream")), (
        f"download_url enthält kein erwartetes Keyword: {url}"
    )


def test_no_source_returns_empty():
    """Alle Quellen schlagen fehl → leeres dict, kein crash."""
    import book_resolve

    with patch("book_resolve.requests.get") as mock_get:
        mock_get.side_effect = Exception("Netzwerkfehler")
        result = book_resolve.resolve(isbn="0000000000000")

    assert result == {} or result is None  # Kein crash


def test_isbn_csl_has_required_fields():
    """CSL-JSON enthält immer type, title."""
    import book_resolve

    with patch("book_resolve.requests.get") as mock_get:
        mock_get.return_value = _make_mock_response(DNB_SRU_RESPONSE_ISBN)
        result = book_resolve.resolve(isbn="9783446461031")

    assert result.get("type") in ("book", "chapter")
    assert result.get("title"), "title darf nicht leer sein"


def test_parse_name_splits_family_given():
    """Issue #908: _parse_name() nutzt den geteilten Parser aus text_utils
    (DRY) -- 'Nachname, Vorname' wird weiterhin korrekt zerlegt."""
    import book_resolve

    assert book_resolve._parse_name("Tschaetsch, Heinz") == {
        "family": "Tschaetsch",
        "given": "Heinz",
    }


def test_parse_name_unparseable_falls_back_to_literal():
    """Issue #908: ein Name ohne Komma (z.B. Organisation) wird nicht
    geraten, sondern als literal durchgereicht."""
    import book_resolve

    assert book_resolve._parse_name("Deutsche Bundesbank") == {"literal": "Deutsche Bundesbank"}
