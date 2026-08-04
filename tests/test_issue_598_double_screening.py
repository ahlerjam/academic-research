"""Tests fuer Issue #598 — blindes Doppel-Screening mit Uebereinstimmungsmass.

Baut auf der Buchfuehrung aus Issue #460 (``screening_ledger.py``) auf: eine
dritte Dimension ``round`` (1, 2, ``"human"``) zusaetzlich zu
``paper_id``+``stage``. Blindheit ist strukturell gratis (Runde 2 ist ein
eigener Aufruf ohne Runde-1-Text im Kontext) und wird in ``SKILL.md`` als
Ausfuehrungsvorschrift verankert, nicht im Code erzwungen.

Akzeptanzkriterium -> Testfall:

- Zwei getrennte Runden, Runde 2 ohne Runde-1-Urteil im Kontext ->
  ``test_double_screening_records_two_independent_rounds``,
  ``test_skill_md_documents_blind_second_round``
- Uebereinstimmungsmass mit Fallzahl ->
  ``test_compute_agreement_returns_kappa_and_n``,
  ``test_compute_agreement_perfect_agreement_returns_one``
- Widersprechende Urteile gesammelt vorgelegt, nicht automatisch entschieden ->
  ``test_dissent_cases_lists_disagreements``,
  ``test_dissent_not_written_to_vault_before_human_decision``
- Menschliche Entscheidung von Agenten-Urteil unterscheidbar ->
  ``test_human_resolution_marked_decided_by_human``,
  ``test_merge_double_prefers_human_over_dissent``
- Einfaches Screening per Schalter, verhaelt sich exakt wie heute ->
  ``test_simple_mode_switch_disables_second_round`` + die bestehende Suite
  ``tests/test_issue_460_parallel_screening.py`` bleibt unveraendert gruen.
- Abbruch nach erster Judge-Welle hinterlaesst keine halben Doppelurteile als
  vollstaendig ->
  ``test_pending_round_after_partial_first_wave_still_open``,
  ``test_resume_does_not_treat_single_round_as_double_complete``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "parallel-screening"
CONFIG_PATH = REPO_ROOT / "config" / "parallel_agents.json"

sys.path.insert(0, str(SKILL_DIR / "scripts"))


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "session"
    d.mkdir()
    return str(d)


def _round1(paper_id: str) -> dict:
    return {
        "paper_id": paper_id,
        "decision": "include",
        "reason": "Thema und Studientyp erfuellen die Einschlusskriterien",
        "criterion": "topic",
    }


def _round2_agree(paper_id: str) -> dict:
    return {
        "paper_id": paper_id,
        "decision": "include",
        "reason": "Population und Design passen zur Fragestellung",
        "criterion": "population",
    }


def _round2_disagree(paper_id: str) -> dict:
    return {
        "paper_id": paper_id,
        "decision": "exclude",
        "reason": "Kontrollgruppe fehlt laut Abstract",
        "criterion": "study_design",
    }


# ---------------------------------------------------------------------------
# Zwei getrennte, blinde Runden
# ---------------------------------------------------------------------------


def test_double_screening_records_two_independent_rounds(session_dir):
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="screening-judge#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_agree("p1"), agent="screening-judge#2", wave=1, round=2)

    rows = [r for r in sl.read_ledger(session_dir) if r["paper_id"] == "p1"]
    assert len(rows) == 2, rows
    by_round = {r["round"]: r for r in rows}
    assert by_round[1]["agent"] == "screening-judge#1"
    assert by_round[2]["agent"] == "screening-judge#2"
    assert by_round[1]["decision"] == "include"
    assert by_round[2]["decision"] == "include"


def test_second_round_idempotent_independent_of_first(session_dir):
    """Runde 1 und Runde 2 sind getrennte Idempotenz-Slots — (paper_id, stage, round)."""
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="screening-judge#1", wave=1, round=1)
    sl.record_decision(session_dir, _round1("p1"), agent="screening-judge#9", wave=9, round=1)
    sl.record_decision(session_dir, _round2_agree("p1"), agent="screening-judge#2", wave=1, round=2)

    rows = [r for r in sl.read_ledger(session_dir) if r["paper_id"] == "p1"]
    assert len(rows) == 2
    by_round = {r["round"]: r for r in rows}
    assert by_round[1]["agent"] == "screening-judge#1", "Erstentscheidung Runde 1 bleibt stehen"


def test_old_ledger_rows_without_round_field_count_as_round_one(session_dir):
    """Rueckwaertskompatibilitaet: Ledger-Zeilen aus #460 kennen kein 'round'-Feld."""
    import screening_ledger as sl

    path = sl.ledger_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy_entry = {
        "paper_id": "legacy1",
        "decision": "include",
        "reason": "alt",
        "stage": "screening",
        "agent": "screening-judge#1",
        "wave": 1,
        "ts": 1,
    }
    path.write_text(json.dumps(legacy_entry) + "\n", encoding="utf-8")

    assert sl.pending_round(["legacy1"], session_dir, round=1) == []
    buckets = sl.merge(session_dir)
    assert "legacy1" in buckets["include"]


