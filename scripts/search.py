#!/usr/bin/env python3
"""Multi-source academic paper search — v4 rewrite.

Searches across 8 API sources in parallel:
  CrossRef, OpenAlex, Semantic Scholar, BASE, EconBiz, EconStor, arXiv, DBLP

Usage:
  python search.py --query "DevOps Governance" --modules crossref,openalex --limit 50
  python search.py --queries-file queries.json --modules crossref,semantic_scholar
"""

from __future__ import annotations

import argparse
import concurrent.futures
import functools
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from text_utils import normalize_paper, save_json

# ---------------------------------------------------------------------------
# PRISMA counters
# ---------------------------------------------------------------------------

PRISMA_COUNTER_KEYS = [
    "n_identified",
    "n_after_dedup",
    "n_excluded_screening",
    "n_excluded_eligibility",
    "n_included",
]


def build_prisma_counters(
    n_identified: int = 0,
    n_after_dedup: int = 0,
    n_excluded_screening: int = 0,
    n_excluded_eligibility: int = 0,
    n_included: int = 0,
) -> dict[str, int]:
    """Build a PRISMA counter dict from individual counts."""
    return {
        "n_identified": n_identified,
        "n_after_dedup": n_after_dedup,
        "n_excluded_screening": n_excluded_screening,
        "n_excluded_eligibility": n_excluded_eligibility,
        "n_included": n_included,
    }


