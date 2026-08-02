"""Tests fuer ``resolve_quote_context`` -- echten Quellkontext speichern (Issue #520).

AC -> Testfall (siehe Issue #520 / Plan-Kommentar):
  - AC1 ``context_before/after`` nach ``add_quote(local-verbatim)`` nachweislich
    aus ``paper_fulltext``: :class:`TestAc1RealFulltextContext`
  - AC2 ohne Volltext/Treffer wird nichts geraten: :class:`TestAc2NoGuessing`
  - AC3 ``resolve_quote_context(quote_id)`` aufrufbar + Randlagen +
    Mehrfachvorkommen: :class:`TestAc3ResolveQuoteContextDirectCalls`,
    :class:`TestAc3SchemaMigration`

Zusaetzlich (Plan-Risikonotizen): Fuzzy-Fallback bei Extractor-Mismatch
(:class:`TestFuzzyFallback`) und Locked-Vault (:class:`TestLockedVault`).

Fixtures: ``tests/fixtures/verbatim/`` (aus #511) nur fuer den einen
Integrationstest ueber den echten ``add_quote(local-verbatim)``-Pfad; alle
uebrigen Tests rufen ``resolve_quote_context`` direkt und brauchen kein PDF,
weil die Funktion ausschliesslich gegen ``paper_fulltext`` prueft.
"""

import os
import sqlite3

import pytest
from academic_vault import db as db_module
from academic_vault.db import VaultDB, VaultLockedError
from academic_vault.server import add_quote, get_quote, resolve_quote_context

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "verbatim")
SOURCE_PDF = os.path.join(FIXTURES, "verbatim_source.pdf")

_PAPER_ID = "context-fixture"
_CSL = '{"title": "Vault Context Fixture"}'

# Aus tests/fixtures/verbatim/create_fixtures.py (#511): exakter Wortlaut auf
# Seite 2 der Fixture-PDF, inkl. typografischer Anfuehrungszeichen.
CANDIDATE_EXACT_PAGE2 = 'Die Teilnehmenden beschrieben "implizites Wissen" als zentralen Faktor.'


def _vault_with_paper(tmp_path, pdf_path: str | None = None) -> str:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(_PAPER_ID, _CSL, pdf_path=pdf_path)
    return db_path


class TestAc1RealFulltextContext:
    """AC1: context_before/after nach add_quote(local-verbatim) stammen aus paper_fulltext."""

    def test_add_quote_local_verbatim_persists_fulltext_context(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)
        db = VaultDB(db_path)
        before_text = "Einleitender Absatz. " * 5
        after_text = " Abschliessender Absatz." * 5
        # Bewusst separater "Extractor" (anderer Wortlaut drumherum) als die
        # PDF-Seitenextraktion, die verify_verbatim nutzt (Issue #511-Risiko).
        fulltext = before_text + CANDIDATE_EXACT_PAGE2 + after_text
        assert db.set_fulltext(_PAPER_ID, fulltext, extractor="pdftext-mismatch") is True

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_EXACT_PAGE2,
            extraction_method="local-verbatim",
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["context_source"] == "fulltext"
        assert stored["context_before"]
        assert stored["context_after"]
        assert stored["context_before"] in fulltext
        assert stored["context_after"] in fulltext
        assert "Einleitender" in stored["context_before"]
        assert "Abschliessender" in stored["context_after"]


