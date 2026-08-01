"""Tests fuer Issue #530 — possible_pdf_mismatch blockiert Persistierung (Audit R4).

TDD-First: Tests schreiben BEVOR die Implementierung existiert.

Textbasierte Struktur-Assertions analog
`tests/test_material_passport_skill.py::TestReproLockAskUserQuestionGate`
(Precedent aus #536). Skill-/Agent-Dateien sind Prompt-Instruktionen, keine
ausfuehrbare Logik — Tests pruefen Reihenfolge, Vorhandensein und
Optionslabels, kein Laufzeit-Beweis.

Assertions werden ab dem konkreten Abschnitt verankert (## Vault-Persistenz,
#### PDF-Mismatch-Gate, Schritt-3/4-Grenzen), NICHT global ueber die
Gesamtdatei — sonst waere die Suche tautologisch (#536-Learning).
"""

from __future__ import annotations

import re
from pathlib import Path

_WORKTREE_ROOT = Path(__file__).parent.parent
_SKILL_MD = _WORKTREE_ROOT / "skills" / "citation-extraction" / "SKILL.md"
_AGENT_MD = _WORKTREE_ROOT / "agents" / "quote-extractor.md"


def _section(content: str, start_heading: str, end_heading: str) -> str:
    start_idx = content.find(start_heading)
    end_idx = content.find(end_heading)
    assert start_idx != -1, f"Abschnitt '{start_heading}' nicht gefunden"
    assert end_idx != -1, f"Abschnitt '{end_heading}' nicht gefunden"
    assert start_idx < end_idx, f"'{start_heading}' liegt nicht vor '{end_heading}'"
    return content[start_idx:end_idx]


# ---------------------------------------------------------------------------
# AC1: kein Zitat eines Mismatch-Papers ohne dokumentierte Freigabe persistiert
# ---------------------------------------------------------------------------


class TestAgentConditionalPersistence:
    """agents/quote-extractor.md: vault.add_quote() ist an possible_pdf_mismatch geknuepft."""

    def _vault_persistenz_section(self) -> str:
        content = _AGENT_MD.read_text(encoding="utf-8")
        start_idx = content.find("## Vault-Persistenz")
        end_idx = content.find("## Strategie")
        assert start_idx != -1, "'## Vault-Persistenz' nicht gefunden"
        assert end_idx != -1, "'## Strategie' nicht gefunden"
        return content[start_idx:end_idx]

    def test_add_quote_call_is_conditioned_on_mismatch_flag(self):
        section = self._vault_persistenz_section()
        assert "possible_pdf_mismatch" in section, (
            "Vault-Persistenz-Abschnitt muss possible_pdf_mismatch referenzieren"
        )
        assert "mismatch_override" in section, (
            "Vault-Persistenz-Abschnitt muss mismatch_override als Override-Pfad nennen"
        )
        # Der tatsaechliche Code-Aufruf im Python-Code-Block (nicht die Prosa davor)
        # muss durch eine echte Bedingung geschuetzt sein.
        code_block_match = re.search(r"```python\s+# result:.*?(?=\n```)", section, re.DOTALL)
        assert code_block_match, "Python-Code-Block mit Bedingungslogik nicht gefunden"
        code_block = code_block_match.group(0)
        # Pruefe auf die Bedingungszeile im echten Code (nicht nur in der Prosa).
        assert re.search(r"if\s+.*mismatch", code_block, re.IGNORECASE), (
            "Code-Block muss eine echte if-Bedingung mit 'mismatch' enthalten, "
            "nicht nur prosa-seitige Erwaehnung"
        )
        # Pruefe, dass vault.add_quote() NACH dieser Bedingung aufgerufen wird.
        add_quote_idx = code_block.find("vault.add_quote(")
        if_idx = code_block.find("if")
        assert if_idx != -1 and add_quote_idx != -1, (
            "Code-Block muss Bedingung vor vault.add_quote() enthalten"
        )
        assert if_idx < add_quote_idx, "if-Bedingung muss VOR vault.add_quote() stehen"

    def test_skip_path_sets_vault_quote_id_null(self):
        section = self._vault_persistenz_section()
        assert "vault_quote_id" in section and "null" in section, (
            "Skip-Pfad muss vault_quote_id: null dokumentieren"
        )

    def test_input_format_documents_mismatch_override_field(self):
        content = _AGENT_MD.read_text(encoding="utf-8")
        input_idx = content.find("## Input-Format")
        output_idx = content.find("## Output-Format")
        assert input_idx != -1 and output_idx != -1
        input_section = content[input_idx:output_idx]
        assert "mismatch_override" in input_section, (
            "Input-Format muss das optionale Feld mismatch_override dokumentieren"
        )


