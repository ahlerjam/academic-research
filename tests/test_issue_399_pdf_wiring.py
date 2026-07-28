"""Regressionstests fuer Issue #399, Scope-"In": Verdrahtung von
arxiv_latex.fetch_arxiv_latex_source() als Alternative zur PDF-Extraktion
in scripts/pdf.py, wenn ein Paper eine arXiv-ID hat.

Vor dieser Datei war `fetch_arxiv_latex_source` ausser in
tests/test_issue_399_arxiv_latex.py nirgends im Repo referenziert
(critic-Review PR #435, scripts/arxiv_latex.py:126) -- das Feature war
praktisch nur ueber den manuellen CLI-Einstieg erreichbar. Diese Tests
decken die Verdrahtung ab:

  - pdf.extract_text_for_paper(pdf_path, doi): bevorzugt die arXiv-LaTeX-
    Quelle, wenn `doi` auf eine arXiv-ID verweist, sonst PDF-Extraktion.
  - pdf.action_extract(..., pdf_status_path=...): nutzt das von
    action_resolve erzeugte pdf_status.json, um pro PDF-Datei die zugehoerige
    DOI nachzuschlagen und darueber die LaTeX-Alternative zu aktivieren.

Bewusst NICHT veraendert (Out-Scope #399, "bestehende PDF-Extraktions-
Pipeline fuer Nicht-arXiv-Quellen"): ohne `pdf_status_path` (wie im
bisherigen CLI-Aufruf `--action extract --pdf-dir ... --output ...` ohne
weitere Flags) ist das Verhalten von action_extract identisch zum
Vorher-Stand -- siehe test_action_extract_without_pdf_status_is_unchanged.
"""

from __future__ import annotations

import json

import pdf


def test_arxiv_id_from_doi_is_reexported_via_arxiv_latex():
    """Baustein-Sanity: pdf.py muss dieselbe Erkennung nutzen wie
    arxiv_latex.arxiv_id_from_doi (keine zweite, abweichende Implementierung)."""
    import arxiv_latex

    assert pdf.arxiv_latex.arxiv_id_from_doi is arxiv_latex.arxiv_id_from_doi


def test_extract_text_for_paper_prefers_latex_source_for_arxiv_doi(monkeypatch):
    """Bekannte arXiv-DOI -> LaTeX-Quelle wird verwendet, PDF-Extraktion NICHT
    aufgerufen (Formeltreue, #399 Kernnutzen)."""
    marker = "\\begin{equation} E = mc^2 \\end{equation}"

    def fake_fetch(arxiv_id: str) -> str | None:
        assert arxiv_id == "2301.12345"
        return marker

    def fail_if_called(pdf_path: str) -> str:
        raise AssertionError("extract_text_from_pdf haette NICHT aufgerufen werden duerfen")

    monkeypatch.setattr(pdf.arxiv_latex, "fetch_arxiv_latex_source", fake_fetch)
    monkeypatch.setattr(pdf, "extract_text_from_pdf", fail_if_called)

    result = pdf.extract_text_for_paper("irrelevant.pdf", doi="10.48550/arxiv.2301.12345")

    assert result == marker


def test_extract_text_for_paper_falls_back_to_pdf_when_doi_not_arxiv(monkeypatch):
    """Nicht-arXiv-DOI -> unveraenderte PDF-Extraktion (Out-Scope #399)."""

    def fail_if_called(arxiv_id: str) -> str | None:
        raise AssertionError("fetch_arxiv_latex_source haette NICHT aufgerufen werden duerfen")

    def fake_pdf_extract(pdf_path: str) -> str:
        return f"pdf-text:{pdf_path}"

    monkeypatch.setattr(pdf.arxiv_latex, "fetch_arxiv_latex_source", fail_if_called)
    monkeypatch.setattr(pdf, "extract_text_from_pdf", fake_pdf_extract)

    result = pdf.extract_text_for_paper("paper.pdf", doi="10.1016/j.example.2024.01.001")

    assert result == "pdf-text:paper.pdf"


def test_extract_text_for_paper_falls_back_to_pdf_when_doi_is_none(monkeypatch):
    """Fehlende DOI (haeufig bei Nicht-arXiv-Quellen) -> PDF-Extraktion,
    kein Absturz."""

    def fail_if_called(arxiv_id: str) -> str | None:
        raise AssertionError("fetch_arxiv_latex_source haette NICHT aufgerufen werden duerfen")

    def fake_pdf_extract(pdf_path: str) -> str:
        return f"pdf-text:{pdf_path}"

    monkeypatch.setattr(pdf.arxiv_latex, "fetch_arxiv_latex_source", fail_if_called)
    monkeypatch.setattr(pdf, "extract_text_from_pdf", fake_pdf_extract)

    result = pdf.extract_text_for_paper("paper.pdf", doi=None)

    assert result == "pdf-text:paper.pdf"


