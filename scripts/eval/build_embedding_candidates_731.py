#!/usr/bin/env python3
"""Live-Generator fuer den Embedding-Kandidatenvergleich (#731).

Erzeugt je Kandidat aus ``tests/fixtures/retrieval_goldset_chunks_708/sources.json``:

* ``tests/fixtures/embedding_candidates_731/<key>/goldset.json`` — Chunks (ueber
  ``chunking.chunk_pages`` mit dem **eigenen** Tokenizer des Kandidaten und
  Kontextsatz), Queries mit neu aufgeloesten ``relevant_chunk_ids``, die
  aufgezeichneten Tokenzaehlungen sowie Zeit-, Groessen- und Hardware-Meta.
* ``tests/fixtures/embedding_candidates_731/<key>/vectors.json`` — base64-
  kodierte float32-Vektoren fuer Chunks und Queries.

Dieses Skript laeuft **nicht** hermetisch: es laedt rund 7 GB Modellgewichte
und rechnet auf der CPU (Qwen3-Embedding-0.6B liegt bei rund 2 s je Chunk).
Es ist deshalb bewusst kein pytest-Test, sondern wird manuell ausgefuehrt::

    VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_embedding_candidates_731.py

Der hermetische Lauf gegen das Ergebnis ist
``scripts/eval/run_embedding_candidates_731.py``; dessen Ausgabe gehoert als
``docs/evals/2026-08-08-embedding-candidates-731-live-results.json`` ins Repo
(``--write-live-results``).

Bewusste Festlegungen:

* **CPU, nicht MPS/CUDA.** AC3 verlangt CPU-Zahlen; ``device="cpu"`` wird
  explizit gesetzt und der Geraetezustand im Hardware-Block festgehalten.
* **Kein stiller Naeherungs-Fallback.** Ist der Tokenizer eines Kandidaten
  nicht ladbar, bricht der Lauf ab. ``chunk_pages`` wuerde sonst mit
  ``approximate_token_count`` weiterchunken — die Messung waere heimlich eine
  andere.
* **Prompting je Kandidat.** Siehe ``CandidateConfig.prompting_note`` im
  Runner: der ``passage:``-Praefix gehoert zur e5-Familie, nicht zu BGE-M3
  oder Qwen3.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_embedding_candidates_731 import (  # noqa: E402
    CANDIDATES,
    FIXTURE_DIR,
    LIVE_RESULTS_PATH,
    CandidateConfig,
    build_report,
    token_key,
)
from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    compute_manifest_sha256,
    encode_vector,
    load_sources,
)

#: Warmlauf-Durchgaenge vor der Zeitmessung. Der erste Encode eines Modells
#: enthaelt Lazy-Init von torch und ist als "Zeit je Chunk" nicht ehrlich.
WARMUP_TEXTS = 2


class TokenizerNotLoadableError(RuntimeError):
    """Der Tokenizer eines Kandidaten liess sich nicht laden (#731).

    Harter Abbruch statt Naeherung: ``chunk_pages`` faellt sonst still auf
    ``approximate_token_count`` zurueck, und der Lauf misst andere
    Chunkgrenzen, als er behauptet.
    """


class RecordingTokenCounter:
    """Zaehlt Tokens mit dem echten Tokenizer und zeichnet jeden Aufruf auf."""

    def __init__(self, counter: Any) -> None:
        self._counter = counter
        self.counts: dict[str, int] = {}

    def __call__(self, text: str) -> int:
        value = int(self._counter(text))
        self.counts[token_key(text)] = value
        return value


def load_token_counter(model_id: str) -> RecordingTokenCounter:
    """Echter Tokenizer des Kandidaten, aufzeichnend. Bricht ab, wenn nicht ladbar."""
    from academic_vault.chunking import model_token_counter

    counter = model_token_counter(model_id)
    if counter is None:
        raise TokenizerNotLoadableError(
            f"Tokenizer fuer {model_id} nicht ladbar. Ohne ihn wuerde chunk_pages "
            "genaehert chunken und die Messung waere eine andere — Abbruch statt "
            "stillem Fallback."
        )
    return RecordingTokenCounter(counter)


def build_chunks(sources: dict, counter: RecordingTokenCounter) -> list[dict[str, Any]]:
    """Zerlegt jedes Quelldokument mit dem Tokenizer DIESES Kandidaten."""
    from academic_vault.chunking import chunk_pages

    records: list[dict[str, Any]] = []
    for document in sources["documents"]:
        pages = [(int(number), text) for number, text in document["pages"]]
        for chunk in chunk_pages(pages, token_counter=counter):
            records.append(
                {
                    "chunk_id": f"{document['doc_id']}#{chunk.chunk_index}",
                    "doc_id": document["doc_id"],
                    "lang": document["lang"],
                    "chunk_index": chunk.chunk_index,
                    "chunk_text": chunk.chunk_text,
                    "context_sentence": chunk.context_sentence,
                    "embedding_text": chunk.embedding_text,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section_title": chunk.section_title,
                    "word_count": len(chunk.chunk_text.split()),
                }
            )
    return records


def load_model(cfg: CandidateConfig) -> Any:
    """Laedt das Modell ausdruecklich auf der CPU (AC3)."""
    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, Any] = {"device": "cpu", **cfg.load_kwargs}
    if cfg.truncate_dim is not None:
        kwargs["truncate_dim"] = cfg.truncate_dim
    if cfg.trust_remote_code:
        kwargs["trust_remote_code"] = True
    return SentenceTransformer(cfg.model_id, **kwargs)


def _encode_one(model: Any, text: str, prompt_name: str | None) -> list[float]:
    from academic_vault.embedding_model import l2_normalize

    kwargs: dict[str, Any] = {"normalize_embeddings": True, "show_progress_bar": False}
    if prompt_name:
        kwargs["prompt_name"] = prompt_name
    raw = model.encode([text], **kwargs)
    return l2_normalize(list(raw[0]))


def embed_with_timing(
    model: Any,
    cfg: CandidateConfig,
    chunks: list[dict],
    queries: list[dict],
) -> tuple[dict[str, str], dict[str, str], list[float], int]:
    """Bettet Chunks und Queries ein und misst die Zeit je Einzeltext.

    Einzeln statt im Batch, weil AC3 nach der Zeit **je Chunk** fragt und ein
    Batch-Mittelwert die Latenz eines einzelnen Ingest-Schritts verschleiern
    wuerde.
    """
    for text in [c["embedding_text"] for c in chunks][:WARMUP_TEXTS]:
        _encode_one(model, cfg.passage_prefix + text, None)

    encoded_chunks: dict[str, str] = {}
    index_ms: list[float] = []
    dim = 0
    for chunk in chunks:
        started = time.perf_counter()
        vector = _encode_one(model, cfg.passage_prefix + chunk["embedding_text"], None)
        index_ms.append((time.perf_counter() - started) * 1000.0)
        encoded_chunks[chunk["chunk_id"]] = encode_vector(vector)
        dim = len(vector)

    encoded_queries = {
        query["query_id"]: encode_vector(
            _encode_one(model, cfg.query_prefix + query["query"], cfg.query_prompt_name)
        )
        for query in queries
    }
    return encoded_chunks, encoded_queries, index_ms, dim


def measure_download_bytes(model_id: str) -> tuple[int, str]:
    """Groesse der Dateien, die dieser Kandidat tatsaechlich braucht.

    Gemessen wird der aufgeloeste HuggingFace-Snapshot, aus dem
    ``sentence-transformers`` laedt — ohne die optionale ONNX-Variante und ohne
    die doppelt vorgehaltenen Gewichte (``pytorch_model.bin`` neben
    ``model.safetensors`` zaehlen einmal). Gegenprobe zu den HF-API-Zahlen aus
    #730 steht im Report.
    """
    from huggingface_hub import snapshot_download

    root = Path(snapshot_download(model_id, local_files_only=True))
    by_name: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith("onnx/") or relative.startswith("openvino/"):
            continue
        by_name[relative] = path.resolve().stat().st_size
    if "model.safetensors" in by_name:
        by_name.pop("pytorch_model.bin", None)
    return sum(by_name.values()), str(root)


def _cpu_brand() -> str:
    """Handelsname der CPU, so weit die Plattform ihn hergibt.

    ``platform.processor()`` liefert auf Apple Silicon nur ``arm`` — als
    Messhardware-Angabe (AC3) waere das wertlos.
    """
    import subprocess

    for command in (
        ["sysctl", "-n", "machdep.cpu.brand_string"],
        ["lscpu", "-p=MODELNAME"],
    ):
        try:
            output = subprocess.run(command, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - Plattformfrage
            continue
        lines = [line for line in output.stdout.splitlines() if line and not line.startswith("#")]
        if output.returncode == 0 and lines:
            return lines[-1].strip()
    return platform.processor() or platform.machine()  # pragma: no cover - Fallback


def hardware_block() -> dict[str, Any]:
    """Messhardware und Geraetezustand — ohne das ist keine Zeit ueberpruefbar."""
    import torch

    try:
        mps_available = bool(torch.backends.mps.is_available())
    except Exception:  # pragma: no cover - Plattformen ohne MPS-Backend
        mps_available = False

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
        "torch": torch.__version__,
        "device": "cpu",
        "cuda_available": bool(torch.cuda.is_available()),
        "mps_available": mps_available,
        "mps_used": False,
    }


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def _at(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round(fraction * len(ordered) + 0.5) - 1))
        return round(ordered[index], 3)

    return {
        "p50": _at(0.50),
        "p95": _at(0.95),
        "mean": round(statistics.fmean(ordered), 3),
        "n": len(ordered),
    }


def build_candidate(cfg: CandidateConfig, sources: dict, hardware: dict) -> tuple[dict, dict]:
    """Erzeugt Goldset- und Vektor-Fixture eines Kandidaten."""
    from scripts.eval.build_retrieval_chunk_goldset import resolve_anchors

    counter = load_token_counter(cfg.model_id)
    chunks = build_chunks(sources, counter)
    queries = resolve_anchors(chunks, sources)

    model = load_model(cfg)
    encoded_chunks, encoded_queries, index_ms, dim = embed_with_timing(model, cfg, chunks, queries)
    download_bytes, download_source = measure_download_bytes(cfg.model_id)

    manifest = compute_manifest_sha256(
        [c["embedding_text"] for c in chunks],
        [q["query"] for q in queries],
        cfg.model_id,
        dim,
    )
    meta = {
        "issue": 731,
        "candidate": cfg.key,
        "model_id": cfg.model_id,
        "dim": dim,
        "truncate_dim": cfg.truncate_dim,
        "prompting": {
            "query_prefix": cfg.query_prefix,
            "passage_prefix": cfg.passage_prefix,
            "query_prompt_name": cfg.query_prompt_name,
            "note": cfg.prompting_note,
        },
        "generator": "scripts/eval/build_embedding_candidates_731.py",
        "download_bytes": download_bytes,
        "download_source": download_source,
        "index_ms_per_chunk": _percentiles(index_ms),
        "hardware": hardware,
        "manifest_sha256": manifest,
        "token_counts": dict(sorted(counter.counts.items())),
    }
    goldset = {
        "meta": meta,
        "documents": [
            {"doc_id": d["doc_id"], "lang": d["lang"], "title": d["title"]}
            for d in sources["documents"]
        ],
        "chunks": chunks,
        "queries": queries,
    }
    vectors = {
        "candidate": cfg.key,
        "model_id": cfg.model_id,
        "dim": dim,
        "manifest_sha256": manifest,
        "chunks": encoded_chunks,
        "queries": encoded_queries,
    }
    return goldset, vectors


def write_candidate(key: str, goldset: dict, vectors: dict) -> None:
    directory = FIXTURE_DIR / key
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "goldset.json").write_text(
        json.dumps(goldset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (directory / "vectors.json").write_text(json.dumps(vectors, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        choices=sorted(CANDIDATES),
        action="append",
        dest="candidates",
        help="Nur diesen Kandidaten neu bauen (mehrfach angebbar). Default: alle.",
    )
    parser.add_argument(
        "--write-live-results",
        action="store_true",
        help="Nach dem Bau den hermetischen Lauf fahren und die Rohdaten schreiben.",
    )
    args = parser.parse_args(argv)

    if os.environ.get("VAULT_E5_LIVE_TEST") != "1":
        print(
            "VAULT_E5_LIVE_TEST=1 setzen — dieses Skript laedt rund 7 GB Modelle "
            "und rechnet auf der CPU; es laeuft bewusst nicht hermetisch.",
            file=sys.stderr,
        )
        return 2

    sources = load_sources()
    hardware = hardware_block()
    for key in args.candidates or list(CANDIDATES):
        print(f"--- {key} ({CANDIDATES[key].model_id}) ---", file=sys.stderr)
        goldset, vectors = build_candidate(CANDIDATES[key], sources, hardware)
        write_candidate(key, goldset, vectors)
        meta = goldset["meta"]
        print(
            f"{len(goldset['chunks'])} Chunks, {meta['dim']}d, "
            f"index p50 {meta['index_ms_per_chunk']['p50']} ms/Chunk, "
            f"Download {meta['download_bytes'] / 1e9:.2f} GB",
            file=sys.stderr,
        )

    if args.write_live_results:
        report = build_report()
        LIVE_RESULTS_PATH.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Rohdaten geschrieben: {LIVE_RESULTS_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