def test_skill_md_documents_blind_second_round():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "blind" in text.lower()
    assert "round=2" in text or "Runde 2" in text
    assert "screening_ledger.py" in text


# ---------------------------------------------------------------------------
# Uebereinstimmungsmass (Cohen's Kappa)
# ---------------------------------------------------------------------------


def test_compute_agreement_returns_kappa_and_n(session_dir):
    import screening_ledger as sl

    # 3 Uebereinstimmungen, 1 Dissens
    for i in range(1, 4):
        pid = f"p{i}"
        sl.record_decision(session_dir, _round1(pid), agent="j#1", wave=1, round=1)
        sl.record_decision(session_dir, _round2_agree(pid), agent="j#2", wave=1, round=2)
    sl.record_decision(session_dir, _round1("p4"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_disagree("p4"), agent="j#2", wave=1, round=2)

    result = sl.compute_agreement(session_dir)
    assert result["n"] == 4
    assert result["kappa"] is not None
    assert -1.0 <= result["kappa"] <= 1.0


def test_compute_agreement_perfect_agreement_returns_one(session_dir):
    import screening_ledger as sl

    for i in range(1, 6):
        pid = f"p{i}"
        sl.record_decision(session_dir, _round1(pid), agent="j#1", wave=1, round=1)
        sl.record_decision(session_dir, _round2_agree(pid), agent="j#2", wave=1, round=2)

    result = sl.compute_agreement(session_dir)
    assert result["kappa"] == 1.0
    assert result["n"] == 5


def test_compute_agreement_without_pairs_is_none(session_dir):
    import screening_ledger as sl

    result = sl.compute_agreement(session_dir)
    assert result["kappa"] is None
    assert result["n"] == 0


def test_compute_agreement_ignores_single_round_papers(session_dir):
    """Nur Faelle mit VOLLSTAENDIGEM Runde-1+Runde-2-Paar zaehlen."""
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_agree("p1"), agent="j#2", wave=1, round=2)
    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)  # Runde 2 offen

    result = sl.compute_agreement(session_dir)
    assert result["n"] == 1


# ---------------------------------------------------------------------------
# Dissens gesammelt vorlegen
# ---------------------------------------------------------------------------


def test_dissent_cases_lists_disagreements(session_dir):
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_agree("p1"), agent="j#2", wave=1, round=2)
    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_disagree("p2"), agent="j#2", wave=1, round=2)

    cases = sl.dissent_cases(session_dir)
    assert [c["paper_id"] for c in cases] == ["p2"]
    assert cases[0]["round_1"]["decision"] == "include"
    assert cases[0]["round_2"]["decision"] == "exclude"


