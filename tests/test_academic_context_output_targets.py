"""Tests fuer die output_targets-Erhebung in academic-context (Issue #472, AC2).

Die drei Output-Skills `grant-proposal`, `conference-poster` und
`reviewer-response` sind seit v6.5 Default-Off und aktivieren sich nur ueber
`output_targets` in `./academic_context.md` (siehe docs/reference/glossary.md).
Bisher erhob `academic-context` dieses Feld in der Erstaktivierung nicht --
die drei Skills waren dadurch faktisch nie erreichbar, ohne dass der User von
sich aus das rohe YAML-Feld von Hand anlegt. Diese Tests stellen strukturell
sicher, dass die Feldliste und das Template-Beispiel das Feld jetzt nennen.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SKILL_MD = _ROOT / "skills" / "academic-context" / "SKILL.md"

_OUTPUT_SKILLS = ["grant-proposal", "conference-poster", "reviewer-response"]


def _text() -> str:
    return _SKILL_MD.read_text()


class TestOutputTargetsFieldListed:
    def test_output_targets_field_named_in_erstaktivierung(self):
        text = _text()
        assert "output_targets" in text, "SKILL.md erwaehnt das Feld 'output_targets' nicht"

    def test_ausgabeform_wording_present(self):
        text = _text()
        assert "Ausgabeform" in text, "SKILL.md nennt keine 'Ausgabeform(en)'-Feldbezeichnung"

    def test_all_three_output_skills_offered_as_options(self):
        text = _text()
        for skill in _OUTPUT_SKILLS:
            assert skill in text, f"SKILL.md bietet '{skill}' nicht als output_targets-Option an"

    def test_opt_in_default_off_pattern_referenced(self):
        text = _text()
        assert "Default-Off" in text or "default off" in text.lower(), (
            "SKILL.md erklaert nicht, dass die drei Skills per Default aus sind"
        )


class TestTemplateShowsOutputTargetsBlock:
    def test_template_contains_output_targets_yaml_block(self):
        text = _text()
        # Innerhalb des ```markdown-Templates muss ein "output_targets:"-Block stehen.
        template_m = re.search(r"```markdown(.*?)```", text, re.DOTALL)
        assert template_m, "Kein ```markdown-Template im SKILL.md gefunden"
        template = template_m.group(1)
        assert "output_targets:" in template, (
            "Das academic_context.md-Template zeigt keinen 'output_targets:'-Block"
        )

    def test_template_output_targets_block_is_a_list(self):
        text = _text()
        template_m = re.search(r"```markdown(.*?)```", text, re.DOTALL)
        assert template_m
        template = template_m.group(1)
        m = re.search(r"output_targets:\s*\n\s*-\s*\S+", template)
        assert m, "output_targets im Template ist keine YAML-Liste (Zeile mit '  - ...')"


class TestExistingOptInSkillsUnaffected:
    """Die drei Default-Off-Skills selbst bleiben unveraendert (kein Scope-Creep)."""

    def test_grant_proposal_still_guards_via_output_targets(self):
        text = (_ROOT / "skills" / "grant-proposal" / "SKILL.md").read_text()
        assert "output_targets" in text

    def test_conference_poster_still_guards_via_output_targets(self):
        text = (_ROOT / "skills" / "conference-poster" / "SKILL.md").read_text()
        assert "output_targets" in text

    def test_reviewer_response_still_guards_via_output_targets(self):
        text = (_ROOT / "skills" / "reviewer-response" / "SKILL.md").read_text()
        assert "output_targets" in text
