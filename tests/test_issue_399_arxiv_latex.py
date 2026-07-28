"""Regressionstests fuer Issue #399.

arxiv_latex.fetch_arxiv_latex_source(arxiv_id) laedt den e-print-Endpoint
(https://arxiv.org/e-print/<id>) und liefert den Inhalt der Haupt-.tex-Datei
als Text zurueck -- oder None, wenn keine LaTeX-Quelle verfuegbar ist
(PDF-only-Submission, HTTP-Fehler, kaputtes Archiv).

Akzeptanzkriterien (#399):
- Bekannte arXiv-ID mit LaTeX-Quellpaket -> Inhalt der Haupt-.tex-Datei als Text.
- arXiv-ID ohne LaTeX-Quelle (PDF-only) -> definierter Fallback-Wert (None),
  kein Absturz.
- pytest-Testfall mit gemocktem HTTP-Response deckt beide Faelle ab.
"""

from __future__ import annotations

import gzip
import io
import tarfile

import httpx

import arxiv_latex

ARXIV_ID = "2301.12345"
MAIN_MARKER = "UNIQUE_MAIN_TEX_MARKER_399"
SIDE_MARKER = "UNIQUE_SIDE_TEX_MARKER_399"


def _make_targz(files: dict[str, bytes]) -> bytes:
    """Baut ein gzip-tar-Archiv im Speicher aus {arcname: content}."""
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return gzip.compress(tar_buf.getvalue())


def _patched_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(arxiv_latex.httpx, "Client", patched)


def test_fetch_returns_main_tex_content_from_multi_file_targz(monkeypatch):
    """Mehrdatei-Tarball: Haupt-.tex (mit \\documentclass) wird erkannt,
    nicht die Nebendatei ohne \\documentclass."""
    main_tex = (
        b"\\documentclass{article}\n"
        b"\\begin{document}\n" + MAIN_MARKER.encode() + b"\n\\end{document}\n"
    )
    side_tex = b"% just a fragment, no documentclass\n" + SIDE_MARKER.encode() + b"\n"
    body = _make_targz({"main.tex": main_tex, "appendix_fragment.tex": side_tex})

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"https://arxiv.org/e-print/{ARXIV_ID}"
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert isinstance(result, str)
    assert MAIN_MARKER in result
    assert SIDE_MARKER not in result


def test_fetch_returns_none_for_pdf_only_submission(monkeypatch):
    """PDF-only-Submission (e-print liefert PDF-Bytes) -> None, kein Absturz."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4\n%dummy pdf bytes")

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert result is None


def test_fetch_returns_none_for_http_error(monkeypatch):
    """Unbekannte/nicht existente arXiv-ID (404) -> None, kein Absturz."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source("0000.00000")

    assert result is None


def test_fetch_returns_none_for_empty_targz_without_tex(monkeypatch):
    """Archiv ohne jegliche .tex-Datei -> None statt Absturz."""
    body = _make_targz({"README": b"no tex here"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert result is None


def test_fetch_handles_single_gzipped_tex_file(monkeypatch):
    """Einzeldatei-gzip (kein Tar) mit \\documentclass wird als Haupt-Tex gelesen."""
    single_tex = (
        b"\\documentclass{article}\n"
        b"\\begin{document}\n" + MAIN_MARKER.encode() + b"\n\\end{document}\n"
    )
    body = gzip.compress(single_tex)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert isinstance(result, str)
    assert MAIN_MARKER in result


def test_latex_limit_constants_exist():
    """Caps gegen Decompression-Bomb/Speicherverbrauch muessen existieren."""
    assert hasattr(arxiv_latex, "ARXIV_LATEX_MAX_MEMBERS")
    assert hasattr(arxiv_latex, "ARXIV_LATEX_MAX_MEMBER_SIZE")
    assert arxiv_latex.ARXIV_LATEX_MAX_MEMBERS > 0
    assert arxiv_latex.ARXIV_LATEX_MAX_MEMBER_SIZE > 0
