"""Regressionstest fuer Issue #905.

Entscheidungsklassen im Preamble: eine offene Abwaegung wird im Lauf selbst
entschieden und protokolliert statt erfragt; eine fehlende Tatsache fuehrt
weiterhin zur Rueckfrage.

Die Preamble ist Prosa fuers Modell, kein Code — dieser Test prueft deshalb
nur, dass die noetigen Marker/Beispiele/Vorbehalte vorhanden sind, nicht dass
das Modell im Lauf tatsaechlich danach handelt (siehe Plan-Kommentar,
Risiko-Abschnitt). Der Decision-Log-Pfad selbst (Protokollierung, Revision,
"abgeloest bleibt sichtbar") wird gegen echten DB-/Server-Code geprueft.
"""

import os
import re
import tempfile
from pathlib import Path

import yaml
from academic_vault import decision_log
from academic_vault import server as vault_server
from academic_vault.db import VaultDB

REPO_ROOT = Path(__file__).parent.parent
PREAMBLE = REPO_ROOT / "skills/_common/preamble.md"
COMMAND_FILE = REPO_ROOT / "commands/entscheidungen.md"
CHAPTER_WRITER = REPO_ROOT / "skills/chapter-writer/SKILL.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Preamble: beide Klassen mit Beispielen, Protokollierungspflicht,
# "Aufwand kein Rueckfragegrund", bestehende Gates ausgenommen
# ---------------------------------------------------------------------------


def test_preamble_has_both_classes_with_examples():
    text = _read(PREAMBLE)
    assert "Fehlende Tatsache" in text
    assert "Offene Abwägung" in text or "offene Abwägung" in text

    # Beispiele der Tatsachen-Klasse aus dem Issue-Text.
    for example in ("Prüfungsordnung", "Abgabedatum", "Zugangsdaten"):
        assert example in text, f"Tatsachen-Beispiel '{example}' fehlt in der Preamble"

    # Beispiele der Abwaegungs-Klasse aus dem Issue-Text.
    for example in ("Positionierung", "Methodenwahl"):
        assert example in text, f"Abwaegungs-Beispiel '{example}' fehlt in der Preamble"


def test_preamble_requires_decision_log_for_judgment_calls():
    text = _read(PREAMBLE)
    assert "vault.add_decision" in text
    assert "judgment-call" in text
    assert "vault.supersede_decision" in text


def test_preamble_effort_is_no_reason_to_ask():
    text = _read(PREAMBLE)
    assert "Aufwand" in text
    assert "Rückfragegrund" in text or "Rückfrage" in text


def test_preamble_fabrication_rule_untouched():
    """Die bestehende Fabrikationsregel darf nicht verschwinden (Issue #905, Out-of-Scope)."""
    text = _read(PREAMBLE)
    assert "Fehlen Daten: frag" in text
    assert "rate nicht" in text


def test_preamble_exempts_existing_gates():
    text = _read(PREAMBLE)
    assert "outline_gate" in text
    # Der Gate-Bezug muss im neuen Abschnitt stehen, nicht nur zufaellig irgendwo.
    section_start = text.index("Fehlende Tatsache vs. offene Abwägung")
    provenance_start = text.index("## Provenance-Blindheit")
    section = text[section_start:provenance_start]
    assert "outline_gate" in section


def test_chapter_writer_gate_reference_unchanged():
    """Regressions-Guard: outline_gate-Referenz in chapter-writer bleibt bestehen (AC5)."""
    text = _read(CHAPTER_WRITER)
    assert "outline_gate" in text


# ---------------------------------------------------------------------------
# Neue Decision-Kategorie: eigene Konstante, keine Kollision
# ---------------------------------------------------------------------------


def test_judgment_call_category_constant_exists_and_is_unique():
    assert decision_log.JUDGMENT_CALL_CATEGORY == "judgment-call"
    assert decision_log.JUDGMENT_CALL_CATEGORY != decision_log.AUTO_CATEGORY
    assert decision_log.JUDGMENT_CALL_CATEGORY != decision_log.MODEL_VERSION_CATEGORY


# ---------------------------------------------------------------------------
# commands/entscheidungen.md: Frontmatter-Konvention
# ---------------------------------------------------------------------------


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}
    return yaml.safe_load("\n".join(lines[1:end])) or {}


def test_command_file_exists():
    assert COMMAND_FILE.exists(), f"Missing: {COMMAND_FILE}"


