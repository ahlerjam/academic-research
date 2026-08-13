"""Tests fuer Issue #886: Known-Item-Suche als eigener Schritt.

AC1 (Live-Beleg): siehe PR-Beschreibung -- ein realer Skript-Aufruf ist per
Definition kein Unit-Test.
AC2: found_via_known_item ist im Schema erkennbar und uebersteht Dedup-Merge.
AC3: der Schritt meldet, wonach gesucht wurde -- auch bei Null-Treffern.
AC4: faellt known_works_queries aus, laeuft der Schritt trotzdem (Fallback).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from dedup import merge_group
from known_item_search import (
    FALLBACK_REASON,
    build_candidates,
    citation_heuristic_candidates,
    load_known_works_queries,
    run_known_item_search,
)
from text_utils import Paper, normalize_paper

# ---------------------------------------------------------------------------
# AC2: Schema-Feld
# ---------------------------------------------------------------------------


def test_paper_default_not_found_via_known_item():
    paper = Paper()
    assert paper.found_via_known_item is False


def test_normalize_paper_passes_through_found_via_known_item():
    result = normalize_paper({"title": "X", "found_via_known_item": True}, "crossref")
    assert result["found_via_known_item"] is True


def test_normalize_paper_defaults_found_via_known_item_false():
    result = normalize_paper({"title": "X"}, "crossref")
    assert result["found_via_known_item"] is False


# ---------------------------------------------------------------------------
# AC2: Dedup-Merge-Konsolidierung (Vorbild is_retracted, #618)
# ---------------------------------------------------------------------------


def test_merge_group_known_item_marker_survives_merge_with_unmarked_duplicate():
    thematic_dup = {
        "doi": "10.1/x",
        "title": "MetaGPT: Meta Programming for Multi-Agent Systems",
        "citations": 500,
        "found_via_known_item": False,
        "source_module": "openalex",
    }
    known_item_hit = {
        "doi": "10.1/x",
        "title": "MetaGPT: Meta Programming for Multi-Agent Systems",
        "citations": 3,
        "found_via_known_item": True,
        "source_module": "crossref",
    }
    # The thematic (unmarked) duplicate wins representative selection on
    # non-none-count/citations -- the marker must not be lost regardless.
    merged = merge_group([thematic_dup, known_item_hit])
    assert merged["found_via_known_item"] is True


def test_merge_group_stays_false_when_no_member_is_known_item():
    a = {"doi": "10.1/y", "title": "A", "citations": 10, "found_via_known_item": False}
    b = {"doi": "10.1/y", "title": "A", "citations": 5}  # field absent entirely
    merged = merge_group([a, b])
    assert merged["found_via_known_item"] is False


# ---------------------------------------------------------------------------
# AC4: Fallback ohne known_works_queries
# ---------------------------------------------------------------------------


def test_load_known_works_queries_missing_file_returns_empty():
    assert load_known_works_queries("/nonexistent/queries.json") == []


def test_load_known_works_queries_none_path_returns_empty():
    assert load_known_works_queries(None) == []


def test_load_known_works_queries_malformed_json_returns_empty(tmp_path: Path):
    bad = tmp_path / "queries.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert load_known_works_queries(str(bad)) == []


def test_load_known_works_queries_empty_field_returns_empty(tmp_path: Path):
    qf = tmp_path / "queries.json"
    qf.write_text(json.dumps({"queries": {}, "known_works_queries": []}), encoding="utf-8")
    assert load_known_works_queries(str(qf)) == []


def test_load_known_works_queries_present(tmp_path: Path):
    qf = tmp_path / "queries.json"
    qf.write_text(
        json.dumps(
            {"known_works_queries": [{"type": "title", "query": "MetaGPT", "note": "seminal work"}]}
        ),
        encoding="utf-8",
    )
    result = load_known_works_queries(str(qf))
    assert result == [{"type": "title", "query": "MetaGPT", "note": "seminal work"}]


def test_citation_heuristic_candidates_picks_top_n_by_citations():
    papers = [
        {"title": "Low", "citations": 1},
        {"title": "High", "citations": 100},
        {"title": "Mid", "citations": 10},
        {"title": "No title", "citations": 999},
    ]
    del papers[3]["title"]
    candidates = citation_heuristic_candidates(papers, top_n=2)
    queries = [c["query"] for c in candidates]
    assert queries == ["High", "Mid"]
    assert all(c["source"] == "citation_heuristic" for c in candidates)


def test_build_candidates_fallback_reason_set_when_known_works_queries_missing(tmp_path: Path):
    deduped = [{"title": "Foo", "citations": 5, "url": "https://openalex.org/W1"}]
    candidates, fallback_reason = build_candidates(None, deduped, include_reference_tally=False)
    assert fallback_reason == FALLBACK_REASON
    # Trotz ausgefallenem query-generator laeuft der Schritt mit der
    # Zitationsheuristik weiter, statt leer zu bleiben (#886 AC4).
    assert len(candidates) >= 1
    assert candidates[0]["source"] == "citation_heuristic"


def test_build_candidates_no_fallback_when_known_works_queries_present(tmp_path: Path):
    qf = tmp_path / "queries.json"
    qf.write_text(
        json.dumps({"known_works_queries": [{"type": "title", "query": "AutoGen"}]}),
        encoding="utf-8",
    )
    deduped = [{"title": "Foo", "citations": 5}]
    candidates, fallback_reason = build_candidates(str(qf), deduped, include_reference_tally=False)
    assert fallback_reason is None
    assert any(c["query"] == "AutoGen" for c in candidates)


def test_build_candidates_deduplicates_and_caps(tmp_path: Path):
    qf = tmp_path / "queries.json"
    qf.write_text(
        json.dumps({"known_works_queries": [{"type": "title", "query": "Same Title"}]}),
        encoding="utf-8",
    )
    deduped = [{"title": "Same Title", "citations": 5}, {"title": "Other", "citations": 1}]
    candidates, _ = build_candidates(
        str(qf), deduped, max_candidates=1, include_reference_tally=False
    )
    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# AC3: Report-Struktur, inkl. Null-Treffer
# ---------------------------------------------------------------------------


def test_run_known_item_search_reports_searched_for_even_on_zero_hits():
    candidates = [{"type": "title", "query": "Some Obscure Nonexistent Title XYZ"}]
    with patch("known_item_search._run_module", return_value=("crossref", [], False)):
        report = run_known_item_search(candidates, modules=["crossref"], limit=5)

    assert report["searched_for"] == candidates
    assert report["found"]["Some Obscure Nonexistent Title XYZ"] == []
    assert report["papers"] == []


def test_run_known_item_search_tags_hits_as_found_via_known_item():
    candidates = [{"type": "title", "query": "MetaGPT"}]
    hit = {"title": "MetaGPT", "citations": 500}
    with patch("known_item_search._run_module", return_value=("openalex", [hit], False)):
        report = run_known_item_search(candidates, modules=["openalex"], limit=5)

    assert report["found"]["MetaGPT"][0]["found_via_known_item"] is True
    assert report["papers"][0]["found_via_known_item"] is True


def test_run_known_item_search_multiple_candidates_all_reported():
    candidates = [
        {"type": "title", "query": "A"},
        {"type": "title", "query": "B"},
    ]
    with patch("known_item_search._run_module", return_value=("crossref", [], False)):
        report = run_known_item_search(candidates, modules=["crossref"], limit=5)

    assert len(report["searched_for"]) == 2
    assert set(report["found"].keys()) == {"A", "B"}


# ---------------------------------------------------------------------------
# Doku-Assertions: commands/search.md beschreibt den neuen Schritt (#886)
# ---------------------------------------------------------------------------

_SEARCH_MD = (Path(__file__).parent.parent / "commands" / "search.md").read_text(encoding="utf-8")


def test_search_md_documents_known_item_step():
    assert "Known-Item" in _SEARCH_MD


def test_search_md_documents_fallback_behavior():
    assert "known_works_queries" in _SEARCH_MD
    assert "#881" in _SEARCH_MD


def test_search_md_documents_null_hit_reporting():
    assert "Nulltreffer" in _SEARCH_MD or "Null-Treffer" in _SEARCH_MD
