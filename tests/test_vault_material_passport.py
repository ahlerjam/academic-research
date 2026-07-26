"""Tests fuer Material Passport / Repro-Lock (Ticket #104).

TDD-First: Tests definieren das erwuenschte Verhalten.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

_WORKTREE_ROOT = Path(__file__).parent.parent

from academic_vault import server as vault_server
from academic_vault.db import VaultDB, VaultLockedError


def make_temp_db() -> tuple[str, VaultDB]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = VaultDB(tmp.name)
    db.init_schema()
    return tmp.name, db


def _seed_paper(db_path: str, paper_id: str = "p1", doi: str = "10.1234/test") -> None:
    db = VaultDB(db_path)
    db.add_paper(
        paper_id,
        f'{{"title": "Test Paper", "type": "article-journal", "DOI": "{doi}"}}',
        doi=doi,
    )


def _row_count(db_path: str, table: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema-Tests: vault_locked_status
# ---------------------------------------------------------------------------


def test_vault_locked_status_table_exists():
    """Nach init_schema() muss vault_locked_status-Tabelle vorhanden sein."""
    db_path, db = make_temp_db()
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert "vault_locked_status" in names
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# lock_passport / is_locked
# ---------------------------------------------------------------------------


def test_is_locked_returns_false_by_default():
    """is_locked(slug) gibt False zurueck wenn kein Lock gesetzt wurde."""
    db_path, db = make_temp_db()
    try:
        result = vault_server.is_locked(db_path=db_path, slug="my-project")
        assert result is False
    finally:
        os.unlink(db_path)


def test_lock_passport_sets_locked():
    """lock_passport(slug) setzt is_locked(slug) auf True."""
    db_path, db = make_temp_db()
    try:
        vault_server.lock_passport(db_path=db_path, slug="my-project")
        assert vault_server.is_locked(db_path=db_path, slug="my-project") is True
    finally:
        os.unlink(db_path)


def test_lock_passport_idempotent():
    """lock_passport kann mehrfach aufgerufen werden ohne Fehler."""
    db_path, db = make_temp_db()
    try:
        vault_server.lock_passport(db_path=db_path, slug="proj")
        vault_server.lock_passport(db_path=db_path, slug="proj")
        assert vault_server.is_locked(db_path=db_path, slug="proj") is True
    finally:
        os.unlink(db_path)


def test_lock_is_per_slug():
    """Locks sind slug-spezifisch — anderer Slug bleibt unlocked."""
    db_path, db = make_temp_db()
    try:
        vault_server.lock_passport(db_path=db_path, slug="proj-A")
        assert vault_server.is_locked(db_path=db_path, slug="proj-A") is True
        assert vault_server.is_locked(db_path=db_path, slug="proj-B") is False
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Lock-Enforcement bei Schreiboperationen (#380)
#
# Der Lock war bislang nur ein reines Flag -- keine Schreib-Methode pruefte
# ihn. Jede der folgenden Methoden bekommt ein Testpaar: "unlocked -> Schreib-
# operation gelingt wie zuvor" (AC2) und "locked -> Schreiboperation schlaegt
# mit VaultLockedError fehl, kein Teil-Schreibvorgang" (AC1/AC3).
# ---------------------------------------------------------------------------


def test_add_paper_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        vault_server.add_paper(
            db_path,
            "p1",
            '{"title": "T", "type": "article-journal"}',
        )
        assert vault_server.get_paper(db_path, "p1") is not None
    finally:
        os.unlink(db_path)


def test_add_paper_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.add_paper(
                db_path,
                "p1",
                '{"title": "T", "type": "article-journal"}',
            )
        assert vault_server.get_paper(db_path, "p1") is None
    finally:
        os.unlink(db_path)


def test_add_quote_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        quote_id = vault_server.add_quote(db_path, "p1", "Zitat", "manual")
        assert vault_server.get_quote(db_path, quote_id) is not None
    finally:
        os.unlink(db_path)


def test_add_quote_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.add_quote(db_path, "p1", "Zitat", "manual")
        assert _row_count(db_path, "quotes") == 0
    finally:
        os.unlink(db_path)


def test_add_figure_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        figure_id = vault_server.add_figure(db_path, "p1", 1, "Caption", None, None)
        assert vault_server.get_figure(db_path, figure_id) is not None
    finally:
        os.unlink(db_path)


def test_add_figure_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.add_figure(db_path, "p1", 1, "Caption", None, None)
        assert _row_count(db_path, "figures") == 0
    finally:
        os.unlink(db_path)


def test_add_decision_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        decision_id = vault_server.add_decision(db_path, "scope", "Text", "Reason")
        assert decision_id is not None
        assert _row_count(db_path, "decisions") == 1
    finally:
        os.unlink(db_path)


def test_add_decision_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.add_decision(db_path, "scope", "Text", "Reason")
        assert _row_count(db_path, "decisions") == 0
    finally:
        os.unlink(db_path)


def test_supersede_decision_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        id1 = vault_server.add_decision(db_path, "scope", "Old", "R1")
        id2 = vault_server.add_decision(db_path, "scope", "New", "R2")
        vault_server.supersede_decision(db_path=db_path, decision_id=id1, superseded_by=id2)
        active = vault_server.list_decisions(db_path=db_path, active_only=True)
        assert all(d["decision_id"] != id1 for d in active)
    finally:
        os.unlink(db_path)


def test_supersede_decision_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        id1 = vault_server.add_decision(db_path, "scope", "Old", "R1")
        id2 = vault_server.add_decision(db_path, "scope", "New", "R2")
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.supersede_decision(db_path=db_path, decision_id=id1, superseded_by=id2)
        active = vault_server.list_decisions(db_path=db_path, active_only=True)
        assert any(d["decision_id"] == id1 for d in active)
    finally:
        os.unlink(db_path)


def test_add_excluded_source_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        vault_server.add_excluded_source(db_path, "p1", reason="off-topic")
        assert vault_server.is_excluded(db_path, "p1") is True
    finally:
        os.unlink(db_path)


def test_add_excluded_source_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.add_excluded_source(db_path, "p1", reason="off-topic")
        assert vault_server.is_excluded(db_path, "p1") is False
    finally:
        os.unlink(db_path)


def test_add_risk_of_bias_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        assessment_id = vault_server.add_risk_of_bias(
            db_path, "p1", "RCT", {"randomization": "low"}
        )
        assert assessment_id is not None
        assert len(vault_server.list_risk_of_bias(db_path, paper_id="p1")) == 1
    finally:
        os.unlink(db_path)


def test_add_risk_of_bias_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.add_risk_of_bias(db_path, "p1", "RCT", {"randomization": "low"})
        assert vault_server.list_risk_of_bias(db_path, paper_id="p1") == []
    finally:
        os.unlink(db_path)


def test_add_score_snapshot_succeeds_when_unlocked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        snapshot_id = vault_server.add_score_snapshot(db_path, "p1", "session-1", {"total": 5})
        assert snapshot_id is not None
        assert len(vault_server.get_score_history(db_path, "p1")) == 1
    finally:
        os.unlink(db_path)


def test_add_score_snapshot_fails_when_locked():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.lock_passport(db_path=db_path, slug="proj")
        with pytest.raises(VaultLockedError):
            vault_server.add_score_snapshot(db_path, "p1", "session-1", {"total": 5})
        assert vault_server.get_score_history(db_path, "p1") == []
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Fix-Runde PR #407: Guard bricht auf Vaults ohne vault_locked_status-Tabelle
# hart ab (verletzt AC2).
#
# Root cause: server.add_quote() und server.add_figure() rufen -- anders als
# alle anderen guarded Schreib-Wrapper (add_paper, add_decision,
# supersede_decision, add_excluded_source, add_risk_of_bias,
# add_score_snapshot) -- kein db.init_schema() auf, bevor sie die DB-Methode
# aufrufen. Auf einem Vault, der vor v6.4 angelegt und nie migriert wurde
# (vault_locked_status fehlt), liest _raise_if_locked() daher gegen eine
# nicht existierende Tabelle und wirft sqlite3.OperationalError statt die
# Schreiboperation wie vor diesem PR unveraendert durchzulassen.
# ---------------------------------------------------------------------------


def _drop_vault_locked_status_table(db_path: str) -> None:
    """Simuliert einen Vault, der vor v6.4 angelegt und nie migriert wurde."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE vault_locked_status")
        conn.commit()
    finally:
        conn.close()