def test_dissent_report_lists_cases_with_reasons(session_dir):
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_disagree("p2"), agent="j#2", wave=1, round=2)

    report = sl.dissent_report(session_dir)
    assert "p2" in report
    assert "Kontrollgruppe" in report


def test_dissent_not_written_to_vault_before_human_decision(session_dir, temp_vault_db):
    import screening_ledger as sl
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    db.add_paper(paper_id="p2", csl_json=json.dumps({"type": "article-journal", "title": "T"}))

    # Beide Runden bewusst OHNE db_path — Vault-Schreibzugriffe passieren erst
    # nach der Konsolidierung, nie direkt bei der Einzelrunde.
    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_disagree("p2"), agent="j#2", wave=1, round=2)

    buckets = sl.merge_double(session_dir)
    assert buckets["dissent"] == ["p2"]
    assert buckets["exclude"] == []
    assert buckets["include"] == []

    sl.commit_double_screening(session_dir, db_path=temp_vault_db)
    assert not db.is_excluded("p2"), (
        "Dissens darf vor menschlicher Entscheidung nicht ausschliessen"
    )


# ---------------------------------------------------------------------------
# Menschliche Entscheidung unterscheidbar
# ---------------------------------------------------------------------------


def test_human_resolution_marked_decided_by_human(session_dir):
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_disagree("p2"), agent="j#2", wave=1, round=2)

    sl.record_human_decision(
        session_dir,
        {"paper_id": "p2", "decision": "exclude", "reason": "Nach Volltextsicht: kein RCT"},
    )

    rows = [r for r in sl.read_ledger(session_dir) if r["paper_id"] == "p2"]
    human_rows = [r for r in rows if r["round"] == "human"]
    agent_rows = [r for r in rows if r["round"] in (1, 2)]

    assert len(human_rows) == 1
    assert human_rows[0]["decided_by"] == "human"
    assert all(r["decided_by"] == "agent" for r in agent_rows)


def test_merge_double_prefers_human_over_dissent(session_dir, temp_vault_db):
    import screening_ledger as sl
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    db.add_paper(paper_id="p2", csl_json=json.dumps({"type": "article-journal", "title": "T"}))

    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_disagree("p2"), agent="j#2", wave=1, round=2)

    assert sl.merge_double(session_dir)["dissent"] == ["p2"]

    sl.record_human_decision(
        session_dir,
        {"paper_id": "p2", "decision": "exclude", "reason": "Nach Volltextsicht: kein RCT"},
    )

    buckets = sl.merge_double(session_dir)
    assert buckets["dissent"] == [], "Aufgeloester Dissens bleibt nicht im Dissens-Bucket"
    assert buckets["exclude"] == ["p2"]

    sl.commit_double_screening(session_dir, db_path=temp_vault_db)
    assert db.is_excluded("p2"), "Menschlich aufgeloester Ausschluss muss den Vault erreichen"


def test_merge_double_consensus_include_reaches_vault(session_dir, temp_vault_db):
    """Stimmen beide Runden ueberein, ist keine menschliche Entscheidung noetig."""
    import screening_ledger as sl
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    db.add_paper(paper_id="p1", csl_json=json.dumps({"type": "article-journal", "title": "T"}))

    sl.record_decision(session_dir, _round1("p1"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_agree("p1"), agent="j#2", wave=1, round=2)

    buckets = sl.commit_double_screening(session_dir, db_path=temp_vault_db)
    assert buckets["include"] == ["p1"]
    assert not db.is_excluded("p1")


# ---------------------------------------------------------------------------
# Schalter: einfaches Screening exakt wie heute
# ---------------------------------------------------------------------------


def test_simple_mode_switch_disables_second_round(monkeypatch, tmp_path):
    import screening_ledger as sl

    monkeypatch.delenv(sl.DOUBLE_SCREENING_ENV, raising=False)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"double_screening": False}), encoding="utf-8")
    assert sl.resolve_double_screening(config_path=cfg) is False

    cfg2 = tmp_path / "cfg2.json"
    cfg2.write_text(json.dumps({"double_screening": True}), encoding="utf-8")
    assert sl.resolve_double_screening(config_path=cfg2) is True


