#!/usr/bin/env python3
"""Two-level paper deduplication — v4 rewrite.

Level 1: Exact DOI match (after normalization).
Level 2: Fuzzy title similarity (SequenceMatcher, threshold 0.85).

Usage:
  python dedup.py --papers api_results.json --output deduped.json
"""

from __future__ import annotations

import argparse
import bisect
import json
import logging
import re
import sys
from difflib import SequenceMatcher
from typing import Any

from text_utils import load_json, normalize_doi, save_json

log = logging.getLogger(__name__)

# DOI-Praefix, den scripts/search.py::search_arxiv() fuer arXiv-Treffer setzt
# (siehe scripts/arxiv_latex.py::arxiv_id_from_doi() fuer die Referenz-
# Implementierung; hier bewusst lokal nachgebaut statt importiert, um den
# httpx-Import von arxiv_latex.py nicht in dedup.py zu ziehen, #707).
_ARXIV_DOI_PREFIX = "10.48550/arxiv."
_PMID_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.IGNORECASE)
_OPENALEX_URL_RE = re.compile(r"openalex\.org/(w\d+)", re.IGNORECASE)


def _normalize_arxiv_id(paper: dict[str, Any]) -> str | None:
    """arXiv-ID aus optionalem Direkt-Feld, sonst aus der DOI-Konvention
    `10.48550/arxiv.<id>` (#707 AC2)."""
    direct = paper.get("arxiv_id")
    if direct:
        value = str(direct).strip().lower()
        return value or None
    doi = paper.get("doi")
    if doi and doi.startswith(_ARXIV_DOI_PREFIX):
        return doi[len(_ARXIV_DOI_PREFIX) :] or None
    return None


def _normalize_pmid(paper: dict[str, Any]) -> str | None:
    """PMID aus optionalem Direkt-Feld, sonst aus einer
    pubmed.ncbi.nlm.nih.gov-URL (#707 AC2, P2). Kein Producer im Repo befuellt
    aktuell `pmid` direkt — die URL-Konvention ist die praxisnahe Quelle."""
    direct = paper.get("pmid")
    if direct:
        # Prüfe zunächst, ob der Direkt-Wert selbst eine URL ist
        url_match = _PMID_URL_RE.search(str(direct))
        if url_match:
            return url_match.group(1)
        # Sonst: Rohwert
        value = str(direct).strip()
        return value or None
    url = paper.get("url") or ""
    match = _PMID_URL_RE.search(url)
    return match.group(1) if match else None


def _normalize_openalex_id(paper: dict[str, Any]) -> str | None:
    """OpenAlex-ID aus optionalem Direkt-Feld, sonst aus einer
    openalex.org/W<digits>-URL (#707 AC2, P2)."""
    direct = paper.get("openalex_id")
    if direct:
        # Prüfe zunächst, ob der Direkt-Wert selbst eine URL ist
        url_match = _OPENALEX_URL_RE.search(str(direct))
        if url_match:
            return url_match.group(1).upper()
        # Sonst: Rohwert normalisieren
        value = str(direct).strip().upper()
        return value or None
    url = paper.get("url") or ""
    match = _OPENALEX_URL_RE.search(url)
    return match.group(1).upper() if match else None


