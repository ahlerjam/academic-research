"""export_thesis.py — Orchestriert den LaTeX-Export (Issue #467).

Bindet die in commands/latex.md dokumentierten CLI-Parameter ans
tatsaechliche Verhalten:

    --kapitel <n>|all      Kapitel-Auswahl aus kapitel/
    --output <datei.tex>   Ausgabepfad (frei waehlbar)
    --bib <datei.bib>      BibTeX-Ausgabe, unabhaengig von --output
                            (Default: output/refs.bib)
    --template <uni>       Uni-Vorlage aus
                            ~/.academic-research/library-profiles/<uni>.tex.template

Oeffentliche API:
    resolve_chapters(kapitel_dir, selector) -> list[Path]
    concatenate_chapters(chapters, force_custom=False) -> str
    apply_template(body, uni, profiles_dir) -> tuple[str, str | None]
    export_thesis(...) -> ExportResult
    main(argv) -> int
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Geschwister-Module (render_tex.py, build_bib.py) liegen im selben
# Verzeichnis. Beim direkten Skriptaufruf (python3 export_thesis.py) haengt
# Python sys.path[0] automatisch an; beim Import aus Tests haben diese
# bereits SCRIPTS_DIR auf sys.path gelegt. Der explizite Insert deckt auch
# den Fall ab, dass nur export_thesis importiert wird (z.B. via
# ${CLAUDE_PLUGIN_ROOT}-Aufruf aus einem anderen cwd).
sys.path.insert(0, str(Path(__file__).parent))

from build_bib import build_bib_from_vault  # noqa: E402
from render_tex import render_markdown_to_tex  # noqa: E402

DEFAULT_BIB_PATH = "output/refs.bib"
DEFAULT_PROFILES_DIR = Path.home() / ".academic-research" / "library-profiles"

_LEADING_NUMBER_RE = re.compile(r"^0*(\d+)")


class ChapterResolutionError(ValueError):
    """--kapitel-Selektor passt auf keine oder mehrere Dateien in kapitel/."""


def _leading_number(stem: str) -> int | None:
    """Extrahiert die fuehrende Ziffernfolge aus einem Dateinamen-Stamm.

    "3" -> 3, "03-methodik" -> 3, "10" -> 10, "methodik" -> None.
    """
    match = _LEADING_NUMBER_RE.match(stem)
    if match is None:
        return None
    return int(match.group(1))


def _sort_key(path: Path) -> tuple[int, str]:
    number = _leading_number(path.stem)
    # Dateien ohne fuehrende Zahl landen sortiert hinter allen nummerierten
    # Kapiteln (alphabetischer Fallback ueber den Dateinamen).
    return (number if number is not None else 10**9, path.name)


def resolve_chapters(kapitel_dir: Path | str, selector: str) -> list[Path]:
    """Loest --kapitel <n>|all gegen die Markdown-Dateien in kapitel_dir auf.

    "all": alle *.md-Dateien, numerisch nach fuehrender Zahl im Dateinamen
    sortiert (Fallback: alphabetisch) -- z.B. kapitel/2.md vor kapitel/10.md.

    "<n>": Datei(en), deren fuehrende Ziffernfolge im Stamm numerisch "<n>"
    entspricht -- deckt sowohl "kapitel/3.md" als auch "kapitel/03-methodik.md"
    ab (die Namenskonvention ist im Repo nicht einheitlich, siehe Plan-Risiko #1).

    Wirft ChapterResolutionError mit einer fuer Menschen verstaendlichen
    Meldung bei fehlendem Verzeichnis, keinem Treffer oder Mehrdeutigkeit.
    """
    directory = Path(kapitel_dir)
    if not directory.is_dir():
        raise ChapterResolutionError(f"Kapitel-Verzeichnis '{directory}' existiert nicht.")

    all_chapters = sorted(directory.glob("*.md"), key=_sort_key)

    if selector == "all":
        if not all_chapters:
            raise ChapterResolutionError(f"Kein Kapitel in '{directory}' gefunden (*.md erwartet).")
        return all_chapters

    try:
        wanted = int(selector)
    except ValueError as exc:
        raise ChapterResolutionError(
            f"Ungueltiger --kapitel-Wert '{selector}': erwartet eine Zahl oder 'all'."
        ) from exc

    matches = [p for p in all_chapters if _leading_number(p.stem) == wanted]
    if not matches:
        available = ", ".join(p.name for p in all_chapters) or "(keine Dateien)"
        raise ChapterResolutionError(
            f"Kapitel '{selector}' nicht gefunden in '{directory}'. Verfuegbar: {available}"
        )
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise ChapterResolutionError(
            f"Kapitel '{selector}' ist mehrdeutig in '{directory}': {names}"
        )
    return matches


def concatenate_chapters(chapters: list[Path], force_custom: bool = False) -> str:
    """Rendert mehrere Kapitel-Dateien und verkettet sie in Datei-Reihenfolge."""
    bodies = []
    for chapter in chapters:
        md = chapter.read_text(encoding="utf-8")
        bodies.append(render_markdown_to_tex(md, force_custom=force_custom))
    return "\n\n".join(bodies)


def apply_template(
    body: str,
    uni: str | None,
    profiles_dir: Path | str = DEFAULT_PROFILES_DIR,
) -> tuple[str, str | None]:
    """Wickelt `body` in die Uni-Vorlage `<uni>.tex.template` (Platzhalter %%CONTENT%%).

    Gibt (finaler_content, fallback_meldung) zurueck. Ohne `uni` wird `body`
    unveraendert durchgereicht (keine Meldung). Fehlt die Vorlage-Datei, wird
    `body` ebenfalls unveraendert zurueckgegeben -- kein Absturz -- und eine
    erklaerende Meldung gesetzt (Wortlaut konsistent mit SKILL.md:
    "Template `<uni>` fehlt.").
    """
    if uni is None:
        return body, None

    template_path = Path(profiles_dir) / f"{uni}.tex.template"
    if not template_path.exists():
        message = f"Template `{uni}` fehlt ({template_path}). Fallback: Export ohne Vorlage."
        return body, message

    template_text = template_path.read_text(encoding="utf-8")
    return template_text.replace("%%CONTENT%%", body), None


@dataclass
class ExportResult:
    """Ergebnis eines export_thesis()-Laufs."""

    output_path: Path
    bib_path: Path
    chapters: list[Path]
    template_message: str | None = None


def export_thesis(
    kapitel_dir: Path | str,
    selector: str,
    output_path: Path | str,
    bib_path: Path | str | None = None,
    template_uni: str | None = None,
    profiles_dir: Path | str = DEFAULT_PROFILES_DIR,
    vault_db_path: str | None = None,
    force_custom: bool = False,
) -> ExportResult:
    """Fuehrt den vollstaendigen LaTeX-Export aus (Issue #467).

    1. Kapitel resolven (resolve_chapters) -- wirft ChapterResolutionError.
    2. Markdown -> LaTeX rendern + verketten (render_tex, in Datei-Reihenfolge).
    3. Optional: Uni-Template anwenden (apply_template, kein Absturz bei
       fehlender Vorlage).
    4. .tex schreiben; .bib aus dem Vault erzeugen -- Pfad unabhaengig von
       --output (Default: output/refs.bib).
    """
    chapters = resolve_chapters(kapitel_dir, selector)
    body = concatenate_chapters(chapters, force_custom=force_custom)
    content, template_message = apply_template(body, template_uni, profiles_dir)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    # Wahrheitswert statt `is not None`: ein leerer String (z.B. wenn
    # commands/latex.md ohne --bib "$BIB" mit leerem $BIB durchreicht) soll
    # ebenfalls auf den Default fallen statt Path("") -> PosixPath('.') an
    # build_bib_from_vault()/write_text() zu reichen (IsADirectoryError,
    # PR #485-Review, P1).
    resolved_bib_path = Path(bib_path) if bib_path else Path(DEFAULT_BIB_PATH)
    resolved_bib_path.parent.mkdir(parents=True, exist_ok=True)

    if vault_db_path is None:
        # Kanonischer Default-Pfad (Single Source of Truth, Issue #190):
        # respektiert VAULT_DB_PATH, sonst ~/.academic-research/projects/<slug>/vault.db.
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
        from academic_vault.db import default_db_path

        vault_db_path = default_db_path()

    build_bib_from_vault(vault_db_path, str(resolved_bib_path))

    return ExportResult(
        output_path=out_path,
        bib_path=resolved_bib_path,
        chapters=chapters,
        template_message=template_message,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LaTeX-Export: Kapitel aus kapitel/ zu .tex, .bib aus Vault (Issue #467).",
    )
    parser.add_argument("--kapitel", required=True, help="Kapitel-Nummer oder 'all'")
    parser.add_argument("--output", required=True, help="Ausgabepfad fuer die .tex-Datei")
    parser.add_argument(
        "--bib",
        default=None,
        help=f"Pfad fuer die .bib-Ausgabe (Default: {DEFAULT_BIB_PATH})",
    )
    parser.add_argument("--template", default=None, help="Uni-Kuerzel fuer den Vorlagen-Slot")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        result = export_thesis(
            kapitel_dir="kapitel",
            selector=args.kapitel,
            output_path=args.output,
            bib_path=args.bib,
            template_uni=args.template,
            profiles_dir=DEFAULT_PROFILES_DIR,
        )
    except ChapterResolutionError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    print(f"Exportiert: {result.output_path} ({len(result.chapters)} Kapitel)")
    print(f"BibTeX: {result.bib_path}")
    if result.template_message:
        print(result.template_message, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
