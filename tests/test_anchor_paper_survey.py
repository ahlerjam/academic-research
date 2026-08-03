"""Tests fuer anchor-paper-survey Skill (Issue #394, TDD).

Testet anchor_paper.py:
- arXiv-URL als Eingabe -> genau ein Paper wird ueber vault_add_paper() im
  Vault angelegt, verifizierbar via academic_vault.server.get_paper() (AC1).
- Lokaler PDF-Pfad als Eingabe -> Titel/Autoren werden heuristisch
  extrahiert und eine Folge-Suche (scripts/search.py::run_search) wird mit
  dem extrahierten Titel ausgeloest; mind. 1 Treffer bei Netzzugriff, sonst
  sauberer Fehlertext ohne Crash (AC2).
- Ungueltiger Pfad/ungueltige URL -> ValueError mit verstaendlicher Meldung,
  KEINE Vault-Mutation (AC3).
- Alle Faelle sind hier gemeinsam gruen (AC4).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "anchor-paper-survey"
SKILL_MD = SKILL_DIR / "SKILL.md"
ANCHOR_PAPER_SCRIPT = SKILL_DIR / "scripts" / "anchor_paper.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "anchor_paper_survey"

if str(SKILL_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))

import anchor_paper as aps  # noqa: E402  (Pfad-Setup muss vor dem Import stehen)
from academic_vault.server import get_paper as vault_get_paper  # noqa: E402


def _read(fixture_name: str) -> str:
    return (FIXTURES_DIR / fixture_name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# arXiv-ID-Parsing
# ---------------------------------------------------------------------------


class TestParseArxivId:
    def test_parses_abs_url(self):
        assert aps.parse_arxiv_id("https://arxiv.org/abs/2005.14165") == "2005.14165"

    def test_parses_pdf_url_with_version(self):
        assert aps.parse_arxiv_id("http://arxiv.org/pdf/1706.03762v5") == "1706.03762"

    def test_parses_bare_id(self):
        assert aps.parse_arxiv_id("2005.14165") == "2005.14165"

    def test_parses_bare_id_with_version(self):
        assert aps.parse_arxiv_id("2005.14165v2") == "2005.14165"

    def test_non_arxiv_string_returns_none(self):
        assert aps.parse_arxiv_id("/tmp/does-not-matter.pdf") is None

    def test_non_arxiv_url_returns_none(self):
        assert aps.parse_arxiv_id("https://example.com/paper") is None

    def test_empty_string_returns_none(self):
        assert aps.parse_arxiv_id("") is None


# ---------------------------------------------------------------------------
# Input-Erkennung (arXiv vs. PDF-Pfad vs. ungueltig)
# ---------------------------------------------------------------------------


class TestDetectInput:
    def test_detects_arxiv_url(self):
        kind, value = aps.detect_input("https://arxiv.org/abs/2005.14165")
        assert kind == "arxiv"
        assert value == "2005.14165"

    def test_detects_existing_pdf_path(self, sample_pdf):
        kind, value = aps.detect_input(str(sample_pdf))
        assert kind == "pdf"
        assert value == str(sample_pdf)

    def test_nonexistent_path_raises_value_error(self):
        with pytest.raises(ValueError):
            aps.detect_input("/no/such/path/does-not-exist.pdf")

    def test_invalid_url_raises_value_error(self):
        with pytest.raises(ValueError):
            aps.detect_input("https://example.com/not-arxiv-not-a-file")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            aps.detect_input("")


# ---------------------------------------------------------------------------
# arXiv-Resolution (eigenstaendig implementiert, kein Cross-Skill-Import)
# ---------------------------------------------------------------------------


class TestResolveArxivId:
    def test_resolves_title_author_doi_from_atom_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response.xml")

        with patch("requests.get", return_value=mock_resp):
            csl_json = aps.resolve_arxiv_id("2005.14165")

        assert csl_json is not None
        data = json.loads(csl_json)
        assert data["type"] == "article-journal"
        assert data["title"] == "Language Models are Few-Shot Learners"
        assert data["DOI"] == "10.48550/arXiv.2005.14165"
        assert {"literal": "Tom B. Brown"} in data["author"]

    def test_empty_feed_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response_empty.xml")

        with patch("requests.get", return_value=mock_resp):
            assert aps.resolve_arxiv_id("9999.99999") is None

    def test_http_error_returns_none_no_crash(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("requests.get", return_value=mock_resp):
            assert aps.resolve_arxiv_id("2005.14165") is None

    def test_network_exception_returns_none_no_crash(self):
        with patch("requests.get", side_effect=OSError("timeout")):
            assert aps.resolve_arxiv_id("2005.14165") is None

    def test_error_feed_returns_none_no_fake_paper(self):
        """arXiv beantwortet eine unbekannte/ungueltige ID mit HTTP 200 und
        einem regulaeren Atom-Feed, dessen einziger <entry> auf
        arxiv.org/api/errors zeigt und <title>Error</title> traegt (siehe
        arXiv-API-Manual). Dieser Fehler-Entry darf NIEMALS als gueltiges
        Paper (Titel "Error") durchgereicht werden -- sonst landet ein
        Fake-Paper im Vault (P1-Regression aus PR #440 Review)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response_error.xml")

        with patch("requests.get", return_value=mock_resp):
            assert aps.resolve_arxiv_id("1234.5678") is None


# ---------------------------------------------------------------------------
# Titel/Autoren-Heuristik aus PDF-Volltext
# ---------------------------------------------------------------------------


class TestExtractTitleAndAuthors:
    def test_first_line_is_title_second_line_authors(self):
        text = "Attention Is All You Need\nAshish Vaswani, Noam Shazeer\n\nAbstract...\n"
        title, authors = aps._extract_title_and_authors(text)
        assert title == "Attention Is All You Need"
        assert {"literal": "Ashish Vaswani"} in authors
        assert {"literal": "Noam Shazeer"} in authors

    def test_empty_text_returns_empty_title(self):
        title, authors = aps._extract_title_and_authors("")
        assert title == ""
        assert authors == []

    def test_single_line_text_has_no_authors(self):
        title, authors = aps._extract_title_and_authors("Just A Title\n")
        assert title == "Just A Title"
        assert authors == []


# ---------------------------------------------------------------------------
# AC1: arXiv-URL -> genau ein Paper im Vault, verifizierbar via get_paper()
# ---------------------------------------------------------------------------


class TestAnchorPaperSurveyArxivSuccess:
    def test_arxiv_url_adds_exactly_one_paper_verifiable_via_get_paper(self, temp_vault_db):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response.xml")

        search_hits = [{"title": "A Related Work", "doi": "10.1234/related"}]

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(aps, "vault_add_paper", wraps=aps.vault_add_paper) as mock_add,
            patch.object(aps, "run_citation_search", return_value=(search_hits, [])) as mock_search,
        ):
            result = aps.anchor_paper_survey(
                "https://arxiv.org/abs/2005.14165", db_path=temp_vault_db
            )

        assert result["status"] == "ok"
        assert result["source"] == "arxiv"
        mock_add.assert_called_once()
        # arXiv-Anker nutzt die echte Zitations-/Referenz-Traversierung
        # (run_citation_search), nicht die Titel-Keyword-Suche -- P1 aus
        # PR #440 Review: SKILL.md versprach Zitations-Recherche, geliefert
        # wurde vorher nur run_search(). Siehe auch
        # TestFollowUpSearchQualityFixes weiter unten.
        mock_search.assert_called_once_with("ARXIV:2005.14165", limit=aps.DEFAULT_SEARCH_LIMIT)

        paper = vault_get_paper(temp_vault_db, result["paper_id"])
        assert paper is not None
        csl = json.loads(paper["csl_json"])
        assert csl["title"] == "Language Models are Few-Shot Learners"
        assert paper["provenance"] == "anchor-paper"

        # Ein einzelner Roh-Treffer ohne Kollision mit dem Anker durchlaeuft
        # _filter_and_dedupe() -- dedup.py::deduplicate() normalisiert dabei
        # jeden Treffer auf das gemeinsame Paper-Schema (ergaenzt z.B. leere
        # "authors"/"citations"-Felder), deshalb hier gezielte Feldchecks
        # statt exakter Dict-Gleichheit mit der rohen Eingabe.
        assert result["search"]["count"] == 1
        assert result["search"]["hits"][0]["title"] == "A Related Work"
        assert result["search"]["hits"][0]["doi"] == "10.1234/related"

    def test_arxiv_resolution_failure_adds_no_paper(self, temp_vault_db):
        with (
            patch.object(aps, "resolve_arxiv_id", return_value=None),
            patch.object(aps, "vault_add_paper") as mock_add,
            patch.object(aps, "run_citation_search") as mock_search,
        ):
            result = aps.anchor_paper_survey(
                "https://arxiv.org/abs/2005.14165", db_path=temp_vault_db
            )

        assert result["status"] == "error"
        mock_add.assert_not_called()
        mock_search.assert_not_called()
        assert vault_get_paper(temp_vault_db, "arxiv-2005-14165") is None

    def test_arxiv_error_feed_adds_no_fake_paper(self, temp_vault_db):
        """End-to-End-Gegenstueck zu TestResolveArxivId::test_error_feed_returns_none_no_fake_paper:
        eine reale HTTP-200-Fehlerantwort der arXiv-API darf nicht als
        Anker-Paper mit Titel "Error" im Vault landen (AC1: genau ein Paper
        NUR bei echtem Treffer)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response_error.xml")

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(aps, "vault_add_paper") as mock_add,
            patch.object(aps, "run_citation_search") as mock_search,
        ):
            result = aps.anchor_paper_survey("1234.5678", db_path=temp_vault_db)

        assert result["status"] == "error"
        mock_add.assert_not_called()
        mock_search.assert_not_called()
        assert vault_get_paper(temp_vault_db, "arxiv-1234-5678") is None


# ---------------------------------------------------------------------------
# AC2: PDF-Pfad -> Titel/Autoren "korrekt genug" fuer Folge-Suche
# ---------------------------------------------------------------------------


PDF_SAMPLE_TEXT = "A Great Paper About Testing\nJane Doe, John Smith\n\nAbstract: ...\n"


class TestAnchorPaperSurveyPdfSuccess:
    def test_pdf_path_with_search_hits_adds_paper_and_reports_hits(self, sample_pdf, temp_vault_db):
        search_hits = [
            {"title": "A Related Testing Paper"},
            {"title": "Another Related Work"},
        ]

        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(aps, "run_search", return_value=(search_hits, [])) as mock_search,
        ):
            result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert result["status"] == "ok"
        assert result["source"] == "pdf"
        assert result["title"] == "A Great Paper About Testing"
        assert result["search"]["count"] == 2
        mock_search.assert_called_once()
        query_arg = mock_search.call_args[0][0]
        assert "A Great Paper About Testing" in query_arg

        paper = vault_get_paper(temp_vault_db, result["paper_id"])
        assert paper is not None
        assert paper["provenance"] == "anchor-paper"
        assert paper["pdf_path"] == str(sample_pdf)

    def test_pdf_path_without_network_hits_reports_clean_error_no_crash(
        self, sample_pdf, temp_vault_db
    ):
        """Kein Treffer bei der Folge-Suche (bzw. Suchmodule fehlgeschlagen)
        -> sauberer Fehlertext im Ergebnis, kein Crash, Paper trotzdem
        angelegt (AC2: 'sonst sauberer Fehlertext')."""
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(aps, "run_search", return_value=([], ["arxiv", "crossref"])),
        ):
            result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert result["status"] == "ok"
        assert result["search"]["count"] == 0
        assert result["search"]["failed_modules"] == ["arxiv", "crossref"]
        assert isinstance(result["message"], str) and result["message"].strip()

        # Das Anker-Paper selbst wurde trotzdem angelegt -- eine leere Folge-
        # Suche ist kein Grund, den bereits erfassten Anker zu verwerfen.
        paper = vault_get_paper(temp_vault_db, result["paper_id"])
        assert paper is not None

    def test_pdf_needing_ocr_returns_clean_error_no_vault_mutation(self, sample_pdf, temp_vault_db):
        with (
            patch.object(aps, "detect_needs_ocr", return_value=True),
            patch.object(aps, "vault_add_paper") as mock_add,
            patch.object(aps, "run_search") as mock_search,
        ):
            result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert result["status"] == "error"
        assert isinstance(result["message"], str) and result["message"].strip()
        mock_add.assert_not_called()
        mock_search.assert_not_called()

    def test_pdf_paper_id_is_deterministic_across_repeated_calls(self, sample_pdf, temp_vault_db):
        """Zwei Laeufe auf demselben PDF-Pfad muessen dieselbe paper_id
        liefern, damit vault_add_paper() (Upsert ueber paper_id) den
        gleichen Eintrag aktualisiert statt ein Duplikat anzulegen (P2 aus
        PR #440 Review: uuid4() waere bei jedem Lauf neu)."""
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(aps, "run_search", return_value=([], [])),
        ):
            result1 = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)
            result2 = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert result1["paper_id"] == result2["paper_id"]

    def test_pdf_with_no_extractable_text_returns_clean_error(self, sample_pdf, temp_vault_db):
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=""),
            patch.object(aps, "vault_add_paper") as mock_add,
        ):
            result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert result["status"] == "error"
        mock_add.assert_not_called()


