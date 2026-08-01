"""Tests fuer quote_embeddings-Befuellung nach bestandener Pruefung (Issue #521).

AC -> Testfall (siehe Issue #521 / Plan-Kommentar):
  - AC1 (nur bestandene Pruefung erhaelt Embeddings): :class:`TestAc1EmbedsAfterVerification`
  - AC2 (fehlendes Backend / fehlende Extension degradiert sauber):
    :class:`TestAc2CleanDegradation`
  - AC3 (Backfill idempotent): :class:`TestAc3BackfillIdempotent`

Zusaetzlich (Plan-Risikonotizen): Locked-Vault (:class:`TestLockedVault`).

Rot->Gruen-Beweis: Diese Testdatei importiert ``embed_quote`` aus
``academic_vault.server`` -- auf ``origin/main`` (vor #521) existiert die
Funktion nicht, der Import schlaegt mit ``ImportError`` fehl; auf diesem
Branch gruen.

Fixtures: ``tests/fixtures/verbatim/`` (aus #511) nur fuer den
``local-verbatim``-Fall in AC1; alle uebrigen Tests kommen ohne PDF aus, weil
``embed_quote`` ausschliesslich gegen bereits gespeicherte ``quotes``-Zeilen
arbeitet.
"""

import logging
import os
import sqlite3

import pytest
from academic_vault import migrate
from academic_vault.db import VaultDB, VaultLockedError
from academic_vault.server import add_quote, embed_quote, get_quote

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "verbatim")
SOURCE_PDF = os.path.join(FIXTURES, "verbatim_source.pdf")

_PAPER_ID = "quote-embed-fixture"
_CSL = '{"title": "Quote Embedding Fixture"}'

# Aus tests/fixtures/verbatim/create_fixtures.py (#511): exakter Wortlaut auf
# Seite 2 der Fixture-PDF, inkl. typografischer Anfuehrungszeichen.
CANDIDATE_EXACT_PAGE2 = 'Die Teilnehmenden beschrieben "implizites Wissen" als zentralen Faktor.'


def _vault_with_paper(tmp_path, pdf_path: str | None = None) -> str:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(_PAPER_ID, _CSL, pdf_path=pdf_path)
    return db_path


def _vec_available(db_path: str) -> bool:
    """Prueft ``vec_available`` ueber eine FRISCH initialisierte Instanz.

    ``VaultDB.vec_available`` ist Instanz-Zustand (per-Connection gesetzt via
    ``init_schema()``/``load_vec_extension()``), nicht aus der DB-Datei
    ableitbar -- ein neu konstruiertes ``VaultDB(db_path)`` startet immer mit
    ``vec_available=False``, bis eine Connection auf dieser Instanz die
    Extension geladen hat.
    """
    db = VaultDB(db_path)
    db.init_schema()
    return db.vec_available


def _open_vec_conn(db_path: str) -> sqlite3.Connection:
    """Frische Connection mit geladener sqlite-vec-Extension (Muster test_vault_embeddings_ingest)."""
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    import sqlite_vec

    conn.load_extension(sqlite_vec.loadable_path())
    return conn


def _quote_embedding_row_count(db_path: str) -> int:
    conn = _open_vec_conn(db_path)
    try:
        return int(conn.execute("SELECT count(*) FROM quote_embeddings").fetchone()[0])
    finally:
        conn.close()