def test_extract_text_for_paper_falls_back_to_pdf_when_latex_unavailable(monkeypatch):
    """arXiv-DOI, aber keine LaTeX-Quelle verfuegbar (PDF-only-Submission)
    -> Fallback auf PDF-Extraktion statt None weiterzureichen."""

    def fake_fetch(arxiv_id: str) -> str | None:
        return None

    def fake_pdf_extract(pdf_path: str) -> str:
        return f"pdf-text:{pdf_path}"

    monkeypatch.setattr(pdf.arxiv_latex, "fetch_arxiv_latex_source", fake_fetch)
    monkeypatch.setattr(pdf, "extract_text_from_pdf", fake_pdf_extract)

    result = pdf.extract_text_for_paper("paper.pdf", doi="10.48550/arxiv.2301.12345")

    assert result == "pdf-text:paper.pdf"


def test_extract_text_for_paper_falls_back_to_pdf_when_latex_source_is_empty_string(monkeypatch):
    """arXiv-DOI, aber fetch_arxiv_latex_source() liefert "" (z. B. Tarball mit
    ausschliesslich 0-Byte-.tex-Dateien, siehe arxiv_latex._pick_main_tex()'s
    Groessen-Fallback) -> Fallback auf PDF-Extraktion, NICHT der leere String
    (P1-Finding pr-deep-review PR #435: `is not None` wertete "" faelschlich
    als Erfolg und unterdrueckte den Fallback -- leerer Papertext trotz
    vorhandenem PDF)."""

    def fake_fetch(arxiv_id: str) -> str | None:
        return ""

    def fake_pdf_extract(pdf_path: str) -> str:
        return f"pdf-text:{pdf_path}"

    monkeypatch.setattr(pdf.arxiv_latex, "fetch_arxiv_latex_source", fake_fetch)
    monkeypatch.setattr(pdf, "extract_text_from_pdf", fake_pdf_extract)

    result = pdf.extract_text_for_paper("paper.pdf", doi="10.48550/arxiv.2301.12345")

    assert result == "pdf-text:paper.pdf"


def test_action_extract_uses_latex_source_via_pdf_status(tmp_path, monkeypatch):
    """Integrationstest: action_extract() mit pdf_status_path nutzt fuer ein
    Paper mit arXiv-DOI die LaTeX-Quelle statt pypdf-Extraktion (#399,
    Scope-"In": Nutzung als Alternative zur PDF-Extraktion)."""
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "arxiv_paper.pdf").write_bytes(b"%PDF-1.4 dummy")

    pdf_status_path = tmp_path / "pdf_status.json"
    pdf_status_path.write_text(
        json.dumps(
            {
                "10.48550/arxiv.2301.12345": {
                    "success": True,
                    "pdf_path": str(pdf_dir / "arxiv_paper.pdf"),
                    "source": "arxiv",
                    "error": None,
                }
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "pdf_texts.json"

    marker = "\\begin{equation} E = mc^2 \\end{equation}"

    def fake_fetch(arxiv_id: str) -> str | None:
        assert arxiv_id == "2301.12345"
        return marker

    def fail_if_called(pdf_path: str) -> str:
        raise AssertionError("extract_text_from_pdf haette NICHT aufgerufen werden duerfen")

    monkeypatch.setattr(pdf.arxiv_latex, "fetch_arxiv_latex_source", fake_fetch)
    monkeypatch.setattr(pdf, "extract_text_from_pdf", fail_if_called)

    exit_code = pdf.action_extract(
        str(pdf_dir), str(output_path), pdf_status_path=str(pdf_status_path)
    )

    assert exit_code == 0
    texts = json.loads(output_path.read_text(encoding="utf-8"))
    assert texts["arxiv_paper.pdf"] == marker


def test_action_extract_without_pdf_status_is_unchanged(tmp_path, monkeypatch):
    """Ohne pdf_status_path (bisheriger Aufruf) bleibt das Verhalten
    identisch: keine arXiv-Erkennung, ganz normale pypdf-Extraktion
    (Out-Scope #399: bestehende Pipeline fuer Nicht-arXiv-Quellen
    unveraendert)."""
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "some_paper.pdf").write_bytes(b"%PDF-1.4 dummy")
    output_path = tmp_path / "pdf_texts.json"

    def fail_if_called(arxiv_id: str) -> str | None:
        raise AssertionError("fetch_arxiv_latex_source haette NICHT aufgerufen werden duerfen")

    def fake_pdf_extract(pdf_path: str) -> str:
        return "plain-pdf-text"

    monkeypatch.setattr(pdf.arxiv_latex, "fetch_arxiv_latex_source", fail_if_called)
    monkeypatch.setattr(pdf, "extract_text_from_pdf", fake_pdf_extract)

    exit_code = pdf.action_extract(str(pdf_dir), str(output_path))

    assert exit_code == 0
    texts = json.loads(output_path.read_text(encoding="utf-8"))
    assert texts["some_paper.pdf"] == "plain-pdf-text"