# ---------------------------------------------------------------------------
# AC3: ungueltiger Pfad/URL -> ValueError, Vault unveraendert
# ---------------------------------------------------------------------------


class TestAnchorPaperSurveyInvalidInput:
    def test_nonexistent_path_raises_value_error_no_vault_mutation(self, temp_vault_db):
        with patch.object(aps, "vault_add_paper") as mock_add:
            with pytest.raises(ValueError):
                aps.anchor_paper_survey("/no/such/path/does-not-exist.pdf", db_path=temp_vault_db)
        mock_add.assert_not_called()

    def test_invalid_url_raises_value_error_no_vault_mutation(self, temp_vault_db):
        with patch.object(aps, "vault_add_paper") as mock_add:
            with pytest.raises(ValueError):
                aps.anchor_paper_survey(
                    "https://example.com/not-arxiv-not-a-file", db_path=temp_vault_db
                )
        mock_add.assert_not_called()

    def test_empty_input_raises_value_error(self, temp_vault_db):
        with pytest.raises(ValueError):
            aps.anchor_paper_survey("", db_path=temp_vault_db)


# ---------------------------------------------------------------------------
# Folge-Suche-Qualitaet (P1-Findings aus PR #440 Review, Fix-Runde)
#
# 1. Folge-Suche ohne Dedup und ohne Anker-Filter: Trefferzahl falsch,
#    Anker-Paper landet als eigene "verwandte Arbeit" (anchor_paper.py:408).
# 2. SKILL.md wirbt mit Zitations-Recherche, liefert aber nur eine
#    Titel-Keyword-Suche -- Scope-"In" von #394 nicht umgesetzt (SKILL.md:13).
# ---------------------------------------------------------------------------


