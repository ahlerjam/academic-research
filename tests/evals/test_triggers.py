"""Trigger-Evals: prueft, ob Skill-Descriptions Undertriggering/Overtriggering aufweisen."""

from __future__ import annotations

import json
import os
import re
from datetime import date

import pytest

from tests.evals.eval_runner import EVALS_ROOT, SKILLS_ROOT, call_claude

pytestmark = pytest.mark.eval_core_set

ALL_SKILLS = sorted(p.parent.name for p in SKILLS_ROOT.glob("*/SKILL.md"))

# ---------------------------------------------------------------------------
# Rotierende Stichprobe fuer den geplanten Kern-Set-Lauf (Issue #597,
# Operator-Entscheidung nach Review): test_triggers.py deckt mit 45 Skills x
# should_trigger/should_not_trigger allein ~871 der ~991 API-Aufrufe eines
# Vollaufs ab -- das machte das "Kern-Set" faktisch zum Vollauf. Statt jede
# Woche alle Skills zu pruefen, laeuft nur noch eine feste Rotationsgruppe
# pro Woche; ueber ROTATION_GROUP_COUNT Wochen kommt jeder Skill dran.
#
# Deterministisch statt zufaellig: die Gruppenzuordnung ist rein positionell
# (ALL_SKILLS ist bereits alphabetisch sortiert, Index modulo Gruppenzahl),
# die Wochenauswahl folgt der ISO-Kalenderwoche (`date.isocalendar().week`).
# Kein `random`/Zeitstempel-Jitter -- ein Lauf ist damit aus dem Datum allein
# reproduzierbar.
#
# Ueberschreibbar ueber die Umgebungsvariable EVAL_TRIGGER_ROTATION_GROUP
# (vom Workflow gesetzt, s. .github/workflows/eval-behavior.yml):
#   unset/leer -> ALL_SKILLS (bisheriges Verhalten fuer manuelle/CI-Laeufe,
#                 die den Marker gar nicht anwenden bzw. den vollen Satz
#                 anfordern).
#   "all"      -> ALL_SKILLS (expliziter Override, z.B. fuer einen manuellen
#                 Nachvollzug des Vollaufs).
#   "auto"     -> Rotationsgruppe der aktuellen ISO-Kalenderwoche (vom
#                 geplanten Lauf gesetzt, sofern kein workflow_dispatch-Input
#                 eine Gruppe erzwingt).
#   "0".."N-1" -> genau diese Rotationsgruppe (manueller Override).
ROTATION_GROUP_COUNT = 4


def _build_rotation_groups(skills: list[str], group_count: int) -> list[list[str]]:
    """Teilt `skills` positionell (Index modulo `group_count`) in feste,
    disjunkte Gruppen. Deterministisch bei stabiler ALL_SKILLS-Reihenfolge;
    die Vereinigung aller Gruppen ist exakt `skills` (kein Skill faellt raus,
    keiner ist doppelt -- siehe test_rotation_groups_partition_all_skills)."""
    groups: list[list[str]] = [[] for _ in range(group_count)]
    for index, skill in enumerate(skills):
        groups[index % group_count].append(skill)
    return groups


ROTATION_GROUPS = _build_rotation_groups(ALL_SKILLS, ROTATION_GROUP_COUNT)


def select_rotation_skills(
    env_value: str | None, skills: list[str] = ALL_SKILLS, today: date | None = None
) -> list[str]:
    """Waehlt die Skill-Teilmenge fuer die beiden API-gateten Trigger-Tests
    unten. Siehe Modul-Kommentar oben fuer die Bedeutung von `env_value`."""
    if not env_value or not env_value.strip():
        return skills
    value = env_value.strip().lower()
    if value == "all":
        return skills
    if value == "auto":
        week = (today or date.today()).isocalendar().week
        return ROTATION_GROUPS[week % ROTATION_GROUP_COUNT]
    if value.isdigit() and int(value) < ROTATION_GROUP_COUNT:
        return ROTATION_GROUPS[int(value)]
    raise ValueError(
        f"Unbekannter Wert fuer EVAL_TRIGGER_ROTATION_GROUP: {env_value!r} -- "
        f"erwartet leer/'all'/'auto'/0..{ROTATION_GROUP_COUNT - 1}."
    )


ROTATION_SKILLS = select_rotation_skills(os.environ.get("EVAL_TRIGGER_ROTATION_GROUP"))

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


