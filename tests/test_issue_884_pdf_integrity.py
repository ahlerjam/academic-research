"""Regressionstests fuer Issue #884: Volltext-Integritaet erzwingen.

Eine HTML-Fehlerseite unter HTTP 200 darf auf keinem Beschaffungsweg als PDF
im Korpus landen. Deckt die Wege ab, die vor diesem Issue ungeprueft waren:

1. ``scripts.pdf.download_pdf`` (HTTP-Tier-Resolver) -- war teilweise
   geprueft (Magic-Bytes), aber ohne Mindestgroesse.
2. ``academic_vault.server.add_paper``/``update_pdf_path`` (Vault-Gate) --
   war komplett ungeprueft; schliesst zugleich die Wege ueber
   ``commands/fetch.md`` und manuelle/direkte Aufrufe.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

#: Neun Browser-use-Fetcher-Subagenten mit eigener Download-Selbstpruefung
#: (Issue #884 Plan). Vereinheitlicht auf die 2-KB-Schwelle von
#: ``scripts.pdf.MIN_PDF_SIZE`` -- vorher uneinheitlich (sechs auf "> 10 KB",
#: generic-fetcher auf "> 0 Bytes", scihub-fetcher ganz ohne Groessenpruefung).
UNIFIED_THRESHOLD_AGENTS = (
    "doabooks-fetcher",
    "hathitrust-fetcher",
    "internetarchive-fetcher",
    "kvk-fetcher",
    "mdz-fetcher",
    "oapen-fetcher",
    "tib-fetcher",
    "generic-fetcher",
)


class TestFetcherPromptsUnifiedThreshold:
    """Prompt-Selbstpruefung ist keine Durchsetzung (#627), aber die
    Vereinheitlichung auf 2 KB soll nicht unbemerkt wieder auseinanderlaufen."""

    @pytest.mark.parametrize("agent_name", UNIFIED_THRESHOLD_AGENTS)
    def test_agent_prompt_uses_2kb_threshold(self, agent_name):
        body = (AGENTS_DIR / f"{agent_name}.md").read_text(encoding="utf-8")
        assert "2 KB" in body, f"{agent_name}.md nennt nicht die vereinheitlichte 2-KB-Schwelle"
        assert "10 KB" not in body, f"{agent_name}.md haengt noch an der alten 10-KB-Schwelle"

    def test_scihub_fetcher_has_magic_byte_check(self):
        """Groesste Luecke im Repo vor #884: scihub-fetcher.md pruefte nur
        '> 0 Bytes', ganz ohne Magic-Byte-Pruefung."""
        body = (AGENTS_DIR / "scihub-fetcher.md").read_text(encoding="utf-8")
        assert "%PDF" in body
        assert "2 KB" in body


# ---------------------------------------------------------------------------
# scripts.pdf.is_valid_pdf_file
# ---------------------------------------------------------------------------


class TestIsValidPdfFile:
    def test_missing_file_is_valid(self, tmp_path):
        """Ein (noch) nicht heruntergeladenes PDF ist kein Verstoss."""
        import pdf as pdf_module

        assert pdf_module.is_valid_pdf_file(str(tmp_path / "nicht_da.pdf")) is True

    def test_real_pdf_magic_bytes_is_valid(self, tmp_path):
        import pdf as pdf_module

        path = tmp_path / "echt.pdf"
        path.write_bytes(b"%PDF-1.4\n%small but real header\n")

        assert pdf_module.is_valid_pdf_file(str(path)) is True

    def test_html_error_page_is_rejected(self, tmp_path):
        """Der Kernfall aus Issue #884: HTTP 200 mit HTML-Fehlerseite im Rumpf."""
        import pdf as pdf_module

        path = tmp_path / "faelschlich.pdf"
        path.write_bytes(b"<!DOCTYPE html><html><body>404 Not Found</body></html>")

        assert pdf_module.is_valid_pdf_file(str(path)) is False

    def test_empty_file_is_rejected(self, tmp_path):
        import pdf as pdf_module

        path = tmp_path / "leer.pdf"
        path.write_bytes(b"")

        assert pdf_module.is_valid_pdf_file(str(path)) is False

    def test_short_real_pdf_under_2kb_is_still_valid(self, tmp_path):
        """Bewusste Abweichung vom Plan (siehe PR-Beschreibung): die
        Mindestgroesse aus MIN_PDF_SIZE gilt nur fuer FRISCHE Downloads
        (``download_pdf``), nicht fuer bereits vorhandene lokale Dateien --
        reale kurze Fachtexte (z.B. Konferenz-Abstracts) und bestehende
        Test-Fixtures (z.B. tests/fixtures/tables/no_table.pdf, 914 Bytes)
        unterschreiten 2 KB legitim."""
        import pdf as pdf_module

        path = tmp_path / "kurz.pdf"
        path.write_bytes(b"%PDF-1.4\n" + b"x" * 100)
        assert os.path.getsize(path) < pdf_module.MIN_PDF_SIZE

        assert pdf_module.is_valid_pdf_file(str(path)) is True


# ---------------------------------------------------------------------------
# scripts.pdf.download_pdf
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeClient:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    def stream(self, method, url, timeout=None):
        return _FakeStreamResponse(self._chunks)


class TestDownloadPdfRejectsBadContent:
    def test_html_200_body_is_rejected_and_no_file_written(self, tmp_path):
        import pdf as pdf_module

        output_path = str(tmp_path / "out.pdf")
        client = _FakeClient([b"<html><body>404 Not Found</body></html>"])

        with pytest.raises(ValueError, match="Not a valid PDF"):
            pdf_module.download_pdf(client, "https://example.org/paper.pdf", output_path)

        assert not os.path.exists(output_path)

    def test_valid_header_but_too_small_is_rejected(self, tmp_path):
        """Abgebrochener/korrupter Download: gueltiger %PDF-Kopf, aber weit
        unter MIN_PDF_SIZE -- kein Volltext (Issue #884)."""
        import pdf as pdf_module

        output_path = str(tmp_path / "out.pdf")
        client = _FakeClient([b"%PDF-1.4\n" + b"x" * 50])

        with pytest.raises(ValueError, match="zu klein"):
            pdf_module.download_pdf(client, "https://example.org/paper.pdf", output_path)

        assert not os.path.exists(output_path)

    def test_valid_full_pdf_is_written(self, tmp_path):
        import pdf as pdf_module

        output_path = str(tmp_path / "out.pdf")
        body = b"%PDF-1.4\n" + b"x" * 3000
        client = _FakeClient([body])

        pdf_module.download_pdf(client, "https://example.org/paper.pdf", output_path)

        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) == len(body)


