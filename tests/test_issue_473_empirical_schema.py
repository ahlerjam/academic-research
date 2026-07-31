"""Tests fuer Issue #473 — Vault-Schema fuer eigenes Erhebungsmaterial.

Eigenes Erhebungsmaterial wird als ``papers``-Zeile gefuehrt (nur so greift die
bestehende Belegkette ueber ``quotes.paper_id``) und von Literatur ueber
``papers.source_kind`` unterschieden. Dazu kommen ``transcript_segments``
(belegfaehige Stellenangabe) und ``codings`` (Kategorienzuordnung).

Geprueft wird ausdruecklich auch der Bestands-DB-Pfad: eine Legacy-``papers``-
Tabelle ohne ``source_kind`` muss beim naechsten ``init_schema()`` migriert
werden, und die Versions-Stempelung darf erst danach greifen (Muster #368/#427).
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from academic_vault.db import (
    _LEGACY_MIGRATION_COLUMNS,
    CURRENT_SCHEMA_VERSION,
    VALID_CATEGORY_ORIGINS,
    VALID_SOURCE_KINDS,
    VaultDB,
)


def _columns(db_path: str, table: str) -> set[str]:
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


def _create_legacy_papers_table(db_path: str) -> None:
    """Legt eine ``papers``-Tabelle ohne ``source_kind`` an (kein init_schema())."""
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
              parent_paper_id    TEXT,
              provenance         TEXT,
              added_at           INTEGER NOT NULL,
              updated_at         INTEGER NOT NULL
            )
        """)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def fresh_vault(tmp_path):
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    return db_path


# ---------------------------------------------------------------------------
# Versions-Gate + Bestands-Migration
# ---------------------------------------------------------------------------


def test_schema_version_covers_source_kind():
    assert CURRENT_SCHEMA_VERSION >= 4, (
        "CURRENT_SCHEMA_VERSION muss fuer papers.source_kind hochgezaehlt werden (#473)"
    )


def test_legacy_migration_columns_lists_source_kind():
    """Ohne diesen Eintrag stempelt init_schema() eine unvollstaendige Migration ab."""
    assert "source_kind" in _LEGACY_MIGRATION_COLUMNS["papers"]