def _quote_has_embedding(db_path: str, quote_id: str) -> bool:
    conn = _open_vec_conn(db_path)
    try:
        row = conn.execute(
            "SELECT quote_id FROM quote_embeddings WHERE quote_id = ?", (quote_id,)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


class TestAc1EmbedsAfterVerification:
    """AC1: nur Quotes mit bestandener Pruefung (alle drei extraction_method) erhalten Embeddings."""

    def test_local_verbatim_gets_embedded(self, tmp_path, fake_embedder, monkeypatch):
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)
        if not _vec_available(db_path):
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_EXACT_PAGE2,
            extraction_method="local-verbatim",
        )

        assert _quote_embedding_row_count(db_path) == 1
        assert _quote_has_embedding(db_path, quote_id)

    def test_citations_api_gets_embedded(self, tmp_path, fake_embedder, monkeypatch):
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)
        db_path = _vault_with_paper(tmp_path, None)
        if not _vec_available(db_path):
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim="Ein per Citations-API belegtes Zitat.",
            extraction_method="citations-api",
            api_response_id="resp_1",
        )

        assert _quote_embedding_row_count(db_path) == 1
        assert _quote_has_embedding(db_path, quote_id)

    def test_manual_gets_embedded(self, tmp_path, fake_embedder, monkeypatch):
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)
        db_path = _vault_with_paper(tmp_path, None)
        if not _vec_available(db_path):
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim="Ein manuell erfasstes Zitat mit eigenem Beleg.",
            extraction_method="manual",
        )

        assert _quote_embedding_row_count(db_path) == 1
        assert _quote_has_embedding(db_path, quote_id)

    def test_embedding_text_falls_back_to_verbatim_without_context(
        self, tmp_path, fake_embedder, monkeypatch
    ):
        """Ohne context_before/after (manual, kein resolve_quote_context) wird nur verbatim eingebettet."""
        db_path = _vault_with_paper(tmp_path, None)
        if not _vec_available(db_path):
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")

        captured: dict = {}
        original_embed_documents = fake_embedder.embed_documents

        def _spy(texts):
            captured["texts"] = list(texts)
            return original_embed_documents(texts)

        monkeypatch.setattr(fake_embedder, "embed_documents", _spy)
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)

        verbatim = "Nacktes Zitat ohne jeglichen Kontext."
        add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=verbatim,
            extraction_method="manual",
        )

        assert captured["texts"] == [verbatim]

    def test_invalid_extraction_method_fails_check_constraint_before_embedding(
        self, tmp_path, fake_embedder, monkeypatch
    ):
        """Ungueltiger extraction_method scheitert weiterhin am CHECK-Constraint (kein Embedding-Versuch)."""
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)

        with pytest.raises(sqlite3.IntegrityError):
            db.add_quote(
                quote_id="bad-method-quote",
                paper_id=_PAPER_ID,
                verbatim="Irrelevant.",
                extraction_method="not-a-real-method",
            )

        if _vec_available(db_path):
            assert not _quote_has_embedding(db_path, "bad-method-quote")


class TestAc2CleanDegradation:
    """AC2: fehlendes Backend / fehlende Extension degradieren sauber (geloggt, kein Absturz)."""

    def test_add_quote_without_backend_does_not_raise_and_leaves_no_embedding(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: None)
        db_path = _vault_with_paper(tmp_path, None)
        if not _vec_available(db_path):
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")

        with caplog.at_level(logging.WARNING):
            quote_id = add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim="Ein Zitat ohne Embedding-Backend.",
                extraction_method="manual",
            )

        assert quote_id  # add_quote() wirft nicht, gibt quote_id normal zurueck
        assert get_quote(db_path, quote_id) is not None
        assert not _quote_has_embedding(db_path, quote_id)
        assert any("embedding" in r.message.lower() for r in caplog.records)

    def test_embed_quote_returns_false_without_vec_extension(
        self, tmp_path, fake_embedder, monkeypatch, caplog
    ):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        db.add_quote(
            quote_id="no-ext-quote",
            paper_id=_PAPER_ID,
            verbatim="Zitat ohne ladbare Extension.",
            extraction_method="manual",
        )

        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)
        monkeypatch.setattr(VaultDB, "load_vec_extension", lambda self, conn=None: False)

        with caplog.at_level(logging.WARNING):
            result = embed_quote(db_path, "no-ext-quote")

        assert result is False
        assert any("extension" in r.message.lower() for r in caplog.records)

    def test_maybe_embed_quote_swallows_unexpected_exceptions(self, tmp_path, monkeypatch, caplog):
        """_maybe_embed_quote() faengt auch unerwartete Fehler ab (Muster _maybe_resolve_quote_context)."""
        from academic_vault.server import _maybe_embed_quote

        def _boom(*_a, **_kw):
            raise RuntimeError("kaputt")

        monkeypatch.setattr("academic_vault.server.embed_quote", _boom)

        with caplog.at_level(logging.WARNING):
            result = _maybe_embed_quote("irrelevant.db", "irrelevant-quote")

        assert result is False
        assert any("fehlgeschlagen" in r.message.lower() for r in caplog.records)


