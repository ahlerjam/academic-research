"""Tests fuer Issue #373 — papers_fts.fulltext wird real befuellt.

Vorher schrieben die FTS5-Trigger ``papers_ai``/``papers_au`` die Spalte
``fulltext`` hart auf ``NULL``; ``vault.search`` durchsuchte damit faktisch nur
Titel und Abstract. Diese Suite deckt die drei Akzeptanzkriterien ab:

  AC1  Nach der Extraktion steht der PDF-Text in ``papers_fts.fulltext``.
  AC2  ``search_papers`` findet ein Paper ueber einen Begriff, der
       ausschliesslich im PDF-Volltext vorkommt.
  AC3  Eine Backfill-Migration befuellt Bestands-Paper, ohne ``papers`` oder
       ``quotes`` zu veraendern.

Die Fixture-PDFs entstehen aus ``tests/fixtures/fulltext/create_fixtures.py``
(reine Standardbibliothek, kein reportlab).
"""

import json
import sqlite3
from pathlib import Path

import pytest
from academic_vault import fulltext as fulltext_mod
from academic_vault import migrate
from academic_vault.db import VaultDB, VaultLockedError
from academic_vault.server import add_paper as server_add_paper
from academic_vault.server import extract_fulltext_for_paper, search_papers

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fulltext"
NONCE_PDF = FIXTURE_DIR / "nonce_paper.pdf"
SCAN_PDF = FIXTURE_DIR / "scan_no_text.pdf"

# Kunstwort, das weder im Titel noch im Abstract der Testdaten vorkommt.
NONCE_TOKEN = "zqxwvfulltextnonce373"

CSL_WITHOUT_NONCE = json.dumps(
    {
        "type": "article-journal",
        "title": "Eine Studie ohne besonderes Schlagwort",
        "abstract": "Der Abstract nennt das Token bewusst nicht.",
    }
)

TEI_SAMPLE = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc><titleStmt><title>Ein GROBID-Titel</title></titleStmt></fileDesc>
  </teiHeader>
  <text xml:lang="de">
    <body>
      <div><head>Einleitung</head><p>Grobid-Absatz mit {NONCE_TOKEN} im Fliesstext.</p></div>
      <div><p>Zweiter    Absatz
      mit Zeilenumbruch.</p></div>
    </body>
  </text>
</TEI>
"""

# Schema-Stand VOR #373: Trigger schreiben fulltext hart auf NULL.
_LEGACY_TRIGGERS = """
DROP TRIGGER IF EXISTS papers_ai;
DROP TRIGGER IF EXISTS papers_au;
DROP TABLE IF EXISTS paper_fulltext;
CREATE TRIGGER papers_ai AFTER INSERT ON papers BEGIN
  INSERT INTO papers_fts(paper_id, title, abstract, fulltext)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract'),
    NULL
  );
END;
CREATE TRIGGER papers_au AFTER UPDATE ON papers BEGIN
  DELETE FROM papers_fts WHERE paper_id = old.paper_id;
  INSERT INTO papers_fts(paper_id, title, abstract, fulltext)
  VALUES (
    new.paper_id,
    json_extract(new.csl_json, '$.title'),
    json_extract(new.csl_json, '$.abstract'),
    NULL
  );
END;
"""


def _fts_fulltext(db_path: str, paper_id: str):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT fulltext FROM papers_fts WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


def _downgrade_to_legacy_schema(db_path: str) -> None:
    """Setzt eine frische DB auf den Schema-Stand vor #373 zurueck."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_LEGACY_TRIGGERS)
        conn.commit()
    finally:
        conn.close()


def _add_paper_with_pdf(db_path: str, paper_id: str = "nonce2026") -> None:
    VaultDB(db_path).add_paper(
        paper_id=paper_id,
        csl_json=CSL_WITHOUT_NONCE,
        pdf_path=str(NONCE_PDF),
    )


