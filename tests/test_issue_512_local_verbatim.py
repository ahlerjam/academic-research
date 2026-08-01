"""Tests fuer fail-closed ``extraction_method='local-verbatim'`` (Issue #512).

Der Enforcement-Punkt liegt bewusst in ``server.add_quote()`` und nicht in
einem Hook: ein Hook-Marker laesst sich abschalten, der Vault-Pfad nicht.
Geprueft wird deshalb immer BEIDES -- dass die erwartete ``ValueError``
fliegt UND dass die Datenbank danach leer ist (kein Teil-Insert).

AC -> Testfall (siehe Issue #512):
  - AC1 nicht belegbarer Kandidat -> ValueError, nichts gespeichert:
    :class:`TestAc1FailClosed`
  - AC2 ``snapped`` persistiert den Quelltext samt verifizierter Seite:
    :class:`TestAc2SnappedPersistsSourceWording`
  - AC3 Bestands-DBs werden ohne Datenverlust migriert:
    :class:`TestAc3Migration`
  - AC4 ``citations-api``/``manual`` bleiben unveraendert:
    :class:`TestAc4LegacyPathsUnchanged`

Fixtures: ``tests/fixtures/verbatim/`` (aus #511, siehe dortiges
``create_fixtures.py`` fuer die exakte Kontrolle des extrahierten Textes).
"""

import os
import sqlite3

import pytest
from academic_vault import db as db_module
from academic_vault import migrate
from academic_vault.db import VaultDB
from academic_vault.server import add_quote, get_quote
from academic_vault.verbatim import verify_verbatim

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "verbatim")
SOURCE_PDF = os.path.join(FIXTURES, "verbatim_source.pdf")
SCAN_PDF = os.path.join(FIXTURES, "scan_no_text.pdf")

_PAPER_ID = "verbatim-fixture"
_CSL = '{"title": "Vault Verbatim Fixture"}'

# Wortlaute aus tests/fixtures/verbatim/create_fixtures.py:
# Seite 1 enthaelt "Der Interviewpartner betonte ...", Seite 2 den Satz mit
# typografischen Anfuehrungszeichen.
CANDIDATE_TYPO_PAGE1 = "Der Interviewpartner betonto die Bedeutung von Vertrauen im Team."
CANDIDATE_EXACT_PAGE2 = 'Die Teilnehmenden beschrieben "implizites Wissen" als zentralen Faktor.'
CANDIDATE_UNRELATED = "Die Wallfahrt nach Santiago de Compostela ist unabhaengig vom Studienthema."


def _quote_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0])
    finally:
        conn.close()


