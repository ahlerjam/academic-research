"""Regression tests for issue #393 — DBLP als zusaetzliche Quelle im Fetcher.

Akzeptanzkriterien (#393):
- `search_dblp(query, limit)` liefert ein valides Ergebnis-Objekt mit
  `source_module: "dblp"` (gemockter Erfolgsfall) oder einen sauber
  behandelten Fehler ueber `_run_module`, keinen Crash.
- `dblp` ist im `MODULES`-Dict registriert und ueber `--modules` waehlbar.
"""

import httpx

import search


def _mock_client_factory(transport: httpx.MockTransport):
    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    return patched_client


def test_search_dblp_happy_path_mixed_author_shapes(monkeypatch):
    """Ein Hit mit Einzelautor (Objekt), einer mit Autorenliste — beide Formen abgedeckt."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "dblp.org/search/publ/api" in str(request.url)
        assert request.url.params["q"] == "graph neural networks"
        assert request.url.params["format"] == "json"
        assert request.url.params["h"] == "2"
        body = {
            "result": {
                "hits": {
                    "@total": "2",
                    "hit": [
                        {
                            "info": {
                                "title": "Solo-Authored Paper.",
                                "venue": "ICML",
                                "year": "2021",
                                "doi": "10.1234/solo",
                                "ee": "https://doi.org/10.1234/solo",
                                "authors": {"author": {"@pid": "1/1", "text": "Alice Solo"}},
                            }
                        },
                        {
                            "info": {
                                "title": "Multi-Authored Paper.",
                                "venue": "NeurIPS",
                                "year": "2022",
                                "ee": "https://example.org/multi",
                                "authors": {
                                    "author": [
                                        {"@pid": "2/1", "text": "Bob Multi"},
                                        {"@pid": "2/2", "text": "Carol Multi"},
                                    ]
                                },
                            }
                        },
                    ],
                }
            }
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(search.httpx, "Client", _mock_client_factory(transport))
    monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)

    results = search.search_dblp("graph neural networks", limit=2)

    assert len(results) == 2

    solo = results[0]
    assert solo["source_module"] == "dblp"
    assert solo["title"] == "Solo-Authored Paper."
    assert solo["venue"] == "ICML"
    assert solo["year"] == 2021
    assert solo["doi"] == "10.1234/solo"
    assert solo["url"] == "https://doi.org/10.1234/solo"
    assert solo["authors"] == ["Alice Solo"]
    assert solo["abstract"] is None

    multi = results[1]
    assert multi["authors"] == ["Bob Multi", "Carol Multi"]
    assert multi["doi"] is None
    assert multi["url"] == "https://example.org/multi"


def test_search_dblp_zero_hits_no_hit_key(monkeypatch):
    """DBLP liefert bei 0 Treffern 'hits' ohne 'hit'-Key (live verifiziert)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "result": {
                "hits": {"@total": "0", "@computed": "0", "@sent": "0", "@first": "0"},
            }
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(search.httpx, "Client", _mock_client_factory(transport))
    monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)

    results = search.search_dblp("zzzznonexistentqueryxyz123", limit=5)

    assert results == []


def test_search_dblp_venue_as_list_is_flattened_to_string(monkeypatch):
    """DBLP liefert 'venue' bei Editorship-Eintraegen (Proceedings-Baende) als
    Liste statt String (live gegen die echte API verifiziert, z.B.
    journals/corr/abs-2601-00047: venue: ["ICLP", "EPTCS"]). Das Paper-Schema
    (text_utils.Paper.venue: str | None) erwartet einen String — ungefiltert
    durchgereicht wuerde eine Liste ins Schema geschrieben. Analog zum
    bestehenden Muster in search_base()'s dc()-Helper: erstes Element ziehen.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "result": {
                "hits": {
                    "@total": "1",
                    "hit": [
                        {
                            "info": {
                                "title": "Proceedings 41st ICLP.",
                                "venue": ["ICLP", "EPTCS"],
                                "year": "2026",
                                "doi": "10.4204/EPTCS.439",
                                "ee": "https://doi.org/10.4204/EPTCS.439",
                                "authors": {"author": {"@pid": "1/1", "text": "Alice Editor"}},
                            }
                        }
                    ],
                }
            }
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(search.httpx, "Client", _mock_client_factory(transport))
    monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)

    results = search.search_dblp("ICLP proceedings", limit=1)

    assert len(results) == 1
    assert results[0]["venue"] == "ICLP"
    assert isinstance(results[0]["venue"], str)


def test_search_dblp_http_error_is_caught_by_run_module(monkeypatch):
    """Ein HTTP-Fehler darf den Prozess nicht crashen — _run_module faengt ihn ab."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream down")

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(search.httpx, "Client", _mock_client_factory(transport))
    monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)

    name, papers, failed = search._run_module("dblp", "test", 5)

    assert name == "dblp"
    assert papers == []
    assert failed is True
