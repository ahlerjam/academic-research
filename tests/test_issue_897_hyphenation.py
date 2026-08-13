"""Tests fuer Issue #897 — Silbentrennung am Zeilenumbruch aufloesen.

``normalize_whitespace()`` kollabierte bislang jede Whitespace-Folge (inkl.
``\\n``) sofort zu einem einzelnen Leerzeichen, bevor eine Trennung am
Zeilenumbruch erkannt werden konnte: ``"In-\\nequality"`` wurde so zu
``"In- equality"`` statt ``"Inequality"``. Ein so entstandenes Zitat besteht
``vault_verify_verbatim``, weil es wortgetreu gegen genau diesen (defekten)
Text prueft — der Fehler unterlaeuft die Schutzschicht statt an ihr zu
scheitern.

Abdeckung:
  AC1  Die vier belegten Faelle aus dem Lauf werden zusammengefuehrt.
  AC2  Echte Bindestriche (nicht am Zeilenumbruch) bleiben unveraendert.
  AC3  Ein bereits im Vault liegender betroffener Volltext laesst sich
       nachtraeglich per Massen-Nachlauf korrigieren.
  AC4  Ein woertliches Zitat ueber einen simulierten Zeilenumbruch hinweg ist
       im extrahierten Volltext auffindbar (FTS5), ohne Nachbearbeitung.
  AC5  Die Entscheidungsregel fuer nicht eindeutige Faelle (Grossschreibung
       nach dem Umbruch, Absatzumbruch, Ziffern-Bindestrich) ist hier als
       Regressionstest festgeschrieben.
"""

import sqlite3
from pathlib import Path

import pytest
from academic_vault import fulltext as fulltext_mod
from academic_vault import migrate
from academic_vault.db import VaultDB

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fulltext"
HYPHENATION_PDF = FIXTURE_DIR / "hyphenation_897.pdf"

CSL_MINIMAL = (
    '{"type": "article-journal", "title": "Ohne Bezug zum Testtext", "abstract": "Kein Bezug."}'
)


def _fts_fulltext(db_path: str, paper_id: str):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT fulltext FROM papers_fts WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


# ---------------------------------------------------------------------------
# AC1 + AC2 + AC5 — Regex-Ebene auf _merge_hyphenation()/normalize_whitespace()
# ---------------------------------------------------------------------------


class TestMergeHyphenation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("In-\nequality", "Inequality"),
            ("individ-\nual", "individual"),
            ("consul-\ntancy", "consultancy"),
            ("reproducibil-\nity", "reproducibility"),
            ("compu-\ntation", "computation"),
        ],
    )
    def test_documented_cases_are_merged(self, raw, expected):
        """AC1: die vier Belegfaelle aus dem Issue plus 'compu- tation'."""
        assert fulltext_mod.normalize_whitespace(raw) == expected

    def test_real_hyphen_without_linebreak_is_preserved(self):
        """AC2: 'Multi-Agent' ohne Zeilenumbruch bleibt unangetastet."""
        assert fulltext_mod.normalize_whitespace("Multi-Agent") == "Multi-Agent"

    def test_real_hyphen_with_slash_is_preserved(self):
        """AC2: 'Ein-/Ausschluss' ohne Zeilenumbruch bleibt unangetastet."""
        assert fulltext_mod.normalize_whitespace("Ein-/Ausschluss") == "Ein-/Ausschluss"

    def test_uppercase_continuation_is_not_merged(self):
        """AC5: Grossschreibung nach dem Umbruch gilt als Satzanfang/Eigenname."""
        result = fulltext_mod.normalize_whitespace("Multi-\nAgent System")
        assert result == "Multi- Agent System"

    def test_paragraph_break_is_not_merged(self):
        """AC5: ein Absatzumbruch (doppeltes \\n) ist keine Silbentrennung."""
        result = fulltext_mod.normalize_whitespace("Ende des Satzes-\n\nneuer Absatz")
        assert result == "Ende des Satzes- neuer Absatz"

    def test_digit_range_hyphen_is_not_merged(self):
        """AC5: Bereichs-Bindestrich zwischen Ziffern ist kein Silbentrennstrich."""
        result = fulltext_mod.normalize_whitespace("2020 -\n2021")
        assert result == "2020 - 2021"

    def test_whitespace_around_hyphen_and_break_is_handled(self):
        """Leerraum vor/nach dem Bindestrich bzw. Umbruch stoert die Erkennung nicht."""
        result = fulltext_mod.normalize_whitespace("In-  \n  equality")
        assert result == "Inequality"


# ---------------------------------------------------------------------------
# AC4 — Integrationstest ueber extract_pypdf() auf der Fixture
# ---------------------------------------------------------------------------


