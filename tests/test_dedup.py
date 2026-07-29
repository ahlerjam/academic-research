"""Tests for dedup.py — paper deduplication."""

from dedup import deduplicate, merge_group
from text_utils import normalize_doi


def test_normalize_doi_basic():
    assert normalize_doi("10.1109/TEST.2023") == "10.1109/test.2023"


def test_normalize_doi_with_url():
    assert normalize_doi("https://doi.org/10.1109/TEST") == "10.1109/test"


def test_normalize_doi_none():
    assert normalize_doi(None) is None


def test_normalize_doi_empty():
    assert normalize_doi("") is None


def test_normalize_doi_dx_doi_org():
    assert normalize_doi("https://dx.doi.org/10.1109/TEST") == "10.1109/test"


def test_normalize_doi_dx_doi_org_http():
    assert normalize_doi("http://dx.doi.org/10.1109/TEST") == "10.1109/test"


def test_normalize_doi_bare_domain_no_protocol():
    assert normalize_doi("doi.org/10.1109/TEST") == "10.1109/test"


def test_normalize_doi_colon_prefix():
    assert normalize_doi("doi:10.1109/TEST") == "10.1109/test"


def test_normalize_doi_urn_prefix():
    assert normalize_doi("urn:doi:10.1109/TEST") == "10.1109/test"


def test_normalize_doi_trailing_period():
    assert normalize_doi("10.1109/TEST.") == "10.1109/test"


def test_normalize_doi_trailing_comma():
    assert normalize_doi("10.1109/TEST,") == "10.1109/test"


def test_normalize_doi_trailing_semicolon():
    assert normalize_doi("10.1109/TEST;") == "10.1109/test"


def test_normalize_doi_mixed_case_and_whitespace():
    assert normalize_doi("  Https://DOI.org/10.1109/Test  ") == "10.1109/test"