def save_prisma_counters(session_dir: str, counters: dict[str, int]) -> None:
    """Write PRISMA counters to <session_dir>/prisma_counters.json."""
    path = Path(session_dir) / "prisma_counters.json"
    path.write_text(json.dumps(counters, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Interactive Phase 1
# ---------------------------------------------------------------------------


def run_interactive_phase1(
    papers: list[dict[str, Any]],
    query: str,
    n_preview: int = 5,
) -> dict[str, Any]:
    """Phase 1 of interactive research mode: return top-paper preview + approval options.

    Args:
        papers: List of ranked paper dicts (expected to have a 'prescore' key;
            falls back to 'score' for ranked.json written before #892).
        query: Original search query.
        n_preview: Minimum number of papers to include in preview (default 5).

    Returns:
        dict with:
          - top_papers: sorted list of up to 10 best papers
          - approval_options: list of option labels for the approval gate
          - query: original query
    """
    if not papers:
        return {
            "top_papers": [],
            "approval_options": _approval_options(),
            "query": query,
        }

    sorted_papers = sorted(papers, key=_ranking_key, reverse=True)
    preview_count = max(n_preview, min(10, len(sorted_papers)))
    top_papers = sorted_papers[:preview_count]

    return {
        "top_papers": top_papers,
        "approval_options": _approval_options(),
        "query": query,
    }


def _ranking_key(paper: dict[str, Any]) -> float:
    """Sortierschluessel der Vorschau: 4D-Vorranking, sonst der 5D-Score (#892).

    Das Gate steht vor dem Relevanz-Scoring — dort existiert nur ``prescore``.
    ``score`` bleibt als Rueckfall, damit eine ``ranked.json`` aus einem Lauf
    vor #892 unveraendert sortierbar bleibt.
    """
    value = paper.get("prescore")
    if value is None:
        value = paper.get("score", 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _approval_options() -> list[str]:
    """Return the 4 standard approval options for the interactive gate."""
    return [
        "Weiter — Phase 2 starten",
        "Anders formulieren — neue Query eingeben",
        "Mehr Quellen — zusätzliche Module hinzufügen",
        "Modul-Wahl ändern — andere API-Module wählen",
    ]


TIMEOUT = 30.0
OAI_DC_NS = "http://purl.org/dc/elements/1.1/"
ARXIV_NS = "http://www.w3.org/2005/Atom"

# Mengenlimits fuer den EconStor-OAI-PMH-Fallback (#236):
# Verhindern, dass bei dauerhaftem REST-Ausfall der gesamte Repo-Dump
# (> 250k Records) in den Speicher geladen wird bzw. die resumptionToken-
# Schleife unbegrenzt paginiert.
OAI_MAX_PAGES = 5  # max. resumptionToken-Runden (inkl. Erstabfrage)
OAI_MAX_RECORDS = 1000  # max. insgesamt geparste Records pro Fallback

# Zeitbudgets fuer den Gesamtlauf und den EconStor-OAI-PMH-Fallback (#465):
# eine einzelne langsame Quelle darf den ganzen Suchlauf nicht mehr um
# Minuten verzoegern. DEFAULT_TIME_BUDGET_S gilt fuer run_search() ueber
# alle Module hinweg; ECONSTOR_FALLBACK_TIME_BUDGET_S ist bewusst enger und
# greift zusaetzlich, direkt in der resumptionToken-Schleife von
# search_econstor() -- unabhaengig davon, wie grosszuegig das Gesamtbudget
# ist. Beide sind ueber CLI-Flags konfigurierbar (--time-budget,
# --fallback-time-budget).
DEFAULT_TIME_BUDGET_S = 60.0
ECONSTOR_FALLBACK_TIME_BUDGET_S = 20.0

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


def _retry_on_429(fn: Callable, max_retries: int = 3, base_delay: float = 2.0) -> Any:
    """Call fn(), retrying on HTTP 429 with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 or attempt == max_retries - 1:
                raise
            delay = base_delay * (2**attempt)
            log.warning(
                "429 rate limit — retrying in %.0fs (%d/%d)", delay, attempt + 1, max_retries
            )
            time.sleep(delay)


# ---------------------------------------------------------------------------
# Search modules
# ---------------------------------------------------------------------------


def search_crossref(query: str, limit: int) -> list[dict[str, Any]]:
    """Search CrossRef works endpoint."""
    url = "https://api.crossref.org/works"
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params={"query": query, "rows": limit})
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
    time.sleep(0.5)
    results: list[dict[str, Any]] = []
    for item in items:
        try:
            authors = []
            for author in item.get("author", []):
                given = author.get("given", "")
                family = author.get("family", "")
                full_name = f"{given} {family}".strip()
                if full_name:
                    authors.append(full_name)
            year = None
            date_parts = item.get("published-print", {}).get("date-parts") or item.get(
                "published-online", {}
            ).get("date-parts")
            if date_parts and date_parts[0]:
                year = int(date_parts[0][0])
            results.append(
                normalize_paper(
                    {
                        "doi": item.get("DOI"),
                        "title": (item.get("title") or [None])[0],
                        "authors": authors,
                        "year": year,
                        "abstract": item.get("abstract"),
                        "venue": (item.get("container-title") or [None])[0],
                        "citations": item.get("is-referenced-by-count", 0),
                        "url": item.get("URL"),
                        "language": item.get("language"),
                        "publication_type": item.get("type"),
                    },
                    "crossref",
                )
            )
        except Exception:
            log.warning("Module 'crossref': skipping malformed item %r", item, exc_info=True)
    return results


def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruct abstract from OpenAlex inverted index."""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions))


def search_openalex(query: str, limit: int) -> list[dict[str, Any]]:
    """Search OpenAlex works endpoint."""
    url = "https://api.openalex.org/works"
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params={"search": query, "per-page": limit})
        resp.raise_for_status()
        items = resp.json().get("results", [])
    time.sleep(0.5)
    results: list[dict[str, Any]] = []
    for item in items:
        try:
            authors = [
                a.get("author", {}).get("display_name")
                for a in item.get("authorships", [])
                if a.get("author", {}).get("display_name")
            ]
            location = item.get("primary_location", {}) or {}
            source = location.get("source", {}) or {}
            oa_info = item.get("open_access") or {}
            entry = normalize_paper(
                {
                    "doi": (item.get("doi") or "").replace("https://doi.org/", "") or None,
                    "title": item.get("title"),
                    "authors": authors,
                    "year": item.get("publication_year"),
                    "abstract": _reconstruct_abstract(item.get("abstract_inverted_index")),
                    "venue": source.get("display_name"),
                    "citations": item.get("cited_by_count", 0),
                    "url": item.get("id"),
                    "oa_url": oa_info.get("oa_url"),
                    "is_retracted": item.get("is_retracted"),
                    "citations_normalized": item.get("fwci"),
                    "language": item.get("language"),
                    "publication_type": item.get("type"),
                },
                "openalex",
            )
            results.append(entry)
        except Exception:
            log.warning("Module 'openalex': skipping malformed item %r", item, exc_info=True)
    return results


