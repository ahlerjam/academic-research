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

import argparse
import json
import re
import sys
from pathlib import Path

_LATEX_EXPORT_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "latex-export" / "scripts"
if str(_LATEX_EXPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LATEX_EXPORT_SCRIPTS))

from export_thesis import ChapterResolutionError, resolve_chapters  # noqa: E402  (Re-Export)
from render_tex import LATEX_COMMAND_RE  # noqa: E402

__all__ = [
    "resolve_chapters",
    "ChapterResolutionError",
    "extract_title",
    "extract_core_statement",
    "extract_slide_data",
    "strip_latex_markers",
]

_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"(.+?[.!?])(\s|$)")


def strip_latex_markers(text: str) -> str:
    """Entfernt LaTeX-Zitations-/Referenzmarker aus einem Folientext.

    slide-export fuehrt bewusst kein Literaturverzeichnis (SKILL.md,
    Abgrenzung) und hat keinen Vault-Zugriff -- ein Marker kann hier also nicht
    wie im word-export-Pfad zu einem Kurzbeleg aufgeloest werden. Roh stehen
    lassen darf man ihn trotzdem nicht: der Live-Lauf des dokumentierten
    Aufrufwegs (Fixrunde PR #488) hat ``\\cite{smith2023,jones2022}`` woertlich
    als Folien-Kernaussage geliefert. Zusaetzlich zerschiesst der Punkt in einem
    Locator (``\\citep[S. 12]{k}``) die Erste-Satz-Erkennung, weil er wie ein
    Satzende aussieht -- deshalb wird VOR der Satzzerlegung entfernt.

    Kommandoliste kommt aus ``render_tex.LATEX_COMMAND_RE`` (Import statt
    Kopie), damit sie nicht gegenueber latex-export driftet.
    """
    without_markers = LATEX_COMMAND_RE.sub("", text)
    # Leerzeichen, das erst durch das Entfernen vor dem Satzzeichen entstand.
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", without_markers)


def extract_title(markdown: str, fallback: str) -> str:
    """Erste H1-Ueberschrift als Folientitel; ohne H1 -> `fallback` (Dateiname)."""
    match = _HEADING_RE.search(markdown)
    if match:
        return match.group(1).strip()
    return fallback


def extract_core_statement(markdown: str) -> str:
    """Erster Fliesstext-Absatz nach der Ueberschrift, auf den ersten Satz gekuerzt.

    LaTeX-Marker werden vorher entfernt (siehe `strip_latex_markers`) -- sie
    gehoeren nicht auf eine Folie und ihre Locator-Punkte wuerden die
    Satzgrenze falsch setzen.

    Kein Fliesstext-Absatz gefunden (nur Ueberschrift, nur Liste) -> leerer
    String; SKILL.md verlangt in dem Fall eine Rueckfrage statt Fabrikation
    einer Kernaussage.
    """
    markdown = strip_latex_markers(markdown)
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


# ---------------------------------------------------------------------------
# CLI: der von commands/slides.md dokumentierte Aufrufweg (Fixrunde PR #488)
# ---------------------------------------------------------------------------
#
# Gleiche Ursache und gleiches Gegenmittel wie bei word-export: der bisherige
# Inline-Python-Block im quotierten Heredoc (`python3 - <<'PY'`) hat weder
# ${CLAUDE_PLUGIN_ROOT} noch $KAPITEL expandiert und starb mit einem rohen
# ModuleNotFoundError, bevor `document-skills:pptx` erreicht wurde (AC4/AC6).

DEFAULT_KAPITEL_DIR = "kapitel"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Baut die Folien-Zwischenrepraesentation fuer den document-skills:pptx-Schritt "
            "von /academic-research:slides (Issue #446)."
        ),
    )
    parser.add_argument("--kapitel", required=True, help="Kapitel-Nummer oder 'all'")
    parser.add_argument(
        "--payload",
        required=True,
        help="Zieldatei fuer die JSON-Zwischenrepraesentation",
    )
    parser.add_argument("--kapitel-dir", default=DEFAULT_KAPITEL_DIR)
    parser.add_argument(
        "--rahmen",
        default="",
        choices=["", "kolloquium", "konferenz"],
        help="Foliensatz-Rahmen (--kolloquium/--konferenz aus dem Command)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        chapters = resolve_chapters(args.kapitel_dir, args.kapitel)
        slides = extract_slide_data(chapters)
    except ChapterResolutionError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    payload_path = Path(args.payload)
    if payload_path.parent != Path(""):
        payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(
        json.dumps({"slides": slides, "rahmen": args.rahmen}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Vorbereitet: {payload_path} ({len(slides)} Folien)")
    # Fehlende Kernaussage ist kein Abbruch, sondern eine Rueckfrage-Pflicht
    # des Agenten (SKILL.md: keine Fabrikation) -- hier nur sichtbar machen.
    for slide in slides:
        if not slide["core_statement"]:
            print(
                f"Kapitel '{slide['source']}' hat keine erkennbare Kernaussage - "
                "beim Nutzer nachfragen statt eine zu erfinden.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
