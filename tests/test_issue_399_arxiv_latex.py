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
import logging
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
    nicht die Nebendatei ohne \\documentclass.

    Die Nebendatei ist bewusst LAENGER als main.tex: _pick_main_tex() faellt
    auf die groesste Datei zurueck, wenn keine `\\documentclass` enthaelt. Waere
    main.tex (wie in einer frueheren Fixture-Version) die groessere Datei,
    wuerde der Groessen-Fallback zufaellig dieselbe (richtige) Datei liefern,
    selbst wenn die `\\documentclass`-Heuristik komplett entfernt wuerde --
    der Test koennte diese Regression dann nicht erkennen (test-gaming-Luecke,
    critic-Review PR #435). Die Laengen-Assertion haelt das absichtlich fest.
    """
    main_tex = (
        b"\\documentclass{article}\n"
        b"\\begin{document}\n" + MAIN_MARKER.encode() + b"\n\\end{document}\n"
    )
    side_tex = (
        b"% just a fragment, no documentclass -- deliberately padded so this\n"
        b"% file is LONGER than main.tex; only the \\documentclass heuristic,\n"
        b"% not the size-based fallback, may correctly select main.tex here.\n"
        + SIDE_MARKER.encode()
        + b"\n"
    )
    assert len(side_tex) > len(main_tex), (
        "Fixture-Invariante: die Nebendatei muss groesser sein als main.tex, "
        "sonst testet dieser Fall die \\documentclass-Heuristik nicht mehr "
        "(siehe Docstring)."
    )
    body = _make_targz({"main.tex": main_tex, "appendix_fragment.tex": side_tex})

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"https://arxiv.org/e-print/{ARXIV_ID}"
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert isinstance(result, str)
    assert MAIN_MARKER in result
    assert SIDE_MARKER not in result


def test_fetch_returns_none_for_pdf_only_submission(monkeypatch, caplog):
    """PDF-only-Submission (e-print liefert PDF-Bytes) -> None ueber den
    dedizierten PDF_MAGIC-Zweig, kein Absturz.

    Eine reine `result is None`-Assertion wuerde die PDF-Erkennung selbst
    NICHT pruefen: entfernt man den `PDF_MAGIC`-Zweig komplett, faellt der
    Code auf den generischen "unbekanntes Format"-Fallback durch, der
    ebenfalls `None` liefert -- der Test bliebe gruen (critic-Review PR
    #435). Die caplog-Assertion auf die PDF-spezifische Log-Meldung stellt
    sicher, dass tatsaechlich der PDF_MAGIC-Zweig gegriffen hat.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4\n%dummy pdf bytes")

    _patched_client(monkeypatch, handler)

    with caplog.at_level(logging.INFO, logger="arxiv_latex"):
        result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert result is None
    assert any("PDF-only" in record.message for record in caplog.records), (
        "Erwarte die dedizierte PDF_MAGIC-Log-Meldung ('...ist PDF-only...'); "
        "ohne sie koennte der generische Fallback-Zweig unbemerkt denselben "
        "None-Rueckgabewert liefern."
    )


def test_fetch_returns_none_for_http_error(monkeypatch):
    """Unbekannte/nicht existente arXiv-ID (404) -> None, kein Absturz."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source("0000.00000")

    assert result is None


def test_fetch_returns_none_for_truncated_gzip_body(monkeypatch, caplog):
    """Abgeschnittener gzip-Body (kaputte HTTP-Antwort) -> None statt Absturz.

    Regression: gzip.decompress() wirft bei einem Stream ohne End-of-Stream-
    Marker EOFError, bei einem korrupten Deflate-Block zlib.error -- beides
    KEINE OSError-Subklassen. Ein `except OSError` allein liess diese beiden
    Faelle durchschlagen und riss den Aufrufer-Batch ab (P1-Review-Fund PR #435).
    """
    full_body = _make_targz({"main.tex": b"\\documentclass{article}"})
    truncated_body = full_body[:-5]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=truncated_body)

    _patched_client(monkeypatch, handler)

    with caplog.at_level(logging.INFO):
        result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

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


def test_fetch_returns_none_for_single_gzipped_pdf(monkeypatch):
    """Einzeldatei-gzip-Antwort mit PDF-Bytes (arXiv liefert PDF-only-
    Einzeldatei-Submissions ebenfalls gzip-gepackt aus, Content-Encoding:
    x-gzip) -> None statt latin-1-dekodiertem Binaermuell (AC #2, #399).

    Ohne Magic-Byte-Pruefung der ENTPACKTEN Bytes faellt der Code auf
    `_decode_tex(decompressed)` durch; `_decode_tex` verschluckt via
    latin-1-Fallback jeden Dekodierfehler und liefert einen str mit
    PDF-Binaermuell statt des dokumentierten `None`-Fallbacks
    (critic-Review PR #435, scripts/arxiv_latex.py:168).
    """
    body = gzip.compress(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert result is None


def test_fetch_returns_none_for_single_gzipped_postscript(monkeypatch):
    """Einzeldatei-gzip-Antwort mit PostScript-Bytes (aeltere Einzeldatei-
    Submission) -> None statt vermeintlicher LaTeX-Quelle (AC #2, #399)."""
    body = gzip.compress(b"%!PS-Adobe-3.0\nsome postscript content here\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert result is None


def test_fetch_returns_none_for_single_gzipped_non_latex_text(monkeypatch):
    """Einzeldatei-gzip mit unverdaechtigem, aber NICHT-LaTeX-Text (kein
    `\\documentclass`, kein `\\begin{document}`) -> None statt Fehltext (AC
    #2, #399). Vorher wurde jeder nicht-leere Einzeldatei-gzip-Inhalt als
    vermeintliche LaTeX-Quelle zurueckgegeben."""
    body = gzip.compress(b"This is just a plain readme, not LaTeX at all.\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    result = arxiv_latex.fetch_arxiv_latex_source(ARXIV_ID)

    assert result is None


def test_latex_limit_constants_exist():
    """Caps gegen Decompression-Bomb/Speicherverbrauch muessen existieren."""
    assert hasattr(arxiv_latex, "ARXIV_LATEX_MAX_MEMBERS")
    assert hasattr(arxiv_latex, "ARXIV_LATEX_MAX_MEMBER_SIZE")
    assert arxiv_latex.ARXIV_LATEX_MAX_MEMBERS > 0
    assert arxiv_latex.ARXIV_LATEX_MAX_MEMBER_SIZE > 0


# ---------------------------------------------------------------------------
# arxiv_id_from_doi() -- Baustein fuer die Verdrahtung in scripts/pdf.py
# (Issue #399, Scope "In": Nutzung als Alternative zur PDF-Extraktion, wenn
# ein Paper eine arXiv-ID hat). scripts/search.py setzt fuer arXiv-Treffer
# `doi = f"10.48550/arxiv.{arxiv_id}"` (Tier "arxiv" in search_arxiv()) --
# arxiv_id_from_doi() muss genau dieses Muster wiedererkennen.
# ---------------------------------------------------------------------------


def test_arxiv_id_from_doi_matches_arxiv_doi_pattern():
    """DOI im von search_arxiv() erzeugten Muster liefert die arXiv-ID."""
    assert arxiv_latex.arxiv_id_from_doi("10.48550/arxiv.2301.12345") == "2301.12345"


def test_arxiv_id_from_doi_is_case_insensitive():
    """DOI-Vergleich case-insensitiv, analog zu text_utils.normalize_doi."""
    assert arxiv_latex.arxiv_id_from_doi("10.48550/ARXIV.2301.12345") == "2301.12345"


def test_arxiv_id_from_doi_returns_none_for_non_arxiv_doi():
    """Nicht-arXiv-DOI (z.B. Elsevier) -> None (Out-Scope #399 bleibt
    unberuehrt: nur echte arXiv-DOIs werden erkannt)."""
    assert arxiv_latex.arxiv_id_from_doi("10.1016/j.example.2024.01.001") is None


def test_arxiv_id_from_doi_returns_none_for_none_input():
    """Fehlende DOI (haeufig bei Nicht-arXiv-Quellen) -> None, kein Absturz."""
    assert arxiv_latex.arxiv_id_from_doi(None) is None
