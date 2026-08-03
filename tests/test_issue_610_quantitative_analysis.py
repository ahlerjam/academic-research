"""Tests fuer Issue #610 — eigene quantitative Auswertung.

Deckt die sechs Akzeptanzkriterien des Issues ab. Alles Urteilende
(Verfahrenswahl im Dialog, Deutung des Ergebnisses) bleibt bewusst ausserhalb
des Skripts; hier wird nur geprueft, was deterministisch und wiederholbar sein
muss: Ingest, Rechenkern, Voraussetzungspruefungen, Berichtsform und die
Abgrenzung des Skills gegen seine Nachbarn.

| AC | Testfaelle |
| --- | --- |
| AC1 Umfang entschieden | ``test_skill_declares_scope_boundaries`` |
| AC2 reproduzierbar | ``test_rerun_yields_identical_results``, ``test_protokoll_contains_rerun_command_and_data_hash``, ``test_changed_data_changes_hash`` |
| AC3 Effektstaerke + KI | ``test_every_inference_result_has_effect_size_and_ci``, ``test_render_rejects_result_without_effect_size``, ``test_render_rejects_result_without_ci`` |
| AC4 Voraussetzungen | ``test_assumption_checks_are_reported_when_met``, ``test_violated_assumption_is_named_with_alternative``, ``test_violation_does_not_silently_switch_procedure`` |
| AC5 keine Deutung | ``test_report_contains_no_interpretive_claims``, ``test_report_ends_with_interpretation_placeholder``, ``test_skill_states_no_interpretation_rule`` |
| AC6 Abgrenzung | ``test_skill_description_names_neighbours``, ``test_abgrenzung_section_names_neighbours``, ``test_no_trigger_phrase_collision_across_skills`` |
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "quantitative-analysis"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCE_MD = SKILL_DIR / "references" / "verfahren.md"
SCRIPT_PATH = SKILL_DIR / "scripts" / "analyze.py"

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "quantitative_analysis"
FIXTURE_CSV = FIXTURE_DIR / "erhebung.csv"
FIXTURE_PLAN = FIXTURE_DIR / "analyseplan.json"

SKILLS_DIR = REPO_ROOT / "skills"
VENDORED_SKILLS = {"_common", "humanizer-de"}


def _load_module():
    """Laedt das Skill-Skript als Modul (Skills liegen nicht im Python-Paketpfad)."""
    spec = importlib.util.spec_from_file_location("quant_analyze", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"Skript nicht ladbar: {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analyze():
    return _load_module()


@pytest.fixture(scope="module")
def lauf(tmp_path_factory, analyze):
    """Ein vollstaendiger ``run``-Durchlauf ueber den Fixture-Datensatz."""
    out = tmp_path_factory.mktemp("lauf")
    rc = analyze.main(
        [
            "run",
            "--data",
            str(FIXTURE_CSV),
            "--plan",
            str(FIXTURE_PLAN),
            "--out",
            str(out),
        ]
    )
    assert rc == 0, "run-Subkommando lieferte einen Fehlercode"
    return out


@pytest.fixture(scope="module")
def ergebnisse(lauf):
    return json.loads((lauf / "ergebnisse.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def protokoll(lauf):
    return (lauf / "protokoll.md").read_text(encoding="utf-8")


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


def _inferenz(ergebnisse: dict) -> list[dict]:
    return [e for e in ergebnisse["ergebnisse"] if e["typ"] == "inferenz"]


def _by_id(ergebnisse: dict, analysis_id: str) -> dict:
    treffer = [e for e in ergebnisse["ergebnisse"] if e["id"] == analysis_id]
    assert treffer, f"Kein Ergebnis mit id={analysis_id!r}"
    return treffer[0]


# ---------------------------------------------------------------------------
# Grundgeruest
# ---------------------------------------------------------------------------


def test_skill_files_exist() -> None:
    assert SKILL_MD.exists(), f"{SKILL_MD} fehlt"
    assert REFERENCE_MD.exists(), f"{REFERENCE_MD} fehlt"
    assert SCRIPT_PATH.exists(), f"{SCRIPT_PATH} fehlt"


def test_every_planned_analysis_yields_a_result(ergebnisse) -> None:
    plan = json.loads(FIXTURE_PLAN.read_text(encoding="utf-8"))
    geplant = [a["id"] for a in plan["analysen"]]
    berichtet = [e["id"] for e in ergebnisse["ergebnisse"]]
    assert berichtet == geplant, (
        "Jede geplante Analyse muss genau ein Ergebnis in Planreihenfolge liefern."
    )


def test_descriptive_result_reports_missing_values(ergebnisse) -> None:
    d1 = _by_id(ergebnisse, "d1")
    assert d1["typ"] == "deskriptiv"
    score = d1["variablen"]["score"]
    assert score["n_fehlend"] == 1, "Der leere score-Wert muss als fehlend gezaehlt werden."
    assert score["n"] == 59
    alter = d1["variablen"]["alter"]
    assert alter["n_fehlend"] == 1, "'NA' muss als fehlender Wert erkannt werden."
    for key in ("m", "sd", "median", "iqr", "min", "max"):
        assert key in score, f"Deskription ohne Kennwert {key!r}"
    gruppe = d1["variablen"]["gruppe"]
    assert gruppe["haeufigkeiten"]["A"] == 30


def test_unknown_verfahren_is_rejected(analyze, tmp_path) -> None:
    plan = json.loads(FIXTURE_PLAN.read_text(encoding="utf-8"))
    plan["analysen"] = [{"id": "x", "verfahren": "strukturgleichungsmodell", "messwert": "score"}]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="strukturgleichungsmodell"):
        analyze.fuehre_plan_aus(
            analyze.lade_datensatz(FIXTURE_CSV, plan["fehlende_werte"]),
            json.loads(plan_path.read_text(encoding="utf-8")),
        )


# ---------------------------------------------------------------------------
# AC1 — Umfang der ersten Fassung ist entschieden und ausgesprochen
# ---------------------------------------------------------------------------


def test_skill_declares_scope_boundaries() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for begriff in ("Regression", "Post-hoc", "Poweranalyse"):
        assert begriff in text, (
            f"SKILL.md muss '{begriff}' ausdruecklich als nicht abgedeckt benennen (AC1)."
        )


def test_anova_result_names_missing_posthoc(ergebnisse) -> None:
    a1 = _by_id(ergebnisse, "a1")
    hinweise = " ".join(a1["hinweise"])
    assert "Post-hoc" in hinweise, (
        "Der Omnibus-Test muss aussprechen, dass Post-hoc-Vergleiche nicht abgedeckt sind."
    )


# ---------------------------------------------------------------------------
# AC2 — reproduzierbar
# ---------------------------------------------------------------------------


def test_rerun_yields_identical_results(analyze, tmp_path, lauf) -> None:
    zweiter = tmp_path / "zweiter"
    rc = analyze.main(
        ["run", "--data", str(FIXTURE_CSV), "--plan", str(FIXTURE_PLAN), "--out", str(zweiter)]
    )
    assert rc == 0
    erst = (lauf / "ergebnisse.json").read_bytes()
    zweit = (zweiter / "ergebnisse.json").read_bytes()
    assert erst == zweit, "Zwei Laeufe ueber dieselben Daten muessen byte-identisch sein (AC2)."


def test_run_meta_is_separate_from_results(lauf) -> None:
    ergebnisse = json.loads((lauf / "ergebnisse.json").read_text(encoding="utf-8"))
    meta = json.loads((lauf / "lauf_meta.json").read_text(encoding="utf-8"))
    assert "lauf_meta" not in ergebnisse, (
        "Zeitstempel/Versionen gehoeren in lauf_meta.json, nicht in ergebnisse.json (AC2)."
    )
    assert meta["zeitpunkt"], "lauf_meta.json ohne Zeitstempel"
    assert meta["versionen"]["python"], "lauf_meta.json ohne Python-Version"
    assert meta["versionen"]["scipy"], "lauf_meta.json ohne scipy-Version"
    assert meta["versionen"]["numpy"], "lauf_meta.json ohne numpy-Version"


def test_protokoll_contains_rerun_command_and_data_hash(protokoll, ergebnisse) -> None:
    assert "analyze.py run" in protokoll, "Protokoll ohne Wiederhol-Kommandozeile (AC2)."
    assert "--plan" in protokoll and "--data" in protokoll
    assert ergebnisse["daten_sha256"] in protokoll, "Protokoll ohne SHA-256 der Rohdatei (AC2)."
    assert re.search(r"scipy\s+\S+", protokoll), "Protokoll ohne scipy-Version (AC2)."


def test_changed_data_changes_hash(analyze, tmp_path) -> None:
    manipuliert = tmp_path / "erhebung.csv"
    original = FIXTURE_CSV.read_text(encoding="utf-8")
    manipuliert.write_text(original.replace("P001", "P999", 1), encoding="utf-8")
    out = tmp_path / "out"
    assert (
        analyze.main(
            ["run", "--data", str(manipuliert), "--plan", str(FIXTURE_PLAN), "--out", str(out)]
        )
        == 0
    )
    neu = json.loads((out / "ergebnisse.json").read_text(encoding="utf-8"))
    assert neu["daten_sha256"] != analyze.datei_sha256(FIXTURE_CSV), (
        "Geaenderte Rohdaten muessen einen anderen SHA-256 tragen (AC2)."
    )


# ---------------------------------------------------------------------------
# AC3 — Effektstaerke und Vertrauensintervall
# ---------------------------------------------------------------------------


def test_every_inference_result_has_effect_size_and_ci(ergebnisse) -> None:
    inferenz = _inferenz(ergebnisse)
    assert len(inferenz) >= 10, "Der Fixture-Plan deckt zu wenige Verfahren ab."
    for e in inferenz:
        effekt = e.get("effekt") or {}
        assert effekt.get("name"), f"{e['id']}: Effektstaerke ohne Namen"
        assert isinstance(effekt.get("wert"), float), f"{e['id']}: Effektstaerke ohne Wert"
        ci = e.get("ci") or {}
        for key in ("lo", "hi", "niveau", "methode", "bezug"):
            assert key in ci, f"{e['id']}: Vertrauensintervall ohne {key!r}"
        assert ci["lo"] <= ci["hi"], f"{e['id']}: Intervallgrenzen vertauscht"
        assert e["statistik"]["name"], f"{e['id']}: Teststatistik ohne Namen"
        assert isinstance(e["p"], float), f"{e['id']}: p-Wert fehlt"


def test_render_rejects_result_without_effect_size(analyze, ergebnisse, lauf) -> None:
    meta = json.loads((lauf / "lauf_meta.json").read_text(encoding="utf-8"))
    kaputt = json.loads(json.dumps(ergebnisse))
    ziel = next(e for e in kaputt["ergebnisse"] if e["typ"] == "inferenz")
    ziel.pop("effekt")
    with pytest.raises(ValueError, match="Effektstärke"):
        analyze.rendere_protokoll(kaputt, meta)


def test_render_rejects_result_without_ci(analyze, ergebnisse, lauf) -> None:
    meta = json.loads((lauf / "lauf_meta.json").read_text(encoding="utf-8"))
    kaputt = json.loads(json.dumps(ergebnisse))
    ziel = next(e for e in kaputt["ergebnisse"] if e["typ"] == "inferenz")
    ziel.pop("ci")
    with pytest.raises(ValueError, match="Vertrauensintervall"):
        analyze.rendere_protokoll(kaputt, meta)


def test_tiny_p_value_survives_rounding(ergebnisse) -> None:
    """Ein p von 1e-9 darf nicht auf 0.0 gerundet werden — sonst ist es nicht mehr lesbar."""
    t3 = _by_id(ergebnisse, "t3")
    assert 0.0 < t3["p"] < 0.001, (
        f"p-Wert des gepaarten t-Tests ist {t3['p']!r} — auf 0.0 gerundet wäre "
        f"er weder berichtbar noch von 'exakt null' unterscheidbar."
    )


def test_tiny_p_value_does_not_flip_the_test_decision(protokoll, ergebnisse) -> None:
    """Der auffälligste Fall im Fixture-Plan: p ≈ 1e-9 muss zur Verwerfung führen."""
    t3 = _by_id(ergebnisse, "t3")
    assert t3["p"] < ergebnisse["alpha"]
    block = protokoll.split("### t3 ")[1].split("\n### ")[0]
    assert "wird verworfen" in block, (
        "Bei p weit unter α muss die Testentscheidung 'verworfen' lauten."
    )
    assert "p = 0.0000" not in block, "p-Werte unter der Anzeigegrenze gehören als '< …' berichtet."


def test_protokoll_reports_effect_size_and_ci_for_every_test(protokoll, ergebnisse) -> None:
    for e in _inferenz(ergebnisse):
        block = protokoll.split(f"### {e['id']} ")[1].split("\n### ")[0]
        assert e["effekt"]["name"] in block, f"{e['id']}: Effektstaerke fehlt im Protokoll"
        assert "95-%-Konfidenzintervall" in block or "Konfidenzintervall" in block, (
            f"{e['id']}: Konfidenzintervall fehlt im Protokoll"
        )


# ---------------------------------------------------------------------------
# AC4 — Voraussetzungen werden geprueft und berichtet
# ---------------------------------------------------------------------------


def test_assumption_checks_are_reported_when_met(ergebnisse, protokoll) -> None:
    t1 = _by_id(ergebnisse, "t1")
    namen = [v["name"] for v in t1["voraussetzungen"]]
    assert any("Shapiro-Wilk" in n for n in namen), "t-Test ohne Normalverteilungspruefung"
    assert any("Levene" in n for n in namen), "t-Test ohne Varianzhomogenitaetspruefung"
    for v in t1["voraussetzungen"]:
        assert "verletzt" in v, "Voraussetzung ohne Verdikt"
        assert v["kennwert"] is not None, "Voraussetzung ohne Pruefstatistik"
    block = protokoll.split("### t1 ")[1].split("\n### ")[0]
    assert "Voraussetzungen" in block, "Protokoll berichtet erfuellte Voraussetzungen nicht."
    assert "Shapiro-Wilk" in block


def test_violated_assumption_is_named_with_alternative(ergebnisse, protokoll) -> None:
    t4 = _by_id(ergebnisse, "t4")
    verletzt = [v for v in t4["voraussetzungen"] if v["verletzt"]]
    assert verletzt, "Der rechtsschiefe Datensatz muss die Normalverteilungsannahme verletzen."
    for v in verletzt:
        assert v["alternative"], f"Verletzte Voraussetzung {v['name']!r} ohne benannte Alternative"
    block = protokoll.split("### t4 ")[1].split("\n### ")[0]
    assert "verletzt" in block.lower(), "Protokoll spricht die Verletzung nicht aus (AC4)."
    assert "Mann-Whitney" in block, "Protokoll nennt die Alternative nicht (AC4)."


def test_violation_does_not_silently_switch_procedure(ergebnisse) -> None:
    t4 = _by_id(ergebnisse, "t4")
    assert t4["verfahren"] == "t_test_unabhaengig", (
        "Eine verletzte Voraussetzung darf das geplante Verfahren nicht still ersetzen (AC4)."
    )
    assert t4["statistik"]["name"] == "t"


def test_every_inference_result_has_assumption_block(ergebnisse) -> None:
    for e in _inferenz(ergebnisse):
        assert e["voraussetzungen"], f"{e['id']}: leerer Voraussetzungsblock"


def test_chi_square_reports_expected_cell_frequency(ergebnisse) -> None:
    c1 = _by_id(ergebnisse, "c1")
    namen = [v["name"] for v in c1["voraussetzungen"]]
    assert any("erwartete" in n.lower() for n in namen), (
        "Chi-Quadrat-Test ohne Pruefung der erwarteten Zellhaeufigkeiten"
    )


# ---------------------------------------------------------------------------
# AC5 — keine inhaltliche Deutung
# ---------------------------------------------------------------------------

DEUTUNGS_BLACKLIST = [
    "bestätigt die Hypothese",
    "zeigt, dass",
    "belegt",
    "widerlegt",
    "beweist",
    "bedeutet, dass",
    "erwartungsgemäß",
    "wie erwartet",
]


def test_report_contains_no_interpretive_claims(protokoll) -> None:
    treffer = [w for w in DEUTUNGS_BLACKLIST if w.lower() in protokoll.lower()]
    assert not treffer, f"Protokoll enthaelt deutende Formulierungen: {treffer} (AC5)"


def test_report_ends_with_interpretation_placeholder(protokoll) -> None:
    assert "Deutung: [vom Autor zu ergänzen]" in protokoll, (
        "Protokoll muss die Deutung als Leerstelle ausweisen (AC5)."
    )


def test_skill_states_no_interpretation_rule() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "Deutung" in text
    assert re.search(r"keine (inhaltliche )?Deutung", text, re.I), (
        "SKILL.md muss das Deutungsverbot ausdruecklich formulieren (AC5)."
    )


# ---------------------------------------------------------------------------
# AC6 — Abgrenzung
# ---------------------------------------------------------------------------

NACHBARN = ("methodology-advisor", "qualitative-coding", "meta-analysis")


@pytest.mark.parametrize("nachbar", NACHBARN)
def test_skill_description_names_neighbours(nachbar: str) -> None:
    desc = _frontmatter_description(SKILL_MD)
    assert nachbar in desc, (
        f"Frontmatter-description muss '{nachbar}' abgrenzen — der Body allein "
        f"steuert die Aktivierung nicht (AC6)."
    )


@pytest.mark.parametrize("nachbar", NACHBARN)
def test_abgrenzung_section_names_neighbours(nachbar: str) -> None:
    section = _abgrenzung_section(SKILL_MD)
    assert nachbar in section, f"'## Abgrenzung' nennt '{nachbar}' nicht (AC6)."


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
    assert not kollisionen, f"Trigger-Phrasen kollidieren mit anderen Skills: {kollisionen} (AC6)"


def test_neighbours_point_back_to_quantitative_analysis() -> None:
    """Abgrenzung wirkt nur beidseitig — sonst greift der falsche Skill zuerst zu.

    ``methodology-advisor`` verweist bewusst aus seinem Methodenkatalog statt aus
    der SKILL.md: Die SKILL.md liegt 15 Zeichen unter der Grenze von
    ``test_token_reduction`` (>= 1400 Zeichen unter Baseline), dort ist kein Platz
    mehr. Der Katalog wird ohnehin bei jeder Methodenwahl gelesen.
    """
    coding = SKILLS_DIR / "qualitative-coding" / "SKILL.md"
    assert "quantitative-analysis" in _abgrenzung_section(coding), (
        f"{coding}: Abgrenzung verweist nicht auf 'quantitative-analysis' (AC6)."
    )
    katalog = SKILLS_DIR / "methodology-advisor" / "methodology-catalog.md"
    assert "quantitative-analysis" in katalog.read_text(encoding="utf-8"), (
        f"{katalog}: Methodenkatalog verweist nicht auf 'quantitative-analysis' (AC6)."
    )
    agent = REPO_ROOT / "agents" / "meta-analysis.md"
    assert "quantitative-analysis" in agent.read_text(encoding="utf-8"), (
        "agents/meta-analysis.md grenzt sich nicht gegen 'quantitative-analysis' ab (AC6)."
    )


# ---------------------------------------------------------------------------
# Referenz + Vault-Anbindung
# ---------------------------------------------------------------------------


def test_reference_covers_every_supported_verfahren(analyze) -> None:
    text = REFERENCE_MD.read_text(encoding="utf-8")
    for name in analyze.VERFAHREN:
        assert name in text, f"references/verfahren.md dokumentiert '{name}' nicht."


def test_skill_documents_vault_wiring() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "vault.add_decision" in text, "SKILL.md ohne Decision-Log-Anbindung"
    assert "vault.add_figure" in text, "SKILL.md ohne Ergebnis-Anbindung an den Vault"
    assert "vault.is_locked" in text, "SKILL.md prueft den Vault-Lock nicht"


def test_skill_keeps_raw_data_out_of_the_vault() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert re.search(r"Rohdaten.*(nicht|ausserhalb|außerhalb)", text, re.S | re.I), (
        "SKILL.md muss aussprechen, dass die Falldaten nicht in den Vault wandern."
    )
