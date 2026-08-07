"""Chunking an GROBID-Sektionsgrenzen statt am Title-Case-Regex (Issue #709).

TDD: Tests zuerst (RED), dann academic_vault/fulltext.py + chunking.py (GREEN).

AK -> Testklasse:
  AK1  TestSectionTitlesComeFromTei
  AK2  TestWithoutGrobidUrlNothingChanges
  AK3  TestChunksPreferParagraphBoundaries
  AK4  TestTeiFixtureCoversGrobidPathWithoutServer
  AK5  TestOversizedSectionSplitsWithOverlap

Alle Tests laufen ohne GROBID-Server: der HTTP-Aufruf wird gemockt (Muster aus
tests/test_issue_373_fulltext.py), die TEI-Antwort kommt aus der Repo-Fixture
``tests/fixtures/chunking/grobid_tei_sample.xml``.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "chunking"
FIXTURE_PDF = FIXTURES / "multi_section_paper.pdf"
FIXTURE_TEI = FIXTURES / "grobid_tei_sample.xml"

# Aus tests/fixtures/chunking/create_fixtures.py -- hier dupliziert, damit der
# Test die Erwartung benennt statt sie aus dem Generator zu importieren.
HEAD_MISSED_BY_REGEX = "3.1 Effekte auf die Governance-Praxis, ein Ueberblick"
REGEX_FALSE_POSITIVE = "However"
OVERSIZED_HEAD = "4 Ergebnisse der Fallstudie"
OVERSIZED_WORDS = 1519
BACK_MARKER = "Literaturverzeichnismarker"
ALL_TEI_HEADS = {"Abstract", HEAD_MISSED_BY_REGEX, OVERSIZED_HEAD, "5 Fazit"}


def _word_counter(text: str) -> int:
    """1 Token = 1 Wort -- macht Budgetgrenzen wortgenau ansteuerbar
    (gleicher Zaehler wie in tests/test_chunking.py)."""
    return len(text.split())


def _shared_word_run(words_a: list[str], words_b: list[str]) -> int:
    """Laengster Suffix von ``words_a``, der zugleich Praefix von ``words_b`` ist."""
    for size in range(min(len(words_a), len(words_b)), 0, -1):
        if words_a[-size:] == words_b[:size]:
            return size
    return 0


def _tei_text() -> str:
    return FIXTURE_TEI.read_text(encoding="utf-8")


def _sections():
    from academic_vault.fulltext import parse_tei_sections

    return parse_tei_sections(_tei_text())


class _Response:
    status_code = 200

    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _mock_grobid(monkeypatch, tei: str, captured: dict | None = None) -> None:
    """Ersetzt httpx.post durch eine Antwort aus der Fixture (kein Server noetig)."""
    from academic_vault import fulltext as fulltext_mod

    def _fake_post(url, **kwargs):
        if captured is not None:
            captured["url"] = url
            captured["data"] = kwargs.get("data")
            captured["files"] = kwargs.get("files")
        return _Response(tei)

    monkeypatch.setattr(fulltext_mod.httpx, "post", _fake_post)
    monkeypatch.setenv(fulltext_mod.ENV_GROBID_URL, "http://localhost:8070")


class TestSectionTitlesComeFromTei:
    """AK1: mit ``GROBID_URL`` stammen ``section_title`` und Grenzen aus dem TEI."""

    def test_regex_heuristic_misses_the_real_head_and_invents_a_fake_one(self):
        """Belegt die Ausgangslage: der Regex verliert die echte Ueberschrift
        und haelt ein umbrochenes Fliesstext-Wort fuer eine."""
        from academic_vault.chunking import _detect_heading

        assert _detect_heading(HEAD_MISSED_BY_REGEX) is None
        assert _detect_heading(REGEX_FALSE_POSITIVE) == REGEX_FALSE_POSITIVE

    def test_regex_path_labels_the_false_positive_as_section_title(self):
        """Kontrast-Haelfte 1: derselbe Text seitenweise -> Regex-Label."""
        from academic_vault.chunking import chunk_pages

        chunks = chunk_pages(_regex_pages(), target_tokens=20, token_counter=_word_counter)
        titles = {c.section_title for c in chunks}
        assert REGEX_FALSE_POSITIVE in titles
        assert HEAD_MISSED_BY_REGEX not in titles

    def test_tei_path_labels_the_real_head_as_section_title(self):
        """Kontrast-Haelfte 2: derselbe Text als TEI-Sektion -> echter Head."""
        from academic_vault.chunking import chunk_sections
        from academic_vault.fulltext import TeiParagraph, TeiSection

        section = TeiSection(
            title=HEAD_MISSED_BY_REGEX,
            paragraphs=[TeiParagraph(text=_regex_paragraph_text(), page=1)],
        )
        chunks = chunk_sections([section], target_tokens=20, token_counter=_word_counter)
        titles = {c.section_title for c in chunks}
        assert titles == {HEAD_MISSED_BY_REGEX}
        assert REGEX_FALSE_POSITIVE not in titles

    def test_chunk_pdf_with_grobid_url_uses_tei_heads(self, monkeypatch):
        from academic_vault.chunking import chunk_pdf

        _mock_grobid(monkeypatch, _tei_text())
        chunks = chunk_pdf(str(FIXTURE_PDF), token_counter=_word_counter)

        titles = {c.section_title for c in chunks}
        assert titles == ALL_TEI_HEADS, f"Unerwartete Titel: {titles}"

    def test_chunk_pdf_with_grobid_url_ignores_the_pypdf_headings(self, monkeypatch):
        """Die PDF-Ueberschriften ("1 Introduction" ...) duerfen im GROBID-Pfad
        nirgends auftauchen -- sonst wurde doch der Regex-Pfad gefahren."""
        from academic_vault.chunking import chunk_pdf

        _mock_grobid(monkeypatch, _tei_text())
        titles = {c.section_title for c in chunk_pdf(str(FIXTURE_PDF), token_counter=_word_counter)}
        assert "1 Introduction" not in titles
        assert "5 Conclusion" not in titles

    def test_grobid_request_asks_for_head_and_paragraph_coordinates(self, monkeypatch):
        """Ohne ``teiCoordinates`` haette der GROBID-Pfad keine Seitenzahlen."""
        from academic_vault.chunking import chunk_pdf

        captured: dict = {}
        _mock_grobid(monkeypatch, _tei_text(), captured)
        chunk_pdf(str(FIXTURE_PDF), token_counter=_word_counter)

        assert captured["url"] == "http://localhost:8070/api/processFulltextDocument"
        assert set(captured["data"]["teiCoordinates"]) == {"head", "p"}
        assert captured["data"]["consolidateHeader"] == "0"

    def test_pages_come_from_tei_coordinates(self, monkeypatch):
        from academic_vault.chunking import chunk_pdf

        _mock_grobid(monkeypatch, _tei_text())
        chunks = chunk_pdf(str(FIXTURE_PDF), token_counter=_word_counter)

        # Die Fixture hat Absaetze auf Seite 1, 2 und 3; das PDF hat 6 Seiten.
        assert min(c.page_start for c in chunks) == 1
        assert max(c.page_end for c in chunks) == 3

    def test_first_box_of_multi_box_coords_decides_the_page(self):
        """``coords="1,...;2,..."`` -> Seite 1, nicht 2."""
        from academic_vault.fulltext import parse_tei_sections

        tei = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
            "<head>Kapitel</head>"
            '<p coords="4,72.0,90.0,451.0,11.0;5,72.0,90.0,451.0,11.0">alpha beta</p>'
            "</div></body></text></TEI>"
        )
        sections = parse_tei_sections(tei)
        assert sections[0].paragraphs[0].page == 4

    def test_paragraph_without_coords_carries_the_last_known_page(self):
        from academic_vault.fulltext import parse_tei_sections

        sections = _parse(parse_tei_sections)
        pages = [p.page for s in sections for p in s.paragraphs]
        # Absatz 3 der zweiten Sektion hat kein @coords -> Seite bleibt 1.
        assert pages[:4] == [1, 1, 1, 1]
        assert pages[4] == 2

    def test_back_matter_is_not_a_section(self):
        for section in _sections():
            for paragraph in section.paragraphs:
                assert BACK_MARKER not in paragraph.text


def _parse(fn):
    return fn(_tei_text())


def _regex_paragraph_text() -> str:
    return " ".join(_regex_words())


def _regex_words() -> list[str]:
    return [REGEX_FALSE_POSITIVE] + [f"befund{i}" for i in range(60)]


def _regex_pages() -> list[tuple[int, str]]:
    """Derselbe Inhalt seitenweise, mit PDF-typischem Zeilenumbruch:
    die echte Ueberschrift steht auf einer Zeile, "However" auf einer eigenen."""
    words = _regex_words()
    text = "\n".join(
        [
            HEAD_MISSED_BY_REGEX,
            words[0],
            " ".join(words[1:]),
        ]
    )
    return [(1, text)]


class TestWithoutGrobidUrlNothingChanges:
    """AK2: ohne ``GROBID_URL`` verhaelt sich das Chunking exakt wie heute."""

    def test_chunk_pdf_output_is_field_identical_to_the_page_path(self, monkeypatch):
        from academic_vault import fulltext as fulltext_mod
        from academic_vault.chunking import chunk_pages, chunk_pdf, extract_pages

        monkeypatch.delenv(fulltext_mod.ENV_GROBID_URL, raising=False)

        def _no_http(*args, **kwargs):
            raise AssertionError("Ohne GROBID_URL darf kein HTTP-Request stattfinden")

        monkeypatch.setattr(fulltext_mod.httpx, "post", _no_http)

        actual = chunk_pdf(str(FIXTURE_PDF), token_counter=_word_counter)
        expected = chunk_pages(extract_pages(str(FIXTURE_PDF)), token_counter=_word_counter)

        assert actual == expected
        assert len(actual) > 1

    def test_existing_fixture_headings_are_still_detected(self, monkeypatch):
        from academic_vault import fulltext as fulltext_mod
        from academic_vault.chunking import chunk_pdf

        monkeypatch.delenv(fulltext_mod.ENV_GROBID_URL, raising=False)
        titles = {c.section_title for c in chunk_pdf(str(FIXTURE_PDF))}
        assert titles & {"Abstract", "1 Introduction", "5 Conclusion"}

    def test_grobid_failure_falls_back_to_the_page_path(self, monkeypatch, caplog):
        """Ein kaputter/abwesender Server darf das Chunking nicht kippen."""
        import logging

        from academic_vault import fulltext as fulltext_mod
        from academic_vault.chunking import chunk_pages, chunk_pdf, extract_pages

        def _boom(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(fulltext_mod.httpx, "post", _boom)
        monkeypatch.setenv(fulltext_mod.ENV_GROBID_URL, "http://localhost:8070")

        with caplog.at_level(logging.WARNING, logger="academic_vault.chunking"):
            actual = chunk_pdf(str(FIXTURE_PDF), token_counter=_word_counter)

        expected = chunk_pages(extract_pages(str(FIXTURE_PDF)), token_counter=_word_counter)
        assert actual == expected
        assert any("GROBID" in record.message for record in caplog.records)

    def test_empty_tei_falls_back_to_the_page_path(self, monkeypatch):
        from academic_vault.chunking import chunk_pages, chunk_pdf, extract_pages

        _mock_grobid(monkeypatch, '<TEI xmlns="http://www.tei-c.org/ns/1.0"/>')
        actual = chunk_pdf(str(FIXTURE_PDF), token_counter=_word_counter)
        expected = chunk_pages(extract_pages(str(FIXTURE_PDF)), token_counter=_word_counter)
        assert actual == expected


class TestChunksPreferParagraphBoundaries:
    """AK3: Schnitt an Absatz-/Sektionsgrenze, mitten im Absatz nur bei Budgetdruck."""

    def test_every_chunk_ends_on_a_paragraph_boundary_when_budget_allows(self):
        from academic_vault.chunking import chunk_sections
        from academic_vault.fulltext import TeiParagraph, TeiSection

        # Vier Absaetze zu je 100 Woertern, Budget 250 -> Schnitte bei 200/400.
        sections = [
            TeiSection(
                title="Kapitel",
                paragraphs=[
                    TeiParagraph(text=" ".join(f"w{p}_{i}" for i in range(100)), page=1)
                    for p in range(4)
                ],
            )
        ]
        chunks = chunk_sections(sections, target_tokens=250, token_counter=_word_counter)

        assert len(chunks) == 2
        assert [len(c.chunk_text.split()) for c in chunks] == [200, 200]
        assert chunks[0].chunk_text.split()[-1] == "w1_99"
        assert chunks[1].chunk_text.split()[0] == "w2_0"

    def test_section_boundary_ends_a_chunk(self):
        from academic_vault.chunking import chunk_sections
        from academic_vault.fulltext import TeiParagraph, TeiSection

        sections = [
            TeiSection(
                title="Erste",
                paragraphs=[TeiParagraph(text=" ".join(f"a{i}" for i in range(90)), page=1)],
            ),
            TeiSection(
                title="Zweite",
                paragraphs=[TeiParagraph(text=" ".join(f"b{i}" for i in range(90)), page=2)],
            ),
        ]
        chunks = chunk_sections(sections, target_tokens=100, token_counter=_word_counter)

        assert [c.section_title for c in chunks] == ["Erste", "Zweite"]
        assert chunks[0].chunk_text.split() == [f"a{i}" for i in range(90)]
        assert chunks[1].chunk_text.split() == [f"b{i}" for i in range(90)]

    def test_paragraph_is_split_only_when_the_budget_forces_it(self):
        from academic_vault.chunking import chunk_sections
        from academic_vault.fulltext import TeiParagraph, TeiSection

        sections = [
            TeiSection(
                title="Lang",
                paragraphs=[TeiParagraph(text=" ".join(f"x{i}" for i in range(500)), page=1)],
            )
        ]
        chunks = chunk_sections(sections, target_tokens=200, token_counter=_word_counter)

        assert len(chunks) > 1
        for chunk in chunks:
            assert _word_counter(chunk.chunk_text) <= 200

    def test_tiny_boundary_does_not_produce_a_starved_chunk(self):
        """Ein Absatzende direkt hinter dem Chunkstart darf keinen Mini-Chunk
        erzeugen -- dafuer gibt es MIN_BOUNDARY_FILL_RATIO."""
        from academic_vault.chunking import MIN_BOUNDARY_FILL_RATIO, chunk_sections
        from academic_vault.fulltext import TeiParagraph, TeiSection

        sections = [
            TeiSection(
                title="Gemischt",
                paragraphs=[
                    TeiParagraph(text=" ".join(f"p0_{i}" for i in range(190)), page=1),
                    TeiParagraph(text=" ".join(f"p1_{i}" for i in range(10)), page=1),
                    TeiParagraph(text=" ".join(f"p2_{i}" for i in range(400)), page=1),
                ],
            )
        ]
        budget = 200
        chunks = chunk_sections(sections, target_tokens=budget, token_counter=_word_counter)

        assert 0 < MIN_BOUNDARY_FILL_RATIO < 1
        for chunk in chunks[:-1]:
            size = _word_counter(chunk.chunk_text)
            assert size >= MIN_BOUNDARY_FILL_RATIO * budget, (
                f"Chunk {chunk.chunk_index} nutzt nur {size} von {budget} Tokens"
            )

    def test_no_word_is_lost_or_reordered(self):
        from academic_vault.chunking import chunk_sections

        sections = _sections()
        chunks = chunk_sections(sections, token_counter=_word_counter)

        source = [w for s in sections for p in s.paragraphs for w in p.text.split()]
        rebuilt: list[str] = []
        for chunk in chunks:
            words = chunk.chunk_text.split()
            overlap = _shared_word_run(rebuilt, words) if rebuilt else 0
            rebuilt.extend(words[overlap:])
        assert rebuilt == source


class TestTeiFixtureCoversGrobidPathWithoutServer:
    """AK4: eine TEI-Fixture im Repo deckt den GROBID-Pfad ohne Server ab."""

    def test_fixture_is_tracked_in_the_repo(self):
        assert FIXTURE_TEI.is_file(), f"TEI-Fixture fehlt: {FIXTURE_TEI}"

    def test_fixture_parses_into_the_expected_sections(self):
        sections = _sections()
        assert [s.title for s in sections] == [
            "Abstract",
            HEAD_MISSED_BY_REGEX,
            OVERSIZED_HEAD,
            "5 Fazit",
        ]
        assert [len(s.paragraphs) for s in sections] == [1, 3, 1, 1]

    def test_chunking_the_fixture_needs_no_http_at_all(self, monkeypatch):
        from academic_vault import fulltext as fulltext_mod
        from academic_vault.chunking import chunk_sections

        def _no_http(*args, **kwargs):
            raise AssertionError("Die Fixture darf keinen Server kontaktieren")

        monkeypatch.setattr(fulltext_mod.httpx, "post", _no_http)
        chunks = chunk_sections(_sections(), token_counter=_word_counter)
        assert len(chunks) > 1

    def test_parser_rejects_external_entities(self):
        """TEI kommt von einem externen Dienst -- XXE muss geblockt bleiben."""
        from academic_vault.fulltext import parse_tei_sections
        from lxml.etree import XMLSyntaxError

        evil = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE TEI [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
            "<head>Kapitel</head><p>&xxe;</p></div></body></text></TEI>"
        )
        try:
            sections = parse_tei_sections(evil)
        except XMLSyntaxError:
            return
        for section in sections:
            for paragraph in section.paragraphs:
                assert "root:" not in paragraph.text

    def test_section_text_is_capped_at_max_fulltext_chars(self, monkeypatch):
        from academic_vault import fulltext as fulltext_mod

        monkeypatch.setattr(fulltext_mod, "MAX_FULLTEXT_CHARS", 50)
        sections = fulltext_mod.parse_tei_sections(_tei_text())
        total = sum(len(p.text) for s in sections for p in s.paragraphs)
        assert total == 50


class TestOversizedSectionSplitsWithOverlap:
    """AK5: eine Sektion ueber dem Budget wird weiterhin mit Overlap zerlegt."""

    def _oversized(self):
        for section in _sections():
            if section.title == OVERSIZED_HEAD:
                return section
        raise AssertionError(f"Sektion '{OVERSIZED_HEAD}' fehlt in der Fixture")

    def test_fixture_section_is_really_over_the_budget(self):
        from academic_vault.chunking import TARGET_TOKENS

        section = self._oversized()
        assert len(section.paragraphs) == 1
        words = section.paragraphs[0].text.split()
        assert len(words) == OVERSIZED_WORDS
        assert len(words) > 3 * TARGET_TOKENS

    def test_splits_into_several_chunks_of_the_same_section(self):
        from academic_vault.chunking import TARGET_TOKENS, chunk_sections

        chunks = chunk_sections([self._oversized()], token_counter=_word_counter)

        assert len(chunks) >= 3
        assert {c.section_title for c in chunks} == {OVERSIZED_HEAD}
        for chunk in chunks:
            assert _word_counter(chunk.chunk_text) <= TARGET_TOKENS

    def test_adjacent_chunks_overlap_10_to_15_percent(self):
        from academic_vault.chunking import chunk_sections

        chunks = chunk_sections([self._oversized()], token_counter=_word_counter)
        assert len(chunks) >= 3

        for i in range(len(chunks) - 1):
            words_a = chunks[i].chunk_text.split()
            words_b = chunks[i + 1].chunk_text.split()
            overlap = _shared_word_run(words_a, words_b)
            assert overlap > 0, f"Chunks {i}/{i + 1} ueberlappen gar nicht"
            ratio = overlap / len(words_a)
            assert 0.10 <= ratio <= 0.15, (
                f"Chunks {i}/{i + 1}: Overlap-Ratio {ratio:.3f} ausserhalb 10-15%"
            )

    def test_no_word_of_the_oversized_section_is_lost(self):
        from academic_vault.chunking import chunk_sections

        section = self._oversized()
        chunks = chunk_sections([section], token_counter=_word_counter)

        source = section.paragraphs[0].text.split()
        rebuilt: list[str] = []
        for chunk in chunks:
            words = chunk.chunk_text.split()
            overlap = _shared_word_run(rebuilt, words) if rebuilt else 0
            rebuilt.extend(words[overlap:])
        assert rebuilt == source

    def test_chunk_indices_are_sequential(self):
        from academic_vault.chunking import chunk_sections

        chunks = chunk_sections(_sections(), token_counter=_word_counter)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


class TestEdgeCases:
    def test_empty_section_list_yields_no_chunks(self):
        from academic_vault.chunking import chunk_sections

        assert chunk_sections([]) == []

    def test_sections_without_text_yield_no_chunks(self):
        from academic_vault.chunking import chunk_sections
        from academic_vault.fulltext import TeiParagraph, TeiSection

        sections = [TeiSection(title="Leer", paragraphs=[TeiParagraph(text="   ", page=1)])]
        assert chunk_sections(sections) == []

    def test_section_without_head_gets_the_default_title(self):
        from academic_vault.chunking import DEFAULT_SECTION_TITLE, chunk_sections
        from academic_vault.fulltext import parse_tei_sections

        tei = (
            '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
            '<p coords="1,72.0,90.0,451.0,11.0">alpha beta gamma</p>'
            "</div></body></text></TEI>"
        )
        chunks = chunk_sections(parse_tei_sections(tei), token_counter=_word_counter)
        assert [c.section_title for c in chunks] == [DEFAULT_SECTION_TITLE]

    def test_tei_without_body_yields_no_sections(self):
        from academic_vault.fulltext import parse_tei_sections

        assert parse_tei_sections('<TEI xmlns="http://www.tei-c.org/ns/1.0"/>') == []

    def test_extract_grobid_sections_accepts_bytes_and_str(self):
        from academic_vault.fulltext import parse_tei_sections

        as_str = parse_tei_sections(_tei_text())
        as_bytes = parse_tei_sections(_tei_text().encode("utf-8"))
        assert [s.title for s in as_str] == [s.title for s in as_bytes]

    def test_missing_coords_warns_once(self, caplog):
        import logging

        from academic_vault.fulltext import parse_tei_sections

        with caplog.at_level(logging.WARNING, logger="academic_vault.fulltext"):
            parse_tei_sections(_tei_text())
        hits = [r for r in caplog.records if "coords" in r.message]
        assert len(hits) == 1

    def test_extract_fulltext_request_stays_without_coordinates(self, monkeypatch):
        """Der Fliesstext-Pfad (#373) bleibt unveraendert -- kein teiCoordinates."""
        from academic_vault import fulltext as fulltext_mod

        captured: dict = {}
        _mock_grobid(monkeypatch, _tei_text(), captured)
        text, extractor = fulltext_mod.extract_fulltext(str(FIXTURE_PDF))

        assert extractor == "grobid"
        assert "teiCoordinates" not in captured["data"]
        # Der Fliesstext zieht bewusst auch <back> mit (siehe parse_tei_fulltext).
        assert BACK_MARKER in text


@pytest.mark.parametrize("bad", ["", "abc,1,2", "0,1,2,3,4", "-3,1,2,3,4"])
def test_unusable_coords_do_not_crash_the_parser(bad):
    from academic_vault.fulltext import parse_tei_sections

    tei = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
        f'<head>Kapitel</head><p coords="{bad}">alpha beta</p>'
        "</div></body></text></TEI>"
    )
    sections = parse_tei_sections(tei)
    assert sections[0].paragraphs[0].page == 1