def search_semantic_scholar(query: str, limit: int) -> list[dict[str, Any]]:
    """Search Semantic Scholar paper endpoint."""
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params: dict[str, str | int] = {
        "query": query,
        "limit": limit,
        "fields": (
            "paperId,title,authors,year,abstract,venue,citationCount,openAccessPdf,"
            "externalIds,publicationTypes"
        ),
    }
    headers: dict[str, str] = {}
    if api_key := os.environ.get("SS_API_KEY"):
        headers["x-api-key"] = api_key
    with httpx.Client(timeout=TIMEOUT) as client:

        def _get() -> httpx.Response:
            r = client.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r

        resp = _retry_on_429(_get)
        items = resp.json().get("data", [])
    time.sleep(0.5)
    results: list[dict[str, Any]] = []
    for item in items:
        try:
            external_ids = item.get("externalIds") or {}
            oa_pdf = item.get("openAccessPdf") or {}
            # S2 liefert eine Liste (z.B. ["JournalArticle", "Review"]); der
            # Vorfilter arbeitet auf einem Wert -- der erste ist der primaere.
            publication_types = item.get("publicationTypes") or []
            entry = normalize_paper(
                {
                    "doi": external_ids.get("DOI"),
                    "title": item.get("title"),
                    "authors": [a.get("name") for a in item.get("authors", []) if a.get("name")],
                    "year": item.get("year"),
                    "abstract": item.get("abstract"),
                    "venue": item.get("venue"),
                    "citations": item.get("citationCount", 0),
                    "url": f"https://www.semanticscholar.org/paper/{item.get('paperId')}"
                    if item.get("paperId")
                    else None,
                    "open_access_pdf": oa_pdf.get("url"),
                    "publication_type": publication_types[0] if publication_types else None,
                },
                "semantic_scholar",
            )
            results.append(entry)
        except Exception:
            log.warning(
                "Module 'semantic_scholar': skipping malformed item %r", item, exc_info=True
            )
    return results


def search_base(query: str, limit: int) -> list[dict[str, Any]]:
    """Search BASE API (Bielefeld Academic Search Engine)."""
    url = "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi"
    params: dict[str, str | int] = {
        "func": "PerformSearch",
        "query": query,
        "format": "json",
        "hits": limit,
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    time.sleep(0.5)
    # BASE meldet seine dokumentierten Fehler nicht per HTTP-Status, sondern
    # mit HTTP 200 + {"error": ...} (Interface Guide v1.27, Appendix 4) --
    # darunter "Access denied ...", das jede nicht registrierte IP bekommt.
    # Ohne diese Pruefung faende der Zugriff unten schlicht keine "docs" und
    # das Modul meldete 0 Treffer als Erfolg: stiller Totalausfall der Quelle,
    # genau der Fall aus #456.
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"BASE API error: {payload['error']}")
    items = payload.get("response", {}).get("docs", []) or []
    results: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            log.warning("Module 'base': skipping non-dict item %r", item)
            continue
        try:

            def dc(fld: str, item=item) -> str | None:
                val = item.get(fld)
                return val[0] if isinstance(val, list) and val else val

            doi = None
            for ident in item.get("dcidentifier") or []:
                ident_str = str(ident)
                if "doi.org/" in ident_str:
                    doi = ident_str.split("doi.org/")[-1]
                    break
                if ident_str.startswith("10."):
                    doi = ident_str
                    break
            year_raw = dc("dcyear")
            year = int(year_raw) if year_raw and str(year_raw).isdigit() else None
            results.append(
                normalize_paper(
                    {
                        "doi": doi,
                        "title": dc("dctitle"),
                        "authors": item.get("dccreator") or [],
                        "year": year,
                        # BASE kennt kein "dcabstract" -- das Abstract-Feld
                        # heisst "dcdescription" (Interface Guide v1.27,
                        # Appendix 2 "Fields").
                        "abstract": dc("dcdescription"),
                        "venue": dc("dcpublisher"),
                        "citations": 0,
                        "url": dc("dcidentifier"),
                    },
                    "base",
                )
            )
        except Exception:
            log.warning("Module 'base': skipping malformed item %r", item, exc_info=True)
    return results


