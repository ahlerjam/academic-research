"""Tests fuer Issue #726: FTS5 indiziert auch Chunk-Texte.

``papers_fts`` (Basis) und ``papers_trgm`` (#703, Komposita) matchen
ausschliesslich Paper-Felder (Titel, Abstract, Volltext). Ein Suchbegriff, der
nur in einem einzelnen Chunk (``chunk_embeddings.chunk_text``) steht, war
damit lexikalisch unauffindbar -- genau die Stellen, die beim Belegen gesucht
werden.

Neue eigenstaendige virtuelle Tabelle ``chunk_fts`` (FTS5, ``unicode61``-
Default, kein ``content=``), analog zu ``notes_fts`` (nicht zu
``papers_trgm``): dieselbe Tokenizer-Entscheidung wie ``papers_fts``. Drei
Trigger (``chunk_ai``/``chunk_ad``/``chunk_au``) halten den Index bei
INSERT/UPDATE/DELETE auf ``chunk_embeddings`` synchron. Fusion/Retrieval
bleibt Out of Scope -- dieser Test greift ueber einen rohen ``chunk_fts
MATCH ?``-Codepfad zu.
"""

import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_db(tmp_path: Path) -> str:
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "vault.db")
    VaultDB(db_path).init_schema()
    return db_path


def _add_paper(db_path: str, paper_id: str, title: str, abstract: str = "") -> None:
    import json

    from academic_vault.server import add_paper

    csl = {"type": "article-journal", "title": title, "abstract": abstract}
    add_paper(db_path, paper_id, json.dumps(csl))