def test_command_frontmatter_description_not_empty():
    fm = _parse_frontmatter(COMMAND_FILE)
    assert fm.get("description"), "commands/entscheidungen.md: description fehlt"


def test_command_frontmatter_argument_hint():
    fm = _parse_frontmatter(COMMAND_FILE)
    assert fm.get("argument-hint"), "commands/entscheidungen.md: argument-hint fehlt"


def test_command_frontmatter_allowed_tools_reference_decision_tools():
    fm = _parse_frontmatter(COMMAND_FILE)
    allowed = str(fm.get("allowed-tools", ""))
    assert allowed, "commands/entscheidungen.md: allowed-tools fehlt"
    for tool in (
        "mcp__academic-vault__vault_list_decisions",
        "mcp__academic-vault__vault_add_decision",
        "mcp__academic-vault__vault_supersede_decision",
    ):
        assert tool in allowed, f"commands/entscheidungen.md: '{tool}' fehlt in allowed-tools"


def test_command_frontmatter_disable_model_invocation():
    fm = _parse_frontmatter(COMMAND_FILE)
    assert fm.get("disable-model-invocation") is True


# ---------------------------------------------------------------------------
# Decision-Log-Pfad: protokollieren, auflisten, revidieren, abgeloest bleibt
# sichtbar (AC2 + AC4 gegen echten DB-/Server-Code)
# ---------------------------------------------------------------------------


def make_temp_db() -> tuple[str, VaultDB]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = VaultDB(tmp.name)
    db.init_schema()
    return tmp.name, db


def test_judgment_call_decision_recorded_with_rationale():
    """Eine getroffene Abwaegung ist danach mit Grund nachlesbar (AC2)."""
    db_path, _db = make_temp_db()
    try:
        decision_id = vault_server.add_decision(
            db_path=db_path,
            category=decision_log.JUDGMENT_CALL_CATEGORY,
            text="Positionierung: deskriptiv statt normativ.",
            rationale="Forschungsfrage ist explorativ, keine Handlungsempfehlung gefordert.",
        )
        decisions = vault_server.list_decisions(
            db_path=db_path, category=decision_log.JUDGMENT_CALL_CATEGORY
        )
        assert len(decisions) == 1
        d = decisions[0]
        assert d["decision_id"] == decision_id
        assert (
            d["rationale"] == "Forschungsfrage ist explorativ, keine Handlungsempfehlung gefordert."
        )
    finally:
        os.unlink(db_path)


def test_judgment_call_decision_revision_keeps_old_visible_as_superseded():
    """Revision ueber supersede_decision: alte Decision bleibt sichtbar, aktiv nur die neue (AC4)."""
    db_path, _db = make_temp_db()
    try:
        old_id = vault_server.add_decision(
            db_path=db_path,
            category=decision_log.JUDGMENT_CALL_CATEGORY,
            text="Nur Studien ab 2015.",
            rationale="Aktualitaet.",
        )
        new_id = vault_server.add_decision(
            db_path=db_path,
            category=decision_log.JUDGMENT_CALL_CATEGORY,
            text="Nur Studien ab 2010.",
            rationale="Zu wenig Treffer ab 2015.",
        )
        vault_server.supersede_decision(db_path=db_path, decision_id=old_id, superseded_by=new_id)

        all_decisions = vault_server.list_decisions(
            db_path=db_path, category=decision_log.JUDGMENT_CALL_CATEGORY, active_only=False
        )
        assert {d["decision_id"] for d in all_decisions} == {old_id, new_id}
        old_entry = next(d for d in all_decisions if d["decision_id"] == old_id)
        assert old_entry["superseded_by"] == new_id

        active_decisions = vault_server.list_decisions(
            db_path=db_path, category=decision_log.JUDGMENT_CALL_CATEGORY, active_only=True
        )
        assert [d["decision_id"] for d in active_decisions] == [new_id]
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Doku-Zahl-Guard: commands/*.md-Anzahl bleibt mit README/Referenz synchron
# (Regressionsschutz gegen genau die Drift, die dieser PR selbst ausgeloest
# haette, wenn die Zahl-Updates vergessen worden waeren).
# ---------------------------------------------------------------------------


def test_command_count_includes_new_command():
    count = len(list((REPO_ROOT / "commands").glob("*.md")))
    readme = _read(REPO_ROOT / "README.md")
    m = re.search(r"(\d+)\s+Slash-Commands\b", readme)
    assert m, "README.md: 'N Slash-Commands' nicht gefunden"
    assert int(m.group(1)) == count