ARXIV_TITLE = "Language Models are Few-Shot Learners"
ARXIV_DOI = "10.48550/arXiv.2005.14165"


class TestAnchorFilterAndDedupe:
    """Direkte Unit-Tests fuer _filter_and_dedupe() (P1 #1)."""

    def test_anchor_hit_with_identical_title_is_excluded(self):
        hits = [
            {"title": ARXIV_TITLE, "doi": None},
            {"title": "A Genuinely Different Related Work", "doi": "10.1/other"},
        ]
        result = aps._filter_and_dedupe(hits, ARXIV_TITLE, ARXIV_DOI)
        titles = [h["title"] for h in result]
        assert ARXIV_TITLE not in titles
        assert "A Genuinely Different Related Work" in titles
        assert len(result) == 1

    def test_anchor_hit_matched_by_doi_even_with_slightly_different_title(self):
        """Manche Fetcher liefern denselben Treffer mit leicht abweichender
        Titel-Schreibweise (Gross-/Kleinschreibung, Zusatz) zurueck -- der
        DOI-Abgleich muss ihn trotzdem als Anker erkennen."""
        hits = [{"title": "language models are few-shot learners", "doi": ARXIV_DOI}]
        result = aps._filter_and_dedupe(hits, ARXIV_TITLE, ARXIV_DOI)
        assert result == []

    def test_unrelated_hit_with_similar_but_distinct_title_survives(self):
        """Ein NICHT-identisches, nur thematisch verwandtes Paper darf nicht
        faelschlich als Anker herausgefiltert werden (kein Overmatching)."""
        hits = [{"title": "A Survey of Few-Shot Learning Methods", "doi": "10.1/survey"}]
        result = aps._filter_and_dedupe(hits, ARXIV_TITLE, ARXIV_DOI)
        assert len(result) == 1

    def test_duplicate_hits_across_modules_are_merged(self):
        """Dieselbe verwandte Arbeit, von zwei Modulen unabhaengig gefunden
        (gleiche DOI) -- muss zu einem Treffer zusammengefuehrt werden,
        sonst ist die gemeldete Trefferzahl aufgeblaeht."""
        hits = [
            {"title": "A Related Work", "doi": "10.1234/related", "source_module": "arxiv"},
            {"title": "A Related Work", "doi": "10.1234/related", "source_module": "crossref"},
        ]
        result = aps._filter_and_dedupe(hits, ARXIV_TITLE, ARXIV_DOI)
        assert len(result) == 1

    def test_empty_hits_returns_empty(self):
        assert aps._filter_and_dedupe([], ARXIV_TITLE, ARXIV_DOI) == []