# ---------------------------------------------------------------------------
# academic_vault.server Vault-Gate (add_paper / update_pdf_path)
# ---------------------------------------------------------------------------


@pytest.fixture
def html_pdf_path(tmp_path):
    path = tmp_path / "html_fehlerseite.pdf"
    path.write_bytes(b"<!DOCTYPE html><html><body>404 Not Found</body></html>")
    return str(path)


@pytest.fixture
def real_pdf_path(tmp_path):
    path = tmp_path / "echt.pdf"
    path.write_bytes(b"%PDF-1.4\n%header\n")
    return str(path)


class TestAddPaperVaultGate:
    def test_html_pdf_path_is_rejected(self, tmp_path, html_pdf_path):
        from academic_vault.server import add_paper, get_paper

        db_path = str(tmp_path / "vault.db")
        with pytest.raises(ValueError, match="keine gueltige PDF-Datei"):
            add_paper(
                db_path=db_path,
                paper_id="p1",
                csl_json='{"type": "article-journal", "title": "T"}',
                pdf_path=html_pdf_path,
            )

        # Nichts wurde committet -- die Abweisung greift VOR dem DB-Write.
        assert get_paper(db_path, "p1") is None

    def test_valid_pdf_path_is_accepted(self, tmp_path, real_pdf_path):
        from academic_vault.server import add_paper, get_paper

        db_path = str(tmp_path / "vault.db")
        add_paper(
            db_path=db_path,
            paper_id="p2",
            csl_json='{"type": "article-journal", "title": "T"}',
            pdf_path=real_pdf_path,
        )

        paper = get_paper(db_path, "p2")
        assert paper is not None
        assert paper["pdf_path"] == real_pdf_path

    def test_missing_pdf_path_still_succeeds(self, tmp_path):
        """Regression: ein (noch) nicht heruntergeladener pdf_path bleibt
        unveraendert moeglich (Metadaten-only-Eintrag, ``pickup_required``)."""
        from academic_vault.server import add_paper, get_paper

        db_path = str(tmp_path / "vault.db")
        add_paper(
            db_path=db_path,
            paper_id="p3",
            csl_json='{"type": "article-journal", "title": "T"}',
            pdf_path=str(tmp_path / "kommt-noch.pdf"),
        )

        assert get_paper(db_path, "p3") is not None

    def test_no_pdf_path_at_all_still_succeeds(self, tmp_path):
        from academic_vault.server import add_paper, get_paper

        db_path = str(tmp_path / "vault.db")
        add_paper(
            db_path=db_path,
            paper_id="p4",
            csl_json='{"type": "article-journal", "title": "T"}',
        )

        assert get_paper(db_path, "p4") is not None


class TestUpdatePdfPathVaultGate:
    def test_html_new_path_is_rejected(self, tmp_path, html_pdf_path):
        from academic_vault.server import add_paper, update_pdf_path

        db_path = str(tmp_path / "vault.db")
        add_paper(
            db_path=db_path,
            paper_id="p5",
            csl_json='{"type": "article-journal", "title": "T"}',
        )

        with pytest.raises(ValueError, match="keine gueltige PDF-Datei"):
            update_pdf_path(db_path, "p5", html_pdf_path)

    def test_valid_new_path_is_accepted(self, tmp_path, real_pdf_path):
        from academic_vault.server import add_paper, get_paper, update_pdf_path

        db_path = str(tmp_path / "vault.db")
        add_paper(
            db_path=db_path,
            paper_id="p6",
            csl_json='{"type": "article-journal", "title": "T"}',
        )
        update_pdf_path(db_path, "p6", real_pdf_path)

        assert get_paper(db_path, "p6")["pdf_path"] == real_pdf_path

    def test_missing_new_path_still_succeeds(self, tmp_path):
        """Regression: bestehendes Verhalten fuer noch nicht existierende
        Pfade (z.B. skills/book-handler/SKILL.md OCR-Nachtrag) bleibt."""
        from academic_vault.server import add_paper, update_pdf_path

        db_path = str(tmp_path / "vault.db")
        add_paper(
            db_path=db_path,
            paper_id="p7",
            csl_json='{"type": "article-journal", "title": "T"}',
        )
        update_pdf_path(db_path, "p7", str(tmp_path / "spaeter.pdf"))
