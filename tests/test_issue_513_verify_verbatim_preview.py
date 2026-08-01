"""Tests fuer die read-only Vorschau ``vault.verify_verbatim`` (Issue #513).

``verify_verbatim_preview()`` teilt sich den Paper-/pdf_path-Aufloesungspfad
mit dem Schreib-Gate ``_verify_local_verbatim()`` (#512), unterscheidet sich
aber genau darin: Status ``no-match``/``no-textlayer`` werfen HIER keine
Exception, sondern kommen als Ergebnis-dict zurueck -- die Funktion ist eine
reine Vorschau ohne jeden Schreibzugriff.

AC -> Testfall (siehe Issue #513 / Plan-Kommentar):
  - AC1 alle vier Status + ggf. Snap-Text/Seite: :class:`TestAc1StatusResult`
  - AC2 Tool schreibt nachweislich nichts: :class:`TestAc2NoWrite`
  - AC3 Paper ohne pdf_path -> verstaendliche Fehlermeldung: :class:`TestAc3ErrorMessages`

Fixtures: ``tests/fixtures/verbatim/`` (aus #511/#512, kein neues Fixture noetig).
"""

import hashlib
import os
import sqlite3

import pytest
from academic_vault.db import VaultDB
from academic_vault.server import verify_verbatim_preview

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "verbatim")
SOURCE_PDF = os.path.join(FIXTURES, "verbatim_source.pdf")
SCAN_PDF = os.path.join(FIXTURES, "scan_no_text.pdf")

_PAPER_ID = "verbatim-fixture"
_CSL = '{"title": "Vault Verbatim Fixture"}'

# Wortlaute aus tests/fixtures/verbatim/create_fixtures.py (identisch zu
# tests/test_issue_512_local_verbatim.py):
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


def _sha256(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _vault_with_paper(tmp_path, pdf_path: str | None) -> str:
    """Frischer, bereits ``init_schema()``-initialisierter Vault mit einem Paper.

    Bewusst analog zu ``tests/test_issue_512_local_verbatim.py``: ``init_schema()``
    VOR dem Preview-Aufruf, damit ``get_paper()`` -> ``_ensure_schema_for_read()``
    keine Tabellen mehr anlegen muss und der No-Write-Beweis (AC2) nicht
    faelschlich auf Schema-DDL statt Nutzdaten-Schreiben anspringt.
    """
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(_PAPER_ID, _CSL, pdf_path=pdf_path)
    return db_path


class TestAc1StatusResult:
    """AC1: exact/snapped/no-match/no-textlayer + ggf. Snap-Text und Seite."""

    def test_exact_match_returns_status_verbatim_and_page(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        result = verify_verbatim_preview(db_path, _PAPER_ID, CANDIDATE_EXACT_PAGE2)

        assert result["status"] == "exact"
        assert result["pdf_page"] == 2
        assert result["verbatim"]
        assert "implizites Wissen" in result["verbatim"]
        assert result["ratio"] == 1.0

    def test_snapped_returns_snap_suggestion_and_page(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        result = verify_verbatim_preview(db_path, _PAPER_ID, CANDIDATE_TYPO_PAGE1)

        assert result["status"] == "snapped"
        assert result["pdf_page"] == 1
        assert "betonte" in result["verbatim"]
        assert "betonto" not in result["verbatim"]
        assert 0.0 < result["ratio"] < 1.0

    def test_no_match_returns_status_without_page(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        result = verify_verbatim_preview(db_path, _PAPER_ID, CANDIDATE_UNRELATED)

        assert result["status"] == "no-match"
        assert result["pdf_page"] is None
        assert result["verbatim"] == ""

    def test_no_textlayer_returns_status(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SCAN_PDF)

        result = verify_verbatim_preview(db_path, _PAPER_ID, "Ein beliebiger Kandidat.")

        assert result["status"] == "no-textlayer"
        assert result["pdf_page"] is None
        assert result["verbatim"] == ""

    def test_result_keys_are_exactly_the_documented_four(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        result = verify_verbatim_preview(db_path, _PAPER_ID, CANDIDATE_EXACT_PAGE2)

        assert set(result.keys()) == {"status", "verbatim", "pdf_page", "ratio"}


class TestAc2NoWrite:
    """AC2: das Tool schreibt nachweislich nichts in die DB."""

    @pytest.mark.parametrize(
        "pdf_path,candidate",
        [
            (SOURCE_PDF, CANDIDATE_EXACT_PAGE2),
            (SOURCE_PDF, CANDIDATE_TYPO_PAGE1),
            (SOURCE_PDF, CANDIDATE_UNRELATED),
            (SCAN_PDF, "Ein beliebiger Kandidat."),
        ],
        ids=["exact", "snapped", "no-match", "no-textlayer"],
    )
    def test_db_file_byte_identical_after_preview_call(self, tmp_path, pdf_path, candidate):
        db_path = _vault_with_paper(tmp_path, pdf_path)
        before = _sha256(db_path)

        result = verify_verbatim_preview(db_path, _PAPER_ID, candidate)

        after = _sha256(db_path)
        assert after == before
        assert _quote_count(db_path) == 0
        assert result["status"] in ("exact", "snapped", "no-match", "no-textlayer")

    def test_monkeypatch_control_preview_calls_verifier(self, tmp_path, monkeypatch):
        """Positivkontrolle: beweist, dass der Preview-Pfad tatsaechlich
        ``verbatim.verify_verbatim`` aufruft -- kein stiller No-Op, der die
        No-Write-Tests oben wertlos machen wuerde."""
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)
        called = {}

        def _fake_verify_verbatim(pdf_path, candidate):
            called["pdf_path"] = pdf_path
            called["candidate"] = candidate
            raise AssertionError("Kontrollpunkt erreicht")

        monkeypatch.setattr("academic_vault.verbatim.verify_verbatim", _fake_verify_verbatim)

        with pytest.raises(AssertionError, match="Kontrollpunkt erreicht"):
            verify_verbatim_preview(db_path, _PAPER_ID, CANDIDATE_EXACT_PAGE2)

        assert called["pdf_path"] == SOURCE_PDF
        assert called["candidate"] == CANDIDATE_EXACT_PAGE2


class TestAc3ErrorMessages:
    """AC3: Paper ohne pdf_path -> verstaendliche ValueError statt Traceback."""

    def test_missing_pdf_path_raises_value_error(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, None)

        with pytest.raises(ValueError, match="pdf_path"):
            verify_verbatim_preview(db_path, _PAPER_ID, CANDIDATE_EXACT_PAGE2)

        assert _quote_count(db_path) == 0

    def test_unknown_paper_raises_value_error(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        with pytest.raises(ValueError, match="nicht gefunden"):
            verify_verbatim_preview(db_path, "gibt-es-nicht", CANDIDATE_EXACT_PAGE2)

    def test_nonexistent_pdf_file_raises_value_error(self, tmp_path):
        db_path = _vault_with_paper(tmp_path, str(tmp_path / "weg.pdf"))

        with pytest.raises(ValueError, match="existiert nicht"):
            verify_verbatim_preview(db_path, _PAPER_ID, CANDIDATE_EXACT_PAGE2)
