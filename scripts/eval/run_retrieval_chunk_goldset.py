#!/usr/bin/env python3
"""Hermetischer Lauf des Chunk-Retrieval-Goldsets aus Issue #708.

Misst ``Recall@10``, ``nDCG@10`` und ``MRR`` auf einem Goldset, dessen Chunks
denselben Weg genommen haben wie im Betrieb (``chunking.chunk_pages`` mit
Kontextsatz, Einbettung mit ``passage: ``-Praefix). Anders als
``scripts/eval/recall_at_k_model_ab.py`` (#375/#628) braucht dieser Lauf **kein
Netz und kein Modell**: die Vektoren liegen als eingecheckte Fixture unter
``tests/fixtures/retrieval_goldset_chunks_708/`` und werden von einem
Playback-Embedder nur noch abgespielt.

Der Suchpfad selbst ist der echte: die Vektoren gehen ueber
``VaultDB.add_chunk_embedding`` in eine Wegwerf-Vault-DB und werden mit
``VaultDB.knn_chunks`` gerankt — inklusive vec0-Spiegel, sofern die Extension
ladbar ist. Gemessen wird damit der Speicher- und KNN-Pfad des Produkts, nicht
eine Matrixmultiplikation daneben.

Nutzung::

    uv run python scripts/eval/run_retrieval_chunk_goldset.py                  # Report
    uv run python scripts/eval/run_retrieval_chunk_goldset.py --check-thresholds

Exit-Code 1, sobald eine Metrik ihre in ``thresholds.json`` hinterlegte
Schwelle unterschreitet (Gesamtset oder eine der Teilmengen). Exit-Code 2 bei
Fixture-Drift (``manifest_sha256`` passt nicht zu den Texten).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOLDSET_DIR = REPO_ROOT / "tests" / "fixtures" / "retrieval_goldset_chunks_708"
SOURCES_PATH = GOLDSET_DIR / "sources.json"
GOLDSET_PATH = GOLDSET_DIR / "goldset.json"
VECTORS_PATH = GOLDSET_DIR / "vectors.json"
THRESHOLDS_PATH = GOLDSET_DIR / "thresholds.json"

DEFAULT_K = 10
METRICS = ("recall_at_10", "ndcg_at_10", "mrr")

REBUILD_HINT = "VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_retrieval_chunk_goldset.py"


class ManifestMismatchError(RuntimeError):
    """Goldset-Texte und eingecheckte Vektoren gehoeren nicht zusammen (#708).

    Bewusst ein harter Abbruch statt einer Warnung: ein editierter
    ``chunk_text`` mit altem Vektor sieht im Report voellig normal aus und
    verschiebt die Metrik um einen Betrag, den niemand einem Commit zuordnen
    kann.
    """


# ---------------------------------------------------------------------------
# Fixture laden
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_sources(path: Path = SOURCES_PATH) -> dict:
    """Die synthetischen Volltexte, aus denen die Chunks entstanden sind."""
    return _read_json(path)


def load_goldset(path: Path = GOLDSET_PATH) -> dict:
    """Chunks, Queries und Metadaten des Goldsets."""
    return _read_json(path)


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict:
    """Schwellen je Metrik fuer Gesamtset und Teilmengen."""
    return _read_json(path)


def decode_vector(encoded: str) -> list[float]:
    """base64 -> float32 little-endian -> Liste von Floats (sqlite-vec-Format)."""
    blob = base64.b64decode(encoded)
    if len(blob) % 4 != 0:
        raise ValueError(f"Vektor-BLOB hat Laenge {len(blob)} (kein Vielfaches von 4)")
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def encode_vector(vector: Sequence[float]) -> str:
    """Umkehrung von :func:`decode_vector` (nur vom Generator gebraucht)."""
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *(float(v) for v in vector))).decode(
        "ascii"
    )


def load_vectors(path: Path = VECTORS_PATH) -> dict[str, list[float]]:
    """Alle Vektoren als flaches Mapping ``id -> Vektor``.

    Chunk- und Query-IDs teilen sich einen Namensraum; der Generator stellt
    ueber die Praefixe (``<doc_id>#<index>`` bzw. ``q-...``) sicher, dass sie
    kollisionsfrei bleiben.
    """
    raw = _read_json(path)
    flat: dict[str, list[float]] = {}
    for section in ("chunks", "queries"):
        for key, encoded in raw.get(section, {}).items():
            flat[key] = decode_vector(encoded)
    return flat


def compute_manifest_sha256(
    embedding_texts: Sequence[str],
    query_texts: Sequence[str],
    model_id: str,
    dim: int,
) -> str:
    """Fingerabdruck ueber alles, was die Vektoren bestimmt hat.

    Geht einer der Texte, die Modell-ID oder die Dimension geraeuschlos
    auseinander, faellt das hier auf — und nicht erst an einer Metrik, die sich
    um zwei Prozentpunkte verschoben hat.
    """
    digest = hashlib.sha256()
    digest.update(f"{model_id}\n{dim}\n".encode())
    for text in embedding_texts:
        digest.update(b"P\x00")
        digest.update(text.encode("utf-8"))
        digest.update(b"\n")
    for text in query_texts:
        digest.update(b"Q\x00")
        digest.update(text.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_manifest(goldset: dict) -> None:
    """Wirft :class:`ManifestMismatchError`, wenn Texte und Hash auseinanderlaufen."""
    meta = goldset["meta"]
    recomputed = compute_manifest_sha256(
        [c["embedding_text"] for c in goldset["chunks"]],
        [q["query"] for q in goldset["queries"]],
        meta["model_id"],
        meta["dim"],
    )
    if recomputed != meta["manifest_sha256"]:
        raise ManifestMismatchError(
            "manifest_sha256 passt nicht zu den Texten im Goldset: erwartet "
            f"{meta['manifest_sha256']}, berechnet {recomputed}. Die eingecheckten "
            f"Vektoren gehoeren zu einem anderen Textstand — neu erzeugen mit: {REBUILD_HINT}"
        )


# ---------------------------------------------------------------------------
# Playback-Embedder
# ---------------------------------------------------------------------------
class PlaybackEmbedder:
    """Erfuellt das ``Embedder``-Protokoll, rechnet aber nichts.

    Liefert zu einem Text den vorberechneten Vektor aus der Fixture. Ein Text
    ohne hinterlegten Vektor ist ein ``KeyError`` und ausdruecklich kein
    Nullvektor: ein still eingesetzter Nullvektor wuerde die Rangfolge
    verfaelschen und der Lauf saehe trotzdem gruen aus.
    """

    def __init__(self, vectors: dict[str, list[float]], meta: dict) -> None:
        self._by_id = vectors
        self.model_id = meta["model_id"]
        self._dim = int(meta["dim"])
        self._by_text: dict[str, list[float]] = {}

    def register(self, key: str, text: str) -> None:
        """Verknuepft einen Text mit der ID, unter der sein Vektor liegt."""
        self._by_text[text] = self._by_id[key]

    @property
    def dim(self) -> int:
        return self._dim

    def _lookup(self, text: str) -> list[float]:
        try:
            return self._by_text[text]
        except KeyError as exc:
            raise KeyError(
                f"Kein vorberechneter Vektor fuer den Text {text[:60]!r}. Fixture und "
                f"Aufrufer laufen auseinander — neu erzeugen mit: {REBUILD_HINT}"
            ) from exc

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._lookup(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._lookup(text)


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------
def build_playback_embedder(goldset: dict, vectors: dict[str, list[float]]) -> PlaybackEmbedder:
    """Bindet jeden Fixture-Text an seinen vorberechneten Vektor."""
    embedder = PlaybackEmbedder(vectors, goldset["meta"])
    for chunk in goldset["chunks"]:
        embedder.register(chunk["chunk_id"], chunk["embedding_text"])
    for query in goldset["queries"]:
        embedder.register(query["query_id"], query["query"])
    return embedder


def _populate_vault(db_path: str, goldset: dict, embedder: PlaybackEmbedder) -> dict[str, str]:
    """Schreibt Papers und Chunk-Embeddings in eine frische Vault-DB.

    Die Vektoren kommen ueber ``embedder.embed_documents`` und damit ueber
    dieselbe Text-zu-Vektor-Schnittstelle, die im Betrieb das echte Modell
    bedient — laufen Fixture-Texte und Fixture-Vektoren auseinander, bricht der
    Lauf hier ab, statt eine unauffaellig verschobene Metrik zu melden.

    Returns:
        Mapping ``vault_chunk_id (UUID) -> goldset chunk_id``.
    """
    from academic_vault.db import VaultDB
    from academic_vault.embedding_model import serialize_f32

    db = VaultDB(db_path)
    db.init_schema()

    for document in goldset["documents"]:
        db.add_paper(
            paper_id=document["doc_id"],
            csl_json=json.dumps(
                {"title": document["title"], "type": "article-journal"}, ensure_ascii=False
            ),
        )

    db.register_embedding_inventory(embedder.model_id, embedder.dim)

    chunks = goldset["chunks"]
    computed = embedder.embed_documents([c["embedding_text"] for c in chunks])

    id_map: dict[str, str] = {}
    for chunk, vector in zip(chunks, computed, strict=True):
        vault_id = db.add_chunk_embedding(
            paper_id=chunk["doc_id"],
            chunk_text=chunk["chunk_text"],
            context_sentence=chunk["context_sentence"],
            embedding_text=chunk["embedding_text"],
            embedding_vector=serialize_f32(vector),
        )
        id_map[vault_id] = chunk["chunk_id"]
    return id_map


def _aggregate(rows: Sequence[dict], k: int) -> dict[str, float]:
    if not rows:
        return {metric: 0.0 for metric in METRICS}
    return {
        "recall_at_10": sum(r["recall_at_10"] for r in rows) / len(rows),
        "ndcg_at_10": sum(r["ndcg_at_10"] for r in rows) / len(rows),
        "mrr": sum(r["reciprocal_rank"] for r in rows) / len(rows),
    }


def evaluate(
    goldset: dict,
    vectors: dict[str, list[float]],
    k: int = DEFAULT_K,
) -> dict:
    """Fuehrt das Goldset gegen den echten Vault-KNN-Pfad aus.

    Args:
        goldset: Ergebnis von :func:`load_goldset`.
        vectors: Ergebnis von :func:`load_vectors`.
        k: Cutoff fuer alle drei Metriken.

    Returns:
        Report-Dict mit ``overall``, ``subsets`` (je ``case``) und ``per_query``.
    """
    from academic_vault.db import VaultDB
    from academic_vault.retrieval import (
        compute_ndcg_at_k,
        compute_recall_at_k,
        compute_reciprocal_rank_at_k,
    )

    embedder = build_playback_embedder(goldset, vectors)

    with tempfile.TemporaryDirectory(prefix="goldset-708-") as tmpdir:
        db_path = str(Path(tmpdir) / "goldset.db")
        id_map = _populate_vault(db_path, goldset, embedder)
        db = VaultDB(db_path)

        per_query: list[dict] = []
        for query in goldset["queries"]:
            hits = db.knn_chunks(embedder.embed_query(query["query"]), k=k)
            ranked = [id_map[hit["chunk_id"]] for hit in hits]
            relevant = query["relevant_chunk_ids"]
            reciprocal = compute_reciprocal_rank_at_k(ranked, relevant, k=k)
            per_query.append(
                {
                    "query_id": query["query_id"],
                    "lang": query["lang"],
                    "case": query["case"],
                    "recall_at_10": compute_recall_at_k(ranked, relevant, k=k),
                    "ndcg_at_10": compute_ndcg_at_k(ranked, relevant, k=k),
                    "reciprocal_rank": reciprocal,
                    "first_hit_rank": round(1 / reciprocal) if reciprocal else None,
                    "retrieved": ranked,
                }
            )

    subsets: dict[str, dict[str, float]] = {}
    for case in sorted({row["case"] for row in per_query}):
        subsets[case] = _aggregate([r for r in per_query if r["case"] == case], k)

    return {
        "k": k,
        "model_id": goldset["meta"]["model_id"],
        "dim": goldset["meta"]["dim"],
        "manifest_sha256": goldset["meta"]["manifest_sha256"],
        "chunk_count": len(goldset["chunks"]),
        "query_count": len(goldset["queries"]),
        "overall": _aggregate(per_query, k),
        "subsets": subsets,
        "per_query": per_query,
    }


def check_thresholds(report: dict, thresholds: dict) -> list[str]:
    """Vergleicht den Report gegen die Schwellen. Leere Liste = alles bestanden.

    Returns:
        Je Unterschreitung eine Zeile ``<scope>.<metric>: <ist> < <soll>``.
    """
    violations: list[str] = []

    def _compare(scope: str, measured: dict[str, float], limits: dict[str, float]) -> None:
        for metric, limit in limits.items():
            value = measured.get(metric)
            if value is None:
                violations.append(f"{scope}.{metric}: im Report nicht vorhanden")
            elif value + 1e-9 < limit:
                violations.append(f"{scope}.{metric}: {value:.4f} < {limit:.4f}")

    _compare("overall", report["overall"], thresholds.get("overall", {}))
    for case, limits in thresholds.get("subsets", {}).items():
        measured = report["subsets"].get(case)
        if measured is None:
            violations.append(f"subsets.{case}: im Report nicht vorhanden")
        else:
            _compare(f"subsets.{case}", measured, limits)
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goldset", type=Path, default=GOLDSET_PATH)
    parser.add_argument("--vectors", type=Path, default=VECTORS_PATH)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--check-thresholds",
        action="store_true",
        help="Exit 1, wenn eine Metrik ihre Schwelle unterschreitet.",
    )
    parser.add_argument(
        "--skip-manifest-check",
        action="store_true",
        help="Nur fuer Negativtests: Drift-Schutz aussetzen.",
    )
    args = parser.parse_args(argv)

    goldset = load_goldset(args.goldset)
    if not args.skip_manifest_check:
        try:
            verify_manifest(goldset)
        except ManifestMismatchError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    report = evaluate(goldset, load_vectors(args.vectors), k=args.k)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not args.check_thresholds:
        return 0

    violations = check_thresholds(report, load_thresholds(args.thresholds))
    if violations:
        print(
            "Retrieval-Goldset #708: Schwelle unterschritten\n  " + "\n  ".join(violations),
            file=sys.stderr,
        )
        return 1
    print("Retrieval-Goldset #708: alle Schwellen gehalten.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
