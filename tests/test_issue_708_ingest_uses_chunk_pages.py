"""Der produktive Ingest chunkt ueber ``chunk_pages`` — nicht ueber ein Zeichenfenster (#708).

Warum ein eigenes Modul: das Goldset aus #708 misst Chunks, die
``chunking.chunk_pages()`` mit Kontextsatz und ``passage: ``-Praefix erzeugt hat.
Diese Messung ist nur dann eine Aussage ueber den Betrieb, wenn der
Auto-Ingest-Pfad (``server.add_paper`` -> ``_maybe_ingest_embeddings`` ->
``ingest.ingest_paper_embeddings``) dieselben Chunks erzeugt. Bis #708 tat er
das nicht: er zerlegte ueber den ``split_text``-Platzhalter aus #372 in
1600-Zeichen-Fenster und schrieb ``context_sentence=""`` — also andere
Chunkgrenzen UND einen anderen Embedding-Input als das Goldset.

Die Tests hier pinnen die Gleichheit an der Stelle fest, an der sie zaehlt:
was ``ingest_paper_embeddings`` in ``chunk_embeddings`` schreibt und was es dem
Embedder zum Einbetten gibt.

Der eine verbleibende Unterschied zum Goldset ist die Seitenzahl im
Kontextsatz: der Ingest-Text stammt aus ``papers_fts.fulltext``, das seit #373
bewusst keine Seitengrenzen mehr traegt, also ist er genau eine Seite. Diese
Grenze wird von ``TestPageFramingIsTheOnlyRemainingDelta`` vermessen statt
behauptet.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

SOURCES_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "retrieval_goldset_chunks_708" / "sources.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str) -> None:
    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


def _use_embedder(monkeypatch, embedder) -> None:
    monkeypatch.setattr("academic_vault.ingest.get_embedder", lambda *_a, **_kw: embedder)
    monkeypatch.setattr("academic_vault.server.get_embedder", lambda *_a, **_kw: embedder)


def _set_fulltext(db_path: str, paper_id: str, text: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE papers_fts SET fulltext = ? WHERE paper_id = ?", (text, paper_id))
    conn.commit()
    conn.close()


class _RecordingEmbedder:
    """Deterministischer Embedder, der die eingebetteten Texte mitschreibt."""

    dim = 384
    model_id = "test/recording"

    def __init__(self, inner):
        self._inner = inner
        self.document_texts: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_texts.extend(texts)
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)


@pytest.fixture(scope="module")
def source_document() -> dict:
    """Ein echtes Goldset-Quelldokument — mehrseitig, mit Ueberschriften."""
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    return sources["documents"][0]


@pytest.fixture
def ingested(temp_vault_db, fake_embedder, monkeypatch, source_document):
    """Fuehrt den produktiven Ingest ueber einen Goldset-Volltext aus.

    Gibt ``(rows, flat_text, embedder)`` zurueck: die geschriebenen
    ``chunk_embeddings``-Zeilen in Schreibreihenfolge, den eingebetteten Text
    und den mitschreibenden Embedder.
    """
    from academic_vault.db import VaultDB
    from academic_vault.ingest import ingest_paper_embeddings

    monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
    _add_paper(temp_vault_db, "p708", "Change Approval", "Abstract")

    flat_text = "\n".join(text for _number, text in source_document["pages"])
    _set_fulltext(temp_vault_db, "p708", flat_text)

    recorder = _RecordingEmbedder(fake_embedder)
    _use_embedder(monkeypatch, recorder)

    written = ingest_paper_embeddings(temp_vault_db, "p708", max_chunks=0)
    assert written > 1, "Der Testtext muss mehrere Chunks ergeben, sonst prueft nichts"

    rows = VaultDB(temp_vault_db).get_chunk_embeddings("p708")
    assert len(rows) == written
    return rows, flat_text, recorder


# ---------------------------------------------------------------------------
# AC1: derselbe Chunk-Weg wie im Goldset
# ---------------------------------------------------------------------------


class TestIngestChunksViaChunkPages:
    def test_written_chunks_are_exactly_chunk_pages_output(self, ingested):
        """chunk_text/context_sentence/embedding_text == chunk_pages([(1, text)]).

        Der Test faellt, solange der Ingest ueber ein Zeichenfenster zerlegt:
        ``split_text`` schneidet nach 1600 Zeichen, ``chunk_pages`` nach
        Modell-Tokens — die Grenzen liegen zwangslaeufig woanders.
        """
        from academic_vault.chunking import PaperMeta, chunk_pages

        rows, flat_text, _ = ingested
        # Der Ingest baut PaperMeta aus dem CSL-JSON des Papers (#701) --
        # "Change Approval"/"Abstract" aus ``_add_paper`` traegt keine
        # Autoren/kein Jahr, also nur der Titel.
        expected = chunk_pages([(1, flat_text)], paper_meta=PaperMeta(title="Change Approval"))

        assert [r["chunk_text"] for r in rows] == [c.chunk_text for c in expected]
        assert [r["context_sentence"] for r in rows] == [c.context_sentence for c in expected]
        assert [r["embedding_text"] for r in rows] == [c.embedding_text for c in expected]

    def test_context_sentence_is_persisted_and_not_empty(self, ingested):
        """Jeder Chunk traegt den deterministischen Kontextsatz aus #374.

        Bis #708 stand hier durchgehend ``""`` — das Goldset misst aber
        Embeddings, in deren Input der Kontextsatz steckt.
        """
        from academic_vault.chunking import PaperMeta, default_context_sentence

        rows, _, _ = ingested
        assert all(r["context_sentence"].strip() for r in rows)
        for index, row in enumerate(rows):
            # Format seit #701: '...aus "<Titel>", Abschnitt "<Sektion>" (...)'.
            section_title = row["context_sentence"].split('"')[3]
            assert row["context_sentence"] == default_context_sentence(
                section_title, index, 1, 1, paper_meta=PaperMeta(title="Change Approval")
            )

    def test_embedder_sees_context_plus_chunk(self, ingested):
        """Eingebettet wird der kontextualisierte Text, nicht der nackte Chunk."""
        from academic_vault.embeddings import build_contextual_embedding_text

        rows, _, recorder = ingested
        assert recorder.document_texts == [r["embedding_text"] for r in rows]
        for row in rows:
            assert row["embedding_text"] == build_contextual_embedding_text(
                row["context_sentence"], row["chunk_text"]
            )

    def test_chunk_pages_is_the_chunker_the_ingest_calls(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        """Regressionsanker: der Ingest ruft ``chunking.chunk_pages`` auf.

        Ohne diesen Anker koennte ein spaeterer Umbau die drei Feldwerte oben
        nachbilden, ohne noch dieselbe Funktion zu benutzen — dann waere die
        Goldset-Aussage wieder nur behauptet.
        """
        import academic_vault.chunking as chunking
        from academic_vault.ingest import ingest_paper_embeddings

        calls: list[list[tuple[int, str]]] = []
        real = chunking.chunk_pages

        def _spy(pages, *args, **kwargs):
            calls.append(list(pages))
            return real(pages, *args, **kwargs)

        monkeypatch.setattr(chunking, "chunk_pages", _spy)
        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        _add_paper(temp_vault_db, "p001", "Titel", "Abstract")
        _use_embedder(monkeypatch, fake_embedder)

        ingest_paper_embeddings(temp_vault_db, "p001", text="Ein kurzer Volltext.")

        assert calls == [[(1, "Ein kurzer Volltext.")]]

    def test_no_character_window_chunker_remains(self):
        """``split_text`` ist der Platzhalter aus #372 und darf nicht zurueckkehren.

        Der Modul-Docstring von #372 hat den Ersatz durch #374 angekuendigt; er
        blieb sieben Issues lang aus. Ein Test statt einer Absichtserklaerung.
        """
        import academic_vault.ingest as ingest

        assert not hasattr(ingest, "split_text")


# ---------------------------------------------------------------------------
# Issue #701: der Ingest baut PaperMeta aus dem CSL-JSON und reicht sie durch
# ---------------------------------------------------------------------------


class TestIngestPassesPaperMetaFromCsl:
    def test_context_sentence_carries_title_authors_and_year_from_csl(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        """AC1: Titel, Erstautor/"et al." und Jahr stammen aus dem CSL-JSON des Papers."""
        from academic_vault.chunking import PaperMeta, default_context_sentence
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings
        from academic_vault.server import add_paper

        csl = {
            "type": "article-journal",
            "title": "Attention Is All You Need",
            "author": [
                {"family": "Vaswani"},
                {"family": "Shazeer"},
                {"family": "Parmar"},
            ],
            "issued": {"date-parts": [[2017]]},
        }
        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        add_paper(temp_vault_db, "p701", json.dumps(csl))
        _use_embedder(monkeypatch, fake_embedder)

        written = ingest_paper_embeddings(
            temp_vault_db, "p701", text="Ein kurzer Volltext fuer den Test."
        )
        assert written == 1

        rows = VaultDB(temp_vault_db).get_chunk_embeddings("p701")
        assert len(rows) == 1
        expected = default_context_sentence(
            "Unbenannter Abschnitt",
            0,
            1,
            1,
            paper_meta=PaperMeta(
                title="Attention Is All You Need",
                authors=["Vaswani", "Shazeer", "Parmar"],
                year=2017,
            ),
        )
        assert rows[0]["context_sentence"] == expected
        assert '"Attention Is All You Need"' in rows[0]["context_sentence"]
        assert "Vaswani et al." in rows[0]["context_sentence"]
        assert "(2017)" in rows[0]["context_sentence"]

    def test_missing_csl_metadata_does_not_crash_ingest(
        self, temp_vault_db, fake_embedder, monkeypatch
    ):
        """AC2: unvollstaendiges CSL-JSON (kein Titel/kein Jahr) -> kein Absturz."""
        from academic_vault.db import VaultDB
        from academic_vault.ingest import ingest_paper_embeddings
        from academic_vault.server import add_paper

        csl = {"type": "article-journal"}
        monkeypatch.setenv("VAULT_AUTO_EMBED", "0")
        add_paper(temp_vault_db, "p701b", json.dumps(csl))
        _use_embedder(monkeypatch, fake_embedder)

        written = ingest_paper_embeddings(
            temp_vault_db, "p701b", text="Ein weiterer kurzer Volltext."
        )
        assert written == 1

        rows = VaultDB(temp_vault_db).get_chunk_embeddings("p701b")
        assert rows[0]["context_sentence"].strip()


# ---------------------------------------------------------------------------
# Die verbleibende Differenz zum Goldset, vermessen statt behauptet
# ---------------------------------------------------------------------------


class TestPageFramingIsTheOnlyRemainingDelta:
    def test_flat_text_changes_only_the_page_range_in_the_context_sentence(self, source_document):
        """Ein-Seiten-Rahmen (Ingest) vs. Seitenrahmen (Goldset): gleicher Text.

        Der Ingest-Volltext stammt aus ``papers_fts.fulltext`` und traegt seit
        #373 keine Seitengrenzen mehr, ist also genau eine Seite. Belegt wird
        hier, dass das ausschliesslich die Seitenangabe im Kontextsatz
        verschiebt — Chunkgrenzen, Section-Titel und Chunk-Index bleiben
        identisch. ``page_start``/``page_end`` landen ohnehin in keiner Spalte
        von ``chunk_embeddings``.
        """
        from academic_vault.chunking import chunk_pages

        pages = [(int(number), text) for number, text in source_document["pages"]]
        assert len({p for p, _ in pages}) > 1, "Fixture muss mehrseitig sein"

        paged = chunk_pages(pages)
        flat = chunk_pages([(1, "\n".join(text for _n, text in pages))])

        assert [c.chunk_text for c in flat] == [c.chunk_text for c in paged]
        assert [c.section_title for c in flat] == [c.section_title for c in paged]
        assert [c.chunk_index for c in flat] == [c.chunk_index for c in paged]

        # Einzige Abweichung: der Seitenbereich im Kontextsatz.
        for flat_chunk, paged_chunk in zip(flat, paged, strict=True):
            assert (
                flat_chunk.context_sentence.split(" (Seite ")[0]
                == (paged_chunk.context_sentence.split(" (Seite ")[0])
            )
            assert (flat_chunk.page_start, flat_chunk.page_end) == (1, 1)
