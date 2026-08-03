"""Regressions-Guard fuer Issue #206 — README-Skills-Coverage.

Die README-Skills-Tabelle (Sektion "Skills-Uebersicht") muss JEDEN
plugin-eigenen Skill (skills/*/SKILL.md) dokumentieren. Ausserdem muessen
Badge und TOC-Eintrag den korrekten Count tragen.

Befund vor dem Fix: book-handler, cluster-visualizer, latex-export und
notebook-bundle fehlten komplett, Badge stand auf 23+, TOC auf "23+".
"""

import re
from pathlib import Path

from tests.helpers import docs as _docs

REPO_ROOT = Path(__file__).parent.parent
README = REPO_ROOT / "README.md"
SKILLS_DIR = REPO_ROOT / "skills"

# Kein eigenstaendiger Skill, nur geteilte Markdown-Fragmente.
VENDORED_SKILLS = {"_common"}

# Skills, deren Fehlen Issue #206 explizit benennt.
ISSUE_206_SKILLS = {
    "book-handler",
    "cluster-visualizer",
    "latex-export",
    "notebook-bundle",
}


def _plugin_own_skills() -> set[str]:
    return {
        p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md") if p.parent.name not in VENDORED_SKILLS
    }


def test_all_plugin_skills_documented_in_readme():
    text = _docs.SKILLS_DOC.read_text(encoding="utf-8")
    # Tabellen-Zeilen referenzieren Skills als `name` in Backticks.
    missing = sorted(s for s in _plugin_own_skills() if f"`{s}`" not in text)
    assert not missing, "Plugin-eigene Skills fehlen in der README-Skills-Tabelle: " + ", ".join(
        missing
    )


def test_issue_206_named_skills_documented():
    text = _docs.SKILLS_DOC.read_text(encoding="utf-8")
    missing = sorted(s for s in ISSUE_206_SKILLS if f"`{s}`" not in text)
    assert not missing, "Von Issue #206 benannte Skills weiterhin undokumentiert: " + ", ".join(
        missing
    )


def test_skills_badge_count_is_41():
    text = README.read_text(encoding="utf-8")
    assert re.search(r"img\.shields\.io/badge/skills-41", text), (
        "Skills-Badge muss auf 'skills-41' stehen (41 SKILL.md, Stand Issue #610)."
    )


def test_readme_links_skills_reference():
    """Die README verlinkt die Skills-Referenz — sonst ist sie unauffindbar.

    Ersetzt den frueheren TOC-Eintrag-Test: seit #402 hat die README kein
    Inhaltsverzeichnis mehr, sondern eine Doku-Karte mit Links.
    """
    text = README.read_text(encoding="utf-8")
    assert "docs/reference/skills.md" in text, "README verlinkt docs/reference/skills.md nicht."
    assert "selbstaktivierend" in _docs.SKILLS_DOC.read_text(encoding="utf-8"), (
        "Skills-Referenz erklaert die Selbstaktivierung nicht mehr."
    )