class TestAnchorPaperSurveyEndToEndFiltersAnchor:
    """End-to-End-Gegenstueck: der Anker darf auch ueber die volle Pipeline
    nicht als eigene 'verwandte Arbeit' im Ergebnis auftauchen (P1 #1)."""

    def test_arxiv_anchor_not_counted_as_its_own_related_work(self, temp_vault_db):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response.xml")

        # Realistisches Szenario: die Zitations-/Referenz-Traversierung
        # liefert den Anker selbst (z.B. weil er als Ko-Zitation auftaucht)
        # PLUS zwei echte verwandte Arbeiten, eine davon doppelt (zwei
        # Relationen liefern denselben Nachbarn).
        raw_hits = [
            {"title": ARXIV_TITLE, "doi": ARXIV_DOI},
            {
                "title": "GPT-2: Language Models are Unsupervised Multitask Learners",
                "doi": "10.1/gpt2",
            },
            {
                "title": "GPT-2: Language Models are Unsupervised Multitask Learners",
                "doi": "10.1/gpt2",
            },
        ]

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(aps, "run_citation_search", return_value=(raw_hits, [])),
        ):
            result = aps.anchor_paper_survey(
                "https://arxiv.org/abs/2005.14165", db_path=temp_vault_db
            )

        assert result["status"] == "ok"
        titles = [h["title"] for h in result["search"]["hits"]]
        assert ARXIV_TITLE not in titles
        assert result["search"]["count"] == 1
        assert "GPT-2: Language Models are Unsupervised Multitask Learners" in titles


