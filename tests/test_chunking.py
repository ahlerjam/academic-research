"""Tests fuer das generische, seitenbewusste Chunking-Modul (Issue #374).

TDD: Tests zuerst (RED), dann academic_vault/chunking.py (GREEN).

AC -> Testklasse:
  AC1  TestChunkPdfProducesRequiredFields
  AC2  TestChunkSizeAndOverlap
  AC3  TestEmbeddingTextHasContext
  AC4  TestEdgeCases (Randfaelle, Div-by-zero/Off-by-one-Schutz)
"""

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "chunking"
FIXTURE_PDF = FIXTURES / "multi_section_paper.pdf"

# Aus tests/fixtures/chunking/create_fixtures.py: 6 Seiten, 1520 Body-Woerter
# insgesamt, TARGET_TOKENS=512 / OVERLAP_RATIO=0.125 -> vier Chunks:
#   [0:512), [448:960), [896:1408), [1344:1520)   (Wortindizes)
EXPECTED_TOTAL_WORDS = 1520


def _word_list(text: str) -> list[str]:
    return text.split()


class TestChunkPdfProducesMultipleChunksWithRequiredFields:
    """AC1: mehrere Chunks, page_start/page_end/section_title befuellt."""

    def test_produces_multiple_chunks(self):
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        assert len(chunks) > 1

    def test_every_chunk_has_valid_page_range(self):
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        for chunk in chunks:
            assert isinstance(chunk.page_start, int)
            assert isinstance(chunk.page_end, int)
            assert chunk.page_start >= 1
            assert chunk.page_end >= chunk.page_start

    def test_every_chunk_has_nonempty_section_title(self):
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        for chunk in chunks:
            assert isinstance(chunk.section_title, str)
            assert chunk.section_title.strip() != ""

    def test_section_titles_reflect_fixture_headings(self):
        """Die erkannten Section-Titel muessen (mind. teilweise) den echten
        Ueberschriften der Fixture entsprechen -- kein reiner Fallback-Dauerzustand."""
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        titles = {c.section_title for c in chunks}
        known_headings = {
            "Abstract",
            "1 Introduction",
            "2 Related Work",
            "3 Method",
            "4 Experiments",
            "5 Conclusion",
        }
        assert titles & known_headings, f"Keine bekannte Ueberschrift erkannt: {titles}"

    def test_chunk_index_is_sequential(self):
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


class TestChunkSizeAndOverlap:
    """AC2: ~512 Tokens Zielkorridor, 10-15% Overlap nachweisbar."""

    def test_chunk_size_within_target_corridor(self):
        from academic_vault.chunking import TARGET_TOKENS, chunk_pdf, count_tokens

        chunks = chunk_pdf(str(FIXTURE_PDF))
        assert len(chunks) >= 2
        # Alle Chunks ausser dem letzten muessen exakt die Zielgroesse treffen
        # (deterministisches Sliding-Window); der letzte darf kuerzer sein.
        for chunk in chunks[:-1]:
            size = count_tokens(chunk.chunk_text)
            assert size == TARGET_TOKENS, f"Chunk {chunk.chunk_index}: {size} != {TARGET_TOKENS}"
        last_size = count_tokens(chunks[-1].chunk_text)
        assert 0 < last_size <= TARGET_TOKENS

    def test_adjacent_chunks_overlap_10_to_15_percent(self):
        """Fuer jedes Nachbar-Chunk-Paar: gemeinsamer Wort-Suffix/Praefix-Anteil
        liegt im 10-15%-Korridor. Da alle Body-Woerter der Fixture global
        eindeutig sind (Wortstamm+Index), ist ein Match zweifelsfrei die
        tatsaechliche Ueberlappung -- kein Zufallstreffer durch Wiederholung."""
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        assert len(chunks) >= 2

        for i in range(len(chunks) - 1):
            words_a = _word_list(chunks[i].chunk_text)
            words_b = _word_list(chunks[i + 1].chunk_text)
            overlap = _shared_word_run(words_a, words_b)
            assert overlap > 0, f"Chunks {i}/{i + 1} ueberlappen gar nicht"
            ratio = overlap / len(words_a)
            assert 0.10 <= ratio <= 0.15, (
                f"Chunks {i}/{i + 1}: Overlap-Ratio {ratio:.3f} ausserhalb 10-15%"
            )

    def test_non_adjacent_chunks_do_not_share_words(self):
        """Chunk 0 und Chunk 2 (ueberspringt Chunk 1) duerfen sich nicht
        ueberlappen -- sonst waere das Sliding-Window kaputt."""
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        if len(chunks) < 3:
            return
        words_0 = set(_word_list(chunks[0].chunk_text))
        words_2 = set(_word_list(chunks[2].chunk_text))
        assert not (words_0 & words_2)