def test_dedup_by_doi():
    papers = [
        {"doi": "10.1109/TEST", "title": "Paper A", "authors": ["Alice"], "citations": 5},
        {
            "doi": "https://doi.org/10.1109/test",
            "title": "Paper A (copy)",
            "authors": ["Bob"],
            "citations": 10,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert result[0]["citations"] == 10
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_by_title_similarity():
    papers = [
        {
            "doi": None,
            "title": "DevOps Governance in Large Organizations",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": None,
            "title": "DevOps Governance in Large Organisations",
            "authors": ["Alice"],
            "citations": 5,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1


def test_dedup_different_papers():
    papers = [
        {"doi": "10.1109/A", "title": "Paper A", "authors": ["Alice"]},
        {"doi": "10.1109/B", "title": "Paper B", "authors": ["Bob"]},
    ]
    result = deduplicate(papers)
    assert len(result) == 2


def test_merge_group_oa_urls():
    group = [
        {"title": "Paper", "authors": [], "oa_url": None, "open_access_pdf": None, "citations": 5},
        {
            "title": "Paper",
            "authors": [],
            "oa_url": "https://test.pdf",
            "open_access_pdf": None,
            "citations": 3,
        },
    ]
    merged = merge_group(group)
    assert merged["oa_url"] == "https://test.pdf"
    assert merged["citations"] == 5


def test_dedup_preserves_source_modules():
    papers = [
        {"doi": "10.1109/X", "title": "Same Paper", "source_module": "crossref", "citations": 5},
        {"doi": "10.1109/X", "title": "Same Paper", "source_module": "openalex", "citations": 10},
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "source_modules" in result[0]
    assert set(result[0]["source_modules"]) == {"crossref", "openalex"}


def test_dedup_merges_no_doi_hit_into_doi_group():
    """Ein Treffer ohne DOI wird per Titel-Similarity in die passende DOI-Gruppe gemergt (AC2)."""
    papers = [
        {
            "doi": "10.1109/TEST",
            "title": "DevOps Governance in Large Organizations",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": None,
            "title": "DevOps Governance in Large Organizations",
            "authors": ["Bob"],
            "abstract": "An abstract only this source provided.",
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert result[0]["doi"] == "10.1109/test"
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_merges_no_doi_hit_matching_non_first_group_member():
    """Ein Treffer ohne DOI wird auch dann gemergt, wenn sein Titel nur zum
    ZWEITEN Mitglied der DOI-Gruppe passt, nicht zum ersten (AC2). DOI-Gruppen
    werden per exakter DOI-Gleichheit gebildet, nicht per Titel-Ähnlichkeit —
    Mitglieder derselben Gruppe können also unterschiedliche Titelschreibweisen
    tragen."""
    papers = [
        {
            "doi": "10.1109/TEST",
            "title": "DevOps Governance in Large Firms",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": "https://doi.org/10.1109/test",
            "title": "DevOps Governance in Large Organizations",
            "authors": ["Carol"],
            "citations": 3,
        },
        {
            "doi": None,
            "title": "DevOps Governance in Large Organizations",
            "authors": ["Bob"],
            "abstract": "An abstract only this source provided.",
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Carol" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_merge_group_doi_fallback_when_best_record_has_no_doi():
    """Beim Merge bleibt die DOI erhalten, auch wenn der 'vollständigste' Datensatz selbst
    keine DOI trägt (AC3)."""
    group = [
        {"doi": "10.1109/test", "title": "Paper", "authors": ["Alice"], "citations": 1},
        {
            "doi": None,
            "title": "Paper",
            "authors": ["Alice", "Bob"],
            "abstract": "Long abstract",
            "venue": "Some Venue",
            "citations": 1,
        },
    ]
    merged = merge_group(group)
    assert merged["doi"] == "10.1109/test"
    assert merged["abstract"] == "Long abstract"
    assert merged["venue"] == "Some Venue"


def test_dedup_real_world_multi_source_duplicate():
    """Dieselbe Arbeit, geliefert von vier Quellen-Schemata (Crossref, OpenAlex,
    Semantic-Scholar-artig mit dx.doi.org-Präfix, sowie ein BASE-Treffer ganz ohne
    DOI aber mit den meisten Feldern), erscheint genau einmal. Der vollständigste
    Datensatz (BASE) gewinnt die Merge-Auswahl, verliert dabei aber nicht die DOI,
    die er selbst nie hatte (AC1 + AC2 + AC3 + AC4)."""
    papers = [
        # Crossref-Style: nackte DOI
        {
            "doi": "10.1145/3510003.3510621",
            "title": "Continuous Delivery in Practice",
            "authors": ["A. Author"],
            "source_module": "crossref",
            "citations": 12,
        },
        # OpenAlex-Style: https://doi.org/-Präfix, höchste Zitationszahl
        {
            "doi": "https://doi.org/10.1145/3510003.3510621",
            "title": "Continuous Delivery in Practice",
            "authors": ["B. Author"],
            "source_module": "openalex",
            "citations": 20,
        },
        # dx.doi.org-Style mit abschließendem Punkt
        {
            "doi": "http://dx.doi.org/10.1145/3510003.3510621.",
            "title": "Continuous Delivery in Practice",
            "authors": ["C. Author"],
            "source_module": "semantic_scholar",
            "citations": 8,
        },
        # BASE-Style: kein DOI geliefert, aber die meisten Metadatenfelder
        {
            "doi": None,
            "title": "Continuous Delivery in Practice",
            "authors": ["D. Author"],
            "source_module": "base",
            "abstract": "Abstract only BASE provided.",
            "venue": "ICSE",
            "url": "https://example.org/paper",
            "citations": 1,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    merged = result[0]
    # Vollständigster Datensatz (BASE, 7 Felder) gewinnt die Merge-Auswahl ...
    assert merged["abstract"] == "Abstract only BASE provided."
    assert merged["venue"] == "ICSE"
    assert merged["url"] == "https://example.org/paper"
    # ... behält aber via Fallback die DOI aus der Gruppe, obwohl er selbst keine trug.
    assert merged["doi"] == "10.1145/3510003.3510621"
    # Max-Zitationszahl und Autor:innen werden weiterhin über die ganze Gruppe konsolidiert.
    assert merged["citations"] == 20
    assert {"A. Author", "B. Author", "C. Author", "D. Author"} <= set(merged["authors"])
    assert set(merged["source_modules"]) == {"crossref", "openalex", "semantic_scholar", "base"}
