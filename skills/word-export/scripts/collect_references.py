"""collect_references.py — geteilte Bibliografie-Auswahl fuer word-export (Issue #446).

Dupliziert NICHT die Vault-Query aus latex-export/scripts/build_bib.py, sondern
importiert deren `get_all_papers()` (Plan-Risiko #2: eine zweite, unabhaengige
Implementierung wuerde AC3 -- Entrymengen-Paritaet docx <-> LaTeX -- lautlos bei
kuenftigen Vault-Aenderungen brechen). Ebenso definiert dieses Modul keine
eigenen Zitierstil-Regeln: die Regeln werden unveraendert aus den bestehenden
`citation-extraction/references/<style>.md`-Dateien geladen und als Rohtext an
den Agenten zurueckgegeben, der sie beim Rendern der Literaturliste in den
docx-Body anwendet (Python schreibt keine eigenen Stil-Strings, siehe
Plan-Kommentar zu Issue #446).

Oeffentliche API:
  get_all_papers(db_path) -> list[dict]                        (Re-Export aus build_bib)
  resolve_citation_style(academic_context_text) -> str          Zitationsstil -> Referenz-Dateiname
  load_style_rules(style_file, references_dir) -> str           Referenzdatei-Inhalt, unveraendert
  collect_references(db_path, academic_context_text, references_dir) -> dict
  resolve_cite_markers(text, papers) -> str                     \\cite{key} -> Klartext-Kurzzitat
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Geschwister-Skill latex-export liefert die kanonische Vault-Query. Import
# statt Kopie ist hartes Muss (nicht nur Empfehlung), siehe Modul-Docstring.
_SKILLS_ROOT = Path(__file__).resolve().parent.parent.parent
_PLUGIN_ROOT = _SKILLS_ROOT.parent
_LATEX_EXPORT_SCRIPTS = _SKILLS_ROOT / "latex-export" / "scripts"
if str(_LATEX_EXPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LATEX_EXPORT_SCRIPTS))
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from build_bib import get_all_papers  # noqa: E402  (bewusster Re-Export)
from export_thesis import ChapterResolutionError, resolve_chapters  # noqa: E402
from render_tex import LATEX_CITATION_COMMANDS  # noqa: E402

#: Default-Referenzverzeichnis: citation-extraction ist Single Source of Truth
#: fuer die Zitierstil-Regeln (siehe Modul-Docstring).
DEFAULT_REFERENCES_DIR = _SKILLS_ROOT / "citation-extraction" / "references"
DEFAULT_KAPITEL_DIR = "kapitel"
DEFAULT_ACADEMIC_CONTEXT = "academic_context.md"

__all__ = [
    "get_all_papers",
    "resolve_chapters",
    "parse_context_fields",
    "resolve_citation_style",
    "load_style_rules",
    "collect_references",
    "resolve_cite_markers",
    "build_payload",
    "StyleRulesNotFoundError",
    "ChapterResolutionError",
]


class StyleRulesNotFoundError(FileNotFoundError):
    """Referenzdatei fuer den aufgeloesten Zitationsstil fehlt."""


# ---------------------------------------------------------------------------
# Zitationsstil-Aufloesung
# ---------------------------------------------------------------------------

# Gleiche Zuordnung wie die Variant-Selector-Tabelle in
# citation-extraction/SKILL.md -- Single Source of Truth fuer die Stilregeln
# bleibt dort; hier wird nur der Dateiname referenziert, kein Regelinhalt
# dupliziert.
_STYLE_FILES = {
    "apa7": "apa.md",
    "apa": "apa.md",
    "harvard": "harvard.md",
    "chicago": "chicago.md",
    "din 1505-2": "din1505.md",
    "din1505-2": "din1505.md",
    "din 1505": "din1505.md",
    "din1505": "din1505.md",
    "mla": "mla.md",
    "vancouver": "vancouver.md",
    "springer author-date": "springer-author-date.md",
    "springer-author-date": "springer-author-date.md",
}
DEFAULT_STYLE_FILE = "apa.md"

_ZITATIONSSTIL_RE = re.compile(r"^-\s*Zitationsstil:\s*(.+?)\s*$", re.MULTILINE)

#: Alle "- Feld: Wert"-Zeilen aus academic_context.md (Format siehe
#: skills/academic-context/SKILL.md).
_CONTEXT_FIELD_RE = re.compile(r"^-\s*([^:\n]+?):\s*(.*?)\s*$", re.MULTILINE)


def parse_context_fields(academic_context_text: str) -> dict[str, str]:
    """Liest die "- Feld: Wert"-Zeilen aus academic_context.md als dict.

    Liefert nur ausgefuellte Felder: die Vorlage aus academic-context/SKILL.md
    schreibt unbeantwortete Punkte als "[...]" -- die als Wert durchzureichen
    ergaebe spaeter ein Titelblatt mit "Hochschule: [...]". Die tatsaechlich
    ausgelieferte Bootstrap-Vorlage (scripts/bootstrap/academic_context.stub.md)
    schreibt stattdessen unbeantwortete Punkte als "TODO" bzw.
    "TODO (Default: ...)" -- deckungsgleich mit resolve_citation_style() weiter
    unten wird auch dieses Format als Nicht-Wert behandelt. Ein weggelassenes
    Feld rendert render_docx.py stattdessen als sichtbare Leerstelle
    ("[bitte ergaenzen]") -- keine erfundenen Titelblatt-Angaben.
    """
    fields: dict[str, str] = {}
    for key, value in _CONTEXT_FIELD_RE.findall(academic_context_text or ""):
        cleaned = value.strip()
        if not cleaned or cleaned.startswith("[") or cleaned.upper().startswith("TODO"):
            continue
        fields[key.strip()] = cleaned
    return fields


def resolve_citation_style(academic_context_text: str) -> str:
    """Liest das Feld 'Zitationsstil' aus academic_context.md-Text.

    Gibt den Dateinamen der zugehoerigen citation-extraction-Referenzdatei
    zurueck. Fehlt das Feld, ist es leer oder steht noch auf 'TODO' -> Default
    (apa.md, deckungsgleich mit dem Plugin-Default aus academic-context/SKILL.md).
    Unbekannter Wert -> ebenfalls Default; eine Rueckfrage an den Nutzer ist
    Aufgabe des Agenten/SKILL.md-Workflows, nicht dieses reinen Parsers.
    """
    match = _ZITATIONSSTIL_RE.search(academic_context_text or "")
    if not match:
        return DEFAULT_STYLE_FILE
    raw = match.group(1).strip()
    if not raw or raw.upper().startswith("TODO"):
        return DEFAULT_STYLE_FILE
    # Klammerzusatz wie "APA7 (Default)" vor dem Lookup abtrennen.
    raw = raw.split("(")[0].strip()
    return _STYLE_FILES.get(raw.lower(), DEFAULT_STYLE_FILE)


def load_style_rules(style_file: str, references_dir: Path | str) -> str:
    """Laedt den Inhalt der citation-extraction-Referenzdatei unveraendert.

    Wirft StyleRulesNotFoundError mit einer fuer Menschen verstaendlichen
    Meldung, wenn die Datei fehlt -- SKILL.md faengt das ab statt einen
    Stacktrace durchzureichen (AC6).
    """
    path = Path(references_dir) / style_file
    if not path.is_file():
        raise StyleRulesNotFoundError(
            f"Zitierstil-Referenzdatei '{style_file}' fehlt in '{references_dir}'."
        )
    return path.read_text(encoding="utf-8")


def collect_references(
    db_path: str,
    academic_context_text: str,
    references_dir: Path | str,
) -> dict:
    """Buendelt Paper-Liste + Stilregeln fuer den Word-Renderer.

    Liefert Rohdaten (Papers als CSL-JSON) und den unveraenderten Stilregel-
    Text -- keine fertig formatierten Literatureintraege. Das Rendern in
    docx-Absaetze macht der Agent im word-export-Workflow (SKILL.md), analog
    zum bestehenden Citations-API-Fallback in citation-extraction.
    """
    papers = get_all_papers(db_path)
    style_file = resolve_citation_style(academic_context_text)
    style_rules = load_style_rules(style_file, references_dir)
    return {"papers": papers, "style_file": style_file, "style_rules": style_rules}


# ---------------------------------------------------------------------------
# \cite{key}-Marker-Aufloesung fuer den docx-Pfad (Plan-Risiko #1)
# ---------------------------------------------------------------------------

# Kommandoliste IMPORTIERT statt kopiert (LATEX_CITATION_COMMANDS aus
# render_tex.py) -- eine zweite, handgepflegte Allowlist wuerde bei kuenftigen
# Erweiterungen lautlos auseinanderdriften. Rohe LaTeX-Zitationsmarker aus
# kapitel/*.md (Issue #386) sind fuer Word bedeutungslos und muessen vor dem
# Einfuegen in einen docx-js-Absatz aufgeloest werden, sonst tauchen rohe
# \\cite{...}-Strings im Word-Dokument auf.
_CITE_MARKER_RE = re.compile(
    r"\\(?:" + "|".join(LATEX_CITATION_COMMANDS) + r")\*?(?:\[[^\[\]]*\])*\{([^{}]+)\}"
)


def _short_reference_body(paper: dict) -> str:
    """Baut den Kurzbeleg-Rumpf 'Nachname Jahr' aus dem CSL-JSON eines Papers.

    Ohne Klammern, damit Mehrfachzitate zu EINEM Klammerausdruck mit
    Semikolon-getrennten Belegen zusammengefasst werden koennen -- so schreiben
    es die Autor-Jahr-Stile (APA7, Harvard, Chicago) vor.

    Autor-Schwelle (Review-Fund PR #488, flowkit Runde 2): "et al." gilt in
    diesen Autor-Jahr-Stilen erst ab DREI Autoren -- bei genau zwei werden
    beide genannt ("Nachname & Nachname"). Vorher stand hier `len(authors) > 1`,
    also faelschlich schon ab zwei Autoren "et al." statt beider Namen.
    """
    try:
        csl = json.loads(paper.get("csl_json", "{}"))
    except json.JSONDecodeError:
        csl = {}

    authors = csl.get("author", [])
    if authors:
        fallback = paper.get("paper_id", "?")
        if len(authors) == 1:
            name = authors[0].get("family") or fallback
        elif len(authors) == 2:
            first = authors[0].get("family") or fallback
            second = authors[1].get("family") or fallback
            name = f"{first} & {second}"
        else:
            family = authors[0].get("family") or fallback
            name = f"{family} et al."
    else:
        name = paper.get("paper_id", "?")

    issued = csl.get("issued", {})
    date_parts = issued.get("date-parts", [[]])
    year = str(date_parts[0][0]) if date_parts and date_parts[0] else "o. J."
    return f"{name} {year}"


def _short_reference(paper: dict) -> str:
    """Klartext-Kurzzitat '(Nachname Jahr)' fuer einen einzelnen Key."""
    return f"({_short_reference_body(paper)})"


def resolve_cite_markers(text: str, papers: list[dict]) -> str:
    """Ersetzt \\cite{key}-Marker (und Varianten) durch Klartext-Kurzzitate.

    Mehrfachzitate (``\\cite{a,b}`` -- gueltiges BibTeX/biblatex und in
    kapitel/*.md real vorhanden, Issue #386) werden Key fuer Key aufgeloest und
    zu einem Klammerausdruck zusammengefasst: ``(Smith 2023; Jones et al. 2022)``.
    Die Key-Liste als Ganzes nachzuschlagen wuerde selbst bei zwei im Vault
    bekannten Papers den Platzhalter ``(? a,b)`` ins Word-Dokument schreiben.

    Unbekannte Keys werden durch '? key' ersetzt statt den Marker roh stehen
    zu lassen -- sichtbarer Hinweis statt stillem LaTeX-Leck ins Word-Dokument.
    """
    by_id = {p.get("paper_id"): p for p in papers}

    def _replace(match: re.Match[str]) -> str:
        keys = [key.strip() for key in match.group(1).split(",")]
        keys = [key for key in keys if key]
        if not keys:
            return match.group(0)
        parts = []
        for key in keys:
            paper = by_id.get(key)
            parts.append(f"? {key}" if paper is None else _short_reference_body(paper))
        return f"({'; '.join(parts)})"

    return _CITE_MARKER_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# CLI: der von commands/word.md dokumentierte Aufrufweg (Fixrunde PR #488)
# ---------------------------------------------------------------------------
#
# Vorher enthielt commands/word.md einen Inline-Python-Block in einem
# QUOTIERTEN Heredoc (`python3 - <<'PY'`). Ein quotierter Delimiter schaltet
# jede Shell-Expansion ab: ${CLAUDE_PLUGIN_ROOT}, $KAPITEL und $VAULT_DB_PATH
# blieben literal stehen, der erste Import starb mit einem rohen
# ModuleNotFoundError -- bevor `document-skills:docx` erreicht wurde.
# Gegenmittel ist dasselbe Muster wie bei latex-export nach #467/#485: eine
# echte argparse-CLI, die als normale Kommandozeile aufgerufen wird (Argumente
# expandiert die Shell dort ganz normal) und Fehler als "FEHLER: ..." meldet
# statt als Traceback (AC6).


def _resolve_vault_db_path(explicit: str | None) -> str:
    """Kanonischer Vault-Pfad -- identische Quelle wie der .bib-Pfad (AC3).

    Ohne ``--vault-db`` gilt ``academic_vault.db.default_db_path()``: exakt der
    Aufloeser, den ``latex-export/scripts/export_thesis.py`` fuer die
    ``.bib``-Erzeugung nutzt (Issue #190). Damit ist die Literatureintrag-Menge
    im docx per Konstruktion dieselbe wie im LaTeX-Pfad -- vorher stand hier
    ``$VAULT_DB_PATH``, eine im Command nirgends definierte Variable.
    """
    if explicit:
        return explicit
    from academic_vault.db import default_db_path

    return default_db_path()


def build_payload(
    selector: str,
    kapitel_dir: Path | str = DEFAULT_KAPITEL_DIR,
    academic_context_path: Path | str = DEFAULT_ACADEMIC_CONTEXT,
    references_dir: Path | str = DEFAULT_REFERENCES_DIR,
    vault_db_path: str | None = None,
) -> dict:
    """Alles, was `document-skills:docx` zum Rendern braucht, als ein dict.

    Enthaelt die Kapitel mit bereits aufgeloesten \\cite{}-Markern, die
    Paper-Rohdaten und den unveraenderten Stilregel-Text. Bewusst KEINE
    fertig formatierten Literatureintraege -- das Rendern bleibt Aufgabe des
    Agenten mit den geladenen Stilregeln (keine zweite Stilregel-
    Implementierung neben citation-extraction, siehe Modul-Docstring).
    """
    chapters = resolve_chapters(str(kapitel_dir), selector)

    context_path = Path(academic_context_path)
    academic_context_text = (
        context_path.read_text(encoding="utf-8") if context_path.is_file() else ""
    )

    resolved_db_path = _resolve_vault_db_path(vault_db_path)
    refs = collect_references(resolved_db_path, academic_context_text, references_dir)

    messages: list[str] = []
    if not context_path.is_file():
        messages.append(
            f"'{context_path}' fehlt - Zitationsstil faellt auf {DEFAULT_STYLE_FILE} zurueck."
        )
    if not refs["papers"]:
        messages.append(
            "Vault leer - Papers via `add` hinzufuegen (Literaturverzeichnis bleibt leer)."
        )

    return {
        "chapters": [
            {
                "source": chapter.name,
                "path": str(chapter),
                "body": resolve_cite_markers(chapter.read_text(encoding="utf-8"), refs["papers"]),
            }
            for chapter in chapters
        ],
        "papers": refs["papers"],
        "style_file": refs["style_file"],
        "style_rules": refs["style_rules"],
        # Titelblatt-Angaben fuer render_docx.py -- ausschliesslich Felder, die
        # academic_context.md wirklich enthaelt (siehe parse_context_fields).
        "context": parse_context_fields(academic_context_text),
        "vault_db_path": resolved_db_path,
        "messages": messages,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bereitet Kapitel + Vault-Bibliografie fuer den document-skills:docx-Schritt "
            "von /academic-research:word auf (Issue #446)."
        ),
    )
    parser.add_argument("--kapitel", required=True, help="Kapitel-Nummer oder 'all'")
    parser.add_argument(
        "--payload",
        required=True,
        help="Zieldatei fuer die JSON-Zwischenrepraesentation",
    )
    parser.add_argument("--kapitel-dir", default=DEFAULT_KAPITEL_DIR)
    parser.add_argument("--academic-context", default=DEFAULT_ACADEMIC_CONTEXT)
    parser.add_argument("--references-dir", default=str(DEFAULT_REFERENCES_DIR))
    parser.add_argument(
        "--vault-db",
        default=None,
        help="Vault-Pfad (Default: academic_vault.db.default_db_path(), wie latex-export)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        payload = build_payload(
            selector=args.kapitel,
            kapitel_dir=args.kapitel_dir,
            academic_context_path=args.academic_context,
            references_dir=args.references_dir,
            vault_db_path=args.vault_db,
        )
    except (ChapterResolutionError, StyleRulesNotFoundError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        # Vault-Modul nicht importierbar -> verstaendliche Meldung statt
        # Traceback (AC6).
        print(
            f"FEHLER: Vault-Modul 'academic_vault' nicht ladbar ({exc}). "
            "Plugin-Installation pruefen (scripts/setup.sh).",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1

    payload_path = Path(args.payload)
    if payload_path.parent != Path(""):
        payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"Vorbereitet: {payload_path} "
        f"({len(payload['chapters'])} Kapitel, {len(payload['papers'])} Literatureintraege, "
        f"Stil {payload['style_file']})"
    )
    for message in payload["messages"]:
        print(message, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
