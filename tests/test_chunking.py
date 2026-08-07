"""Tests fuer das generische, seitenbewusste Chunking-Modul (Issue #374).

TDD: Tests zuerst (RED), dann academic_vault/chunking.py (GREEN).

AC -> Testklasse:
  AC1  TestChunkPdfProducesRequiredFields
  AC2  TestChunkSizeAndOverlap
  AC3  TestEmbeddingTextHasContext
  AC4  TestEdgeCases (Randfaelle, Div-by-zero/Off-by-one-Schutz)
"""

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "chunking"
FIXTURE_PDF = FIXTURES / "multi_section_paper.pdf"

# Aus tests/fixtures/chunking/create_fixtures.py: 6 Seiten, 1520 Body-Woerter.
# Die Chunk-Grenzen sind NICHT mehr wortweise vorhersagbar: die Fenstergroesse
# ergibt sich aus dem Tokenbudget (TARGET_TOKENS) und der jeweiligen Textsorte.
EXPECTED_TOTAL_WORDS = 1520


def _word_list(text: str) -> list[str]:
    return text.split()


def _word_counter(text: str) -> int:
    """Zaehler mit "1 Token = 1 Wort" -- macht Budgetgrenzen wortgenau
    ansteuerbar, ohne Annahmen ueber das Subword-Splitting des echten
    Tokenizers zu treffen."""
    return len(text.split())


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
        """Kein Chunk darf das Tokenbudget ueberschreiten, und die Chunks vor
        dem letzten muessen es weitgehend ausnutzen.

        Exakte Gleichheit ist NICHT erreichbar (und war die falsche Zusicherung
        der wortbasierten Zaehlung): das Fenster endet an einer Wortgrenze, das
        letzte noch passende Wort kostet je nach Textsorte mehrere Tokens.
        """
        from academic_vault.chunking import TARGET_TOKENS, chunk_pdf, count_tokens

        chunks = chunk_pdf(str(FIXTURE_PDF))
        assert len(chunks) >= 2
        for chunk in chunks[:-1]:
            size = count_tokens(chunk.chunk_text)
            assert size <= TARGET_TOKENS, (
                f"Chunk {chunk.chunk_index}: {size} > TARGET_TOKENS={TARGET_TOKENS}"
            )
            assert size >= 0.9 * TARGET_TOKENS, (
                f"Chunk {chunk.chunk_index}: nur {size} von {TARGET_TOKENS} Tokens genutzt"
            )
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


# Realistischer deutscher Fliesstext: die Wort->Token-Spreizung des
# e5-Tokenizers (XLM-R-SentencePiece) liegt bei deutscher Wissenschaftsprosa
# gemessen bei ~2.4 Tokens/Wort, bei englischer Prosa bei ~1.7.
_GERMAN_PROSE = (
    "Die seitenbewusste Segmentierung wissenschaftlicher Volltexte erfordert eine "
    "nachvollziehbare Zuordnung von Seitenzahlen zu Textabschnitten, damit die "
    "Zitierfaehigkeit im Auditpfad erhalten bleibt und Belegstellen spaeter "
    "eindeutig rekonstruierbar sind. "
)


