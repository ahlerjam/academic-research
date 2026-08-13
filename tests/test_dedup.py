"""Tests for dedup.py — paper deduplication."""

import itertools
import random
import time
from difflib import SequenceMatcher
from typing import Any

from dedup import _canonical_sort_key, _length_bound_ok, deduplicate, merge_group
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


def test_merge_group_is_retracted_true_wins_even_from_non_best_record():
    """Ein Retraction-Hinweis aus einer Nebenquelle darf beim Merge mit einem
    vollstaendigeren, aber nicht-retracted Datensatz nicht verschwinden (#618 AC2)."""
    group = [
        {
            "title": "Paper",
            "authors": ["Alice"],
            "abstract": "Long abstract",
            "venue": "Some Venue",
            "citations": 10,
            "is_retracted": False,
        },
        {
            "title": "Paper",
            "authors": [],
            "citations": 1,
            "is_retracted": True,
        },
    ]
    merged = merge_group(group)
    assert merged["is_retracted"] is True


def test_merge_group_is_retracted_stays_none_when_unknown_everywhere():
    """Fehlt das Feld ueberall, bleibt das Ergebnis None (unbekannt), nicht False (#618 AC4)."""
    group = [
        {"title": "Paper", "authors": ["Alice"], "citations": 5, "is_retracted": None},
        {"title": "Paper", "authors": [], "citations": 1, "is_retracted": None},
    ]
    merged = merge_group(group)
    assert merged["is_retracted"] is None


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


def test_dedup_order_independent_with_transitive_title_chain():
    """Drei Papers A~B, B~C, aber A!~C (unter der Schwelle) ergeben in jeder
    Permutation der Eingabeliste dieselbe Gruppierung (AC1)."""
    paper_a = {
        "doi": None,
        "title": "Refactoring Legacy Monolithic Codebases into Modular Services",
        "authors": ["Alice"],
        "citations": 1,
    }
    paper_b = {
        "doi": None,
        "title": "Refactoring Legacy Monolithic Codebases into Modular Microservices",
        "authors": ["Bob"],
        "citations": 2,
    }
    paper_c = {
        "doi": None,
        "title": "Refactoring Legacy Monolithic Codebases into Distributed Microservices",
        "authors": ["Carol"],
        "citations": 3,
    }
    papers = [paper_a, paper_b, paper_c]

    results = [deduplicate(list(perm)) for perm in itertools.permutations(papers)]

    # A~B und B~C liegen über der Schwelle, A~C darunter — trotzdem landen
    # A, B und C dank der transitiven Kette (Union-Find) in EINER Gruppe.
    for result in results:
        assert len(result) == 1
        assert {"Alice", "Bob", "Carol"} <= set(result[0]["authors"])

    # Alle Permutationen liefern identische Autor:innen-Mengen im Ergebnis.
    author_sets = [frozenset(r[0]["authors"]) for r in results]
    assert len(set(author_sets)) == 1


