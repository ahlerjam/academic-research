"""Regressionstests fuer Issue #400: optionales `stance`-Feld an `quotes`.

Das Feld haelt die Haltung eines Zitats zur zitierenden Aussage fest
(`supports`/`contrasts`/`mentions`) und ist der Datenmodell-Anschluss fuer eine
spaetere, rein lokale NLI-Klassifikation (Konzept-Anleihe: scite Smart
Citations / SemanticCite). In diesem Issue bleibt das Feld durchgehend `None`,
sofern es nicht manuell gesetzt wird — die Klassifikation selbst ist ein
Folge-Issue.

Abgedeckte Akzeptanzkriterien:
- AC1: `vault_add_quote` akzeptiert optionales `stance` (drei Werte oder `None`).
- AC2: Ungueltiger Wert -> verstaendlicher `ValueError`, kein roher
  `sqlite3.IntegrityError`.
- AC3: Bestehende Aufrufe ohne `stance` funktionieren unveraendert.
- AC4: Migrationshelfer ruestet eine Bestands-DB ohne `stance`-Spalte nach.
"""

import asyncio
import importlib
import json
import sqlite3

import pytest
from academic_vault import migrate
from academic_vault.db import CURRENT_SCHEMA_VERSION, VALID_STANCES, VaultDB

from tests.helpers import docs as _docs

_PAPER_ID = "stance-paper"
_CSL = json.dumps({"type": "article-journal", "title": "Stance-Testpaper"})


def _table_columns(db_path: str, table: str) -> set[str]:
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


@pytest.fixture
def vault_with_paper(temp_vault_db):
    """Initialisierte Vault-DB mit einem Paper (FK-Ziel fuer quotes)."""
    db = VaultDB(temp_vault_db)
    db.init_schema()
    db.add_paper(paper_id=_PAPER_ID, csl_json=_CSL)
    return temp_vault_db


# ---------------------------------------------------------------------------
# Schema-Ebene
# ---------------------------------------------------------------------------


class TestStanceSchema:
    def test_schema_sql_declares_all_valid_stances(self):
        """Drift-Anker: schema.sql und `VALID_STANCES` nennen dieselben Werte."""
        ddl = (_docs.REPO_ROOT / "academic_vault" / "schema.sql").read_text(encoding="utf-8")
        assert "stance" in ddl, "schema.sql muss die stance-Spalte deklarieren"
        for value in VALID_STANCES:
            assert f"'{value}'" in ddl, (
                f"schema.sql nennt den erlaubten stance-Wert '{value}' nicht — "
                "CHECK-Constraint und VALID_STANCES sind auseinandergelaufen"
            )

    def test_valid_stances_are_exactly_the_three_documented_values(self):
        assert VALID_STANCES == frozenset({"supports", "contrasts", "mentions"})

    def test_quotes_table_has_stance_column_after_init_schema(self, temp_vault_db):
        VaultDB(temp_vault_db).init_schema()
        assert "stance" in _table_columns(temp_vault_db, "quotes")


# ---------------------------------------------------------------------------
# AC1 + AC3: VaultDB.add_quote akzeptiert stance, Default bleibt NULL
# ---------------------------------------------------------------------------


