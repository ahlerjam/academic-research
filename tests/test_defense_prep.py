"""Tests fuer den defense-prep Skill (Issue #472).

TDD: Diese Tests wurden vor/parallel zur SKILL.md geschrieben.

Abdeckung je Akzeptanzkriterium:
- AC3 (Vortragsgliederung mit Zeitrahmen + Kernaussage je Kapitel): SKILL.md
  enthaelt eine Gliederungs-Sektion mit Zeitangaben (Minuten/Zeitrahmen) und
  eine explizite "Kernaussage je Kapitel"-Anforderung.
- AC4 (Fragenkatalog an tatsaechliche Methodik/Grenzen gebunden): SKILL.md
  nennt das academic_context.md-Feld "Methodik" und das Fazit-Kapitel als
  Pflichtquelle fuer Limitationen-Fragen, inklusive Regel fuer den Fall
  "keine Limitationen-Sektion gefunden" (Rueckfrage statt Erfindung).

Plus generische Struktur-Checks (Frontmatter, Preamble, Umlaut-Trigger-Paar,
Abgrenzung zu slide-export, Baseline-Eintrag) nach dem etablierten Muster
aus tests/test_grant_proposal.py / tests/test_conference_poster.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SKILL_DIR = _ROOT / "skills" / "defense-prep"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_SIZES_BASELINE = _ROOT / "tests" / "baselines" / "skill_sizes.json"
_TOKENS_BASELINE = _ROOT / "tests" / "baselines" / "tokens.json"
_PREAMBLE_PATTERN = "> **Gemeinsames Preamble laden:**"


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, "Kein YAML-Frontmatter gefunden"
    return m.group(1)


# ---------------------------------------------------------------------------
# Struktur
# ---------------------------------------------------------------------------


class TestDefensePrepSkillMd:
    def test_skill_md_exists(self):
        assert _SKILL_MD.exists(), f"{_SKILL_MD} fehlt"

    def test_frontmatter_has_name(self):
        fm = _frontmatter(_SKILL_MD.read_text())
        assert re.search(r"^name:\s*defense-prep\s*$", fm, re.M), "name != defense-prep"

    def test_frontmatter_has_description(self):
        fm = _frontmatter(_SKILL_MD.read_text())
        assert re.search(r"^description:\s*\S+", fm, re.M), "description fehlt"

    def test_description_has_umlaut_pair(self):
        """description enthaelt mindestens ein Umlaut-Paar (X.../Y...-Muster)."""
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

    def test_abgrenzung_references_slide_export(self):
        """Abgrenzung muss klarstellen, dass der Foliensatz selbst slide-export ist (Out-of-Scope-Klausel des Issues)."""
        text = _SKILL_MD.read_text()
        assert "slide-export" in text, "SKILL.md grenzt nicht gegen slide-export ab"

    def test_no_grading_prediction(self):
        """Out-of-Scope: keine automatische Bewertungsprognose (Issue #472 Scope-Out)."""
        text = _SKILL_MD.read_text().lower()
        assert "keine" in text and (
            "bewertungsprognose" in text or "notenschätzung" in text or "notenschaetzung" in text
        ), "SKILL.md schliesst Bewertungsprognose nicht ausdruecklich aus"


# ---------------------------------------------------------------------------
# AC3: Vortragsgliederung mit Zeitrahmen + Kernaussage je Kapitel
# ---------------------------------------------------------------------------


class TestAc3Gliederung:
    def test_zeitrahmen_mentioned(self):
        text = _SKILL_MD.read_text()
        assert re.search(r"[Mm]inute", text), "SKILL.md nennt keinen Zeitrahmen in Minuten"

    def test_zeitbudget_table_or_section_present(self):
        text = _SKILL_MD.read_text()
        assert "Zeitbudget" in text, "SKILL.md beschreibt kein Zeitbudget-Konzept"

    def test_kernaussage_je_kapitel_required(self):
        text = _SKILL_MD.read_text()
        assert "Kernaussage" in text and "Kapitel" in text, (
            "SKILL.md verlangt keine Kernaussage je Kapitel"
        )

    def test_no_kernaussage_without_fliesstext_is_flagged(self):
        """Kapitel ohne Fliesstext duerfen keine erfundene Kernaussage bekommen (Keine Fabrikation)."""
        text = _SKILL_MD.read_text()
        assert "erfinden" in text.lower(), (
            "SKILL.md regelt nicht explizit den Fall 'kein Fliesstext -> nicht erfinden'"
        )


# ---------------------------------------------------------------------------
# AC4: Fragenkatalog an tatsaechliche Methodik/Grenzen gebunden
# ---------------------------------------------------------------------------


class TestAc4Fragenkatalog:
    def test_methodik_feld_is_pflichtquelle(self):
        text = _SKILL_MD.read_text()
        assert "academic_context.md" in text and "Methodik" in text, (
            "SKILL.md bindet den Fragenkatalog nicht an das Methodik-Feld aus academic_context.md"
        )

    def test_limitationen_source_is_fazit_kapitel(self):
        text = _SKILL_MD.read_text()
        assert "Limitationen" in text and "Fazit" in text, (
            "SKILL.md bindet Limitationen-Fragen nicht an das Fazit-Kapitel"
        )

    def test_missing_limitationen_section_triggers_rueckfrage_not_invention(self):
        """Fehlt die Limitationen-Sektion im Fazit, muss der Skill nachfragen statt zu erfinden."""
        text = _SKILL_MD.read_text()
        assert "Fehlt diese Sektion" in text or "keine Limitationen" in text.lower(), (
            "SKILL.md regelt nicht den Fall 'Fazit ohne Limitationen-Sektion'"
        )
        assert "erfinden" in text.lower(), (
            "SKILL.md verbietet das Erfinden generischer Limitationen nicht explizit"
        )


# ---------------------------------------------------------------------------
# Baseline-Eintraege
# ---------------------------------------------------------------------------


class TestDefensePrepBaseline:
    def test_skill_sizes_contains_defense_prep(self):
        sizes = json.loads(_SIZES_BASELINE.read_text())
        assert "defense-prep" in sizes, "skill_sizes.json enthaelt keinen 'defense-prep'-Eintrag"
        assert sizes["defense-prep"] > 0

    def test_tokens_contains_defense_prep(self):
        tokens = json.loads(_TOKENS_BASELINE.read_text())
        assert "defense-prep" in tokens, "tokens.json enthaelt keinen 'defense-prep'-Eintrag"
        assert tokens["defense-prep"] > 0