class TestChunkSizeIsMeasuredInModelTokens:
    """AC2 praezise: die Zielgroesse ist in MODELL-Tokens definiert, nicht in Woertern.

    Das Embedding-Backend (``intfloat/multilingual-e5-small``) hat ein hartes
    Kontextfenster von ``max_seq_length=512``. ``SentenceTransformer.encode``
    schneidet laengere Eingaben STILLSCHWEIGEND ab (kein Log, keine Exception) --
    ein Chunk jenseits des Fensters verliert seinen Schwanz ersatzlos aus dem
    Vektor. Eine wortbasierte Zaehlung kann diese Grenze nicht einhalten: der
    Tokenizer erzeugt je nach Textsorte 1.7 bis 38 Tokens pro Wort.
    """

    def test_chunks_respect_an_injected_subword_token_counter(self):
        """Ein injizierter Counter, der Subword-Splitting nachbildet (3 Tokens je
        Wort), muss die Fenstergroesse tatsaechlich steuern."""
        from academic_vault.chunking import TARGET_TOKENS, chunk_pages

        def _subword_counter(text: str) -> int:
            return 3 * len(text.split())

        text = " ".join(f"wort{i}" for i in range(2000))
        chunks = chunk_pages([(1, text)], token_counter=_subword_counter)

        assert len(chunks) > 1
        for chunk in chunks:
            size = _subword_counter(chunk.chunk_text)
            assert size <= TARGET_TOKENS, (
                f"Chunk {chunk.chunk_index} hat {size} Tokens > TARGET_TOKENS={TARGET_TOKENS}"
            )

    def test_embedding_text_stays_inside_the_model_context_window(self):
        """Nicht nur ``chunk_text``, sondern der komplette Embedding-Input
        (Kontextsatz + Chunk) muss in ``MODEL_MAX_TOKENS`` passen -- sonst
        schneidet das Modell genau den Chunk-Schwanz ab."""
        from academic_vault.chunking import MODEL_MAX_TOKENS, chunk_pages

        def _subword_counter(text: str) -> int:
            return 3 * len(text.split())

        text = " ".join(f"wort{i}" for i in range(2000))
        chunks = chunk_pages([(1, text)], token_counter=_subword_counter)

        for chunk in chunks:
            size = _subword_counter(chunk.embedding_text)
            assert size <= MODEL_MAX_TOKENS, (
                f"Chunk {chunk.chunk_index}: embedding_text hat {size} Tokens "
                f"> MODEL_MAX_TOKENS={MODEL_MAX_TOKENS}"
            )

    def test_default_counter_keeps_german_prose_inside_the_window(self):
        """Deutscher Fliesstext ist der Regelfall dieses Repos -- mit der
        wortbasierten Zaehlung ergaben 512 Woerter gemessene ~1200 e5-Tokens."""
        from academic_vault.chunking import (
            MODEL_MAX_TOKENS,
            TARGET_TOKENS,
            chunk_pages,
            count_tokens,
        )

        chunks = chunk_pages([(1, _GERMAN_PROSE * 120)])
        assert len(chunks) > 1
        for chunk in chunks:
            assert count_tokens(chunk.chunk_text) <= TARGET_TOKENS
            assert count_tokens(chunk.embedding_text) <= MODEL_MAX_TOKENS

    def test_target_tokens_reserves_room_for_the_context_sentence(self):
        """``TARGET_TOKENS`` ist das Budget fuer ``chunk_text`` ALLEIN; der
        Kontextsatz kommt obendrauf und muss reserviert sein."""
        from academic_vault.chunking import (
            CONTEXT_TOKEN_RESERVE,
            MODEL_MAX_TOKENS,
            TARGET_TOKENS,
        )

        assert CONTEXT_TOKEN_RESERVE > 0
        assert TARGET_TOKENS == MODEL_MAX_TOKENS - CONTEXT_TOKEN_RESERVE
        assert TARGET_TOKENS < MODEL_MAX_TOKENS

    def test_single_word_over_budget_still_makes_progress_and_warns(self, caplog):
        """Ein einzelnes Wort kann das Budget sprengen (lange URL, Summenformel).
        Der Chunker darf dann weder haengen noch das Wort stillschweigend
        verschlucken -- er muss Fortschritt machen UND die unvermeidliche
        Modell-Kuerzung sichtbar loggen."""
        import logging

        from academic_vault.chunking import chunk_pages

        def _subword_counter(text: str) -> int:
            return sum(len(word) for word in text.split())

        monster = "x" * 5000
        text = f"vorher {monster} nachher"

        with caplog.at_level(logging.WARNING, logger="academic_vault.chunking"):
            chunks = chunk_pages([(1, text)], token_counter=_subword_counter)

        assert chunks, "Kein Chunk erzeugt -- Fortschritt verloren"
        all_words = [word for chunk in chunks for word in chunk.chunk_text.split()]
        assert monster in all_words, "Ueberlanges Wort stillschweigend verschluckt"
        assert any(
            record.levelno == logging.WARNING and "Kontextfenster" in record.message
            for record in caplog.records
        ), "Modell-Kuerzung wurde nicht geloggt (stillschweigender Verlust)"


