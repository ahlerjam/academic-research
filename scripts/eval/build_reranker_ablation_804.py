#!/usr/bin/env python3
"""Live-Generator fuer die Reranker-Ablation (#804).

Fuehrt auf dem #708-Chunk-Goldset die ECHTE Produktions-Chunk-Fusion aus --
``server._vec0_search`` + ``chunk_fts`` ueber ``server._attach_chunk_to_fts_hit``,
``retrieval.reciprocal_rank_fusion`` -- genau wie in
``server.search_papers(rerank=True)`` VOR ``_aggregate_chunks_to_papers`` -- und
wendet den echten lokalen Reranker (``BAAI/bge-reranker-v2-m3`` per
``sentence_transformers.CrossEncoder``) auf die fusionierten Kandidaten an.

Schreibt je Query die fusionierten Kandidaten samt echten ``rerank_score``-Werten
als Fixture unter ``tests/fixtures/reranker_ablation_804/``. Der hermetische
Replay ist ``scripts/eval/run_reranker_ablation_804.py`` -- er sortiert dieselben
Kandidaten zweimal (nach ``rrf_score`` bzw. nach ``rerank_score``) und braucht
dafuer kein Modell.

Dieses Skript laedt das Reranker-Modell und rechnet CPU-Inferenz -- bewusst
kein pytest-Test, sondern manuell ausgefuehrt::

    VAULT_RERANK_LIVE_TEST=1 uv run python scripts/eval/build_reranker_ablation_804.py \\
        --write-live-results docs/evals/2026-08-10-reranker-ablation-804-live-results.json

Latenz und Peak-RSS (AC3) werden je Bedingung ("aus"/"an") in einem EIGENEN
Subprozess gemessen (``--cost-condition aus|an``): ``resource.getrusage().ru_maxrss``
ist pro Prozess monoton steigend -- nur getrennte Prozesse liefern isolierte
Peak-Werte je Bedingung, sonst kontaminiert das Laden des CrossEncoder-Modells
fuer "an" die "aus"-Messung.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    GOLDSET_PATH,
    VECTORS_PATH,
    build_playback_embedder,
    load_goldset,
    load_vectors,
    verify_manifest,
)

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "reranker_ablation_804"
DEFAULT_K = 10
RRF_K = 60

#: Cloud-Reranker-Keys neutralisieren, lokalen Reranker aber AKTIV lassen --
#: das Gegenteil des Env-Guards aus #729 (der schaltet den lokalen Reranker
#: bewusst AB, weil #729 den Reranker nicht misst; #804 misst genau ihn).
_CLOUD_KEYS = ("VOYAGE_API_KEY", "COHERE_API_KEY")


class _CloudKeyGuard:
    """Entfernt Cloud-Reranker-Keys aus der Umgebung, erzwingt den lokalen
    Fallback AKTIV -- unabhaengig vom Produktivdefault (seit #807 AUS), denn
    #804 misst genau den Reranker-Beitrag, nicht den jeweils aktuellen
    Default-Zustand."""

    def __enter__(self) -> _CloudKeyGuard:
        self._prior: dict[str, str | None] = {k: os.environ.pop(k, None) for k in _CLOUD_KEYS}
        self._prior_disable = os.environ.pop("VAULT_RERANK_LOCAL_DISABLE", None)
        self._prior_enabled = os.environ.get("ACADEMIC_RESEARCH_RERANKER_ENABLED")
        os.environ["ACADEMIC_RESEARCH_RERANKER_ENABLED"] = "1"
        return self

    def __exit__(self, *exc: object) -> None:
        for key, value in self._prior.items():
            if value is not None:
                os.environ[key] = value
        if self._prior_disable is not None:
            os.environ["VAULT_RERANK_LOCAL_DISABLE"] = self._prior_disable
        if self._prior_enabled is None:
            os.environ.pop("ACADEMIC_RESEARCH_RERANKER_ENABLED", None)
        else:
            os.environ["ACADEMIC_RESEARCH_RERANKER_ENABLED"] = self._prior_enabled


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def populate_db(db_path: str, goldset: dict, embedder: Any) -> dict[str, str]:
    """Baut die Wegwerf-Vault-DB samt Volltext fuer die lexikalische Seite.

    ``_populate_vault`` (aus #708) liefert das Mapping vault-interne
    Chunk-UUID -> Goldset-``chunk_id`` UND registriert Papers/Chunk-Vektoren.
    Zusaetzlich ``set_fulltext`` je Paper (wie ``run_retrieval_ablation_722.build_db``),
    damit ``papers_fts``/``papers_trgm`` -- die reale lexikalische
    Kandidatenquelle -- ueberhaupt Inhalt zum Durchsuchen hat.
    """
    from academic_vault.db import VaultDB

    from scripts.eval.run_retrieval_chunk_goldset import _populate_vault

    id_map = _populate_vault(db_path, goldset, embedder)

    db = VaultDB(db_path)
    sources_by_doc: dict[str, list[str]] = {}
    for chunk in goldset["chunks"]:
        sources_by_doc.setdefault(chunk["doc_id"], []).append(chunk["chunk_text"])
    for document in goldset["documents"]:
        fulltext = " ".join(sources_by_doc.get(document["doc_id"], []))
        if fulltext.strip():
            db.set_fulltext(document["doc_id"], fulltext)
    return id_map


def _hermetic_env(embedder: Any):
    """Registriert den Playback-Embedder im Prozess-Cache (Muster #729/#731)."""
    from academic_vault import embedding_model

    class _Guard:
        def __enter__(self) -> _Guard:
            self._prior_cache = dict(embedding_model._EMBEDDER_CACHE)
            embedding_model._EMBEDDER_CACHE[embedder.model_id] = embedder
            self._prior_env = os.environ.get("VAULT_EMBEDDING_MODEL")
            os.environ["VAULT_EMBEDDING_MODEL"] = embedder.model_id
            return self

        def __exit__(self, *exc: object) -> None:
            embedding_model._EMBEDDER_CACHE.clear()
            embedding_model._EMBEDDER_CACHE.update(self._prior_cache)
            if self._prior_env is None:
                os.environ.pop("VAULT_EMBEDDING_MODEL", None)
            else:
                os.environ["VAULT_EMBEDDING_MODEL"] = self._prior_env

    return _Guard()


def fuse_query(
    db_path: str, id_map: dict[str, str], raw_query: str, k: int = DEFAULT_K
) -> list[dict]:
    """Reimplementiert exakt den Fusionsteil von ``server.search_papers(rerank=True)``
    VOR ``apply_reranker`` -- ``top_n=k*4``, dieselbe Produktionskonstante wie #727.

    Derselbe vorbestehende FTS5-Komma-Defekt wie in #722/#729
    (``db._sanitize_fts5_query`` haertet kein Komma ab, ``papers_fts``/
    ``papers_trgm`` MATCH bricht dann mit ``sqlite3.OperationalError`` ab) wird
    identisch behandelt: betroffene Query laeuft mit leeren FTS-Treffern
    weiter (rein vektorielle Fusion), kein Laufabbruch.
    """
    import sqlite3

    from academic_vault import server as _server
    from academic_vault.db import VaultDB
    from academic_vault.retrieval import reciprocal_rank_fusion

    sanitized = _server._sanitize_fts5_query(raw_query)
    if not sanitized:
        return []

    _server._ensure_schema_for_read(db_path)
    conn = VaultDB._open(db_path)
    try:
        try:
            fts_results = _server._fts_exact_hits(conn, sanitized, None, k)
            if len(fts_results) < k:
                seen = {r["paper_id"] for r in fts_results}
                for row in _server._fts_trigram_hits(conn, sanitized, None, k):
                    if row["paper_id"] in seen:
                        continue
                    fts_results.append(row)
                    seen.add(row["paper_id"])
                    if len(fts_results) >= k:
                        break
            fts_chunk_results = [
                _server._attach_chunk_to_fts_hit(conn, r, sanitized) for r in fts_results
            ]
        except sqlite3.OperationalError:
            fts_chunk_results = []
    finally:
        conn.close()

    vec_results = _server._vec0_search(db_path, raw_query, k=k)
    fused = reciprocal_rank_fusion(vec_results, fts_chunk_results, k=RRF_K, top_n=k * 4)
    _server._fill_missing_reranker_text(db_path, fused)

    for entry in fused:
        entry["goldset_chunk_id"] = id_map.get(entry["chunk_id"])
    return fused


def build_fixture_for_query(db_path: str, id_map: dict[str, str], query: dict, k: int) -> dict:
    """Fusion + ECHTER lokaler Reranker fuer eine Query (AC1/AC2)."""
    from academic_vault.retrieval import apply_reranker

    fused = fuse_query(db_path, id_map, query["query"], k=k)
    with _CloudKeyGuard():
        reranked = apply_reranker(query=query["query"], candidates=fused)

    candidates = [
        {
            "vault_chunk_id": entry["chunk_id"],
            "goldset_chunk_id": entry.get("goldset_chunk_id"),
            "rrf_score": entry.get("rrf_score", 0.0),
            "rerank_score": entry["rerank_score"],
            "text_sha256": _sha256(entry.get("text") or ""),
            "reranked": entry["reranked"],
            "reranker": entry["reranker"],
        }
        for entry in reranked
    ]
    return {
        "query_id": query["query_id"],
        "lang": query["lang"],
        "case": query["case"],
        "relevant_chunk_ids": query["relevant_chunk_ids"],
        "candidates": candidates,
    }


def _cpu_brand() -> str:
    import subprocess as _sp

    for command in (
        ["sysctl", "-n", "machdep.cpu.brand_string"],
        ["lscpu", "-p=MODELNAME"],
    ):
        try:
            output = _sp.run(command, capture_output=True, text=True, timeout=5)
        except (OSError, _sp.SubprocessError):  # pragma: no cover - Plattformfrage
            continue
        lines = [line for line in output.stdout.splitlines() if line and not line.startswith("#")]
        if output.returncode == 0 and lines:
            return lines[-1].strip()
    return platform.processor() or platform.machine()  # pragma: no cover - Fallback


def hardware_block() -> dict[str, Any]:
    cores = os.cpu_count() or 0
    ram_gb = 0.0
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        ram_gb = round(page_size * pages / 1e9, 1)
    except (ValueError, OSError, AttributeError):  # pragma: no cover - nicht ueberall verfuegbar
        ram_gb = 0.0
    return {
        "cpu": _cpu_brand(),
        "cpu_cores": cores,
        "ram_gb": ram_gb,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "n": 0}

    def _at(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
        return round(ordered[index], 3)

    return {
        "p50": _at(0.50),
        "p95": _at(0.95),
        "mean": round(statistics.fmean(ordered), 3),
        "n": len(ordered),
    }


def _apply_condition_env(condition: str) -> None:
    """Setzt (bzw. raeumt) die Reranker-Env-Variablen fuer eine Kostenmessungs-
    Bedingung -- ausgelagert, damit sich die Zuordnung Bedingung -> Env-Zustand
    isoliert testen laesst (Review-Fund an PR #831).

    "aus" misst seit #807 den ECHTEN Produktivpfad OHNE gesetzten Schalter:
    weder der Alias ``VAULT_RERANK_LOCAL_DISABLE`` (#714) noch der kanonische
    Schalter ``ACADEMIC_RESEARCH_RERANKER_ENABLED`` (#719) werden gesetzt --
    ``resolve_reranker_enabled()`` faellt dann auf den Code-/Config-Default
    zurueck (seit #807 ``False``). Vorher setzte diese Stelle den Alias
    explizit und mass damit den Alias-Disable-Pfad statt des Default-Pfads,
    was der Behauptung "ohne gesetzten Schalter" in PR-Text und
    Verifikations-Report widersprach.

    "an" setzt weiterhin explizit den kanonischen Schalter, weil der
    Produktivdefault seit #807 AUS ist -- ohne das wuerde "an" trotz
    Alias-Pop den neuen Default treffen und zweimal "aus" messen.
    """
    os.environ.pop("VAULT_RERANK_LOCAL_DISABLE", None)
    if condition == "aus":
        os.environ.pop("ACADEMIC_RESEARCH_RERANKER_ENABLED", None)
    else:
        os.environ["ACADEMIC_RESEARCH_RERANKER_ENABLED"] = "1"


def run_cost_condition(condition: str, db_path: str, goldset: dict, vectors: dict, k: int) -> dict:
    """Misst Latenz + Peak-RSS EINER Bedingung ueber den echten Suchpfad
    ``server.search_papers(rerank=True)``. Wird als eigener Subprozess aufgerufen
    (RSS-Isolation, siehe Modul-Docstring).
    """
    from academic_vault import server as _server

    embedder = build_playback_embedder(goldset, vectors)
    with _hermetic_env(embedder), _CloudKeyGuard():
        _apply_condition_env(condition)

        import sqlite3

        search_ms: list[float] = []
        for query in goldset["queries"]:
            started = time.perf_counter()
            try:
                _server.search_papers(db_path, query["query"], k=k, rerank=True)
            except sqlite3.OperationalError:
                # Derselbe vorbestehende FTS5-Komma-Defekt wie in fuse_query()
                # oben (#722/#729-Muster) -- die Latenz dieses fehlgeschlagenen
                # Versuchs zaehlt trotzdem, weil beide Bedingungen ("aus"/"an")
                # identisch betroffen sind und die Vergleichbarkeit sonst litte.
                pass
            search_ms.append((time.perf_counter() - started) * 1000.0)

    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux liefert KB, macOS Bytes (getrusage-Plattformunterschied) -- auf KB
    # normalisieren, damit der Report vergleichbare Zahlen zeigt.
    peak_rss_kb = peak_rss_kb // 1024 if sys.platform == "darwin" else peak_rss_kb
    return {
        "condition": condition,
        "search_ms": _percentiles(search_ms),
        "peak_rss_kb": int(peak_rss_kb),
        "hardware": hardware_block(),
    }


def run_cost_measurement(goldset_path: Path, vectors_path: Path, k: int) -> dict:
    """Baut die DB EINMAL, misst dann beide Bedingungen in getrennten Subprozessen."""
    goldset = load_goldset(goldset_path)
    vectors = dict(load_vectors(vectors_path))
    embedder = build_playback_embedder(goldset, vectors)

    with tempfile.TemporaryDirectory(prefix="reranker-ablation-804-cost-") as tmp:
        db_path = str(Path(tmp) / "cost.db")
        with _hermetic_env(embedder):
            populate_db(db_path, goldset, embedder)

        results: dict[str, dict] = {}
        for condition in ("aus", "an"):
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--cost-condition",
                    condition,
                    "--goldset",
                    str(goldset_path),
                    "--vectors",
                    str(vectors_path),
                    "--db-path",
                    db_path,
                    "--k",
                    str(k),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Kostenmessung ({condition}) fehlgeschlagen (exit {proc.returncode}):\n"
                    f"{proc.stderr}"
                )
            results[condition] = json.loads(proc.stdout)

    hardware = results["aus"]["hardware"]
    if results["an"]["hardware"] != hardware:  # pragma: no cover - dieselbe Maschine
        raise ValueError("Bedingungen liefen auf unterschiedlicher Hardware -- nicht vergleichbar")
    return {
        "aus": {
            "search_ms": results["aus"]["search_ms"],
            "peak_rss_kb": results["aus"]["peak_rss_kb"],
        },
        "an": {
            "search_ms": results["an"]["search_ms"],
            "peak_rss_kb": results["an"]["peak_rss_kb"],
        },
        "hardware": hardware,
    }


def build_all(goldset_path: Path, vectors_path: Path, k: int) -> dict:
    goldset = load_goldset(goldset_path)
    verify_manifest(goldset)
    vectors = dict(load_vectors(vectors_path))
    embedder = build_playback_embedder(goldset, vectors)

    with tempfile.TemporaryDirectory(prefix="reranker-ablation-804-") as tmp:
        db_path = str(Path(tmp) / "quality.db")
        with _hermetic_env(embedder):
            id_map = populate_db(db_path, goldset, embedder)
            per_query = [
                build_fixture_for_query(db_path, id_map, query, k) for query in goldset["queries"]
            ]

    meta: dict[str, Any] = {
        "issue": 804,
        "k": k,
        "rrf_k": RRF_K,
        "reranker_model_id": "BAAI/bge-reranker-v2-m3",
        "goldset_manifest_sha256": goldset["meta"]["manifest_sha256"],
        "generator": "scripts/eval/build_reranker_ablation_804.py",
    }
    meta["fixture_sha256"] = _sha256(json.dumps(per_query, sort_keys=True, ensure_ascii=False))
    return {"meta": meta, "per_query": per_query}


def write_fixture(fixture: dict) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / "candidates.json").write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goldset", type=Path, default=GOLDSET_PATH)
    parser.add_argument("--vectors", type=Path, default=VECTORS_PATH)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--write-live-results",
        type=Path,
        default=None,
        help="Nach dem Fixture-Bau den hermetischen Runner ausfuehren und Rohdaten schreiben.",
    )
    parser.add_argument(
        "--skip-cost", action="store_true", help="AC3 (Latenz/Peak-RSS, Subprozesse) auslassen."
    )
    # Interner Subprozess-Modus fuer die Kostenmessung (RSS-Isolation) --
    # nicht Teil der oeffentlichen Nutzung, siehe run_cost_measurement().
    parser.add_argument(
        "--cost-condition", choices=("aus", "an"), default=None, help=argparse.SUPPRESS
    )
    parser.add_argument("--db-path", type=str, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.cost_condition is not None:
        if args.db_path is None:
            print("--cost-condition setzt --db-path voraus", file=sys.stderr)
            return 2
        goldset = load_goldset(args.goldset)
        vectors = dict(load_vectors(args.vectors))
        result = run_cost_condition(args.cost_condition, args.db_path, goldset, vectors, args.k)
        print(json.dumps(result))
        return 0

    if os.environ.get("VAULT_RERANK_LIVE_TEST") != "1":
        print(
            "VAULT_RERANK_LIVE_TEST=1 setzen -- dieses Skript laedt den lokalen "
            "bge-reranker-v2-m3 und rechnet CPU-Inferenz; es laeuft bewusst nicht "
            "hermetisch.",
            file=sys.stderr,
        )
        return 2

    fixture = build_all(args.goldset, args.vectors, args.k)
    write_fixture(fixture)
    print(
        f"{len(fixture['per_query'])} Queries, Fixture geschrieben nach {FIXTURE_DIR}",
        file=sys.stderr,
    )

    if not args.skip_cost:
        cost = run_cost_measurement(args.goldset, args.vectors, args.k)
        cost_path = FIXTURE_DIR / "cost.json"
        cost_path.write_text(
            json.dumps(cost, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Kostenmessung geschrieben nach {cost_path}", file=sys.stderr)

    if args.write_live_results is not None:
        from scripts.eval.run_reranker_ablation_804 import build_report

        report = build_report(k=args.k)
        args.write_live_results.parent.mkdir(parents=True, exist_ok=True)
        args.write_live_results.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Rohdaten geschrieben: {args.write_live_results}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