def search_econbiz(query: str, limit: int) -> list[dict[str, Any]]:
    """Search EconBiz API."""
    url = "https://api.econbiz.de/v1/search"
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params={"q": query, "size": limit})
        resp.raise_for_status()
        payload = resp.json()
    time.sleep(0.5)
    # EconBiz liefert je nach API-Version entweder eine flache "results"/"items"-
    # Liste oder (aktueller Live-Stand, Elasticsearch-Envelope) "hits.hits" --
    # Fallback-Kette deckt beide Formen ab (#456).
    items = (
        payload.get("results")
        or payload.get("items")
        or (payload.get("hits") or {}).get("hits")
        or []
    )
    results: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            log.warning("Module 'econbiz': skipping non-dict item %r", item)
            continue
        try:
            identifier_urls = item.get("identifier_url") or []
            doi = item.get("doi")
            if not doi:
                for ident in identifier_urls:
                    if isinstance(ident, str) and "doi.org/" in ident:
                        doi = ident.split("doi.org/")[-1]
                        break
            year_raw = item.get("year")
            if year_raw is None:
                date_list = item.get("date") or []
                if date_list and isinstance(date_list[0], str):
                    digits = "".join(c for c in date_list[0] if c.isdigit())
                    year_raw = digits[:4] if len(digits) >= 4 else None
            year = int(year_raw) if year_raw and str(year_raw).isdigit() else None
            authors = item.get("authors") or item.get("creator") or []
            paper_url = item.get("url") or (identifier_urls[0] if identifier_urls else None)
            results.append(
                normalize_paper(
                    {
                        "doi": doi,
                        "title": item.get("title"),
                        "authors": authors,
                        "year": year,
                        "abstract": item.get("abstract"),
                        "venue": item.get("source") or item.get("venue"),
                        "citations": item.get("citationCount", 0),
                        "url": paper_url,
                    },
                    "econbiz",
                )
            )
        except Exception:
            log.warning("Module 'econbiz': skipping malformed item %r", item, exc_info=True)
    return results


