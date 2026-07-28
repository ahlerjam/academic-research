"""Tests fuer Issue #369: vault_search-Crash bei leerer/Sonderzeichen-Query.

TDD: Tests werden zuerst geschrieben (RED), dann Implementierung (GREEN).

``_sanitize_fts5_query`` fiel bei leerem Sanitisierungsergebnis bisher auf
die unveraenderte Roh-Query zurueck (``return sanitized if sanitized else
query``). Genau die Faelle, die sanitisiert werden sollten (leere Query,
reine Sonderzeichen), landeten so roh in der FTS5-``MATCH``-Klausel und
loesten einen ``sqlite3.OperationalError: fts5: syntax error`` aus.
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _make_db(tmp_path: Path) -> str:
    """Erstellt eine Vault-DB mit Schema und gibt den Pfad zurueck."""
    db_path = str(tmp_path / "vault.db")
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    db.init_schema()
    return db_path


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str) -> None:
    """Hilfsfunktion: fuegt ein Paper in den Vault ein."""
    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


class TestSearchPapersEmptyOrSpecialCharsQuery:
    """AK1 + AK2: leere/rein-Sonderzeichen-Query -> [] statt Exception."""

    def test_search_papers_empty_query_returns_empty_list(self, tmp_path):
        """search_papers(DB, '') liefert [] statt eine Exception zu werfen."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p001", "Transformer Neural Networks", "Self-attention for NLP.")

        from academic_vault.server import search_papers

        results = search_papers(db_path, "")

        assert results == []

    @pytest.mark.parametrize(
        "query",
        [
            "-()*",
            '"',
            ":",
            "NOT",
        ],
    )
    def test_search_papers_special_chars_only_returns_empty_list(self, tmp_path, query):
        """Jede nach Sanitisierung leere Query liefert [] statt Exception."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p001", "Transformer Neural Networks", "Self-attention for NLP.")

        from academic_vault.server import search_papers

        results = search_papers(db_path, query)

        assert results == []

    def test_search_papers_empty_query_with_rerank_returns_empty_list(self, tmp_path):
        """rerank=True-Pfad darf bei leerer Query nicht durchlaufen werden."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p001", "Transformer Neural Networks", "Self-attention for NLP.")

        from academic_vault.server import search_papers

        results = search_papers(db_path, "", rerank=True)

        assert results == []

    def test_search_papers_empty_query_with_type_filter_returns_empty_list(self, tmp_path):
        """type_filter-SQL-Zweig muss ebenfalls den Empty-Query-Guard respektieren."""
        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p001", "Transformer Neural Networks", "Self-attention for NLP.")

        from academic_vault.server import search_papers

        results = search_papers(db_path, "-()*", type_filter="article-journal")

        assert results == []

    def test_search_papers_valid_query_still_returns_results(self, tmp_path):
        """AK3-Regression: gueltige Suchanfrage liefert weiterhin korrekte Treffer."""
        db_path = _make_db(tmp_path)
        _add_paper(
            db_path,
            "p001",
            "Transformer Neural Networks",
            "Self-attention mechanism for NLP tasks.",
        )
        _add_paper(
            db_path, "p002", "Convolutional Networks", "Image classification with deep learning."
        )

        from academic_vault.server import search_papers

        results = search_papers(db_path, "transformer attention", k=5)

        assert len(results) > 0
        paper_ids = [r["paper_id"] for r in results]
        assert "p001" in paper_ids
