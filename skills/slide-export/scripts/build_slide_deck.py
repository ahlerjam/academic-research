"""build_slide_deck.py — Kapitel -> Folien-Zwischenrepraesentation (Issue #446).

Extrahiert aus Kapitel-Markdown eine Liste von {title, core_statement, source}
-- ein Eintrag pro Kapitel-Datei, eine Kernaussage pro Folie (AC4). Reine
Textextraktion ohne pptx-Rendering: das tatsaechliche Foliendeck erzeugt der
Agent im slide-export-Workflow (SKILL.md) ueber `document-skills:pptx`. Wie
bei latex-export/Pandoc ist nur die Struktur- und Extraktionslogik hier
CI-testbar, der Skill-Aufruf selbst nicht (Plan-Risiko #3).

Kapitel-Auflösung (--kapitel <n>|all) dupliziert bewusst NICHT resolve_chapters
aus latex-export/scripts/export_thesis.py, sondern importiert es -- dieselbe
Begruendung wie bei collect_references.get_all_papers (Import statt Kopie).

Oeffentliche API:
  resolve_chapters(kapitel_dir, selector) -> list[Path]   (Re-Export aus export_thesis)
  extract_title(markdown, fallback) -> str
  extract_core_statement(markdown) -> str
  extract_slide_data(chapters) -> list[dict]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_LATEX_EXPORT_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "latex-export" / "scripts"
if str(_LATEX_EXPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LATEX_EXPORT_SCRIPTS))

from export_thesis import ChapterResolutionError, resolve_chapters  # noqa: E402  (Re-Export)

__all__ = [
    "resolve_chapters",
    "ChapterResolutionError",
    "extract_title",
    "extract_core_statement",
    "extract_slide_data",
]

_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"(.+?[.!?])(\s|$)")


def extract_title(markdown: str, fallback: str) -> str:
    """Erste H1-Ueberschrift als Folientitel; ohne H1 -> `fallback` (Dateiname)."""
    match = _HEADING_RE.search(markdown)
    if match:
        return match.group(1).strip()
    return fallback


def extract_core_statement(markdown: str) -> str:
    """Erster Fliesstext-Absatz nach der Ueberschrift, auf den ersten Satz gekuerzt.

    Kein Fliesstext-Absatz gefunden (nur Ueberschrift, nur Liste) -> leerer
    String; SKILL.md verlangt in dem Fall eine Rueckfrage statt Fabrikation
    einer Kernaussage.
    """
    body_lines: list[str] = []
    started = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not started:
            if not stripped or stripped.startswith("#"):
                continue
            # Listen-/Zitat-Zeilen zaehlen nicht als Fliesstext-Absatz-Start.
            if stripped.startswith(("-", "*", "+", ">")) or re.match(r"^\d+\.\s", stripped):
                continue
            started = True
        else:
            if not stripped:
                break  # Absatzende
        if started:
            body_lines.append(stripped)

    if not body_lines:
        return ""

    paragraph = " ".join(body_lines)
    sentence_match = _SENTENCE_END_RE.match(paragraph)
    return sentence_match.group(1) if sentence_match else paragraph


def extract_slide_data(chapters: list[Path]) -> list[dict]:
    """Baut die Folien-Zwischenrepraesentation: ein Eintrag pro Kapitel-Datei.

    Jeder Eintrag: {"title": str, "core_statement": str, "source": str}.
    1:1-Zuordnung Kapitel-Datei -> Folie (AC4).
    """
    slides = []
    for chapter in chapters:
        markdown = chapter.read_text(encoding="utf-8")
        slides.append(
            {
                "title": extract_title(markdown, fallback=chapter.stem),
                "core_statement": extract_core_statement(markdown),
                "source": chapter.name,
            }
        )
    return slides
