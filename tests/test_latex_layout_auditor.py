"""Tests fuer den latex-layout-auditor Skill (Issue #392).

TDD: Diese Tests wurden vor der SKILL.md/den Fixtures geschrieben.

Abdeckung je Akzeptanzkriterium:
- AC1: SKILL.md existiert mit gueltigem Frontmatter und einem
  Abgrenzungs-Abschnitt gegenueber submission-checker.
- AC2: Gegen tests/fixtures/latex_layout_auditor/missing_tightlist.tex
  meldet audit_tex() genau einen Fundort (Zeilennummer + Snippet).
- AC3: Gegen tests/fixtures/latex_layout_auditor/valid_structure.tex
  liefert audit_tex() keine falsch-positiven Findings.
- AC4: Dieser Testfall deckt beide Fixtures ab und ist gruen
  (`uv run pytest tests/test_latex_layout_auditor.py -v`).

Struktur-Checks (Frontmatter, Preamble, Umlaut-Trigger-Paar, Baseline-
Eintrag) nach dem etablierten Muster aus tests/test_defense_prep.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_SKILL_DIR = _ROOT / "skills" / "latex-layout-auditor"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_SCRIPTS_DIR = _ROOT / "skills" / "latex-layout-auditor" / "scripts"
_SIZES_BASELINE = _ROOT / "tests" / "baselines" / "skill_sizes.json"
_TOKENS_BASELINE = _ROOT / "tests" / "baselines" / "tokens.json"
_PREAMBLE_PATTERN = "> **Gemeinsames Preamble laden:**"
_FIXTURES_DIR = _ROOT / "tests" / "fixtures" / "latex_layout_auditor"

sys.path.insert(0, str(_SCRIPTS_DIR))


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, "Kein YAML-Frontmatter gefunden"
    return m.group(1)


# ---------------------------------------------------------------------------
# AC1: SKILL.md-Struktur + Abgrenzung
# ---------------------------------------------------------------------------


class TestSkillMdStructure:
    def test_skill_md_exists(self):
        assert _SKILL_MD.exists(), f"{_SKILL_MD} fehlt"

    def test_frontmatter_has_name(self):
        fm = _frontmatter(_SKILL_MD.read_text())
        assert re.search(r"^name:\s*latex-layout-auditor\s*$", fm, re.M), (
            "name != latex-layout-auditor"
        )

    def test_frontmatter_has_description(self):
        fm = _frontmatter(_SKILL_MD.read_text())
        assert re.search(r"^description:\s*\S+", fm, re.M), "description fehlt"

    def test_frontmatter_has_mit_license(self):
        fm = _frontmatter(_SKILL_MD.read_text())
        assert re.search(r"^license:\s*MIT\s*$", fm, re.M), "license != MIT"

    def test_allowed_tools_is_read_only(self):
        """Issue-Scope: 'SKILL.md, Read-only' -- allowed-tools darf nur Read enthalten."""
        text = _SKILL_MD.read_text()
        m = re.search(r"^allowed-tools:\s*(.*?)(?=^\S|\Z)", text, re.M | re.S)
        assert m, "allowed-tools fehlt im Frontmatter"
        block = m.group(1)
        assert "Read" in block, "allowed-tools enthaelt kein Read"
        assert "Write" not in block, "allowed-tools ist nicht read-only (Write gefunden)"
        assert "Bash" not in block, "allowed-tools ist nicht read-only (Bash gefunden)"

    def test_description_has_umlaut_pair(self):
        fm = _frontmatter(_SKILL_MD.read_text())
        desc_m = re.search(
            r"^description:\s*(.*?)(?=^[a-zA-Z_][a-zA-Z0-9_-]*:|\Z)", fm, re.DOTALL | re.M
        )
        assert desc_m
        desc = " ".join(desc_m.group(1).split())
        pairs = re.findall(r'"[^"]*[äöüß][^"]*\s*/\s*[a-zA-Z][^"]*"', desc)
        assert len(pairs) >= 1, f"0 Umlaut-Paare in description: {desc[:200]}"

    def test_preamble_load_instruction_present(self):
        assert _PREAMBLE_PATTERN in _SKILL_MD.read_text(), "Preamble-Ladereferenz fehlt"

    def test_no_inline_vorbedingungen(self):
        assert "\n## Vorbedingungen\n" not in _SKILL_MD.read_text()

    def test_no_inline_fabrikation(self):
        assert "\n## Keine Fabrikation\n" not in _SKILL_MD.read_text()

    def test_abgrenzung_submission_checker_mentioned(self):
        """AC1: expliziter Abgrenzungs-Abschnitt gegenueber submission-checker."""
        text = _SKILL_MD.read_text()
        assert "submission-checker" in text, "SKILL.md grenzt nicht gegen submission-checker ab"
        lower = text.lower()
        assert "abgrenzung" in lower, "SKILL.md hat keinen 'Abgrenzung'-Abschnitt"

    def test_abgrenzung_latex_export_mentioned(self):
        """Scope-Out laut Issue: latex-export-Bugs werden erkannt, nicht gefixt."""
        text = _SKILL_MD.read_text()
        assert "latex-export" in text, "SKILL.md grenzt nicht gegen latex-export ab"

    def test_no_auto_fix_of_render_bugs(self):
        """Scope-Out laut Issue: render_tex.py-Bugs werden nur gemeldet, nicht behoben."""
        text = _SKILL_MD.read_text().lower()
        assert "nicht behoben" in text or "nicht fixt" in text or "meldet" in text, (
            "SKILL.md stellt nicht klar, dass Findings gemeldet statt automatisch behoben werden"
        )

    def test_source_attribution_present(self):
        """Wortlaut-Uebernahme aus andrehuang/academic-writing-agents (MIT) braucht Quellenhinweis."""
        text = _SKILL_MD.read_text()
        assert "andrehuang/academic-writing-agents" in text, (
            "SKILL.md nennt nicht die Quelle des 30-Prinzipien-Katalogs"
        )


# ---------------------------------------------------------------------------
# AC2 + AC3: audit_tex() gegen die beiden Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def audit_tex():
    from check_layout import audit_tex as _audit_tex

    return _audit_tex


class TestMissingTightlistFixture:
    """AC2: nicht-kompilierende Liste (fehlendes \\tightlist) -> konkreter Fundort."""

    def test_fixture_exists(self):
        path = _FIXTURES_DIR / "missing_tightlist.tex"
        assert path.exists(), f"{path} fehlt"

    def test_reports_exactly_one_finding(self, audit_tex):
        text = (_FIXTURES_DIR / "missing_tightlist.tex").read_text(encoding="utf-8")
        findings = audit_tex(text)
        assert len(findings) == 1, f"Erwartet genau 1 Finding, erhalten: {findings}"

    def test_finding_reports_concrete_location(self, audit_tex):
        text = (_FIXTURES_DIR / "missing_tightlist.tex").read_text(encoding="utf-8")
        findings = audit_tex(text)
        finding = findings[0]
        # Fundort = Zeilennummer + Snippet der betroffenen Liste.
        assert finding.line == text.splitlines().index(r"\tightlist") + 1
        assert r"\tightlist" in finding.snippet
        assert finding.rule == "missing-tightlist-definition"


class TestValidStructureFixture:
    """AC3: korrekte Struktur -> keine falsch-positiven Findings."""

    def test_fixture_exists(self):
        path = _FIXTURES_DIR / "valid_structure.tex"
        assert path.exists(), f"{path} fehlt"

    def test_reports_zero_findings(self, audit_tex):
        text = (_FIXTURES_DIR / "valid_structure.tex").read_text(encoding="utf-8")
        findings = audit_tex(text)
        assert findings == [], f"Erwartet 0 Findings, erhalten: {findings}"


class TestCorruptedCiteRule:
    """Zweite Digest-Regel: korrumpierte \\cite{}-Befehle (Issue #392 Scope)."""

    def test_detects_backslash_escaped_cite(self, audit_tex):
        text = (
            "\\chapter{Ergebnisse}\n\n"
            "Ein Befund \\textbackslash{}cite{smith2020} wurde uebernommen.\n"
        )
        findings = audit_tex(text)
        assert len(findings) == 1
        assert findings[0].rule == "corrupted-cite-command"
        assert findings[0].line == 3

    def test_normal_cite_not_flagged(self, audit_tex):
        text = "\\chapter{Ergebnisse}\n\nEin Befund \\cite{smith2020} wurde uebernommen.\n"
        findings = audit_tex(text)
        assert findings == []


# ---------------------------------------------------------------------------
# Baseline-Eintraege
# ---------------------------------------------------------------------------


class TestLatexLayoutAuditorBaseline:
    def test_skill_sizes_contains_entry(self):
        sizes = json.loads(_SIZES_BASELINE.read_text())
        assert "latex-layout-auditor" in sizes, (
            "skill_sizes.json enthaelt keinen 'latex-layout-auditor'-Eintrag"
        )
        assert sizes["latex-layout-auditor"] > 0

    def test_tokens_contains_entry(self):
        tokens = json.loads(_TOKENS_BASELINE.read_text())
        assert "latex-layout-auditor" in tokens, (
            "tokens.json enthaelt keinen 'latex-layout-auditor'-Eintrag"
        )
        assert tokens["latex-layout-auditor"] > 0
