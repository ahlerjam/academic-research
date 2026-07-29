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

import json
import re
import sys
from pathlib import Path

# Geschwister-Skill latex-export liefert die kanonische Vault-Query. Import
# statt Kopie ist hartes Muss (nicht nur Empfehlung), siehe Modul-Docstring.
_LATEX_EXPORT_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "latex-export" / "scripts"
if str(_LATEX_EXPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LATEX_EXPORT_SCRIPTS))

from build_bib import get_all_papers  # noqa: E402  (bewusster Re-Export)

__all__ = [
    "get_all_papers",
    "resolve_citation_style",
    "load_style_rules",
    "collect_references",
    "resolve_cite_markers",
    "StyleRulesNotFoundError",
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

# Gleiche Kommando-Allowlist wie render_tex.py (_LATEX_SAFE_COMMANDS): rohe
# LaTeX-Zitationsmarker aus kapitel/*.md (Issue #386) sind fuer Word bedeutungs-
# los und muessen vor dem Einfuegen in einen docx-js-Absatz aufgeloest werden,
# sonst tauchen rohe \\cite{...}-Strings im Word-Dokument auf.
_CITE_MARKER_RE = re.compile(
    r"\\(?:cite|citep|citet|parencite|footcite)\*?(?:\[[^\[\]]*\])*\{([^{}]+)\}"
)


def _short_reference(paper: dict) -> str:
    """Baut ein Klartext-Kurzzitat '(Nachname Jahr)' aus dem CSL-JSON eines Papers."""
    try:
        csl = json.loads(paper.get("csl_json", "{}"))
    except json.JSONDecodeError:
        csl = {}

    authors = csl.get("author", [])
    if authors:
        family = authors[0].get("family") or paper.get("paper_id", "?")
        suffix = " et al." if len(authors) > 1 else ""
        name = f"{family}{suffix}"
    else:
        name = paper.get("paper_id", "?")

    issued = csl.get("issued", {})
    date_parts = issued.get("date-parts", [[]])
    year = str(date_parts[0][0]) if date_parts and date_parts[0] else "o. J."
    return f"({name} {year})"


def resolve_cite_markers(text: str, papers: list[dict]) -> str:
    """Ersetzt \\cite{key}-Marker (und Varianten) durch Klartext-Kurzzitate.

    Unbekannte Keys werden durch '(? key)' ersetzt statt den Marker roh stehen
    zu lassen -- sichtbarer Hinweis statt stillem LaTeX-Leck ins Word-Dokument.
    """
    by_id = {p.get("paper_id"): p for p in papers}

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        paper = by_id.get(key)
        if paper is None:
            return f"(? {key})"
        return _short_reference(paper)

    return _CITE_MARKER_RE.sub(_replace, text)
