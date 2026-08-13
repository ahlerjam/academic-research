"""Regressionstest fuer Issue #878.

Vorbedingungen im gemeinsamen Preamble heben sich von einer Existenzpruefung
(Dateien vorhanden?) zu einer Zustandspruefung (sind die Felder der aktuellen
Phase in academic_context.md tatsaechlich befuellt?). Bei nicht erfuellter
Vorbedingung wird gewarnt, nicht blockiert.

Die Preamble ist Prosa fuers Modell, kein Code — dieser Test prueft deshalb
nur, dass die noetigen Marker/Beispiele/Vorbehalte im Text vorhanden sind,
nicht dass das Modell im Lauf tatsaechlich danach handelt (siehe Plan-
Kommentar, Risiko-Abschnitt, analog Issue #905).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PREAMBLE = REPO_ROOT / "skills/_common/preamble.md"
ACADEMIC_CONTEXT_SKILL = REPO_ROOT / "skills/academic-context/SKILL.md"
WORKFLOW_PHASES = REPO_ROOT / "config/workflow-phases.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _vorbedingungen_section() -> str:
    text = _read(PREAMBLE)
    start = text.index("## Vorbedingungen")
    end = text.index("## Keine Fabrikation")
    return text[start:end]


# ---------------------------------------------------------------------------
# AC1: Meldung nennt den zustaendigen naechsten Skill
# ---------------------------------------------------------------------------


def test_vorbedingungen_section_names_research_question_refiner_as_example():
    section = _vorbedingungen_section()
    assert "research-question-refiner" in section


# ---------------------------------------------------------------------------
# AC2: Bestaetigt der Operator die Rueckfrage, laeuft der Skill trotzdem
# ---------------------------------------------------------------------------


def test_vorbedingungen_section_has_proceed_anyway_path():
    section = _vorbedingungen_section()
    assert "trotzdem" in section
    assert "AskUserQuestion" in section


# ---------------------------------------------------------------------------
# AC3: VORLAEUFIG (und TODO/OFFEN) gelten als unbelegt
# ---------------------------------------------------------------------------


def test_vorbedingungen_section_defines_unfilled_markers():
    section = _vorbedingungen_section()
    for marker in ("TODO", "OFFEN", "VORLAEUFIG"):
        assert marker in section, f"Marker '{marker}' fehlt im Vorbedingungen-Block"


# ---------------------------------------------------------------------------
# AC4: Erfuellte Vorbedingungen erzeugen keinen zusaetzlichen Overhead
# ---------------------------------------------------------------------------


def test_vorbedingungen_section_has_no_overhead_when_satisfied_guard():
    section = _vorbedingungen_section()
    assert "nur" in section.lower()
    # Die Formulierung muss den reibungslosen Normalfall explizit machen —
    # nicht nur implizit aus "Warnung bei unbelegt" folgern.
    assert "erfuellt" in section.lower() or "erfüllt" in section


# ---------------------------------------------------------------------------
# AC5: academic-context startet weiterhin ohne Vorbedingung (unveraendert)
# ---------------------------------------------------------------------------


def test_academic_context_override_unchanged():
    text = _read(ACADEMIC_CONTEXT_SKILL)
    assert "Keine Vorbedingungen" in text
    assert "dieser Skill bootet den" in text


# ---------------------------------------------------------------------------
# AC6: Fehlt academic_context.md vollstaendig, bleibt der bisherige Trigger
# ---------------------------------------------------------------------------


def test_vorbedingungen_section_keeps_missing_context_trigger():
    section = _vorbedingungen_section()
    assert "academic-context" in section
    assert "Fehlt Kontext" in section or "fehlt" in section.lower()
    # Der Ablehnungspfad (bestehendes Verhalten) muss erhalten bleiben.
    assert "erfundenes Thema" in section


# ---------------------------------------------------------------------------
# Dreiteilige Meldung laut Issue-Body: (a) fehlende Vorbedingung,
# (b) zustaendiger naechster Schritt/Skill, (c) Rueckfrage
# ---------------------------------------------------------------------------


def test_vorbedingungen_section_message_has_three_parts():
    section = _vorbedingungen_section()
    assert "unbelegt" in section.lower() or "fehlt" in section.lower()
    assert "naechst" in section.lower() or "nächst" in section


# ---------------------------------------------------------------------------
# Die neue Zustandspruefung referenziert workflow-phases.json als Quelle,
# statt die Phasenliste in Prosa zu duplizieren.
# ---------------------------------------------------------------------------


def test_vorbedingungen_section_references_workflow_phases_source():
    section = _vorbedingungen_section()
    assert "workflow-phases.json" in section


def test_workflow_phases_file_exists():
    assert WORKFLOW_PHASES.exists()
