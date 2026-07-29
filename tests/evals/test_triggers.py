"""Trigger-Evals: prueft, ob Skill-Descriptions Undertriggering/Overtriggering aufweisen."""

from __future__ import annotations

import json
import re

import pytest

from tests.evals.eval_runner import EVALS_ROOT, SKILLS_ROOT, call_claude

ALL_SKILLS = sorted(p.parent.name for p in SKILLS_ROOT.glob("*/SKILL.md"))

# Externe Konkurrenz-Skills, die NICHT unter SKILLS_ROOT liegen (Marketplace-
# Plugin, s. AGENTS.md: "Excel-Backend ist das externe Plugin document-skills
# ... nicht im Repo mitgeliefert (#445)"). Ohne diesen Eintrag stuende der
# eigentliche Trigger-Kollisions-Gegner aus Issue #447 dem Klassifikator nie
# als waehlbarer Kandidat zur Verfuegung -- selbst ein API-gateter Lauf koennte
# AC2 dann nicht direkt belegen (PR #499 Review-Fund). Wortlaut: woertliche
# Kopie des description-Felds aus dem xlsx-Skill des Marketplace-Plugins
# anthropic-agent-skills/document-skills (Stand 2026-07-29); bei
# Upstream-Aenderung manuell nachziehen.
EXTERNAL_COLLISION_CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "literature-excel": [
        (
            "document-skills:xlsx",
            "Use this skill any time a spreadsheet file is the primary input or "
            "output. This means any task where the user wants to: open, read, "
            "edit, or fix an existing .xlsx, .xlsm, .xltx, .csv, or .tsv file "
            "(e.g., adding columns, computing formulas, formatting, charting, "
            "cleaning messy data); create a new spreadsheet from scratch or from "
            "other data sources; or convert between tabular file formats. "
            "Trigger especially when the user references a spreadsheet file by "
            'name or path — even casually (like "the xlsx in my downloads") — '
            "and wants something done to it or produced from it. Also trigger "
            "for cleaning or restructuring messy tabular data files (malformed "
            "rows, misplaced headers, junk data) into proper spreadsheets. The "
            "deliverable must be a spreadsheet file. Do NOT trigger when the "
            "primary deliverable is a Word document, HTML report, standalone "
            "Python script, database pipeline, or Google Sheets API integration, "
            "even if tabular data is involved.",
        )
    ],
}


def _load_all_descriptions(extra: list[tuple[str, str]] | None = None) -> str:
    parts: list[str] = []
    for skill in ALL_SKILLS:
        content = (SKILLS_ROOT / skill / "SKILL.md").read_text()
        m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not m:
            continue
        fm = m.group(1)
        name_m = re.search(r"^name:\s*(.+)$", fm, re.M)
        desc_m = re.search(r"^description:\s*\|?\s*(.+?)(?=^[a-z_]+:|\Z)", fm, re.M | re.S)
        if name_m and desc_m:
            parts.append(f"- **{name_m.group(1).strip()}**: {desc_m.group(1).strip()[:500]}")
    for name, desc in extra or []:
        parts.append(f"- **{name}**: {desc[:500]}")
    return "\n".join(parts)


def _load_trigger_evals(skill: str) -> dict | None:
    path = EVALS_ROOT / skill / "trigger_evals.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def test_literature_excel_candidate_list_includes_external_collision_skill():
    """AC2-Review-Fund (PR #499): der eigentliche Trigger-Kollisions-Gegner aus
    Issue #447 -- ``document-skills:xlsx``, ein externes Marketplace-Plugin,
    nicht unter SKILLS_ROOT (AGENTS.md: "nicht im Repo mitgeliefert", #445) --
    muss dem Klassifikator als eigener, waehlbarer Kandidat vorliegen. Ohne
    diesen Eintrag koennte selbst ein API-gateter Lauf AC2 nie direkt belegen,
    weil der Dispatcher-Prompt document-skills:xlsx gar nicht zur Wahl stellt.
    """
    extra = EXTERNAL_COLLISION_CANDIDATES.get("literature-excel", [])
    assert extra, "literature-excel hat keinen registrierten externen Kollisions-Kandidaten."
    desc = _load_all_descriptions(extra)
    assert re.search(r"\*\*document-skills:xlsx\*\*", desc), (
        "document-skills:xlsx taucht im Klassifikator-Prompt nicht als eigener "
        "Kandidaten-Eintrag auf (nur als Erwaehnung in literature-excels eigener "
        "Beschreibung zaehlt nicht als waehlbare Option)."
    )
    assert "spreadsheet file is the primary input or output" in desc, (
        "Der gepinnte Konkurrenz-Text fuer document-skills:xlsx scheint leer oder verstuemmelt."
    )


def test_external_collision_candidate_does_not_leak_into_other_skills():
    """Regressions-Schutz: der neue Kandidat darf nur literature-excel betreffen,
    nicht alle 33 Skills' Klassifikator-Prompts global aufblaehen/veraendern."""
    header_re = re.compile(r"\*\*document-skills:xlsx\*\*")
    for skill in ALL_SKILLS:
        if skill == "literature-excel":
            continue
        desc = _load_all_descriptions(EXTERNAL_COLLISION_CANDIDATES.get(skill))
        assert not header_re.search(desc), (
            f"{skill}: document-skills:xlsx erscheint faelschlich als eigener Kandidaten-Eintrag."
        )


TRIGGER_SYSTEM_TEMPLATE = (
    "Du bist ein Skill-Dispatcher. Gegeben eine Liste verfuegbarer Skills und "
    "einen User-Prompt, antworte ausschliesslich mit dem Skill-Namen, der "
    "aktiviert werden sollte, oder 'none' falls keiner passt.\n\n"
    "Verfuegbare Skills:\n{descriptions}\n\n"
    "Antworte nur mit dem Skill-Namen oder 'none'. Keine Erklaerung."
)


def _classify(user_prompt: str, skill: str) -> str:
    extra = EXTERNAL_COLLISION_CANDIDATES.get(skill)
    system = TRIGGER_SYSTEM_TEMPLATE.format(descriptions=_load_all_descriptions(extra))
    output = call_claude(system=system, user=user_prompt, model="claude-haiku-4-5-20251001")
    return output.strip().lower().split()[0] if output.strip() else "none"


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_should_trigger_recall(skill: str):
    evals = _load_trigger_evals(skill)
    if not evals or not evals.get("should_trigger"):
        pytest.skip(f"Keine trigger_evals.json fuer {skill}")
    assert evals is not None  # narrow fuer type checker
    prompts: list[str] = list(evals["should_trigger"])
    hits = sum(_classify(p, skill) == skill for p in prompts)
    total = len(prompts)
    recall = hits / total
    assert recall >= 0.85, f"{skill}: recall={recall:.0%} ({hits}/{total}), Schwelle 85%"


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_should_not_trigger_fpr(skill: str):
    evals = _load_trigger_evals(skill)
    if not evals or not evals.get("should_not_trigger"):
        pytest.skip(f"Keine trigger_evals.json fuer {skill}")
    assert evals is not None  # narrow fuer type checker
    prompts: list[str] = list(evals["should_not_trigger"])
    false_pos = sum(_classify(p, skill) == skill for p in prompts)
    total = len(prompts)
    fpr = false_pos / total
    assert fpr <= 0.10, f"{skill}: fpr={fpr:.0%} ({false_pos}/{total}), Schwelle 10%"
