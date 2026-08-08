#!/usr/bin/env python3
"""Fixture-Generator fuer den Kontextsatz-Vergleich (#785/#710-C).

Zwei Stufen, beide bewusst **nicht** hermetisch und deshalb opt-in -- nach dem
Muster von ``scripts/eval/build_hyde_multiquery_fixture.py`` (#733):

``--stage sentences`` (Gate ``VAULT_CONTEXT_LIVE_TRANSFORM=1``)
    Ruft je Goldset-**Dokument** einmal die eingeloggte ``claude``-CLI auf
    (``--output-format json``, echte ``usage``-Felder), mit ALLEN Chunks dieses
    Dokuments in Lesereihenfolge im Prompt. Das Modell schreibt zu jedem Chunk
    zwei Saetze: einen inhaltlichen Kontextsatz in der Sprache des Chunks
    (``sentence``, hoechstens 25 Woerter) und DENSELBEN Inhalt auf Deutsch
    erzwungen (``sentence_de``) -- Letzteres isoliert den Sprach-Confound
    gegenueber dem immer-deutschen Metadaten-Satz (siehe
    ``run_context_ablation_710.py``-Modul-Docstring). Schreibt ``sentences.json``.

``--stage vectors`` (Gate ``VAULT_E5_LIVE_TEST=1``)
    Embeddet drei der vier Arme (``no_context``, ``model_context``,
    ``model_context_de``) mit dem echten ``BAAI/bge-m3``-Modell, CPU-erzwungen
    -- exakt wie ``build_embedding_candidates_731.py``. Der vierte Arm
    (``metadata_context``) wird NICHT neu embedded: er uebernimmt die bereits
    eingecheckten #731-bge-m3-Vektoren fuer Chunks UND Queries unveraendert --
    Grundlage des Kontrolltests in ``run_context_ablation_710.py``. Schreibt
    ``vectors.json`` mit ``manifest_sha256``.

Der Messlauf gegen das Ergebnis ist ``scripts/eval/run_context_ablation_710.py``
und braucht weder Netz noch Modell.

Nutzung::

    VAULT_CONTEXT_LIVE_TRANSFORM=1 uv run python \\
        scripts/eval/build_context_sentences_710.py --stage sentences
    VAULT_E5_LIVE_TEST=1 uv run python \\
        scripts/eval/build_context_sentences_710.py --stage vectors
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_context_ablation_710 import (  # noqa: E402
    ARMS,
    BGE_M3_CANDIDATE,
    MAX_SENTENCE_WORDS,
    MODEL_ID,
    SENTENCES_PATH,
    VECTORS_PATH,
    build_arm_texts,
    compute_context_manifest_sha256,
    load_base_goldset,
)
from scripts.eval.run_embedding_candidates_731 import load_candidate_fixture  # noqa: E402
from scripts.eval.run_retrieval_chunk_goldset import encode_vector  # noqa: E402

SENTENCE_ENV_GATE = "VAULT_CONTEXT_LIVE_TRANSFORM"
EMBED_ENV_GATE = "VAULT_E5_LIVE_TEST"

#: Modell fuer die Kontextsatz-Erzeugung (wie #733/#734: Sonnet ueber die
#: eingeloggte CLI-Sitzung, kein API-Key -- #632).
DEFAULT_TRANSFORM_MODEL = "sonnet"

CLI_TIMEOUT_S = 240

#: Hoeher als bei #733 (3): die 25-Woerter-Grenze wird trotz expliziter
#: Prompt-Anweisung im Referenzlauf gelegentlich um 1-3 Woerter gerissen --
#: mehr Versuche statt einer aufgeweichten Grenze (die Grenze steht im
#: #710-Plan-Kommentar, keine Ermessensfrage dieses Skripts).
MAX_ATTEMPTS = 6

#: Der einzige Arm, der beim ``vectors``-Stage NICHT neu embedded wird --
#: siehe Modul-Docstring.
COPIED_ARM = "metadata_context"
LIVE_EMBED_ARMS = tuple(arm for arm in ARMS if arm != COPIED_ARM)

SENTENCE_METHOD = (
    "Wanduhrzeit je `claude -p`-Aufruf (CLI-Subprozess, eingeloggte OAuth-Sitzung, "
    "--output-format json), ein Aufruf je Goldset-Dokument (alle Chunks des Dokuments "
    "in einem Prompt, in Lesereihenfolge), serieller Lauf. Bei einer verworfenen "
    "Antwort zaehlt der erfolgreiche Versuch (`attempts` je Dokument)."
)
EMBED_METHOD = (
    "Wanduhrzeit je Einzel-Embedding mit BAAI/bge-m3 auf der CPU (device='cpu', wie "
    "#731), Modellladen nicht eingerechnet, gemessen auf der Maschine des Generatorlaufs."
)

CONTEXT_SENTENCE_PROMPT_TEMPLATE = """Du bekommst alle Textabschnitte (Chunks) eines wissenschaftlichen Papers in Lesereihenfolge. Paper-Titel: {title}

