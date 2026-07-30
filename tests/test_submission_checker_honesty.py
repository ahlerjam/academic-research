"""Tests fuer die Ehrlichkeitsgrenze der submission-checker-Abgabepruefung (Issue #472, AC1).

Bisher behauptete `submission-checker` Pruefungen (Typografie, Zeilenabstand,
Raender, exakte Seitenzahl), die am reinen Markdown-Material (`kapitel/*.md`,
`writing_state.md`) gar nicht belegbar sind -- Layout entsteht erst beim
Export (`word-export`/`latex-export`). Diese Tests stellen strukturell sicher,
dass SKILL.md die Trennung "am Material pruefbar" vs. "nicht pruefbar ohne
Export/explizite User-Angabe" explizit enthaelt und das Output-Template eine
Pflicht-Sektion "Nicht geprueft" vorschreibt.

Risiko aus dem Plan zu #472: der bestehende Eval `sc-01` (User nennt
Formatwerte explizit im Prompt -> PASS) muss gruen bleiben -- die
Ehrlichkeitsgrenze gilt nur, wenn der Skill die Werte selbst aus dem Material
ableiten muesste, nicht wenn der User sie direkt liefert. Das wird hier nicht
erneut getestet (das deckt der Eval selbst), aber die SKILL.md-Regel dafuer
wird strukturell verifiziert (test_user_supplied_values_still_checkable).
"""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SKILL_MD = _ROOT / "skills" / "submission-checker" / "SKILL.md"
_SIZES_BASELINE = _ROOT / "tests" / "baselines" / "skill_sizes.json"
_TOKENS_BASELINE = _ROOT / "tests" / "baselines" / "tokens.json"


def _text() -> str:
    return _SKILL_MD.read_text()


class TestPruefbarkeitsgrenze:
    def test_seitenzahl_marked_not_checkable_on_material(self):
        text = _text()
        assert "NICHT am Material prüfbar" in text or "nicht am Material prüfbar" in text.lower(), (
            "SKILL.md kennzeichnet die Seitenzahl-Dimension nicht explizit als "
            "am Material nicht pruefbar"
        )
        # Sowohl Seitenzahl- als auch Formatierungs-Dimension muessen die Markierung tragen.
        assert text.count("NICHT am Material prüfbar") >= 2, (
            "Erwartet mind. 2 Dimensionen (Seitenzahl, Formatierung), die explizit als "
            "nicht am Material pruefbar markiert sind"
        )

    def test_layout_entsteht_erst_beim_export_explained(self):
        text = _text()
        assert "word-export" in text and "latex-export" in text, (
            "SKILL.md erklaert nicht, dass Layout erst bei word-export/latex-export entsteht"
        )

    def test_user_supplied_values_still_checkable(self):
        """Nennt der User die Werte explizit, bleibt die Pruefung moeglich (sc-01 muss PASS-faehig bleiben)."""
        text = _text()
        assert "der User" in text and "explizit" in text, (
            "SKILL.md beschreibt keinen Pfad fuer explizit vom User genannte Werte"
        )

    def test_unterschrift_not_verifiable_even_after_export(self):
        text = _text()
        assert "handschriftlich" in text.lower() or "tatsächlich unterzeichnet" in text, (
            "SKILL.md klaert nicht, dass eine tatsaechliche Unterschrift nie pruefbar ist"
        )


class TestNichtGeprueftPflichtsektion:
    def test_output_format_has_nicht_geprueft_section(self):
        text = _text()
        assert "### Nicht geprüft" in text, (
            "Output-Format-Template enthaelt keine '### Nicht geprüft'-Sektion"
        )

    def test_nicht_geprueft_is_mandatory_not_optional(self):
        text = _text()
        assert "Pflicht-Sektion" in text or "ist Pflicht" in text, (
            "SKILL.md macht die 'Nicht geprueft'-Sektion nicht ausdruecklich verpflichtend"
        )

    def test_no_silent_pass_rule_present(self):
        """Regel gegen stillschweigendes PASS bei ungeprueften Dimensionen."""
        text = _text()
        assert "erfundenes PASS" in text or "stillschweigend" in text, (
            "SKILL.md verbietet ein stillschweigendes/erfundenes PASS nicht explizit"
        )

    def test_ergebnis_uebersicht_table_allows_nicht_geprueft_status(self):
        text = _text()
        assert "NICHT GEPRÜFT" in text, (
            "Ergebnis-Uebersicht-Tabelle im Output-Format erlaubt keinen "
            "'NICHT GEPRÜFT'-Status neben PASS/PARTIAL/FAIL"
        )


class TestSubmissionCheckerBaselineRaised:
    """Die Ehrlichkeits-Erweiterung wächst den Skill; die Baseline muss ehrlich mitziehen
    (etabliertes Muster, siehe tests/test_issue_395_baseline_honesty.py)."""

    def test_skill_sizes_baseline_still_present_and_positive(self):
        sizes = json.loads(_SIZES_BASELINE.read_text())
        assert "submission-checker" in sizes
        assert sizes["submission-checker"] > 0

    def test_token_reduction_margin_holds(self):
        sizes = json.loads(_SIZES_BASELINE.read_text())
        current_chars = len(_text())
        delta = sizes["submission-checker"] - current_chars
        assert delta >= 1400, (
            f"submission-checker: Reduktionsmarge nur {delta} Zeichen "
            f"(erwartet >= 1400) -- Baseline muss mit dem Ehrlichkeits-Zuwachs mitziehen"
        )