def _vault_with_paper(tmp_path, pdf_path: str | None) -> str:
    """Frischer Vault mit genau einem Paper (optional mit ``pdf_path``)."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(_PAPER_ID, _CSL, pdf_path=pdf_path)
    return db_path


class TestAc1FailClosed:
    """AC1: nicht belegbarer Kandidat -> ValueError, nichts gespeichert."""

    def test_no_match_raises_and_persists_nothing(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        with pytest.raises(ValueError, match="no-match"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_UNRELATED,
                extraction_method="local-verbatim",
            )

        assert _quote_count(db_path) == 0

    def test_no_textlayer_raises_and_persists_nothing(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SCAN_PDF)

        with pytest.raises(ValueError, match="no-textlayer"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim="Ein beliebiger Kandidat.",
                extraction_method="local-verbatim",
            )

        assert _quote_count(db_path) == 0

    def test_missing_pdf_path_raises_and_persists_nothing(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)

        with pytest.raises(ValueError, match="pdf_path"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_EXACT_PAGE2,
                extraction_method="local-verbatim",
            )

        assert _quote_count(db_path) == 0

    def test_nonexistent_pdf_file_raises_and_persists_nothing(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, str(tmp_path / "weg.pdf"))

        with pytest.raises(ValueError, match="existiert nicht"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_EXACT_PAGE2,
                extraction_method="local-verbatim",
            )

        assert _quote_count(db_path) == 0

    def test_unknown_paper_raises_and_persists_nothing(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        with pytest.raises(ValueError, match="nicht gefunden"):
            add_quote(
                db_path=db_path,
                paper_id="gibt-es-nicht",
                verbatim=CANDIDATE_EXACT_PAGE2,
                extraction_method="local-verbatim",
            )

        assert _quote_count(db_path) == 0

    def test_error_message_names_the_fallback_path(self, tmp_path):
        """Fail-closed ist eine harte Nutzerblockade -- der Ausweg muss drinstehen.

        Grenze des Pruefers (Learning #511): seitenuebergreifende Zitate und
        Wort-Auslassungen koennen falsch-negativ ``no-match`` liefern. Die
        Meldung nennt deshalb ``manual`` als dokumentierten Ausweichweg.
        """
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        with pytest.raises(ValueError, match="manual"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_UNRELATED,
                extraction_method="local-verbatim",
            )


class TestAc2SnappedPersistsSourceWording:
    """AC2: bei ``snapped`` wird der Quelltext samt ``pdf_page`` gespeichert."""

    def test_snapped_persists_source_wording_not_candidate(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)
        expected = verify_verbatim(SOURCE_PDF, CANDIDATE_TYPO_PAGE1)
        assert expected.status == "snapped", "Fixture-Annahme verletzt"

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_TYPO_PAGE1,
            extraction_method="local-verbatim",
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["verbatim"] == expected.verbatim
        assert stored["verbatim"] != CANDIDATE_TYPO_PAGE1
        assert "betonte" in stored["verbatim"]
        assert "betonto" not in stored["verbatim"]
        assert stored["pdf_page"] == 1

    def test_verified_page_wins_over_caller_page(self, tmp_path):
        """Der Beweis ist die verifizierte Seite, nicht die behauptete."""
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_TYPO_PAGE1,
            extraction_method="local-verbatim",
            pdf_page=99,
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["pdf_page"] == 1

    def test_conflicting_caller_page_is_logged(self, tmp_path, caplog):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        with caplog.at_level("WARNING", logger="academic_vault.server"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_TYPO_PAGE1,
                extraction_method="local-verbatim",
                pdf_page=99,
            )

        assert any("99" in record.getMessage() for record in caplog.records)

    def test_exact_match_persists_and_records_page(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)
        expected = verify_verbatim(SOURCE_PDF, CANDIDATE_EXACT_PAGE2)
        assert expected.status == "exact", "Fixture-Annahme verletzt"

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_EXACT_PAGE2,
            extraction_method="local-verbatim",
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["verbatim"] == expected.verbatim
        assert stored["pdf_page"] == 2

    def test_other_fields_are_passed_through(self, tmp_path):
        """Nur Wortlaut und Seite kommen aus dem Pruefer -- der Rest bleibt."""
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_EXACT_PAGE2,
            extraction_method="local-verbatim",
            printed_page=42,
            section="Ergebnisse",
            stance="supports",
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["printed_page"] == 42
        assert stored["section"] == "Ergebnisse"
        assert stored["stance"] == "supports"
        assert stored["extraction_method"] == "local-verbatim"


class TestFreshSchemaAcceptsLocalVerbatim:
    def test_valid_extraction_methods_constant(self):
        assert db_module.VALID_EXTRACTION_METHODS == frozenset(
            {"citations-api", "manual", "local-verbatim"}
        )

    def test_fresh_schema_check_accepts_local_verbatim(self, tmp_path):
        """Zweite Verteidigungslinie: der CHECK selbst laesst den Wert zu."""
        db_path = str(tmp_path / "fresh.db")
        db = VaultDB(db_path)
        db.init_schema()
        db.add_paper(_PAPER_ID, _CSL)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO quotes (quote_id, paper_id, verbatim, extraction_method, "
                "created_at) VALUES ('direct', ?, 'Text', 'local-verbatim', 0)",
                (_PAPER_ID,),
            )
            conn.commit()
        finally:
            conn.close()

        assert _quote_count(db_path) == 1

    def test_fresh_db_is_stamped_with_current_version(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        VaultDB(db_path).init_schema()

        conn = sqlite3.connect(db_path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert version == db_module.CURRENT_SCHEMA_VERSION
        assert db_module.CURRENT_SCHEMA_VERSION >= 6


def _create_legacy_quotes_db(db_path: str, *, with_stance: bool = False) -> None:
    """Legt papers/quotes/codings im Schema VOR #512 an (alter CHECK).

    ``papers`` bekommt den vollstaendigen Stand nach #195/#368, damit hier
    ausschliesslich die neue ``quotes``-Migration geprueft wird. ``codings``
    haelt eine Fremdschluessel-Referenz auf ``quotes`` -- der Tabellen-Rebuild
    muss sie unbeschaedigt lassen.
    """
    stance_column = (
        ",\n              stance TEXT CHECK(stance IN "
        "('supports','contrasts','mentions') OR stance IS NULL)"
        if with_stance
        else ""
    )
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
        conn.execute(f"""
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
              created_at        INTEGER NOT NULL{stance_column}
            )
        """)
        conn.execute("""
            CREATE TABLE codings (
              coding_id TEXT PRIMARY KEY,
              quote_id  TEXT REFERENCES quotes(quote_id)
            )
        """)
        conn.execute(
            "INSERT INTO papers (paper_id, csl_json, added_at, updated_at) VALUES (?, ?, 0, 0)",
            (_PAPER_ID, _CSL),
        )
        conn.execute(
            "INSERT INTO quotes (quote_id, paper_id, verbatim, pdf_page, printed_page, "
            "section, context_before, context_after, extraction_method, api_response_id, "
            "created_at) VALUES ('legacy-quote', ?, 'Altes Zitat', 7, 12, 'Methode', "
            "'davor', 'danach', 'manual', 'resp-1', 4711)",
            (_PAPER_ID,),
        )
        if with_stance:
            conn.execute("UPDATE quotes SET stance = 'supports' WHERE quote_id = 'legacy-quote'")
        conn.execute("INSERT INTO codings (coding_id, quote_id) VALUES ('c1', 'legacy-quote')")
        conn.execute("PRAGMA user_version = 5")
        conn.commit()
    finally:
        conn.close()


def _quotes_table_sql(db_path: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='quotes'"
        ).fetchone()
    finally:
        conn.close()
    return str(row[0])


def _legacy_row(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM quotes WHERE quote_id = 'legacy-quote'").fetchone()
    finally:
        conn.close()
    return dict(row)


class TestAc3Migration:
    """AC3: Bestands-DBs werden ohne Datenverlust auf den neuen CHECK gehoben."""

    @pytest.fixture
    def legacy_db(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        _create_legacy_quotes_db(db_path)
        assert "local-verbatim" not in _quotes_table_sql(db_path), "Fixture-Annahme verletzt"
        return db_path

    def test_legacy_check_rejects_local_verbatim_before_migration(self, legacy_db):
        conn = sqlite3.connect(legacy_db)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO quotes (quote_id, paper_id, verbatim, extraction_method, "
                    "created_at) VALUES ('x', ?, 'Text', 'local-verbatim', 0)",
                    (_PAPER_ID,),
                )
        finally:
            conn.close()

    def test_widen_check_migrates_legacy_db_without_data_loss(self, legacy_db):
        before = _legacy_row(legacy_db)

        migrate.widen_extraction_method_check(legacy_db)

        assert "local-verbatim" in _quotes_table_sql(legacy_db)
        assert _legacy_row(legacy_db) == before

    def test_migrated_check_accepts_local_verbatim(self, legacy_db):
        migrate.widen_extraction_method_check(legacy_db)

        conn = sqlite3.connect(legacy_db)
        try:
            conn.execute(
                "INSERT INTO quotes (quote_id, paper_id, verbatim, extraction_method, "
                "created_at) VALUES ('neu', ?, 'Text', 'local-verbatim', 0)",
                (_PAPER_ID,),
            )
            conn.commit()
        finally:
            conn.close()
        assert _quote_count(legacy_db) == 2

    def test_migrated_check_still_rejects_unknown_method(self, legacy_db):
        migrate.widen_extraction_method_check(legacy_db)

        conn = sqlite3.connect(legacy_db)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO quotes (quote_id, paper_id, verbatim, extraction_method, "
                    "created_at) VALUES ('muell', ?, 'Text', 'erfunden', 0)",
                    (_PAPER_ID,),
                )
        finally:
            conn.close()

    def test_migration_is_idempotent(self, legacy_db):
        before = _legacy_row(legacy_db)

        migrate.widen_extraction_method_check(legacy_db)
        sql_after_first = _quotes_table_sql(legacy_db)
        migrate.widen_extraction_method_check(legacy_db)

        assert _quotes_table_sql(legacy_db) == sql_after_first
        assert _legacy_row(legacy_db) == before
        assert _quote_count(legacy_db) == 1

    def test_foreign_key_check_clean_after_rebuild(self, legacy_db):
        migrate.widen_extraction_method_check(legacy_db)

        conn = sqlite3.connect(legacy_db)
        try:
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            codings = conn.execute("SELECT COUNT(*) FROM codings").fetchone()[0]
        finally:
            conn.close()
        assert violations == []
        assert codings == 1

    def test_legacy_db_keeps_stance_column_after_rebuild(self, tmp_path):
        """Reihenfolge-Unabhaengigkeit: eine bereits vorhandene stance-Spalte
        (und ihr Wert) ueberlebt den Tabellen-Rebuild."""
        db_path = str(tmp_path / "legacy_stance.db")
        _create_legacy_quotes_db(db_path, with_stance=True)

        migrate.apply_pending_migrations(db_path)

        row = _legacy_row(db_path)
        assert row["stance"] == "supports"
        assert "local-verbatim" in _quotes_table_sql(db_path)

    def test_apply_pending_migrations_widens_check(self, legacy_db):
        migrate.apply_pending_migrations(legacy_db)

        assert "local-verbatim" in _quotes_table_sql(legacy_db)
        assert "stance" in _legacy_row(legacy_db)

    def test_init_schema_migrates_and_stamps_version(self, legacy_db):
        VaultDB(legacy_db).init_schema()

        conn = sqlite3.connect(legacy_db)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert version == db_module.CURRENT_SCHEMA_VERSION
        assert "local-verbatim" in _quotes_table_sql(legacy_db)

    def test_version_not_stamped_when_rebuild_fails(self, legacy_db, monkeypatch):
        """Risiko 1: der Stempel darf nicht ohne wirksamen Rebuild fallen."""
        monkeypatch.setattr(migrate, "widen_extraction_method_check", lambda db_path: None)

        VaultDB(legacy_db).init_schema()

        conn = sqlite3.connect(legacy_db)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert version < db_module.CURRENT_SCHEMA_VERSION
        assert "local-verbatim" not in _quotes_table_sql(legacy_db)


class TestAc4LegacyPathsUnchanged:
    """AC4: ``citations-api`` und ``manual`` verhalten sich unveraendert."""

    def test_citations_api_still_requires_api_response_id(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        with pytest.raises(ValueError, match="api_response_id"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_EXACT_PAGE2,
                extraction_method="citations-api",
                api_response_id=None,
            )

        assert _quote_count(db_path) == 0

    def test_manual_path_skips_verification(self, tmp_path, monkeypatch):
        """``manual`` speichert unveraendert und ruft den Pruefer gar nicht auf."""
        import academic_vault.verbatim as verbatim_module

        def _boom(*args, **kwargs):
            raise AssertionError("verify_verbatim darf auf dem manual-Pfad nicht laufen")

        monkeypatch.setattr(verbatim_module, "verify_verbatim", _boom)
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_UNRELATED,
            extraction_method="manual",
            pdf_page=99,
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["verbatim"] == CANDIDATE_UNRELATED
        assert stored["pdf_page"] == 99

    def test_citations_api_path_skips_verification(self, tmp_path, monkeypatch):
        import academic_vault.verbatim as verbatim_module

        def _boom(*args, **kwargs):
            raise AssertionError("verify_verbatim darf auf dem API-Pfad nicht laufen")

        monkeypatch.setattr(verbatim_module, "verify_verbatim", _boom)
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_UNRELATED,
            extraction_method="citations-api",
            api_response_id="resp-42",
            pdf_page=7,
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["verbatim"] == CANDIDATE_UNRELATED
        assert stored["pdf_page"] == 7

    def test_monkeypatch_control_local_verbatim_path_does_call_verifier(
        self, tmp_path, monkeypatch
    ):
        """Positivkontrolle zu den beiden Tests darueber.

        Ohne sie waeren die ``skips_verification``-Tests wertlos: sie wuerden
        auch dann gruen bleiben, wenn der Monkeypatch am lazy importierten
        Namen vorbeigeht und ``verify_verbatim`` NIE ersetzt wird.
        """
        import academic_vault.verbatim as verbatim_module

        def _boom(*args, **kwargs):
            raise AssertionError("Pruefer wurde erwartungsgemaess aufgerufen")

        monkeypatch.setattr(verbatim_module, "verify_verbatim", _boom)
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        with pytest.raises(AssertionError, match="erwartungsgemaess"):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_EXACT_PAGE2,
                extraction_method="local-verbatim",
            )

    def test_manual_path_works_without_pdf_path(self, tmp_path):
        """Ein Paper ohne PDF bleibt fuer ``manual`` uneingeschraenkt nutzbar."""
        db_path = _vault_with_paper(tmp_path, None)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim="Aus einem gedruckten Band abgetippt.",
            extraction_method="manual",
        )

        assert get_quote(db_path, quote_id) is not None