class TestCitationSearchWiring:
    """arXiv-Anker nutzen die echte Semantic-Scholar-Zitations-/Referenz-API,
    PDF-Anker fallen mangels stabiler externer ID auf die Titel-Keyword-Suche
    zurueck (P1 #2: SKILL.md versprach Zitations-Recherche, geliefert wurde
    vorher immer nur run_search())."""

    def test_arxiv_anchor_calls_citation_search_not_keyword_search(self, temp_vault_db):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response.xml")

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(aps, "run_citation_search", return_value=([], [])) as mock_citation,
            patch.object(aps, "run_search") as mock_keyword,
        ):
            aps.anchor_paper_survey("https://arxiv.org/abs/2005.14165", db_path=temp_vault_db)

        mock_citation.assert_called_once_with("ARXIV:2005.14165", limit=aps.DEFAULT_SEARCH_LIMIT)
        mock_keyword.assert_not_called()

    def test_pdf_anchor_falls_back_to_keyword_search_documented_limitation(
        self, sample_pdf, temp_vault_db
    ):
        """PDF-Anker haben keinen stabilen externen Paper-Identifier fuer die
        Semantic-Scholar-API -- dieser Fallback ist eine dokumentierte
        Einschraenkung (SKILL.md), kein Bug."""
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(aps, "run_search", return_value=([], [])) as mock_keyword,
            patch.object(aps, "run_citation_search") as mock_citation,
        ):
            aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        mock_keyword.assert_called_once()
        mock_citation.assert_not_called()

    def test_partial_relation_failure_is_reported(self, temp_vault_db):
        """Schlaegt nur eine der beiden Relationen (citations/references)
        fehl, muss das im Ergebnis sichtbar sein -- kein stiller Datenverlust."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response.xml")

        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(aps, "run_citation_search", return_value=([], ["references"])),
        ):
            result = aps.anchor_paper_survey(
                "https://arxiv.org/abs/2005.14165", db_path=temp_vault_db
            )

        assert result["status"] == "ok"
        assert result["search"]["failed_modules"] == ["references"]
        assert "references" in result["message"]


class TestRunCitationSearch:
    """Netzwerk-naher Test fuer run_citation_search() selbst (echte
    Zitations-/Referenz-Traversierung ueber die Semantic-Scholar-Graph-API)."""

    def _s2_payload(self, nested_key: str, papers: list[dict]) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": [{nested_key: p} for p in papers]}
        return resp

    def test_combines_citations_and_references(self):
        citing = self._s2_payload(
            "citingPaper",
            [{"title": "Citing Paper A", "externalIds": {"DOI": "10.1/a"}, "year": 2021}],
        )
        cited = self._s2_payload(
            "citedPaper",
            [{"title": "Cited Paper B", "externalIds": {"DOI": "10.1/b"}, "year": 2019}],
        )
        with patch("requests.get", side_effect=[citing, cited]):
            hits, failed = aps.run_citation_search("ARXIV:2005.14165", limit=10)

        assert failed == []
        titles = {h["title"] for h in hits}
        assert titles == {"Citing Paper A", "Cited Paper B"}

    def test_one_relation_failing_is_reported_without_crash(self):
        citing_ok = self._s2_payload("citingPaper", [{"title": "Citing Paper A"}])
        references_fail = MagicMock(status_code=500)

        with patch("requests.get", side_effect=[citing_ok, references_fail]):
            hits, failed = aps.run_citation_search("ARXIV:2005.14165", limit=10)

        assert failed == ["references"]
        assert [h["title"] for h in hits] == ["Citing Paper A"]

    def test_network_exception_reported_no_crash(self):
        with patch("requests.get", side_effect=OSError("timeout")):
            hits, failed = aps.run_citation_search("ARXIV:2005.14165", limit=10)

        assert hits == []
        assert set(failed) == {"citations", "references"}

    def test_retries_once_on_429_then_succeeds(self):
        rate_limited = MagicMock(status_code=429)
        ok_after_retry = self._s2_payload("citingPaper", [{"title": "Citing Paper A"}])
        references_empty = self._s2_payload("citedPaper", [])

        with (
            patch("requests.get", side_effect=[rate_limited, ok_after_retry, references_empty]),
            patch.object(aps.time, "sleep"),
        ):
            hits, failed = aps.run_citation_search("ARXIV:2005.14165", limit=10)

        assert failed == []
        assert [h["title"] for h in hits] == ["Citing Paper A"]

    def test_empty_paper_ref_returns_empty_with_failed(self):
        hits, failed = aps.run_citation_search("", limit=10)
        assert hits == []
        assert set(failed) == {"citations", "references"}


# ---------------------------------------------------------------------------
# Issue #599: DOI-Aufloesung fuer PDF-Anker -- echte Zitations-Traversierung
# auch ohne arXiv-ID, sobald ein stabiler Identifier (DOI) vorliegt.
# ---------------------------------------------------------------------------

PDF_TEXT_WITH_DOI = (
    "A Great Paper About Testing\n"
    "Jane Doe, John Smith\n"
    "DOI: 10.1234/great.testing.2024\n\n"
    "Abstract: ...\n"
)


class TestExtractDoiFromText:
    """Unit-Tests fuer extract_doi_from_text() (textquellenagnostisch,
    analog skills/github-repo-research/scripts/analyze_repo.py::extract_dois(),
    Praezedenzfall Issue #401 -- eigenstaendige Implementierung)."""

    def test_extracts_doi_from_header_window(self):
        assert aps.extract_doi_from_text(PDF_TEXT_WITH_DOI) == "10.1234/great.testing.2024"

    def test_returns_none_without_doi(self):
        assert aps.extract_doi_from_text(PDF_SAMPLE_TEXT) is None

    def test_returns_none_for_empty_or_missing_text(self):
        assert aps.extract_doi_from_text("") is None
        assert aps.extract_doi_from_text(None) is None

    def test_ignores_doi_outside_the_search_window(self):
        """Eine DOI weit hinten im Volltext (z.B. in der Bibliographie) darf
        nicht als die EIGENE DOI des Papers missverstanden werden -- die
        Extraktion ist bewusst auf ein Fenster am Textanfang begrenzt
        (Issue #599 Plan, Risiko 1)."""
        padding = "x" * (aps._DOI_SEARCH_WINDOW_CHARS + 100)
        text = f"Title\nAuthors\n{padding}\nDOI: 10.1234/too.late\n"
        assert aps.extract_doi_from_text(text) is None


class TestPdfDoiCitationSearch:
    """AC1: PDF-Anker mit DOI im Text -> Zitations-/Referenz-Abfrage ueber
    Semantic Scholar, nicht die Titel-Stichwortsuche."""

    def test_pdf_with_doi_in_text_uses_citation_search_not_keyword(self, sample_pdf, temp_vault_db):
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_TEXT_WITH_DOI),
            patch.object(aps, "run_citation_search", return_value=([], [])) as mock_citation,
            patch.object(aps, "run_search") as mock_keyword,
        ):
            result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert result["status"] == "ok"
        mock_citation.assert_called_once_with(
            "DOI:10.1234/great.testing.2024", limit=aps.DEFAULT_SEARCH_LIMIT
        )
        mock_keyword.assert_not_called()
        assert result["search"]["method"] == "citation"
        assert result["doi"] == "10.1234/great.testing.2024"

        paper = vault_get_paper(temp_vault_db, result["paper_id"])
        assert paper is not None
        assert paper["doi"] == "10.1234/great.testing.2024"