def test_add_quote_succeeds_on_vault_without_locked_status_table():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        _drop_vault_locked_status_table(db_path)
        quote_id = vault_server.add_quote(db_path, "p1", "Zitat", "manual")
        assert vault_server.get_quote(db_path, quote_id) is not None
    finally:
        os.unlink(db_path)


def test_add_figure_succeeds_on_vault_without_locked_status_table():
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        _drop_vault_locked_status_table(db_path)
        figure_id = vault_server.add_figure(db_path, "p1", 1, "Caption", None, None)
        assert vault_server.get_figure(db_path, figure_id) is not None
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# export_material_passport
# ---------------------------------------------------------------------------


def test_export_material_passport_creates_file(tmp_path):
    """export_material_passport schreibt material-passport.json in output_dir."""
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="test-project",
            output_dir=str(tmp_path),
        )
        passport_file = tmp_path / "material-passport.json"
        assert passport_file.exists(), "material-passport.json wurde nicht erstellt"
    finally:
        os.unlink(db_path)


def test_export_material_passport_valid_json(tmp_path):
    """export_material_passport schreibt gueltiges JSON."""
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="test-project",
            output_dir=str(tmp_path),
        )
        passport_file = tmp_path / "material-passport.json"
        data = json.loads(passport_file.read_text())
        assert isinstance(data, dict)
    finally:
        os.unlink(db_path)


