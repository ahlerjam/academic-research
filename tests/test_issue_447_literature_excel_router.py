"""Regressionstests fuer Issue #447 — Trigger-Kollision /excel vs. xlsx-Skill.

Der generische Skill ``document-skills:xlsx`` aktiviert sich ueber eine sehr
breite Beschreibung und gewinnt deshalb jede natuerlichsprachige Excel-Anfrage
— auch literaturbezogene, obwohl `/academic-research:excel`
(`disable-model-invocation: true`) genau dafuer die passende 4-Sheet-
Spezifikation definiert. Der neue Router-Skill ``literature-excel`` faengt
literaturbezogene Anfragen vorher ab, dupliziert aber die Spezifikation nicht.

Die eigentliche Trigger-Auswahl ist Modellverhalten und laeuft ueber
``evals/literature-excel/trigger_evals.json`` (nicht unter ``pytest tests/``,
vgl. AGENTS.md-Verzeichnisgrenzen). Diese Datei prueft nur die statische
Verdrahtung: Frontmatter, Verweiskette Skill -> Command, Nicht-Duplikation der
Sheet-Spezifikation, Doku-Konsistenz und die Skill-Count-Synchronisation.
"""

import json
import re
from pathlib import Path

from tests.helpers import docs as _docs

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "literature-excel" / "SKILL.md"
TRIGGER_EVALS = REPO_ROOT / "evals" / "literature-excel" / "trigger_evals.json"
EXCEL_CMD = REPO_ROOT / "commands" / "excel.md"
PICKUP_CMD = REPO_ROOT / "commands" / "pickup.md"
README = REPO_ROOT / "README.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"

#: Fingerprint der Sheet-Spezifikation aus commands/excel.md — darf im
#: Router-Skill nicht wortgleich dupliziert werden (Single Source of Truth).
SHEET_SPEC_COLUMN_FINGERPRINT = (
    "Titel | Autoren | Jahr | Venue | DOI | Gesamt | Relevanz | Aktualität | "
    "Qualität | Autorität | Zugang | Cluster"
)
CLUSTER_COLOR_MAPPINGS = (
    "Kern = grün",
    "Ergänzung = blau",
    "Hintergrund = grau",
    "Methoden = gelb",
)


# --------------------------------------------------------------------------
# AC1/AC4 — Skill existiert, aktiviert korrekt, verweist statt zu duplizieren
# --------------------------------------------------------------------------


def test_skill_file_exists():
    assert SKILL_MD.exists(), f"{SKILL_MD} fehlt — Router-Skill fuer Issue #447 nicht angelegt."


def test_skill_frontmatter_has_name_and_description():
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, "SKILL.md: kein valides YAML-Frontmatter"
    fm = m.group(1)
    assert re.search(r"^name:\s*literature-excel\s*$", fm, re.M), "Frontmatter-name falsch/fehlt"
    assert re.search(r"^description:", fm, re.M), "Frontmatter-description fehlt"


def test_skill_references_excel_command_as_single_source():
    """AC1: Der Skill leitet auf commands/excel.md, statt selbst zu spezifizieren."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "commands/excel.md" in text, (
        "literature-excel/SKILL.md verweist nicht auf commands/excel.md — "
        "Single Source of Truth der Sheet-Spezifikation waere gebrochen."
    )
    assert "/academic-research:excel" in text, (
        "literature-excel/SKILL.md nennt den referenzierten Command nicht beim Namen."
    )


def test_skill_does_not_duplicate_sheet_spec():
    """Der Router-Skill darf keine eigene, abweichende Sheet-Struktur definieren."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert SHEET_SPEC_COLUMN_FINGERPRINT not in text, (
        "literature-excel/SKILL.md dupliziert die Spalten-Spezifikation aus "
        "commands/excel.md wortgleich — sie darf nur referenziert werden."
    )
    duplicated_colors = [m for m in CLUSTER_COLOR_MAPPINGS if m in text]
    assert not duplicated_colors, (
        f"literature-excel/SKILL.md dupliziert Cluster-Farbcodierung: {duplicated_colors}"
    )


