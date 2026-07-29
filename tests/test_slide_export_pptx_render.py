"""Echter pptx-Rendering-Nachweis fuer slide-export (Fixrunde PR #488, Issue #446).

Review-Fund (PR #488, Runde 2): "AC4: Foliensatz-Oeffnenbarkeit in PowerPoint
ist nicht belegt -- nur ein Test-only-python-pptx-Renderer statt des echten
Produktionspfads."

Das stimmte: die Vorrunde hatte den Renderer als ``_render_reference_pptx`` IN
DIESE DATEI gelegt, weil es im Repo keinen gab -- bewiesen war damit nur, dass
der Test ein .pptx schreiben kann.

Behoben an der Ursache: ``skills/slide-export/scripts/render_pptx.py`` erzeugt
das Deck jetzt als Repo-Code (dieselbe Rolle wie ``render_tex.py`` im
LaTeX-Pfad). Diese Datei ruft ausschliesslich diesen Produktionsrenderer auf --
kein Rendering-Code mehr im Test.

Arbeitsteilung der beiden Suiten:
  - tests/test_issue_446_render_pipeline.py faehrt den kompletten
    dokumentierten Aufrufweg (bash-Bloecke aus commands/slides.md).
  - diese Datei prueft den Renderer direkt gegen die Kapitel-Fixtures, inkl.
    Grenzfall "Kapitel ohne Fliesstext".

Mechanisch nachgewiesen:
  - extract_slide_data() laeuft gegen echte Kapitel-Fixtures und das Ergebnis
    fliesst durch render_pptx() in eine tatsaechliche Datei.
  - 1:1-Zuordnung Kapitel-Eintrag -> Folie bleibt im gerenderten Deck erhalten
    (AC4).
  - `title` landet im Titel-Platzhalter, `core_statement` im Inhalts-
    Platzhalter -- keine Datenverluste beim Rendern.
  - Ein Kapitel ohne Fliesstext (leerer core_statement) erzeugt trotzdem eine
    gueltige Folie, keinen Absturz.
  - Die erzeugte Datei laesst sich verlustfrei wieder oeffnen (python-pptx-
    Roundtrip) -- Repair-Hinweis-Proxy wie beim docx-Pendant.

Zusaetzlich, wenn `soffice` (LibreOffice) lokal verfuegbar ist: echte
Kompatibilitaets-Konvertierung nach PDF -- derselbe Nachweisweg, den
document-skills:pptx selbst fuer die eigene QA vorschreibt. CI hat kein
LibreOffice installiert, daher dort geskippt -- exakt dasselbe Pattern wie
PDFLATEX_AVAILABLE in tests/test_latex_export.py.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pptx = pytest.importorskip("pptx", reason="python-pptx nicht installiert (uv sync)")

WORKTREE = Path(__file__).parent.parent
SCRIPTS_DIR = WORKTREE / "skills" / "slide-export" / "scripts"
LATEX_SCRIPTS_DIR = WORKTREE / "skills" / "latex-export" / "scripts"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "slide_export"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(LATEX_SCRIPTS_DIR))

# LibreOffice ist in der CI-Matrix (ubuntu-latest/macos-latest) nicht
# installiert -- etabliertes Pattern siehe PDFLATEX_AVAILABLE in
# tests/test_latex_export.py: dort nur lokal beweiskraeftig.
SOFFICE_AVAILABLE = shutil.which("soffice") is not None

#: Inhalts-Platzhalter im Standard-python-pptx-Template -- dort landet die
#: Kernaussage (eine pro Folie, SKILL.md).
_CONTENT_PLACEHOLDER_IDX = 1


def _render_reference_pptx(slides_data: list[dict], out_path: Path) -> None:
    """Duenne Huelle um den PRODUKTIONSRENDERER -- kein Rendering-Code im Test.

    Baut nur die Payload-Form auf, die build_slide_deck.py schreibt, und
    uebergibt sie an skills/slide-export/scripts/render_pptx.py.
    """
    from render_pptx import render_pptx

    render_pptx({"slides": slides_data, "rahmen": ""}, out_path)


# ---------------------------------------------------------------------------
# AC4 — volle Pipeline einmal wirklich ausgefuehrt
# ---------------------------------------------------------------------------


class TestRealPptxRenderFromPipeline:
    def test_pipeline_output_renders_into_valid_reopenable_pptx(self, tmp_path):
        """extract_slide_data() -> echter, wieder oeffenbarer Foliensatz mit
        1:1-Zuordnung Kapitel -> Folie und verlustfreier Titel-/Kernaussage-
        Uebernahme."""
        from build_slide_deck import extract_slide_data, resolve_chapters

        chapters = resolve_chapters(FIXTURES_DIR, "all")
        slides_data = extract_slide_data(chapters)
        assert len(slides_data) == 3  # Vorbedingung: Pipeline lief wirklich gegen die Fixtures

        out_path = tmp_path / "deck.pptx"
        _render_reference_pptx(slides_data, out_path)

        # -- Repair-Proxy: die Datei laesst sich verlustfrei wieder oeffnen --
        reopened = pptx.Presentation(str(out_path))

        assert len(reopened.slides) == len(slides_data) == 3  # AC4: 1:1-Zuordnung im Deck

        for slide, expected in zip(reopened.slides, slides_data, strict=True):
            assert slide.shapes.title.text == expected["title"]
            content = slide.placeholders[_CONTENT_PLACEHOLDER_IDX].text_frame.text
            assert content == expected["core_statement"]

        # Konkrete Titel/Kernaussagen aus den Fixtures muessen ankommen, nicht
        # nur strukturell gleich viele Eintraege.
        titles = [s.shapes.title.text for s in reopened.slides]
        assert titles == ["Einleitung", "Methodik", "Ergebnisse"]

    def test_chapter_without_running_text_yields_valid_slide_with_empty_body(self, tmp_path):
        """Fehlerpfad "Kapitel ohne Kernaussage" (SKILL.md) erzeugt trotzdem
        eine gueltige, wieder oeffenbare Folie -- kein Absturz."""
        from build_slide_deck import extract_slide_data

        chapters = sorted(FIXTURES_DIR.glob("3-ergebnisse.md"))
        slides_data = extract_slide_data(chapters)
        assert slides_data[0]["core_statement"] == ""  # Vorbedingung (nur Ueberschrift/Liste)

        out_path = tmp_path / "deck_empty_statement.pptx"
        _render_reference_pptx(slides_data, out_path)

        reopened = pptx.Presentation(str(out_path))
        assert len(reopened.slides) == 1
        assert reopened.slides[0].shapes.title.text == "Ergebnisse"


class TestRealPptxRenderMatchesOfficeQAMethod:
    """Staerkerer Repair-Hinweis-Proxy ueber dieselbe QA-Methode, die
    document-skills:pptx selbst fuer die eigene Verifikation vorschreibt.
    Nur lokal beweiskraeftig -- siehe Moduldocstring."""

    @pytest.mark.skipif(
        not SOFFICE_AVAILABLE,
        reason="soffice/LibreOffice nicht in PATH (in CI-Matrix nicht installiert)",
    )
    def test_rendered_pptx_converts_cleanly_via_soffice(self, tmp_path):
        from build_slide_deck import extract_slide_data, resolve_chapters

        chapters = resolve_chapters(FIXTURES_DIR, "all")
        slides_data = extract_slide_data(chapters)

        out_path = tmp_path / "deck.pptx"
        _render_reference_pptx(slides_data, out_path)

        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path),
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"soffice-Konvertierung fehlgeschlagen (Reparaturhinweis-Signal):\n"
            f"{result.stdout}\n{result.stderr}"
        )
        pdf_path = tmp_path / "deck.pdf"
        assert pdf_path.exists() and pdf_path.stat().st_size > 0
