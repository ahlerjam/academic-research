"""check_layout.py -- deterministische Pruefregeln fuer latex-layout-auditor (#392).

Reine Pruef-Logik ohne Seiteneffekte: ``audit_tex(text) -> list[Finding]``.
Deckt die beiden im Issue #392 genannten Digest-Befunde zu
``skills/latex-export/scripts/render_tex.py`` ab -- hier nur als Finding
erkannt, nicht repariert (Scope-Abgrenzung laut Issue):

1. ``missing-tightlist-definition`` -- ``\\tightlist`` wird in einer Liste
   verwendet, ohne dass ``\\providecommand{\\tightlist}`` oder
   ``\\newcommand{\\tightlist}`` irgendwo im Dokument definiert ist. Ohne
   diese Definition bricht pdflatex mit "Undefined control sequence
   \\tightlist" ab (vgl. Issue #386, das den render_tex.py-Renderpfad selbst
   gefixt hat -- dieser Auditor erkennt dasselbe Muster in beliebigen,
   auch manuell editierten .tex-Dateien).
2. ``corrupted-cite-command`` -- ein Zitationskommando wurde durch
   nachtraegliches Escaping korrumpiert, z. B. ``\\textbackslash{}cite{key}``
   statt ``\\cite{key}``. Das Muster entsteht, wenn ein bereits vorhandenes
   LaTeX-Kommando im Markdown-Quelltext ein zweites Mal escaped wird.

Diese Datei ist Test-/Aufrufinfrastruktur fuer die pytest-Beweisbarkeit der
Akzeptanzkriterien (AC2-AC4). Der Skill selbst ist read-only (``allowed-tools:
[Read]``, Issue-Scope) und wendet dieselben Regeln beim Lesen einer .tex-Datei
per Musterabgleich an, statt dieses Skript zur Laufzeit auszufuehren.

Oeffentliche API:
    audit_tex(text: str) -> list[Finding]
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Zitations-/Referenzkommandos, deren Korruption dieser Auditor erkennt.
#: Deckungsgleich mit LATEX_CITATION_COMMANDS in
#: skills/latex-export/scripts/render_tex.py (bewusst dupliziert statt
#: importiert -- der Auditor ist ein eigenstaendiges Read-only-Werkzeug ohne
#: Laufzeit-Abhaengigkeit auf latex-export).
_CITATION_COMMANDS = ("cite", "citep", "citet", "parencite", "footcite")

_TIGHTLIST_USAGE_RE = re.compile(r"^\s*\\tightlist\s*$")
_TIGHTLIST_DEFINITION_RE = re.compile(r"\\(?:providecommand|newcommand)\{\\tightlist\}")
_CORRUPTED_CITE_RE = re.compile(
    r"\\textbackslash\{\}(?:" + "|".join(_CITATION_COMMANDS) + r")\*?\{"
)


@dataclass
class Finding:
    """Ein einzelner Auditor-Fund: Regel, Fundort (Zeile) und Kontext-Snippet."""

    rule: str
    line: int
    snippet: str
    message: str


def _check_missing_tightlist(lines: list[str]) -> list[Finding]:
    has_definition = any(_TIGHTLIST_DEFINITION_RE.search(line) for line in lines)
    if has_definition:
        return []
    findings: list[Finding] = []
    for idx, line in enumerate(lines, start=1):
        if _TIGHTLIST_USAGE_RE.match(line):
            findings.append(
                Finding(
                    rule="missing-tightlist-definition",
                    line=idx,
                    snippet=line.strip(),
                    message=(
                        f"Zeile {idx}: \\tightlist ohne vorangehende "
                        r"\providecommand{\tightlist}"
                        "-Definition -- pdflatex bricht mit "
                        '"Undefined control sequence" ab.'
                    ),
                )
            )
    return findings


def _check_corrupted_cite(lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for idx, line in enumerate(lines, start=1):
        for match in _CORRUPTED_CITE_RE.finditer(line):
            findings.append(
                Finding(
                    rule="corrupted-cite-command",
                    line=idx,
                    snippet=line.strip(),
                    message=(
                        f"Zeile {idx}: korrumpiertes Zitationskommando "
                        f"'{match.group(0)}...' -- vermutlich doppelt "
                        r"escaptes \cite{}."
                    ),
                )
            )
    return findings


def audit_tex(text: str) -> list[Finding]:
    """Prueft LaTeX-Quelltext auf die deterministischen Layout-Regeln.

    Gibt eine Liste von Findings zurueck (leer, wenn keine Regel greift).
    Reihenfolge: erst tightlist-Funde, dann cite-Funde, jeweils nach Zeile
    aufsteigend sortiert.
    """
    lines = text.splitlines()
    findings = _check_missing_tightlist(lines) + _check_corrupted_cite(lines)
    return sorted(findings, key=lambda f: f.line)