class TestAddQuoteStance:
    @pytest.mark.parametrize("stance", sorted({"supports", "contrasts", "mentions"}))
    def test_add_quote_accepts_valid_stance(self, vault_with_paper, stance):
        """AC1: jeder der drei erlaubten Werte wird persistiert."""
        db = VaultDB(vault_with_paper)
        db.add_quote(
            quote_id=f"q-{stance}",
            paper_id=_PAPER_ID,
            verbatim="Ein woertliches Zitat.",
            extraction_method="manual",
            stance=stance,
        )
        quote = db.get_quote(f"q-{stance}")
        assert quote is not None
        assert quote["stance"] == stance

    def test_add_quote_accepts_explicit_none_stance(self, vault_with_paper):
        """AC1: `None` ist ein zulaessiger Wert und landet als NULL in der DB."""
        db = VaultDB(vault_with_paper)
        db.add_quote(
            quote_id="q-none",
            paper_id=_PAPER_ID,
            verbatim="Ein woertliches Zitat.",
            extraction_method="manual",
            stance=None,
        )
        quote = db.get_quote("q-none")
        assert quote is not None
        assert quote["stance"] is None

    def test_add_quote_without_stance_defaults_to_null(self, vault_with_paper):
        """AC3: exakt die alte Signatur (ohne stance) bleibt gueltig."""
        db = VaultDB(vault_with_paper)
        db.add_quote(
            quote_id="q-legacy-call",
            paper_id=_PAPER_ID,
            verbatim="Zitat aus einem Alt-Aufruf.",
            extraction_method="manual",
            api_response_id=None,
            pdf_page=12,
            printed_page=10,
            section="Einleitung",
            context_before="davor",
            context_after="danach",
        )
        quote = db.get_quote("q-legacy-call")
        assert quote is not None
        assert quote["stance"] is None
        assert quote["pdf_page"] == 12
        assert quote["section"] == "Einleitung"

    def test_invalid_stance_raises_valueerror_not_integrityerror(self, vault_with_paper):
        """AC2: `ValueError` mit lesbarer Meldung statt rohem sqlite3-Fehler."""
        db = VaultDB(vault_with_paper)
        with pytest.raises(ValueError, match="stance") as excinfo:
            db.add_quote(
                quote_id="q-invalid",
                paper_id=_PAPER_ID,
                verbatim="Ein woertliches Zitat.",
                extraction_method="manual",
                stance="foo",
            )
        message = str(excinfo.value)
        assert "foo" in message
        for value in VALID_STANCES:
            assert value in message, f"Fehlermeldung nennt den erlaubten Wert '{value}' nicht"

    def test_invalid_stance_inserts_nothing(self, vault_with_paper):
        """AC2: Die Validierung greift vor dem INSERT — keine Teil-Zeile."""
        db = VaultDB(vault_with_paper)
        with pytest.raises(ValueError):
            db.add_quote(
                quote_id="q-invalid",
                paper_id=_PAPER_ID,
                verbatim="Ein woertliches Zitat.",
                extraction_method="manual",
                stance="foo",
            )
        assert db.find_quotes(_PAPER_ID) == []

    def test_find_quotes_exposes_stance(self, vault_with_paper):
        db = VaultDB(vault_with_paper)
        db.add_quote(
            quote_id="q-find",
            paper_id=_PAPER_ID,
            verbatim="Ein woertliches Zitat.",
            extraction_method="manual",
            stance="contrasts",
        )
        rows = db.find_quotes(_PAPER_ID)
        assert [r["stance"] for r in rows] == ["contrasts"]


# ---------------------------------------------------------------------------
# AC1 + AC2 auf MCP-Ebene (server.py)
# ---------------------------------------------------------------------------


class TestServerLayerStance:
    def test_server_add_quote_passes_stance_through(self, vault_with_paper):
        from academic_vault.server import add_quote, get_quote

        quote_id = add_quote(
            db_path=vault_with_paper,
            paper_id=_PAPER_ID,
            verbatim="Ein woertliches Zitat.",
            extraction_method="manual",
            stance="supports",
        )
        quote = get_quote(vault_with_paper, quote_id)
        assert quote is not None
        assert quote["stance"] == "supports"

    def test_server_add_quote_without_stance_defaults_to_null(self, vault_with_paper):
        """AC3: Rueckwaertskompatibilitaet des MCP-Layers."""
        from academic_vault.server import add_quote, get_quote

        quote_id = add_quote(vault_with_paper, _PAPER_ID, "Zitat", "manual")
        quote = get_quote(vault_with_paper, quote_id)
        assert quote is not None
        assert quote["stance"] is None

    def test_server_add_quote_invalid_stance_raises_valueerror(self, vault_with_paper):
        """AC2: auch ueber den MCP-Einstieg kommt ein `ValueError` heraus."""
        from academic_vault.server import add_quote, find_quotes

        with pytest.raises(ValueError, match="stance"):
            add_quote(
                db_path=vault_with_paper,
                paper_id=_PAPER_ID,
                verbatim="Ein woertliches Zitat.",
                extraction_method="manual",
                stance="foo",
            )
        assert find_quotes(vault_with_paper, _PAPER_ID) == []

    def test_mcp_tool_schema_exposes_stance_parameter(self):
        """`vault.add_quote` bietet `stance` auch ueber `tools/list` an."""
        pytest.importorskip("mcp.server.fastmcp")
        server = importlib.import_module("academic_vault.server")
        mcp_server = server._build_mcp_server()
        assert mcp_server is not None
        tools = asyncio.run(mcp_server.list_tools())
        tool = next(t for t in tools if t.name == "vault.add_quote")
        assert "stance" in tool.inputSchema["properties"], (
            f"vault.add_quote exponiert stance nicht: {sorted(tool.inputSchema['properties'])}"
        )
        assert "stance" not in tool.inputSchema.get("required", []), (
            "stance muss optional bleiben (Rueckwaertskompatibilitaet, AC3)"
        )

    def test_documented_signature_lists_stance(self):
        """Doku-Drift: die Vault-Referenz zeigt die neue Signatur."""
        doc = _docs.VAULT_DOC.read_text(encoding="utf-8")
        assert "stance=None" in doc, (
            "docs/reference/vault.md nennt den neuen Parameter stance nicht"
        )


# ---------------------------------------------------------------------------
# AC4: Migration einer Bestands-DB
# ---------------------------------------------------------------------------


