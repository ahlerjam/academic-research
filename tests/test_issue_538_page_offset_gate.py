"""Tests fuer Issue #538 — page_offset-Bestaetigungs-Gate beim Buch-Import (Audit R2).

Audit-Risiko R2: `skills/book-handler/SKILL.md` Schritt 2.5 speicherte das
Ergebnis von `scripts/page_offset.py` ohne Rueckfrage per
`vault.set_page_offset`. Ein falscher Offset macht damit stillschweigend alle
Seitenzahlen eines Buchs systematisch falsch.

Das Artefakt ist die Markdown-Anweisung (nicht Python-Verhalten), die Tests
sind daher Text-Assertions auf SKILL.md — analog zu
`tests/test_material_passport_skill.py::TestReproLockAskUserQuestionGate`
(Repro-Lock-Gate, #536) und `tests/test_issue_537_interactive_defaults.py`.

Akzeptanzkriterien aus dem Issue:
- AC1: `set_page_offset` wird erst nach bestaetigter Auswahl aufgerufen; die
  Frage zeigt Offset und mindestens ein Beispiel-Mapping.
- AC2: Ablehnung fuehrt zu manueller Offset-Eingabe statt stillem Weiter.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skills" / "book-handler" / "SKILL.md"
SIZES_BASELINE = REPO_ROOT / "tests" / "baselines" / "skill_sizes.json"
TOKENS_BASELINE = REPO_ROOT / "tests" / "baselines" / "tokens.json"


def _content() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _frontmatter() -> dict:
    text = _content()
    assert text.startswith("---\n"), "SKILL.md ohne Frontmatter"
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def _step_2_5() -> str:
    """Liefert den Abschnitt `### 2.5. ...` bis zur naechsten `### `-Ueberschrift."""
    content = _content()
    start = content.find("### 2.5.")
    assert start != -1, "Schritt 2.5 (page_offset) nicht in SKILL.md gefunden"
    end = content.find("\n### ", start + 1)
    assert end != -1, "Kein Abschnitt nach Schritt 2.5 gefunden"
    return content[start:end]


# ---------------------------------------------------------------------------
# AC1: Gate vor dem Speichern, mit Offset und Beispiel-Mapping in der Frage
# ---------------------------------------------------------------------------


def test_allowed_tools_declares_ask_user_question() -> None:
    """AC1-Voraussetzung: der Skill darf AskUserQuestion ueberhaupt aufrufen."""
    allowed = _frontmatter().get("allowed-tools")
    assert isinstance(allowed, list), "allowed-tools fehlt oder ist keine YAML-Liste"
    assert "AskUserQuestion" in allowed, (
        "book-handler stellt in Schritt 2.5 ein AskUserQuestion-Gate, muss das "
        f"Tool aber auch in allowed-tools deklarieren (ist: {allowed})"
    )


def test_gate_is_ask_user_question_not_prose() -> None:
    """AC1: Schritt 2.5 beschreibt ein echtes AskUserQuestion-Gate."""
    assert "AskUserQuestion" in _step_2_5(), (
        "Schritt 2.5 muss ein AskUserQuestion-Gate beschreiben — eine "
        "Prosa-Rueckfrage ('nachfragen') genuegt nicht"
    )


def test_gate_precedes_every_set_page_offset_call() -> None:
    """AC1: kein `set_page_offset` ohne textuell vorangestelltes Gate."""
    content = _content()
    ask_idx = content.find("AskUserQuestion")
    assert ask_idx != -1, "Kein AskUserQuestion in SKILL.md"

    calls = [m.start() for m in re.finditer(r"set_page_offset\(", content)]
    assert calls, "SKILL.md ruft `vault.set_page_offset(...)` nicht mehr auf"
    assert all(ask_idx < call for call in calls), (
        "Jeder `set_page_offset(...)`-Aufruf muss textuell NACH dem AskUserQuestion-Gate stehen"
    )


def test_question_shows_offset_and_example_mapping() -> None:
    """AC1: die Frage nennt den Offset UND mindestens ein Beispiel-Mapping."""
    step = _step_2_5()
    assert "{offset}" in step, (
        "Der berechnete Offset muss als Platzhalter in der Frage auftauchen, "
        "damit der User den konkreten Wert sieht"
    )
    mapping_lines = [
        line for line in step.splitlines() if "PDF-Seite" in line and "gedruckte Seite" in line
    ]
    assert mapping_lines, (
        "Schritt 2.5 muss mindestens ein Beispiel-Mapping "
        "'PDF-Seite ... = gedruckte Seite ...' zur Plausibilisierung zeigen"
    )


def test_example_mapping_stands_in_an_option_line() -> None:
    """AC1 praeziser: das Mapping steht in der Optionszeile selbst, nicht nur im Fliesstext.

    Sonst koennte das Gate mit einer nackten Ja/Nein-Frage gestellt werden und
    der User bestaetigt eine Zahl, deren Bedeutung er nicht sieht.
    """
    option_lines = [
        line.strip()
        for line in _step_2_5().splitlines()
        if line.strip().startswith("-")
        and "PDF-Seite" in line
        and "gedruckte Seite" in line
        and "{offset}" in line
    ]
    assert option_lines, (
        "Mindestens eine AskUserQuestion-Optionszeile muss Offset und "
        "Beispiel-Mapping (PDF-Seite <-> gedruckte Seite) selbst tragen"
    )


def test_no_unconditional_save_instruction_left() -> None:
    """AC1-Regression: die alte bedingungslose Speicher-Anweisung ist weg."""
    step = _step_2_5()
    assert "Ergebnis via `vault.set_page_offset({citekey}, {offset})` speichern." not in step, (
        "Die alte Formulierung speichert das Skript-Ergebnis ohne Bestaetigung "
        "— genau der Befund aus Audit-Risiko R2"
    )


# ---------------------------------------------------------------------------
# AC2: Ablehnung fuehrt zur manuellen Eingabe, nicht zu stillem Weiter
# ---------------------------------------------------------------------------


def test_rejection_path_asks_for_manual_offset() -> None:
    """AC2: der Ablehnungs-Pfad verlangt einen vom User genannten Offset."""
    step = _step_2_5().lower()
    assert "manuell" in step or "selbst eingeben" in step, (
        "Schritt 2.5 muss den Ablehnungs-Pfad als manuelle Offset-Eingabe beschreiben"
    )


def test_rejection_path_forbids_silent_fallback() -> None:
    """AC2: der berechnete Wert darf bei Ablehnung nicht doch gespeichert werden."""
    step = _step_2_5()
    assert re.search(r"nie .{0,40}(ungefragt|ohne Best[äa]tigung)", step) or re.search(
        r"(ungefragt|ohne Best[äa]tigung) .{0,40}(nie|nicht)", step
    ), (
        "Schritt 2.5 muss ausdruecklich verbieten, den berechneten Offset ohne "
        "Bestaetigung zu speichern (stilles Weiter war der Befund R2)"
    )


def test_rejection_path_is_not_an_error_path() -> None:
    """AC2: Ablehnung ist der normale Korrektur-Pfad, kein Abbruch."""
    step = _step_2_5()
    assert "abgebrochen" not in step.lower(), (
        "Ablehnung fuehrt zur manuellen Eingabe, nicht zum Abbruch des Imports"
    )


# ---------------------------------------------------------------------------
# Guard-Baselines: die Anhebung muss dem Netto-Zuwachs entsprechen
# ---------------------------------------------------------------------------


def test_size_guard_still_has_margin() -> None:
    """`test_token_reduction` (>= 1400 Zeichen unter Baseline) bleibt erfuellt.

    Der Gate-Text laesst book-handler wachsen; die Baseline wird — wie im Repo
    etabliert (vgl. 9962c22, #540) — um den Netto-Zuwachs angehoben. Dieser
    Test haelt fest, dass die Anhebung den Guard nicht ueber den geforderten
    Mindestabstand hinaus entwertet.
    """
    sizes = json.loads(SIZES_BASELINE.read_text(encoding="utf-8"))
    baseline = sizes["book-handler"]
    current = len(_content())
    delta = baseline - current
    assert delta >= 1400, f"Guard-Marge zu klein: {delta} (Baseline {baseline}, aktuell {current})"
    assert delta < 1600, (
        f"Baseline {baseline} liegt {delta} Zeichen ueber der Datei — mehr als "
        "der Netto-Zuwachs, die Anhebung waere damit ein Freibrief statt einer "
        "Korrektur"
    )


def test_token_baseline_covers_current_size_without_headroom_abuse() -> None:
    """Die tokens.json-Anhebung bleibt ebenfalls am tatsaechlichen Zuwachs."""
    tokens = json.loads(TOKENS_BASELINE.read_text(encoding="utf-8"))
    baseline = tokens["book-handler"]
    current = -(-len(_content()) // 4)  # cl100k-Proxy wie tests/test_skills_manifest.py
    assert current <= baseline * 1.20, (
        f"Token-Drift {current} > {baseline} * 1.20 — Baseline nicht angehoben"
    )
    assert baseline <= current, (
        f"tokens.json-Baseline {baseline} liegt ueber dem Ist-Wert {current}; "
        "die Baseline ist der gemessene Stand, kein Vorschuss"
    )
