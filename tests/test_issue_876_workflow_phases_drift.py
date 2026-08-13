"""Drift-Guard fuer config/workflow-phases.json vs. docs/guide/walkthrough.md.

Issue #876: Die Phasenkette des Forschungsprozesses existiert als
maschinenlesbare Datei mit Vorbedingungen je Phase. Dieser Test stellt
sicher, dass die Definition und der menschenlesbare Walkthrough nicht
auseinanderlaufen und dass jeder referenzierte Skill/Command real existiert.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PHASES_PATH = REPO_ROOT / "config" / "workflow-phases.json"
WALKTHROUGH_PATH = REPO_ROOT / "docs" / "guide" / "walkthrough.md"
SKILLS_DIR = REPO_ROOT / "skills"
COMMANDS_DIR = REPO_ROOT / "commands"
AGENTS_DIR = REPO_ROOT / "agents"

HEADING_PATTERN = re.compile(r"^##\s+(\d+)\.\s+(.+)$", re.MULTILINE)

# Geschlossenes Vokabular fuer preconditions[].expected (AC2: maschinell
# pruefbar statt freier Prosa). Nuancen gehoeren ins optionale 'note'-Feld,
# das NICHT gegen dieses Vokabular geprueft wird.
ALLOWED_EXPECTED_VALUES = {"filled", "checked", "checked_partial"}


def _load_phases_data() -> dict:
    with PHASES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _phase_entries(data: dict) -> list[dict]:
    """Liefert die Phasen-Liste, ohne die _comment*-Metafelder."""
    phases = data["phases"]
    assert isinstance(phases, list)
    return phases


def _walkthrough_headings() -> list[str]:
    """Extrahiert alle '## N. Titel'-Ueberschriften aus walkthrough.md."""
    text = WALKTHROUGH_PATH.read_text(encoding="utf-8")
    matches = HEADING_PATTERN.findall(text)
    return [f"{num}. {title}" for num, title in matches]


def _diff_headings_vs_phases(headings: list[str], phases: list[dict]) -> tuple[set[str], set[str]]:
    """Vergleicht Walkthrough-Ueberschriften gegen Phasen-Ueberschriften.

    Gibt (nur_im_walkthrough, nur_in_phasen) zurueck -- beide leer heisst
    kein Drift.
    """
    heading_set = set(headings)
    phase_heading_set = {p["walkthrough_heading"] for p in phases}
    only_in_walkthrough = heading_set - phase_heading_set
    only_in_phases = phase_heading_set - heading_set
    return only_in_walkthrough, only_in_phases


def _missing_skill_or_command_refs(phases: list[dict]) -> list[str]:
    """Liefert eine Liste menschenlesbarer Fehlermeldungen fuer jede Phase,
    die einen Skill/Command/Agent referenziert, den es im Repo nicht gibt."""
    missing: list[str] = []
    for phase in phases:
        phase_id = phase.get("id", "<ohne id>")
        for slug in phase.get("skills", []):
            if not (SKILLS_DIR / slug / "SKILL.md").exists():
                missing.append(f"{phase_id}: Skill '{slug}' fehlt unter skills/{slug}/SKILL.md")
        for slug in phase.get("commands", []):
            if not (COMMANDS_DIR / f"{slug}.md").exists():
                missing.append(f"{phase_id}: Command '{slug}' fehlt unter commands/{slug}.md")
        for slug in phase.get("agents", []):
            if not (AGENTS_DIR / f"{slug}.md").exists():
                missing.append(f"{phase_id}: Agent '{slug}' fehlt unter agents/{slug}.md")
    return missing


class TestWorkflowPhasesFile:
    """Die reale config/workflow-phases.json gegen walkthrough.md und den Skill-Baum."""

    def test_json_is_valid_and_parseable(self) -> None:
        """AC3 (Python-Seite): json.load liest die Datei fehlerfrei -- reines
        JSON ohne Kommentar-Syntax/Trailing Commas ist die Voraussetzung dafuer."""
        data = _load_phases_data()
        assert "phases" in data
        assert isinstance(data["phases"], list)
        assert len(data["phases"]) > 0

    def test_json_is_parseable_by_node_without_extra_dependency(self) -> None:
        """AC3 (Node-Seite, die tatsaechliche Behauptung der Datei selbst --
        config/workflow-phases.json:2 sagt 'Gelesen von Node-Hooks
        (JSON.parse)'): JSON.parse in Node muss dieselbe Datei ohne
        Zusatzabhaengigkeit lesen koennen. json.load und JSON.parse sind NICHT
        identisch (z.B. NaN/Infinity-Literale), daher hier ein echter
        Node-Aufruf statt einer Gleichsetzung im Docstring."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("node ist auf diesem System nicht installiert")
        result = subprocess.run(
            [
                node,
                "-e",
                "JSON.parse(require('fs').readFileSync(process.argv[1], 'utf-8'))",
                str(PHASES_PATH),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"JSON.parse ist an config/workflow-phases.json gescheitert: {result.stderr}"
        )

    def test_all_walkthrough_headings_have_phase(self) -> None:
        """AC1: Kein Schritt aus walkthrough.md fehlt in der Definition."""
        headings = _walkthrough_headings()
        assert len(headings) > 0, "Keine '## N. Titel'-Ueberschriften in walkthrough.md gefunden"
        phases = _phase_entries(_load_phases_data())
        only_in_walkthrough, only_in_phases = _diff_headings_vs_phases(headings, phases)
        assert not only_in_walkthrough, (
            f"Walkthrough-Schritte ohne Phase in workflow-phases.json: {only_in_walkthrough}"
        )
        assert not only_in_phases, (
            f"Phasen in workflow-phases.json ohne Entsprechung im Walkthrough: {only_in_phases}"
        )
        assert len(phases) == len(headings)

    def test_phase_order_matches_walkthrough_order(self) -> None:
        """config/workflow-phases.json erklaert sich selbst zur 'verbindlichen
        Quelle der Ablaufordnung' -- eine reine Mengengleichheit deckt eine
        vertauschte Reihenfolge im 'phases'-Array nicht ab, obwohl genau das
        der Kern von Issue #876 ist (Forschungsfrage an der falschen Stelle)."""
        headings = _walkthrough_headings()
        phases = _phase_entries(_load_phases_data())
        phase_headings_in_order = [p["walkthrough_heading"] for p in phases]
        assert phase_headings_in_order == headings, (
            "Reihenfolge von 'phases' in workflow-phases.json weicht von der "
            "Ueberschriften-Reihenfolge in walkthrough.md ab"
        )

    def test_every_phase_has_field_checkable_preconditions(self) -> None:
        """AC2: Zu jeder Phase ist maschinell pruefbar hinterlegt, welche Felder
        in academic_context.md belegt sein muessen. Ausnahme: die Startphase
        (Kontext einrichten) hat explizit keine Vorbedingung."""
        phases = _phase_entries(_load_phases_data())
        stub_text = (REPO_ROOT / "scripts" / "bootstrap" / "academic_context.stub.md").read_text(
            encoding="utf-8"
        )
        for phase in phases:
            preconditions = phase.get("preconditions")
            assert preconditions is not None, f"{phase['id']}: 'preconditions'-Feld fehlt"
            if phase.get("is_entry_point"):
                assert preconditions == [], (
                    f"{phase['id']}: Startphase sollte leere preconditions haben"
                )
                continue
            assert len(preconditions) >= 1, (
                f"{phase['id']}: keine Vorbedingung hinterlegt (nur Startphase darf das)"
            )
            for cond in preconditions:
                assert "field" in cond and "expected" in cond, (
                    f"{phase['id']}: Vorbedingung ohne 'field'/'expected': {cond}"
                )
                assert cond["field"] in stub_text, (
                    f"{phase['id']}: Feld '{cond['field']}' kommt nicht in "
                    "academic_context.stub.md vor -- nicht maschinell pruefbar"
                )
                assert cond["expected"] in ALLOWED_EXPECTED_VALUES, (
                    f"{phase['id']}: 'expected' = {cond['expected']!r} ist kein "
                    f"geschlossenes Vokabular (erlaubt: {sorted(ALLOWED_EXPECTED_VALUES)}) -- "
                    "Prosa waere nicht maschinell auswertbar; Nuancen gehoeren ins 'note'-Feld"
                )

    def test_all_referenced_skills_and_commands_exist(self) -> None:
        """AC5: CI-Test schlaegt fehl, wenn die Definition einen Skill nennt,
        den es im Repo nicht gibt. Gegen die reale Datei: gruen."""
        phases = _phase_entries(_load_phases_data())
        missing = _missing_skill_or_command_refs(phases)
        assert not missing, "Referenzen ohne Entsprechung im Repo:\n" + "\n".join(missing)


class TestDriftDetectionFiresOnMismatch:
    """AC4 (Negativtest): Der Vergleichsmechanismus muss auf Inline-Fixtures
    tatsaechlich rot werden -- sonst waere der Guard wirkungslos."""

    def test_extra_phase_not_in_walkthrough_is_detected(self) -> None:
        headings = ["1. Kontext einrichten", "2. Thema finden"]
        phases = [
            {"id": "context-setup", "walkthrough_heading": "1. Kontext einrichten"},
            {"id": "topic-finding", "walkthrough_heading": "2. Thema finden"},
            {"id": "ghost-phase", "walkthrough_heading": "99. Erfundene Phase"},
        ]
        only_in_walkthrough, only_in_phases = _diff_headings_vs_phases(headings, phases)
        assert only_in_walkthrough == set()
        assert only_in_phases == {"99. Erfundene Phase"}

    def test_missing_phase_for_walkthrough_step_is_detected(self) -> None:
        headings = ["1. Kontext einrichten", "2. Thema finden", "3. Forschungsfrage schaerfen"]
        phases = [
            {"id": "context-setup", "walkthrough_heading": "1. Kontext einrichten"},
            {"id": "topic-finding", "walkthrough_heading": "2. Thema finden"},
        ]
        only_in_walkthrough, only_in_phases = _diff_headings_vs_phases(headings, phases)
        assert only_in_walkthrough == {"3. Forschungsfrage schaerfen"}
        assert only_in_phases == set()

    def test_swapped_phase_order_is_not_masked_by_set_equality(self) -> None:
        """Regression fuer die Luecke im Review: gleiche Menge, vertauschte
        Reihenfolge muss die Mengenpruefung passieren lassen (kein False
        Positive dort) UND vom Reihenfolge-Vergleich erkannt werden."""
        headings = ["1. Kontext einrichten", "2. Thema finden", "3. Forschungsfrage schaerfen"]
        phases = [
            {"id": "research-question", "walkthrough_heading": "3. Forschungsfrage schaerfen"},
            {"id": "context-setup", "walkthrough_heading": "1. Kontext einrichten"},
            {"id": "topic-finding", "walkthrough_heading": "2. Thema finden"},
        ]
        only_in_walkthrough, only_in_phases = _diff_headings_vs_phases(headings, phases)
        assert only_in_walkthrough == set()
        assert only_in_phases == set()
        phase_headings_in_order = [p["walkthrough_heading"] for p in phases]
        assert phase_headings_in_order != headings, (
            "Testaufbau fehlerhaft: die Fixture muss tatsaechlich vertauscht sein"
        )

    def test_unenumerated_expected_value_is_rejected(self) -> None:
        """Regression fuer die Luecke im Review: 'expected' als freie Prosa
        (z.B. 'wenn es passt') muss gegen das Vokabular durchfallen."""
        assert "wenn es passt" not in ALLOWED_EXPECTED_VALUES
        assert "filled" in ALLOWED_EXPECTED_VALUES
        assert "checked" in ALLOWED_EXPECTED_VALUES
        assert "checked_partial" in ALLOWED_EXPECTED_VALUES

    def test_matching_headings_and_phases_produce_no_drift(self) -> None:
        headings = ["1. Kontext einrichten", "2. Thema finden"]
        phases = [
            {"id": "context-setup", "walkthrough_heading": "1. Kontext einrichten"},
            {"id": "topic-finding", "walkthrough_heading": "2. Thema finden"},
        ]
        only_in_walkthrough, only_in_phases = _diff_headings_vs_phases(headings, phases)
        assert only_in_walkthrough == set()
        assert only_in_phases == set()

    def test_missing_skill_reference_fails(self) -> None:
        phases = [
            {
                "id": "fake-phase",
                "skills": ["dieser-skill-existiert-nicht-876"],
                "commands": [],
                "agents": [],
            }
        ]
        missing = _missing_skill_or_command_refs(phases)
        assert len(missing) == 1
        assert "dieser-skill-existiert-nicht-876" in missing[0]

    def test_missing_command_reference_fails(self) -> None:
        phases = [
            {
                "id": "fake-phase",
                "skills": [],
                "commands": ["kommando-gibt-es-nicht-876"],
                "agents": [],
            }
        ]
        missing = _missing_skill_or_command_refs(phases)
        assert len(missing) == 1
        assert "kommando-gibt-es-nicht-876" in missing[0]

    def test_missing_agent_reference_fails(self) -> None:
        phases = [
            {
                "id": "fake-phase",
                "skills": [],
                "commands": [],
                "agents": ["agent-gibt-es-nicht-876"],
            }
        ]
        missing = _missing_skill_or_command_refs(phases)
        assert len(missing) == 1
        assert "agent-gibt-es-nicht-876" in missing[0]

    def test_valid_references_produce_no_missing_entries(self) -> None:
        phases = [
            {
                "id": "context-setup",
                "skills": ["academic-context"],
                "commands": ["search"],
                "agents": ["book-fetcher"],
            }
        ]
        assert _missing_skill_or_command_refs(phases) == []


@pytest.mark.skipif(not PHASES_PATH.exists(), reason="config/workflow-phases.json fehlt noch")
class TestWalkthroughReferencesDefinition:
    """AC: walkthrough.md verweist auf die Definition als verbindliche Quelle."""

    def test_walkthrough_mentions_workflow_phases_json(self) -> None:
        text = WALKTHROUGH_PATH.read_text(encoding="utf-8")
        assert "config/workflow-phases.json" in text