class TestApproximateTokenCountIsHonestlyLabelled:
    """Ohne echten Tokenizer bleibt nur eine Naeherung -- sie muss als solche
    benannt sein und darf nicht mehr versprechen als sie halten kann."""

    def test_approximation_scales_with_characters_not_only_words(self):
        """Ein langes Kompositum ist EIN Wort, aber viele Subword-Tokens."""
        from academic_vault.chunking import approximate_token_count

        one_short = approximate_token_count("Haus")
        one_long = approximate_token_count(
            "Rindfleischetikettierungsueberwachungsaufgabenuebertragungsgesetz"
        )
        assert one_long > one_short

    def test_approximation_is_monotone_when_words_are_appended(self):
        """Die Fenstersuche setzt Monotonie voraus."""
        from academic_vault.chunking import approximate_token_count

        words = _GERMAN_PROSE.split()
        counts = [approximate_token_count(" ".join(words[:i])) for i in range(1, len(words) + 1)]
        assert counts == sorted(counts)


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
        """Off-by-one an der Budgetgrenze. Der Zaehler wird bewusst auf
        "1 Token = 1 Wort" fixiert, damit der Grenzfall wortgenau ansteuerbar
        ist -- ohne Annahme darueber, wie der echte Tokenizer splittet."""
        from academic_vault.chunking import TARGET_TOKENS, chunk_pages

        text = " ".join(f"word{i}" for i in range(TARGET_TOKENS))
        chunks = chunk_pages([(1, text)], token_counter=_word_counter)
        assert len(chunks) == 1

    def test_document_one_word_over_target_produces_short_final_chunk(self):
        """TARGET_TOKENS+1 Tokens -> zweiter Chunk existiert und ist kurz,
        aber nicht leer/negativ (Off-by-one-Schutz)."""
        from academic_vault.chunking import TARGET_TOKENS, chunk_pages

        text = " ".join(f"word{i}" for i in range(TARGET_TOKENS + 1))
        chunks = chunk_pages([(1, text)], token_counter=_word_counter)
        assert len(chunks) == 2
        assert _word_counter(chunks[0].chunk_text) == TARGET_TOKENS
        last_size = _word_counter(chunks[1].chunk_text)
        assert 0 < last_size < TARGET_TOKENS

    def test_multi_page_document_tracks_page_boundaries_correctly(self):
        from academic_vault.chunking import chunk_pages

        page1 = " ".join(f"a{i}" for i in range(30))
        page2 = " ".join(f"b{i}" for i in range(30))
        chunks = chunk_pages([(1, page1), (2, page2)])
        assert len(chunks) == 1
        assert chunks[0].page_start == 1
        assert chunks[0].page_end == 2

    def test_heading_line_is_detected_and_still_part_of_the_body(self):
        """Eine Ueberschrift setzt den ``section_title`` UND bleibt im Chunk-Text.

        Die Heading-Erkennung ist eine reine Metadaten-Annotation: sie darf
        Zeilen markieren, aber niemals aus dem Wortstrom entfernen (siehe
        :class:`TestHeadingHeuristicIsNonDestructive`)."""
        from academic_vault.chunking import chunk_pages

        text = "1 Introduction\n" + " ".join(f"word{i}" for i in range(20))
        chunks = chunk_pages([(1, text)])
        assert len(chunks) == 1
        assert chunks[0].section_title == "1 Introduction"
        assert chunks[0].chunk_text.split()[:2] == ["1", "Introduction"]