class TestPdfDoiVaultPriority:
    """AC2: ein Anker, der bereits mit DOI im Vault liegt, nutzt diesen,
    ohne den DOI erneut aus dem PDF zu ziehen."""

    def test_existing_vault_doi_is_reused_without_reextraction(self, sample_pdf, temp_vault_db):
        # Erster Lauf: DOI wird aus dem Text extrahiert und im Vault abgelegt.
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_TEXT_WITH_DOI),
            patch.object(aps, "run_citation_search", return_value=([], [])),
        ):
            first = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        # Zweiter Lauf: der PDF-Text liefert diesmal KEINE DOI -- trotzdem
        # muss die bereits im Vault gespeicherte DOI benutzt werden.
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(aps, "run_citation_search", return_value=([], [])) as mock_citation,
            patch.object(aps, "run_search") as mock_keyword,
        ):
            second = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert first["paper_id"] == second["paper_id"]
        mock_citation.assert_called_once_with(
            "DOI:10.1234/great.testing.2024", limit=aps.DEFAULT_SEARCH_LIMIT
        )
        mock_keyword.assert_not_called()
        assert second["search"]["method"] == "citation"


class TestPdfWithoutDoiFallback:
    """AC3: ohne auffindbaren DOI laeuft der Skill wie bisher ueber die
    Titel-Stichwortsuche und meldet das offen."""

    def test_pdf_without_doi_uses_keyword_search_and_reports_it(self, sample_pdf, temp_vault_db):
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(
                aps, "run_search", return_value=([{"title": "A Related Testing Paper"}], [])
            ) as mock_keyword,
            patch.object(aps, "run_citation_search") as mock_citation,
        ):
            result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        mock_keyword.assert_called_once()
        mock_citation.assert_not_called()
        assert result["search"]["method"] == "keyword"
        assert "kein doi" in result["message"].lower()


