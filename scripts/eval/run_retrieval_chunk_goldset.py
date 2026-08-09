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


def vector_dim(encoded: str) -> int:
    """Laenge eines kodierten Vektors, ohne ihn zu entpacken.

    float32 little-endian, also vier Byte je Wert. Fuer reine
    Dimensionspruefungen ueber ganze Fixtures ist das der billige Weg:
    :func:`decode_vector` allozierte dafuer je Vektor eine Float-Liste, die
    sofort wieder verworfen wird.
    """
    blob = base64.b64decode(encoded)
    if len(blob) % 4 != 0:
        raise ValueError(f"Vektor-BLOB hat Laenge {len(blob)} (kein Vielfaches von 4)")
    return len(blob) // 4


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


# ---------------------------------------------------------------------------
# Report-Vergleich (gemeinsam fuer die compare_against-Funktionen)
# ---------------------------------------------------------------------------
# Die --check-against-Gatter in run_retrieval_ablation_729,
# run_embedding_candidates_731 und run_hyde_multiquery_eval pruefen dieselbe
# Sache: deckt sich der frische Lauf mit den eingecheckten Rohdaten? Die
# Vergleichsmechanik liegt deshalb hier, in dem Modul, aus dem ohnehin alle
# drei importieren -- sonst driften drei Kopien derselben Pruefung
# auseinander, wie es beim Wechsel vom positionsweisen Listenvergleich auf den
# schluesselbasierten schon passiert ist.
_MISSING = object()


def _show(value: Any) -> str:
    return "<fehlt>" if value is _MISSING else repr(value)


def _detail(keys: Sequence[Any], fresh: dict, stored: dict, limit: int) -> str:
    """``<key>: gemessen ..., im Report ...`` fuer die ersten ``limit`` Schluessel.

    Gekappt, weil ein durchgaengig abweichender Report sonst eine Meldung ueber
    alle Queries erzeugt; die Zahl der uebergangenen Schluessel steht dabei.
    """
    shown = ", ".join(
        f"{key}: gemessen {_show(fresh.get(key, _MISSING))}, "
        f"im Report {_show(stored.get(key, _MISSING))}"
        for key in keys[:limit]
    )
    if len(keys) > limit:
        shown += f", ... (+{len(keys) - limit} weitere)"
    return shown


def _index_per_query(
    rows: Sequence[Any], field: str
) -> tuple[dict[str, Any], list[str], list[str]]:
    """``per_query``-Liste als ``query_id -> Wert``, plus Reihenfolge und Dubletten."""
    index: dict[str, Any] = {}
    order: list[str] = []
    duplicates: list[str] = []
    for position, row in enumerate(rows):
        is_object = isinstance(row, dict)
        raw_id = row.get("query_id") if is_object else None
        # Ohne verwertbare query_id bleibt die Position als Schluessel -- als
        # str, damit sorted() spaeter nicht ueber gemischte Typen faellt.
        key = raw_id if isinstance(raw_id, str) else f"<Position {position} ohne query_id>"
        if key in index:
            duplicates.append(key)
        index[key] = row.get(field, _MISSING) if is_object else _MISSING
        order.append(key)
    return index, order, sorted(set(duplicates))


def diverged_per_query(
    fresh_rows: Sequence[Any],
    stored_rows: Any,
    label: str,
    *,
    field: str = "retrieved",
    limit: int = 3,
) -> list[str]:
    """Vergleicht zwei ``per_query``-Bloecke und benennt die abweichende Query.

    Der Vergleich laeuft ueber die ``query_id``, damit die Meldung sagen kann,
    WELCHE Query abweicht -- ein positionsweiser Listenvergleich meldet nur,
    DASS irgendwo etwas abweicht, und das ist ohne kompletten lokalen Re-Run
    nicht triagierbar.

    Reihenfolge und Dubletten fallen dabei nicht unter den Tisch: beides wird
    separat gemeldet, sonst waere der Schluesselvergleich schwaecher als der
    Listenvergleich, den er ersetzt.

    Returns:
        Je Abweichung eine Zeile, jeweils mit ``label`` praefigiert.
    """
    if not isinstance(stored_rows, list):
        return [
            f"{label}: die eingecheckten Rohdaten fuehren hier "
            f"{type(stored_rows).__name__} statt einer Liste"
        ]

    fresh_index, fresh_order, fresh_duplicates = _index_per_query(fresh_rows, field)
    stored_index, stored_order, stored_duplicates = _index_per_query(stored_rows, field)

    problems: list[str] = []
    for source, duplicates in (
        ("im frischen Lauf", fresh_duplicates),
        ("in den eingecheckten Rohdaten", stored_duplicates),
    ):
        if duplicates:
            problems.append(
                f"{label}: doppelte query_id {source}: {duplicates!r} -- verglichen wird "
                "davon nur der letzte Eintrag"
            )

    diverged = sorted(
        key
        for key in set(fresh_index) | set(stored_index)
        if fresh_index.get(key, _MISSING) != stored_index.get(key, _MISSING)
    )
    if diverged:
        problems.append(
            f"{label}.{field}: Rangfolge weicht von den Rohdaten ab bei "
            f"query_id={diverged!r} -- {_detail(diverged, fresh_index, stored_index, limit)}"
        )
    elif fresh_order != stored_order:
        problems.append(
            f"{label}: gleiche Inhalte, andere Reihenfolge -- gemessen {fresh_order!r}, "
            f"im Report {stored_order!r}"
        )
    return problems


def diverged_mapping(fresh_map: dict, stored_map: Any, label: str, *, limit: int = 3) -> list[str]:
    """Schluesselweiser Vergleich zweier Report-Bloecke (z. B. ``by_case``).

    Faengt die beiden Faelle mit ab, in denen ein blanker
    Ungleichheitsvergleich zwar unspezifisch, aber wenigstens tragfaehig war:
    fehlt der Block in den Rohdaten ganz, ist das eine Abweichung -- auch
    gegenueber einem leeren frischen Block --, und ein fremder Typ wird
    gemeldet, statt die Set-Operationen in einen ``TypeError`` laufen zu
    lassen.
    """
    if stored_map is None:
        return [f"{label}: fehlt in den eingecheckten Rohdaten"]
    if not isinstance(stored_map, dict):
        return [
            f"{label}: die eingecheckten Rohdaten fuehren hier "
            f"{type(stored_map).__name__} statt eines Objekts"
        ]
    diverged = sorted(
        key
        for key in set(fresh_map) | set(stored_map)
        if fresh_map.get(key, _MISSING) != stored_map.get(key, _MISSING)
    )
    if not diverged:
        return []
    return [
        f"{label}: weicht von den Rohdaten ab bei {diverged!r} -- "
        f"{_detail(diverged, fresh_map, stored_map, limit)}"
    ]


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