class TestSkillNoLongerDescribesUngatedPersistence:
    """SKILL.md darf Persistenz bei Mismatch nicht mehr als automatisch/ungegated beschreiben."""

    def test_step4_delegates_mismatch_to_the_gate(self):
        """Schritt 4 muss auf das Gate verweisen, nicht nur alte Prosa vermeiden.

        Eine reine Negativ-Assertion ('alte Formulierung kommt nicht vor') waere
        auch ohne die Implementierung gruen — den Satz gab es auf main nie in
        genau dieser Form. Geprueft wird deshalb positiv, dass der
        Mismatch-Punkt an das Gate delegiert.
        """
        content = _SKILL_MD.read_text(encoding="utf-8")
        step4 = _section(content, "### 4. Qualitätsprüfung", "## Export-Formate")
        mismatch_lines = [ln for ln in step4.splitlines() if "possible_pdf_mismatch" in ln]
        assert mismatch_lines, "Schritt 4 muss possible_pdf_mismatch behandeln"
        joined = " ".join(mismatch_lines)
        assert "Gate" in joined, (
            "Der Mismatch-Punkt in Schritt 4 muss auf das PDF-Mismatch-Gate "
            f"verweisen statt eigenstaendig zu flaggen — gefunden: {joined!r}"
        )
        assert "flaggen" not in joined or "kein" in joined.lower(), (
            "Schritt 4 darf Mismatches nicht mehr eigenstaendig flaggen"
        )

    def test_step3_binds_persistence_to_the_mismatch_flag(self):
        """Schritt 3 muss die Persistenz an die Bedingung knuepfen.

        Auch hier positiv geprueft: dass 'automatisch' fehlt, sagt fuer sich
        genommen nichts — es muss die Kopplung an possible_pdf_mismatch bzw.
        mismatch_override dastehen.
        """
        content = _SKILL_MD.read_text(encoding="utf-8")
        step3 = _section(content, "### 3. Zitat-Extraktion", "### 4. Qualitätsprüfung")
        assert "persistiert die Zitate automatisch via" not in step3, (
            "Schritt 3 darf Persistenz nicht mehr pauschal als automatisch beschreiben"
        )
        assert "possible_pdf_mismatch" in step3 and "mismatch_override" in step3, (
            "Schritt 3 muss die Persistenz explizit an possible_pdf_mismatch und "
            "den Override-Pfad binden"
        )


# ---------------------------------------------------------------------------
# AC2: Freigabe als strukturierte AskUserQuestion-Auswahl, nicht Prosa
# ---------------------------------------------------------------------------


class TestMismatchAskUserQuestionGate:
    """SKILL.md bindet die Mismatch-Freigabe an ein echtes AskUserQuestion-Gate."""

    def _gate_section(self) -> str:
        content = _SKILL_MD.read_text(encoding="utf-8")
        return _section(content, "#### PDF-Mismatch-Gate", "### 4. Qualitätsprüfung")

    def test_allowed_tools_declares_ask_user_question(self):
        content = _SKILL_MD.read_text(encoding="utf-8")
        frontmatter = content.split("---")[1]
        assert "AskUserQuestion" in frontmatter, (
            "SKILL.md nutzt AskUserQuestion fuer das Mismatch-Gate, "
            "muss es aber auch in allowed-tools deklarieren"
        )

    def test_gate_section_exists_and_precedes_result_presentation(self):
        content = _SKILL_MD.read_text(encoding="utf-8")
        gate_idx = content.find("#### PDF-Mismatch-Gate")
        step4_idx = content.find("### 4. Qualitätsprüfung")
        assert gate_idx != -1, "'#### PDF-Mismatch-Gate' Abschnitt fehlt"
        assert gate_idx < step4_idx, "Gate muss vor Schritt 4 stehen"

    def test_gate_uses_ask_user_question(self):
        gate = self._gate_section()
        assert "AskUserQuestion" in gate, (
            "Gate-Abschnitt muss AskUserQuestion beschreiben, nicht nur Prosa"
        )

    def test_gate_has_at_least_three_option_lines_with_required_labels(self):
        gate = self._gate_section()
        option_lines = [line for line in gate.splitlines() if line.strip().startswith("-")]
        assert len(option_lines) >= 3, (
            f"Gate muss mindestens 3 AskUserQuestion-Optionszeilen haben, gefunden: {len(option_lines)}"
        )
        joined = "\n".join(option_lines).lower()
        for label in ("fortfahren", "überspringen", "prüfen"):
            assert label in joined, f"Optionszeile mit Label '{label}' fehlt im Gate"


