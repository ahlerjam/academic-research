"""Echter pptx-Rendering-Nachweis fuer slide-export (Fixrunde PR #488, Issue #446).

Review-Fund (PR #488): "AC4: Kein Nachweis, dass ein erzeugter Foliensatz
sich in PowerPoint oeffnen laesst -- build_slide_deck.py liefert nur eine
Zwischenrepraesentation, das eigentliche .pptx-Rendering laeuft ueber den
externen, nicht getesteten Skill document-skills:pptx."

Vor diesem Test stimmt das: tests/test_slide_export.py deckt nur
extract_slide_data() (die {title, core_statement, source}-Zwischenrepraesen-
tation) isoliert ab -- kein Test baut daraus je eine tatsaechliche Datei.

Dieser Test schliesst genau diese Luecke -- mit `python-pptx` als
Test-only-Renderer, NICHT als Ersatz fuer den Produktionspfad
`document-skills:pptx` (der bleibt pptxgenjs/Node, siehe
skills/slide-export/SKILL.md, Abschnitt "Slide-Backend"). python-pptx ist
ein reines PyPI-Paket (pyproject.toml [project.optional-dependencies].dev)
und damit -- anders als document-skills selbst -- in der CI-Matrix
installierbar (uv sync --extra dev in .github/actions/setup-python-uv); die
strukturellen Assertions unten laufen also in JEDEM CI-Lauf, nicht nur
lokal.

Mechanisch nachgewiesen:
  - extract_slide_data() wird einmal wirklich gegen echte Kapitel-Fixtures
    ausgefuehrt und das Ergebnis fliesst in einen tatsaechlich gerenderten
    Foliensatz (vorher lief dieser Pfad nirgends).
  - 1:1-Zuordnung Kapitel-Eintrag -> Folie bleibt im gerenderten Deck
    erhalten (AC4).
  - `title` landet im Titel-Platzhalter der Folie, `core_statement` im
    Inhalts-Platzhalter -- keine Datenverluste beim Rendern.
  - Ein Kapitel ohne Fliesstext (leerer core_statement) erzeugt trotzdem
    eine gueltige Folie, keinen Absturz.
  - Die erzeugte Datei laesst sich verlustfrei wieder oeffnen (python-pptx-
    Roundtrip) -- derselbe Repair-Hinweis-Proxy wie beim docx-Pendant, siehe
    tests/test_word_export_docx_render.py.

Zusaetzlich, wenn `soffice` (LibreOffice) lokal verfuegbar ist: echte
Kompatibilitaets-Konvertierung nach PDF -- derselbe Nachweisweg, den
document-skills:pptx selbst fuer die eigene QA vorschreibt (SKILL.md:
"python scripts/office/soffice.py --headless --convert-to pdf deck.pptx").
CI hat kein LibreOffice installiert, daher dort geskippt -- exakt dasselbe
Pattern wie PDFLATEX_AVAILABLE in tests/test_latex_export.py.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pptx = pytest.importorskip("pptx", reason="python-pptx nicht installiert (uv sync --extra dev)")

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

#: Layout-Index "Title and Content" im Standard-python-pptx-Template --
#: Titel- + Inhalts-Platzhalter, analog zur "eine Kernaussage pro Folie"-
#: Vorgabe aus SKILL.md.
_TITLE_AND_CONTENT_LAYOUT = 1
_CONTENT_PLACEHOLDER_IDX = 1


def _render_reference_pptx(slides_data: list[dict], out_path: Path) -> None:
    """Baut aus echter extract_slide_data()-Ausgabe einen minimalen, aber
    echten .pptx-Foliensatz.

    Testeigene Rendering-Referenz, kein Ersatz fuer document-skills:pptx
    (siehe Moduldocstring). Eine Folie pro Eintrag, Titel im Titel-
    Platzhalter, core_statement im Inhalts-Platzhalter -- bildet nur die
    im Review bemaengelte 1:1-Zuordnung und Datenuebernahme ab.
    """
    presentation = pptx.Presentation()
    layout = presentation.slide_layouts[_TITLE_AND_CONTENT_LAYOUT]
    for entry in slides_data:
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = entry["title"]
        slide.placeholders[_CONTENT_PLACEHOLDER_IDX].text_frame.text = entry["core_statement"]

    presentation.save(str(out_path))


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