def _parse_dispatcher_output(output: str, skills: list[str]) -> str:
    """Parst eine Dispatcher-Antwort robust gegen geschwaetzige Modellantworten.

    Fast-Path: Ist das erste Token bereits ein exaktes Match auf einen
    Skill-Namen oder 'none' (bisheriges Verhalten), wird das direkt
    zurueckgegeben -- deckt den Normalfall compliant formatierter
    Ein-Wort-Antworten ab, ohne die gesamte Antwort zu durchsuchen.

    Fallback: Sonst wird die GESAMTE Antwort nach Vorkommen von Skill-Namen
    durchsucht (Wortgrenzen, case-insensitive). Genau EIN eindeutig genannter
    Skill-Name zaehlt als dessen Antwort -- rettet inhaltlich korrekte, aber
    unformatierte Antworten wie "Sobald ich den Text habe, nutze ich den
    **humanizer-de**-Skill ...", bei denen ``split()[0]`` faelschlich 'ich'
    lieferte (Issue #825 Review-Fund, belegt durch Diagnoselauf). Werden ZWEI
    ODER MEHR unterschiedliche Skill-Namen genannt, ist die Antwort
    mehrdeutig und zaehlt als Fehlschlag -- weder Hit (Recall-Test) noch
    False Positive (FPR-Test). Das macht die Klassifikation strenger, nie
    lockerer: ein blosses "Antwort enthaelt den Skillnamen" waere bei 45
    Kandidaten zu lax, weil eine geschwaetzige Antwort leicht mehrere Namen
    nennt.
    """
    stripped = output.strip()
    if not stripped:
        return "none"
    first_token = stripped.lower().split()[0]
    valid_answers = {s.lower() for s in skills} | {"none"}
    if first_token in valid_answers:
        return first_token
    lowered = stripped.lower()
    mentioned = {
        name
        for name in skills
        if re.search(rf"(?<![\w-]){re.escape(name.lower())}(?![\w-])", lowered)
    }
    if len(mentioned) == 1:
        return next(iter(mentioned))
    return "__ambiguous__"


def _classify(user_prompt: str, skill: str) -> str:
    extra = EXTERNAL_COLLISION_CANDIDATES.get(skill)
    system = TRIGGER_SYSTEM_TEMPLATE.format(descriptions=_load_all_descriptions(extra))
    output = call_claude(system=system, user=user_prompt, model="claude-haiku-4-5-20251001")
    return _parse_dispatcher_output(output, ALL_SKILLS)


@pytest.mark.parametrize("skill", ROTATION_SKILLS)
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


@pytest.mark.parametrize("skill", ROTATION_SKILLS)
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


# ---------------------------------------------------------------------------
# Hermetischer Test fuer den Dispatcher-Output-Parser -- kein API-Aufruf,
# laeuft immer. Belegt den Issue-#825-Review-Fund direkt an einer echten
# Beispielantwort aus dem Diagnoselauf (statt nur indirekt ueber einen
# API-gateten Recall-Test).
# ---------------------------------------------------------------------------

_REAL_CHATTY_OUTPUT = (
    "Ich bin bereit, einen Text zu humanisieren! \U0001f60a Aber ich brauche "
    "noch **welchen Text** du meinst. \n\nKannst du mir bitte eine der "
    "folgenden Optionen geben?\n\n1. **Den Text direkt posten** – kopier "
    "ihn hier rein\n2. **Eine Datei angeben** – z.B. "
    "`kapitel/einleitung.md`\n3. **Beschreib, welcher Abschnitt** – z.B. "
    "„das Kapitel zur Literatur, das ich gerade geschrieben habe“\n\n"
    "Sobald ich den Text habe, nutze ich den **humanizer-de**-Skill, um:\n"
    "- KI-typische Muster zu erkennen (Floskeln, aufgeblähte Symbolik, "
    "etc.)\n- Den Schreibstil natürlicher und authentischer zu machen\n- "
    "Die Sachlichkeit zu bewahren\n\nWorauf wartest du? \U0001f3af"
)

_PARSE_CASES = [
    pytest.param(_REAL_CHATTY_OUTPUT, "humanizer-de", id="real-chatty-single-mention"),
    pytest.param("style-evaluator", "style-evaluator", id="clean-one-word"),
    pytest.param("none", "none", id="clean-none"),
    pytest.param(
        "Das koennte entweder humanizer-de oder style-evaluator sein.",
        None,
        id="two-skill-names-ambiguous",
    ),
]


