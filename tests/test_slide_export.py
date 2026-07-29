"""Tests fuer slide-export (Issue #446).

TDD-First: deckt die reinen Python-Funktionen aus
skills/slide-export/scripts/build_slide_deck.py ab -- Kapitel-Aufloesung
(Re-Export aus latex-export/export_thesis.resolve_chapters), Titel-/Kernaussage-
Extraktion und die 1:1-Zuordnung Kapitel -> Folie (AC4). Das eigentliche
pptx-Rendering laeuft ueber `document-skills:pptx` und ist nicht CI-fahrbar
(Plan-Risiko #3, analog xlsx).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).parent.parent
SCRIPTS_DIR = WORKTREE / "skills" / "slide-export" / "scripts"
LATEX_SCRIPTS_DIR = WORKTREE / "skills" / "latex-export" / "scripts"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "slide_export"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(LATEX_SCRIPTS_DIR))


class TestImportAndChapterResolutionReuse:
    def test_import(self):
        import build_slide_deck

        assert build_slide_deck

    def test_resolve_chapters_is_reexport_of_export_thesis(self):
        """build_slide_deck.resolve_chapters MUSS export_thesis.resolve_chapters sein.

        Eine eigene Kapitel-Aufloesung wuerde die --kapitel <n>|all-Semantik
        (Nummern-Matching, Sortierung) dupliziert pflegen -- Import statt Kopie.
        """
        import build_slide_deck
        import export_thesis

        assert build_slide_deck.resolve_chapters is export_thesis.resolve_chapters


class TestTitleExtraction:
    def test_extracts_h1_as_title(self):
        from build_slide_deck import extract_title

        md = "# Einleitung\n\nText.\n"
        assert extract_title(md, fallback="x") == "Einleitung"

    def test_falls_back_to_filename_without_h1(self):
        from build_slide_deck import extract_title

        md = "Nur Fliesstext ohne Ueberschrift.\n"
        assert extract_title(md, fallback="3-ergebnisse") == "3-ergebnisse"


class TestCoreStatementExtraction:
    def test_first_sentence_of_first_paragraph(self):
        from build_slide_deck import extract_core_statement

        md = "# Einleitung\n\nDies ist der erste Satz. Dies ist der zweite.\n"
        assert extract_core_statement(md) == "Dies ist der erste Satz."

    def test_empty_when_only_heading(self):
        from build_slide_deck import extract_core_statement

        md = "# Nur Ueberschrift\n"
        assert extract_core_statement(md) == ""

    def test_empty_when_only_list(self):
        from build_slide_deck import extract_core_statement

        md = "# Ergebnisse\n\n- Befund eins\n- Befund zwei\n"
        assert extract_core_statement(md) == ""

    def test_fixture_list_only_chapter_has_empty_statement(self):
        from build_slide_deck import extract_core_statement

        md = (FIXTURES_DIR / "3-ergebnisse.md").read_text(encoding="utf-8")
        assert extract_core_statement(md) == ""


class TestExtractSlideData:
    def test_one_core_statement_per_slide(self):
        """AC4: 1:1-Zuordnung zwischen Kapitel-Dateien und Folien-Eintraegen."""
        from build_slide_deck import extract_slide_data

        chapters = sorted(FIXTURES_DIR.glob("*.md"))
        slides = extract_slide_data(chapters)

        assert len(slides) == len(chapters) == 3
        for slide in slides:
            assert set(slide.keys()) == {"title", "core_statement", "source"}

        titles = [s["title"] for s in slides]
        assert titles == ["Einleitung", "Methodik", "Ergebnisse"]

        assert slides[0]["core_statement"] == (
            "Diese Arbeit untersucht, wie DevOps-Governance in kleinen und "
            "mittleren Unternehmen wirkt."
        )
        assert slides[2]["core_statement"] == ""

    def test_empty_chapter_list_yields_empty_slides(self):
        from build_slide_deck import extract_slide_data

        assert extract_slide_data([]) == []


class TestChapterResolutionIntegration:
    def test_resolve_all_matches_fixture_count(self):
        from build_slide_deck import resolve_chapters

        chapters = resolve_chapters(FIXTURES_DIR, "all")
        assert len(chapters) == 3
        assert [c.name for c in chapters] == [
            "1-einleitung.md",
            "2-methodik.md",
            "3-ergebnisse.md",
        ]

    def test_resolve_unknown_selector_raises(self):
        from build_slide_deck import ChapterResolutionError, resolve_chapters

        with pytest.raises(ChapterResolutionError):
            resolve_chapters(FIXTURES_DIR, "99")