def _shared_word_run(words_a: list[str], words_b: list[str]) -> int:
    """Groesse des laengsten Suffixes von ``words_a``, der zugleich Praefix
    von ``words_b`` ist (0, wenn keine Ueberlappung besteht)."""
    max_check = min(len(words_a), len(words_b))
    for size in range(max_check, 0, -1):
        if words_a[-size:] == words_b[:size]:
            return size
    return 0


class TestEmbeddingTextHasContext:
    """AC3: jeder Chunk hat einen vorangestellten Kontextsatz im embedding_text."""

    def test_embedding_text_differs_from_chunk_text(self):
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        for chunk in chunks:
            assert chunk.embedding_text != chunk.chunk_text

    def test_context_sentence_is_nonempty(self):
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        for chunk in chunks:
            assert chunk.context_sentence.strip() != ""

    def test_context_sentence_precedes_chunk_text_in_embedding_text(self):
        from academic_vault.chunking import chunk_pdf

        chunks = chunk_pdf(str(FIXTURE_PDF))
        for chunk in chunks:
            assert chunk.context_sentence in chunk.embedding_text
            assert chunk.chunk_text in chunk.embedding_text
            assert chunk.embedding_text.index(chunk.context_sentence) < chunk.embedding_text.index(
                chunk.chunk_text
            )

    def test_default_context_sentence_is_deterministic_and_offline(self):
        """Ohne Provider (Default) liefert derselbe Aufruf denselben Kontextsatz
        -- kein API-Call, kein Netzwerk, kein Nichtdeterminismus."""
        from academic_vault.chunking import chunk_pdf

        chunks_a = chunk_pdf(str(FIXTURE_PDF))
        chunks_b = chunk_pdf(str(FIXTURE_PDF))
        assert [c.context_sentence for c in chunks_a] == [c.context_sentence for c in chunks_b]

    def test_custom_context_provider_is_used(self):
        """Ein injizierter context_provider ersetzt den Default vollstaendig."""
        from academic_vault.chunking import chunk_pdf

        def _fake_provider(chunk_text, section_title, chunk_index, page_start, page_end):
            return f"FAKE-CONTEXT-{chunk_index}"

        chunks = chunk_pdf(str(FIXTURE_PDF), context_provider=_fake_provider)
        for chunk in chunks:
            assert chunk.context_sentence == f"FAKE-CONTEXT-{chunk.chunk_index}"


