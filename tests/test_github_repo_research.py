"""Tests fuer github-repo-research Skill (Issue #401, TDD).

Testet analyze_repo.py:
- README mit arXiv-Link -> mind. 1 Kandidat wird ueber vault_add_paper()
  in den Vault geschrieben (AC1)
- README ohne erkennbare Publikations-Referenz -> strukturiertes
  Leer-Ergebnis, kein Crash, keine Fabrikation (AC2)
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
            patch.object(agr, "fetch_readme", return_value=readme_text),
            patch.object(agr, "fetch_citation_cff", return_value=None),
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
            patch.object(agr, "fetch_readme", return_value="# My Tool\n\nNo direct link here.\n"),
            patch.object(agr, "fetch_citation_cff", return_value=cff_text),
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
            patch.object(agr, "fetch_readme", return_value="# My Tool\n\nNo direct link here.\n"),
            patch.object(agr, "fetch_citation_cff", return_value=cff_text),
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
            patch.object(agr, "fetch_readme", return_value=readme_text),
            patch.object(agr, "fetch_citation_cff", return_value=None),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        assert isinstance(result["message"], str) and result["message"]
        mock_add.assert_not_called()

    def test_readme_fetch_failure_does_not_crash(self):
        """GitHub-API nicht erreichbar (Rate-Limit/Netzfehler) -> kein Crash (AC2)."""
        with (
            patch.object(agr, "fetch_readme", return_value=None),
            patch.object(agr, "fetch_citation_cff", return_value=None),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        mock_add.assert_not_called()

    def test_resolution_failure_returns_no_candidates_not_fabricated(self):
        """arXiv-ID erkannt, aber Resolution schlaegt fehl -> kein Fake-Paper."""
        readme_text = _read("readme_with_arxiv.md")

        with (
            patch.object(agr, "fetch_readme", return_value=readme_text),
            patch.object(agr, "fetch_citation_cff", return_value=None),
            patch.object(agr, "resolve_arxiv_id", return_value=None),
            patch.object(agr, "vault_add_paper") as mock_add,
        ):
            result = agr.analyze_repo("https://github.com/foo/bar", db_path="unused.db")

        assert result["candidates"] == []
        mock_add.assert_not_called()


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