# ---------------------------------------------------------------------------
# Extraktion (academic_vault/fulltext.py)
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_pypdf_backend_extracts_nonce_token(self):
        text, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF), backend="pypdf")
        assert extractor == "pypdf"
        assert NONCE_TOKEN in text

    def test_extraction_normalizes_whitespace(self):
        text, _ = fulltext_mod.extract_fulltext(str(NONCE_PDF), backend="pypdf")
        assert "  " not in text
        assert "\n" not in text

    def test_scan_pdf_without_text_layer_yields_empty_result(self):
        """Scan-PDFs liefern leeren Text — der darf nicht als extrahiert gelten."""
        text, extractor = fulltext_mod.extract_fulltext(str(SCAN_PDF), backend="pypdf")
        assert text == ""
        assert extractor == ""

    def test_missing_pdf_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            fulltext_mod.extract_fulltext(str(tmp_path / "fehlt.pdf"))

    def test_text_is_truncated_at_max_chars(self, monkeypatch):
        monkeypatch.setattr(fulltext_mod, "MAX_FULLTEXT_CHARS", 20)
        text, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF), backend="pypdf")
        assert len(text) == 20
        assert extractor == "pypdf"


class TestGrobidBackend:
    def test_grobid_backend_parses_tei_body(self, monkeypatch):
        captured: dict = {}

        class _Response:
            status_code = 200
            text = TEI_SAMPLE

            def raise_for_status(self) -> None:
                return None

        def _fake_post(url, **kwargs):
            captured["url"] = url
            captured["files"] = kwargs.get("files")
            captured["data"] = kwargs.get("data")
            return _Response()

        monkeypatch.setattr(fulltext_mod.httpx, "post", _fake_post)
        monkeypatch.setenv(fulltext_mod.ENV_GROBID_URL, "http://localhost:8070")

        text, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF))

        assert extractor == "grobid"
        assert NONCE_TOKEN in text
        assert "Zweiter Absatz mit Zeilenumbruch." in text
        assert captured["url"] == "http://localhost:8070/api/processFulltextDocument"
        assert "input" in captured["files"]
        # Consolidation zieht sonst CrossRef-Requests nach sich (kein Offline-Lauf).
        assert captured["data"]["consolidateHeader"] == "0"

    def test_grobid_failure_falls_back_to_pypdf(self, monkeypatch):
        def _boom(url, **kwargs):
            raise fulltext_mod.httpx.ConnectError("kein Server")

        monkeypatch.setattr(fulltext_mod.httpx, "post", _boom)
        monkeypatch.setenv(fulltext_mod.ENV_GROBID_URL, "http://localhost:8070")

        text, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF))

        assert extractor == "pypdf"
        assert NONCE_TOKEN in text

    def test_grobid_is_opt_in_via_env(self, monkeypatch):
        """Ohne GROBID_URL wird der HTTP-Pfad gar nicht erst betreten."""

        def _must_not_be_called(url, **kwargs):
            raise AssertionError("GROBID wurde ohne GROBID_URL kontaktiert")

        monkeypatch.setattr(fulltext_mod.httpx, "post", _must_not_be_called)
        monkeypatch.delenv(fulltext_mod.ENV_GROBID_URL, raising=False)

        _, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF))
        assert extractor == "pypdf"


# ---------------------------------------------------------------------------
# AC1 — papers_fts.fulltext wird befuellt und bleibt befuellt
# ---------------------------------------------------------------------------