def test_legacy_db_gets_source_kind_column(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    _create_legacy_papers_table(db_path)
    assert "source_kind" not in _columns(db_path, "papers")

    VaultDB(db_path).init_schema()

    assert "source_kind" in _columns(db_path, "papers")
    assert _user_version(db_path) == CURRENT_SCHEMA_VERSION


def test_legacy_db_gets_empirical_tables(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    _create_legacy_papers_table(db_path)

    VaultDB(db_path).init_schema()

    assert _columns(db_path, "transcript_segments")
    assert _columns(db_path, "codings")


def test_db_already_stamped_by_dead_table_drop_still_gets_migrated(tmp_path):
    """Eine DB auf der #539-Generation muss die #473-Migration noch bekommen.

    Beide Aenderungen entstanden parallel und beanspruchten zunaechst dieselbe
    Schema-Version 4. Waere es dabei geblieben, kaeme `init_schema()` bei einer
    von #539 auf 4 gestempelten DB nie ueber sein `current_version >=
    CURRENT_SCHEMA_VERSION`-Gate hinaus: `source_kind` und die Empirie-Tabellen
    fehlten dauerhaft, ohne Fehlermeldung. Der Test haelt den Versionssprung
    fest, nicht nur seinen Zahlenwert.
    """
    db_path = str(tmp_path / "stamped-v4.db")
    _create_legacy_papers_table(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
    finally:
        conn.close()

    assert _user_version(db_path) == 4
    assert "source_kind" not in _columns(db_path, "papers")

    VaultDB(db_path).init_schema()

    assert "source_kind" in _columns(db_path, "papers")
    assert _columns(db_path, "transcript_segments")
    assert _columns(db_path, "codings")
    assert _user_version(db_path) == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION > 4, (
        "Version 4 gehoert #539 (Drop der toten Tabellen) — #473 braucht eine "
        "eigene Generation darueber, sonst laeuft seine Migration nie an."
    )


def test_legacy_paper_defaults_to_literature(tmp_path):
    """Bestands-Paper bleiben Literatur — die neue Spalte darf sie nicht umdeuten."""
    db_path = str(tmp_path / "legacy.db")
    _create_legacy_papers_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO papers (paper_id, type, csl_json, added_at, updated_at) "
        "VALUES ('alt2019', 'article-journal', '{}', 1, 1)"
    )
    conn.commit()
    conn.close()

    VaultDB(db_path).init_schema()

    paper = VaultDB(db_path).get_paper("alt2019")
    assert paper is not None
    assert paper["source_kind"] == "literature"


# ---------------------------------------------------------------------------
# add_paper(source_kind=...)
# ---------------------------------------------------------------------------


def test_add_paper_defaults_to_literature(fresh_vault):
    db = VaultDB(fresh_vault)
    db.add_paper(paper_id="mueller2021", csl_json=json.dumps({"title": "T"}))
    assert db.get_paper("mueller2021")["source_kind"] == "literature"


def test_add_paper_accepts_primary(fresh_vault):
    db = VaultDB(fresh_vault)
    db.add_paper(
        paper_id="interview-01",
        csl_json=json.dumps({"title": "Interview 01"}),
        source_kind="primary",
    )
    assert db.get_paper("interview-01")["source_kind"] == "primary"


def test_add_paper_rejects_unknown_source_kind(fresh_vault):
    db = VaultDB(fresh_vault)
    with pytest.raises(ValueError) as exc:
        db.add_paper(
            paper_id="x",
            csl_json=json.dumps({"title": "T"}),
            source_kind="feldnotiz",
        )
    assert "source_kind" in str(exc.value)
    assert db.get_paper("x") is None


def test_source_kind_survives_partial_upsert(fresh_vault):
    """Ein Folge-Upsert ohne source_kind darf das Primaermaterial nicht umdeuten."""
    db = VaultDB(fresh_vault)
    db.add_paper(
        paper_id="interview-01",
        csl_json=json.dumps({"title": "Interview 01"}),
        source_kind="primary",
    )
    db.add_paper(paper_id="interview-01", csl_json=json.dumps({"title": "Interview 01 (rev)"}))
    assert db.get_paper("interview-01")["source_kind"] == "primary"


def test_valid_value_sets_are_exposed():
    assert VALID_SOURCE_KINDS == frozenset({"literature", "primary"})
    assert VALID_CATEGORY_ORIGINS == frozenset({"induktiv", "deduktiv"})


# ---------------------------------------------------------------------------
# transcript_segments + codings
# ---------------------------------------------------------------------------


def test_transcript_segment_upsert_keeps_seq_unique(fresh_vault):
    db = VaultDB(fresh_vault)
    db.add_paper(
        paper_id="interview-01",
        csl_json=json.dumps({"title": "Interview 01"}),
        source_kind="primary",
    )
    first = db.add_transcript_segment(
        paper_id="interview-01", seq=1, text="Erste Fassung", speaker="B1"
    )
    second = db.add_transcript_segment(
        paper_id="interview-01", seq=1, text="Korrigierte Fassung", speaker="B1"
    )
    assert first == second, "segment_id muss fuer (paper_id, seq) deterministisch sein"

    segments = db.list_transcript_segments("interview-01")
    assert len(segments) == 1
    assert segments[0]["text"] == "Korrigierte Fassung"


def test_coding_references_segment_and_quote(fresh_vault):
    db = VaultDB(fresh_vault)
    db.add_paper(
        paper_id="interview-01",
        csl_json=json.dumps({"title": "Interview 01"}),
        source_kind="primary",
    )
    segment_id = db.add_transcript_segment(paper_id="interview-01", seq=1, text="Aussage")
    db.add_quote(
        quote_id="q1",
        paper_id="interview-01",
        verbatim="Aussage",
        extraction_method="manual",
        section="Abs. 1",
    )
    coding_id = db.add_coding(
        paper_id="interview-01",
        category="Teamabstimmung",
        category_origin="induktiv",
        segment_id=segment_id,
        quote_id="q1",
        memo="Ankerbeispiel",
    )
    rows = db.list_codings(paper_id="interview-01")
    assert len(rows) == 1
    assert rows[0]["coding_id"] == coding_id
    assert rows[0]["segment_id"] == segment_id
    assert rows[0]["quote_id"] == "q1"
    assert rows[0]["memo"] == "Ankerbeispiel"


def test_list_codings_filters_by_category(fresh_vault):
    db = VaultDB(fresh_vault)
    db.add_paper(paper_id="interview-01", csl_json=json.dumps({"title": "I"}))
    db.add_coding(paper_id="interview-01", category="A", category_origin="induktiv")
    db.add_coding(paper_id="interview-01", category="B", category_origin="deduktiv")
    assert [r["category"] for r in db.list_codings(category="B")] == ["B"]


def test_empirical_writes_respect_vault_lock(fresh_vault):
    from academic_vault.db import VaultLockedError

    db = VaultDB(fresh_vault)
    db.add_paper(paper_id="interview-01", csl_json=json.dumps({"title": "I"}))
    db.lock_vault("projekt")

    with pytest.raises(VaultLockedError):
        db.add_transcript_segment(paper_id="interview-01", seq=1, text="Aussage")
    with pytest.raises(VaultLockedError):
        db.add_coding(paper_id="interview-01", category="A", category_origin="induktiv")
