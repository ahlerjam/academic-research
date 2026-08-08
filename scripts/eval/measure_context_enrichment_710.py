#!/usr/bin/env python3
"""Live-Kostenmessung fuer den Kontextsatz-Schreibweg (#710/#784).

Misst den **produktiven** Aufrufpfad -- nicht eine Simulation davon: fuer
jedes Paper wird der echte Subagent ``agents/chunk-context-writer.md`` ueber
``claude -p --output-format json`` gestartet, mit dem echten
``academic-vault``-MCP-Server (echter stdio-Subprozess, echte SQLite-Vault,
echtes ``BAAI/bge-m3``-Embedding) als einzigem Werkzeugzugang. Der Agent
sieht dabei exakt die zwei Tools, die er auch in einer echten
``/academic-research:fetch``-Sitzung haette
(``vault.pending_context_chunks``/``vault.enrich_chunk_contexts``, #783) --
kein hartkodiertes Prompt-Duplikat, keine Kurzschluss-Simulation.

Zwei Blocks, beide unter demselben Gate ``VAULT_CONTEXT_LIVE_TRANSFORM=1``:

``sessions``
    Ein ``claude -p``-Lauf je Paper: die 11 Goldset-Dokumente aus
    ``tests/fixtures/embedding_candidates_731/bge-m3/goldset.json`` (30
    Chunks, das bge-m3-Chunk-Goldset aus #708/#731/#732) PLUS ein echtes
    Paper mit >= 20 Chunks. Erfasst echte ``usage``-Felder (Input-/Output-/
    Cache-Tokens), ``total_cost_usd``, ``duration_ms`` (Wanduhrzeit) und
    ``duration_api_ms`` (reine Modellzeit ohne lokalen Subprozess-Overhead)
    aus dem JSON-Envelope -- keine Schaetzung.

``embed_latency``
    Re-Embedding-Latenz (p50/p95/mean) je Einzeltext, nach dem Muster von
    ``build_embedding_candidates_731.py::embed_with_timing``: dieselben
    ``embedding_text``-Werte, die die Live-Laeufe oben tatsaechlich in den
    Vault geschrieben haben, werden nachtraeglich einzeln (nicht im Batch)
    mit dem echten Produktions-Embedder erneut encodiert und einzeln
    gestoppt.

Das echte Paper wird ueber den echten Produktionspfad eingebettet
(``academic_vault.server.add_paper`` mit ``pdf_path``, derselbe Aufruf wie
in ``commands/fetch.md`` Schritt 2) -- die 11 Goldset-Dokumente haben keine
Quell-PDFs und werden stattdessen direkt ueber ``VaultDB.add_chunk_embedding``
mit dem bereits im #731-Fixture vorhandenen Metadaten-Kontextsatz gesät
(derselbe deterministische Satz, den ``chunking.chunk_pages`` produziert
haette -- keine Abkuerzung im INHALT, nur im Erzeugungsweg der Ausgangsdaten).

**Wichtige Einschraenkung zur Wanduhrzeit:** jeder ``claude -p``-Aufruf
startet einen FRISCHEN ``academic-vault``-MCP-Serverprozess, der das
bge-m3-Embedding-Modell (~2,3 GB) beim ersten Tool-Aufruf laedt. In einer
echten interaktiven Sitzung laeuft dieser Server bereits (ein Ladevorgang
pro Sitzung, nicht pro Paper) -- ``duration_ms`` aus diesem Lauf ist daher
PESSIMISTISCH fuer wiederholte Aufrufe in derselben Sitzung.
``duration_api_ms`` (reine Zeit beim Modell) ist davon unberuehrt und der
tragfaehigere Vergleichswert. Beide werden gemeldet, mit dieser Einordnung.

Nutzung::

    VAULT_CONTEXT_LIVE_TRANSFORM=1 uv run python \\
        scripts/eval/measure_context_enrichment_710.py

Schreibt ``docs/evals/<datum>-context-enrichment-710-live-results.json``
(``--out`` zum Ueberschreiben des Pfads).
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

ENV_GATE = "VAULT_CONTEXT_LIVE_TRANSFORM"

AGENT_PATH = REPO_ROOT / "agents" / "chunk-context-writer.md"
GOLDSET_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "embedding_candidates_731" / "bge-m3" / "goldset.json"
)
DEFAULT_OUT_PATH = (
    REPO_ROOT / "docs" / "evals" / "2026-08-09-context-enrichment-710-live-results.json"
)

#: Modell fuer den Agentenlauf -- wie im produktiven Aufruf aus fetch.md
#: (Session-Agent, keine eigene Modellwahl, hier explizit gesetzt, damit die
#: Messung reproduzierbar bleibt statt vom Default der aufrufenden Sitzung
#: abzuhaengen).
DEFAULT_MODEL = "sonnet"

#: Grosszuegig: der erste Aufruf traegt volle Cache-Erstellung (System-
#: prompt + zwei MCP-Tool-Schemas) UND den MCP-Server-Kaltstart (Modell-
#: laden). Folgeaufrufe sind idR deutlich schneller (Cache-Hit).
CLI_TIMEOUT_S = 420

#: Harte Kostenbremse je Aufruf (Sicherheitsnetz, kein erwarteter Ausloeser --
#: der Smoke-Test kostete rund 0,15 USD fuer 2 Chunks).
MAX_BUDGET_USD_PER_CALL = "3.00"

#: Nur die zwei Tools, die der Agent laut Frontmatter deklariert -- exakt der
#: Zugriff, den ein echter Task()-Dispatch dem Subagenten gewaehren wuerde.
ALLOWED_TOOLS = (
    "mcp__academic-vault__vault_pending_context_chunks",
    "mcp__academic-vault__vault_enrich_chunk_contexts",
)

#: Ein reales Paper mit >= 20 Chunks (AC3). Kein PDF-Fixture im Repo erreicht
#: das (groesstes textfuehrendes Fixture: 13 Chunks, siehe
#: tests/fixtures/chunking/multi_section_paper.pdf) -- deshalb ein oeffentlich
#: zugaengliches arXiv-Paper, nur fuer diesen Live-Lauf heruntergeladen
#: (NICHT ins Repo committet, s. Doku-Bericht fuer die Quelle/Lizenzlage).
REAL_PAPER_ID = "vaswani2017-attention"
REAL_PAPER_URL = "https://arxiv.org/pdf/1706.03762"
REAL_PAPER_TITLE = "Attention Is All You Need"


def _require_gate() -> None:
    if os.environ.get(ENV_GATE) != "1":
        print(
            f"{ENV_GATE}=1 setzen -- dieser Lauf startet echte claude-p-Subprozesse "
            "(Sonnet, echte API-Kosten) und laedt das echte bge-m3-Embedding-Modell.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _percentiles(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"n": 0, "p50": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))], 3),
        "mean": round(statistics.fmean(ordered), 3),
        "max": round(ordered[-1], 3),
    }


def load_agent_system_prompt() -> str:
    """Body von agents/chunk-context-writer.md ohne Frontmatter.

    Das ist EXAKT der Text, den ein echter Task()-Dispatch als Subagenten-
    Systemprompt verwenden wuerde -- kein Duplikat, kein Kurzform-Ersatz.
    """
    text = AGENT_PATH.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"Kein gueltiges Frontmatter in {AGENT_PATH}")
    return match.group(2).strip()


def write_mcp_config(vault_db_path: Path, config_dir: Path) -> Path:
    """MCP-Serverkonfiguration fuer genau EINEN Server: academic-vault.

    Identischer Startbefehl wie .mcp.json im Repo, nur mit VAULT_DB_PATH auf
    die Wegwerf-Vault dieses Laufs gesetzt und ohne Fremdvariablen.
    """
    config = {
        "mcpServers": {
            "academic-vault": {
                "command": sys.executable,
                "args": ["-m", "academic_vault.server"],
                "env": {
                    "PYTHONPATH": str(REPO_ROOT),
                    "VAULT_DB_PATH": str(vault_db_path),
                },
            }
        }
    }
    config_path = config_dir / "mcp_config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def seed_goldset_documents(db_path: str, goldset: dict) -> list[dict[str, Any]]:
    """Saet die 11 Goldset-Dokumente als eigene Papers, Chunks 'pending'.

    Verwendet den bereits im #731-Fixture vorhandenen Metadaten-Kontextsatz
    (``chunk["context_sentence"]``, aus ``chunking.default_context_sentence()``
    erzeugt) -- derselbe Text, den ein echter ``add_paper()``-Aufruf ohne
    Anreicherung geschrieben haette. ``embedding_vector=None``: die Chunks
    sind bewusst noch nicht eingebettet (kein Vektor noetig, um "pending" zu
    sein -- ``pending_context_chunks`` fragt nur ``context_source`` ab).
    """
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    db.init_schema()

    chunks_by_doc: dict[str, list[dict]] = {}
    for chunk in goldset["chunks"]:
        chunks_by_doc.setdefault(chunk["doc_id"], []).append(chunk)
    for chunks in chunks_by_doc.values():
        chunks.sort(key=lambda c: c["chunk_index"])

    papers: list[dict[str, Any]] = []
    for document in goldset["documents"]:
        doc_id = document["doc_id"]
        csl_json = json.dumps(
            {"type": "article-journal", "title": document["title"], "language": document["lang"]}
        )
        db.add_paper(doc_id, csl_json)
        chunks = chunks_by_doc.get(doc_id, [])
        for chunk in chunks:
            db.add_chunk_embedding(
                paper_id=doc_id,
                chunk_text=chunk["chunk_text"],
                context_sentence=chunk["context_sentence"],
                embedding_text=chunk["embedding_text"],
                embedding_vector=None,
                section_title=chunk.get("section_title"),
                page_start=chunk.get("page_start"),
                page_end=chunk.get("page_end"),
                context_source="metadata",
            )
        papers.append({"paper_id": doc_id, "chunk_count": len(chunks), "source": "goldset-731"})
    return papers


def download_real_paper(dest_dir: Path) -> Path:
    """Laedt das reale >=20-Chunk-Paper fuer diesen Lauf (nicht Repo-Bestand)."""
    import urllib.request

    dest = dest_dir / "real_paper.pdf"
    print(f"Lade {REAL_PAPER_URL} ...", file=sys.stderr)
    urllib.request.urlretrieve(REAL_PAPER_URL, dest)  # noqa: S310 - feste, dokumentierte URL
    return dest


def seed_real_paper(db_path: str, pdf_path: Path) -> dict[str, Any]:
    """Saet das reale Paper ueber den ECHTEN Produktionspfad (fetch.md Schritt 2).

    ``academic_vault.server.add_paper`` mit ``pdf_path`` loest Volltext-
    extraktion + Embedding-Ingest aus -- derselbe Aufruf, den
    ``mcp__academic-vault__vault_add_paper`` in einer echten Sitzung macht.
    """
    from academic_vault import server as vault_server
    from academic_vault.db import VaultDB

    csl_json = json.dumps({"type": "article-journal", "title": REAL_PAPER_TITLE, "language": "en"})
    vault_server.add_paper(db_path, REAL_PAPER_ID, csl_json, pdf_path=str(pdf_path))

    db = VaultDB(db_path)
    chunks = db.get_chunk_embeddings(REAL_PAPER_ID)
    if len(chunks) < 20:
        raise RuntimeError(
            f"{REAL_PAPER_ID}: nur {len(chunks)} Chunks eingebettet, AC3 verlangt >= 20 -- "
            "Quelle in REAL_PAPER_URL pruefen/ersetzen."
        )
    return {
        "paper_id": REAL_PAPER_ID,
        "chunk_count": len(chunks),
        "source": REAL_PAPER_URL,
        "title": REAL_PAPER_TITLE,
    }


def call_agent_live(
    paper_id: str, mcp_config_path: Path, system_prompt: str, model: str
) -> dict[str, Any]:
    """Startet den echten chunk-context-writer-Agenten ueber ``claude -p``.

    Returns:
        ``{"paper_id", "duration_ms", "envelope": {...}}`` -- ``envelope``
        ist das vollstaendige JSON-Envelope der CLI (usage, total_cost_usd,
        duration_api_ms, num_turns, result-Text, ...).

    Raises:
        RuntimeError: CLI-Fehlercode, Timeout oder kein valides JSON.
    """
    prompt = f'Input: {{"paper_id": "{paper_id}"}}'
    started = time.perf_counter()
    proc = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--model",
            model,
            "--output-format",
            "json",
            "--system-prompt",
            system_prompt,
            "--mcp-config",
            str(mcp_config_path),
            "--strict-mcp-config",
            "--tools",
            "",
            "--allowedTools",
            ",".join(ALLOWED_TOOLS),
            "--permission-mode",
            "bypassPermissions",
            "--max-budget-usd",
            MAX_BUDGET_USD_PER_CALL,
        ],
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_S,
        cwd=str(REPO_ROOT),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude-CLI fuer {paper_id} endete mit {proc.returncode}: {proc.stderr[-400:]}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"claude-CLI fuer {paper_id} lieferte kein valides JSON: {proc.stdout[:400]!r}"
        ) from exc
    if envelope.get("is_error"):
        raise RuntimeError(f"claude-CLI fuer {paper_id} meldete einen Fehler: {envelope}")
    return {"paper_id": paper_id, "duration_ms": round(elapsed_ms, 2), "envelope": envelope}


def collect_post_state(db_path: str, paper_ids: list[str]) -> dict[str, Any]:
    """Liest nach dem Lauf zurueck: wie viele Chunks tragen context_source='model'."""
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    per_paper: list[dict[str, Any]] = []
    total_chunks = 0
    total_model = 0
    for paper_id in paper_ids:
        chunks = db.get_chunk_embeddings(paper_id)
        model_count = sum(1 for c in chunks if c["context_source"] == "model")
        per_paper.append(
            {
                "paper_id": paper_id,
                "chunk_count": len(chunks),
                "enriched_model": model_count,
                "still_pending": len(chunks) - model_count,
            }
        )
        total_chunks += len(chunks)
        total_model += model_count
    return {
        "per_paper": per_paper,
        "total_chunks": total_chunks,
        "total_enriched_model": total_model,
        "total_still_pending": total_chunks - total_model,
    }


def collect_model_embedding_texts(db_path: str, paper_ids: list[str]) -> list[str]:
    """``embedding_text`` aller inhaltlich angereicherten Chunks (fuer die Latenzmessung)."""
    from academic_vault.db import VaultDB

    db = VaultDB(db_path)
    texts: list[str] = []
    for paper_id in paper_ids:
        for chunk in db.get_chunk_embeddings(paper_id):
            if chunk["context_source"] == "model":
                texts.append(chunk["embedding_text"])
    return texts


#: Warmlauf-Durchgaenge vor der Zeitmessung -- wie in #731 (Lazy-Init des
#: Modell-Backends ist keine ehrliche "Zeit je Chunk").
WARMUP_TEXTS = 2


def measure_reembedding_latency(embedding_texts: list[str]) -> dict[str, Any]:
    """Einzelmessung je Text mit dem echten Produktions-Embedder (Muster #731).

    Bewusst NICHT im Batch (wie ``enrich_chunk_contexts`` es intern tut):
    AC3 verlangt die Latenz JE CHUNK, ein Batch-Mittelwert wuerde das
    verschleiern -- exakt die Begruendung aus
    ``build_embedding_candidates_731.py::embed_with_timing``.
    """
    from academic_vault.embedding_model import get_embedder

    embedder = get_embedder()
    if embedder is None:
        return {"status": "embedder-unavailable", "durations_ms": {}, "model_id": None, "dim": None}

    for text in embedding_texts[:WARMUP_TEXTS]:
        embedder.embed_documents([text])

    durations_ms: list[float] = []
    dim = 0
    for text in embedding_texts:
        started = time.perf_counter()
        vectors = embedder.embed_documents([text])
        durations_ms.append((time.perf_counter() - started) * 1000.0)
        dim = len(vectors[0])

    return {
        "status": "ok",
        "model_id": getattr(embedder, "model_id", None),
        "dim": dim,
        "durations_ms": _percentiles(durations_ms),
    }


def build_report(
    sessions: list[dict[str, Any]],
    post_state: dict[str, Any],
    embed_latency: dict[str, Any],
    goldset_papers: list[dict[str, Any]],
    real_paper: dict[str, Any],
) -> dict[str, Any]:
    usage_totals: dict[str, float] = {}
    total_cost_usd = 0.0
    duration_ms_wall: list[float] = []
    duration_ms_api: list[float] = []
    per_session: list[dict[str, Any]] = []

    for session in sessions:
        envelope = session["envelope"]
        usage = envelope.get("usage", {})
        for key, value in usage.items():
            if isinstance(value, int | float):
                usage_totals[key] = usage_totals.get(key, 0.0) + value
        cost = envelope.get("total_cost_usd") or 0.0
        total_cost_usd += cost
        duration_ms_wall.append(session["duration_ms"])
        duration_ms_api.append(float(envelope.get("duration_api_ms", 0)))
        per_session.append(
            {
                "paper_id": session["paper_id"],
                "duration_ms_wall": session["duration_ms"],
                "duration_api_ms": envelope.get("duration_api_ms"),
                "num_turns": envelope.get("num_turns"),
                "total_cost_usd": cost,
                "usage": usage,
                "session_id": envelope.get("session_id"),
                "result_text": envelope.get("result"),
            }
        )

    return {
        "meta": {
            "issue": 784,
            "epic": 710,
            "generator": "scripts/eval/measure_context_enrichment_710.py",
            "agent_path": "agents/chunk-context-writer.md",
            "transform_model": DEFAULT_MODEL,
            "goldset_manifest_sha256": None,
            "goldset_papers": goldset_papers,
            "real_paper": real_paper,
            "session_count": len(sessions),
            "usage_totals": usage_totals,
            "total_cost_usd": round(total_cost_usd, 6),
            "duration_ms_wall": {
                "method": (
                    "Wanduhrzeit je claude-p-Aufruf, EIN Aufruf je Paper. Enthaelt "
                    "MCP-Server-Kaltstart (bge-m3-Modell laden) -- pessimistisch fuer "
                    "wiederholte Aufrufe in derselben warmen Sitzung, siehe Modul-Docstring."
                ),
                **_percentiles(duration_ms_wall),
            },
            "duration_api_ms": {
                "method": "duration_api_ms aus dem JSON-Envelope -- reine Modellzeit, ohne lokalen Subprozess-/Kaltstart-Overhead.",
                **_percentiles(duration_ms_api),
            },
        },
        "sessions": per_session,
        "post_state": post_state,
        "embed_latency": embed_latency,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args(argv)

    _require_gate()

    goldset = json.loads(GOLDSET_PATH.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="vault-context-enrichment-710-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        vault_db_path = tmp_dir / "vault.db"

        goldset_papers = seed_goldset_documents(str(vault_db_path), goldset)
        print(
            f"{len(goldset_papers)} Goldset-Papers gesaet "
            f"({sum(p['chunk_count'] for p in goldset_papers)} Chunks).",
            file=sys.stderr,
        )

        pdf_path = download_real_paper(tmp_dir)
        real_paper = seed_real_paper(str(vault_db_path), pdf_path)
        print(
            f"Reales Paper gesaet: {real_paper['paper_id']} ({real_paper['chunk_count']} Chunks).",
            file=sys.stderr,
        )

        mcp_config_path = write_mcp_config(vault_db_path, tmp_dir)
        system_prompt = load_agent_system_prompt()

        all_paper_ids = [p["paper_id"] for p in goldset_papers] + [real_paper["paper_id"]]

        cache_path = args.out.with_suffix(".partial.jsonl")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        done: dict[str, dict] = {}
        if cache_path.is_file():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    done[record["paper_id"]] = record
            print(f"{len(done)} Sessions aus dem Cache uebernommen.", file=sys.stderr)

        sessions: list[dict[str, Any]] = []
        for idx, paper_id in enumerate(all_paper_ids, start=1):
            cached = done.get(paper_id)
            if cached is not None:
                sessions.append(cached)
                print(f"[{idx}/{len(all_paper_ids)}] {paper_id}: aus Cache.", file=sys.stderr)
                continue
            session = call_agent_live(paper_id, mcp_config_path, system_prompt, args.model)
            with cache_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(session, ensure_ascii=False) + "\n")
            sessions.append(session)
            envelope = session["envelope"]
            usage = envelope.get("usage", {})
            print(
                f"[{idx}/{len(all_paper_ids)}] {paper_id}: "
                f"{session['duration_ms'] / 1000:.1f}s wall / "
                f"{envelope.get('duration_api_ms', 0) / 1000:.1f}s api, "
                f"in={usage.get('input_tokens', 0)} "
                f"cache_read={usage.get('cache_read_input_tokens', 0)} "
                f"cache_create={usage.get('cache_creation_input_tokens', 0)} "
                f"out={usage.get('output_tokens', 0)}, "
                f"${envelope.get('total_cost_usd', 0):.4f}",
                file=sys.stderr,
                flush=True,
            )

        post_state = collect_post_state(str(vault_db_path), all_paper_ids)
        embedding_texts = collect_model_embedding_texts(str(vault_db_path), all_paper_ids)
        print(f"Re-Embedding-Latenz ueber {len(embedding_texts)} Texte ...", file=sys.stderr)
        embed_latency = measure_reembedding_latency(embedding_texts)

        report = build_report(sessions, post_state, embed_latency, goldset_papers, real_paper)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        cache_path.unlink(missing_ok=True)
        print(f"Rohdaten geschrieben: {args.out}", file=sys.stderr)
        print(
            f"Gesamt: {report['meta']['session_count']} Sessions, "
            f"${report['meta']['total_cost_usd']:.4f}, "
            f"{post_state['total_enriched_model']}/{post_state['total_chunks']} Chunks angereichert.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
