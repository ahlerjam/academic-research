#!/usr/bin/env python3
"""PDF resolution, download and text extraction — v4 rewrite.

Merges v3 pdf_resolver.py + fulltext_index.py into a single module.

Actions:
  resolve  — Download PDFs via 5-tier fallback strategy
  extract  — Extract text from downloaded PDFs (pypdf)

Usage:
  python pdf.py --action resolve --papers papers.json --output-dir pdfs/ --output pdf_status.json
  python pdf.py --action extract --pdf-dir pdfs/ --output pdf_texts.json
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

import arxiv_latex
from text_utils import load_json, normalize_doi, safe_filename, save_json

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment,misc]

TIMEOUT = 30.0
PDF_MAGIC = b"%PDF"

BIOMED_DOI_PREFIXES: list[str] = [
    "10.1016/j.",  # Elsevier Biomedical
    "10.1186/",  # BMC
    "10.1371/",  # PLOS
    "10.3390/",  # MDPI Biology
]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PDF validation
# ---------------------------------------------------------------------------


def is_valid_pdf(content: bytes) -> bool:
    """Return True if content starts with PDF magic bytes."""
    return len(content) >= 4 and content[:4] == PDF_MAGIC


def tier_arxiv_direct(doi: str | None) -> str | None:
    """Tier 0: Bildet die arXiv-PDF-Adresse direkt aus der DOI, ohne einen
    Nachweisdienst zu befragen (Issue #885).

    Nutzt arxiv_latex.arxiv_id_from_doi() wieder, damit das
    arXiv-DOI-Muster (`10.48550/arxiv.<id>`) nur an einer Stelle im Repo
    lebt. Keine Netzwerk-I/O -- kann folglich nie einen Fehler werfen.

    Args:
        doi: DOI-String, roh oder bereits normalisiert; `None` erlaubt.

    Returns:
        Die PDF-Adresse `https://arxiv.org/pdf/<id>` oder `None`, wenn
        `doi` nicht dem arXiv-DOI-Muster entspricht.
    """
    arxiv_id = arxiv_latex.arxiv_id_from_doi(doi)
    if not arxiv_id:
        return None
    return f"https://arxiv.org/pdf/{arxiv_id}"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_pdf(client: httpx.Client, pdf_url: str, output_path: str) -> None:
    """Stream-download PDF. Raises ValueError if not valid PDF."""
    try:
        with client.stream("GET", pdf_url, timeout=TIMEOUT) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                if not chunks and not is_valid_pdf(chunk):
                    raise ValueError(f"Not a valid PDF: {pdf_url!r}")
                chunks.append(chunk)
        with open(output_path, "wb") as fh:
            for chunk in chunks:
                fh.write(chunk)
    except Exception:
        if os.path.exists(output_path):
            os.unlink(output_path)
        raise


# ---------------------------------------------------------------------------
# Tier-based PDF resolution
# ---------------------------------------------------------------------------


def _looks_like_pdf_url(url: str) -> bool:
    """Precise check whether a URL plausibly points at a direct PDF file.

    Matches only a ``.pdf`` path extension, an exact ``pdf`` path segment
    (e.g. ``/content/pdf/...`` — not ``/pdfjs/...``), or a ``type=printable``
    query parameter (exact key/value, not a substring). A naive substring
    check against the raw URL (``"/pdf" in url``) also matches PDF.js viewer
    pages like ``https://repo.example.org/pdfjs/viewer.html?file=123``,
    which are HTML, not PDFs — this precision avoids that false positive.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".pdf"):
        return True
    if "pdf" in [segment for segment in path.split("/") if segment]:
        return True
    query = parse_qs(parsed.query.lower())
    return query.get("type") == ["printable"]