class TestExtractionMergesHyphenation:
    def test_extract_pypdf_merges_hyphenated_word_from_pdf(self):
        text, extractor = fulltext_mod.extract_fulltext(str(HYPHENATION_PDF), backend="pypdf")
        assert extractor == "pypdf"
        assert "Inequality" in text
        assert "In- equality" not in text
        assert "In-equality" not in text

    def test_extract_pypdf_preserves_real_hyphen_from_pdf(self):
        text, _ = fulltext_mod.extract_fulltext(str(HYPHENATION_PDF), backend="pypdf")
        assert "Multi-Agent" in text


class TestQuoteFindableAcrossSimulatedLinebreak:
    def test_literal_quote_across_linebreak_is_searchable_without_postprocessing(
        self, temp_vault_db
    ):
        """AC4: ein woertliches Zitat ueber den Umbruch hinweg ist per FTS5 auffindbar."""
        db = VaultDB(temp_vault_db)
        db.add_paper("hyph897", CSL_MINIMAL, pdf_path=str(HYPHENATION_PDF))
        text, extractor = fulltext_mod.extract_fulltext(str(HYPHENATION_PDF), backend="pypdf")
        db.set_fulltext("hyph897", text, extractor)

        conn = sqlite3.connect(temp_vault_db)
        try:
            hits = conn.execute(
                "SELECT paper_id FROM papers_fts WHERE papers_fts MATCH ?",
                ("fulltext:Inequality",),
            ).fetchall()
        finally:
            conn.close()
        assert [h[0] for h in hits] == ["hyph897"]


# ---------------------------------------------------------------------------
# AC3 — Nachtraeglicher Massen-Nachlauf ueber bereits im Vault liegende Texte
# ---------------------------------------------------------------------------


class TestReextractFulltext:
    def test_reextract_fixes_already_stored_broken_fulltext(self, temp_vault_db):
        db = VaultDB(temp_vault_db)
        db.add_paper("hyph897", CSL_MINIMAL, pdf_path=str(HYPHENATION_PDF))
        # Simuliert den Bestand vor dem Fix: bereits mit der Trennung gespeichert.
        db.set_fulltext("hyph897", "Text mit In- equality Artefakt", "pypdf")
        assert db.get_fulltext("hyph897") == "Text mit In- equality Artefakt"

        result = migrate.reextract_fulltext(temp_vault_db)

        assert result["fixed"] == 1
        stored = db.get_fulltext("hyph897")
        assert stored is not None
        assert "Inequality" in stored

    def test_reextract_leaves_papers_and_quotes_untouched(self, temp_vault_db):
        db = VaultDB(temp_vault_db)
        db.add_paper("hyph897", CSL_MINIMAL, pdf_path=str(HYPHENATION_PDF))
        db.set_fulltext("hyph897", "Text mit In- equality Artefakt", "pypdf")
        db.add_quote(
            quote_id="q1",
            paper_id="hyph897",
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
        migrate.reextract_fulltext(temp_vault_db)
        assert _snapshot() == before

    def test_reextract_skips_paper_without_pdf(self, temp_vault_db):
        db = VaultDB(temp_vault_db)
        db.add_paper("ohne_pdf", CSL_MINIMAL)
        result = migrate.reextract_fulltext(temp_vault_db)
        assert result["fixed"] == 0

    def test_reextract_skips_paper_without_existing_fulltext(self, temp_vault_db):
        """Nur Paper MIT vorhandener paper_fulltext-Zeile sind Kandidaten (siehe backfill_fulltext)."""
        db = VaultDB(temp_vault_db)
        db.add_paper("hyph897", CSL_MINIMAL, pdf_path=str(HYPHENATION_PDF))
        result = migrate.reextract_fulltext(temp_vault_db)
        assert result["fixed"] == 0
        assert db.get_fulltext("hyph897") is None

    def test_reextract_is_idempotent(self, temp_vault_db):
        db = VaultDB(temp_vault_db)
        db.add_paper("hyph897", CSL_MINIMAL, pdf_path=str(HYPHENATION_PDF))
        db.set_fulltext("hyph897", "Text mit In- equality Artefakt", "pypdf")

        first = migrate.reextract_fulltext(temp_vault_db)
        second = migrate.reextract_fulltext(temp_vault_db)

        assert first["fixed"] == 1
        assert second["fixed"] == 1  # ueberschreibt erneut mit demselben Ergebnis
        assert "Inequality" in db.get_fulltext("hyph897")

    def test_reextract_respects_limit(self, temp_vault_db):
        db = VaultDB(temp_vault_db)
        db.add_paper("a", CSL_MINIMAL, pdf_path=str(HYPHENATION_PDF))
        db.add_paper("b", CSL_MINIMAL, pdf_path=str(HYPHENATION_PDF))
        db.set_fulltext("a", "Text mit In- equality Artefakt", "pypdf")
        db.set_fulltext("b", "Text mit In- equality Artefakt", "pypdf")

        result = migrate.reextract_fulltext(temp_vault_db, limit=1)
        assert result["fixed"] == 1