class TestAc2NoGuessing:
    """AC2: ohne Volltext oder ohne Fundstelle wird nichts geraten."""

    def test_add_quote_local_verbatim_without_fulltext_leaves_context_none(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_EXACT_PAGE2,
            extraction_method="local-verbatim",
        )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert stored["context_before"] is None
        assert stored["context_after"] is None
        assert stored["context_source"] is None

    def test_resolve_quote_context_without_fulltext_entry_is_noop(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        db.add_quote(
            quote_id="no-fulltext-quote",
            paper_id=_PAPER_ID,
            verbatim="Ein beliebiges Zitat ohne hinterlegten Volltext.",
            extraction_method="manual",
        )

        result = resolve_quote_context(db_path, "no-fulltext-quote")

        assert result is False
        stored = db.get_quote("no-fulltext-quote")
        assert stored is not None
        assert stored["context_before"] is None
        assert stored["context_after"] is None
        assert stored["context_source"] is None

    def test_resolve_quote_context_below_similarity_threshold_is_noop(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        verbatim = "Ein vollkommen anderslautender Satz."
        fulltext = "Voelliger unabhaengiger Text ueber Baumarten und Waelder. " * 20
        db.set_fulltext(_PAPER_ID, fulltext)
        db.add_quote(
            quote_id="nomatch-quote",
            paper_id=_PAPER_ID,
            verbatim=verbatim,
            extraction_method="manual",
        )

        result = resolve_quote_context(db_path, "nomatch-quote")

        assert result is False
        stored = db.get_quote("nomatch-quote")
        assert stored is not None
        assert stored["context_before"] is None
        assert stored["context_after"] is None
        assert stored["context_source"] is None

    def test_resolve_quote_context_unknown_quote_raises(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)

        with pytest.raises(ValueError, match="nicht gefunden"):
            resolve_quote_context(db_path, "gibt-es-nicht")


class TestAc3ResolveQuoteContextDirectCalls:
    """AC3: resolve_quote_context(quote_id) direkt aufrufbar, Randlagen, Mehrfachvorkommen."""

    def test_match_at_text_start_clips_context_before(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        verbatim = "Der Anfang des Textes ist die Fundstelle selbst."
        after_text = " Danach folgt weiterer Text." * 30
        fulltext = verbatim + after_text
        db.set_fulltext(_PAPER_ID, fulltext)
        db.add_quote(
            quote_id="start-quote",
            paper_id=_PAPER_ID,
            verbatim=verbatim,
            extraction_method="manual",
        )

        result = resolve_quote_context(db_path, "start-quote", window=600)

        assert result is True
        stored = db.get_quote("start-quote")
        assert stored is not None
        assert stored["context_before"] == ""
        assert stored["context_after"]
        assert len(stored["context_after"]) <= 600
        assert stored["context_source"] == "fulltext"

    def test_match_at_text_end_clips_context_after(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        verbatim = "Das Ende des Textes ist die Fundstelle selbst."
        before_text = "Davor steht einiges an Text. " * 30
        fulltext = before_text + verbatim
        db.set_fulltext(_PAPER_ID, fulltext)
        db.add_quote(
            quote_id="end-quote",
            paper_id=_PAPER_ID,
            verbatim=verbatim,
            extraction_method="manual",
        )

        result = resolve_quote_context(db_path, "end-quote", window=600)

        assert result is True
        stored = db.get_quote("end-quote")
        assert stored is not None
        assert stored["context_after"] == ""
        assert stored["context_before"]
        assert len(stored["context_before"]) <= 600
        assert stored["context_source"] == "fulltext"

    def test_multiple_occurrences_uses_first_deterministically(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        verbatim = "Wiederkehrender Satz zur Fundstelle."
        fulltext = (
            "ERSTER_MARKER "
            + verbatim
            + " nach dem ersten Vorkommen. "
            + "Fuellwort " * 200
            + "ZWEITER_MARKER "
            + verbatim
            + " nach dem zweiten Vorkommen."
        )
        db.set_fulltext(_PAPER_ID, fulltext)
        db.add_quote(
            quote_id="dup-quote",
            paper_id=_PAPER_ID,
            verbatim=verbatim,
            extraction_method="manual",
        )

        result = resolve_quote_context(db_path, "dup-quote", window=600)

        assert result is True
        stored = db.get_quote("dup-quote")
        assert stored is not None
        assert "ERSTER_MARKER" in stored["context_before"]
        assert "ZWEITER_MARKER" not in stored["context_before"]
        assert "nach dem ersten" in stored["context_after"]
        assert "nach dem zweiten" not in stored["context_after"]


def _create_v6_quotes_db(db_path: str) -> None:
    """Legt papers/quotes im Schema NACH #512 (v6), aber VOR #520 (kein context_source) an."""
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
              chapter             TEXT,
              page_first          INTEGER,
              page_last           INTEGER,
              container_title     TEXT,
              parent_paper_id     TEXT REFERENCES papers(paper_id),
              provenance          TEXT DEFAULT NULL,
              added_at            INTEGER NOT NULL,
              updated_at          INTEGER NOT NULL,
              source_kind         TEXT NOT NULL DEFAULT 'literature'
                                    CHECK(source_kind IN ('literature','primary'))
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
                                  CHECK(extraction_method IN
                                        ('citations-api','manual','local-verbatim')),
              api_response_id   TEXT,
              created_at        INTEGER NOT NULL,
              stance            TEXT CHECK(stance IN
                                        ('supports','contrasts','mentions') OR stance IS NULL)
            )
        """)
        conn.execute(
            "INSERT INTO papers (paper_id, csl_json, added_at, updated_at) VALUES (?, ?, 0, 0)",
            (_PAPER_ID, _CSL),
        )
        conn.execute(
            "INSERT INTO quotes (quote_id, paper_id, verbatim, extraction_method, created_at) "
            "VALUES ('legacy-quote', ?, 'Altes Zitat', 'manual', 4711)",
            (_PAPER_ID,),
        )
        conn.execute("PRAGMA user_version = 6")
        conn.commit()
    finally:
        conn.close()


class TestAc3SchemaMigration:
    """AC3-Randbedingung: Bestands-DBs (Schema v6) werden ohne Datenverlust migriert."""

    def test_current_schema_version_covers_context_source(self):
        # context_source kam mit Schema 7; spaetere Generationen (#629: 8)
        # duerfen weiterzaehlen, unterschreiten darf die Version sie nie.
        assert db_module.CURRENT_SCHEMA_VERSION >= 7

    def test_fresh_db_has_context_source_column(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        VaultDB(db_path).init_schema()

        conn = sqlite3.connect(db_path)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(quotes)").fetchall()}
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert "context_source" in cols
        assert version == db_module.CURRENT_SCHEMA_VERSION

    def test_legacy_v6_db_gets_context_source_column_without_data_loss(self, tmp_path):
        db_path = str(tmp_path / "legacy_v6.db")
        _create_v6_quotes_db(db_path)

        VaultDB(db_path).init_schema()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(quotes)").fetchall()}
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            row = dict(
                conn.execute("SELECT * FROM quotes WHERE quote_id = 'legacy-quote'").fetchone()
            )
        finally:
            conn.close()

        assert "context_source" in cols
        assert version == db_module.CURRENT_SCHEMA_VERSION
        assert row["verbatim"] == "Altes Zitat"
        assert row["context_source"] is None

    def test_add_context_source_column_is_idempotent(self, tmp_path):
        from academic_vault import migrate

        db_path = str(tmp_path / "legacy_v6.db")
        _create_v6_quotes_db(db_path)

        migrate.add_context_source_column(db_path)
        migrate.add_context_source_column(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(quotes)").fetchall()]
        finally:
            conn.close()
        assert cols.count("context_source") == 1


class TestFuzzyFallback:
    """Extractor-Mismatch (Plan-Risikonotiz): Fuzzy-Fallback via rapidfuzz."""

    def test_extractor_mismatch_falls_back_to_fuzzy_match(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        verbatim = "Die Charakteristik der Prozesse zeigt sich deutlich."
        # Volltext-Extraktor liefert eine leicht abweichende Schreibweise
        # (Tippfehler-Analog fuer echte Extractor-Drift) -- kein exakter
        # Substring-Treffer, aber deutlich ueber SNAP_RATIO_THRESHOLD.
        mismatched = "Die Charaktersitik der Prozesse zeigt sich deutlich."
        fulltext = "Vorspann-Text. " * 10 + mismatched + " Nachspann-Text." * 10
        db.set_fulltext(_PAPER_ID, fulltext)
        db.add_quote(
            quote_id="fuzzy-quote",
            paper_id=_PAPER_ID,
            verbatim=verbatim,
            extraction_method="manual",
        )

        result = resolve_quote_context(db_path, "fuzzy-quote")

        assert result is True
        stored = db.get_quote("fuzzy-quote")
        assert stored is not None
        assert stored["context_source"] == "fulltext"
        assert "Vorspann-Text" in stored["context_before"]
        assert "Nachspann-Text" in stored["context_after"]


class TestLockedVault:
    """Locked-Vault (Plan-Risikonotiz): resolve_quote_context respektiert den Lock."""

    def test_resolve_quote_context_raises_on_locked_vault(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        verbatim = "Zitat, das im Volltext auffindbar ist."
        fulltext = "Kontext davor. " + verbatim + " Kontext danach."
        db.set_fulltext(_PAPER_ID, fulltext)
        db.add_quote(
            quote_id="locked-quote",
            paper_id=_PAPER_ID,
            verbatim=verbatim,
            extraction_method="manual",
        )
        db.lock_vault("test-slug")

        with pytest.raises(VaultLockedError):
            resolve_quote_context(db_path, "locked-quote")

        stored = db.get_quote("locked-quote")
        assert stored is not None
        assert stored["context_source"] is None
        assert stored["context_before"] is None


class TestAddQuoteNonFatalIntegration:
    """add_quote() darf durch einen Kontext-Backfill-Fehler nicht scheitern (#520)."""

    def test_context_backfill_failure_does_not_fail_add_quote(self, tmp_path, monkeypatch, caplog):
        import academic_vault.server as server_module

        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        def _boom(db_path, quote_id, window=600):
            raise RuntimeError("simulierter Fehler im Kontext-Backfill")

        monkeypatch.setattr(server_module, "resolve_quote_context", _boom)

        with caplog.at_level("WARNING", logger="academic_vault.server"):
            quote_id = add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=CANDIDATE_EXACT_PAGE2,
                extraction_method="local-verbatim",
            )

        stored = get_quote(db_path, quote_id)
        assert stored is not None
        assert "simulierter Fehler" in caplog.text

    def test_manual_path_never_calls_resolve_quote_context(self, tmp_path, monkeypatch):
        import academic_vault.server as server_module

        db_path = _vault_with_paper(tmp_path, None)

        def _boom(*args, **kwargs):
            raise AssertionError("resolve_quote_context darf auf dem manual-Pfad nicht laufen")

        monkeypatch.setattr(server_module, "resolve_quote_context", _boom)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim="Von Hand belegtes Zitat.",
            extraction_method="manual",
        )

        assert get_quote(db_path, quote_id) is not None