class TestHeadingHeuristicIsNonDestructive:
    """Die Heading-Heuristik darf NIE Inhalt verschlucken.

    Sie ist zwangslaeufig unscharf: PDF-Textextraktion bricht Zeilen nach
    Layout, weshalb ganz normale Fliesstext-Zeilen aus ein bis zwei
    grossgeschriebenen Woertern ohne Satzzeichen bestehen koennen ("Smith",
    "However", "Deep Learning" -- Absatzende, umbrochener Eigenname,
    Literaturliste). Ein False Positive darf deshalb hoechstens das Label
    ``section_title`` verfaelschen, niemals Woerter aus dem Retrieval-Body
    entfernen: verlorener Text ist in keinem spaeteren Schritt rekonstruierbar.
    """

    def test_false_positive_lines_keep_their_words_in_the_body(self):
        from academic_vault.chunking import chunk_pages

        text = (
            "Die Ergebnisse wurden mehrfach repliziert, unter anderem von\n"
            "Smith\n"
            "und Kollegen im selben Zeitraum. Der Effekt blieb stabil.\n"
            "However\n"
            "the sample size remained small. Vergleiche dazu auch\n"
            "Deep Learning\n"
            "als methodischen Gegenentwurf.\n"
        )
        body = chunk_pages([(1, text)])[0].chunk_text.split()
        for token in ("Smith", "However", "Deep", "Learning"):
            assert token in body, f"'{token}' wurde stillschweigend verworfen: {body}"

    def test_every_input_word_survives_into_the_chunk_stream(self):
        """Verlustfreiheit als Invariante: der aus den Chunks rekonstruierte
        Wortstrom ist exakt der Eingabe-Wortstrom -- inklusive aller Zeilen,
        welche die Heuristik (zu Recht oder zu Unrecht) als Heading einstuft."""
        from academic_vault.chunking import chunk_pages

        lines = ["1 Introduction"]
        for i in range(600):
            lines.append(f"word{i}")
            if i % 97 == 0:
                # Zeilen, die wie eine Ueberschrift aussehen, aber Fliesstext sind.
                lines.append(f"However{i}")
        text = "\n".join(lines)
        expected = text.split()

        chunks = chunk_pages([(1, text)])
        assert len(chunks) > 1, "Testdokument muss mehrere Chunks erzeugen"

        reconstructed = chunks[0].chunk_text.split()
        for previous, current in zip(chunks, chunks[1:], strict=False):
            overlap = _shared_word_run(previous.chunk_text.split(), current.chunk_text.split())
            reconstructed.extend(current.chunk_text.split()[overlap:])
        assert reconstructed == expected

    def test_false_positive_only_affects_the_section_label(self):
        """Ein False Positive bleibt folgenlos fuer den Inhalt und wirkt sich
        ausschliesslich auf das Metadatenfeld ``section_title`` aus."""
        from academic_vault.chunking import chunk_pages

        text = "1 Introduction\nSmith\n" + " ".join(f"word{i}" for i in range(20))
        chunks = chunk_pages([(1, text)])
        assert len(chunks) == 1
        assert chunks[0].section_title == "1 Introduction"
        assert chunks[0].chunk_text.split()[:3] == ["1", "Introduction", "Smith"]


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


