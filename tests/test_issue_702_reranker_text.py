"""Tests fuer Issue #702: Reranker bekommt echten Chunk-/Abstract-Text statt

10-Token-FTS5-Snippets mit HTML-Markup.

TDD: Tests werden zuerst geschrieben (RED), dann Implementierung (GREEN).

AC1: Fuer einen rein per FTS5 gefundenen Treffer erhaelt der Reranker einen
     Text, der weder auf die Snippet-Laenge gekuerzt ist noch '<b>'/'</b>'
     enthaelt.
AC2: Fuer einen Treffer aus beiden Quellen bleibt das angezeigte 'snippet'
     samt Highlighting unveraendert -- nur die Reranker-Eingabe aendert sich.
AC3: apply_reranker() wird mit der unsanitierten Nutzerquery aufgerufen.
AC4: Kein an einen Reranker uebergebener Text enthaelt FTS5-Markup.
AC5: Findet sich fuer einen Treffer kein besserer Text als das Snippet, wird
     das geloggt statt still hingenommen.
"""

import json
import logging


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str) -> None:
    """Legt ein Paper via server.add_paper an."""
    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


def _use_embedder(monkeypatch, embedder) -> None:
    """Injiziert den Test-Embedder in beide Aufrufstellen (ingest + server)."""
    monkeypatch.setattr("academic_vault.ingest.get_embedder", lambda *a, **kw: embedder)
    monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: embedder)


def _store_chunk(db_path: str, paper_id: str, text: str, embedder) -> str:
    """Schreibt einen Chunk inkl. Vektor direkt in chunk_embeddings."""
    from academic_vault.db import VaultDB
    from academic_vault.embedding_model import serialize_f32

    vector = embedder.embed_documents([text])[0]
    db = VaultDB(db_path)
    return db.add_chunk_embedding(
        paper_id=paper_id,
        chunk_text=text,
        context_sentence="",
        embedding_text=text,
        embedding_vector=serialize_f32(vector),
    )


class TestFtsOnlyCandidateGetsFullText:
    """AC1: FTS5-only-Treffer bekommt einen ungekuerzten, markupfreien Text."""

    def test_fts_only_hit_gets_abstract_not_truncated_snippet(self, temp_vault_db, monkeypatch):
        from academic_vault import server

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        long_abstract = (
            "Dieser Abstract beschreibt ausfuehrlich ein Retrieval-System mit "
            "vielen Woertern, die weit ueber die zehn Token hinausgehen, die ein "
            "FTS5-Snippet normalerweise liefert, damit der Unterschied zwischen "
            "Snippet und Volltext im Test messbar ist."
        )
        _add_paper(temp_vault_db, "p_fts_only", "Retrieval systems", long_abstract)
        monkeypatch.setattr(server, "get_embedder", lambda *a, **kw: None)

        seen_candidates: list[list[dict]] = []

        def _spy(query, candidates, voyage_api_key=None, cohere_api_key=None):
            seen_candidates.append(candidates)
            for c in candidates:
                c["reranked"] = False
                c["reranker"] = "none"
            return candidates

        import academic_vault.retrieval as retrieval_module

        # search_papers importiert apply_reranker lokal im Funktionskoerper
        # (from .retrieval import apply_reranker) -- patchbar ist daher nur
        # das Modul-Attribut, nicht ein server-seitiger Name.
        monkeypatch.setattr(retrieval_module, "apply_reranker", _spy)

        server.search_papers(temp_vault_db, "retrieval", k=5, rerank=True)

        assert seen_candidates, "apply_reranker wurde nicht aufgerufen"
        candidates = seen_candidates[0]
        by_id = {c["paper_id"]: c for c in candidates}
        assert "p_fts_only" in by_id
        text = by_id["p_fts_only"]["text"]
        assert "<b>" not in text and "</b>" not in text
        assert len(text) > 50, "Reranker-Text ist auf Snippet-Laenge gekuerzt"
        assert text == long_abstract