class TestSetFulltext:
    def test_set_fulltext_fills_papers_fts(self, temp_vault_db):
        _add_paper_with_pdf(temp_vault_db)
        assert _fts_fulltext(temp_vault_db, "nonce2026") in (None, "")

        text, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF), backend="pypdf")
        assert VaultDB(temp_vault_db).set_fulltext("nonce2026", text, extractor) is True

        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None
        assert NONCE_TOKEN in stored

    def test_fulltext_survives_paper_update(self, temp_vault_db):
        """``papers_au`` baut die FTS-Zeile neu — der Volltext muss ueberleben."""
        _add_paper_with_pdf(temp_vault_db)
        db = VaultDB(temp_vault_db)
        db.set_fulltext("nonce2026", f"Text mit {NONCE_TOKEN}", "pypdf")

        db.update_pdf_path("nonce2026", "/anderer/pfad.pdf")
        db.set_ocr_done("nonce2026", 1)

        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None and NONCE_TOKEN in stored

    def test_get_fulltext_roundtrip(self, temp_vault_db):
        _add_paper_with_pdf(temp_vault_db)
        db = VaultDB(temp_vault_db)
        assert db.get_fulltext("nonce2026") is None
        db.set_fulltext("nonce2026", "Ein Volltext", "pypdf")
        assert db.get_fulltext("nonce2026") == "Ein Volltext"

    def test_blank_text_is_not_persisted(self, temp_vault_db):
        """Leerer Extraktionsversuch (Scan-PDF) darf nichts als Volltext ablegen."""
        _add_paper_with_pdf(temp_vault_db)
        db = VaultDB(temp_vault_db)
        assert db.set_fulltext("nonce2026", "   \n  ", "pypdf") is False
        assert db.get_fulltext("nonce2026") is None

    def test_set_fulltext_is_idempotent(self, temp_vault_db):
        _add_paper_with_pdf(temp_vault_db)
        db = VaultDB(temp_vault_db)
        db.set_fulltext("nonce2026", f"erste Fassung {NONCE_TOKEN}", "pypdf")
        db.set_fulltext("nonce2026", f"zweite Fassung {NONCE_TOKEN}", "grobid")

        conn = sqlite3.connect(temp_vault_db)
        try:
            rows = conn.execute(
                "SELECT text, extractor FROM paper_fulltext WHERE paper_id = ?",
                ("nonce2026",),
            ).fetchall()
            fts_rows = conn.execute(
                "SELECT count(*) FROM papers_fts WHERE paper_id = ?", ("nonce2026",)
            ).fetchone()[0]
        finally:
            conn.close()
        assert rows == [(f"zweite Fassung {NONCE_TOKEN}", "grobid")]
        assert fts_rows == 1

    def test_set_fulltext_respects_vault_lock(self, temp_vault_db):
        _add_paper_with_pdf(temp_vault_db)
        db = VaultDB(temp_vault_db)
        db.lock_vault("projekt")
        with pytest.raises(VaultLockedError):
            db.set_fulltext("nonce2026", "Text", "pypdf")

    def test_papers_missing_fulltext_lists_only_candidates(self, temp_vault_db):
        db = VaultDB(temp_vault_db)
        db.add_paper("mit_pdf", CSL_WITHOUT_NONCE, pdf_path=str(NONCE_PDF))
        db.add_paper("ohne_pdf", CSL_WITHOUT_NONCE)
        db.add_paper("schon_da", CSL_WITHOUT_NONCE, pdf_path=str(NONCE_PDF))
        db.set_fulltext("schon_da", "bereits extrahiert", "pypdf")

        candidates = db.papers_missing_fulltext()
        assert [c["paper_id"] for c in candidates] == ["mit_pdf"]
        assert candidates[0]["pdf_path"] == str(NONCE_PDF)


# ---------------------------------------------------------------------------
# AC2 — Suche findet reine Volltext-Treffer
# ---------------------------------------------------------------------------


class TestSearchFindsFulltextOnlyTerm:
    def test_search_finds_term_only_in_fulltext(self, temp_vault_db):
        _add_paper_with_pdf(temp_vault_db)

        # Negativkontrolle: ohne Volltext-Index kein Treffer.
        assert search_papers(temp_vault_db, NONCE_TOKEN) == []

        text, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF), backend="pypdf")
        VaultDB(temp_vault_db).set_fulltext("nonce2026", text, extractor)

        hits = search_papers(temp_vault_db, NONCE_TOKEN)
        assert [h["paper_id"] for h in hits] == ["nonce2026"]

    def test_snippet_points_at_the_fulltext_hit(self, temp_vault_db):
        """Snippet muss die Fundstelle zeigen, nicht stumpf den Titel."""
        _add_paper_with_pdf(temp_vault_db)
        text, extractor = fulltext_mod.extract_fulltext(str(NONCE_PDF), backend="pypdf")
        VaultDB(temp_vault_db).set_fulltext("nonce2026", text, extractor)

        hits = search_papers(temp_vault_db, NONCE_TOKEN)
        assert f"<b>{NONCE_TOKEN}</b>" in hits[0]["snippet"]

    def test_title_search_still_works(self, temp_vault_db):
        """Regression: der Titel-Treffer darf durch die Umstellung nicht verschwinden."""
        _add_paper_with_pdf(temp_vault_db)
        hits = search_papers(temp_vault_db, "Schlagwort")
        assert [h["paper_id"] for h in hits] == ["nonce2026"]