def search_econstor(
    query: str,
    limit: int,
    fallback_time_budget: float = ECONSTOR_FALLBACK_TIME_BUDGET_S,
) -> list[dict[str, Any]]:
    """Search EconStor via REST API with OAI-PMH fallback.

    Args:
        query: Search query.
        limit: Max results.
        fallback_time_budget: Engeres Zeitbudget (Sekunden) fuer die
            OAI-PMH-resumptionToken-Schleife (#465) -- unabhaengig vom
            Mengenlimit OAI_MAX_PAGES/OAI_MAX_RECORDS aus #236.
    """
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=TIMEOUT) as client:
        rest_resp = client.get(
            "https://www.econstor.eu/rest/items/find-by-metadata-field",
            params={"value": query, "key": "dc.title", "limit": limit},
        )
        if rest_resp.status_code == 200 and rest_resp.headers.get("content-type", "").startswith(
            "application/json"
        ):
            items = rest_resp.json()
        else:
            # Fallback: OAI-PMH harvest with client-side keyword filtering.
            # Mengenlimit (#236): hoechstens OAI_MAX_PAGES resumptionToken-Runden
            # und insgesamt hoechstens OAI_MAX_RECORDS geparste Records, damit bei
            # dauerhaftem REST-Ausfall nicht der gesamte Repo-Dump (> 250k Records)
            # in den Speicher geladen wird und die Schleife garantiert terminiert.
            items = []
            ns = {"oai": "http://www.openarchives.org/OAI/2.0/", "dc": OAI_DC_NS}
            query_lower = query.lower()
            resumption_token: str | None = None
            records_seen = 0
            deadline = time.monotonic() + fallback_time_budget
            for _ in range(OAI_MAX_PAGES):
                if time.monotonic() >= deadline:
                    log.warning(
                        "Module 'econstor': OAI-PMH fallback skipped remaining pages "
                        "-- exceeded fallback time budget of %.1fs, returning %d hit(s) "
                        "so far",
                        fallback_time_budget,
                        len(items),
                    )
                    break
                if resumption_token:
                    oai_params: dict[str, str] = {
                        "verb": "ListRecords",
                        "resumptionToken": resumption_token,
                    }
                else:
                    oai_params = {"verb": "ListRecords", "metadataPrefix": "oai_dc"}
                oai_resp = client.get(
                    "https://www.econstor.eu/oai/request",
                    params=oai_params,
                )
                oai_resp.raise_for_status()
                # Rohe Bytes statt oai_resp.text: httpx dekodiert .text ohne
                # charset-Angabe im Content-Type immer als UTF-8 -- Expat
                # wertet dagegen die <?xml ... encoding="..."?>-Deklaration
                # im Prolog selbst aus (Issue #464 AC1).
                root = ET.fromstring(oai_resp.content)
                page_done = False
                for record in root.findall(".//oai:record", ns):
                    if records_seen >= OAI_MAX_RECORDS or len(items) >= limit:
                        page_done = True
                        break
                    records_seen += 1
                    try:
                        metadata = record.find(".//oai:metadata", ns)
                        if metadata is None:
                            continue
                        dc_el = metadata.find("{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
                        if dc_el is None:
                            continue
                        title_el = dc_el.find(f"{{{OAI_DC_NS}}}title")
                        title = title_el.text if title_el is not None and title_el.text else ""
                        desc_el = dc_el.find(f"{{{OAI_DC_NS}}}description")
                        desc = desc_el.text if desc_el is not None and desc_el.text else ""
                        if query_lower not in title.lower() and query_lower not in desc.lower():
                            continue
                        creators = [
                            c.text for c in dc_el.findall(f"{{{OAI_DC_NS}}}creator") if c.text
                        ]
                        date_el = dc_el.find(f"{{{OAI_DC_NS}}}date")
                        year = None
                        if date_el is not None and date_el.text:
                            year_str = date_el.text[:4]
                            if year_str.isdigit():
                                year = int(year_str)
                        doi = None
                        item_url = None
                        for id_el in dc_el.findall(f"{{{OAI_DC_NS}}}identifier"):
                            if id_el.text and "doi.org" in id_el.text:
                                doi = id_el.text.replace("https://doi.org/", "").replace(
                                    "http://doi.org/", ""
                                )
                            elif id_el.text and id_el.text.startswith("http"):
                                item_url = id_el.text
                        items.append(
                            {
                                "title": title,
                                "authors": creators,
                                "year": year,
                                "abstract": desc,
                                "doi": doi,
                                "url": item_url,
                            }
                        )
                    except Exception:
                        log.warning(
                            "Module 'econstor': skipping malformed OAI record", exc_info=True
                        )
                        continue
                    if len(items) >= limit:
                        page_done = True
                        break
                if page_done or len(items) >= limit or records_seen >= OAI_MAX_RECORDS:
                    break
                token_el = root.find(".//oai:resumptionToken", ns)
                resumption_token = (
                    token_el.text.strip()
                    if token_el is not None and token_el.text and token_el.text.strip()
                    else None
                )
                if not resumption_token:
                    break
    time.sleep(0.5)
    for item in items[:limit]:
        if not isinstance(item, dict):
            log.warning("Module 'econstor': skipping non-dict item %r", item)
            continue
        try:
            results.append(
                normalize_paper(
                    {
                        "doi": item.get("doi"),
                        "title": item.get("title"),
                        "authors": item.get("authors") or [],
                        "year": item.get("year"),
                        "abstract": item.get("abstract"),
                        "venue": "EconStor",
                        "citations": 0,
                        "url": item.get("url"),
                    },
                    "econstor",
                )
            )
        except Exception:
            log.warning("Module 'econstor': skipping malformed item %r", item, exc_info=True)
    return results


def search_arxiv(query: str, limit: int) -> list[dict[str, Any]]:
    """Search arXiv via Atom feed API."""
    url = "https://export.arxiv.org/api/query"
    params: dict[str, str | int] = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    # Rohe Bytes statt resp.text (Issue #464 AC1, siehe Kommentar oben bei
    # search_econstor).
    root = ET.fromstring(resp.content)
    results: list[dict[str, Any]] = []
    for entry in root.findall(f"{{{ARXIV_NS}}}entry"):
        try:
            raw_id = (entry.findtext(f"{{{ARXIV_NS}}}id") or "").strip()
            arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]
            title = (entry.findtext(f"{{{ARXIV_NS}}}title") or "").strip().replace("\n", " ")
            abstract = (entry.findtext(f"{{{ARXIV_NS}}}summary") or "").strip()
            authors = [
                a.findtext(f"{{{ARXIV_NS}}}name") or ""
                for a in entry.findall(f"{{{ARXIV_NS}}}author")
            ]
            published = entry.findtext(f"{{{ARXIV_NS}}}published") or ""
            year = int(published[:4]) if len(published) >= 4 else None
            pdf_url = None
            for link in entry.findall(f"{{{ARXIV_NS}}}link"):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href")
                    break
            if not pdf_url and arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
            results.append(
                normalize_paper(
                    {
                        "doi": f"10.48550/arxiv.{arxiv_id}" if arxiv_id else None,
                        "title": title,
                        "authors": [a for a in authors if a],
                        "year": year,
                        "abstract": abstract,
                        "venue": "arXiv",
                        "citations": 0,
                        "url": pdf_url,
                        "open_access_pdf": pdf_url,
                        # arXiv liefert keinen Typ -- die Quelle ist per
                        # Definition ein Preprint-Server (#892).
                        "publication_type": "preprint",
                    },
                    "arxiv",
                )
            )
        except Exception:
            log.warning("Module 'arxiv': skipping malformed entry", exc_info=True)
    time.sleep(0.5)
    return results


