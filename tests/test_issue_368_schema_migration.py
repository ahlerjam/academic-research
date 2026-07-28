"""Regressionstests fuer Issue #368: Bestands-DBs automatisch migrieren.

`VaultDB.init_schema()` nutzte bislang ausschliesslich `CREATE TABLE IF NOT
EXISTS` und konnte bestehende Tabellen nicht um neue Spalten erweitern. Eine
DB mit prae-#195-Schema (`papers` ohne `parent_paper_id`/`provenance`) fuehrte
bei `add_paper()` zu `sqlite3.OperationalError`. Diese Tests decken das
Versions-Gate (`PRAGMA user_version` + `migrate.apply_pending_migrations`) ab.
"""

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

from academic_vault.db import CURRENT_SCHEMA_VERSION, VaultDB

# Erwartete Spalten von `papers` nach vollstaendiger Migration (schema.sql).
_EXPECTED_PAPERS_COLUMNS = {
    "paper_id",
    "type",
    "csl_json",
    "doi",
    "isbn",
    "pdf_path",
    "file_id",
    "file_id_expires_at",
    "page_offset",
    "ocr_done",
    "editor",
    "chapter",
    "page_first",
    "page_last",
    "container_title",
    "parent_paper_id",
    "provenance",
    "added_at",
    "updated_at",
}


def _create_pre_195_papers_table(db_path: str) -> None:
    """Legt eine `papers`-Tabelle im prae-#195-Schema an (kein init_schema()).

    Enthaelt bewusst alle Spalten AUSSER `parent_paper_id`/`provenance`
    (Issue #368: genau diese beiden Spalten fehlen im prae-#195-Schema).
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE papers (
              paper_id           TEXT PRIMARY KEY,
              type               TEXT NOT NULL DEFAULT 'article-journal'
                                    CHECK(type IN ('article-journal','book','chapter')),
              csl_json           TEXT NOT NULL,
              doi                TEXT,
              isbn               TEXT,
              pdf_path           TEXT,
              file_id            TEXT,
              file_id_expires_at INTEGER,
              page_offset        INTEGER DEFAULT 0,
              ocr_done           INTEGER DEFAULT 0,
              editor             TEXT,
              chapter            TEXT,
              page_first         INTEGER,
              page_last          INTEGER,
              container_title    TEXT,
              added_at           INTEGER NOT NULL,
              updated_at         INTEGER NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _table_info_columns(db_path: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        conn.close()


def _user_version(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


class TestLegacySchemaMigration:
    """AC1 + AC2: prae-#195-DB wird beim init_schema()/add_paper() migriert."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        _create_pre_195_papers_table(self.db_path)

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_add_paper_on_legacy_schema_no_operational_error(self):
        """AC1: add_paper() auf einer prae-#195-DB wirft keinen OperationalError."""
        db = VaultDB(self.db_path)
        db.init_schema()

        # Eltern-Paper zuerst (parent_paper_id ist FOREIGN KEY auf papers.paper_id).
        db.add_paper(
            paper_id="legacy-parent",
            csl_json=json.dumps({"type": "book", "title": "Elternbuch"}),
        )

        # Darf NICHT mit sqlite3.OperationalError ("no column named ...") crashen.
        db.add_paper(
            paper_id="legacy-child",
            csl_json=json.dumps({"type": "chapter", "title": "Kapitel"}),
            parent_paper_id="legacy-parent",
            provenance="oa",
        )

        paper = db.get_paper("legacy-child")
        assert paper is not None
        assert paper["parent_paper_id"] == "legacy-parent"
        assert paper["provenance"] == "oa"

    def test_table_info_reports_all_expected_columns_after_migration(self):
        """AC2: PRAGMA table_info(papers) zeigt nach Migration alle erwarteten Spalten."""
        db = VaultDB(self.db_path)
        db.init_schema()

        cols = _table_info_columns(self.db_path, "papers")
        assert _EXPECTED_PAPERS_COLUMNS <= cols