@pytest.mark.parametrize("output, expected", _PARSE_CASES)
def test_parse_dispatcher_output(output: str, expected: str | None):
    """Belegt Issue #825: eine geschwaetzige, aber inhaltlich eindeutige
    Antwort (genau ein genannter Skill-Name) wird korrekt aufgeloest;
    eine Antwort mit zwei genannten Skill-Namen bleibt ein Fehlschlag
    (weder 'humanizer-de' noch 'style-evaluator') statt stillschweigend
    den ersten/naechsten Treffer zu waehlen."""
    skills = ["humanizer-de", "style-evaluator", "title-generator"]
    result = _parse_dispatcher_output(output, skills)
    if expected is None:
        assert result not in skills, (
            f"Mehrdeutige Antwort mit zwei Skill-Namen wurde faelschlich einem "
            f"einzelnen Skill zugeordnet: {result!r}"
        )
    else:
        assert result == expected


# ---------------------------------------------------------------------------
# Hermetische Tests fuer die Rotationslogik selbst -- kein API-Aufruf, laufen
# immer (auch ohne Key/CLI). Siehe Modul-Kommentar oben zu ROTATION_GROUPS.
# ---------------------------------------------------------------------------


def test_rotation_groups_partition_all_skills():
    """Die Vereinigung aller Rotationsgruppen ist exakt ALL_SKILLS -- kein
    Skill faellt raus, keiner steckt in mehr als einer Gruppe."""
    union: list[str] = []
    for group in ROTATION_GROUPS:
        assert group, "Eine Rotationsgruppe ist leer."
        union.extend(group)
    assert sorted(union) == ALL_SKILLS, (
        "Rotationsgruppen decken ALL_SKILLS nicht exakt ab (fehlender oder zusaetzlicher Skill)."
    )
    assert len(union) == len(set(union)), "Ein Skill steckt in mehr als einer Rotationsgruppe."


def test_rotation_group_sizes_are_in_operator_approved_range():
    """Operator-Vorgabe: 10-15 Skills pro Rotationsgruppe (Review zu Issue #597)."""
    for index, group in enumerate(ROTATION_GROUPS):
        assert 10 <= len(group) <= 15, (
            f"Rotationsgruppe {index} hat {len(group)} Skills, ausserhalb 10-15."
        )


def test_rotation_selection_is_deterministic_from_iso_week():
    """Dieselbe ISO-Kalenderwoche liefert immer dieselbe Gruppe, egal an
    welchem Wochentag der Lauf tatsaechlich startet -- kein
    random/Zeitstempel-Jitter."""
    monday = date.fromisocalendar(2026, 5, 1)
    sunday = date.fromisocalendar(2026, 5, 7)
    assert select_rotation_skills("auto", today=monday) == select_rotation_skills(
        "auto", today=sunday
    )
    assert select_rotation_skills("auto", today=monday) == ROTATION_GROUPS[5 % ROTATION_GROUP_COUNT]


def test_rotation_full_cycle_hits_every_group_without_skipping():
    """Ueber ROTATION_GROUP_COUNT aufeinanderfolgende Wochen kommt jede
    Gruppe genau einmal dran -- keine Gruppe wird dauerhaft uebersprungen."""
    for week in range(1, 1 + ROTATION_GROUP_COUNT):
        expected = ROTATION_GROUPS[week % ROTATION_GROUP_COUNT]
        actual = select_rotation_skills("auto", today=date.fromisocalendar(2026, week, 1))
        assert actual == expected, f"Woche {week}: erwartete Gruppe {expected}, bekam {actual}"


def test_rotation_override_values():
    """unset/leer/'all' -> voller Satz; Ziffer -> genau diese Gruppe; unbekannter
    Wert -> Fehler statt stillschweigendem Fallback."""
    assert select_rotation_skills(None) == ALL_SKILLS
    assert select_rotation_skills("") == ALL_SKILLS
    assert select_rotation_skills("all") == ALL_SKILLS
    assert select_rotation_skills("ALL") == ALL_SKILLS
    assert select_rotation_skills("0") == ROTATION_GROUPS[0]
    assert select_rotation_skills(str(ROTATION_GROUP_COUNT - 1)) == ROTATION_GROUPS[-1]
    with pytest.raises(ValueError):
        select_rotation_skills("not-a-group")
    with pytest.raises(ValueError):
        select_rotation_skills(str(ROTATION_GROUP_COUNT))