def search_dblp(query: str, limit: int) -> list[dict[str, Any]]:
    """Search DBLP publication API (computer science venues/conferences).

    Pattern adapted from JeanDiable/academic-research-plugin (MIT),
    lib/paper_search.py.
    """
    url = "https://dblp.org/search/publ/api"
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, params={"q": query, "format": "json", "h": limit})
        resp.raise_for_status()
        payload = resp.json()
    time.sleep(0.5)
    hits = payload.get("result", {}).get("hits", {}) or {}
    items = hits.get("hit", []) or []
    results: list[dict[str, Any]] = []
    for item in items:
        info = item.get("info", {}) or {}
        author_data = (info.get("authors") or {}).get("author") or []
        if isinstance(author_data, dict):
            author_data = [author_data]
        authors = [a.get("text") for a in author_data if isinstance(a, dict) and a.get("text")]
        year_raw = info.get("year")
        year = int(year_raw) if year_raw and str(year_raw).isdigit() else None
        venue_raw = info.get("venue")
        venue = venue_raw[0] if isinstance(venue_raw, list) and venue_raw else venue_raw
        ee_raw = info.get("ee")
        if isinstance(ee_raw, list):
            # Mehrere Links (z.B. DOI-Resolver + OA-/arXiv-Kopie): DOI-Link
            # bevorzugen, sonst erstes Element. Analoge Skalar/Array-Quirk
            # wie bei venue/authors.author.
            ee = next((e for e in ee_raw if isinstance(e, str) and "doi.org" in e), None)
            if ee is None:
                ee = ee_raw[0] if ee_raw else None
        else:
            ee = ee_raw
        results.append(
            normalize_paper(
                {
                    "doi": info.get("doi"),
                    "title": info.get("title"),
                    "authors": authors,
                    "year": year,
                    "abstract": None,
                    "venue": venue,
                    "citations": 0,
                    "url": ee or info.get("url"),
                },
                "dblp",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Module registry
# ---------------------------------------------------------------------------

MODULES: dict[str, Callable[[str, int], list[dict[str, Any]]]] = {
    "crossref": search_crossref,
    "openalex": search_openalex,
    "semantic_scholar": search_semantic_scholar,
    "base": search_base,
    "econbiz": search_econbiz,
    "econstor": search_econstor,
    "arxiv": search_arxiv,
    "dblp": search_dblp,
}


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------


def _run_module(
    module_name: str,
    query: str,
    limit: int,
    fn: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> tuple[str, list[dict[str, Any]], bool]:
    """Run one search module, return (name, papers, failed).

    `fn` overrides the MODULES-registry lookup -- used by run_search() to
    bind a narrower fallback_time_budget onto search_econstor() (#465)
    without changing the generic (str, int) -> list[dict] module signature.
    """
    fn = fn or MODULES[module_name]
    max_attempts = 3 if module_name == "semantic_scholar" else 1
    for attempt in range(max_attempts):
        try:
            return module_name, fn(query, limit), False
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < max_attempts - 1:
                delay = 2**attempt * 2
                log.warning("Module '%s' rate-limited, retry in %ds", module_name, delay)
                time.sleep(delay)
                continue
            log.exception("Module '%s' failed (HTTP %s)", module_name, e.response.status_code)
            return module_name, [], True
        except Exception:
            log.exception("Module '%s' failed", module_name)
            return module_name, [], True
    return module_name, [], True


def _module_fn(
    module_name: str, fallback_time_budget: float | None
) -> Callable[[str, int], list[dict[str, Any]]] | None:
    """Bind a narrower OAI-PMH fallback budget onto search_econstor(), if
    requested (#465). Returns None (= use the MODULES-registry default) for
    every other module or when no override is requested."""
    if module_name == "econstor" and fallback_time_budget is not None:
        return functools.partial(search_econstor, fallback_time_budget=fallback_time_budget)
    return None


def run_search(
    query: str,
    modules: list[str],
    limit: int = 50,
    queries_map: dict[str, str] | None = None,
    *,
    time_budget: float | None = None,
    fallback_time_budget: float | None = None,
    skipped_out: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run search across multiple modules in parallel.

    Args:
        query: Default search query.
        modules: List of module names to search.
        limit: Max results per module.
        queries_map: Optional module-specific queries (from query-generator).
        time_budget: Optional overall wall-clock budget in seconds (#465).
            Default None reproduces the old, unbounded blocking behaviour --
            existing callers (e.g. anchor_paper.py) that don't pass this
            keyword are unaffected. Modules still running when the budget
            elapses are reported via `skipped_out`, not `failed`.
        fallback_time_budget: Optional narrower budget forwarded to
            search_econstor()'s OAI-PMH resumptionToken loop.
        skipped_out: Optional output list; module names skipped due to
            `time_budget` are appended here. Kept separate from the return
            value so the 2-tuple return signature stays unchanged (call
            sites like anchor_paper.py unpack `raw_hits, failed = ...`).

    Returns:
        Tuple of (all_papers, failed_modules).
    """
    all_results: list[dict[str, Any]] = []
    failed: list[str] = []

    if time_budget is None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(modules))) as executor:
            futures = []
            for m in modules:
                q = (queries_map or {}).get(m, query)
                fn = _module_fn(m, fallback_time_budget)
                futures.append(executor.submit(_run_module, m, q, limit, fn))
            for future in concurrent.futures.as_completed(futures):
                name, papers, did_fail = future.result()
                all_results.extend(papers)
                if did_fail:
                    failed.append(name)
        return all_results, failed

    # Budget gesetzt: concurrent.futures.wait(..., timeout=...) statt
    # unbegrenztem as_completed(). Nicht fertige Futures werden NICHT per
    # .result() abgewartet, sondern als "skipped" gewertet. shutdown(wait=
    # False, cancel_futures=True) gibt den Aufrufer sofort frei -- ein
    # `with`-Block wuerde beim Exit shutdown(wait=True) rufen und das Budget
    # damit wirkungslos machen.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(modules)))
    future_to_name: dict[concurrent.futures.Future, str] = {}
    try:
        for m in modules:
            q = (queries_map or {}).get(m, query)
            fn = _module_fn(m, fallback_time_budget)
            future = executor.submit(_run_module, m, q, limit, fn)
            future_to_name[future] = m
        done, not_done = concurrent.futures.wait(future_to_name, timeout=time_budget)
        for future in done:
            name, papers, did_fail = future.result()
            all_results.extend(papers)
            if did_fail:
                failed.append(name)
        for future in not_done:
            name = future_to_name[future]
            log.warning(
                "Module '%s' skipped -- exceeded overall time budget of %.1fs",
                name,
                time_budget,
            )
            if skipped_out is not None:
                skipped_out.append(name)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return all_results, failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search multiple academic APIs")
    parser.add_argument("--query", required=True)
    parser.add_argument("--modules", required=True, help="Comma-separated module names")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--queries-file", help="JSON file with module-specific queries")
    parser.add_argument("--output")
    parser.add_argument(
        "--time-budget",
        type=float,
        default=DEFAULT_TIME_BUDGET_S,
        help=(
            "Gesamtzeitbudget in Sekunden ueber alle Module (#465); "
            f"Default: {DEFAULT_TIME_BUDGET_S}"
        ),
    )
    parser.add_argument(
        "--fallback-time-budget",
        type=float,
        default=ECONSTOR_FALLBACK_TIME_BUDGET_S,
        help=(
            "Engeres Zeitbudget in Sekunden fuer den EconStor-OAI-PMH-Fallback "
            f"(#465); Default: {ECONSTOR_FALLBACK_TIME_BUDGET_S}"
        ),
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    requested = [m.strip() for m in args.modules.split(",") if m.strip()]
    invalid = [m for m in requested if m not in MODULES]
    if invalid:
        log.error("Unknown modules: %s", ", ".join(invalid))
        return 1

    queries_map = None
    if args.queries_file:
        try:
            with open(args.queries_file, encoding="utf-8") as fh:
                queries_map = json.load(fh)
        except Exception:
            log.exception("Failed to load queries file")
            return 1

    skipped: list[str] = []
    papers, failed = run_search(
        args.query,
        requested,
        args.limit,
        queries_map,
        time_budget=args.time_budget,
        fallback_time_budget=args.fallback_time_budget,
        skipped_out=skipped,
    )
    papers_per_module = {
        m: sum(1 for p in papers if p.get("source_module") == m) for m in requested
    }
    if failed:
        log.warning(
            "%d/%d modules failed: %s",
            len(failed),
            len(requested),
            ", ".join(sorted(failed)),
        )
    if skipped:
        log.warning(
            "%d/%d modules skipped (time budget of %.1fs exceeded): %s",
            len(skipped),
            len(requested),
            args.time_budget,
            ", ".join(sorted(skipped)),
        )
    log.info(
        "Found %d papers (%d modules failed, %d modules skipped)",
        len(papers),
        len(failed),
        len(skipped),
    )

    output_text = json.dumps(papers, ensure_ascii=False, indent=2)
    if args.output:
        save_json(papers, args.output)
        status = {
            "requested_modules": requested,
            "failed_modules": sorted(failed),
            "skipped_modules": sorted(skipped),
            "papers_per_module": papers_per_module,
        }
        status_path = Path(args.output).with_name(Path(args.output).stem + "_status.json")
        save_json(status, str(status_path))
    else:
        sys.stdout.write(output_text + "\n")

    return 1 if len(failed) + len(skipped) >= len(requested) else 0


if __name__ == "__main__":
    _exit_code = main()
    # #465/#487: run_search()/main() halten das Zeitbudget zuverlaessig ein,
    # aber ein regulaeres sys.exit() (bzw. jeder normale Interpreter-Shutdown)
    # nicht -- concurrent.futures.thread registriert ueber
    # threading._register_atexit() einen globalen Hook (_python_exit), der
    # VOR dem Join aller nicht-Daemon-Threads laeuft und dabei ALLE je
    # gestarteten ThreadPoolExecutor-Worker-Threads joint, unabhaengig davon,
    # ob executor.shutdown(wait=False, cancel_futures=True) schon aufgerufen
    # wurde: cancel_futures=True storniert nur noch nicht gestartete Futures,
    # ein Worker-Thread, der bereits in einem blockierenden Request steckt
    # (die Quelle, die gerade das Budget gerissen hat), laeuft unveraendert
    # weiter und haelt so den Prozessexit auf -- der eigentliche, von
    # commands/search.md abgewartete Aufrufpfad ist genau dieser Prozess,
    # nicht main() als Python-Funktion. os._exit() umgeht den kompletten
    # Interpreter-Finalisierungspfad (inkl. dieses Hooks) und terminiert
    # sofort; stdout/stderr davor flushen, da os._exit() keine Puffer mehr
    # schreibt (main() hat alle Ausgaben zu diesem Zeitpunkt bereits per
    # sys.stdout.write()/save_json()s mit-with-geschlossenem open() erledigt).
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_code)
