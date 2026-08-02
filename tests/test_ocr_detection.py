"""Tests fuer OCR-Detection und ocrmypdf-Workflow."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ocr import OcrTimeoutError, run_ocrmypdf

# scripts/ im Suchpfad


# ---------------------------------------------------------------------------
# detect_needs_ocr
# ---------------------------------------------------------------------------


class TestDetectNeedsOcr:
    """Tests fuer scripts.pdf.detect_needs_ocr."""

    def test_text_pdf_returns_false(self):
        """PDF mit viel Text → False (kein OCR noetig)."""
        from pdf import detect_needs_ocr

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 200  # 200 Zeichen pro Seite

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page] * 10

        with patch("pdf.PdfReader", return_value=mock_reader):
            result = detect_needs_ocr("dummy.pdf")

        assert result is False

    def test_scan_pdf_returns_true(self):
        """PDF ohne Text-Layer → True (OCR benoetigt)."""
        from pdf import detect_needs_ocr

        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""  # kein Text

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page] * 10

        with patch("pdf.PdfReader", return_value=mock_reader):
            result = detect_needs_ocr("dummy.pdf")

        assert result is True

    def test_mixed_pdf_returns_true(self):
        """Mischung: wenige Seiten mit Text, viele leer → True (Durchschnitt < 100)."""
        from pdf import detect_needs_ocr

        pages = []
        # 2 Seiten mit etwas Text (50 Zeichen), 8 Seiten leer
        # Durchschnitt aus 5 Stichproben-Seiten wird < 100
        for _ in range(2):
            p = MagicMock()
            p.extract_text.return_value = "A" * 50
            pages.append(p)
        for _ in range(8):
            p = MagicMock()
            p.extract_text.return_value = ""
            pages.append(p)

        mock_reader = MagicMock()
        mock_reader.pages = pages

        with patch("pdf.PdfReader", return_value=mock_reader):
            with patch("random.sample", return_value=[2, 4, 6, 7, 9]):
                result = detect_needs_ocr("dummy.pdf", sample_pages=5, threshold=100)

        assert result is True

    def test_empty_pdf_returns_true(self):
        """PDF ohne Seiten → True."""
        from pdf import detect_needs_ocr

        mock_reader = MagicMock()
        mock_reader.pages = []

        with patch("pdf.PdfReader", return_value=mock_reader):
            result = detect_needs_ocr("dummy.pdf")

        assert result is True

    def test_sample_pages_capped_at_total(self):
        """Wenn sample_pages > Gesamtseiten, werden alle Seiten benutzt."""
        from pdf import detect_needs_ocr

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "A" * 50  # unter threshold

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page] * 3  # nur 3 Seiten

        with patch("pdf.PdfReader", return_value=mock_reader):
            # sample_pages=10 > 3 Seiten — soll nicht crashen
            result = detect_needs_ocr("dummy.pdf", sample_pages=10, threshold=100)

        assert result is True  # 50 < 100


# ---------------------------------------------------------------------------
# run_ocrmypdf
# ---------------------------------------------------------------------------


class TestRunOcrmypdf:
    """Tests fuer scripts.ocr.run_ocrmypdf."""

    def test_ocrmypdf_not_found_raises_runtime_error(self):
        """subprocess.which gibt None → RuntimeError mit Install-Hinweis."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="ocrmypdf nicht gefunden"):
                run_ocrmypdf("input.pdf", "output.pdf")

    def test_ocrmypdf_success(self):
        """Erfolgreicher Aufruf — kein Fehler."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                run_ocrmypdf("input.pdf", "output.pdf")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "ocrmypdf" in call_args[0]
        assert "input.pdf" in call_args
        assert "output.pdf" in call_args

    def test_ocrmypdf_failure_raises_runtime_error(self):
        """Prozess endet mit Exit-Code != 0 → RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"OCR failed"

        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(RuntimeError, match="ocrmypdf"):
                    run_ocrmypdf("input.pdf", "output.pdf")

    def test_ocrmypdf_default_lang_is_deu_plus_eng(self, monkeypatch):
        """Ohne Parameter/Env → '-l deu+eng' im Aufruf (Issue #594)."""
        monkeypatch.delenv("ACADEMIC_RESEARCH_OCR_LANG", raising=False)
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                run_ocrmypdf("input.pdf", "output.pdf")

        call_args = mock_run.call_args[0][0]
        assert "-l" in call_args
        assert call_args[call_args.index("-l") + 1] == "deu+eng"

    def test_ocrmypdf_lang_param_overrides_default(self, monkeypatch):
        """lang-Parameter uebersteuert den Default."""
        monkeypatch.delenv("ACADEMIC_RESEARCH_OCR_LANG", raising=False)
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                run_ocrmypdf("input.pdf", "output.pdf", lang="eng")

        call_args = mock_run.call_args[0][0]
        assert call_args[call_args.index("-l") + 1] == "eng"

    def test_ocrmypdf_lang_env_overrides_default(self, monkeypatch):
        """Env ACADEMIC_RESEARCH_OCR_LANG uebersteuert den Default, wenn kein
        Parameter gesetzt ist."""
        monkeypatch.setenv("ACADEMIC_RESEARCH_OCR_LANG", "fra")
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                run_ocrmypdf("input.pdf", "output.pdf")

        call_args = mock_run.call_args[0][0]
        assert call_args[call_args.index("-l") + 1] == "fra"

    def test_ocrmypdf_timeout_raises_distinct_error(self):
        """Zeitlimit-Ueberschreitung -> OcrTimeoutError, unterscheidbar vom
        inhaltlichen Fehlschlag (RuntimeError, aber nicht OcrTimeoutError).
        Kein echter Langlaeufer: subprocess.run wird per side_effect gemockt."""
        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["ocrmypdf"], timeout=5),
            ):
                with pytest.raises(OcrTimeoutError, match="Zeitlimit"):
                    run_ocrmypdf("input.pdf", "output.pdf", timeout=5)

    def test_ocrmypdf_timeout_error_is_runtime_error_subclass(self):
        """OcrTimeoutError ist ein RuntimeError (Abwaertskompatibilitaet zu
        bestehenden ``except RuntimeError``-Stellen)."""
        assert issubclass(OcrTimeoutError, RuntimeError)

    def test_ocrmypdf_missing_language_package_names_install_path(self):
        """Exit-Code 3 (missing_dependency) mit sprachbezogenem stderr ->
        Fehlermeldung nennt Paketname und Installationsweg statt der
        generischen Meldung."""
        mock_result = MagicMock()
        mock_result.returncode = 3
        mock_result.stderr = b"Error: deu.traineddata not installed"

        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(RuntimeError) as exc_info:
                    run_ocrmypdf("input.pdf", "output.pdf", lang="deu+eng")

        message = str(exc_info.value)
        assert "tesseract-ocr-deu" in message
        assert "brew install tesseract-lang" in message
        assert "apt-get install" in message

    def test_ocrmypdf_exit_3_without_language_hint_uses_generic_message(self):
        """Exit-Code 3 (missing_dependency) OHNE sprachbezogenen stderr-Hinweis
        (z. B. fehlendes Ghostscript) -> generische Fehlermeldung statt einer
        irrefuehrenden Sprachpaket-Diagnose (Review-Finding, PR #613)."""
        mock_result = MagicMock()
        mock_result.returncode = 3
        mock_result.stderr = b"Error: gs (Ghostscript) not found in PATH"

        with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(RuntimeError) as exc_info:
                    run_ocrmypdf("input.pdf", "output.pdf", lang="deu+eng")

        message = str(exc_info.value)
        assert "tesseract-ocr-deu" not in message
        assert "brew install tesseract-lang" not in message
        assert "Ghostscript" in message
        assert "ocrmypdf fehlgeschlagen" in message

    def test_ocrmypdf_invalid_timeout_env_logs_warning_and_falls_back(self, monkeypatch, caplog):
        """Ungueltiger ACADEMIC_RESEARCH_OCR_TIMEOUT (nicht-numerisch oder
        <= 0) wird nicht still verworfen, sondern geloggt, bevor auf die
        Seitenzahl-Schaetzung zurueckgefallen wird (Review-Finding, PR #613)."""
        monkeypatch.setenv("ACADEMIC_RESEARCH_OCR_TIMEOUT", "2h")
        mock_result = MagicMock()
        mock_result.returncode = 0

        with caplog.at_level("WARNING"):
            with patch("shutil.which", return_value="/usr/local/bin/ocrmypdf"):
                with patch("pypdf.PdfReader", side_effect=Exception("n/a")):
                    with patch("subprocess.run", return_value=mock_result):
                        run_ocrmypdf("input.pdf", "output.pdf")

        assert any("ACADEMIC_RESEARCH_OCR_TIMEOUT" in r.message for r in caplog.records)
        assert any("2h" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Vault-Setter
# ---------------------------------------------------------------------------


class TestVaultOcrSetters:
    """Tests fuer set_ocr_done und update_pdf_path in Vault."""

    @pytest.fixture
    def tmp_db(self, tmp_path):
        db_file = str(tmp_path / "vault.db")
        from academic_vault.db import VaultDB

        db = VaultDB(db_file)
        db.init_schema()
        db.add_paper(
            paper_id="test-paper-ocr",
            csl_json='{"type":"book","title":"Scan Test"}',
            pdf_path="/tmp/scan.pdf",
        )
        return db_file

    def test_set_ocr_done(self, tmp_db):
        """set_ocr_done setzt ocr_done=1 im Vault."""
        from academic_vault.server import get_paper, set_ocr_done

        set_ocr_done(tmp_db, "test-paper-ocr")
        paper = get_paper(tmp_db, "test-paper-ocr")

        assert paper is not None
        assert paper["ocr_done"] == 1

    def test_update_pdf_path(self, tmp_db):
        """update_pdf_path aktualisiert pdf_path im Vault."""
        from academic_vault.server import get_paper, update_pdf_path

        update_pdf_path(tmp_db, "test-paper-ocr", "/tmp/scan_ocr.pdf")
        paper = get_paper(tmp_db, "test-paper-ocr")

        assert paper is not None
        assert paper["pdf_path"] == "/tmp/scan_ocr.pdf"