Schreibe zu JEDEM Chunk genau zwei kurze Kontextsaetze:

1. "sentence": ein INHALTLICHER Kontextsatz in der Sprache des Chunks ({lang}) \
-- STRENG hoechstens 25 Woerter (zaehle nach, bevor du antwortest; ein Wort \
ist durch Leerzeichen getrennt, ein Bindestrich-/Gedankenstrich-Kompositum \
zaehlt als ein Wort). Sag, WAS der Abschnitt inhaltlich behauptet oder \
untersucht (z. B. "Der Abschnitt argumentiert, dass ..." oder die englische \
Entsprechung) -- NICHT "Abschnitt X aus Paper Y" oder eine reine \
Herkunftsangabe ohne Inhalt. Lieber ein Wort zu knapp als eines zu viel: \
kuerze im Zweifel einen Nebensatz weg, statt die Grenze zu reissen.
2. "sentence_de": DERSELBE Inhalt wie "sentence", aber auf Deutsch -- auch \
dann, wenn der Chunk selbst schon deutsch ist (dann sind beide Saetze \
inhaltsgleich, nur einmal gebraucht). Ebenfalls STRENG hoechstens 25 Woerter, \
nachgezaehlt.

Chunks (chunk_index: Text):
{chunks_block}

Gib AUSSCHLIESSLICH ein JSON-Array aus -- ein Objekt je Chunk, in genau dieser \
Form, ohne Codeblock-Markierung (keine ```), ohne Einleitung, ohne Nachsatz:
[{{"chunk_index": 0, "sentence": "...", "sentence_de": "..."}}, ...]

Das Array muss genau {n} Eintraege haben, chunk_index von 0 bis {n_minus_1}, \
in dieser Reihenfolge."""


def build_chunks_block(chunks: list[dict]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(f"--- chunk_index {chunk['chunk_index']} ---\n{chunk['chunk_text']}")
    return "\n\n".join(parts)


def context_sentence_prompt(doc_id: str, title: str, lang: str, chunks: list[dict]) -> str:
    return CONTEXT_SENTENCE_PROMPT_TEMPLATE.format(
        title=title or doc_id,
        lang=lang,
        chunks_block=build_chunks_block(chunks),
        n=len(chunks),
        n_minus_1=len(chunks) - 1,
    )


def _extract_json_array(text: str) -> Any | None:
    """Findet und parst das erste valide JSON-Array im Antworttext.

    Modelle halten sich trotz Prompt gelegentlich nicht an "nur das Array":
    Codeblock-Zaeune, eine Einleitung, oder -- beobachtet im Referenzlauf --
    eine nachtraegliche Selbstkorrektur ("Ich korrigiere das Format...") mit
    einem ZWEITEN Array danach. ``json.loads`` auf dem Gesamttext scheitert an
    jedem dieser Zusaetze. ``raw_decode`` ab der ersten ``[`` ignoriert alles,
    was NACH dem ersten vollstaendigen Array kommt (das gewaehlte, nicht die
    Korrektur) -- scheitert der Versuch an dieser Stelle, wird ab der naechsten
    ``[`` weitergesucht.
    """
    decoder = json.JSONDecoder()
    idx = text.find("[")
    while idx != -1:
        try:
            obj, _end = decoder.raw_decode(text, idx)
            return obj
        except json.JSONDecodeError:
            idx = text.find("[", idx + 1)
    return None


def call_claude_cli_json(prompt: str, model: str) -> tuple[dict, float]:
    """Ruft ``claude -p --output-format json`` und liefert das Envelope samt Dauer.

    Returns:
        ``(JSON-Envelope, Wanduhrzeit in ms)``. Das Envelope traegt u. a.
        ``result`` (Antworttext), ``usage`` (echte Token-/Kostenfelder),
        ``total_cost_usd``, ``duration_ms``, ``session_id``.

    Raises:
        RuntimeError: Die CLI endet mit einem Fehler oder liefert kein valides JSON.
    """
    started = time.perf_counter()
    proc = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT_S,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if proc.returncode != 0:
        raise RuntimeError(f"claude-CLI endete mit {proc.returncode}: {proc.stderr[-400:]}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"claude-CLI lieferte kein valides JSON: {proc.stdout[:400]!r}") from exc
    if envelope.get("is_error"):
        raise RuntimeError(f"claude-CLI meldete einen Fehler: {envelope}")
    return envelope, elapsed_ms


def _validate_sentences(answer: str, chunks: list[dict]) -> dict[int, dict[str, str]] | None:
    """Parst und prueft die Modellantwort. ``None`` bei jeder Regelverletzung (Retry)."""
    data = _extract_json_array(answer)
    if not isinstance(data, list) or len(data) != len(chunks):
        return None
    expected_indices = {c["chunk_index"] for c in chunks}
    by_index: dict[int, dict[str, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            return None
        idx = item.get("chunk_index")
        sentence = item.get("sentence")
        sentence_de = item.get("sentence_de")
        if (
            not isinstance(idx, int)
            or not isinstance(sentence, str)
            or not isinstance(sentence_de, str)
        ):
            return None
        sentence = " ".join(sentence.split())
        sentence_de = " ".join(sentence_de.split())
        if not sentence or not sentence_de:
            return None
        if (
            len(sentence.split()) > MAX_SENTENCE_WORDS
            or len(sentence_de.split()) > MAX_SENTENCE_WORDS
        ):
            return None
        by_index[idx] = {"sentence": sentence, "sentence_de": sentence_de}
    if set(by_index) != expected_indices:
        return None
    return by_index


def transform_one_document(document: dict, chunks: list[dict], model: str) -> dict[str, Any]:
    """Erzeugt Kontextsaetze fuer ALLE Chunks EINES Dokuments in einem Aufruf."""
    prompt = context_sentence_prompt(
        document["doc_id"], document.get("title", ""), document["lang"], chunks
    )
    last_answer = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        envelope, elapsed_ms = call_claude_cli_json(prompt, model)
        answer = envelope.get("result", "")
        last_answer = answer
        parsed = _validate_sentences(answer, chunks)
        if parsed is not None:
            return {
                "doc_id": document["doc_id"],
                "by_index": parsed,
                "duration_ms": round(elapsed_ms, 2),
                "attempts": attempt,
                "session_id": envelope.get("session_id"),
                "total_cost_usd": envelope.get("total_cost_usd"),
                "usage": envelope.get("usage", {}),
            }
        print(
            f"  Versuch {attempt} fuer {document['doc_id']} verworfen: {last_answer[:160]!r}",
            file=sys.stderr,
        )
    raise RuntimeError(
        f"{document['doc_id']}: {MAX_ATTEMPTS} Versuche ohne brauchbare Antwort: {last_answer!r}"
    )


def _percentiles(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"n": 0, "p50": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))], 2),
        "mean": round(statistics.fmean(ordered), 2),
        "max": round(ordered[-1], 2),
    }


def build_sentences(goldset: dict, model: str, cache_path: Path | None = None) -> dict[str, Any]:
    """Erzeugt die Kontextsaetze fuer alle Dokumente. Cached je Dokument fuer einen Resume."""
    done: dict[str, dict] = {}
    if cache_path is not None and cache_path.is_file():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                # JSON-Objektschluessel sind immer Strings -- record["by_index"]
                # kommt aus transform_one_document() mit int-Schluesseln (siehe
                # _validate_sentences) und muss nach dem Roundtrip durch
                # json.dumps/json.loads zurueckgewandelt werden. Sonst schlaegt
                # der Lesepfad unten (Zugriff mit chunk["chunk_index"], ein int)
                # mit KeyError fehl, sobald ein Dokument aus dem Cache kommt --
                # der dokumentierte Resume waere dann nie erreichbar.
                record["by_index"] = {int(k): v for k, v in record["by_index"].items()}
                done[record["doc_id"]] = record
        print(f"{len(done)} Dokumente aus dem Cache uebernommen.", file=sys.stderr)

    chunks_by_doc: dict[str, list[dict]] = {}
    for chunk in goldset["chunks"]:
        chunks_by_doc.setdefault(chunk["doc_id"], []).append(chunk)
    for chunks in chunks_by_doc.values():
        chunks.sort(key=lambda c: c["chunk_index"])

    documents: list[dict[str, Any]] = []
    sentences: list[dict[str, Any]] = []
    for index, document in enumerate(goldset["documents"], start=1):
        doc_id = document["doc_id"]
        chunks = chunks_by_doc.get(doc_id, [])
        cached = done.get(doc_id)
        if cached is not None:
            record = cached
        else:
            record = transform_one_document(document, chunks, model)
            if cache_path is not None:
                with cache_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        documents.append(
            {
                "doc_id": doc_id,
                "duration_ms": record["duration_ms"],
                "attempts": record["attempts"],
                "session_id": record["session_id"],
                "total_cost_usd": record["total_cost_usd"],
                "usage": record["usage"],
            }
        )
        for chunk in chunks:
            pair = record["by_index"][chunk["chunk_index"]]
            sentences.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "doc_id": doc_id,
                    "lang": chunk["lang"],
                    "chunk_index": chunk["chunk_index"],
                    "sentence": pair["sentence"],
                    "sentence_de": pair["sentence_de"],
                }
            )
        print(
            f"[{index}/{len(goldset['documents'])}] {doc_id}: "
            f"{record['duration_ms'] / 1000:.1f}s, {len(chunks)} Chunks, "
            f"attempts={record['attempts']}",
            file=sys.stderr,
            flush=True,
        )

    durations = [d["duration_ms"] for d in documents]
    usage_totals: dict[str, float] = {}
    total_cost_usd = 0.0
    for doc in documents:
        for key, value in doc["usage"].items():
            if isinstance(value, int | float):
                usage_totals[key] = usage_totals.get(key, 0.0) + value
        if doc["total_cost_usd"]:
            total_cost_usd += doc["total_cost_usd"]

    return {
        "meta": {
            "issue": 785,
            "epic": 710,
            "goldset_manifest_sha256": goldset["meta"]["manifest_sha256"],
            "transform_model": model,
            "generator": "scripts/eval/build_context_sentences_710.py",
            "max_sentence_words": MAX_SENTENCE_WORDS,
            "sentence_latency_ms": {"method": SENTENCE_METHOD, **_percentiles(durations)},
            "usage_totals": usage_totals,
            "total_cost_usd": round(total_cost_usd, 6),
        },
        "documents": documents,
        "sentences": sentences,
    }


def build_vectors(goldset: dict, sentences: dict) -> dict[str, Any]:
    """Embeddet die drei Live-Arme, uebernimmt ``metadata_context`` aus #731."""
    from academic_vault.embedding_model import l2_normalize
    from sentence_transformers import SentenceTransformer

    arm_texts = build_arm_texts(goldset, sentences)

    _control_goldset, control_vectors = load_candidate_fixture(BGE_M3_CANDIDATE)

    model = SentenceTransformer(MODEL_ID, device="cpu")
    durations: list[float] = []
    dim = 0

    def _encode_one(text: str) -> list[float]:
        nonlocal dim
        started = time.perf_counter()
        raw = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
        durations.append((time.perf_counter() - started) * 1000.0)
        vector = l2_normalize(list(raw[0]))
        dim = len(vector)
        return vector

    arms_out: dict[str, dict[str, dict[str, str]]] = {}

    # Queries sind arm-unabhaengig: einmal live embedden, fuer alle drei
    # Live-Arme wiederverwenden.
    query_vectors: dict[str, str] = {
        query["query_id"]: encode_vector(_encode_one(query["query"]))
        for query in goldset["queries"]
    }

    for arm in LIVE_EMBED_ARMS:
        chunk_vectors: dict[str, str] = {}
        for chunk in goldset["chunks"]:
            _context, embedding_text = arm_texts[arm][chunk["chunk_id"]]
            chunk_vectors[chunk["chunk_id"]] = encode_vector(_encode_one(embedding_text))
        arms_out[arm] = {"chunks": chunk_vectors, "queries": dict(query_vectors)}

    # metadata_context: unveraendert aus dem #731-bge-m3-Fixture uebernommen --
    # kein erneutes Embedding, Grundlage des Kontrolltests.
    arms_out[COPIED_ARM] = {
        "chunks": {
            chunk["chunk_id"]: encode_vector(control_vectors[chunk["chunk_id"]])
            for chunk in goldset["chunks"]
        },
        "queries": {
            query["query_id"]: encode_vector(control_vectors[query["query_id"]])
            for query in goldset["queries"]
        },
    }

    chunk_order = [c["chunk_id"] for c in goldset["chunks"]]
    query_order = [q["query_id"] for q in goldset["queries"]]
    query_texts = {q["query_id"]: q["query"] for q in goldset["queries"]}
    manifest = compute_context_manifest_sha256(
        arm_texts, chunk_order, query_texts, query_order, MODEL_ID, dim
    )

    return {
        "model_id": MODEL_ID,
        "dim": dim,
        "manifest_sha256": manifest,
        "embed_latency_ms": {"method": EMBED_METHOD, **_percentiles(durations)},
        "control_source": {
            "candidate": BGE_M3_CANDIDATE,
            "path": "tests/fixtures/embedding_candidates_731/bge-m3/vectors.json",
            "note": (
                f"Arm {COPIED_ARM!r} uebernimmt Chunk- UND Query-Vektoren unveraendert aus "
                "#731 -- kein erneutes Embedding. Grundlage des Kontrolltests in "
                "run_context_ablation_710.py."
            ),
        },
        "arms": arms_out,
    }


def _require_gate(name: str, hint: str) -> None:
    if os.environ.get(name) != "1":
        print(f"{name}=1 setzen -- {hint}", file=sys.stderr)
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("sentences", "vectors"), required=True)
    parser.add_argument("--sentences-out", type=Path, default=SENTENCES_PATH)
    parser.add_argument("--vectors-out", type=Path, default=VECTORS_PATH)
    parser.add_argument("--model", default=DEFAULT_TRANSFORM_MODEL)
    args = parser.parse_args(argv)

    args.sentences_out.parent.mkdir(parents=True, exist_ok=True)

    if args.stage == "sentences":
        _require_gate(
            SENTENCE_ENV_GATE,
            "diese Stufe ruft die claude-CLI je Dokument auf und laeuft mehrere Minuten.",
        )
        goldset = load_base_goldset()
        cache_path = args.sentences_out.with_suffix(".partial.jsonl")
        payload = build_sentences(goldset, args.model, cache_path=cache_path)
        args.sentences_out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        cache_path.unlink(missing_ok=True)
        print(
            f"{len(payload['sentences'])} Kontextsatz-Paare geschrieben: {args.sentences_out}",
            file=sys.stderr,
        )
        return 0

    _require_gate(EMBED_ENV_GATE, "diese Stufe laedt das echte bge-m3-Modell.")
    goldset = load_base_goldset()
    sentences = json.loads(args.sentences_out.read_text(encoding="utf-8"))
    vectors_payload = build_vectors(goldset, sentences)
    args.vectors_out.write_text(json.dumps(vectors_payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"{len(ARMS)} Arme geschrieben: {args.vectors_out} "
        f"(manifest_sha256={vectors_payload['manifest_sha256'][:16]}...)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
