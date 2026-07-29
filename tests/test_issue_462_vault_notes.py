"""Tests fuer Issue #462 -- Notiz-Ablage im Vault nutzbar machen.

TDD-First: Tests definieren das erwuenschte Verhalten (Schema, CRUD,
FTS5-Suche, Migrations-Idempotenz) bevor die Implementierung in
db.py/migrate.py/server.py ergaenzt wird. Muster: tests/test_vault_decisions.py.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

from academic_vault import server as vault_server
from academic_vault.db import VaultDB

REPO_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_temp_db() -> tuple[str, VaultDB]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = VaultDB(tmp.name)
    db.init_schema()
    return tmp.name, db


def _add_paper(db_path: str, paper_id: str = "p1") -> None:
    import json

    vault_server.add_paper(
        db_path,
        paper_id,
        json.dumps({"type": "article-journal", "title": "Test Paper"}),
    )


# ---------------------------------------------------------------------------
# Schema-Tests
# ---------------------------------------------------------------------------


def test_notes_table_has_page_column():
    """Nach init_schema() muss notes.page existieren (AC2)."""
    db_path, db = make_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
        conn.close()
        assert "page" in cols
    finally:
        os.unlink(db_path)


def test_notes_fts_table_exists():
    """Nach init_schema() muss notes_fts (FTS5-Index) existieren (AC4)."""
    db_path, db = make_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert "notes_fts" in names
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# add_note / find_notes (AC1)
# ---------------------------------------------------------------------------


def test_add_note_persists_and_find_notes_returns_it():
    db_path, db = make_temp_db()
    try:
        _add_paper(db_path, "p1")
        note_id = vault_server.add_note(
            db_path, paper_id="p1", text="Kernbefund: X korreliert mit Y."
        )
        assert note_id
        notes = vault_server.find_notes(db_path, paper_id="p1")
        assert len(notes) == 1
        assert notes[0]["note_id"] == note_id
        assert notes[0]["text"] == "Kernbefund: X korreliert mit Y."
    finally:
        os.unlink(db_path)


def test_find_notes_filters_by_query_substring():
    db_path, db = make_temp_db()
    try:
        _add_paper(db_path, "p1")
        vault_server.add_note(db_path, paper_id="p1", text="Methode: qualitative Inhaltsanalyse.")
        vault_server.add_note(db_path, paper_id="p1", text="Verwendbarkeit: stuetzt Hypothese 2.")

        matches = vault_server.find_notes(db_path, paper_id="p1", query="Methode")
        assert len(matches) == 1
        assert "Methode" in matches[0]["text"]
    finally:
        os.unlink(db_path)


def test_get_note_returns_full_record():
    db_path, db = make_temp_db()
    try:
        _add_paper(db_path, "p1")
        note_id = vault_server.add_note(db_path, paper_id="p1", text="Exzerpt Text")
        record = vault_server.get_note(db_path, note_id)
        assert record is not None
        assert record["note_id"] == note_id
        assert record["paper_id"] == "p1"
    finally:
        os.unlink(db_path)


def test_get_note_returns_none_for_unknown_id():
    db_path, db = make_temp_db()
    try:
        assert vault_server.get_note(db_path, "does-not-exist") is None
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Seitenangabe (AC2)
# ---------------------------------------------------------------------------


def test_add_note_persists_page_field():
    db_path, db = make_temp_db()
    try:
        _add_paper(db_path, "p1")
        note_id = vault_server.add_note(db_path, paper_id="p1", text="Zitat auf Seite 12.", page=12)
        record = vault_server.get_note(db_path, note_id)
        assert record["page"] == 12
    finally:
        os.unlink(db_path)


def test_add_note_page_optional():
    db_path, db = make_temp_db()
    try:
        _add_paper(db_path, "p1")
        note_id = vault_server.add_note(db_path, paper_id="p1", text="Ohne Seitenbezug.")
        record = vault_server.get_note(db_path, note_id)
        assert record["page"] is None
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# search_notes / FTS5 (AC3 + AC4)
# ---------------------------------------------------------------------------


def test_search_notes_finds_note_by_topic():
    db_path, db = make_temp_db()
    try:
        _add_paper(db_path, "p1")
        _add_paper(db_path, "p2")
        vault_server.add_note(
            db_path, paper_id="p1", text="Diskutiert Reliabilitaet von Selbstauskuenften."
        )
        vault_server.add_note(db_path, paper_id="p2", text="Beschreibt Stichprobenziehung.")

        results = vault_server.search_notes(db_path, "Reliabilitaet")
        assert len(results) == 1
        assert results[0]["paper_id"] == "p1"
    finally:
        os.unlink(db_path)


def test_search_notes_fts_match_finds_word_mid_text():
    """FTS5-Wortsuche (nicht Teilstring-Praefix): Treffer mitten im text-Feld."""
    db_path, db = make_temp_db()
    try:
        _add_paper(db_path, "p1")
        vault_server.add_note(
            db_path,
            paper_id="p1",
            text="Die Studie verwendet ein quasi-experimentelles Design mit Kontrollgruppe.",
        )

        results = vault_server.search_notes(db_path, "Kontrollgruppe")
        assert len(results) == 1
        assert results[0]["note_id"]
    finally:
        os.unlink(db_path)


def test_search_notes_empty_query_returns_empty_list():
    """Leere/reine Sonderzeichen-Query darf nicht crashen (Muster Issue #369)."""
    db_path, db = make_temp_db()
    try:
        assert vault_server.search_notes(db_path, "") == []
        assert vault_server.search_notes(db_path, "---") == []
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Migrations-Idempotenz (Legacy-DB ohne page/notes_fts)
# ---------------------------------------------------------------------------


def _make_legacy_db_without_notes_extensions() -> str:
    """Baut eine minimal-legacy DB: notes-Tabelle ohne page-Spalte, kein notes_fts."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute(
        """
        CREATE TABLE papers (
          paper_id TEXT PRIMARY KEY,
          type TEXT NOT NULL DEFAULT 'article-journal',
          csl_json TEXT NOT NULL,
          added_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE notes (
          note_id    TEXT PRIMARY KEY,
          paper_id   TEXT REFERENCES papers(paper_id),
          text       TEXT NOT NULL,
          tags       TEXT,
          created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO papers (paper_id, csl_json, added_at, updated_at) VALUES "
        "('legacy1', '{\"type\":\"article-journal\"}', 0, 0)"
    )
    conn.execute(
        "INSERT INTO notes (note_id, paper_id, text, created_at) VALUES "
        "('legacy-note-1', 'legacy1', 'Alte Notiz vor der Migration.', 0)"
    )
    conn.commit()
    conn.close()
    return tmp.name


def test_legacy_db_gets_page_column_and_notes_fts_backfilled():
    db_path = _make_legacy_db_without_notes_extensions()
    try:
        db = VaultDB(db_path)
        db.init_schema()  # triggert apply_pending_migrations() ueber das Versions-Gate

        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
        assert "page" in cols

        rows = conn.execute(
            "SELECT note_id FROM notes_fts WHERE notes_fts MATCH 'Notiz'"
        ).fetchall()
        conn.close()
        assert any(r[0] == "legacy-note-1" for r in rows)
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# AC3: Exzerpte beim Kapitelschreiben auffindbar (Doku-/Workflow-Anbindung)
# ---------------------------------------------------------------------------


def test_chapter_writer_skill_references_search_notes():
    """chapter-writer/SKILL.md muss den Notiz-Query-Schritt enthalten (AC3).

    Rein funktional ueber search_notes() bereits durch
    test_search_notes_finds_note_by_topic abgedeckt; die Anbindung an den
    Kapitel-Schreibprozess selbst ist nur ueber die Skill-Doku pruefbar.
    """
    skill_md = (REPO_ROOT / "skills" / "chapter-writer" / "SKILL.md").read_text(encoding="utf-8")
    assert "vault.search_notes(" in skill_md, (
        "chapter-writer/SKILL.md referenziert vault.search_notes() nicht (Issue #462 AC3)."
    )


def test_reading_notes_skill_exists_with_structure_fields():
    """reading-notes/SKILL.md existiert und gibt die Struktur vor (AC5).

    AC5 ("Exzerpt auf Zuruf, ohne dass der Nutzer die Struktur vorgibt") ist
    kein klassisch pytest-testbares LLM-Verhalten -- Nachweis ist, dass die
    Struktur-Vorgabe (Kernbefund/Methode/Verwendbarkeit) im Skill-Text selbst
    steht, nicht dass das Modell sie zur Laufzeit tatsaechlich befolgt.
    """
    skill_path = REPO_ROOT / "skills" / "reading-notes" / "SKILL.md"
    assert skill_path.exists(), "skills/reading-notes/SKILL.md fehlt (Issue #462 AC5)."
    text = skill_path.read_text(encoding="utf-8")
    for field in ("Kernbefund", "Methode", "Verwendbarkeit"):
        assert field in text, f"reading-notes/SKILL.md nennt '{field}' nicht als Struktur-Vorgabe."
    assert "vault.add_note(" in text, "reading-notes/SKILL.md ruft vault.add_note() nicht auf."


def test_add_notes_fts_migration_helper_idempotent():
    """add_notes_fts() kann mehrfach aufgerufen werden ohne Fehler/Duplikate."""
    db_path, db = make_temp_db()
    try:
        from academic_vault.migrate import add_notes_fts

        _add_paper(db_path, "p1")
        vault_server.add_note(db_path, paper_id="p1", text="Einmalige Notiz.")

        add_notes_fts(db_path)
        add_notes_fts(db_path)

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM notes_fts").fetchone()[0]
        conn.close()
        assert count == 1
    finally:
        os.unlink(db_path)