def test_dedup_merges_by_arxiv_id_despite_different_doi_and_title():
    """Gleiche arXiv-ID trotz abweichender DOI und abweichendem Titel wird
    gemergt (AC2)."""
    papers = [
        {
            "doi": "10.1109/completely-different-doi",
            "arxiv_id": "2301.12345",
            "title": "First Title Variant",
            "authors": ["Alice"],
            "citations": 1,
        },
        {
            "doi": "10.9999/another-doi",
            "arxiv_id": "2301.12345",
            "title": "Second Totally Unrelated Title",
            "authors": ["Bob"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_merges_by_pmid_despite_different_doi_and_title():
    """Gleiche PMID trotz abweichender DOI und abweichendem Titel wird
    gemergt (AC2)."""
    papers = [
        {
            "doi": "10.1109/completely-different-doi",
            "pmid": "12345678",
            "title": "First Title Variant",
            "authors": ["Alice"],
            "citations": 1,
        },
        {
            "doi": "10.9999/another-doi",
            "pmid": "12345678",
            "title": "Second Totally Unrelated Title",
            "authors": ["Bob"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_merges_by_openalex_id_despite_different_doi_and_title():
    """Gleiche OpenAlex-ID trotz abweichender DOI und abweichendem Titel wird
    gemergt (AC2)."""
    papers = [
        {
            "doi": "10.1109/completely-different-doi",
            "openalex_id": "W123456789",
            "title": "First Title Variant",
            "authors": ["Alice"],
            "citations": 1,
        },
        {
            "doi": "10.9999/another-doi",
            "openalex_id": "w123456789",
            "title": "Second Totally Unrelated Title",
            "authors": ["Bob"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_id_match_wins_even_below_title_threshold():
    """Ein ID-Treffer mergt zwei Papers, deren Titel-Similarity klar unter der
    Schwelle liegt — die ID-Ebenen greifen vor dem Fuzzy-Titelvergleich (AC3)."""
    papers = [
        {
            "doi": None,
            "arxiv_id": "1999.00001",
            "title": "Alpha",
            "authors": ["Alice"],
            "citations": 1,
        },
        {
            "doi": None,
            "arxiv_id": "1999.00001",
            "title": "Zzzzzzzzzzzzzzzzzzzzzzzzzzzz",
            "authors": ["Bob"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_no_ids_falls_back_to_title_similarity_only():
    """Fehlen alle vier ID-Typen, bleibt es beim bisherigen Verhalten über den
    Fuzzy-Titelvergleich (AC4, Regressionsschutz für die bestehende
    Titel-Similarity-Logik)."""
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
            "authors": ["Bob"],
            "citations": 3,
        },
        {
            "doi": None,
            "title": "A Completely Unrelated Paper About Gardening",
            "authors": ["Carol"],
            "citations": 1,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 2
    titles = {p["title"] for p in result}
    assert "A Completely Unrelated Paper About Gardening" in titles


def test_dedup_representative_deterministic_regardless_of_input_order():
    """Bei einem Tie in (_non_none_count, citations) ist der überlebende
    Repräsentant deterministisch — nicht von der Eingabereihenfolge abhängig
    (AC5)."""
    paper_x = {
        "doi": "10.1109/tie-test",
        "title": "Tie Test Paper",
        "authors": ["Alice"],
        "abstract": "Abstract from X",
        "citations": 5,
    }
    paper_y = {
        "doi": "10.1109/tie-test",
        "title": "Tie Test Paper",
        "authors": ["Bob"],
        "abstract": "Abstract from Y",
        "citations": 5,
    }

    result_forward = deduplicate([paper_x, paper_y])
    result_reversed = deduplicate([paper_y, paper_x])

    assert len(result_forward) == 1
    assert len(result_reversed) == 1
    assert result_forward[0]["abstract"] == result_reversed[0]["abstract"]


def test_dedup_merges_openalex_url_without_doi_into_doi_record():
    """Ein OpenAlex-Treffer mit URL aber ohne DOI wird per Titel-Similarity in
    eine DOI-Gruppe gemergt — die Cross-Typ-Regel blockiert nur bei
    ID-Konflikten desselben Typs, nicht bei unterschiedlichen ID-Typen (#707 P1)."""
    papers = [
        {
            "doi": "10.1234/test.machine.learning",
            "title": "Machine Learning for Climate Modeling",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": None,
            "url": "https://openalex.org/W2741809807",
            "title": "Machine Learning for Climate Modelling",
            "authors": ["Bob"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert result[0]["doi"] == "10.1234/test.machine.learning"
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_merges_pubmed_url_without_doi_into_doi_record():
    """Analog für PubMed: ein PMID aus URL ohne DOI wird per Titel-Similarity in
    eine DOI-Gruppe gemergt (#707 P1)."""
    papers = [
        {
            "doi": "10.1234/pubmed.test",
            "title": "Clinical Trial on Medical Device",
            "authors": ["Alice"],
            "citations": 3,
        },
        {
            "doi": None,
            "url": "https://pubmed.ncbi.nlm.nih.gov/12345678",
            "title": "Clinical Trial on Medical Device",
            "authors": ["Bob"],
            "citations": 1,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert result[0]["doi"] == "10.1234/pubmed.test"
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_cluster_level_conflict_prevents_transitive_merge():
    """Ein ID-loser Brücken-Record C darf nicht zwei Records A und B mit
    widersprechenden DOIs transitiv zusammenführen (#707 P1). Paar (A,B)
    ist blockiert, aber (A,C) und (B,C) würden einzeln grün sein — die
    Cluster-Level-Prüfung must dies verhindern."""
    papers = [
        {
            "doi": "10.1234/original",
            "title": "Deep Learning for Medical Image Segmentation",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": "10.5555/erratum",
            "title": "Deep Learning for Medical Image Segmentation.",
            "authors": ["Bob"],
            "citations": 1,
        },
        {
            "doi": None,
            "title": "Deep Learning for Medical Image Segmentation",
            "authors": ["Carol"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    # A und B sollten NICHT über C transitiv mergen (2 Ergebnisse)
    assert len(result) == 2
    dois = {r.get("doi") for r in result}
    # Beide DOIs sollen noch da sein, nicht gemergt
    assert "10.1234/original" in dois
    assert "10.5555/erratum" in dois


def test_dedup_merges_openalex_url_form_direct_key_matches_bare_id():
    """Wenn openalex_id-Direkt-Key die vollständige URL trägt, wird sie auf
    die Bare-ID normalisiert und mergt mit URL-basierten Records (#707 P2)."""
    papers = [
        {
            "doi": None,
            "openalex_id": "https://openalex.org/W2741809807",
            "title": "Test Paper",
            "authors": ["Alice"],
            "citations": 2,
        },
        {
            "doi": None,
            "url": "https://openalex.org/W2741809807",
            "title": "Test Paper",
            "authors": ["Bob"],
            "citations": 1,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_merges_pmid_url_form_direct_key_matches_bare_id():
    """Wenn pmid-Direkt-Key die vollständige pubmed-URL trägt, wird sie auf
    die Bare-ID normalisiert und mergt mit URL-basierten Records (#707 P2)."""
    papers = [
        {
            "doi": None,
            "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345678",
            "title": "Clinical Test Paper",
            "authors": ["Alice"],
            "citations": 2,
        },
        {
            "doi": None,
            "url": "https://pubmed.ncbi.nlm.nih.gov/12345678",
            "title": "Clinical Test Paper",
            "authors": ["Bob"],
            "citations": 1,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_merges_two_doi_less_openalex_records_by_title():
    """Zwei DOI-lose OpenAlex-Treffer (unterschiedliche openalex_id, wie sie
    scripts/search.py::search_openalex() fuer JEDEN Treffer liefert) mergen
    weiterhin per Titel-Similarity — eine OpenAlex-Work-ID ist eine
    Record-ID, kein Beleg fuer Werk-Verschiedenheit wie eine DOI-Differenz
    (#707 P1 Regression-Fix). Vor dem Fix blockierte die disjunkte
    openalex_id-Menge den Titel-Merge fuer genau den Preprint/Journal-Fall,
    den #707 beheben soll."""
    papers = [
        {
            "doi": None,
            "url": "https://openalex.org/W111",
            "title": "Machine Learning for Climate Modeling",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": None,
            "url": "https://openalex.org/W222",
            "title": "Machine Learning for Climate Modelling",
            "authors": ["Bob"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_merges_two_pmid_less_doi_but_different_pmid_by_title():
    """Analog fuer PMID: zwei DOI-lose PubMed-Treffer mit unterschiedlicher
    PMID mergen weiterhin per Titel-Similarity, da PMID (aus der URL
    abgeleitet) kein kanonischer Beleg fuer Werk-Verschiedenheit ist (#707
    P1)."""
    papers = [
        {
            "doi": None,
            "url": "https://pubmed.ncbi.nlm.nih.gov/11111111",
            "title": "Clinical Trial on Medical Device",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": None,
            "url": "https://pubmed.ncbi.nlm.nih.gov/22222222",
            "title": "Clinical Trial on Medical Device",
            "authors": ["Bob"],
            "citations": 2,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 1
    assert "Alice" in result[0]["authors"]
    assert "Bob" in result[0]["authors"]


def test_dedup_doi_conflict_still_blocks_merge_despite_distinct_openalex_ids():
    """Gegenprobe: eine DOI-Differenz bleibt ein echter Konflikt und blockiert
    den Titel-Merge weiterhin — nur DOI/arXiv-ID sind kanonisch genug, um
    einen Merge zu verhindern; die abgeleitete OpenAlex-ID beider Records
    (unterschiedliche W-IDs, wie es zwei tatsaechlich verschiedene Werke
    haetten) hebt die Sperre nicht auf (#707 P1, Abgrenzung der
    Fix-Reichweite)."""
    papers = [
        {
            "doi": "10.1234/original",
            "url": "https://openalex.org/W111",
            "title": "Deep Learning for Medical Image Segmentation",
            "authors": ["Alice"],
            "citations": 5,
        },
        {
            "doi": "10.5555/erratum",
            "url": "https://openalex.org/W222",
            "title": "Deep Learning for Medical Image Segmentation.",
            "authors": ["Bob"],
            "citations": 1,
        },
    ]
    result = deduplicate(papers)
    assert len(result) == 2
    dois = {r.get("doi") for r in result}
    assert "10.1234/original" in dois
    assert "10.5555/erratum" in dois


def test_dedup_cluster_conflict_permutation_invariant_with_bridge_record():
    """AC1 (#707): der Bruecken-Fall aus
    test_dedup_cluster_level_conflict_prevents_transitive_merge bleibt in
    ALLEN 6 Permutationen der Eingabe bei genau 2 Gruppen mit demselben
    DOI-Paar — die Cluster-Konfliktpruefung darf nicht von der
    Paar-Verarbeitungsreihenfolge abhaengen (#707 P2 Nachsteuerung)."""
    a = {
        "doi": "10.1234/original",
        "title": "Deep Learning for Medical Image Segmentation",
        "authors": ["Alice"],
        "citations": 5,
    }
    b = {
        "doi": "10.5555/erratum",
        "title": "Deep Learning for Medical Image Segmentation.",
        "authors": ["Bob"],
        "citations": 1,
    }
    c = {
        "doi": None,
        "title": "Deep Learning for Medical Image Segmentation",
        "authors": ["Carol"],
        "citations": 2,
    }
    for perm in itertools.permutations([a, b, c]):
        result = deduplicate(list(perm))
        assert len(result) == 2, f"permutation {[p['authors'][0] for p in perm]}"
        dois = {r.get("doi") for r in result}
        assert dois == {"10.1234/original", "10.5555/erratum"}


def test_dedup_bridge_record_group_membership_permutation_invariant():
    """AC1 (#707): Nicht nur Gruppenzahl und DOI-Menge, sondern auch die
    tatsaechliche Gruppen-MITGLIEDSCHAFT des ID-losen Bruecken-Records
    (Carol) muss ueber alle 6 Permutationen identisch sein. Der bisherige
    Permutationstest (test_dedup_cluster_conflict_permutation_invariant_with_bridge_record)
    prueft nur len(result) und die DOI-Menge — das bleibt trivial stabil,
    auch wenn Carol mal bei 'original', mal bei 'erratum' landet, weil beide
    Gruppen so oder so existieren. Dieser Test faengt genau diese
    Verletzung."""
    a = {
        "doi": "10.1234/original",
        "title": "Deep Learning for Medical Image Segmentation",
        "authors": ["Alice"],
        "citations": 5,
    }
    b = {
        "doi": "10.5555/erratum",
        "title": "Deep Learning for Medical Image Segmentation.",
        "authors": ["Bob"],
        "citations": 1,
    }
    c = {
        "doi": None,
        "title": "Deep Learning for Medical Image Segmentation",
        "authors": ["Carol"],
        "citations": 2,
    }
    memberships = []
    for perm in itertools.permutations([a, b, c]):
        result = deduplicate(list(perm))
        by_doi = {r.get("doi"): frozenset(r["authors"]) for r in result}
        memberships.append(by_doi)

    first = memberships[0]
    for perm, membership in zip(
        itertools.permutations(["Alice", "Bob", "Carol"]), memberships, strict=True
    ):
        assert membership == first, (
            f"permutation {perm} yields different group membership: {membership} != {first}"
        )


# ---------------------------------------------------------------------------
# #890 — Blocking vor der Titel-Paarbildung
# ---------------------------------------------------------------------------


def test_length_bound_ok_matches_ratio_upper_bound():
    """`_length_bound_ok` ist ein notwendiges (nicht hinreichendes) Kriterium:
    kein Paar, dessen tatsaechliches `ratio()` den Threshold erreicht, darf
    vom Bound ausgeschlossen werden (mathematischer Beweis aus dem Plan-
    Kommentar: ratio() <= 2*min(la,lb)/(la+lb))."""
    threshold = 0.85
    # Gleich lang: 2*min/max = 1.0 >= threshold -> immer erlaubt.
    assert _length_bound_ok(10, 10, threshold) is True
    # Extrem verschieden lang: 2*10/210 << threshold -> ausgeschlossen.
    assert _length_bound_ok(10, 200, threshold) is False
    # Randomisierter Brute-Force-Vergleich: fuer 500 zufaellige Laengenpaare
    # darf _length_bound_ok niemals False liefern, wenn ein reales
    # Titelpaar dieser Laengen den Threshold erreichen KOENNTE (oberste
    # erreichbare ratio() bei diesen Laengen ist genau 2*min/(la+lb)).
    rng = random.Random(42)
    for _ in range(500):
        la = rng.randint(1, 200)
        lb = rng.randint(1, 200)
        max_possible_ratio = 2 * min(la, lb) / (la + lb)
        bound_says_possible = _length_bound_ok(la, lb, threshold)
        if max_possible_ratio >= threshold:
            assert bound_says_possible is True, (la, lb, max_possible_ratio)
        else:
            assert bound_says_possible is False, (la, lb, max_possible_ratio)


def test_length_bound_ok_rejects_zero_length():
    assert _length_bound_ok(0, 5, 0.85) is False
    assert _length_bound_ok(0, 0, 0.85) is False


_DEVOPS_VOCAB = [
    "devops",
    "governance",
    "cloud",
    "security",
    "framework",
    "large",
    "organizations",
    "study",
    "systematic",
    "review",
    "empirical",
    "analysis",
    "continuous",
    "delivery",
    "pipeline",
    "risk",
    "compliance",
    "architecture",
    "microservices",
    "agile",
]


def _brute_force_title_pairs(
    papers: list[dict[str, Any]], threshold: float
) -> set[tuple[int, int]]:
    """Referenzimplementierung: alle Paare per unbeschraenktem O(n^2)-Scan
    und vollem `SequenceMatcher.ratio()` — das Verhalten vor #890 (siehe
    `d141b09:scripts/dedup.py`, verschachtelte Doppelschleife ueber
    `canonical_order`).

    WICHTIG (Bugfix nach False-Positive-Fund bei der #890-Fix-Runde):
    `SequenceMatcher(a, b).ratio() != SequenceMatcher(b, a).ratio()` im
    Allgemeinen (empirisch verifiziert, keine symmetrische Kennzahl trotz
    des Namens). `deduplicate()` weist deshalb bewusst `seq1`/`seq2` nach
    `canonical_order`-POSITION zu (niedrigere Position = `seq1`), NICHT
    nach roher Listen-Reihenfolge — das war schon vor #890 so (#707) und
    ist die Grundlage der Bridge-Record-Determinismus-Garantie. Eine
    Referenz, die stattdessen rohe Listen-Reihenfolge fuer die a/b-Rollen
    verwendet, ist bei manchen Titelpaaren nahe der Schwelle eine ANDERE
    (falsche) Rechnung als das, was `deduplicate()` selbst berechnet, und
    erzeugt dadurch Schein-Abweichungen, die keine echten Blocking-Fehler
    sind (verifiziert: die alte UND die neue Implementierung liefern fuer
    einen so gefundenen Fall IDENTISCHE Gruppen — nur die alte, rohe-Index-
    basierte Referenz in dieser Testdatei war falsch). Diese Funktion
    repliziert deshalb exakt dieselbe canonical-order-basierte Rollenwahl
    wie `deduplicate()` (`_canonical_sort_key` + `normalize_doi`), um eine
    tatsaechlich faire Referenz zu sein."""
    working: list[dict[str, Any]] = []
    for paper in papers:
        paper_copy = dict(paper)
        paper_copy["doi"] = normalize_doi(paper.get("doi"))
        working.append(paper_copy)
    canonical_order = sorted(range(len(working)), key=lambda idx: _canonical_sort_key(working[idx]))

    titles = [(paper.get("title") or "").strip() for paper in working]
    pairs = set()
    for a in range(len(canonical_order)):
        i = canonical_order[a]
        if not titles[i]:
            continue
        for b in range(a + 1, len(canonical_order)):
            j = canonical_order[b]
            if not titles[j]:
                continue
            ratio = SequenceMatcher(None, titles[i].lower(), titles[j].lower()).ratio()
            if ratio >= threshold:
                pairs.add((i, j))
    return pairs


def _generate_near_duplicate_titles(
    count: int, vocab: list[str], seed: int, min_words: int = 2, max_words: int = 12
) -> list[str]:
    """Synthetische Titelmenge mit ~30% Near-Duplicate-Clustern (ein Wort
    ersetzt) — dasselbe Muster wie die reale 12.08.2026-Messung, aber ohne
    reale Treffermenge im Repo (#890, es existiert keine solche Fixture;
    siehe PR-Beschreibung/Plan-Kommentar #890)."""
    rng = random.Random(seed)

    def random_title(word_count: int) -> str:
        return " ".join(rng.choice(vocab) for _ in range(word_count)).title()

    titles: list[str] = []
    while len(titles) < count:
        base = random_title(rng.randint(min_words, max_words))
        titles.append(base)
        if rng.random() < 0.3 and len(titles) < count:
            words = base.split()
            if words:
                words[rng.randrange(len(words))] = rng.choice(vocab).title()
                titles.append(" ".join(words))
    return titles[:count]


def _assert_blocking_matches_brute_force(titles: list[str], threshold: float = 0.85) -> None:
    """AC3-Aequivalenz-Kern: die geblockte `deduplicate()`-Fassung muss
    dieselben Gruppen liefern wie eine reine Brute-Force-Referenz ueber
    alle Paare, unabhaengig von der internen Gruppen-Reihenfolge."""
    papers = [
        {"doi": None, "title": t, "authors": [f"tracer-{idx}"], "citations": 0}
        for idx, t in enumerate(titles)
    ]
    brute_pairs = _brute_force_title_pairs(papers, threshold)

    # Union-Find ueber die Brute-Force-Paare als Referenzgruppierung
    # (ignoriert die ID-Konfliktregel bewusst, da hier keine IDs vorkommen).
    parent = list(range(len(titles)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, j in brute_pairs:
        union(i, j)

    expected_groups: dict[int, set[int]] = {}
    for idx in range(len(titles)):
        expected_groups.setdefault(find(idx), set()).add(idx)
    # Jeder Titel bekommt einen eindeutigen "Autor" als Tracer, damit sich
    # die Gruppenzugehoerigkeit nach dem Merge ueber die konsolidierte
    # Autorenliste rekonstruieren laesst (merge_group() verliert die
    # Einzeltitel, nicht aber die Autoren).
    expected_id_groups = {frozenset(group) for group in expected_groups.values()}

    result = deduplicate(papers, threshold=threshold)

    result_id_groups = set()
    for paper in result:
        ids = {int(a.removeprefix("tracer-")) for a in paper["authors"]}
        result_id_groups.add(frozenset(ids))

    assert result_id_groups == expected_id_groups, (
        f"Gruppierung weicht ab: geblockt={sorted(map(sorted, result_id_groups))}, "
        f"brute-force={sorted(map(sorted, expected_id_groups))}"
    )


def test_dedup_blocking_loses_no_merge_vs_brute_force():
    """AC3-Aequivalenztest (Basisgroesse): 80 synthetische Titel mit
    gestreuten Laengen und Near-Duplicate-Clustern."""
    titles = _generate_near_duplicate_titles(80, _DEVOPS_VOCAB, seed=7)
    _assert_blocking_matches_brute_force(titles)


def test_dedup_blocking_loses_no_merge_vs_brute_force_multi_seed():
    """AC3-Aequivalenztest, verschaerft: Es existiert keine reale
    12.08.2026-Treffermenge im Repo (weder unter tests/fixtures/ noch unter
    docs/evals/ — geprueft, siehe PR-Diskussion zu #890), daher ist eine
    Brute-Force-Aequivalenzpruefung auf synthetischen Daten der bestmoegliche
    ehrliche Ersatz. Um das Risiko zu senken, dass ein einzelner 80-Titel-
    Lauf einen Blocking-Fehler verdeckt, laufen hier drei unabhaengige Seeds
    bei 300 Titeln (mehr Near-Duplicate-Cluster, breitere Laengenstreuung)
    gegen dieselbe Brute-Force-Referenz."""
    for seed in (11, 23, 42):
        titles = _generate_near_duplicate_titles(300, _DEVOPS_VOCAB, seed=seed)
        _assert_blocking_matches_brute_force(titles)


def test_dedup_blocking_performance_smoke():
    """Regressionswaechter: 500 synthetische Titel muessen deutlich unter
    30s dedupliziert werden (AC1, grosszuegige CI-Schranke)."""
    rng = random.Random(99)
    vocab = [f"word{i}" for i in range(60)]

    def random_title() -> str:
        length = rng.randint(3, 15)
        return " ".join(rng.choice(vocab) for _ in range(length)).title()

    titles = [random_title() for _ in range(500)]
    papers = [{"doi": None, "title": t, "authors": [], "citations": 0} for t in titles]

    start = time.monotonic()
    deduplicate(papers)
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, f"500 Titel dauerten {elapsed:.1f}s (Ziel < 10s)"


def test_dedup_blocking_performance_2000_titles_ac1():
    """AC1-Regressionswaechter bei Zielgroesse: 2000 Titel mit demselben
    Vokabular/Near-Duplicate-Muster wie die AC3-Aequivalenztests muessen
    deutlich unter 30s dedupliziert werden. Grosszuegige CI-Schranke
    (10s statt der gemessenen ~4s), damit die Messung auf langsamerer
    CI-Hardware nicht flakig wird."""
    titles = _generate_near_duplicate_titles(2000, _DEVOPS_VOCAB, seed=1)
    papers = [{"doi": None, "title": t, "authors": [], "citations": 0} for t in titles]

    start = time.monotonic()
    deduplicate(papers)
    elapsed = time.monotonic() - start

    assert elapsed < 10.0, f"2000 Titel dauerten {elapsed:.1f}s (Ziel < 30s, CI-Schranke 10s)"