class TestMigrationIdempotency:
    """AC3: eine bereits aktuelle DB durchlaeuft den Check ohne unnoetige Schreiboperationen."""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_second_init_schema_call_skips_migration_helpers(self):
        """Zweiter init_schema()-Aufruf auf bereits aktueller DB ruft keine Helfer auf."""
        db = VaultDB(self.db_path)
        db.init_schema()  # erster Aufruf: frische DB, bringt Schema auf CURRENT_SCHEMA_VERSION

        version_after_first_call = _user_version(self.db_path)
        assert version_after_first_call == CURRENT_SCHEMA_VERSION

        with (
            patch("academic_vault.migrate.add_parent_paper_id_column") as mock_parent,
            patch("academic_vault.migrate.add_provenance_column") as mock_provenance,
            patch("academic_vault.migrate.add_book_columns") as mock_book,
            patch("academic_vault.migrate.add_figures_table") as mock_figures,
            patch("academic_vault.migrate.add_v64_tables") as mock_v64,
        ):
            db.init_schema()  # zweiter Aufruf: DB ist bereits aktuell

            mock_parent.assert_not_called()
            mock_provenance.assert_not_called()
            mock_book.assert_not_called()
            mock_figures.assert_not_called()
            mock_v64.assert_not_called()

        assert _user_version(self.db_path) == version_after_first_call

    def test_legacy_db_migration_runs_helpers_then_skips_on_repeat(self):
        """Legacy-DB: erster Aufruf migriert wirklich, zweiter Aufruf ruft Helfer nicht erneut auf."""
        _create_pre_195_papers_table(self.db_path)
        db = VaultDB(self.db_path)

        db.init_schema()  # erster Aufruf: Legacy-Schema, muss Helfer aufrufen
        assert _user_version(self.db_path) == CURRENT_SCHEMA_VERSION
        assert "parent_paper_id" in _table_info_columns(self.db_path, "papers")
        assert "provenance" in _table_info_columns(self.db_path, "papers")

        with patch("academic_vault.migrate.add_parent_paper_id_column") as mock_parent:
            db.init_schema()  # zweiter Aufruf: bereits aktuell, kein erneuter Helfer-Aufruf
            mock_parent.assert_not_called()


class TestMigrationVerificationBeforeStamping:
    """Regression: `user_version` darf nur bei tatsaechlich verifizierter Migration
    gestempelt werden (Review-Fund zu PR #427, `db.py:336`).

    `migrate.apply_pending_migrations()` gibt `None` zurueck und jeder Helfer
    kapselt sein `ALTER TABLE` in `except sqlite3.OperationalError: pass`
    (migrate.py) -- das faengt nicht nur "duplicate column name", sondern z. B.
    auch "database is locked". Stempelt `init_schema()` `user_version`
    trotzdem unbedingt, gilt eine Legacy-DB ab dann faelschlich als vollstaendig
    migriert und der naechste `init_schema()`-Aufruf ueberspringt jeden
    weiteren Migrationsversuch (`current_version >= CURRENT_SCHEMA_VERSION`) --
    obwohl `parent_paper_id`/`provenance` weiterhin fehlen.
    """

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        _create_pre_195_papers_table(self.db_path)

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_user_version_not_stamped_when_migration_helper_silently_fails(self):
        """Simuliert einen Helfer, dessen ALTER TABLE nie ankommt (z. B. verschluckter
        Lock-Fehler): `parent_paper_id` bleibt nach `init_schema()` weiterhin unter
        `papers`, also darf `user_version` NICHT auf `CURRENT_SCHEMA_VERSION` stehen --
        sonst schliesst sich das Gate unwiderruflich (AC1 dauerhaft verletzt)."""
        with patch("academic_vault.migrate.add_parent_paper_id_column") as mock_parent:
            mock_parent.return_value = None  # No-op statt echtem ALTER TABLE
            db = VaultDB(self.db_path)
            db.init_schema()

        cols = _table_info_columns(self.db_path, "papers")
        assert "parent_paper_id" not in cols, "Testannahme verletzt: Mock hat nicht gegriffen"

        assert _user_version(self.db_path) < CURRENT_SCHEMA_VERSION, (
            "user_version wurde trotz unvollstaendiger Migration gestempelt -- "
            "das Gate schliesst sich unwiderruflich, AC1 ist dauerhaft verletzt"
        )

    def test_failed_migration_is_retried_on_next_init_schema_call(self):
        """Nachdem ein Helfer beim ersten Aufruf (simuliert) fehlschlaegt, muss ein
        zweiter, ungestoerter `init_schema()`-Aufruf die Migration nachholen --
        genau das verhindert das unwiderrufliche Gate aus Issue #368."""
        with patch("academic_vault.migrate.add_parent_paper_id_column") as mock_parent:
            mock_parent.return_value = None
            db = VaultDB(self.db_path)
            db.init_schema()
        assert "parent_paper_id" not in _table_info_columns(self.db_path, "papers")

        # Zweiter, ungestoerter Aufruf (kein Mock mehr): muss die Migration
        # tatsaechlich nachholen statt sie wegen gestempeltem user_version zu
        # ueberspringen.
        db = VaultDB(self.db_path)
        db.init_schema()

        assert "parent_paper_id" in _table_info_columns(self.db_path, "papers")
        assert _user_version(self.db_path) == CURRENT_SCHEMA_VERSION