class TestBothSourcesSnippetUnchanged:
    """AC2: Angezeigtes 'snippet' bleibt bei Doppeltreffern unveraendert."""

    def test_snippet_with_highlighting_survives_text_enrichment(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        from academic_vault.server import search_papers

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p_both", "Retrieval systems", "retrieval methods")
        _store_chunk(temp_vault_db, "p_both", "Retrieval systems und Methoden", fake_embedder)
        _use_embedder(monkeypatch, fake_embedder)

        fts_only = {r["paper_id"]: r for r in search_papers(temp_vault_db, "retrieval", k=5)}
        hybrid = {
            r["paper_id"]: r for r in search_papers(temp_vault_db, "retrieval", k=5, rerank=True)
        }
        entry = hybrid["p_both"]

        assert "<b>" in entry["snippet"], "Setup-Annahme: Snippet traegt Highlighting"
        assert entry["snippet"] == fts_only["p_both"]["snippet"]


class TestApplyRerankerGetsRawQuery:
    """AC3: apply_reranker() bekommt die unsanitierte Nutzerquery."""

    def test_apply_reranker_called_with_unsanitized_query(self, temp_vault_db, monkeypatch):
        import academic_vault.server as server

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "e-Learning AND Digitalisierung", "e-Learning Text")
        monkeypatch.setattr(server, "get_embedder", lambda *a, **kw: None)

        seen_queries: list[str] = []

        def _spy(query, candidates, voyage_api_key=None, cohere_api_key=None):
            seen_queries.append(query)
            for c in candidates:
                c["reranked"] = False
                c["reranker"] = "none"
            return candidates

        import academic_vault.retrieval as retrieval_module

        monkeypatch.setattr(retrieval_module, "apply_reranker", _spy)

        raw_query = "e-Learning AND Digitalisierung"
        server.search_papers(temp_vault_db, raw_query, k=5, rerank=True)

        assert seen_queries == [raw_query]


class TestNoFts5MarkupReachesReranker:
    """AC4: Kein an einen Reranker uebergebener Text enthaelt FTS5-Markup."""

    def test_apply_reranker_hardening_strips_html_markup(self):
        """Haertungs-Fallback in apply_reranker() selbst: strippt '<b>'/'</b>'.

        Dieser Test ruft apply_reranker() direkt auf mit einem Kandidaten, der
        absichtlich keinen 'text' hat und dessen 'snippet' Markup enthaelt --
        genau der Fall, den der bisherige Fallback (entry.get('snippet', ...))
        unveraendert durchreichte.
        """
        from academic_vault.retrieval import apply_reranker

        candidates = [
            {"paper_id": "p001", "snippet": "...Digitali<b>sierung</b> im Mittel..."},
        ]
        result = apply_reranker(query="digitalisierung", candidates=candidates)

        assert len(result) == 1
        text = result[0]["text"]
        assert "<b>" not in text
        assert "</b>" not in text


class TestMissingBetterTextLogsWarning:
    """AC5: Kein Abstract/Chunk -> Logging statt stiller Snippet-Fallback."""

    def test_no_abstract_no_chunk_logs_warning(self, temp_vault_db, monkeypatch, caplog):
        from academic_vault import server

        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p_bare", "Retrieval systems", "")
        monkeypatch.setattr(server, "get_embedder", lambda *a, **kw: None)

        def _spy(query, candidates, voyage_api_key=None, cohere_api_key=None):
            for c in candidates:
                c["reranked"] = False
                c["reranker"] = "none"
            return candidates

        import academic_vault.retrieval as retrieval_module

        monkeypatch.setattr(retrieval_module, "apply_reranker", _spy)

        with caplog.at_level(logging.WARNING):
            results = server.search_papers(temp_vault_db, "retrieval", k=5, rerank=True)

        by_id = {r["paper_id"]: r for r in results}
        assert "p_bare" in by_id
        assert any("p_bare" in record.message for record in caplog.records), (
            "Fehlender besserer Text als das Snippet muss geloggt werden (AC5)"
        )