# ---------------------------------------------------------------------------
# AC3: "Paper überspringen" -> ausgelassen im Abschlussreport, nicht erfolgreich
# ---------------------------------------------------------------------------


class TestSkipOptionAndResultPresentation:
    def _gate_section(self) -> str:
        content = _SKILL_MD.read_text(encoding="utf-8")
        return _section(content, "#### PDF-Mismatch-Gate", "### 4. Qualitätsprüfung")

    def test_skip_option_no_vault_exclusion_for_transient_errors(self):
        """Skip-Option darf nicht in excluded_sources schreiben (transiente Fehler != methodischer Ausschluss)."""
        gate = self._gate_section()
        skip_lines = [line for line in gate.splitlines() if "überspringen" in line.strip().lower()]
        assert skip_lines, "Keine Optionszeile mit 'überspringen' gefunden"
        skip_idx = gate.find(skip_lines[0])
        # Folgesatz/-block direkt nach der Optionszeile durchsuchen.
        follow_up = gate[skip_idx : skip_idx + 300]
        # Skip-Option darf NICHT vault.add_excluded_source enthalten.
        assert "vault.add_excluded_source" not in follow_up, (
            "'Paper überspringen'-Option darf vault.add_excluded_source NICHT referenzieren "
            "(transiente Fehler gehören nicht in excluded_sources)"
        )
        # Skip-Option muss explizit sessionlokal/nicht-persistent sein.
        # Beide Haelften case-insensitiv pruefen: die Optionszeile beginnt mit
        # "Sessionlokal", ein Vergleich gegen das kleingeschriebene Literal
        # traf deshalb nie zu und liess die Bedingung an der zweiten Haelfte
        # haengen.
        assert "sessionlokal" in follow_up.lower() or "kein persist" in follow_up.lower(), (
            "'Paper überspringen'-Option muss explizit dokumentieren, dass es sessionlokal ist"
        )

    def test_step4_separates_successful_and_excluded_groups(self):
        content = _SKILL_MD.read_text(encoding="utf-8")
        step4 = _section(content, "### 4. Qualitätsprüfung", "## Export-Formate")
        lower = step4.lower()
        # Beide Gruppen muessen als getrennte Aufzaehlungspunkte auftauchen, nicht vermischt.
        # Suche nach Bullet-Zeilen (^- **Label**).
        success_bullet = re.search(r"^\s*-\s+\*\*.*erfolgreich", lower, re.MULTILINE)
        excluded_bullet = re.search(r"^\s*-\s+\*\*.*ausgelassen", lower, re.MULTILINE)
        assert success_bullet, (
            "Schritt 4 muss eine Bullet-Zeile mit 'erfolgreich' enthalten "
            "(Format: - **...erfolgreich**)"
        )
        assert excluded_bullet, (
            "Schritt 4 muss eine Bullet-Zeile mit 'ausgelassen' enthalten "
            "(Format: - **...ausgelassen**)"
        )
        # Stelle sicher, dass beide Bullet-Zeilen voneinander getrennt sind.
        assert success_bullet.start() != excluded_bullet.start(), (
            "Erfolgreich- und Ausgelassen-Labels muessen als getrennte Bullet-Zeilen stehen"
        )


# ---------------------------------------------------------------------------
# "Wichtige Regeln"-Bullet verweist auf das Gate
# ---------------------------------------------------------------------------


class TestWichtigeRegelnReferencesGate:
    def test_mismatch_bullet_references_gate(self):
        content = _SKILL_MD.read_text(encoding="utf-8")
        regeln_idx = content.find("## Wichtige Regeln")
        assert regeln_idx != -1, "'## Wichtige Regeln' Abschnitt fehlt"
        regeln_section = content[regeln_idx:]
        # Gezielt DEN Mismatch-Bullet pruefen: 'gate' irgendwo im Abschnitt
        # stammt sonst aus dem unveraenderten Schritt-6-Bullet und waere auch
        # ohne diese Aenderung gruen.
        mismatch_bullets = [
            ln
            for ln in regeln_section.splitlines()
            if ln.lstrip().startswith("-") and "ismatch" in ln
        ]
        assert mismatch_bullets, "Wichtige-Regeln-Abschnitt braucht einen Mismatch-Bullet"
        joined = " ".join(mismatch_bullets)
        assert "Gate" in joined, (
            "Der Mismatch-Bullet in 'Wichtige Regeln' muss auf das Gate verweisen, "
            f"statt eigenstaendiger Flag-Prosa — gefunden: {joined!r}"
        )
