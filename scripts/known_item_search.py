#!/usr/bin/env python3
"""Known-Item-Suche (#886): gezielte Suche nach benannten Grundlagenarbeiten,
zusaetzlich zur thematischen Suche in commands/search.md.

Kandidaten kommen aus zwei Quellen:
  (a) `known_works_queries` aus queries.json (query-generator, #886)
  (b) Zitationsheuristik: die N meistzitierten Treffer der bisherigen
      thematischen Suche (Titel-Query) plus deren haeufigste gemeinsame
      OpenAlex-`referenced_works` (eng begrenzter Lookup, kein Snowballing
      ueber die ganze Menge -- das ist bewusst Out-of-Scope, siehe Issue).

Faellt der query-generator aus (#881: keine queries.json / leeres
known_works_queries), laeuft dieser Schritt trotzdem, nur eben ausschliesslich
mit der Zitationsheuristik -- und sagt das explizit (`fallback_reason`).
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from dedup import deduplicate
from search import _run_module

log = logging.getLogger(__name__)

TIMEOUT = 15.0

FALLBACK_REASON = (
    "query-generator ausgefallen oder known_works_queries leer/fehlend (#881) "
    "-- Kandidaten stammen ausschliesslich aus der Zitationsheuristik "
    "(meistzitierte Treffer der bisherigen thematischen Suche)"
)


def load_known_works_queries(queries_path: str | Path | None) -> list[dict[str, Any]]:
    """Liest `known_works_queries` aus queries.json.

    Fehlende Datei, kaputtes JSON oder fehlendes/leeres Feld sind kein
    Fehler -- leere Liste zurueckgeben, der Aufrufer entscheidet ueber den
    Fallback (#886 AC4)."""
    if not queries_path:
        return []
    path = Path(queries_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    known = data.get("known_works_queries")
    if not isinstance(known, list):
        return []
    return [kw for kw in known if isinstance(kw, dict) and kw.get("query")]


def citation_heuristic_candidates(
    deduped_papers: list[dict[str, Any]], top_n: int = 5
) -> list[dict[str, Any]]:
    """Titel-Kandidaten aus den meistzitierten Treffern der bisherigen Menge."""
    with_titles = [p for p in deduped_papers if p.get("title")]
    top = sorted(with_titles, key=lambda p: int(p.get("citations") or 0), reverse=True)[:top_n]
    return [
        {
            "type": "title",
            "query": p["title"],
            "note": (
                f"meistzitierter Treffer der thematischen Suche "
                f"({int(p.get('citations') or 0)} Zitationen)"
            ),
            "source": "citation_heuristic",
        }
        for p in top
    ]


def _extract_openalex_id(paper: dict[str, Any]) -> str | None:
    url = paper.get("url") or ""
    if "openalex.org/" in url:
        return url.rstrip("/").rsplit("/", 1)[-1]
    return None


def fetch_reference_tally_candidates(
    deduped_papers: list[dict[str, Any]],
    top_n_papers: int = 5,
    top_n_refs: int = 5,
    min_shared: int = 2,
) -> list[dict[str, Any]]:
    """Eng begrenzter Referenz-Lookup: fuer die `top_n_papers` meistzitierten
    OpenAlex-Treffer werden `referenced_works` via OpenAlex geholt, gemeinsame
    Referenzen gezaehlt (mindestens `min_shared` Treffer teilen sie) und die
    haeufigsten `top_n_refs` als Titel-Kandidaten aufgeloest.

    Bewusst auf wenige Top-Treffer begrenzt statt vollstaendiges Snowballing
    ueber die ganze Menge (#886 Scope: Out). Best-effort: jeder Netzwerk-
    oder Parsing-Fehler degradiert auf eine leere Liste, bricht den Schritt
    nicht ab."""
    with_titles = [p for p in deduped_papers if p.get("title")]
    top = sorted(with_titles, key=lambda p: int(p.get("citations") or 0), reverse=True)
    openalex_ids = [oid for p in top if (oid := _extract_openalex_id(p))][:top_n_papers]
    if not openalex_ids:
        return []

    candidates: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            tally: dict[str, int] = {}
            for oid in openalex_ids:
                resp = client.get(f"https://api.openalex.org/works/{oid}")
                if resp.status_code != 200:
                    continue
                for ref in resp.json().get("referenced_works") or []:
                    tally[ref] = tally.get(ref, 0) + 1

            shared = {rid: n for rid, n in tally.items() if n >= min_shared}
            top_refs = sorted(shared.items(), key=lambda kv: kv[1], reverse=True)[:top_n_refs]
            if not top_refs:
                return []

            ids_filter = "|".join(rid.rsplit("/", 1)[-1] for rid, _n in top_refs)
            resp = client.get(
                "https://api.openalex.org/works",
                params={"filter": f"openalex_id:{ids_filter}"},
            )
            if resp.status_code != 200:
                return []
            for item in resp.json().get("results", []):
                title = item.get("title")
                if not title:
                    continue
                shared_by = shared.get(item.get("id", ""), 0)
                candidates.append(
                    {
                        "type": "title",
                        "query": title,
                        "note": f"gemeinsame Referenz von {shared_by} Top-Treffern",
                        "source": "reference_tally",
                    }
                )
    except (httpx.HTTPError, ValueError, KeyError):
        log.warning("Known-Item-Referenz-Lookup fehlgeschlagen", exc_info=True)
        return []
    return candidates


def build_candidates(
    queries_path: str | Path | None,
    deduped_papers: list[dict[str, Any]],
    *,
    max_candidates: int = 8,
    top_n_citations: int = 5,
    include_reference_tally: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    """Baut die Kandidatenliste fuer die Known-Item-Suche.

    Returns:
        (candidates, fallback_reason). `fallback_reason` ist gesetzt, wenn
        `known_works_queries` fehlte/leer war (#881) -- der Schritt laeuft
        trotzdem, nur eben ausschliesslich mit der Zitationsheuristik
        (#886 AC4).
    """
    known = load_known_works_queries(queries_path)
    fallback_reason = None if known else FALLBACK_REASON

    candidates: list[dict[str, Any]] = [
        {
            "type": kw.get("type", "title"),
            "query": kw["query"],
            "note": kw.get("note", ""),
            "source": "known_works_queries",
        }
        for kw in known
    ]
    candidates.extend(citation_heuristic_candidates(deduped_papers, top_n=top_n_citations))
    if include_reference_tally:
        candidates.extend(
            fetch_reference_tally_candidates(deduped_papers, top_n_papers=top_n_citations)
        )

    seen: set[str] = set()
    deduped_candidates: list[dict[str, Any]] = []
    for c in candidates:
        key = (c.get("query") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped_candidates.append(c)

    return deduped_candidates[:max_candidates], fallback_reason


def run_known_item_search(
    candidates: list[dict[str, Any]],
    modules: list[str],
    limit: int = 5,
) -> dict[str, Any]:
    """Fuehrt pro Kandidat eine Modulsuche aus (bestehende `search_*`-
    Funktionen ueber die MODULES-Registry aus `search.py`, keine neue
    HTTP-Logik) und markiert Treffer mit `found_via_known_item=True`.

    Ein Null-Treffer ist ein valides, zu meldendes Ergebnis (#886 AC3) -- er
    landet trotzdem in `searched_for` und als leere Liste in `found[query]`.

    Modulfehler werden als `status: "module_failed"` registriert statt
    verschluckt zu werden (#886 P1).
    """
    searched_for: list[dict[str, Any]] = []
    found: dict[str, dict[str, Any]] = {}  # query -> {hits, status, module_errors}
    all_hits: list[dict[str, Any]] = []

    for candidate in candidates:
        query = candidate["query"]
        searched_for.append(candidate)
        hits: list[dict[str, Any]] = []
        module_errors: dict[str, str] = {}

        for module_name in modules:
            _name, papers, failed = _run_module(module_name, query, limit)
            if failed:
                module_errors[module_name] = "HTTP/network error or timeout"
            hits.extend(papers)

        # Nur known_works_queries badgen, nicht Zitationsheuristik (#886 P1)
        is_known_works = candidate.get("source") == "known_works_queries"
        for paper in hits:
            if is_known_works:
                paper["found_via_known_item"] = True

        status = "module_failed" if module_errors else ("zero_hits" if not hits else "success")
        found[query] = {
            "hits": hits,
            "status": status,
            "module_errors": module_errors if module_errors else None,
        }
        all_hits.extend(hits)

    return {
        "searched_for": searched_for,
        "found": found,
        "papers": all_hits,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Known-Item-Suche (#886)")
    parser.add_argument(
        "--deduped", required=True, help="Pfad zu deduped.json (wird ueberschrieben)"
    )
    parser.add_argument("--queries-file", default=None, help="Pfad zu queries.json (optional)")
    parser.add_argument("--modules", default="crossref,openalex")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--top-n-citations", type=int, default=5)
    parser.add_argument("--no-reference-tally", action="store_true")
    parser.add_argument("--report-output", required=True, help="Pfad fuer den Report (JSON)")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()

    deduped_papers = json.loads(Path(args.deduped).read_text(encoding="utf-8"))
    modules = [m.strip() for m in args.modules.split(",") if m.strip()]

    candidates, fallback_reason = build_candidates(
        args.queries_file,
        deduped_papers,
        max_candidates=args.max_candidates,
        top_n_citations=args.top_n_citations,
        include_reference_tally=not args.no_reference_tally,
    )

    report = run_known_item_search(candidates, modules, limit=args.limit)
    report["fallback_reason"] = fallback_reason
    if fallback_reason:
        log.info("Known-Item-Suche: %s", fallback_reason)
    log.info(
        "Known-Item-Suche: %d Kandidaten durchsucht, %d Treffer gesamt",
        len(report["searched_for"]),
        len(report["papers"]),
    )

    merged = deduplicate(deduped_papers + report["papers"])
    Path(args.deduped).write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report_out = {k: v for k, v in report.items() if k != "papers"}
    Path(args.report_output).write_text(
        json.dumps(report_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report_out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