# ---------------------------------------------------------------------------
# AC3 — Backfill-Migration
# ---------------------------------------------------------------------------


class TestBackfillMigration:
    def test_backfill_fills_existing_paper(self, temp_vault_db):
        _downgrade_to_legacy_schema(temp_vault_db)
        _add_paper_with_pdf(temp_vault_db)
        assert _fts_fulltext(temp_vault_db, "nonce2026") is None

        migrate.add_fulltext_support(temp_vault_db)
        result = migrate.backfill_fulltext(temp_vault_db)

        assert result["filled"] == 1
        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None and NONCE_TOKEN in stored

    def test_backfill_leaves_papers_and_quotes_untouched(self, temp_vault_db):
        _downgrade_to_legacy_schema(temp_vault_db)
        _add_paper_with_pdf(temp_vault_db)
        VaultDB(temp_vault_db).add_quote(
            quote_id="q1",
            paper_id="nonce2026",
            verbatim="Ein Zitat",
            extraction_method="manual",
        )

        def _snapshot():
            conn = sqlite3.connect(temp_vault_db)
            try:
                papers = conn.execute("SELECT * FROM papers ORDER BY paper_id").fetchall()
                quotes = conn.execute("SELECT * FROM quotes ORDER BY quote_id").fetchall()
            finally:
                conn.close()
            return papers, quotes

        before = _snapshot()
        migrate.add_fulltext_support(temp_vault_db)
        migrate.backfill_fulltext(temp_vault_db)
        assert _snapshot() == before

    def test_backfill_is_idempotent(self, temp_vault_db):
        _downgrade_to_legacy_schema(temp_vault_db)
        _add_paper_with_pdf(temp_vault_db)
        migrate.add_fulltext_support(temp_vault_db)

        first = migrate.backfill_fulltext(temp_vault_db)
        second = migrate.backfill_fulltext(temp_vault_db)

        assert first["filled"] == 1
        assert second["filled"] == 0
        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None and NONCE_TOKEN in stored

    def test_backfill_skips_paper_without_pdf(self, temp_vault_db):
        _downgrade_to_legacy_schema(temp_vault_db)
        VaultDB(temp_vault_db).add_paper("ohne_pdf", CSL_WITHOUT_NONCE)
        migrate.add_fulltext_support(temp_vault_db)

        result = migrate.backfill_fulltext(temp_vault_db)
        assert result["filled"] == 0
        assert VaultDB(temp_vault_db).get_fulltext("ohne_pdf") is None

    def test_backfill_counts_scan_pdf_as_skipped(self, temp_vault_db):
        _downgrade_to_legacy_schema(temp_vault_db)
        VaultDB(temp_vault_db).add_paper("scan", CSL_WITHOUT_NONCE, pdf_path=str(SCAN_PDF))
        migrate.add_fulltext_support(temp_vault_db)

        result = migrate.backfill_fulltext(temp_vault_db)
        assert result == {"filled": 0, "skipped": 1, "errors": 0}

    def test_backfill_counts_missing_file_as_error(self, temp_vault_db, tmp_path):
        _downgrade_to_legacy_schema(temp_vault_db)
        VaultDB(temp_vault_db).add_paper(
            "weg", CSL_WITHOUT_NONCE, pdf_path=str(tmp_path / "nicht_da.pdf")
        )
        migrate.add_fulltext_support(temp_vault_db)

        result = migrate.backfill_fulltext(temp_vault_db)
        assert result["errors"] == 1
        assert result["filled"] == 0

    def test_backfill_respects_limit(self, temp_vault_db):
        _downgrade_to_legacy_schema(temp_vault_db)
        db = VaultDB(temp_vault_db)
        db.add_paper("a", CSL_WITHOUT_NONCE, pdf_path=str(NONCE_PDF))
        db.add_paper("b", CSL_WITHOUT_NONCE, pdf_path=str(NONCE_PDF))
        migrate.add_fulltext_support(temp_vault_db)

        assert migrate.backfill_fulltext(temp_vault_db, limit=1)["filled"] == 1
        assert migrate.backfill_fulltext(temp_vault_db)["filled"] == 1

    def test_add_fulltext_support_is_idempotent(self, temp_vault_db):
        _downgrade_to_legacy_schema(temp_vault_db)
        migrate.add_fulltext_support(temp_vault_db)
        migrate.add_fulltext_support(temp_vault_db)

        _add_paper_with_pdf(temp_vault_db)
        VaultDB(temp_vault_db).set_fulltext("nonce2026", f"Text {NONCE_TOKEN}", "pypdf")
        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None and NONCE_TOKEN in stored

    def test_init_schema_upgrades_legacy_triggers(self, temp_vault_db):
        """Bestands-DBs: ``init_schema`` allein muss die alten Trigger ersetzen."""
        _downgrade_to_legacy_schema(temp_vault_db)
        VaultDB(temp_vault_db).init_schema()

        _add_paper_with_pdf(temp_vault_db)
        db = VaultDB(temp_vault_db)
        db.set_fulltext("nonce2026", f"Text {NONCE_TOKEN}", "pypdf")
        db.set_ocr_done("nonce2026", 1)

        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None and NONCE_TOKEN in stored