class TestEdgeCases:
    """Randfaelle: sehr kurzes Dokument, Grenzfall an der Chunkgroesse,
    leerer Text -- keine Div-by-zero/Off-by-one-Fehler."""

    def test_empty_pages_produce_no_chunks(self):
        from academic_vault.chunking import chunk_pages

        assert chunk_pages([]) == []
        assert chunk_pages([(1, "")]) == []
        assert chunk_pages([(1, "   \n  ")]) == []

    def test_short_document_produces_single_chunk(self):
        """Dokument deutlich unter TARGET_TOKENS -> genau ein Chunk, keine
        Overlap-Berechnung noetig."""
        from academic_vault.chunking import chunk_pages

        text = " ".join(f"word{i}" for i in range(50))
        chunks = chunk_pages([(1, text)])
        assert len(chunks) == 1
        assert chunks[0].chunk_text == text
        assert chunks[0].page_start == 1
        assert chunks[0].page_end == 1

    def test_document_without_heading_gets_fallback_section_title(self):
        from academic_vault.chunking import DEFAULT_SECTION_TITLE, chunk_pages

        text = " ".join(f"word{i}" for i in range(50))
        chunks = chunk_pages([(1, text)])
        assert chunks[0].section_title == DEFAULT_SECTION_TITLE

    def test_document_exactly_at_target_size_produces_one_chunk(self):
        from academic_vault.chunking import TARGET_TOKENS, chunk_pages

        text = " ".join(f"word{i}" for i in range(TARGET_TOKENS))
        chunks = chunk_pages([(1, text)])
        assert len(chunks) == 1

    def test_document_one_word_over_target_produces_short_final_chunk(self):
        """TARGET_TOKENS+1 Woerter -> zweiter Chunk existiert und ist kurz,
        aber nicht leer/negativ (Off-by-one-Schutz)."""
        from academic_vault.chunking import TARGET_TOKENS, chunk_pages, count_tokens

        text = " ".join(f"word{i}" for i in range(TARGET_TOKENS + 1))
        chunks = chunk_pages([(1, text)])
        assert len(chunks) == 2
        assert count_tokens(chunks[0].chunk_text) == TARGET_TOKENS
        last_size = count_tokens(chunks[1].chunk_text)
        assert 0 < last_size < TARGET_TOKENS

    def test_multi_page_document_tracks_page_boundaries_correctly(self):
        from academic_vault.chunking import chunk_pages

        page1 = " ".join(f"a{i}" for i in range(30))
        page2 = " ".join(f"b{i}" for i in range(30))
        chunks = chunk_pages([(1, page1), (2, page2)])
        assert len(chunks) == 1
        assert chunks[0].page_start == 1
        assert chunks[0].page_end == 2

    def test_heading_line_is_detected_and_not_counted_as_body_word(self):
        from academic_vault.chunking import chunk_pages

        text = "1 Introduction\n" + " ".join(f"word{i}" for i in range(20))
        chunks = chunk_pages([(1, text)])
        assert len(chunks) == 1
        assert chunks[0].section_title == "1 Introduction"
        assert "Introduction" not in chunks[0].chunk_text.split()


class TestChunkPagesAcceptsExplicitContextProvider:
    """chunk_pages ist die Kernfunktion hinter chunk_pdf -- direkt testbar
    ohne PDF-Rundreise."""

    def test_chunk_pages_default_provider_produces_context(self):
        from academic_vault.chunking import chunk_pages

        text = " ".join(f"word{i}" for i in range(20))
        chunks = chunk_pages([(1, text)])
        assert chunks[0].context_sentence.strip() != ""
        assert chunks[0].embedding_text != chunks[0].chunk_text


class TestExtractPagesLogsCorruptedPage:
    """extract_pages() darf eine defekte Einzelseite nicht stillschweigend
    verschlucken: Verhalten (leerer String, kein Abbruch) bleibt gleich,
    aber der Fehler muss auf dem Produktionspfad geloggt werden (analog zu
    academic_vault/fulltext.py::extract_pypdf)."""

    def test_corrupted_page_logs_warning_and_keeps_empty_text(self, monkeypatch, caplog):
        import logging

        import pypdf
        from academic_vault.chunking import extract_pages

        class _BrokenPage:
            def extract_text(self):
                raise ValueError("defekte Einzelseite")

        class _FakeReader:
            def __init__(self, path):
                self.pages = [_BrokenPage()]

        monkeypatch.setattr(pypdf, "PdfReader", _FakeReader)

        with caplog.at_level(logging.WARNING, logger="academic_vault.chunking"):
            pages = extract_pages("dummy.pdf")

        assert pages == [(1, "")]
        assert any(
            record.levelno == logging.WARNING and "nicht extrahierbar" in record.message
            for record in caplog.records
        )