def test_double_screening_precedence(monkeypatch, tmp_path):
    """Argument > Env > Config > Default True."""
    import screening_ledger as sl

    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"double_screening": False}), encoding="utf-8")

    monkeypatch.delenv(sl.DOUBLE_SCREENING_ENV, raising=False)
    assert sl.resolve_double_screening(config_path=cfg) is False, "Config schlaegt Default"

    monkeypatch.setenv(sl.DOUBLE_SCREENING_ENV, "true")
    assert sl.resolve_double_screening(config_path=cfg) is True, "Env schlaegt Config"

    assert sl.resolve_double_screening(explicit=False, config_path=cfg) is False, (
        "Argument schlaegt Env"
    )


def test_double_screening_default_true_when_nothing_configured(monkeypatch, tmp_path):
    import screening_ledger as sl

    monkeypatch.delenv(sl.DOUBLE_SCREENING_ENV, raising=False)
    missing = tmp_path / "nope.json"
    assert sl.resolve_double_screening(config_path=missing) is True


def test_repo_config_declares_double_screening_default():
    import screening_ledger as sl

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(data["double_screening"], bool)
    assert sl.resolve_double_screening() == data["double_screening"]


def test_merge_stays_round_one_only_when_double_screening_active(session_dir):
    """merge() zaehlt bei aktivem Doppel-Screening nicht doppelt (Summenregel)."""
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_agree("p1"), agent="j#2", wave=1, round=2)

    buckets = sl.merge(session_dir)
    assert buckets["include"] == ["p1"], "merge() darf Runde 2 nicht mitzaehlen"


# ---------------------------------------------------------------------------
# Resume: keine halben Doppelurteile als vollstaendig
# ---------------------------------------------------------------------------


def test_pending_round_after_partial_first_wave_still_open(session_dir):
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="j#1", wave=1, round=1)

    assert sl.pending_round(["p1"], session_dir, round=1) == []
    assert sl.pending_round(["p1"], session_dir, round=2) == ["p1"], (
        "Runde 2 ist nach einem Abbruch nach Welle 1 weiterhin offen"
    )


def test_resume_does_not_treat_single_round_as_double_complete(session_dir):
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_agree("p2"), agent="j#2", wave=1, round=2)

    # p1 hat nur Runde 1 -> kein Paar -> kappa/dissent duerfen es nicht mitzaehlen
    agreement = sl.compute_agreement(session_dir)
    assert agreement["n"] == 1

    dissent = sl.dissent_cases(session_dir)
    assert dissent == []

    buckets = sl.merge_double(session_dir)
    assert "p1" not in buckets["include"]
    assert "p1" not in buckets["exclude"]
    assert "p1" not in buckets["unclear"]
    assert "p1" not in buckets["dissent"]
    assert buckets["include"] == ["p2"]


# ---------------------------------------------------------------------------
# PRISMA-Zaehler bei Doppel-Screening
# ---------------------------------------------------------------------------


def test_to_prisma_counters_double_folds_dissent_into_unclear(session_dir):
    import screening_ledger as sl

    sl.record_decision(session_dir, _round1("p1"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_agree("p1"), agent="j#2", wave=1, round=2)
    sl.record_decision(session_dir, _round1("p2"), agent="j#1", wave=1, round=1)
    sl.record_decision(session_dir, _round2_disagree("p2"), agent="j#2", wave=1, round=2)

    counters = sl.to_prisma_counters_double(session_dir)
    assert counters["n_included"] == 1
    assert counters["n_unclear_screening"] == 1
    assert counters["n_after_dedup"] == 2
