"""Tests fuer Issue #539: tote Schema-Tabellen glossary/style_overrides entfernen.

Die beiden Tabellen hatten nie einen Lese- oder Schreibpfad in ``db.py``/
``server.py``. Sie verschwinden aus ``schema.sql`` und aus
``migrate.add_v64_tables()``; Bestands-DBs raeumt der neue idempotente Helfer
``migrate.drop_dead_v64_tables()`` auf — aber nur, wenn die Tabellen leer sind
(Datensicherheit vor Aufraeumen).
"""

import logging
import sqlite3
from pathlib import Path

import pytest
from academic_vault import migrate
from academic_vault.db import CURRENT_SCHEMA_VERSION, VaultDB

_DEAD_DDL = {
    "glossary": """
        CREATE TABLE IF NOT EXISTS glossary (
          term        TEXT PRIMARY KEY,
          definition  TEXT NOT NULL,
          created_at  INTEGER NOT NULL,
          updated_at  INTEGER NOT NULL
        )
    """,
    "style_overrides": """
        CREATE TABLE IF NOT EXISTS style_overrides (
          key        TEXT PRIMARY KEY,
          value      TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
    """,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_names(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()


def _user_version(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def _set_user_version(db_path: str, version: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fresh_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "fresh.db")
    VaultDB(db_path).init_schema()
    return db_path


@pytest.fixture
def legacy_v3_db(tmp_path: Path) -> str:
    """Bestands-DB im Stand vor #539: aktuelles Schema plus die toten Tabellen."""
    db_path = str(tmp_path / "legacy.db")
    db = VaultDB(db_path)
    db.init_schema()

    db.add_paper(paper_id="paper-539", csl_json='{"title": "Legacy Paper"}')
    db.add_decision(category="scope", text="Decision bleibt erhalten")

    conn = sqlite3.connect(db_path)
    try:
        for ddl in _DEAD_DDL.values():
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO excluded_sources (paper_id, reason, excluded_at) VALUES (?, ?, ?)",
            ("paper-excluded", "off-topic", 1700000000),
        )
        conn.commit()
    finally:
        conn.close()

    # Stand vor dem Bump: DB gilt als vollstaendig auf Version 3 migriert.
    _set_user_version(db_path, 3)
    return db_path


# ---------------------------------------------------------------------------
# AC1a — frische DB enthaelt die Tabellen nicht mehr
# ---------------------------------------------------------------------------


def test_fresh_db_has_no_dead_tables(fresh_db: str) -> None:
    names = _table_names(fresh_db)
    assert "glossary" not in names
    assert "style_overrides" not in names
    assert _user_version(fresh_db) == CURRENT_SCHEMA_VERSION


def test_add_v64_tables_no_longer_creates_dead_tables(tmp_path: Path) -> None:
    """Der Legacy-Helfer darf die toten Tabellen nicht wieder anlegen."""
    db_path = str(tmp_path / "v64.db")
    sqlite3.connect(db_path).close()

    migrate.add_v64_tables(db_path)

    names = _table_names(db_path)
    assert "glossary" not in names
    assert "style_overrides" not in names
    # Die lebenden v6.4-Tabellen bleiben unangetastet.
    assert {"excluded_sources", "risk_of_bias_assessments", "score_history"} <= names


# ---------------------------------------------------------------------------
# AC1b — Bestands-DB migriert verlustfrei
# ---------------------------------------------------------------------------


def test_legacy_db_v3_drops_dead_tables_and_keeps_data(legacy_v3_db: str) -> None:
    assert {"glossary", "style_overrides"} <= _table_names(legacy_v3_db), (
        "Testannahme verletzt: Fixture legt die toten Tabellen nicht an"
    )
    assert _user_version(legacy_v3_db) < CURRENT_SCHEMA_VERSION, (
        "CURRENT_SCHEMA_VERSION muss fuer den Drop hochgezaehlt werden, "
        "sonst ueberspringt init_schema() alle Bestands-DBs (#368-Gate)"
    )

    db = VaultDB(legacy_v3_db)
    db.init_schema()

    names = _table_names(legacy_v3_db)
    assert "glossary" not in names
    assert "style_overrides" not in names
    assert _user_version(legacy_v3_db) == CURRENT_SCHEMA_VERSION

    # Nutzdaten unveraendert.
    paper = db.get_paper("paper-539")
    assert paper is not None
    assert "Legacy Paper" in paper["csl_json"]
    decisions = db.list_decisions()
    assert len(decisions) == 1
    assert decisions[0]["text"] == "Decision bleibt erhalten"

    conn = sqlite3.connect(legacy_v3_db)
    try:
        rows = conn.execute("SELECT paper_id, reason FROM excluded_sources").fetchall()
    finally:
        conn.close()
    assert rows == [("paper-excluded", "off-topic")]


# ---------------------------------------------------------------------------
# AC1c — Abbruch statt Datenverlust bei nicht-leerer Tabelle
# ---------------------------------------------------------------------------


def test_non_empty_dead_table_is_not_dropped(
    legacy_v3_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    conn = sqlite3.connect(legacy_v3_db)
    try:
        conn.execute("INSERT INTO glossary VALUES ('Term', 'Definition', 0, 0)")
        conn.commit()
    finally:
        conn.close()

    with caplog.at_level(logging.WARNING, logger="academic_vault.db"):
        VaultDB(legacy_v3_db).init_schema()

    names = _table_names(legacy_v3_db)
    assert "glossary" in names, "Nicht-leere Tabelle darf nicht gedroppt werden"
    assert "style_overrides" not in names, "Die leere Tabelle wird trotzdem gedroppt"
    assert _user_version(legacy_v3_db) < CURRENT_SCHEMA_VERSION
    assert any("glossary" in record.getMessage() for record in caplog.records)

    conn = sqlite3.connect(legacy_v3_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0] == 1
    finally:
        conn.close()


def test_retry_succeeds_after_manual_cleanup(legacy_v3_db: str) -> None:
    conn = sqlite3.connect(legacy_v3_db)
    try:
        conn.execute("INSERT INTO glossary VALUES ('Term', 'Definition', 0, 0)")
        conn.commit()
    finally:
        conn.close()

    db = VaultDB(legacy_v3_db)
    db.init_schema()
    assert "glossary" in _table_names(legacy_v3_db)

    conn = sqlite3.connect(legacy_v3_db)
    try:
        conn.execute("DELETE FROM glossary")
        conn.commit()
    finally:
        conn.close()

    db.init_schema()

    assert "glossary" not in _table_names(legacy_v3_db)
    assert _user_version(legacy_v3_db) == CURRENT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# AC1d — Idempotenz
# ---------------------------------------------------------------------------


def test_drop_dead_v64_tables_is_idempotent(legacy_v3_db: str) -> None:
    assert migrate.drop_dead_v64_tables(legacy_v3_db) == []
    assert migrate.drop_dead_v64_tables(legacy_v3_db) == []
    assert not (migrate.DEAD_TABLES & _table_names(legacy_v3_db))


def test_drop_dead_v64_tables_on_db_without_dead_tables(tmp_path: Path) -> None:
    """Uralt-Legacy ohne die Tabellen: kein Fehler, nichts zu melden."""
    db_path = str(tmp_path / "ancient.db")
    sqlite3.connect(db_path).close()

    assert migrate.drop_dead_v64_tables(db_path) == []


def test_drop_dead_v64_tables_reports_non_empty_tables(legacy_v3_db: str) -> None:
    conn = sqlite3.connect(legacy_v3_db)
    try:
        conn.execute("INSERT INTO style_overrides VALUES ('k', 'v', 0, 0)")
        conn.commit()
    finally:
        conn.close()

    assert migrate.drop_dead_v64_tables(legacy_v3_db) == ["style_overrides"]


def test_apply_pending_migrations_drops_dead_tables(legacy_v3_db: str) -> None:
    migrate.apply_pending_migrations(legacy_v3_db)
    assert not (migrate.DEAD_TABLES & _table_names(legacy_v3_db))


# ---------------------------------------------------------------------------
# AC2 — Treffer nur noch im Migrationscode
# ---------------------------------------------------------------------------


def test_no_dead_table_references_outside_migration_code() -> None:
    """Wer die Namen wieder in schema.sql/db.py/server.py schreibt, faellt hier auf."""
    package_dir = Path(__file__).resolve().parents[1] / "academic_vault"
    # rglob statt glob (Issue #841): seit der Aufteilung von db.py liegen die
    # CRUD-Module in academic_vault/repositories/ — ein Unterpaket entkaeme dem
    # Guard sonst. Ausweitung des Pruefbereichs, keine Abschwaechung.
    sources = sorted(package_dir.rglob("*.py")) + [package_dir / "schema.sql"]

    offenders: list[str] = []
    for source in sources:
        if source.name == "migrate.py":
            continue  # einzige erlaubte Fundstelle: Konstante + Drop-Helfer
        text = source.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "glossary" in line or "style_overrides" in line:
                offenders.append(f"{source.relative_to(package_dir)}:{lineno}: {line.strip()}")

    assert offenders == [], (
        f"Tote Tabellennamen ausserhalb von migrate.py gefunden (#539): {offenders}"
    )


def test_dead_tables_constant_lists_both_tables() -> None:
    assert migrate.DEAD_TABLES == frozenset({"glossary", "style_overrides"})
