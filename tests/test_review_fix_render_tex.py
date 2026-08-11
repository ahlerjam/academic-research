"""Regressionstest fuer Finding 14 (Code-Review render_tex.py):

_escape_tex_text() escaped laut Docstring "& % $ # ^ ~ { }", liess geschweifte
Klammern aber unveraendert durch. In der exportierten .tex wird eine
unescapte '{' / '}' als LaTeX-GRUPPE interpretiert -- der Inhalt verschwindet
im kompilierten PDF, oder bei unbalancierten Klammern bricht pdflatex mit
"Runaway argument" / "Too many }'s" ab.

Fix: '{' und '}' werden wie die anderen Sonderzeichen escaped -- und zwar in
einem echten Single-Pass (regex-basiert), damit der von der Backslash-
Ersetzung eingefuegte Text ('\\textbackslash{}', enthaelt literale { } )
nicht ein zweites Mal durch die {-/}-Ersetzung laeuft (Doppel-Escaping).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "latex-export" / "scripts"))

from render_tex import _escape_tex_text  # noqa: E402


def test_geschweifte_klammern_werden_escaped():
    """Menge {1,2,3} darf im PDF nicht als Gruppe verschwinden (Kernbefund)."""
    result = _escape_tex_text("Menge {1,2,3}")
    assert result == r"Menge \{1,2,3\}"


def test_einzelne_oeffnende_klammer():
    """Eine unbalancierte oeffnende Klammer darf pdflatex nicht crashen lassen."""
    result = _escape_tex_text("die Menge {a, b")
    assert result == r"die Menge \{a, b"


def test_einzelne_schliessende_klammer():
    """Eine unbalancierte schliessende Klammer muss ebenfalls escaped werden."""
    result = _escape_tex_text("Ergebnis: 42}")
    assert result == r"Ergebnis: 42\}"


def test_alle_sonderzeichen_gleichzeitig_kein_doppel_escaping():
    """Alle Sonderzeichen inkl. literalem Backslash in einem String.

    Kritischer Fall aus dem Finding: der durch die Backslash-Ersetzung
    eingefuegte Text '\\textbackslash{}' enthaelt selbst literale { } --
    diese duerfen NICHT ein zweites Mal escaped werden (kein
    '\\textbackslash\\{\\}').
    """
    raw = "\\&%$#^~{}"
    result = _escape_tex_text(raw)
    assert result == (
        r"\textbackslash{}"
        r"\&"
        r"\%"
        r"\$"
        r"\#"
        r"\textasciicircum{}"
        r"\textasciitilde{}"
        r"\{"
        r"\}"
    )
    # Explizit sicherstellen, dass der Backslash-Ersatz selbst nicht
    # nochmal escaped wurde (kein doppeltes Escaping der eingefuegten { }).
    assert r"\textbackslash\{\}" not in result


def test_bereits_escaped_aussehender_input_wird_nicht_doppelt_escaped():
    """Ein literaler Backslash gefolgt von einer offenen Klammer im
    Markdown-Quelltext (sieht aus wie bereits escaped) muss trotzdem korrekt
    behandelt werden: Backslash und Klammer sind zwei unabhaengige Zeichen
    im Rohtext und werden beide einzeln (aber je nur einmal) escaped.
    """
    raw = "\\{"  # zwei Zeichen: Backslash, dann '{'
    result = _escape_tex_text(raw)
    assert result == r"\textbackslash{}" + r"\{"


def test_ampersand_prozent_dollar_raute_bleiben_korrekt_escaped():
    """Bereits vorher funktionierende Escapes duerfen nicht regressen."""
    result = _escape_tex_text("A & B: 50% ($x #1)")
    assert result == r"A \& B: 50\% (\$x \#1)"


def test_zitationskommandos_bleiben_unveraendert_bei_geschweiften_klammern():
    """Der Braces-Fix darf den bestehenden Passthrough fuer \\cite{key} etc.
    nicht brechen -- diese Spans werden bewusst NICHT escaped (Issue #386)."""
    result = _escape_tex_text("Siehe \\cite{Meier2020} zur Menge {1,2}.")
    assert result == r"Siehe \cite{Meier2020} zur Menge \{1,2\}."