class TestDefaultContextSentenceWithPaperMeta:
    """Issue #701: Kontextsatz mit echten Paper-Metadaten statt Boilerplate."""

    def test_full_metadata_is_included_verbatim(self):
        """AC1/AC4: Titel, Erstautor (>=3 Autoren -> 'et al.') und Jahr im Satz."""
        from academic_vault.chunking import PaperMeta, default_context_sentence

        sentence = default_context_sentence(
            "Introduction",
            2,
            3,
            4,
            paper_meta=PaperMeta(
                title="Attention Is All You Need",
                authors=["Vaswani", "Shazeer", "Parmar"],
                year=2017,
            ),
        )
        assert sentence == (
            'Dieser Abschnitt stammt aus "Attention Is All You Need" '
            'von Vaswani et al. (2017), Abschnitt "Introduction" '
            "(Seite 3-4, Chunk 2)."
        )

    def test_missing_metadata_falls_back_without_raising(self):
        """AC2/AC4: fehlende Metadaten -> kein Abbruch, Sektions-/Seiten-Teil bleibt."""
        from academic_vault.chunking import PaperMeta, default_context_sentence

        sentence = default_context_sentence(
            "Introduction", 2, 3, 4, paper_meta=PaperMeta(title=None, authors=None, year=None)
        )
        assert sentence == default_context_sentence("Introduction", 2, 3, 4)
        assert 'Abschnitt "Introduction"' not in sentence  # unveraendertes Basisformat
        assert '"Introduction"' in sentence
        assert "(Seite 3-4, Chunk 2)." in sentence

    def test_missing_title_and_year_keeps_authors_and_section(self):
        """AC2: Titel unbekannt, kein Jahr -> Satz ohne diese Teile, kein Absturz."""
        from academic_vault.chunking import PaperMeta, default_context_sentence

        sentence = default_context_sentence(
            "Introduction",
            0,
            1,
            1,
            paper_meta=PaperMeta(title=None, authors=["Müller"], year=None),
        )
        assert sentence == (
            'Dieser Abschnitt stammt von Müller, Abschnitt "Introduction" (Seite 1-1, Chunk 0).'
        )

    def test_two_authors_are_joined_with_und(self):
        from academic_vault.chunking import PaperMeta, default_context_sentence

        sentence = default_context_sentence(
            "Intro", 0, 1, 1, paper_meta=PaperMeta(title=None, authors=["A", "B"], year=None)
        )
        assert "von A und B" in sentence

    def test_chunk_pages_accepts_optional_paper_meta(self):
        """AC3: chunk_pages() akzeptiert Paper-Metadaten als optionales Argument."""
        from academic_vault.chunking import PaperMeta, chunk_pages

        text = " ".join(f"word{i}" for i in range(50))
        chunks = chunk_pages(
            [(1, text)], paper_meta=PaperMeta(title="Ein Titel", authors=["Autor"], year=2020)
        )
        assert len(chunks) == 1
        assert "Ein Titel" in chunks[0].context_sentence

    def test_chunk_pages_without_paper_meta_argument_is_unchanged(self):
        """AC3: bestehende Aufrufe ohne paper_meta funktionieren unveraendert weiter."""
        from academic_vault.chunking import chunk_pages

        text = " ".join(f"word{i}" for i in range(50))
        chunks = chunk_pages([(1, text)])
        assert len(chunks) == 1
        assert (
            chunks[0].context_sentence
            == chunk_pages([(1, text)], paper_meta=None)[0].context_sentence
        )