class TestSearchMethodLabel:
    """AC4: das Ergebnis weist aus, ob die Treffer aus einer nachgewiesenen
    Zitationsbeziehung oder aus einer thematischen Naeherung stammen --
    literal unterscheidbar, ueber alle drei Pfade (arXiv, PDF+DOI, PDF ohne
    DOI)."""

    def test_method_and_message_distinguish_citation_from_keyword(self, sample_pdf, temp_vault_db):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response.xml")
        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(aps, "run_citation_search", return_value=([], [])),
        ):
            arxiv_result = aps.anchor_paper_survey(
                "https://arxiv.org/abs/2005.14165", db_path=temp_vault_db
            )
        assert arxiv_result["search"]["method"] == "citation"

        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_TEXT_WITH_DOI),
            patch.object(aps, "run_citation_search", return_value=([], [])),
        ):
            pdf_doi_result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)
        assert pdf_doi_result["search"]["method"] == "citation"

        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(aps, "run_search", return_value=([], [])),
        ):
            pdf_keyword_result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)
        assert pdf_keyword_result["search"]["method"] == "keyword"

        # Bewusst disjunkte Formulierungen (keine gemeinsame Teilphrase), s.
        # anchor_paper_survey()-Kommentar zu method_note.
        assert "nachgewiesenen Zitationsbeziehung" in arxiv_result["message"]
        assert "nachgewiesenen Zitationsbeziehung" in pdf_doi_result["message"]
        assert "nachgewiesenen Zitationsbeziehung" not in pdf_keyword_result["message"]
        assert "thematische" in pdf_keyword_result["message"].lower()
        assert "thematische" not in arxiv_result["message"].lower()


