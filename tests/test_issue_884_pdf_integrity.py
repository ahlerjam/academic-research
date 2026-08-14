"""Regressionstests fuer Issue #884: Volltext-Integritaet erzwingen.

Eine HTML-Fehlerseite unter HTTP 200 darf auf keinem Beschaffungsweg als PDF
im Korpus landen. Deckt die Wege ab, die vor diesem Issue ungeprueft waren:

1. ``scripts.pdf.download_pdf`` (HTTP-Tier-Resolver) -- war teilweise
   geprueft (Magic-Bytes), aber ohne Mindestgroesse.
2. ``academic_vault.server.add_paper``/``update_pdf_path`` (Vault-Gate) --
   war komplett ungeprueft; schliesst zugleich die Wege ueber
   ``commands/fetch.md`` und manuelle/direkte Aufrufe.
3. Der arXiv-Direktweg (Tier 0, Issue #885) -- kam nach #884 dazu und ist der
   einzige Tier, dessen PDF-Adresse geraten und von keinem Nachweisdienst
   bestaetigt wird. Er muss derselben Pruefung unterliegen wie jeder andere
   Tier (siehe ``TestArxivDirectTierIsGated``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

#: Browser-use-Fetcher-Subagenten mit eigener Download-Selbstpruefung
#: (Issue #884 Plan). Vereinheitlicht auf die 2-KB-Schwelle von
#: ``scripts.pdf.MIN_PDF_SIZE`` -- vorher uneinheitlich (sechs auf "> 10 KB",
#: generic-fetcher auf "> 0 Bytes", scihub-fetcher ganz ohne Groessenpruefung).
#:
#: Bewusst AUS DEM DATEIBESTAND ermittelt statt hartkodiert: #840 hat die
#: Site-Fetcher in den generic-fetcher konsolidiert, ihr Site-Wissen liegt
#: jetzt in ``config/browser_guides/``. Eine feste Namensliste haette den Test
#: mit ``FileNotFoundError`` brechen lassen -- ein Fehlschlag, der nichts ueber
#: die Schwelle aussagt. Dynamisch geprueft wird weiterhin JEDER vorhandene
#: Fetcher-Prompt; verschwindet einer, faellt seine Pruefung mit ihm weg,
#: kommt einer dazu, ist er automatisch mit erfasst.
#: Ausgenommen, weil sie keine eigene Groessen-Selbstpruefung tragen:
#: ``scihub-fetcher`` hat einen eigenen, strengeren Test (Magic-Bytes, s. u.),
#: ``book-fetcher`` laedt selbst gar nichts herunter -- er orchestriert die
#: Site-Stufen und den generic-fetcher, die Pruefung sitzt dort.
_NO_OWN_DOWNLOAD_CHECK = {"scihub-fetcher", "book-fetcher"}

UNIFIED_THRESHOLD_AGENTS = tuple(
    sorted(p.stem for p in AGENTS_DIR.glob("*-fetcher.md") if p.stem not in _NO_OWN_DOWNLOAD_CHECK)
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


# ---------------------------------------------------------------------------
# arXiv-Direktweg (Tier 0, Issue #885) unterliegt demselben Gate
# ---------------------------------------------------------------------------

#: DOI im arXiv-Muster -- loest in resolve_pdf_url() Tier 0 aus.
ARXIV_DOI = "10.48550/arxiv.2301.12345"
ARXIV_PDF_URL = "https://arxiv.org/pdf/2301.12345"


class _FakeResolveClient:
    """httpx.Client-Ersatz fuer ``action_resolve``.

    ``get()`` wirft: beweist, dass Tier 0 ohne Nachweisdienst auskommt
    (Issue #885). ``stream()`` liefert den vorgegebenen Rumpf unter HTTP 200
    -- so wie arxiv.org es bei einer Fehler-/Rate-Limit-Seite taete.
    """

    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks
        self.streamed_urls: list[str] = []

    def get(self, *args, **kwargs):
        raise AssertionError("Tier 0 darf keinen Nachweisdienst befragen (Issue #885)")

    def stream(self, method, url, timeout=None):
        self.streamed_urls.append(url)
        return _FakeStreamResponse(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _run_action_resolve(tmp_path, monkeypatch, chunks: list[bytes]):
    """Faehrt ``action_resolve`` fuer ein arXiv-DOI-Paper mit gefaktem Client."""
    import pdf as pdf_module

    papers_path = tmp_path / "papers.json"
    papers_path.write_text(
        json.dumps([{"doi": ARXIV_DOI, "title": "An arXiv paper", "type": "article-journal"}]),
        encoding="utf-8",
    )
    output_dir = tmp_path / "pdfs"
    status_path = tmp_path / "pdf_status.json"

    client = _FakeResolveClient(chunks)
    monkeypatch.setattr(pdf_module.httpx, "Client", lambda *a, **kw: client)

    rc = pdf_module.action_resolve(
        str(papers_path), str(output_dir), str(status_path), "test@example.com"
    )
    assert rc == 0
    status = json.loads(status_path.read_text(encoding="utf-8"))
    return client, output_dir, status[ARXIV_DOI]


class TestArxivDirectTierIsGated:
    """Semantische Klammer zwischen #884 und #885.

    Tier 0 baut die PDF-Adresse allein aus der DOI -- kein Nachweisdienst
    bestaetigt, dass dort wirklich ein PDF liegt. Genau deshalb muss dieser
    Weg durch ``download_pdf()`` laufen. Faellt die Pruefung dort weg oder
    speichert Tier 0 kuenftig an ``download_pdf()`` vorbei, werden diese
    Tests rot.
    """

    def test_arxiv_direct_html_200_is_rejected_and_no_file_written(self, tmp_path, monkeypatch):
        """Kernfall aus #884 auf dem neuen Weg aus #885: arxiv.org liefert
        HTTP 200 mit einer HTML-Seite -- die darf nicht im PDF-Verzeichnis
        der Session landen."""
        client, output_dir, entry = _run_action_resolve(
            tmp_path, monkeypatch, [b"<!DOCTYPE html><html><body>Rate limited</body></html>"]
        )

        # Der Weg war wirklich Tier 0 (sonst prueft der Test etwas anderes).
        assert client.streamed_urls == [ARXIV_PDF_URL]
        assert entry["source"] == "arxiv_direct"

        assert entry["success"] is False
        assert entry["pdf_path"] is None
        assert "Not a valid PDF" in entry["error"]
        assert list(output_dir.glob("*.pdf")) == []

    def test_arxiv_direct_truncated_pdf_is_rejected(self, tmp_path, monkeypatch):
        """Auch die Mindestgroesse aus #884 gilt auf dem arXiv-Direktweg."""
        import pdf as pdf_module

        client, output_dir, entry = _run_action_resolve(
            tmp_path, monkeypatch, [b"%PDF-1.4\n" + b"x" * 50]
        )

        assert client.streamed_urls == [ARXIV_PDF_URL]
        assert entry["source"] == "arxiv_direct"
        assert entry["success"] is False
        assert "zu klein" in entry["error"]
        assert str(pdf_module.MIN_PDF_SIZE) in entry["error"]
        assert list(output_dir.glob("*.pdf")) == []

    def test_arxiv_direct_real_pdf_still_succeeds(self, tmp_path, monkeypatch):
        """Gegenprobe: #885 bleibt funktionsfaehig -- ein echtes arXiv-PDF
        wird ohne Nachweisdienst beschafft und geschrieben."""
        body = b"%PDF-1.4\n" + b"x" * 4000
        client, output_dir, entry = _run_action_resolve(tmp_path, monkeypatch, [body])

        assert client.streamed_urls == [ARXIV_PDF_URL]
        assert entry["source"] == "arxiv_direct"
        assert entry["success"] is True
        written = list(output_dir.glob("*.pdf"))
        assert len(written) == 1
        assert written[0].read_bytes() == body