@pytest.mark.skipif(
    os.environ.get("VAULT_E5_LIVE_TEST") != "1",
    reason="Live-Tokenizer-Test nur mit VAULT_E5_LIVE_TEST=1 (laedt e5-Tokenizer)",
)
class TestRealE5TokenizerRespectsContextWindow:
    """Der eigentliche Beweis fuer AC2 -- gegen den ECHTEN e5-Tokenizer.

    In der CI blockiert tests/conftest.py den Tokenizer-Download (hermetische
    Suite), deshalb ist dieser Test wie der Live-Modelltest in
    tests/test_vault_embeddings_ingest.py per VAULT_E5_LIVE_TEST=1 gegated.
    """

    def _tokenizer(self):
        from academic_vault.embedding_model import DEFAULT_MODEL_ID

        transformers = pytest.importorskip("transformers")
        return transformers.AutoTokenizer.from_pretrained(DEFAULT_MODEL_ID)

    def test_embedding_text_fits_the_real_context_window(self):
        from academic_vault.chunking import MODEL_MAX_TOKENS, chunk_pages, reset_token_counter_cache
        from academic_vault.embedding_model import PASSAGE_PREFIX

        reset_token_counter_cache()
        tokenizer = self._tokenizer()
        chunks = chunk_pages([(1, _GERMAN_PROSE * 120)])
        assert len(chunks) > 1

        for chunk in chunks:
            # Genau das, was E5SmallEmbedder.embed_documents an das Modell gibt.
            model_input = PASSAGE_PREFIX + chunk.embedding_text
            size = len(tokenizer.encode(model_input))
            assert size <= MODEL_MAX_TOKENS, (
                f"Chunk {chunk.chunk_index}: {size} e5-Tokens > {MODEL_MAX_TOKENS} -- "
                "sentence-transformers wuerde den Rest stillschweigend abschneiden"
            )

    def test_embedding_text_with_paper_meta_fits_the_real_context_window(self):
        """AC5: embedding_text (Kontextsatz inkl. Paper-Metadaten + Chunk) bleibt
        im 512-Token-Fenster -- nachgewiesen mit dem echten Tokenizer."""
        from academic_vault.chunking import (
            MODEL_MAX_TOKENS,
            PaperMeta,
            chunk_pages,
            reset_token_counter_cache,
        )
        from academic_vault.embedding_model import PASSAGE_PREFIX

        reset_token_counter_cache()
        tokenizer = self._tokenizer()
        paper_meta = PaperMeta(
            title="DevOps-Governance im Mittelstand",
            authors=["Ahler"],
            year=2024,
        )
        chunks = chunk_pages([(1, _GERMAN_PROSE * 120)], paper_meta=paper_meta)
        assert len(chunks) > 1

        for chunk in chunks:
            model_input = PASSAGE_PREFIX + chunk.embedding_text
            size = len(tokenizer.encode(model_input))
            assert size <= MODEL_MAX_TOKENS, (
                f"Chunk {chunk.chunk_index}: {size} e5-Tokens > {MODEL_MAX_TOKENS} -- "
                "sentence-transformers wuerde den Rest stillschweigend abschneiden"
            )

    def test_word_based_window_would_blow_the_context_window(self):
        """Gegenprobe: die urspruengliche wortbasierte Zaehlung (512 Woerter)
        sprengt bei demselben Text das Fenster messbar.

        Ohne diesen Nachweis koennte der Test oben auch von einer beliebig
        konservativen Naeherung erfuellt werden -- er hat also Zaehne.
        """
        from academic_vault.chunking import MODEL_MAX_TOKENS, chunk_pages, reset_token_counter_cache
        from academic_vault.embedding_model import PASSAGE_PREFIX

        reset_token_counter_cache()
        tokenizer = self._tokenizer()
        chunks = chunk_pages(
            [(1, _GERMAN_PROSE * 120)],
            target_tokens=512,
            token_counter=lambda text: len(text.split()),
        )
        worst = max(len(tokenizer.encode(PASSAGE_PREFIX + c.embedding_text)) for c in chunks)
        assert worst > MODEL_MAX_TOKENS, (
            f"Wortbasierte Zaehlung ergab nur {worst} Tokens -- Gegenprobe untauglich"
        )

    def test_chunks_use_most_of_the_available_budget(self):
        """Gegenprobe zur Sicherheitsgrenze: die Chunks duerfen nicht so
        konservativ werden, dass das Fenster verschenkt wird."""
        from academic_vault.chunking import TARGET_TOKENS, chunk_pages, reset_token_counter_cache

        reset_token_counter_cache()
        tokenizer = self._tokenizer()
        chunks = chunk_pages([(1, _GERMAN_PROSE * 120)])

        for chunk in chunks[:-1]:
            size = len(tokenizer.tokenize(chunk.chunk_text))
            assert size >= 0.9 * TARGET_TOKENS, (
                f"Chunk {chunk.chunk_index}: nur {size} von {TARGET_TOKENS} Tokens genutzt"
            )