class _UnionFind:
    """Minimale Union-Find-Struktur fuer die order-unabhaengige
    Dublettenverklumpung (#707 AC1)."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, x: int) -> int:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a


def _non_none_count(paper: dict[str, Any]) -> int:
    """Count non-empty fields for merge selection."""
    count = 0
    for value in paper.values():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        count += 1
    return count


def _title_similarity(a: str, b: str) -> float:
    """Compute title similarity ratio."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _length_bound_ok(la: int, lb: int, threshold: float) -> bool:
    """Notwendiges (nicht hinreichendes) Kriterium dafuer, ob zwei Titel der
    Laengen `la`/`lb` `SequenceMatcher.ratio() >= threshold` ueberhaupt
    erreichen KOENNEN (#890).

    Beweis: `ratio() = 2*M / (len(a)+len(b))` mit `M <= min(len(a), len(b))`
    (M ist die Anzahl uebereinstimmender Zeichen ueber alle Matching-
    Bloecke, kann per Definition nicht groesser sein als der kuerzere der
    beiden Strings). Daraus folgt die obere Schranke
    `ratio() <= 2*min(la,lb) / (la+lb)`. Ein Paar kann `threshold` also nur
    erreichen, wenn `2*min(la,lb) >= threshold*(la+lb)` gilt. Da dies eine
    obere Schranke und keine Heuristik ist, kann kein Paar, das heute
    tatsaechlich gemerged wird, durch diesen Filter verloren gehen — jedes
    `False` hier beweist `ratio() < threshold` fuer JEDE moegliche
    Zeichenfolge dieser Laengen.
    """
    if la <= 0 or lb <= 0:
        return False
    lo, hi = (la, lb) if la <= lb else (lb, la)
    return 2 * lo >= threshold * (lo + hi)


def _blocked_candidate_pairs(
    indices: list[int], titles: list[str], threshold: float
) -> list[tuple[int, int]]:
    """Erzeuge Kandidatenpaare per Laengen-Blocking statt aller `O(n^2)`
    Paare (#890). `indices` sind die zu betrachtenden Positionen (Titel
    ungleich leer), `titles` die vollstaendige Titelliste.

    Die Indizes werden nach Titellaenge sortiert; fuer jeden Index wird nur
    das zusammenhaengende Laengenfenster gescannt, in dem `_length_bound_ok`
    erfuellt sein kann (per `bisect` auf der sortierten Laengenliste statt
    linearem Scan). Rueckgabe: Paare `(i, j)` mit `i, j` aus `indices`, ohne
    Ordnungsgarantie — die Aufrufer-Seite sortiert die Paare anschliessend
    nach der bestehenden `canonical_order`-Position.
    """
    order_by_len = sorted(indices, key=lambda idx: len(titles[idx]))
    lengths = [len(titles[idx]) for idx in order_by_len]
    n = len(order_by_len)
    pairs: list[tuple[int, int]] = []
    for pos in range(n):
        la = lengths[pos]
        if la <= 0:
            continue
        # ratio() <= threshold erfordert lb <= la*(2-threshold)/threshold
        # (Herleitung siehe `_length_bound_ok`-Docstring, la<=lb-Fall).
        upper = la * (2 - threshold) / threshold
        end = bisect.bisect_right(lengths, upper, lo=pos + 1)
        for pos2 in range(pos + 1, end):
            pairs.append((order_by_len[pos], order_by_len[pos2]))
    return pairs