def tier_openaire(client: httpx.Client, doi: str) -> str | None:
    """Tier 1: Resolve via OpenAIRE Graph API.

    Fragt ``graph/v1/researchProducts`` per DOI (``pid``) ab und sucht in
    ``results[0]["instances"][]["urls"][]`` nach einer URL, die per Muster
    (siehe ``_looks_like_pdf_url``) nach einem direkten PDF-Link aussieht.
    Es gibt kein verlaessliches "ist PDF"-Feld in der API-Antwort, daher
    die Heuristik.
    """
    resp = client.get(
        "https://api.openaire.eu/graph/v1/researchProducts",
        params={"pid": doi},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return None
    instances = results[0].get("instances") or []
    for instance in instances:
        for url in instance.get("urls") or []:
            if not isinstance(url, str):
                continue
            if _looks_like_pdf_url(url):
                return url
    return None


def tier_unpaywall(client: httpx.Client, doi: str, email: str) -> str | None:
    """Tier 2: Resolve via Unpaywall."""
    resp = client.get(
        f"https://api.unpaywall.org/v2/{doi}", params={"email": email}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    return (resp.json().get("best_oa_location") or {}).get("url_for_pdf")


def tier_core(client: httpx.Client, doi: str) -> str | None:
    """Tier 3: Resolve via CORE."""
    import time

    for attempt in range(3):
        try:
            resp = client.get(
                "https://api.core.ac.uk/v3/search/works",
                params={"q": f"doi:{doi}"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return results[0].get("downloadUrl") if results else None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 or attempt == 2:
                raise
            time.sleep(2.0 * (2**attempt))
    return None


def tier_module_urls(paper: dict[str, Any]) -> str | None:
    """Tier 4: OA URLs from search metadata."""
    for field in ("open_access_pdf", "openAccessPdf"):
        val = paper.get(field)
        if isinstance(val, dict) and val.get("url"):
            return val["url"]
        if isinstance(val, str) and val:
            return val
    oa_url = paper.get("oa_url")
    if isinstance(oa_url, str) and oa_url:
        return oa_url
    return None


def tier_direct_url(paper: dict[str, Any]) -> str | None:
    """Tier 5: Direct PDF URL."""
    url = paper.get("url")
    if isinstance(url, str) and url.lower().endswith(".pdf"):
        return url
    return None


def tier_arxiv_title(client: httpx.Client, title: str) -> str | None:
    """Tier 6: arXiv title search fallback."""
    safe_title = title[:80].replace('"', " ")
    try:
        resp = client.get(
            "https://export.arxiv.org/api/query",
            params={"search_query": f"ti:{safe_title}", "max_results": "1"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        # Rohe Bytes statt resp.text: httpx dekodiert .text ohne
        # charset-Angabe im Content-Type immer als UTF-8 -- Expat wertet
        # dagegen die <?xml ... encoding="..."?>-Deklaration im Prolog
        # selbst aus (Issue #464 AC1, Konsistenz mit scripts/search.py).
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            for link in entry.findall("atom:link", ns):
                if link.get("title") == "pdf":
                    return link.get("href")
    except Exception:
        log.exception("arXiv title search failed: %s", title[:40])
    return None


def tier_openaccessbutton(client: httpx.Client, doi: str) -> str | None:
    """Tier 7: Resolve via OpenAccessButton API."""
    resp = client.get(
        "https://api.openaccessbutton.org/find",
        params={"id": doi},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return (resp.json().get("data") or {}).get("url")


_DOAB_BASE = "https://directory.doabooks.org"


def tier_doab(client: httpx.Client, isbn_or_title: str) -> str | None:
    """Tier 8: Resolve via DOAB REST API."""
    resp = client.get(
        "https://directory.doabooks.org/rest/search",
        params={"query": isbn_or_title, "expand": "bitstreams"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    results = resp.json()
    if not isinstance(results, list):
        return None
    for item in results:
        for bs in item.get("bitstreams") or []:
            if bs.get("mimeType") == "application/pdf":
                link: str = bs.get("retrieveLink") or ""
                if not link:
                    continue
                if link.startswith("http"):
                    return link
                return f"{_DOAB_BASE}{link}"
    return None


def tier_europepmc(client: httpx.Client, doi: str) -> str | None:
    """Tier 10: Resolve via Europe PMC API (biomedical OA)."""
    resp = client.get(
        "https://www.europepmc.org/backend/europepmc/findByQuery.do",
        params={
            "query": f"DOI:{doi}",
            "format": "json",
            "resulttype": "core",
            "pageSize": "1",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    results = (resp.json().get("resultList") or {}).get("result") or []
    for article in results:
        urls = (article.get("fullTextUrlList") or {}).get("fullTextUrl") or []
        for entry in urls:
            if entry.get("documentStyle") == "pdf" and entry.get("availability") == "Open access":
                return entry.get("url")
    return None


def resolve_pdf_url(
    client: httpx.Client, paper: dict[str, Any], email: str
) -> tuple[str | None, str | None, str | None]:
    """Try all tiers to find a PDF URL. Returns (url, source_tier, error).

    Tier order:
      0  arXiv-Direct (DOI) — vor allen Nachweisdiensten (Issue #885)
      1  OpenAIRE         (DOI) — European OA repositories
      2  Unpaywall        (DOI)
      3  CORE             (DOI)
      4  Module OA URLs   (metadata)
      5  Direct URL       (metadata)
      6  arXiv Title      (title)
      7  DOAB             (isbn/title) — books/chapters only, before OpenAccessButton
      8  OpenAccessButton (DOI)
      9  DOAB             (isbn/title) — non-book fallback
      10 EuropePMC        (DOI) — final fallback for all DOIs
    """
    doi = normalize_doi(paper.get("doi"))
    last_error = None
    paper_type = paper.get("type") or ""
    is_book = paper_type in {"book", "chapter"}

    # Tier 0: arXiv-Direct — kein Netzwerkaufruf, daher kein last_error moeglich
    if url := tier_arxiv_direct(doi):
        return url, "arxiv_direct", last_error

    # Tier 1: OpenAIRE
    if doi:
        try:
            url = tier_openaire(client, doi)
            if url:
                return url, "openaire", None
        except Exception as exc:
            last_error = str(exc)

    # Tier 2: Unpaywall
    if doi:
        try:
            url = tier_unpaywall(client, doi, email)
            if url:
                return url, "unpaywall", last_error
        except Exception as exc:
            last_error = str(exc)

    # Tier 3: CORE
    if doi:
        try:
            url = tier_core(client, doi)
            if url:
                return url, "core", last_error
        except Exception as exc:
            last_error = str(exc)

    # Tier 4: Module OA URLs
    url = tier_module_urls(paper)
    if url:
        return url, "module_oa", last_error

    # Tier 5: Direct URL
    url = tier_direct_url(paper)
    if url:
        return url, "direct", last_error

    # Tier 6: arXiv title search
    if title := paper.get("title"):
        try:
            url = tier_arxiv_title(client, title)
            if url:
                return url, "arxiv", last_error
        except Exception as exc:
            last_error = str(exc)

    # Tier 7 (book priority): DOAB first for books/chapters
    isbn_or_title = paper.get("isbn") or paper.get("title") or ""
    if is_book and isbn_or_title:
        try:
            url = tier_doab(client, isbn_or_title)
            if url:
                return url, "doab", last_error
        except Exception as exc:
            last_error = str(exc)

    # Tier 8: OpenAccessButton
    if doi:
        try:
            url = tier_openaccessbutton(client, doi)
            if url:
                return url, "openaccessbutton", last_error
        except Exception as exc:
            last_error = str(exc)

    # Tier 9: DOAB for non-book types
    if not is_book and isbn_or_title:
        try:
            url = tier_doab(client, isbn_or_title)
            if url:
                return url, "doab", last_error
        except Exception as exc:
            last_error = str(exc)

    # Tier 10: EuropePMC — final fallback for all DOIs
    if doi:
        try:
            url = tier_europepmc(client, doi)
            if url:
                return url, "europepmc", last_error
        except Exception as exc:
            last_error = str(exc)

    return None, None, last_error or "No PDF URL found"


def action_resolve(papers_path: str, output_dir: str, output_path: str, email: str) -> int:
    """Resolve and download PDFs for all papers."""
    papers = load_json(papers_path)
    os.makedirs(output_dir, exist_ok=True)
    status: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for paper in papers:
            doi = normalize_doi(paper.get("doi"))
            key = doi or (paper.get("title") or "unknown")
            url, source, error = resolve_pdf_url(client, paper, email)

            if not url:
                status[key] = {"success": False, "pdf_path": None, "source": None, "error": error}
                continue

            fname = safe_filename(doi or (paper.get("title") or "untitled")[:80])
            pdf_path = os.path.join(output_dir, f"{fname}.pdf")
            try:
                download_pdf(client, url, pdf_path)
                status[key] = {
                    "success": True,
                    "pdf_path": pdf_path,
                    "source": source,
                    "error": None,
                }
            except Exception as exc:
                log.exception("PDF download failed: %s", key)
                status[key] = {
                    "success": False,
                    "pdf_path": None,
                    "source": source,
                    "error": str(exc),
                }

    save_json(status, output_path)
    success = sum(1 for s in status.values() if s["success"])
    log.info("PDFs resolved: %d/%d successful", success, len(status))
    return 0


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF using pypdf."""
    try:
        reader = PdfReader(pdf_path)
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n".join(text_parts)
    except Exception:
        log.exception("Failed to extract text from %s", pdf_path)
        return ""


def extract_text_for_paper(pdf_path: str, doi: str | None = None) -> str:
    """Extrahiert Text fuer ein Paper: bevorzugt die arXiv-LaTeX-Quelle
    (Formeltreue bei MINT-Themen, #399), wenn `doi` auf eine arXiv-ID
    verweist (Muster `10.48550/arxiv.<id>`, siehe scripts/search.py::
    search_arxiv()); faellt sonst auf die bestehende PDF-Extraktion zurueck.

    Das ist der einzige Aufrufer von arxiv_latex.fetch_arxiv_latex_source()
    im Repo ausserhalb dessen eigener Testdatei (#399, Scope "In": Nutzung
    als Alternative zur PDF-Extraktion, wenn ein Paper eine arXiv-ID hat).
    Aendert NICHTS an der Extraktion fuer Nicht-arXiv-Quellen (`doi` ohne
    arXiv-Muster bzw. `None`) -- Out-Scope aus #399.
    """
    arxiv_id = arxiv_latex.arxiv_id_from_doi(doi)
    if arxiv_id:
        latex_source = arxiv_latex.fetch_arxiv_latex_source(arxiv_id)
        if latex_source:
            return latex_source
    return extract_text_from_pdf(pdf_path)


def _doi_by_pdf_filename(pdf_status_path: str | None) -> dict[str, str]:
    """Baut ein {PDF-Dateiname: DOI}-Mapping aus dem pdf_status.json von
    action_resolve() (#399: ermoeglicht action_extract(), fuer arXiv-Papers
    die LaTeX-Quelle statt PDF-Extraktion zu nutzen).

    Liefert ein leeres Mapping, wenn kein Pfad angegeben ist oder die Datei
    fehlt/kaputt ist -- action_extract() faellt dann vollstaendig auf die
    bisherige, unveraenderte PDF-Extraktion zurueck.
    """
    if not pdf_status_path:
        return {}
    try:
        status = load_json(pdf_status_path)
    except (OSError, ValueError):
        log.warning(
            "pdf-status %s nicht lesbar -- arXiv-LaTeX-Alternative uebersprungen",
            pdf_status_path,
        )
        return {}
    if not isinstance(status, dict):
        return {}

    mapping: dict[str, str] = {}
    for doi, entry in status.items():
        pdf_path = entry.get("pdf_path") if isinstance(entry, dict) else None
        if isinstance(pdf_path, str) and pdf_path:
            mapping[os.path.basename(pdf_path)] = doi
    return mapping


def action_extract(pdf_dir: str, output_path: str, pdf_status_path: str | None = None) -> int:
    """Extract text from all PDFs in directory.

    Wenn `pdf_status_path` (Ausgabe von action_resolve()) angegeben ist,
    wird pro PDF-Datei die zugehoerige DOI nachgeschlagen; hat ein Paper
    eine erkennbare arXiv-ID, wird zuerst die arXiv-LaTeX-Quelle als
    Formeltreue-Alternative zur PDF-Extraktion versucht (#399). Ohne
    `pdf_status_path` ist das Verhalten identisch zum Vorher-Stand (Out-
    Scope #399: bestehende Pipeline fuer Nicht-arXiv-Quellen unveraendert).
    """
    texts: dict[str, str] = {}
    if not os.path.isdir(pdf_dir):
        log.error("PDF directory not found: %s", pdf_dir)
        return 1

    doi_by_filename = _doi_by_pdf_filename(pdf_status_path)

    for fname in sorted(os.listdir(pdf_dir)):
        if not fname.lower().endswith(".pdf"):
            continue
        path = os.path.join(pdf_dir, fname)
        doi = doi_by_filename.get(fname)
        text = extract_text_for_paper(path, doi)
        texts[fname] = text

    save_json(texts, output_path)
    log.info("Extracted text from %d PDFs", len(texts))
    return 0


# ---------------------------------------------------------------------------
# OCR-Detection
# ---------------------------------------------------------------------------


def detect_needs_ocr(
    pdf_path: str,
    sample_pages: int = 5,
    threshold: int = 100,
) -> bool:
    """Prueft ob ein PDF OCR benoetigt.

    Liest bis zu sample_pages zufaellig verteilte Seiten via pypdf.
    Gibt True zurueck wenn der Durchschnitt der extrahierten Zeichen
    je Seite < threshold (Standard: 100 Zeichen).
    Bei leerem PDF (0 Seiten) gibt die Funktion True zurueck.
    """
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        log.exception("detect_needs_ocr: konnte %s nicht oeffnen", pdf_path)
        return True  # Im Fehlerfall: OCR vorschlagen

    total_pages = len(reader.pages)
    if total_pages == 0:
        return True

    n = min(sample_pages, total_pages)
    indices = random.sample(range(total_pages), n)

    total_chars = 0
    for i in indices:
        text = reader.pages[i].extract_text() or ""
        total_chars += len(text)

    avg_chars = total_chars / n
    return avg_chars < threshold


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDF resolution and extraction")
    parser.add_argument("--action", required=True, choices=["resolve", "extract"])
    parser.add_argument("--papers", help="Papers JSON (for resolve)")
    parser.add_argument("--output-dir", help="PDF output directory (for resolve)")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--pdf-dir", help="PDF directory (for extract)")
    parser.add_argument(
        "--pdf-status",
        help=(
            "pdf_status.json von --action resolve (fuer extract, optional). "
            "Aktiviert die arXiv-LaTeX-Alternative aus #399 fuer Papers mit "
            "erkennbarer arXiv-ID; ohne diese Option unveraendertes Verhalten."
        ),
    )
    parser.add_argument(
        "--email", default=os.environ.get("UNPAYWALL_EMAIL", "academic-research@example.com")
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()

    if args.action == "resolve":
        if not args.papers or not args.output_dir or not args.output:
            log.error("resolve requires --papers, --output-dir, --output")
            return 1
        return action_resolve(args.papers, args.output_dir, args.output, args.email)

    if args.action == "extract":
        if not args.pdf_dir or not args.output:
            log.error("extract requires --pdf-dir, --output")
            return 1
        return action_extract(args.pdf_dir, args.output, pdf_status_path=args.pdf_status)

    return 1


if __name__ == "__main__":
    sys.exit(main())