def _create_legacy_quotes_db(db_path: str) -> None:
    """Legt papers + quotes im Schema VOR #400 an (quotes ohne `stance`).

    `papers` bekommt bewusst den vollstaendigen Stand nach #195/#368, damit die
    Tests hier ausschliesslich die neue `quotes`-Migration pruefen. `user_version`
    steht auf 1 — dem Stand vor dieser Schema-Erweiterung.
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
              parent_paper_id    TEXT REFERENCES papers(paper_id),
              provenance         TEXT DEFAULT NULL,
              added_at           INTEGER NOT NULL,
              updated_at         INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE quotes (
              quote_id          TEXT PRIMARY KEY,
              paper_id          TEXT NOT NULL REFERENCES papers(paper_id),
              verbatim          TEXT NOT NULL,
              pdf_page          INTEGER,
              printed_page      INTEGER,
              section           TEXT,
              context_before    TEXT,
              context_after     TEXT,
              extraction_method TEXT NOT NULL
                                  CHECK(extraction_method IN ('citations-api','manual')),
              api_response_id   TEXT,
              created_at        INTEGER NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO papers (paper_id, csl_json, added_at, updated_at) VALUES (?, ?, 0, 0)",
            (_PAPER_ID, _CSL),
        )
        conn.execute(
            "INSERT INTO quotes (quote_id, paper_id, verbatim, extraction_method, created_at) "
            "VALUES ('legacy-quote', ?, 'Altes Zitat', 'manual', 0)",
            (_PAPER_ID,),
        )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    finally:
        conn.close()


class TestStanceMigration:
    @pytest.fixture
    def legacy_db(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        _create_legacy_quotes_db(db_path)
        assert "stance" not in _table_columns(db_path, "quotes"), "Fixture-Annahme verletzt"
        return db_path

    def test_add_stance_column_adds_missing_column(self, legacy_db):
        """AC4: der Helfer ruestet die Spalte auf einer Bestands-DB nach."""
        migrate.add_stance_column(legacy_db)
        assert "stance" in _table_columns(legacy_db, "quotes")

    def test_legacy_row_keeps_null_stance_after_migration(self, legacy_db):
        migrate.add_stance_column(legacy_db)
        conn = sqlite3.connect(legacy_db)
        try:
            value = conn.execute(
                "SELECT stance FROM quotes WHERE quote_id = 'legacy-quote'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert value is None

    def test_add_stance_column_is_idempotent(self, legacy_db):
        migrate.add_stance_column(legacy_db)
        migrate.add_stance_column(legacy_db)  # darf nicht werfen
        assert "stance" in _table_columns(legacy_db, "quotes")

    def test_migrated_column_carries_check_constraint(self, legacy_db):
        """Zweite Verteidigungslinie: Direkt-INSERTs mit Muellwert scheitern."""
        migrate.add_stance_column(legacy_db)
        conn = sqlite3.connect(legacy_db)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO quotes (quote_id, paper_id, verbatim, extraction_method, "
                    "created_at, stance) VALUES ('direct', ?, 'x', 'manual', 0, 'foo')",
                    (_PAPER_ID,),
                )
        finally:
            conn.close()

    def test_apply_pending_migrations_includes_stance(self, legacy_db):
        migrate.apply_pending_migrations(legacy_db)
        assert "stance" in _table_columns(legacy_db, "quotes")

    def test_init_schema_migrates_legacy_db_and_stamps_version(self, legacy_db):
        """Das Versions-Gate (#368) zieht die neue Spalte auf Bestands-DBs nach."""
        assert _user_version(legacy_db) < CURRENT_SCHEMA_VERSION, (
            "CURRENT_SCHEMA_VERSION muss fuer die neue Spalte hochgezaehlt werden, "
            "sonst ueberspringt init_schema() Bestands-DBs (#368)"
        )
        db = VaultDB(legacy_db)
        db.init_schema()

        assert "stance" in _table_columns(legacy_db, "quotes")
        assert _user_version(legacy_db) == CURRENT_SCHEMA_VERSION

        db.add_quote(
            quote_id="q-after-migration",
            paper_id=_PAPER_ID,
            verbatim="Zitat nach der Migration.",
            extraction_method="manual",
            stance="mentions",
        )
        quote = db.get_quote("q-after-migration")
        assert quote is not None
        assert quote["stance"] == "mentions"

    def test_user_version_not_stamped_when_stance_migration_fails(self, legacy_db, monkeypatch):
        """Verifikation vor dem Stempeln gilt auch fuer die quotes-Spalte.

        Schluckt `add_stance_column` einen Fehler still (z. B. "database is
        locked"), darf `init_schema()` die DB nicht als migriert stempeln —
        sonst schliesst sich das Gate unwiderruflich (Muster aus PR #427).
        """
        monkeypatch.setattr(migrate, "add_stance_column", lambda db_path: None)
        VaultDB(legacy_db).init_schema()

        assert "stance" not in _table_columns(legacy_db, "quotes"), (
            "Testannahme verletzt: Monkeypatch hat nicht gegriffen"
        )
        assert _user_version(legacy_db) < CURRENT_SCHEMA_VERSION