def test_export_material_passport_required_fields(tmp_path):
    """material-passport.json enthaelt alle Pflichtfelder."""
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1", doi="10.9999/abc")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="test-project",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        # Pflichtfelder gemaess Ticket #104
        assert "slug" in data
        assert "paper_ids" in data
        assert "dois" in data
        assert "score_algo_version" in data
        assert "plugin_version" in data
        assert "decisions_snapshot" in data
        assert "passport_hash" in data
        assert "created_at" in data
    finally:
        os.unlink(db_path)


def test_export_material_passport_contains_paper_ids(tmp_path):
    """material-passport.json enthaelt alle paper_ids aus dem Vault."""
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1", doi="10.1/a")
        _seed_paper(db_path, "p2", doi="10.2/b")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="multi-paper",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert "p1" in data["paper_ids"]
        assert "p2" in data["paper_ids"]
    finally:
        os.unlink(db_path)


def test_export_material_passport_decisions_snapshot(tmp_path):
    """material-passport.json enthaelt aktuelle Decisions als Snapshot."""
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.add_decision(db_path, "scope", "Nur RCTs", "Qualitaet")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        assert len(data["decisions_snapshot"]) == 1
        assert data["decisions_snapshot"][0]["text"] == "Nur RCTs"
    finally:
        os.unlink(db_path)


def test_export_material_passport_passport_hash_is_sha256(tmp_path):
    """passport_hash ist ein gueltiger SHA-256 Hex-String (64 Zeichen)."""
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "material-passport.json").read_text())
        h = data["passport_hash"]
        assert len(h) == 64
        int(h, 16)  # wirft ValueError wenn kein gueltiger Hex-String
    finally:
        os.unlink(db_path)


def test_export_material_passport_schema_validates(tmp_path):
    """material-passport.json besteht JSON-Schema-Validierung."""
    db_path, db = make_temp_db()
    try:
        _seed_paper(db_path, "p1")
        vault_server.export_material_passport(
            db_path=db_path,
            slug="proj",
            output_dir=str(tmp_path),
        )
        from academic_vault.material_passport import validate_passport

        data = json.loads((tmp_path / "material-passport.json").read_text())
        # validate_passport wirft bei Fehler
        validate_passport(data)
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Migration-Idempotenz
# ---------------------------------------------------------------------------


def test_v64_migration_idempotent_for_passport():
    """add_v64_tables() ist idempotent bezueglich vault_locked_status."""
    db_path, db = make_temp_db()
    try:
        from academic_vault.migrate import add_v64_tables

        add_v64_tables(db_path)
        add_v64_tables(db_path)
    finally:
        os.unlink(db_path)