def merge_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge duplicate papers: pick best representative, consolidate fields."""
    best = sorted(
        group,
        key=lambda p: (_non_none_count(p), int(p.get("citations") or 0)),
        reverse=True,
    )[0]
    merged = dict(best)

    # DOI fallback: the "best" record may itself lack a DOI even though another
    # record in the group carries one (e.g. a source without DOI coverage had
    # the most complete metadata otherwise). Never drop a known DOI on merge.
    if not merged.get("doi"):
        for paper in group:
            if paper.get("doi"):
                merged["doi"] = paper["doi"]
                break

    # Consolidate authors from all duplicates
    all_authors: list[str] = []
    for paper in group:
        for author in paper.get("authors") or []:
            if author not in all_authors:
                all_authors.append(author)
    merged["authors"] = all_authors

    # Take max citations
    merged["citations"] = max(int(p.get("citations") or 0) for p in group)

    # Consolidate OA URLs
    for paper in group:
        if not merged.get("oa_url") and paper.get("oa_url"):
            merged["oa_url"] = paper["oa_url"]
        if not merged.get("open_access_pdf") and paper.get("open_access_pdf"):
            merged["open_access_pdf"] = paper["open_access_pdf"]

    # Retraction status: True beats False beats None across the whole group,
    # so a retraction hint from a secondary source is never lost when merged
    # with a more complete but not-yet-flagged record (#618).
    retraction_values = [p.get("is_retracted") for p in group]
    if True in retraction_values:
        merged["is_retracted"] = True
    elif False in retraction_values:
        merged["is_retracted"] = False
    else:
        merged["is_retracted"] = None

    # Track all source modules
    sources = list({p.get("source_module", "") for p in group if p.get("source_module")})
    if len(sources) > 1:
        merged["source_modules"] = sources

    return merged


def _get_cluster_ids(
    cluster_indices: list[int], ids_per_paper: list[dict[str, str | None]]
) -> dict[str, set[str]]:
    """Sammle alle nicht-leeren ID-Werte eines Clusters nach Typ."""
    cluster_ids: dict[str, set[str]] = {
        "doi": set(),
        "arxiv_id": set(),
        "pmid": set(),
        "openalex_id": set(),
    }
    for idx in cluster_indices:
        for id_type in cluster_ids:
            val = ids_per_paper[idx].get(id_type)
            if val:
                cluster_ids[id_type].add(val)
    return cluster_ids


def _cluster_has_conflicting_ids(
    cluster_a: dict[str, set[str]], cluster_b: dict[str, set[str]]
) -> bool:
    """Prüfe, ob zwei ID-Cluster auf Ebene widersprechende KANONISCHE IDs
    tragen: beide Cluster haben nicht-leere Werte desselben ID-Typs, die sich
    unterscheiden (#707 P1).

    Nur DOI und arXiv-ID zaehlen hier — beide identifizieren das Werk selbst,
    eine Differenz belegt tatsaechlich zwei unterschiedliche Publikationen.
    PMID und OpenAlex-ID werden bewusst AUSGENOMMEN: sie sind, wie hier aus
    Treffer-URLs abgeleitet, Record-IDs der jeweiligen Quelle — OpenAlex
    vergibt fuer Preprint und Journalversion desselben Werks zwei
    verschiedene W-IDs, sodass eine disjunkte openalex_id/pmid-Menge KEIN
    Beleg fuer Werk-Verschiedenheit ist. Sie zaehlen weiterhin fuer den
    positiven Union-Schritt (gleicher Wert = Merge), nur eben nicht als
    Konfliktsperre (Regression-Fix nach 4 Review-Runden auf #707, siehe
    PR #758)."""
    for id_type in ("doi", "arxiv_id"):
        ids_a = cluster_a.get(id_type, set())
        ids_b = cluster_b.get(id_type, set())
        # Beide Cluster tragen denselben ID-Typ UND die Wert-Sets sind disjunkt
        if ids_a and ids_b and not ids_a.intersection(ids_b):
            return True
    return False


def _canonical_sort_key(paper: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    """Deterministischer Sortierschluessel fuer Gruppenmitglieder vor
    `merge_group()`. `sorted(..., reverse=True)` in `merge_group()` ist
    stabil — bei einem Tie in (`_non_none_count`, `citations`) gewinnt sonst
    der erste Kandidat in der Reihenfolge von `group`, was ohne diese
    Vorsortierung von der urspruenglichen Eingabereihenfolge abhinge (#707
    AC5). Der letzte Schluessel (voller JSON-Inhalt) ist ein Fallback-
    Tiebreak, wenn DOI/ID/Titel/Quelle bei ansonsten unterschiedlichem Inhalt
    identisch sind."""
    return (
        paper.get("doi") or "",
        _normalize_arxiv_id(paper) or "",
        _normalize_pmid(paper) or "",
        _normalize_openalex_id(paper) or "",
        (paper.get("title") or "").strip().lower(),
        paper.get("source_module") or "",
        json.dumps(paper, sort_keys=True, default=str),
    )


def deduplicate(papers: list[dict[str, Any]], threshold: float = 0.85) -> list[dict[str, Any]]:
    """Deduplicate papers via order-independent Union-Find clustering.

    Level 1 (ID match, exact): papers sharing a normalized DOI, arXiv-ID,
    PMID, or OpenAlex-ID are unioned first — regardless of input order,
    since the grouping runs over identifier *values*, not list position
    (#707 AC1).

    Level 2 (title fallback, fuzzy): the remaining pairs are compared by
    title similarity (`SequenceMatcher`, `threshold`) and unioned pairwise
    (not just against a single representative), so a transitive chain
    A~B, B~C lands in one group even when A and C themselves fall below
    the threshold (#707 AC1). Cross-type rule (cluster-level, #707 P1),
    CANONICAL IDs only: the clusters of i and j are not unioned if they
    carry non-empty DOI or arXiv-ID values that differ — preventing
    transitive merges that lose contradictory work identity (e.g., two
    papers with different DOIs bridged by an ID-less record). PMID and
    OpenAlex-ID are deliberately excluded from this conflict check
    (`_cluster_has_conflicting_ids`) — as derived from hit URLs they are
    per-source record IDs, not work IDs, and OpenAlex assigns a distinct
    W-ID to a preprint and its journal version of the very same work, so a
    disjoint openalex_id/pmid pair is not evidence of two different works
    (regression found and fixed after 4 review rounds, PR #758). They still
    drive the positive Level-1 union when equal. Papers with no ID at all
    keep today's pure title-similarity behavior (#707 AC4).

    Returns deduplicated list.
    """
    working: list[dict[str, Any]] = []
    for paper in papers:
        paper_copy = dict(paper)
        paper_copy["doi"] = normalize_doi(paper.get("doi"))
        working.append(paper_copy)

    count = len(working)
    uf = _UnionFind(count)

    ids_per_paper: list[dict[str, str | None]] = []
    for paper in working:
        ids: dict[str, str | None] = {
            "doi": paper.get("doi"),
            "arxiv_id": _normalize_arxiv_id(paper),
            "pmid": _normalize_pmid(paper),
            "openalex_id": _normalize_openalex_id(paper),
        }
        ids_per_paper.append(ids)

    for id_type in ("doi", "arxiv_id", "pmid", "openalex_id"):
        buckets: dict[str, list[int]] = {}
        for index, ids in enumerate(ids_per_paper):
            value = ids[id_type]
            if value:
                buckets.setdefault(value, []).append(index)
        for indices in buckets.values():
            first = indices[0]
            for other in indices[1:]:
                uf.union(first, other)

    titles = [(paper.get("title") or "").strip() for paper in working]

    # Canonical (content-based, NOT input-position-based) processing order.
    # The greedy merge loop below is order-sensitive: when a bridge record
    # (e.g. an ID-less paper C) is title-similar to two mutually conflicting
    # clusters (A, B with different DOIs), whichever candidate pair is tried
    # FIRST wins the bridge record, since the second attempt is then blocked
    # by the cluster-conflict rule. Enumerating/processing pairs in raw list
    # order made that "first" depend on the caller's input order, breaking
    # order-independence (#707 AC1 regression). Sorting the working indices
    # by `_canonical_sort_key` first — the same deterministic, content-only
    # key already used for representative selection (AC5) — fixes the
    # processing order to the paper *content*, so any permutation of the
    # same paper set produces the identical pair order and therefore the
    # identical final grouping.
    canonical_order = sorted(range(count), key=lambda idx: _canonical_sort_key(working[idx]))
    position = [0] * count
    for pos, idx in enumerate(canonical_order):
        position[idx] = pos

    # Collect candidate pairs (i, j) where titles are similar
    # BEFORE cluster conflict checks (optimization: #707 P1 performance).
    #
    # #890: statt aller `O(n^2)` Paare wird per Laengen-Blocking nur das
    # Fenster gescannt, in dem `SequenceMatcher.ratio() >= threshold`
    # ueberhaupt erreichbar ist (`_length_bound_ok`, mathematisch
    # bewiesenes notwendiges Kriterium — kein heute gefundenes Paar geht
    # dadurch verloren). Fuer die im Fenster verbliebenen Paare filtert
    # zusaetzlich `quick_ratio()` vor (echte Obergrenze fuer `ratio()` laut
    # difflib-Doku: `quick_ratio() >= ratio()` immer), bevor der teure
    # `ratio()`-Aufruf faellt.
    non_empty_indices = [idx for idx in range(count) if titles[idx]]
    blocked_pairs = _blocked_candidate_pairs(non_empty_indices, titles, threshold)

    candidate_pairs: list[tuple[int, int]] = []
    for x, y in blocked_pairs:
        if uf.find(x) == uf.find(y):
            continue
        i, j = (x, y) if position[x] < position[y] else (y, x)
        matcher = SequenceMatcher(None, titles[i].lower(), titles[j].lower())
        if matcher.quick_ratio() < threshold:
            continue
        if matcher.ratio() >= threshold:
            candidate_pairs.append((i, j))

    # Reihenfolge exakt wie die bisherige verschachtelte Schleife: nach
    # `canonical_order`-Position sortiert (a vor b) — haelt die
    # Bridge-Record-Determinismus-Garantie aus #707/PR #758 unveraendert,
    # nur die Paar-*Erzeugung* wird billiger, nicht die Verarbeitungsreihenfolge.
    candidate_pairs.sort(key=lambda pair: (position[pair[0]], position[pair[1]]))

    # Process candidates with cluster-level conflict checking.
    # Cache cluster IDs per root to avoid O(n^3) re-scans.
    cluster_id_cache: dict[int, dict[str, set[str]]] = {}

    for i, j in candidate_pairs:
        # Skip if they've been merged by a previous pair
        root_i, root_j = uf.find(i), uf.find(j)
        if root_i == root_j:
            continue

        # Get or compute cluster IDs
        if root_i not in cluster_id_cache:
            cluster_i_members = [idx for idx in range(count) if uf.find(idx) == root_i]
            cluster_id_cache[root_i] = _get_cluster_ids(cluster_i_members, ids_per_paper)
        if root_j not in cluster_id_cache:
            cluster_j_members = [idx for idx in range(count) if uf.find(idx) == root_j]
            cluster_id_cache[root_j] = _get_cluster_ids(cluster_j_members, ids_per_paper)

        if _cluster_has_conflicting_ids(cluster_id_cache[root_i], cluster_id_cache[root_j]):
            # The clusters have contradictory IDs — do not merge (#707 P1).
            continue

        # Merge and update cache: combine cluster IDs, invalidate old roots
        uf.union(i, j)
        new_root = uf.find(i)
        merged_ids: dict[str, set[str]] = {
            "doi": set(),
            "arxiv_id": set(),
            "pmid": set(),
            "openalex_id": set(),
        }
        for id_type in merged_ids:
            merged_ids[id_type].update(cluster_id_cache[root_i].get(id_type, set()))
            merged_ids[id_type].update(cluster_id_cache[root_j].get(id_type, set()))
        # `_UnionFind.union(i, j)` always re-parents root_j under root_i, so
        # new_root == root_i — pop the stale entries FIRST, then write the
        # merged cache under new_root, or the write would be discarded by
        # its own invalidation on the next line (#707 P2, dead-code fix).
        cluster_id_cache.pop(root_i, None)
        cluster_id_cache.pop(root_j, None)
        cluster_id_cache[new_root] = merged_ids

    clusters: dict[int, list[dict[str, Any]]] = {}
    for index, paper in enumerate(working):
        clusters.setdefault(uf.find(index), []).append(paper)

    deduped = []
    for group in clusters.values():
        group.sort(key=_canonical_sort_key)
        deduped.append(merge_group(group))

    log.info("Dedup: %d → %d papers", len(papers), len(deduped))
    return deduped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deduplicate paper list")
    parser.add_argument("--papers", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threshold", type=float, default=0.85, help="Title similarity threshold")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    try:
        papers = load_json(args.papers)
    except Exception:
        log.exception("Failed to load papers")
        return 1

    deduped = deduplicate(papers, args.threshold)

    try:
        save_json(deduped, args.output)
    except Exception:
        log.exception("Failed to write output")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