class TestS2UnknownReferenceFallback:
    """AC5: eine DOI (bzw. ein s2_ref), die Semantic Scholar nicht kennt,
    fuehrt zu einer verstaendlichen Meldung und zum Rueckfall auf die
    Titelsuche -- nicht zum Abbruch."""

    def test_unknown_doi_falls_back_to_keyword_search_no_crash(self, sample_pdf, temp_vault_db):
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_TEXT_WITH_DOI),
            patch.object(
                aps, "run_citation_search", return_value=([], ["citations", "references"])
            ) as mock_citation,
            patch.object(
                aps, "run_search", return_value=([{"title": "Fallback Hit"}], [])
            ) as mock_keyword,
        ):
            result = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        assert result["status"] == "ok"
        mock_citation.assert_called_once()
        mock_keyword.assert_called_once()
        assert result["search"]["method"] == "keyword"
        assert result["search"]["count"] == 1
        assert "kennt" in result["message"].lower()

    def test_single_relation_failure_stays_report_only_no_fallback(self, temp_vault_db):
        """Gegenprobe: nur EINE Relation fehlgeschlagen darf NICHT auf die
        Titelsuche zurueckfallen (Unterscheidung zu AC5) -- Regressionsschutz
        fuer den bestehenden Test test_partial_relation_failure_is_reported."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = _read("arxiv_response.xml")
        with (
            patch("requests.get", return_value=mock_resp),
            patch.object(aps, "run_citation_search", return_value=([], ["references"])),
            patch.object(aps, "run_search") as mock_keyword,
        ):
            result = aps.anchor_paper_survey(
                "https://arxiv.org/abs/2005.14165", db_path=temp_vault_db
            )

        mock_keyword.assert_not_called()
        assert result["search"]["method"] == "citation"


class TestSkillMdDocumentsDoiPath:
    """AC6: SKILL.md 'Bekannte Einschraenkungen' beschreibt den neuen Stand
    (DOI-Pfad fuer PDF-Anker), nicht mehr die absolute alte Aussage."""

    def test_old_absolute_claim_is_gone(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "Nur arXiv-Anker bekommen eine geprüfte Zitations-/Referenz-Beziehung" not in text

    def test_doi_path_for_pdf_anchors_is_documented(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "DOI" in text
        assert "extract_doi_from_text" in text


# ---------------------------------------------------------------------------
# Regressionsschutz (Issue #599 Plan-Risiken 2 und 5, nicht selbst ACs)
# ---------------------------------------------------------------------------


class TestVaultAddPaperDoiSentinelDefault:
    """Plan-Risiko 2: vault_add_paper()s doi-Parameter darf, wenn nicht
    uebergeben, einen bereits gespeicherten DOI nicht auf NULL zuruecksetzen
    (Sentinel-Default statt doi=None)."""

    def test_omitting_doi_kwarg_does_not_clear_existing_doi(self, temp_vault_db):
        aps.vault_add_paper(
            db_path=temp_vault_db,
            paper_id="anchor-regression-test",
            csl_json=json.dumps({"type": "article-journal", "title": "T", "author": []}),
            doi="10.9999/existing",
        )
        aps.vault_add_paper(
            db_path=temp_vault_db,
            paper_id="anchor-regression-test",
            csl_json=json.dumps({"type": "article-journal", "title": "T2", "author": []}),
        )
        paper = vault_get_paper(temp_vault_db, "anchor-regression-test")
        assert paper["doi"] == "10.9999/existing"

    def test_pdf_rerun_without_new_doi_does_not_clear_existing_vault_doi(
        self, sample_pdf, temp_vault_db
    ):
        """End-to-End-Gegenstueck ueber die volle Pipeline (nicht nur den
        Wrapper direkt)."""
        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_TEXT_WITH_DOI),
            patch.object(aps, "run_citation_search", return_value=([], [])),
        ):
            first = aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        with (
            patch.object(aps, "detect_needs_ocr", return_value=False),
            patch.object(aps, "extract_text_from_pdf", return_value=PDF_SAMPLE_TEXT),
            patch.object(aps, "run_citation_search", return_value=([], [])),
        ):
            aps.anchor_paper_survey(str(sample_pdf), db_path=temp_vault_db)

        paper = vault_get_paper(temp_vault_db, first["paper_id"])
        assert paper["doi"] == "10.1234/great.testing.2024"


class TestS2ApiKeyHeader:
    """Plan-Risiko 4/5: SS_API_KEY (falls gesetzt) muss als x-api-key-Header
    bei _fetch_s2_relation() ankommen -- ohne Key skaliert das Rate-Limit-
    Risiko mit jedem DOI-tragenden PDF-Anker (#599-Gegenpruefung)."""

    def test_ss_api_key_env_var_sent_as_header(self, monkeypatch):
        monkeypatch.setenv("SS_API_KEY", "test-key-123")
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"data": []}
        with patch("requests.get", return_value=mock_resp) as mock_get:
            aps.run_citation_search("ARXIV:2005.14165", limit=5)

        assert mock_get.call_args_list
        for call in mock_get.call_args_list:
            assert call.kwargs["headers"]["x-api-key"] == "test-key-123"

    def test_no_ss_api_key_env_var_omits_header(self, monkeypatch):
        monkeypatch.delenv("SS_API_KEY", raising=False)
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"data": []}
        with patch("requests.get", return_value=mock_resp) as mock_get:
            aps.run_citation_search("ARXIV:2005.14165", limit=5)

        assert mock_get.call_args_list
        for call in mock_get.call_args_list:
            assert "x-api-key" not in call.kwargs["headers"]

    def test_retries_multiple_times_on_repeated_429(self):
        """Vor #599 gab es nur EINEN Retry -- ein zweiter 429 in Folge waere
        als None zurueckgekommen. Jetzt: mehrere Retries mit exponentiellem
        Backoff (_S2_MAX_RETRIES)."""
        rate_limited = MagicMock(status_code=429)
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"data": []}
        with (
            patch("requests.get", side_effect=[rate_limited, rate_limited, ok]),
            patch.object(aps.time, "sleep"),
        ):
            payload = aps._fetch_s2_relation("ARXIV:2005.14165", "citations", 5)
        assert payload == {"data": []}


# ---------------------------------------------------------------------------
# Sicherheits-/Abgrenzungs-Checks (Frontmatter + Quelltext)
# ---------------------------------------------------------------------------


class TestSkillSafetyDocumentation:
    def test_skill_md_documents_heuristic_limitation(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "heurist" in text.lower(), (
            "SKILL.md sollte die Titel/Autoren-Heuristik explizit als Best-Effort "
            "dokumentieren (kein Anspruch auf Vollstaendigkeit)."
        )

    def test_skill_md_documents_no_new_external_service(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "kein neuer externer Dienst" in text or "keine Zitations-Graph" in text, (
            "SKILL.md sollte die Out-of-Scope-Abgrenzung (kein neuer Dienst, "
            "keine Zitations-Graph-DB) dokumentieren."
        )

    def test_script_contains_no_dangerous_execution(self):
        text = ANCHOR_PAPER_SCRIPT.read_text(encoding="utf-8").lower()
        for forbidden in ("subprocess", "os.system", "exec(", "eval(", "git clone"):
            assert forbidden not in text, (
                f"anchor_paper.py enthaelt verbotenes Muster {forbidden!r}"
            )
