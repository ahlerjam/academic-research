"""Tests fuer Issue #518 — Kapitel-Zitat-Zuordnung als echtes AskUserQuestion-Gate.

TDD-First: Tests schreiben BEVOR SKILL.md angepasst wird (Rot-Beweis).

Analog zu `tests/test_material_passport_skill.py::TestReproLockAskUserQuestionGate`
(Praezedenzfall #536/PR #567) — Prosa-Regel wird durch ein echtes
`AskUserQuestion`-Gate ersetzt, statt nur als Bullet-Point zu existieren.
"""

from __future__ import annotations

from pathlib import Path

_WORKTREE_ROOT = Path(__file__).parent.parent
_SKILL_MD = _WORKTREE_ROOT / "skills" / "citation-extraction" / "SKILL.md"


def _step6_text(content: str) -> str:
    step6_idx = content.find("### 6. Kapitelzuordnung")
    step7_idx = content.find("### 7. Literaturstatus")
    assert step6_idx != -1, "Schritt 6 'Kapitelzuordnung' nicht gefunden"
    assert step7_idx != -1, "Schritt 7 'Literaturstatus' nicht gefunden"
    return content[step6_idx:step7_idx]


class TestChapterMappingAskUserQuestionGate:
    """SKILL.md bindet die Kapitel-Zuordnung an ein echtes AskUserQuestion-Gate."""

    def test_allowed_tools_declares_ask_user_question(self):
        """Voraussetzung fuer AC1: Skill darf AskUserQuestion ueberhaupt aufrufen."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        frontmatter = content.split("---")[1]
        assert "AskUserQuestion" in frontmatter, (
            "SKILL.md nutzt AskUserQuestion fuer das Kapitelzuordnungs-Gate, "
            "muss es aber auch in allowed-tools deklarieren"
        )

    def test_ask_user_question_gate_precedes_downstream_use(self):
        """AC1: Gate steht in Schritt 6 UND textuell vor jeder Weiterverwendung/Export."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        step6_text = _step6_text(content)
        assert "AskUserQuestion" in step6_text, (
            "Schritt 6 muss ein AskUserQuestion-Gate beschreiben, nicht nur Prosa "
            "('User bestaetigt Zuordnungen')"
        )

        ask_idx = content.find("AskUserQuestion")
        export_heading_idx = content.find("## Export-Formate")
        assert export_heading_idx != -1, "Abschnitt 'Export-Formate' nicht gefunden"
        assert ask_idx < export_heading_idx, (
            "Das AskUserQuestion-Gate muss textuell VOR jeder Weiterverwendung/"
            "jedem Export der Kapitel-Zuordnung stehen"
        )

    def test_gate_has_at_least_two_structured_options(self):
        """AC1: Gate bietet mindestens 2 strukturierte Optionen (Uebernehmen/Ablehnen)."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        step6_text = _step6_text(content)
        option_lines = [line for line in step6_text.splitlines() if line.strip().startswith("-")]
        assert len(option_lines) >= 2, (
            "Schritt 6 muss mindestens 2 AskUserQuestion-Optionszeilen enthalten "
            f"(gefunden: {len(option_lines)})"
        )

    def test_reject_path_discards_mapping_without_vault_write(self):
        """AC2: Ablehnung verwirft die Zuordnung explizit ohne Vault-Schreibzugriff."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        step6_text = _step6_text(content)
        assert "kein vault-schreibzugriff" in step6_text.lower() or (
            "keine" in step6_text.lower() and "vault-schreibzugriff" in step6_text.lower()
        ), (
            "Schritt 6 muss den Ablehn-Pfad explizit als 'kein Vault-Schreibzugriff' "
            "(oder gleichwertig) benennen"
        )

    def test_reject_path_is_not_framed_as_error(self):
        """AC2: Ablehnung ist Default-Pfad, kein Fehler-Framing."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        step6_text = _step6_text(content)
        assert "FEHLER" not in step6_text, (
            "Der Ablehn-Pfad darf keine Fehler-Formulierung verwenden — Ablehnung "
            "ist der normale, fehlerfreie Default-Pfad"
        )
        assert "wird abgebrochen" not in step6_text.lower(), (
            "Der Ablehn-Pfad darf den Skill nicht als abgebrochen darstellen"
        )

    def test_important_rules_bullet_references_gate_instead_of_standalone_prose(self):
        """Konsolidierung: 'User bestaetigt Zuordnungen'-Bullet verweist auf das Gate."""
        content = _SKILL_MD.read_text(encoding="utf-8")
        bullet_idx = content.find("User bestätigt Zuordnungen")
        assert bullet_idx != -1, "Bullet 'User bestaetigt Zuordnungen' fehlt"
        bullet_line_end = content.find("\n", bullet_idx)
        bullet_line = content[bullet_idx:bullet_line_end]
        assert "Schritt 6" in bullet_line, (
            "Das Bullet muss auf das AskUserQuestion-Gate in Schritt 6 verweisen "
            "statt eigenstaendiger Prosa ('vor dem Speichern freigeben lassen')"
        )