def _chunk_fts_paper_ids(db_path: str, query: str) -> list[str]:
    """Roher Such-Codepfad fuer AC1 (kein neues MCP-Tool, Fusion out of scope)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DISTINCT paper_id FROM chunk_fts WHERE chunk_fts MATCH ?",
            (query,),
        ).fetchall()
        return [r["paper_id"] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AC1: Chunk-only-Treffer
# ---------------------------------------------------------------------------


class TestAC1ChunkOnlyTreffer:
    def test_ac1_suchbegriff_nur_im_chunk_wird_gefunden(self, tmp_path):
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p_methodik", "Ein neutraler Titel", "Ein neutraler Abstract.")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p_methodik",
            chunk_text="Im Methodikteil auf Seite 14 wird Bootstrapping angewendet.",
            context_sentence="Methodik.",
            embedding_text="Methodik. Im Methodikteil auf Seite 14 wird Bootstrapping angewendet.",
            embedding_vector=None,
        )

        assert "p_methodik" in _chunk_fts_paper_ids(db_path, "Bootstrapping")

    def test_ac1_ohne_neuen_index_findet_search_papers_nichts(self, tmp_path):
        """Beweis: `search_papers()` (Paper-Ebene) findet den Chunk-Begriff nicht."""
        from academic_vault.db import VaultDB
        from academic_vault.server import search_papers

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p_methodik", "Ein neutraler Titel", "Ein neutraler Abstract.")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p_methodik",
            chunk_text="Im Methodikteil auf Seite 14 wird Bootstrapping angewendet.",
            context_sentence="Methodik.",
            embedding_text="Methodik. Im Methodikteil auf Seite 14 wird Bootstrapping angewendet.",
            embedding_vector=None,
        )

        results = [r["paper_id"] for r in search_papers(db_path, "Bootstrapping")]
        assert "p_methodik" not in results


# ---------------------------------------------------------------------------
# AC2: Trigger-Konsistenz bei Insert/Update/Delete
# ---------------------------------------------------------------------------


class TestAC2TriggerKonsistenz:
    def test_ac2_insert_ueber_add_chunk_embedding(self, tmp_path):
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p1", "Titel", "Abstract.")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Ein Satz ueber Feldforschung.",
            context_sentence="Kontext.",
            embedding_text="Kontext. Ein Satz ueber Feldforschung.",
            embedding_vector=None,
        )

        assert "p1" in _chunk_fts_paper_ids(db_path, "Feldforschung")

    def test_ac2_update_ersetzt_den_alten_chunk_text(self, tmp_path):
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p1", "Titel", "Abstract.")
        db = VaultDB(db_path)
        chunk_id = db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Alter Begriff Artefakthaeufigkeit.",
            context_sentence="Kontext.",
            embedding_text="Kontext. Alter Begriff Artefakthaeufigkeit.",
            embedding_vector=None,
        )
        assert "p1" in _chunk_fts_paper_ids(db_path, "Artefakthaeufigkeit")

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE chunk_embeddings SET chunk_text = ? WHERE chunk_id = ?",
                ("Neuer Begriff Rekurrenzquote.", chunk_id),
            )
            conn.commit()
        finally:
            conn.close()

        assert "p1" not in _chunk_fts_paper_ids(db_path, "Artefakthaeufigkeit")
        assert "p1" in _chunk_fts_paper_ids(db_path, "Rekurrenzquote")

    def test_ac2_delete_ueber_delete_chunk_embeddings(self, tmp_path):
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p1", "Titel", "Abstract.")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Ein Satz ueber Diskursanalyse.",
            context_sentence="Kontext.",
            embedding_text="Kontext. Ein Satz ueber Diskursanalyse.",
            embedding_vector=None,
        )
        assert "p1" in _chunk_fts_paper_ids(db_path, "Diskursanalyse")

        db.delete_chunk_embeddings("p1")

        assert "p1" not in _chunk_fts_paper_ids(db_path, "Diskursanalyse")


# ---------------------------------------------------------------------------
# AC3: Bestands-Vault-Migration ohne Datenverlust, ohne Vektor-Reindex
# ---------------------------------------------------------------------------


def _degrade_to_legacy(db_path: str, version: int = 12) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS chunk_fts")
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


def _table_exists(db_path: str, name: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )
    finally:
        conn.close()


def _user_version(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


@pytest.fixture
def legacy_vault(tmp_path):
    """Gefuellter Vault mit Bestands-Chunks, danach auf den Stand vor `chunk_fts` zurueckgesetzt."""
    from academic_vault.db import VaultDB

    db_path = _make_db(tmp_path)
    _add_paper(db_path, "p1", "Titel eins", "Abstract eins.")
    db = VaultDB(db_path)
    db.add_chunk_embedding(
        paper_id="p1",
        chunk_text="Ein Satz ueber Grounded Theory.",
        context_sentence="Kontext.",
        embedding_text="Kontext. Ein Satz ueber Grounded Theory.",
        embedding_vector=None,
    )
    _degrade_to_legacy(db_path)
    return db_path


class TestAC3BestandsVaultMigration:
    def test_ac3_legacy_vault_bekommt_tabelle(self, legacy_vault):
        from academic_vault.db import VaultDB

        assert not _table_exists(legacy_vault, "chunk_fts")
        VaultDB(legacy_vault).init_schema()
        assert _table_exists(legacy_vault, "chunk_fts")

    def test_ac3_keine_chunk_daten_gehen_verloren(self, legacy_vault):
        from academic_vault.db import VaultDB

        conn = sqlite3.connect(legacy_vault)
        try:
            before = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        finally:
            conn.close()

        VaultDB(legacy_vault).init_schema()

        conn = sqlite3.connect(legacy_vault)
        try:
            after = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        finally:
            conn.close()
        assert after == before

    def test_ac3_backfill_erfasst_bestandschunks(self, legacy_vault):
        from academic_vault.db import VaultDB

        VaultDB(legacy_vault).init_schema()
        assert "p1" in _chunk_fts_paper_ids(legacy_vault, "Grounded")

    def test_ac3_kein_reindex_der_vektoren(self, legacy_vault):
        """`embedding_vector`-Spalten bleiben durch die Migration unangetastet."""
        from academic_vault.db import VaultDB

        conn = sqlite3.connect(legacy_vault)
        try:
            before = conn.execute(
                "SELECT chunk_id, embedding_vector FROM chunk_embeddings ORDER BY chunk_id"
            ).fetchall()
        finally:
            conn.close()

        VaultDB(legacy_vault).init_schema()

        conn = sqlite3.connect(legacy_vault)
        try:
            after = conn.execute(
                "SELECT chunk_id, embedding_vector FROM chunk_embeddings ORDER BY chunk_id"
            ).fetchall()
        finally:
            conn.close()
        assert after == before

    def test_ac3_user_version_wird_hochgestempelt(self, legacy_vault):
        from academic_vault.db import CURRENT_SCHEMA_VERSION, VaultDB

        VaultDB(legacy_vault).init_schema()
        assert _user_version(legacy_vault) == CURRENT_SCHEMA_VERSION

    def test_ac3_migration_idempotent(self, legacy_vault):
        from academic_vault.db import VaultDB
        from academic_vault.migrate import add_chunk_fts

        VaultDB(legacy_vault).init_schema()
        conn = sqlite3.connect(legacy_vault)
        try:
            first = conn.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0]
        finally:
            conn.close()

        add_chunk_fts(legacy_vault)
        VaultDB(legacy_vault).init_schema()

        conn = sqlite3.connect(legacy_vault)
        try:
            assert conn.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0] == first
        finally:
            conn.close()

    def test_ac3_lesepfad_repariert_bestands_vault_ueber_ensure_schema_for_read(self, legacy_vault):
        """`_ensure_schema_for_read()` (server.py) migriert `chunk_fts` mit, nicht nur die

        historischen `_READ_REQUIRED_TABLES` -- sonst crasht ein reiner Lesepfad auf
        einem frischen Bestands-Vault mit `no such table: chunk_fts` (Plan-Risiko).
        """
        from academic_vault.server import _ensure_schema_for_read

        assert not _table_exists(legacy_vault, "chunk_fts")
        _ensure_schema_for_read(legacy_vault)
        assert _table_exists(legacy_vault, "chunk_fts")


# ---------------------------------------------------------------------------
# AC4: Tokenizer-Parität mit papers_fts (unicode61, kein Kompositazerlegung)
# ---------------------------------------------------------------------------


class TestAC4TokenizerParitaet:
    def test_ac4_kompositum_wird_nicht_ueber_bestandteil_gefunden(self, tmp_path):
        """unicode61 kennt keine Kompositazerlegung -- bitgleiches Verhalten zu papers_fts."""
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p1", "Titel", "Abstract.")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Ein Satz zur Mittelstandsdigitalisierung im Betrieb.",
            context_sentence="Kontext.",
            embedding_text="Kontext. Ein Satz zur Mittelstandsdigitalisierung im Betrieb.",
            embedding_vector=None,
        )

        assert "p1" not in _chunk_fts_paper_ids(db_path, "Mittelstand")

    def test_ac4_ganzes_wort_wird_weiterhin_gefunden(self, tmp_path):
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        _add_paper(db_path, "p1", "Titel", "Abstract.")
        db = VaultDB(db_path)
        db.add_chunk_embedding(
            paper_id="p1",
            chunk_text="Ein Satz zur Mittelstandsdigitalisierung im Betrieb.",
            context_sentence="Kontext.",
            embedding_text="Kontext. Ein Satz zur Mittelstandsdigitalisierung im Betrieb.",
            embedding_vector=None,
        )

        assert "p1" in _chunk_fts_paper_ids(db_path, "Mittelstandsdigitalisierung")


# ---------------------------------------------------------------------------
# AC5: Plattenbedarf dokumentiert (>= 50 Paper mit Chunks)
# ---------------------------------------------------------------------------


class TestAC5Plattenbedarf:
    def test_ac5_plattenbedarf_an_50_paper_vault_gemessen(self, tmp_path):
        """Misst den Groessenzuwachs durch chunk_fts an einem >=50-Paper-Vault.

        Degradiert eine gefuellte DB auf den Vor-Migrationsstand, misst die
        Dateigroesse, migriert, misst erneut. Das Delta wird nur auf Plausibilitaet
        geprueft (>0, < Grössenordnung des indizierten Texts) -- die dokumentierte
        Zahl selbst steht in docs/reference/vault.md (AC5).
        """
        from academic_vault.db import VaultDB

        db_path = _make_db(tmp_path)
        db = VaultDB(db_path)
        n_papers = 50
        for i in range(n_papers):
            paper_id = f"p{i}"
            _add_paper(db_path, paper_id, f"Titel {i}", f"Abstract Nummer {i}.")
            for c in range(3):
                db.add_chunk_embedding(
                    paper_id=paper_id,
                    chunk_text=(
                        f"Chunk {c} von Paper {i} behandelt Methodikfragen und "
                        "empirische Befunde in ausreichender Laenge fuer eine "
                        "realistische Plattenbedarfsmessung."
                    ),
                    context_sentence=f"Kontext {c}.",
                    embedding_text=f"Kontext {c}. Chunk {c} von Paper {i}.",
                    embedding_vector=None,
                )

        _degrade_to_legacy(db_path)
        import os

        conn = sqlite3.connect(db_path)
        conn.execute("VACUUM")
        conn.close()
        size_before = os.path.getsize(db_path)

        VaultDB(db_path).init_schema()
        conn = sqlite3.connect(db_path)
        conn.execute("VACUUM")
        conn.close()
        size_after = os.path.getsize(db_path)

        delta = size_after - size_before
        assert delta > 0, "chunk_fts sollte messbaren Plattenbedarf hinzufuegen"
        # Delta soll sich in einer plausiblen Groessenordnung zum indizierten
        # Chunk-Text bewegen (Text: 150 Paper*Chunks * ~150 Byte). Ein FTS5-Index
        # liegt typischerweise im niedrigen Vielfachen des Rohtexts.
        conn = sqlite3.connect(db_path)
        try:
            raw_text_bytes = sum(
                len(row[0].encode("utf-8"))
                for row in conn.execute("SELECT chunk_text FROM chunk_embeddings")
            )
        finally:
            conn.close()
        assert delta < raw_text_bytes * 10, (
            f"Plattenbedarf {delta} Byte wirkt unplausibel hoch gegenueber "
            f"{raw_text_bytes} Byte Rohtext"
        )