def test_skill_names_engine_and_avoids_generic_collision():
    """Der Skill grenzt sich explizit vom generischen xlsx-Skill ab (AC2)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "document-skills:xlsx" in text
    assert "literaturfremde" in text.lower() or "ohne literaturbezug" in text.lower(), (
        "SKILL.md grenzt literaturfremde Excel-Wuensche nicht explizit ab."
    )


# --------------------------------------------------------------------------
# AC3 — commands/excel.md dokumentiert Spezifikation vs. Engine in zwei Saetzen
# --------------------------------------------------------------------------


def test_excel_command_documents_spec_vs_engine_split():
    text = EXCEL_CMD.read_text(encoding="utf-8")
    m = re.search(r"## Spezifikation vs\. Engine\n\n(.+?)\n\n", text, re.DOTALL)
    assert m, "commands/excel.md: Abschnitt 'Spezifikation vs. Engine' fehlt."
    block = m.group(1)
    assert "Spezifikation" in block, "Abschnitt benennt die Spezifikation-Rolle nicht."
    assert "document-skills:xlsx" in block, "Abschnitt benennt die Engine nicht."
    assert "Engine" in block, "Abschnitt verwendet den Begriff 'Engine' nicht."
    sentences = [s for s in block.replace("\n", " ").split(". ") if s.strip()]
    assert len(sentences) == 2, (
        f"Abschnitt soll aus genau zwei Saetzen bestehen, gefunden: {len(sentences)} ({block!r})"
    )


def test_excel_command_sheet_spec_still_intact():
    """Regressions-Guard: Issue #447 darf die #445-Spezifikation nicht anfassen."""
    text = EXCEL_CMD.read_text(encoding="utf-8")
    assert SHEET_SPEC_COLUMN_FINGERPRINT in text
    for mapping in CLUSTER_COLOR_MAPPINGS:
        assert mapping in text


# --------------------------------------------------------------------------
# Abgleich commands/pickup.md — bewusst kein eigener Router-Skill (Risiko #7)
# --------------------------------------------------------------------------


def test_pickup_command_documents_why_no_router_skill():
    text = PICKUP_CMD.read_text(encoding="utf-8")
    assert "literature-excel" in text, (
        "commands/pickup.md erklaert nicht, warum es (anders als /excel) keinen "
        "eigenen Router-Skill bekommt."
    )
    assert "#447" in text, "commands/pickup.md referenziert Issue #447 nicht im Abgleich-Vermerk."


