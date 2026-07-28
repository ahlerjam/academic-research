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
            patch.object(aps, "run_search", return_value=(search_hits, [])) as mock_search,
        ):
            result = aps.anchor_paper_survey(
                "https://arxiv.org/abs/2005.14165", db_path=temp_vault_db
            )

        assert result["status"] == "ok"
        assert result["source"] == "arxiv"
        mock_add.assert_called_once()
        mock_search.assert_called_once()

        paper = vault_get_paper(temp_vault_db, result["paper_id"])
        assert paper is not None
        csl = json.loads(paper["csl_json"])
        assert csl["title"] == "Language Models are Few-Shot Learners"
        assert paper["provenance"] == "anchor-paper"

        assert result["search"]["count"] == 1
        assert result["search"]["hits"] == search_hits

    def test_arxiv_resolution_failure_adds_no_paper(self, temp_vault_db):
        with (
            patch.object(aps, "resolve_arxiv_id", return_value=None),
            patch.object(aps, "vault_add_paper") as mock_add,
            patch.object(aps, "run_search") as mock_search,
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
            patch.object(aps, "run_search") as mock_search,
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
