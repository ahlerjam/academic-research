"""Shared Fixtures fuer Evals-Suites."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.evals.eval_runner import (
    load_agent_content,
    load_eval_file,
    load_skill_content,
)
from tests.evals.vault_fixture import SEED_PAPERS, VaultSession, build_vault_session


@pytest.fixture
def skill_loader():
    return load_skill_content


@pytest.fixture
def agent_loader():
    return load_agent_content


@pytest.fixture
def eval_loader():
    return load_eval_file


# ---------------------------------------------------------------------------
# Test-Vault (echt, Issue #824)
# ---------------------------------------------------------------------------


@pytest.fixture
def vault_session(tmp_path) -> VaultSession:
    """Wegwerf-Vault + MCP-Config + cwd fuer das ``vault``-Sitzungsprofil (#824).

    Je Testfunktion eine eigene SQLite-Datei: ``academic_vault/server.py``
    friert ``_DEFAULT_DB`` beim Import ein (ein Serverprozess = eine DB), eine
    Umschaltung innerhalb einer Sitzung gibt es nicht.
    """
    return build_vault_session(tmp_path / "vault-session")


# ---------------------------------------------------------------------------
# MockVault — in-memory dict-stub
# Simuliert vault.add_quote / find_quotes / get_quote / ensure_file
# ohne echten Vault-DB oder API-Key.
# ---------------------------------------------------------------------------

# Eine Quelle fuer Mock und echte Test-Vault (Issue #824): vorher lagen die
# Fake-Papers nur hier, ein Live-Fall gegen die geseedete DB haette andere
# Daten gesehen als der Mock-Test daneben.
_FAKE_PAPERS = SEED_PAPERS


class MockVault:
    """In-memory Vault-Stub fuer Tests ohne echten Vault-DB oder API-Key.

    Stellt dieselbe Schnittstelle wie der MCP academic_vault bereit:
      - add_quote(...) → quote_id (UUID)
      - find_quotes(paper_id, query, k) → list[dict]
      - get_quote(quote_id) → dict | None
      - get_paper(paper_id) → dict | None (Metadaten inkl. pdf_path, #514)
      - ensure_file(paper_id) → file_id (Fake, nur fuer den Citations-API-Opt-in)
    """

    def __init__(self) -> None:
        self._quotes: dict[str, dict] = {}
        # Seed-Quotes aus Fake-Paper-Daten vorbelegen
        for paper_id, paper in _FAKE_PAPERS.items():
            for sq in paper.get("_seed_quotes", []):
                qid = str(uuid4())
                self._quotes[qid] = {
                    "quote_id": qid,
                    "paper_id": paper_id,
                    "verbatim": sq["verbatim"],
                    "pdf_page": sq.get("pdf_page"),
                    "section": sq.get("section"),
                    "extraction_method": "seed",
                    "api_response_id": None,
                }

    def add_quote(
        self,
        paper_id: str,
        verbatim: str,
        extraction_method: str = "manual",
        api_response_id: str | None = None,
        pdf_page: int | None = None,
        section: str | None = None,
        context_before: str | None = None,
        context_after: str | None = None,
    ) -> str:
        """Fuegt Quote hinzu und gibt UUID zurueck."""
        quote_id = str(uuid4())
        self._quotes[quote_id] = {
            "quote_id": quote_id,
            "paper_id": paper_id,
            "verbatim": verbatim,
            "extraction_method": extraction_method,
            "api_response_id": api_response_id,
            "pdf_page": pdf_page,
            "section": section,
            "context_before": context_before,
            "context_after": context_after,
        }
        return quote_id

    def find_quotes(
        self,
        paper_id: str,
        query: str | None = None,
        k: int = 10,
    ) -> list[dict]:
        """Gibt gespeicherte Quotes fuer ein Paper zurueck, optional gefiltert."""
        results = [q for q in self._quotes.values() if q["paper_id"] == paper_id]
        if query:
            q_lower = query.lower()
            results = [
                q for q in results if q_lower in q["verbatim"].lower()
            ] or results  # Fallback: alle Quotes des Papers wenn kein Treffer
        return results[:k]

    def get_quote(self, quote_id: str) -> dict | None:
        """Gibt gespeicherten Quote-Record zurueck oder None."""
        return self._quotes.get(quote_id)

    def ensure_file(self, paper_id: str) -> str:
        """Gibt Fake-file_id zurueck (kein echter API-Upload)."""
        return f"file-fake-{paper_id}"

    def get_paper(self, paper_id: str) -> dict | None:
        """Gibt Fake-Paper-Metadaten inkl. pdf_path zurueck (#514)."""
        paper = _FAKE_PAPERS.get(paper_id)
        if paper is None:
            return None
        return {
            "paper_id": paper["paper_id"],
            "title": paper["title"],
            "doi": paper["doi"],
            "pdf_path": paper["pdf_path"],
        }


@pytest.fixture
def mock_vault() -> MockVault:
    """In-memory MockVault-Instanz fuer Tests ohne Vault-DB oder API-Key."""
    return MockVault()
