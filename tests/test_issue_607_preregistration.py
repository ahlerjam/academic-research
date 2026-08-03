"""Tests fuer Issue #607 — Praeregistrierung (Studienprotokoll, PROSPERO).

Deckt die sechs Akzeptanzkriterien des Issues ab. Urteilendes (Wortlaut der
Feldantworten, ob ein Vorhaben ueberhaupt praeregistrierungspflichtig ist)
bleibt bewusst ausserhalb des Skripts; geprueft wird nur, was deterministisch
sein muss: Klassifikation, Renderer, Platzhalter-Disziplin und die
Aktualisierung von ``academic_context.md``.

| AC | Testfaelle |
| --- | --- |
| AC1 Vorlagenwahl passend + begruendet | ``test_classify_qualitative_is_not_general``, ``test_classify_each_type_returns_expected_template``, ``test_classify_unknown_type_raises`` |
| AC2 PROSPERO-Pflichtfelder | ``test_prospero_protocol_contains_every_required_field_from_reference``, ``test_general_template_does_not_use_prospero_fields`` |
| AC3 Kriterien/Suchstrategie ohne erneute Abfrage | ``test_update_context_writes_both_sections_without_touching_rest``, ``test_update_context_fails_without_existing_file``, ``test_parallel_screening_references_context_criteria``, ``test_query_generator_references_context_strategy`` |
| AC4 keine Fabrikation offener Felder | ``test_missing_field_yields_literal_placeholder``, ``test_missing_context_values_yield_placeholder``, ``test_rerun_yields_identical_protocol`` |
| AC5 Ablageort fuer Abweichungen | ``test_every_template_protocol_contains_abweichungen_section`` |
| AC6 Quelle + Fundstelle | ``test_protocol_contains_quelle_block_with_url_and_date`` |
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "preregistration"
SKILL_MD = SKILL_DIR / "SKILL.md"
PROSPERO_MD = SKILL_DIR / "references" / "prospero-fields.md"
OSF_MD = SKILL_DIR / "references" / "osf-templates.md"
SCRIPT_PATH = SKILL_DIR / "scripts" / "render_protocol.py"

SKILLS_DIR = REPO_ROOT / "skills"
VENDORED_SKILLS = {"_common", "humanizer-de"}

NACHBARN = ["methodology-advisor", "prisma-flow", "parallel-screening", "query-generator"]


def _load_module():
    spec = importlib.util.spec_from_file_location("prereg_render", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"Skript nicht ladbar: {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def render():
    return _load_module()


def _frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, f"{path}: kein Frontmatter gefunden"
    dm = re.search(
        r"^description:\s*(.*?)(?=^[a-zA-Z_][a-zA-Z0-9_-]*:|\Z)", m.group(1), re.DOTALL | re.M
    )
    assert dm, f"{path}: keine description im Frontmatter"
    return " ".join(dm.group(1).split())


def _abgrenzung_section(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^## Abgrenzung\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"{path}: keine '## Abgrenzung'-Section gefunden"
    return m.group(1)


def _headings(markdown: str, level: str = "### ") -> set[str]:
    return {
        zeile[len(level) :].strip() for zeile in markdown.splitlines() if zeile.startswith(level)
    }


# ---------------------------------------------------------------------------
# Grundgeruest
# ---------------------------------------------------------------------------


def test_skill_files_exist() -> None:
    assert SKILL_MD.exists(), f"{SKILL_MD} fehlt"
    assert PROSPERO_MD.exists(), f"{PROSPERO_MD} fehlt"
    assert OSF_MD.exists(), f"{OSF_MD} fehlt"
    assert SCRIPT_PATH.exists(), f"{SCRIPT_PATH} fehlt"


# ---------------------------------------------------------------------------
# AC1 — Vorlagenwahl passend zum Vorhaben, begruendet
# ---------------------------------------------------------------------------


def test_classify_qualitative_is_not_general(render) -> None:
    template, begruendung = render.klassifiziere_vorhaben("qualitativ")
    assert template == "qualitative", "Ein qualitatives Vorhaben darf nicht 'general' bekommen."
    assert begruendung.strip(), "Begruendungstext darf nicht leer sein."


@pytest.mark.parametrize(
    "methodik_typ,erwartet",
    [
        ("systematic-review", "prospero"),
        ("qualitativ", "qualitative"),
        ("sekundaerdaten", "secondary-data"),
        ("quantitativ", "general"),
    ],
)
def test_classify_each_type_returns_expected_template(render, methodik_typ, erwartet) -> None:
    template, begruendung = render.klassifiziere_vorhaben(methodik_typ)
    assert template == erwartet
    assert begruendung.strip()


def test_classify_unknown_type_raises(render) -> None:
    with pytest.raises(ValueError, match="Unbekannter methodik_typ"):
        render.klassifiziere_vorhaben("astrologie")


# ---------------------------------------------------------------------------
# AC2 — PROSPERO-Protokoll mit den dort verlangten Angaben
# ---------------------------------------------------------------------------


def test_prospero_protocol_contains_every_required_field_from_reference(render) -> None:
    pflichtfelder = set(render.lade_pflichtfelder())
    assert len(pflichtfelder) >= 10, "Zu wenige Pflichtfelder geparst — Referenzformat pruefen."
    plan = {"template": "prospero", "felder": {}}
    protokoll = render.rendere_protokoll(plan)
    labels = _headings(protokoll)
    fehlend = pflichtfelder - labels
    assert not fehlend, f"PROSPERO-Pflichtfelder fehlen im Protokoll: {fehlend}"


def test_general_template_does_not_use_prospero_fields(render) -> None:
    prospero_felder = set(render.lade_pflichtfelder())
    plan = {"template": "general", "felder": {}}
    protokoll = render.rendere_protokoll(plan)
    labels = _headings(protokoll)
    assert not (labels & prospero_felder), (
        "Das allgemeine OSF-Template darf keine PROSPERO-Feldnamen uebernehmen."
    )


@pytest.mark.parametrize("template", ["general", "secondary-data", "qualitative"])
def test_osf_template_sections_appear_as_labels(render, template) -> None:
    sektionen = render.lade_osf_felder(template)
    alle_felder = {name for namen in sektionen.values() for name in namen}
    plan = {"template": template, "felder": {}}
    protokoll = render.rendere_protokoll(plan)
    labels = _headings(protokoll)
    fehlend = alle_felder - labels
    assert not fehlend, f"OSF-Template '{template}': Felder fehlen im Protokoll: {fehlend}"


# ---------------------------------------------------------------------------
# AC3 — Kriterien/Suchstrategie ohne erneute Abfrage nutzbar
# ---------------------------------------------------------------------------


def test_update_context_writes_both_sections_without_touching_rest(render) -> None:
    text = (
        "### Profil\n- Universität: FH Leibniz\n\n"
        "### Arbeit\n- Thema: Testthema\n\n"
        "### Gliederung\n[...]\n"
    )
    aktualisiert = render.aktualisiere_academic_context(
        text,
        suchstrategie="(A OR B) AND C",
        einschlusskriterien=["peer-reviewed", "2015-2025"],
        ausschlusskriterien=["Konferenzbeiträge ohne Volltext"],
    )
    assert "### Profil" in aktualisiert and "FH Leibniz" in aktualisiert
    assert "### Arbeit" in aktualisiert and "Testthema" in aktualisiert
    assert "### Gliederung" in aktualisiert
    assert "### Suchstrategie" in aktualisiert
    assert "(A OR B) AND C" in aktualisiert
    assert "### Ein-/Ausschlusskriterien" in aktualisiert
    assert "peer-reviewed" in aktualisiert
    assert "Konferenzbeiträge ohne Volltext" in aktualisiert


def test_update_context_is_idempotent_on_rerun(render) -> None:
    text = "### Profil\n- Universität: FH Leibniz\n"
    erst = render.aktualisiere_academic_context(
        text, suchstrategie="Q1", einschlusskriterien=["a"], ausschlusskriterien=["b"]
    )
    zweit = render.aktualisiere_academic_context(
        erst, suchstrategie="Q1", einschlusskriterien=["a"], ausschlusskriterien=["b"]
    )
    assert erst == zweit, "Ein zweiter Lauf mit denselben Werten darf nichts veraendern."
    assert erst.count("### Suchstrategie") == 1, "Section darf nicht dupliziert werden."


def test_update_context_replaces_previous_values(render) -> None:
    text = "### Suchstrategie\n\nalt\n\n### Ein-/Ausschlusskriterien\n\n**Einschluss**\n- alt\n"
    aktualisiert = render.aktualisiere_academic_context(
        text, suchstrategie="neu", einschlusskriterien=["neu"], ausschlusskriterien=None
    )
    assert "alt" not in aktualisiert
    assert "neu" in aktualisiert


def test_update_context_fails_without_existing_file(render, tmp_path) -> None:
    plan_pfad = tmp_path / "plan.json"
    plan_pfad.write_text('{"suchstrategie": "Q"}', encoding="utf-8")
    context_pfad = tmp_path / "academic_context.md"
    rc = render.main(["update-context", "--plan", str(plan_pfad), "--context", str(context_pfad)])
    assert rc == 1, "Ohne vorhandene academic_context.md darf nicht geschrieben werden."
    assert not context_pfad.exists()


def test_parallel_screening_references_context_criteria() -> None:
    text = (SKILLS_DIR / "parallel-screening" / "SKILL.md").read_text(encoding="utf-8")
    assert "academic_context.md" in text and "Ein-/Ausschlusskriterien" in text, (
        "parallel-screening muss auf die Kriterien-Section aus academic_context.md verweisen (AC3)."
    )


def test_query_generator_references_context_strategy() -> None:
    text = (REPO_ROOT / "agents" / "query-generator.md").read_text(encoding="utf-8")
    assert "academic_context.md" in text and "Suchstrategie" in text, (
        "query-generator muss auf die Suchstrategie-Section aus academic_context.md verweisen (AC3)."
    )


def test_academic_context_template_declares_both_sections() -> None:
    text = (SKILLS_DIR / "academic-context" / "SKILL.md").read_text(encoding="utf-8")
    assert "### Suchstrategie" in text
    assert "### Ein-/Ausschlusskriterien" in text


# ---------------------------------------------------------------------------
# AC4 — keine Fabrikation offener Felder
# ---------------------------------------------------------------------------


def test_missing_field_yields_literal_placeholder(render) -> None:
    plan = {"template": "general", "felder": {"Research questions or hypotheses": None}}
    protokoll = render.rendere_protokoll(plan)
    block = protokoll.split("### Research questions or hypotheses")[1]
    naechster_abschnitt = block.split("###", 1)[0]
    assert render.PLATZHALTER in naechster_abschnitt
    assert "Research questions or hypotheses" not in naechster_abschnitt.replace(
        render.PLATZHALTER, ""
    ), "Kein generierter Ersatztext anstelle des Platzhalters."


def test_answered_field_is_not_replaced_by_placeholder(render) -> None:
    plan = {
        "template": "general",
        "felder": {"Research questions or hypotheses": "Wirkt X auf Y?"},
    }
    protokoll = render.rendere_protokoll(plan)
    assert "Wirkt X auf Y?" in protokoll
    block = protokoll.split("### Research questions or hypotheses")[1].split("###", 1)[0]
    assert render.PLATZHALTER not in block


def test_missing_context_values_yield_placeholder(render) -> None:
    text = "### Profil\n- x\n"
    aktualisiert = render.aktualisiere_academic_context(
        text, suchstrategie=None, einschlusskriterien=None, ausschlusskriterien=None
    )
    assert render.PLATZHALTER in aktualisiert


def test_rerun_yields_identical_protocol(render) -> None:
    plan = {
        "template": "prospero",
        "titel": "Beispiel",
        "begruendung": "Testbegruendung",
        "felder": {"Review question(s)": "Frage X"},
    }
    erst = render.rendere_protokoll(plan)
    zweit = render.rendere_protokoll(plan)
    assert erst == zweit, "Derselbe Plan muss byte-identischen Text liefern (AC4)."


def test_unknown_template_is_rejected(render) -> None:
    with pytest.raises(ValueError, match="Unbekanntes Template"):
        render.rendere_protokoll({"template": "sciencing-harder", "felder": {}})


# ---------------------------------------------------------------------------
# AC5 — Ablageort fuer Abweichungen ist festgelegt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", ["prospero", "general", "secondary-data", "qualitative"])
def test_every_template_protocol_contains_abweichungen_section(render, template) -> None:
    protokoll = render.rendere_protokoll({"template": template, "felder": {}})
    assert "## Abweichungen vom Protokoll" in protokoll


# ---------------------------------------------------------------------------
# AC6 — Quelle + Fundstelle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", ["prospero", "general", "secondary-data", "qualitative"])
def test_protocol_contains_quelle_block_with_url_and_date(render, template) -> None:
    protokoll = render.rendere_protokoll({"template": template, "felder": {}})
    assert "## Quelle" in protokoll
    assert re.search(r"https?://\S+", protokoll), "Quelle-Block ohne URL."
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b|Version\s+\d+", protokoll), (
        "Quelle-Block ohne Abrufdatum oder Vorlagen-Version."
    )


def test_reference_files_name_source_and_retrieval_date() -> None:
    for pfad in (PROSPERO_MD, OSF_MD):
        text = pfad.read_text(encoding="utf-8")
        assert re.search(r"https?://\S+", text), f"{pfad}: keine Quell-URL."
        assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text), f"{pfad}: kein Abrufdatum."


# ---------------------------------------------------------------------------
# Abgrenzung / Aktivierung (Struktur, analog Issue #610)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nachbar", NACHBARN)
def test_skill_description_names_neighbours(nachbar: str) -> None:
    desc = _frontmatter_description(SKILL_MD)
    assert nachbar in desc, f"Frontmatter-description muss '{nachbar}' abgrenzen (AC-Abgrenzung)."


@pytest.mark.parametrize("nachbar", NACHBARN)
def test_abgrenzung_section_names_neighbours(nachbar: str) -> None:
    section = _abgrenzung_section(SKILL_MD)
    assert nachbar in section, f"'## Abgrenzung' nennt '{nachbar}' nicht."


def _quoted_phrases(desc: str) -> list[str]:
    phrasen: list[str] = []
    for quoted in re.findall(r'"([^"]*)"', desc):
        for teil in quoted.split(" / "):
            teil = teil.strip()
            if len(teil) >= 8:
                phrasen.append(teil)
    return phrasen


def test_no_trigger_phrase_collision_across_skills() -> None:
    eigene = _quoted_phrases(_frontmatter_description(SKILL_MD))
    assert len(eigene) >= 5, "Zu wenige Trigger-Phrasen zum Pruefen."
    kollisionen: list[str] = []
    for pfad in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        if pfad.parent.name in VENDORED_SKILLS or pfad == SKILL_MD:
            continue
        fremd = _frontmatter_description(pfad).lower()
        for phrase in eigene:
            if phrase.lower() in fremd:
                kollisionen.append(f"{pfad.parent.name}: {phrase}")
    assert not kollisionen, f"Trigger-Phrasen kollidieren mit anderen Skills: {kollisionen}"


# ---------------------------------------------------------------------------
# Out-of-Scope-Grenzen ausgesprochen (aus dem Issue-Body)
# ---------------------------------------------------------------------------


def test_skill_names_out_of_scope_boundaries() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for begriff in ("out of scope", "Registered Report"):
        assert begriff.lower() in text.lower(), (
            f"SKILL.md muss '{begriff}' als nicht abgedeckt benennen."
        )