class TestAc3BackfillIdempotent:
    """AC3: Backfill fuellt Bestands-Quotes nach und ist idempotent."""

    def test_backfill_embeds_missing_quotes_and_second_run_is_noop(
        self, tmp_path, fake_embedder, monkeypatch
    ):
        # Insert ohne Embedder -> quote_embeddings bleibt zunaechst leer.
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: None)
        db_path = _vault_with_paper(tmp_path, None)
        if not _vec_available(db_path):
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")

        quote_ids = [
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=f"Zitat Nummer {i} ohne Embedding beim Insert.",
                extraction_method="manual",
            )
            for i in range(3)
        ]
        assert _quote_embedding_row_count(db_path) == 0

        stats = migrate.backfill_quote_embeddings(db_path, embedder=fake_embedder)

        assert stats == {"embedded": 3, "skipped": 0}
        assert _quote_embedding_row_count(db_path) == 3
        for quote_id in quote_ids:
            assert _quote_has_embedding(db_path, quote_id)

        # Zweiter Lauf direkt danach: keine Kandidaten mehr uebrig -> No-op,
        # keine Duplikate, Zeilenzahl unveraendert.
        stats_second = migrate.backfill_quote_embeddings(db_path, embedder=fake_embedder)

        assert stats_second == {"embedded": 0, "skipped": 0}
        assert _quote_embedding_row_count(db_path) == 3

    def test_backfill_without_vec_extension_is_clean_noop(
        self, tmp_path, fake_embedder, monkeypatch
    ):
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        db.add_quote(
            quote_id="no-ext-backfill-quote",
            paper_id=_PAPER_ID,
            verbatim="Zitat ohne ladbare Extension beim Backfill.",
            extraction_method="manual",
        )
        monkeypatch.setattr(VaultDB, "load_vec_extension", lambda self, conn=None: False)

        stats = migrate.backfill_quote_embeddings(db_path, embedder=fake_embedder)

        # quotes_missing_embedding() selbst degradiert auf [] ohne ladbare
        # Extension -- der Backfill findet keine Kandidaten, statt zu crashen.
        assert stats == {"embedded": 0, "skipped": 0}


class TestLockedVault:
    """Locked-Vault (Plan-Risikonotiz): add_quote_embedding respektiert den Lock."""

    def test_embed_quote_raises_on_locked_vault(self, tmp_path, fake_embedder, monkeypatch):
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)
        db_path = _vault_with_paper(tmp_path, None)
        if not _vec_available(db_path):
            pytest.skip("sqlite-vec-Extension nicht ladbar (optionales Feature)")
        db = VaultDB(db_path)
        db.add_quote(
            quote_id="locked-quote",
            paper_id=_PAPER_ID,
            verbatim="Zitat vor dem Lock.",
            extraction_method="manual",
        )
        db.lock_vault("test-slug")

        with pytest.raises(VaultLockedError):
            embed_quote(db_path, "locked-quote")

        assert not _quote_has_embedding(db_path, "locked-quote")

    def test_add_quote_on_locked_vault_never_reaches_embedding(
        self, tmp_path, fake_embedder, monkeypatch
    ):
        """vault.add_quote() selbst scheitert bereits am Lock, lange vor jedem Embedding-Versuch."""
        monkeypatch.setattr("academic_vault.server.get_embedder", lambda *a, **kw: fake_embedder)
        db_path = _vault_with_paper(tmp_path, None)
        db = VaultDB(db_path)
        db.lock_vault("test-slug")

        with pytest.raises(VaultLockedError):
            add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim="Zitat nach dem Lock.",
                extraction_method="manual",
            )
