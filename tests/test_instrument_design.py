"""Tests fuer Issue #473 AC1 — Erhebungsinstrument mit Rueckbezug zur Forschungsfrage.

Der Skill ist reine Prosa (kein Skript): das Erzeugen eines Leitfadens ist eine
Modellleistung. Deterministisch pruefbar ist daher die Vertragsseite —
dass die Anleitung die Rueckverweis-Matrix als Pflichtausgabe fuehrt, ohne
Forschungsfrage abbricht statt zu raten, und sich von ``methodology-advisor``
abgrenzt. Die verhaltensseitige Pruefung liegt in ``evals/instrument-design/``
und ist API-gated (Status ``structural`` in ``docs/evals/STRATEGY.md``) — das
ist kein Ersatz fuer diese Assertions, sondern ihre Ergaenzung.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / "skills" / "instrument-design" / "SKILL.md"


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _description() -> str:
    m = re.match(r"^---\n(.*?)\n---", _text(), re.DOTALL)
    assert m, "kein Frontmatter"
    dm = re.search(
        r"^description:\s*(.*?)(?=^[a-zA-Z_][a-zA-Z0-9_-]*:|\Z)", m.group(1), re.DOTALL | re.M
    )
    assert dm, "keine description im Frontmatter"
    return " ".join(dm.group(1).split())


def _section(heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", _text(), re.M | re.S)
    assert m, f"Section '## {heading}' fehlt in {SKILL_MD}"
    return m.group(1)


def test_skill_exists():
    assert SKILL_MD.exists(), f"{SKILL_MD} fehlt"


def test_description_targets_erhebungsinstrument():
    desc = _description()
    for phrase in ("Interviewleitfaden", "Fragebogen"):
        assert phrase in desc, f"Trigger-Phrase '{phrase}' fehlt in der description"


def test_rueckverweis_matrix_is_mandatory_output():
    """Jede Frage muss auf eine Unterfrage/Forschungsfrage zurueckgefuehrt werden."""
    text = _text()
    assert "Rückverweis-Matrix" in text, "Rückverweis-Matrix wird nicht als Ausgabe gefuehrt"
    matrix = _section("Rückverweis-Matrix")
    assert "| Frage" in matrix, "Matrix hat keine Spalte 'Frage'"
    assert re.search(r"Unterfrage\s*/\s*FF", matrix), (
        "Matrix ordnet Fragen nicht Unterfrage/Forschungsfrage zu"
    )
    assert "Pflicht" in matrix, "Matrix ist nicht als Pflichtausgabe gekennzeichnet"


def test_aborts_without_research_question():
    """Ohne Forschungsfrage kein Instrument, sondern Verweis auf academic-context."""
    text = _text()
    assert "academic_context.md" in text
    assert "academic-context" in text
    assert "research-question-refiner" in text
    assert re.search(r"(brich ab|Abbruch|kein Instrument)", text, re.I), (
        "Kein Abbruchpfad fuer eine fehlende Forschungsfrage dokumentiert"
    )


def test_delimits_against_methodology_advisor():
    abgrenzung = _section("Abgrenzung")
    assert "methodology-advisor" in abgrenzung, (
        "Abgrenzung zu methodology-advisor (Methodenwahl) fehlt"
    )
    assert "qualitative-coding" in abgrenzung, "Abgrenzung zu qualitative-coding (Auswertung) fehlt"


def test_does_not_fabricate_sample_or_ethics_advice():
    """Scope 'Out': keine Erhebungsdurchfuehrung, keine Datenschutz-Beratung."""
    text = _text()
    assert re.search(r"Datenschutz", text), "Kein Hinweis zur Datenschutz-Abgrenzung"
    assert re.search(r"(keine Rechts|keine Datenschutz-Beratung|ersetzt keine)", text, re.I), (
        "Datenschutz wird erwaehnt, aber nicht als Nicht-Beratung abgegrenzt"
    )
