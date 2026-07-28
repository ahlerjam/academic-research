"""Tests fuer github-repo-research Skill (Issue #401, TDD).

Testet analyze_repo.py:
- README mit arXiv-Link -> mind. 1 Kandidat wird ueber vault_add_paper()
  in den Vault geschrieben (AC1)
- README ohne erkennbare Publikations-Referenz -> strukturiertes
  Leer-Ergebnis, kein Crash, keine Fabrikation (AC2)
- Fetch-Fehler (403/Timeout/kein requests) -> Ergebnis ist als unvollstaendig
  markiert und behauptet NICHT, das Repo enthalte keine Referenz (AC2,
  Review-Fund PR #433)
- Frontmatter (allowed-tools) und Quelltext verbieten jede
  Code-Ausfuehrung des analysierten Zielrepos (AC3)
- Beide Faelle sind hier gemeinsam gruen (AC4)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "github-repo-research"
SKILL_MD = SKILL_DIR / "SKILL.md"
ANALYZE_REPO_SCRIPT = SKILL_DIR / "scripts" / "analyze_repo.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "github_repo_research"

if str(SKILL_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))

import analyze_repo as agr  # noqa: E402  (Pfad-Setup muss vor dem Import stehen)


def _read(fixture_name: str) -> str:
    return (FIXTURES_DIR / fixture_name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# URL-Parsing
# ---------------------------------------------------------------------------


class TestParseGithubUrl:
    def test_parses_owner_repo(self):
        assert agr.parse_github_url("https://github.com/foo/bar") == ("foo", "bar")

    def test_parses_with_trailing_slash(self):
        assert agr.parse_github_url("https://github.com/foo/bar/") == ("foo", "bar")

    def test_parses_with_git_suffix(self):
        assert agr.parse_github_url("https://github.com/foo/bar.git") == ("foo", "bar")

    def test_parses_without_scheme(self):
        assert agr.parse_github_url("github.com/foo/bar") == ("foo", "bar")

    def test_invalid_url_raises_value_error(self):
        with pytest.raises(ValueError):
            agr.parse_github_url("https://example.com/foo/bar")

    def test_non_repo_github_url_raises_value_error(self):
        with pytest.raises(ValueError):
            agr.parse_github_url("https://github.com/foo")


# ---------------------------------------------------------------------------
# Extraktion aus README-Freitext
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_extract_arxiv_id_from_abs_link(self):
        text = "Paper: https://arxiv.org/abs/2005.14165"
        assert agr.extract_arxiv_ids(text) == ["2005.14165"]

    def test_extract_arxiv_id_from_pdf_link_with_version(self):
        text = "See http://arxiv.org/pdf/1706.03762v5.pdf"
        assert agr.extract_arxiv_ids(text) == ["1706.03762"]

    def test_extract_arxiv_id_from_bare_prefix(self):
        text = "Described in arXiv:2005.14165."
        assert agr.extract_arxiv_ids(text) == ["2005.14165"]

    def test_extract_dois_from_doi_org_link(self):
        text = "Published at https://doi.org/10.1038/nature14539"
        assert agr.extract_dois(text) == ["10.1038/nature14539"]

    def test_extract_dois_from_bare_doi(self):
        text = "DOI: 10.5281/zenodo.1234 for the release."
        assert agr.extract_dois(text) == ["10.5281/zenodo.1234"]

    def test_no_reference_extracts_nothing(self):
        text = _read("readme_without_reference.md")
        assert agr.extract_arxiv_ids(text) == []
        assert agr.extract_dois(text) == []

    def test_empty_text_extracts_nothing(self):
        assert agr.extract_arxiv_ids("") == []
        assert agr.extract_dois("") == []


# ---------------------------------------------------------------------------
# CITATION.cff-Parsing
# ---------------------------------------------------------------------------


class TestParseCitationCff:
    def test_parses_top_level_doi_and_title(self):
        cff = "cff-version: 1.2.0\ntitle: My Tool\ndoi: 10.5281/zenodo.1234\n"
        result = agr.parse_citation_cff(cff)
        assert result is not None
        assert result["doi"] == "10.5281/zenodo.1234"
        assert result["title"] == "My Tool"

    def test_parses_preferred_citation(self):
        cff = (
            "cff-version: 1.2.0\n"
            "title: My Tool\n"
            "preferred-citation:\n"
            "  type: article\n"
            "  title: The Paper Behind My Tool\n"
            "  doi: 10.1234/abcd\n"
            "  authors:\n"
            "    - family-names: Doe\n"
            "      given-names: Jane\n"
        )
        result = agr.parse_citation_cff(cff)
        assert result is not None
        assert result["doi"] == "10.1234/abcd"
        assert result["title"] == "The Paper Behind My Tool"
        assert result["authors"] == [{"family": "Doe", "given": "Jane"}]

    def test_missing_doi_and_title_returns_none(self):
        cff = "cff-version: 1.2.0\nmessage: Please cite this software.\n"
        assert agr.parse_citation_cff(cff) is None

    def test_invalid_yaml_returns_none_no_crash(self):
        assert agr.parse_citation_cff("not: [valid: yaml") is None

    def test_empty_text_returns_none(self):
        assert agr.parse_citation_cff("") is None
        assert agr.parse_citation_cff(None) is None


# ---------------------------------------------------------------------------
# AC1: Treffer-Fall -- README mit arXiv-Link fuehrt zu >=1 Vault-Eintrag
# ---------------------------------------------------------------------------


ARXIV_CSL_JSON = (
    '{"type": "article-journal", "title": "Language Models are Few-Shot Learners", '
    '"author": [{"literal": "Tom B. Brown"}], "DOI": "10.48550/arXiv.2005.14165", '
    '"issued": {"date-parts": [[2020]]}}'
)


class TestAnalyzeRepoHit:
    def test_readme_with_arxiv_link_adds_paper_to_vault(self):
        readme_text = _read("readme_with_arxiv.md")

        with (
            patch.object(agr, "fetch_readme", return_value=agr.FetchResult(readme_text)),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(None)),
            patch.object(agr, "resolve_arxiv_id", return_value=ARXIV_CSL_JSON) as mock_resolve,
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        mock_resolve.assert_called_once_with("2005.14165")
        assert len(result["candidates"]) == 1
        candidate = result["candidates"][0]
        assert candidate["arxiv_id"] == "2005.14165"

        mock_add.assert_called_once()
        _, kwargs = mock_add.call_args
        assert kwargs["csl_json"] == ARXIV_CSL_JSON
        assert kwargs["doi"] == "10.48550/arXiv.2005.14165"
        assert kwargs["db_path"] == "unused.db"

    def test_citation_cff_doi_resolves_via_crossref(self):
        crossref_csl = (
            '{"type": "article-journal", "title": "The Paper Behind My Tool", '
            '"author": [{"family": "Doe", "given": "Jane"}], "DOI": "10.1234/abcd"}'
        )
        cff_text = (
            "cff-version: 1.2.0\ntitle: My Tool\npreferred-citation:\n"
            "  doi: 10.1234/abcd\n  title: The Paper Behind My Tool\n"
        )

        with (
            patch.object(
                agr, "fetch_readme", return_value=agr.FetchResult("# My Tool\n\nNo link.\n")
            ),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(cff_text)),
            patch.object(agr, "resolve_doi", return_value=crossref_csl) as mock_resolve,
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        mock_resolve.assert_called_once_with("10.1234/abcd")
        assert len(result["candidates"]) == 1
        mock_add.assert_called_once()

    def test_doi_path_with_real_crossref_type_reaches_real_vault(self, temp_vault_db):
        """Regression (PR #433-Review): der obige Test mockt resolve_doi() UND
        vault_add_paper() weg und kann daher nie sehen, dass die echte
        resolve_doi()-Implementierung Crossrefs 'type'-Vokabular (z.B.
        'journal-article') unveraendert als CSL-'type' durchreicht. Der Vault
        akzeptiert aber ausschliesslich {'article-journal', 'book', 'chapter'}
        (VALID_PAPER_TYPES, academic_vault/db.py) und wirft sonst ValueError
        (validate_csl_json, academic_vault/server.py) -- vault_add_paper()
        crashte dadurch fuer praktisch jeden echten Crossref-Journal-Treffer.

        Hier laeuft NUR die HTTP-Grenze (requests.get) gemockt; resolve_doi()
        und vault_add_paper() laufen echt gegen eine frisch initialisierte
        Vault-DB (temp_vault_db-Fixture aus tests/conftest.py).
        """
        cff_text = (
            "cff-version: 1.2.0\ntitle: My Tool\npreferred-citation:\n"
            "  doi: 10.1234/abcd\n  title: The Paper Behind My Tool\n"
        )
        crossref_message = {
            # Echtes Crossref-Vokabular, KEIN CSL-Typ (vgl. VALID_PAPER_TYPES).
            "type": "journal-article",
            "title": ["The Paper Behind My Tool"],
            "author": [{"family": "Doe", "given": "Jane"}],
            "DOI": "10.1234/abcd",
            "published": {"date-parts": [[2021]]},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": crossref_message}

        with (
            patch.object(
                agr, "fetch_readme", return_value=agr.FetchResult("# My Tool\n\nNo link.\n")
            ),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(cff_text)),
            patch("requests.get", return_value=mock_resp),
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path=temp_vault_db)

        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["doi"] == "10.1234/abcd"


# ---------------------------------------------------------------------------
# AC2: Kein-Treffer-Fall -- kein Crash, keine Fabrikation
# ---------------------------------------------------------------------------


class TestAnalyzeRepoNoHit:
    def test_readme_without_reference_returns_no_candidates(self):
        readme_text = _read("readme_without_reference.md")

        with (
            patch.object(agr, "fetch_readme", return_value=agr.FetchResult(readme_text)),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(None)),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        assert isinstance(result["message"], str) and result["message"]
        mock_add.assert_not_called()

    def test_readme_fetch_failure_does_not_crash(self):
        """GitHub-API nicht erreichbar (Rate-Limit/Netzfehler) -> kein Crash (AC2)."""
        with (
            patch.object(
                agr, "fetch_readme", return_value=agr.FetchResult(None, "HTTP 403 (Rate-Limit?)")
            ),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(None)),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        mock_add.assert_not_called()

    def test_both_sources_absent_reports_absence_not_error(self):
        """Repo hat weder README noch CITATION.cff (beide 404) -> das IST ein Beleg
        fuer Abwesenheit und darf als solcher gemeldet werden (status 'ok')."""
        with (
            patch.object(agr, "fetch_readme", return_value=agr.FetchResult(None)),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(None)),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        assert result["status"] == "ok"
        assert result["errors"] == []
        mock_add.assert_not_called()

    def test_resolution_failure_returns_no_candidates_not_fabricated(self):
        """arXiv-ID erkannt, aber Resolution schlaegt fehl -> kein Fake-Paper."""
        readme_text = _read("readme_with_arxiv.md")

        with (
            patch.object(agr, "fetch_readme", return_value=agr.FetchResult(readme_text)),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(None)),
            patch.object(agr, "resolve_arxiv_id", return_value=None),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        mock_add.assert_not_called()


# ---------------------------------------------------------------------------
# AC2 (Review-Fund PR #433): Fetch-Fehler != Beleg fuer Abwesenheit
# ---------------------------------------------------------------------------

# Wortlaut-Fragment der Absenz-Behauptung ("... enthalten eine erkennbare
# arXiv-ID oder DOI"). Genau diese Aussage darf NIE fallen, wenn README bzw.
# CITATION.cff gar nicht gelesen werden konnten.
_ABSENCE_CLAIM_FRAGMENT = "enthalten eine erkennbare"


class TestFetchErrorIsNotEvidenceOfAbsence:
    """Ein 403/404-freier Fehlschlag (Rate-Limit, Timeout, fehlendes `requests`)
    liefert KEIN Wissen ueber den Repo-Inhalt. analyze_repo() darf daraus
    deshalb nicht die belegte Aussage 'Repo enthaelt keine Referenz' machen
    (analyze_repo.py:489 vor diesem Fix) -- Evidence before assertions.
    """

    def test_fetch_readme_rate_limit_is_error_not_absence(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        with patch("requests.get", return_value=mock_resp):
            result = agr.fetch_readme("foo", "bar")

        assert result.text is None
        assert result.failed
        assert "403" in result.error

    def test_fetch_readme_404_is_absence_not_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("requests.get", return_value=mock_resp):
            result = agr.fetch_readme("foo", "bar")

        assert result.text is None
        assert not result.failed

    def test_fetch_readme_network_exception_is_error(self):
        with patch("requests.get", side_effect=OSError("connection timed out")):
            result = agr.fetch_readme("foo", "bar")

        assert result.failed
        assert "connection timed out" in result.error

    def test_fetch_citation_cff_rate_limit_is_error_not_absence(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        with patch("requests.get", return_value=mock_resp):
            result = agr.fetch_citation_cff("foo", "bar")

        assert result.text is None
        assert result.failed

    def test_missing_requests_is_error_not_absence(self):
        with patch.object(agr, "_REQUESTS_AVAILABLE", False):
            assert agr.fetch_readme("foo", "bar").failed
            assert agr.fetch_citation_cff("foo", "bar").failed

    def test_analyze_repo_marks_result_incomplete_and_avoids_absence_claim(self):
        with (
            patch.object(
                agr, "fetch_readme", return_value=agr.FetchResult(None, "HTTP 403 (Rate-Limit?)")
            ),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(None)),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        assert result["status"] == "incomplete"
        assert any("403" in e for e in result["errors"])
        assert _ABSENCE_CLAIM_FRAGMENT not in result["message"]
        assert "403" in result["message"]
        mock_add.assert_not_called()

    def test_analyze_repo_reports_fetch_error_even_when_candidates_found(self):
        """CITATION.cff liefert einen Treffer, das README blieb aber ungelesen:
        das Ergebnis ist trotzdem unvollstaendig und muss das sagen."""
        cff_text = (
            "cff-version: 1.2.0\ntitle: My Tool\npreferred-citation:\n"
            "  doi: 10.1234/abcd\n  title: The Paper Behind My Tool\n"
        )
        crossref_csl = '{"type": "article-journal", "title": "T", "DOI": "10.1234/abcd"}'

        with (
            patch.object(
                agr, "fetch_readme", return_value=agr.FetchResult(None, "Netzwerkfehler: timeout")
            ),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(cff_text)),
            patch.object(agr, "resolve_doi", return_value=crossref_csl),
            patch.object(agr, "vault_add_paper"),
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert len(result["candidates"]) == 1
        assert result["status"] == "incomplete"
        assert any("timeout" in e for e in result["errors"])

    def test_successful_run_is_status_ok_without_errors(self):
        readme_text = _read("readme_with_arxiv.md")
        with (
            patch.object(agr, "fetch_readme", return_value=agr.FetchResult(readme_text)),
            patch.object(agr, "fetch_citation_cff", return_value=agr.FetchResult(None)),
            patch.object(agr, "resolve_arxiv_id", return_value=ARXIV_CSL_JSON),
            patch.object(agr, "vault_add_paper"),
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["status"] == "ok"
        assert result["errors"] == []

    def test_cli_exits_nonzero_on_incomplete_result(self):
        """Ein unvollstaendiges Ergebnis darf einem Skript nicht als Erfolg
        (Exit 0) gemeldet werden."""
        incomplete = {
            "candidates": [],
            "status": "incomplete",
            "errors": ["README: HTTP 403 (Rate-Limit?)"],
            "message": "unbestaetigt",
        }
        argv = ["analyze_repo.py", "--url", "https://github.com/foo/bar"]
        with (
            patch.object(agr, "analyze_repo", return_value=incomplete),
            patch.object(sys, "argv", argv),
            pytest.raises(SystemExit) as exc,
        ):
            agr._cli()

        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# AC3: keine Code-Ausfuehrung des Zielrepos
# ---------------------------------------------------------------------------

_ALLOWED_TOOLS_FORBIDDEN = ("clone", "checkout", "git ")
_SCRIPT_FORBIDDEN_PATTERNS = ("subprocess", "os.system", "exec(", "eval(", "git clone", "git.repo")


class TestNoRepoCodeExecution:
    def test_skill_frontmatter_allowed_tools_no_git_exec(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        m = re.search(r"^allowed-tools:\s*\n((?:\s*-\s*.+\n)+)", text, re.MULTILINE)
        assert m, "allowed-tools-Block nicht im SKILL.md-Frontmatter gefunden"
        block = m.group(1).lower()
        for forbidden in _ALLOWED_TOOLS_FORBIDDEN:
            assert forbidden not in block, (
                f"allowed-tools enthaelt verdaechtiges Muster {forbidden!r}: {block}"
            )

    def test_script_contains_no_repo_code_execution(self):
        text = ANALYZE_REPO_SCRIPT.read_text(encoding="utf-8").lower()
        for forbidden in _SCRIPT_FORBIDDEN_PATTERNS:
            assert forbidden not in text, (
                f"analyze_repo.py enthaelt verbotenes Muster {forbidden!r}"
            )

    def test_skill_md_documents_no_clone_policy(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "git clone" in text.lower() or "kein clone" in text.lower(), (
            "SKILL.md sollte explizit dokumentieren, dass kein Repo-Klon erfolgt"
        )
