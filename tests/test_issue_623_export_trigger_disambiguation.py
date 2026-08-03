"""Regression-Guard fuer Issue #623 — Export-Trigger-Kollision latex-export vs word-export.

Der im Issue zitierte Vollstring-Trigger "Kapitel exportieren / uebersetzen"
existiert seit PR #488 nicht mehr woertlich identisch (word-export hat dort
bereits "Kapitel als Word exportieren / uebersetzen" bekommen). Die tiefere
Ambiguitaet bestand aber fort: beide Skills fuehrten die BARE, formatlosen
Segmente "uebersetzen" / "uebersetzen" (ohne Formatqualifikation) als eigene,
slash-getrennte Trigger-Alternative — ein Nutzer, der nur "Kapitel
uebersetzen" ohne Formatangabe sagt, konnte damit weiterhin beide Skills
gleichermassen treffen.

Fix: beide Skills qualifizieren "uebersetzen"/"uebersetzen" jetzt mit ihrem
Zielformat (analog zum bereits vorhandenen Muster bei "exportieren":
latex-export bleibt bare/Default, word-export traegt "als Word").

Akzeptanzkriterien (#623):
- AC1: Keine zwei Skills beanspruchen dieselbe Trigger-Phrase woertlich
  (repo-weiter Vollstring-Duplikat-Guard) UND kein gemeinsames bares
  Slash-Segment zwischen genau latex-export/word-export (pärchen-scoped,
  Praezedenz #178).
- AC2: "Kapitel als PDF exportieren" / "Kapitel als Word exportieren" fuehren
  erkennbar zu je einem Skill — latex-export-description ohne "PDF"/"Word",
  word-export-description mit beidem.
- AC3: Beide SKILL.md verweisen wechselseitig aufeinander (Abgrenzung).
- AC4: Dieser Test selbst ist der geforderte Vollstring-Duplikat-Test.
- AC5: Gegenprobe gegen main — siehe PR-Beschreibung (dieser Test faellt
  gegen den unveraenderten main-Stand der beiden SKILL.md rot).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).parent.parent / "skills"
LATEX_EXPORT_MD = SKILLS_DIR / "latex-export" / "SKILL.md"
WORD_EXPORT_MD = SKILLS_DIR / "word-export" / "SKILL.md"
VENDORED_SKILLS = {"_common", "humanizer-de"}
ALL_SKILL_MDS = sorted(
    p for p in SKILLS_DIR.glob("*/SKILL.md") if p.parent.name not in VENDORED_SKILLS
)


def _frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, f"{path}: kein Frontmatter gefunden"
    fm = m.group(1)
    desc_m = re.search(r"^description:\s*\|?\s*(.+?)(?=^[a-zA-Z_-]+:|\Z)", fm, re.M | re.S)
    assert desc_m, f"{path}: keine description im Frontmatter"
    return " ".join(desc_m.group(1).split())


def _abgrenzung_section(path: Path) -> str:
    """Extrahiert den Text der '## Abgrenzung ...'-Section(en) (bis zur naechsten H2)."""
    text = path.read_text(encoding="utf-8")
    matches = re.findall(r"^## Abgrenzung.*?\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert matches, f"{path}: keine '## Abgrenzung'-Section gefunden"
    return "\n".join(matches)


def _quoted_slash_segments(desc: str) -> set[str]:
    """Alle bare, getrimmten Slash-Segmente aus quotierten Trigger-Phrasen."""
    segments: set[str] = set()
    for quoted in re.findall(r'"([^"]*)"', desc):
        if " / " not in quoted:
            continue
        for seg in quoted.split(" / "):
            segments.add(seg.strip().lower())
    return segments


# --- AC1a: paerchen-scoped bare Slash-Segment-Kollision (Praezedenz #178) --


def test_latex_export_and_word_export_share_no_bare_slash_segment() -> None:
    """latex-export und word-export duerfen keine identischen bare Slash-Segmente teilen.

    Vor dem Fix teilten beide woertlich die formatlosen Segmente "uebersetzen"
    und "uebersetzen" — ein Nutzer ohne Formatangabe traf damit beide Skills
    gleichermassen.
    """
    latex_segments = _quoted_slash_segments(_frontmatter_description(LATEX_EXPORT_MD))
    word_segments = _quoted_slash_segments(_frontmatter_description(WORD_EXPORT_MD))
    shared = latex_segments & word_segments
    assert not shared, (
        f"latex-export und word-export teilen bare Trigger-Segmente {sorted(shared)} "
        "— beide muessen formatqualifiziert sein (#623)."
    )


# --- AC1b + AC4: repo-weiter Vollstring-Duplikat-Guard --------------------


def _quoted_full_phrases(desc: str) -> list[str]:
    return [p.strip().lower() for p in re.findall(r'"([^"]*)"', desc) if p.strip()]


def test_no_two_skills_share_an_identical_quoted_trigger_phrase() -> None:
    """Keine zwei Skills duerfen dieselbe quotierte Trigger-Phrase woertlich fuehren (AC1/AC4)."""
    phrase_owners: dict[str, str] = {}
    collisions: list[str] = []
    for skill_md in ALL_SKILL_MDS:
        desc = _frontmatter_description(skill_md)
        for phrase in _quoted_full_phrases(desc):
            owner = skill_md.parent.name
            if phrase in phrase_owners and phrase_owners[phrase] != owner:
                collisions.append(f"{phrase!r} in {phrase_owners[phrase]!r} und {owner!r}")
            else:
                phrase_owners[phrase] = owner
    assert not collisions, "Woertlich doppelte Trigger-Phrasen gefunden: " + "; ".join(collisions)


# --- AC2: PDF/Word-Routing eindeutig ---------------------------------------


def test_latex_export_description_has_no_pdf_or_word_mention() -> None:
    desc = _frontmatter_description(LATEX_EXPORT_MD)
    assert "PDF" not in desc, "latex-export description nennt 'PDF' — Routing waere mehrdeutig."
    assert "Word" not in desc, "latex-export description nennt 'Word' — Routing waere mehrdeutig."


def test_word_export_description_mentions_pdf_and_word() -> None:
    desc = _frontmatter_description(WORD_EXPORT_MD)
    assert "PDF" in desc, "word-export description fehlt 'PDF'."
    assert "Word" in desc, "word-export description fehlt 'Word'."


# --- AC3: wechselseitige Abgrenzung -----------------------------------------


def test_latex_export_abgrenzung_mentions_word_export() -> None:
    section = _abgrenzung_section(LATEX_EXPORT_MD)
    assert "word-export" in section, (
        "latex-export Abgrenzung verweist nicht auf 'word-export' (#623)."
    )


def test_word_export_abgrenzung_mentions_latex_export() -> None:
    section = _abgrenzung_section(WORD_EXPORT_MD)
    assert "latex-export" in section, (
        "word-export Abgrenzung verweist nicht auf 'latex-export' (#623)."
    )


# --- README-Trigger-Substrings bleiben erhalten -----------------------------


def test_latex_export_readme_trigger_substring_preserved() -> None:
    desc = _frontmatter_description(LATEX_EXPORT_MD)
    assert "kapitel exportieren" in desc.lower(), (
        "latex-export description verliert den README-Trigger 'Kapitel exportieren' (#208)."
    )


def test_word_export_readme_trigger_substring_preserved() -> None:
    desc = _frontmatter_description(WORD_EXPORT_MD)
    assert "kapitel als word exportieren" in desc.lower(), (
        "word-export description verliert den README-Trigger 'Kapitel als Word exportieren' (#208)."
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