# ---------------------------------------------------------------------------
# Server-Anbindung (MCP-Tool vault.extract_fulltext)
# ---------------------------------------------------------------------------


class TestServerExtractFulltext:
    def test_extract_fulltext_for_paper_writes_index(self, temp_vault_db):
        _add_paper_with_pdf(temp_vault_db)

        result = extract_fulltext_for_paper(temp_vault_db, "nonce2026")

        assert result["extractor"] == "pypdf"
        assert result["chars"] > 0
        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None and NONCE_TOKEN in stored

    def test_extract_fulltext_for_paper_without_pdf_path(self, temp_vault_db):
        VaultDB(temp_vault_db).add_paper("ohne_pdf", CSL_WITHOUT_NONCE)
        with pytest.raises(ValueError, match="pdf_path"):
            extract_fulltext_for_paper(temp_vault_db, "ohne_pdf")

    def test_extract_fulltext_for_unknown_paper(self, temp_vault_db):
        with pytest.raises(ValueError, match="unbekannt"):
            extract_fulltext_for_paper(temp_vault_db, "gibt_es_nicht")


class TestAddPaperWiring:
    """``vault.add_paper`` zieht den Volltext direkt mit hoch (Schreibpfad).

    Ohne diese Verdrahtung bliebe ``papers_fts.fulltext`` in der
    Standardnutzung leer — der Index waere nur ueber einen manuellen
    Extra-Aufruf befuellbar.
    """

    def test_add_paper_indexes_fulltext(self, temp_vault_db):
        server_add_paper(temp_vault_db, "nonce2026", CSL_WITHOUT_NONCE, pdf_path=str(NONCE_PDF))

        stored = _fts_fulltext(temp_vault_db, "nonce2026")
        assert stored is not None and NONCE_TOKEN in stored
        assert search_papers(temp_vault_db, NONCE_TOKEN)[0]["paper_id"] == "nonce2026"

    def test_add_paper_fulltext_can_be_disabled(self, temp_vault_db, monkeypatch):
        monkeypatch.setenv("VAULT_AUTO_FULLTEXT", "0")
        server_add_paper(temp_vault_db, "nonce2026", CSL_WITHOUT_NONCE, pdf_path=str(NONCE_PDF))
        assert VaultDB(temp_vault_db).get_fulltext("nonce2026") is None

    def test_add_paper_does_not_reextract_existing_fulltext(self, temp_vault_db):
        _add_paper_with_pdf(temp_vault_db)
        VaultDB(temp_vault_db).set_fulltext("nonce2026", "Handgepflegter Text", "manual")

        server_add_paper(temp_vault_db, "nonce2026", CSL_WITHOUT_NONCE, pdf_path=str(NONCE_PDF))

        assert VaultDB(temp_vault_db).get_fulltext("nonce2026") == "Handgepflegter Text"

    def test_add_paper_survives_unreadable_pdf(self, temp_vault_db, tmp_path):
        """Ein fehlender PDF-Pfad darf den Upsert nicht scheitern lassen."""
        server_add_paper(
            temp_vault_db,
            "kaputt",
            CSL_WITHOUT_NONCE,
            pdf_path=str(tmp_path / "nicht_da.pdf"),
        )
        assert VaultDB(temp_vault_db).get_paper("kaputt") is not None
        assert VaultDB(temp_vault_db).get_fulltext("kaputt") is None