def test_pickup_backend_block_untouched_byte_identical_to_excel():
    """Der xlsx-backend-Block (Issue #445) muss weiterhin byte-gleich bleiben."""
    start, end = "<!-- xlsx-backend:start -->", "<!-- xlsx-backend:end -->"

    def _block(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        assert start in text and end in text, f"{path.name}: xlsx-backend-Block fehlt."
        return text.split(start, 1)[1].split(end, 1)[0]

    assert _block(EXCEL_CMD) == _block(PICKUP_CMD), (
        "xlsx-backend-Block ist zwischen excel.md und pickup.md auseinandergedriftet "
        "(Issue #445 AC4)."
    )


# --------------------------------------------------------------------------
# AC4 — Eval-Datei deckt beide Pfade ab (should_trigger / should_not_trigger)
# --------------------------------------------------------------------------


def test_trigger_evals_file_exists_and_well_formed():
    assert TRIGGER_EVALS.exists(), f"{TRIGGER_EVALS} fehlt."
    data = json.loads(TRIGGER_EVALS.read_text(encoding="utf-8"))
    assert data.get("component") == "literature-excel"
    assert isinstance(data.get("should_trigger"), list) and data["should_trigger"], (
        "should_trigger darf nicht leer sein (AC1/AC4)."
    )
    assert isinstance(data.get("should_not_trigger"), list) and data["should_not_trigger"], (
        "should_not_trigger darf nicht leer sein (AC2/AC4)."
    )


def test_ac1_wording_covered_by_should_trigger():
    """Der woertliche AC1-Satz muss (in Groß-/Kleinschreibung) im Eval stehen."""
    data = json.loads(TRIGGER_EVALS.read_text(encoding="utf-8"))
    ac1_phrase = "excel-übersicht meiner literatur"
    assert any(ac1_phrase in case.lower() for case in data["should_trigger"]), (
        "Kein should_trigger-Fall deckt den woertlichen AC1-Wortlaut ab."
    )


def test_ac1_phrase_is_declared_in_skill_frontmatter_not_only_in_eval_fixture():
    """AC1-Review-Fund (PR #499): Der woertliche AC1-Satz muss im tatsaechlichen
    Aktivierungs-Artefakt stehen, das der Skill-Dispatcher liest — dem
    SKILL.md-Frontmatter — nicht nur im separaten Eval-Fixture
    (``trigger_evals.json``, s. ``test_ac1_wording_covered_by_should_trigger``).
    Die Fixture-Pruefung allein wuerde eine Drift nicht bemerken, bei der die
    Trigger-Phrasen im Frontmatter geaendert werden, ohne dass jemand das
    Fixture nachzieht — genau der Fall, in dem AC1 stillschweigend bricht,
    obwohl der Eval (API-gated, s. tests/evals/test_triggers.py) weiterhin
    nur skippt und den Bruch nie sichtbar macht.
    """
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.search(r"Trigger-Phrasen:\s*(.+?)\.\n", text, re.DOTALL)
    assert m, "SKILL.md-Frontmatter benennt keinen 'Trigger-Phrasen:'-Block."
    trigger_block = m.group(1).lower()
    ac1_phrase = "excel-übersicht meiner literatur"
    assert ac1_phrase in trigger_block, (
        "Der woertliche AC1-Wortlaut steht nicht im 'Trigger-Phrasen:'-Block "
        "des SKILL.md-Frontmatters — dem Artefakt, das die Skill-Aktivierung "
        "tatsaechlich steuert. Ein Eval-Fixture-Eintrag allein belegt keine "
        "Wirkung (PR #499 Review-Fund zu AC1)."
    )


def test_ac2_generic_examples_covered_by_should_not_trigger():
    """Mind. ein literaturfremdes Gegenbeispiel muss vorhanden sein (AC2)."""
    data = json.loads(TRIGGER_EVALS.read_text(encoding="utf-8"))
    literature_markers = ("literatur", "paper", "quelle", "recherche")
    non_literature_cases = [
        case
        for case in data["should_not_trigger"]
        if not any(marker in case.lower() for marker in literature_markers)
    ]
    assert non_literature_cases, (
        "should_not_trigger enthaelt kein eindeutig literaturfremdes Excel-Beispiel."
    )


def test_readme_skills_doc_does_not_list_bare_excel_trigger():
    """AC2: Die Doku darf keine domaenenfremde Catch-all-Phrase als Trigger listen."""
    text = _docs.SKILLS_DOC.read_text(encoding="utf-8")
    m = re.search(r"\| `literature-excel` \| (.+?) \|", text)
    assert m, "docs/reference/skills.md: keine Tabellenzeile fuer literature-excel."
    trigger_cell = m.group(1)
    phrases = re.findall(r'[„"]([^„""]+)["""]', trigger_cell)
    assert phrases, "literature-excel-Zeile listet keine Trigger-Phrasen."
    for phrase in phrases:
        assert phrase.strip().lower() != "excel", (
            f"Trigger-Phrase '{phrase}' ist eine literaturfremde Catch-all-Phrase."
        )
        assert re.search(r"literatur|paper", phrase, re.IGNORECASE), (
            f"Trigger-Phrase '{phrase}' hat keinen erkennbaren Literaturbezug."
        )


# --------------------------------------------------------------------------
# Skill-Count-Synchronisation (42 -> 43, Issue #391: bibliography-auditor neu;
# zuvor 41 -> 42, Issue #608: peer-review neu; davor 40 -> 41, Issue #610:
# quantitative-analysis neu;
# zuvor 39 -> 40, Issue #605: ai-disclosure neu; zuvor
# 37 -> 39, Issue #473: instrument-design + qualitative-coding neu; zuvor
# 36 -> 37, Issue #392: latex-layout-auditor neu; zuvor 35 -> 36, Issue #472:
# defense-prep neu; zuvor 34 -> 35, nach Merge mit main; ursprünglich 32 -> 33
# vor der Zusammenführung mit den zwischenzeitlich auf main gemergten Skills
# word-export/slide-export, siehe #499-Merge-Commit)
# --------------------------------------------------------------------------


def test_skill_count_is_43_across_docs_and_manifests():
    skill_count = len(
        [p for p in (REPO_ROOT / "skills").glob("*/SKILL.md") if p.parent.name != "_common"]
    )
    assert skill_count == 43, f"Erwartet 43 Skills, gefunden {skill_count}."

    assert "skills-43" in README.read_text(encoding="utf-8")
    assert "43 Skills" in _docs.SKILLS_DOC.read_text(encoding="utf-8")
    assert "43 Skills" in AGENTS_MD.read_text(encoding="utf-8")

    plugin_data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    assert "43" in plugin_data["description"]

    marketplace_data = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    assert "43" in marketplace_data["plugins"][0]["description"]
