#!/usr/bin/env python3
"""Generator fuer das Chunk-Retrieval-Goldset aus Issue #708.

Erzeugt aus ``tests/fixtures/retrieval_goldset_chunks_708/sources.json``:

* ``goldset.json``  — Chunks (ueber ``chunking.chunk_pages`` mit Kontextsatz)
  und Queries mit aufgeloesten ``relevant_chunk_ids``
* ``vectors.json``  — base64-kodierte float32-Vektoren fuer Chunks (Praefix
  ``passage: ``) und Queries (Praefix ``query: ``)

Dieses Skript laeuft **nicht** hermetisch: es laedt den echten e5-Tokenizer
(fuer exakte Chunkgrenzen) und das echte Embedding-Modell. Es ist deshalb
bewusst kein pytest-Test, sondern wird manuell ausgefuehrt — analog zu
``scripts/eval/recall_at_k_model_ab.py`` (#375/#628)::

    VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_retrieval_chunk_goldset.py

Der hermetische Lauf gegen das Ergebnis ist
``scripts/eval/run_retrieval_chunk_goldset.py``.

Relevanzurteile stehen in ``sources.json`` nicht als Chunk-Indizes, sondern als
woertliche ``anchors``. Verschieben sich Chunkgrenzen (anderer Tokenizer,
anderes Tokenbudget), bleiben die Urteile damit gueltig; ein Anker, der in
keinem Chunk mehr auftaucht, ist ein harter Fehler statt einer stillen
Fehlmessung.

Seit Issue #790 baut derselbe Generator auch das **Probe-Goldset**
``tests/fixtures/retrieval_goldset_chunk_fusion_790/`` — dieselben elf
#708-Dokumente plus zehn gezielt konstruierte Dokumente, deren Queries den
Chunk-Fusions-Mechanismus ueberhaupt erst sichtbar machen. Zwei Flags kommen
dafuer hinzu::

    VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_retrieval_chunk_goldset.py \\
      --sources tests/fixtures/retrieval_goldset_chunk_fusion_790/sources.json \\
      --goldset-out tests/fixtures/retrieval_goldset_chunk_fusion_790/goldset.json \\
      --vectors-out tests/fixtures/retrieval_goldset_chunk_fusion_790/vectors.json \\
      --conditions-out tests/fixtures/retrieval_goldset_chunk_fusion_790/conditions.json \\
      --reuse-vectors tests/fixtures/retrieval_goldset_chunks_708/vectors.json \\
      --verify-probe-conditions --issue 790 --skip-thresholds

* ``--reuse-vectors`` uebernimmt fuer jede ``chunk_id``/``query_id``, deren
  Text **byteweise unveraendert** ist, den eingecheckten Vektor und embeddet
  nur den Zuwachs neu.
* ``--verify-probe-conditions`` prueft die im Issue festgelegten Design-Regeln
  je Probe-Query gegen die echten Produktionsfunktionen und bricht mit
  Klarnamen der verletzenden Query ab, bevor gemessen wird.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.eval.run_retrieval_chunk_goldset import (  # noqa: E402
    GOLDSET_PATH,
    METRICS,
    SOURCES_PATH,
    THRESHOLDS_PATH,
    VECTORS_PATH,
    compute_manifest_sha256,
    decode_vector,
    encode_vector,
    load_sources,
)

# Marge zwischen gemessenem Wert und hinterlegter Schwelle. Klein, weil der
# Lauf bei fixen Vektoren deterministisch ist (beide knn_chunks-Pfade liefern
# dieselbe Reihenfolge); sie faengt nur Rundungsunterschiede zwischen
# Plattformen ab, keine echte Qualitaetsschwankung.
DEFAULT_MARGIN = 0.02

# Das #708-Goldset ist ausdruecklich das e5-small-Chunk-Goldset (siehe
# docs/evals/retrieval-chunk-goldset-708.md, "Historisches Dokument") --
# gepinnt statt ``DEFAULT_MODEL_ID`` zu folgen (PR-Review zu #732: seit der
# Default auf BAAI/bge-m3 zeigt, wuerde ein Lauf ohne diese Pin-Konstante
# heimlich mit dem bge-m3-Tokenizer chunken und mit e5-Praefixen ("passage: "/
# "query: ") auf bge-m3-Gewichten embedden -- genau die "falsch bediente
# Schnittstelle", die #731 und BgeM3Embedder ausschliessen wollen. #722 und
# #733 bauen auf diesem Goldset auf und teilen dieselbe Annahme.
LEGACY_EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"

# Probe-Rollen des #790-Sets. 'gain'/'harm' beschreiben denselben Mechanismus
# (M1, Signal-Split) in beide Richtungen, 'crowding' den schwaecheren M2, und
# 'control' den Fall, in dem gar nichts passieren darf.
PROBE_ROLES = ("gain", "harm", "crowding", "control")

# Obergrenze fuer die Tokenzahl einer Probe-Query (Design-Regel 1 aus #790):
# ``papers_fts`` MATCH verknuepft Tokens implizit mit AND -- jedes zusaetzliche
# Token senkt die Trefferwahrscheinlichkeit multiplikativ, und genau daran ist
# die lexikalische Seite des #708-Sets gestorben (#789).
MAX_PROBE_QUERY_TOKENS = 4

# Mindestabstand zwischen den RRF-Scores an der Kippstelle (Design-Regel 6).
# RRF erzeugt bei exakt gleichem Score eine Reihenfolge, die von der
# Einfuegereihenfolge in ein ``set`` und damit von Pythons Hash-Randomisierung
# abhaengt (Folge-Issue #792) -- ein messbarer Abstand ist der Schutz dagegen.
MIN_SCORE_GAP = 1e-4


def build_chunks(sources: dict) -> list[dict[str, Any]]:
    """Zerlegt jedes Quelldokument ueber ``chunk_pages`` in Goldset-Chunks.

    Nutzt bewusst die Produktionsdefaults (``TARGET_TOKENS``, ``OVERLAP_RATIO``,
    ``default_context_sentence``) und den echten Tokenizer von
    ``LEGACY_EMBEDDING_MODEL_ID`` (nicht ``DEFAULT_MODEL_ID`` -- dieses Goldset
    ist auf e5-small gepinnt, s. o.), sofern ladbar.
    """
    from academic_vault.chunking import chunk_pages, model_token_counter

    counter = model_token_counter(LEGACY_EMBEDDING_MODEL_ID)
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


def _normalize(text: str) -> str:
    """Whitespace vereinheitlichen — ``chunk_pages`` normalisiert Zeilenumbrueche."""
    return " ".join(text.split())


def resolve_anchors(chunks: list[dict], sources: dict) -> list[dict[str, Any]]:
    """Loest die ``anchors`` jeder Query auf die Chunks auf, die sie enthalten.

    Ein Anker landet regelmaessig in ZWEI benachbarten Chunks, weil sich die
    Fenster ueberlappen. Beide gelten dann als relevant — der Text beantwortet
    die Frage in beiden Faellen, und ein Ranking dafuer zu bestrafen, welchen
    der beiden Ausschnitte es gefunden hat, waere Willkuer.

    Raises:
        ValueError: Ein Anker taucht in keinem Chunk auf (Quelltext geaendert,
            Anker nicht nachgezogen).
    """
    normalized = [(c["chunk_id"], _normalize(c["chunk_text"])) for c in chunks]
    queries: list[dict[str, Any]] = []
    for query in sources["queries"]:
        relevant: list[str] = []
        for anchor in query["anchors"]:
            needle = _normalize(anchor)
            hits = [cid for cid, text in normalized if needle in text]
            if not hits:
                raise ValueError(
                    f"Query {query['query_id']}: Anker {anchor!r} kommt in keinem Chunk vor. "
                    "sources.json und die Anker sind auseinandergelaufen."
                )
            relevant.extend(cid for cid in hits if cid not in relevant)
        entry = {
            "query_id": query["query_id"],
            "lang": query["lang"],
            "case": query["case"],
            "query": query["query"],
            "anchors": list(query["anchors"]),
            "relevant_chunk_ids": relevant,
        }
        # Probe-Felder (Issue #790) nur durchreichen, wenn sie da sind -- das
        # #708-Set kennt sie nicht und soll dadurch keine leeren Schluessel
        # bekommen (sein manifest_sha256 haengt zwar nicht daran, seine
        # eingecheckte goldset.json aber schon).
        if "probe_role" in query:
            entry["probe_role"] = query["probe_role"]
        if "probe" in query:
            entry["probe"] = json.loads(json.dumps(query["probe"]))
        queries.append(entry)
    return queries


def load_reuse_index(vectors_path: Path) -> dict[str, tuple[str, str]]:
    """Baut den Wiederverwendungs-Index aus einem eingecheckten Fixture-Paar (#790).

    ``vectors_path`` zeigt auf eine ``vectors.json``; die zugehoerige
    ``goldset.json`` wird im selben Verzeichnis erwartet — sie liefert die
    Texte, gegen die byteweise verglichen wird. Ein Vektor ohne Text (oder
    umgekehrt) wird stillschweigend uebergangen: er kann die Gleichheitspruefung
    ohnehin nicht bestehen und wuerde sonst nur eine Ausnahme an einer Stelle
    ausloesen, an der ein Neu-Embedding die richtige Antwort ist.

    Returns:
        Mapping ``id -> (text, base64-Vektor)`` ueber Chunks UND Queries. Die
        beiden Namensraeume kollidieren nicht (``<doc_id>#<index>`` vs.
        ``q-...``), siehe ``run_retrieval_chunk_goldset.load_vectors``.
    """
    goldset_path = vectors_path.parent / "goldset.json"
    if not goldset_path.exists():
        raise FileNotFoundError(
            f"--reuse-vectors {vectors_path} braucht die zugehoerige {goldset_path.name} "
            "im selben Verzeichnis (sie liefert die Texte fuer den Byte-Vergleich)."
        )
    old_goldset = json.loads(goldset_path.read_text(encoding="utf-8"))
    old_vectors = json.loads(vectors_path.read_text(encoding="utf-8"))

    index: dict[str, tuple[str, str]] = {}
    for chunk in old_goldset["chunks"]:
        encoded = old_vectors.get("chunks", {}).get(chunk["chunk_id"])
        if encoded is not None:
            index[chunk["chunk_id"]] = (chunk["embedding_text"], encoded)
    for query in old_goldset["queries"]:
        encoded = old_vectors.get("queries", {}).get(query["query_id"])
        if encoded is not None:
            index[query["query_id"]] = (query["query"], encoded)
    return index


def embed_all(
    chunks: list[dict],
    queries: list[dict],
    reuse_index: dict[str, tuple[str, str]] | None = None,
) -> tuple[dict[str, str], dict[str, str], int, dict[str, int]]:
    """Embeddet Chunks (``passage: ``) und Queries (``query: ``) mit dem echten Modell.

    Gepinnt auf ``LEGACY_EMBEDDING_MODEL_ID`` ueber :func:`embedder_for`, NICHT
    auf ``DEFAULT_MODEL_ID`` -- siehe Kommentar dort.

    Mit ``reuse_index`` (Issue #790, ``--reuse-vectors``) wird der eingecheckte
    Vektor uebernommen, sobald ID **und** Text byteweise uebereinstimmen. Der
    Textvergleich ist die eigentliche Bedingung: eine gleichnamige ``chunk_id``
    mit veraendertem Text bekommt einen frischen Vektor, sonst zeigte der
    ``manifest_sha256`` zwar Drift an, die Fixture waere aber schon falsch.

    Returns:
        ``(chunk_vektoren, query_vektoren, dim, statistik)`` -- die Statistik
        zaehlt ``reused``/``embedded`` getrennt fuer Chunks und Queries.
    """
    reuse_index = reuse_index or {}

    def _split(items: list[dict], id_key: str, text_key: str) -> tuple[dict[str, str], list[dict]]:
        reused: dict[str, str] = {}
        todo: list[dict] = []
        for item in items:
            known = reuse_index.get(item[id_key])
            if known is not None and known[0] == item[text_key]:
                reused[item[id_key]] = known[1]
            else:
                todo.append(item)
        return reused, todo

    encoded_chunks, todo_chunks = _split(chunks, "chunk_id", "embedding_text")
    encoded_queries, todo_queries = _split(queries, "query_id", "query")

    dim: int | None = None
    if todo_chunks or todo_queries:
        from academic_vault.embedding_model import embedder_for

        embedder = embedder_for(LEGACY_EMBEDDING_MODEL_ID)
        dim = embedder.dim
        fresh = embedder.embed_documents([c["embedding_text"] for c in todo_chunks])
        for chunk, vector in zip(todo_chunks, fresh, strict=True):
            encoded_chunks[chunk["chunk_id"]] = encode_vector(vector)
        for query in todo_queries:
            encoded_queries[query["query_id"]] = encode_vector(embedder.embed_query(query["query"]))
    else:
        # Vollstaendige Wiederverwendung: die Dimension steht in den
        # uebernommenen Vektoren selbst, das Modell muss dafuer nicht laden.
        any_vector = next(iter({**encoded_chunks, **encoded_queries}.values()))
        dim = len(decode_vector(any_vector))

    # Reihenfolge an die Eingabe angleichen: die JSON-Fixture soll in
    # Dokument-/Query-Reihenfolge lesbar bleiben, nicht in "erst
    # wiederverwendet, dann neu".
    ordered_chunks = {c["chunk_id"]: encoded_chunks[c["chunk_id"]] for c in chunks}
    ordered_queries = {q["query_id"]: encoded_queries[q["query_id"]] for q in queries}
    stats = {
        "chunks_reused": len(chunks) - len(todo_chunks),
        "chunks_embedded": len(todo_chunks),
        "queries_reused": len(queries) - len(todo_queries),
        "queries_embedded": len(todo_queries),
    }
    return ordered_chunks, ordered_queries, dim, stats


def build(
    sources: dict,
    issue: int = 708,
    reuse_index: dict[str, tuple[str, str]] | None = None,
) -> tuple[dict, dict, dict[str, int]]:
    """Baut ``goldset.json``- und ``vectors.json``-Inhalt aus den Quelltexten."""
    from academic_vault.embedding_model import PASSAGE_PREFIX, QUERY_PREFIX

    chunks = build_chunks(sources)
    queries = resolve_anchors(chunks, sources)
    encoded_chunks, encoded_queries, dim, stats = embed_all(chunks, queries, reuse_index)

    meta = {
        "issue": issue,
        "model_id": LEGACY_EMBEDDING_MODEL_ID,
        "dim": dim,
        "passage_prefix": PASSAGE_PREFIX,
        "query_prefix": QUERY_PREFIX,
        "generator": "scripts/eval/build_retrieval_chunk_goldset.py",
        "manifest_sha256": compute_manifest_sha256(
            [c["embedding_text"] for c in chunks],
            [q["query"] for q in queries],
            LEGACY_EMBEDDING_MODEL_ID,
            dim,
        ),
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
        "model_id": LEGACY_EMBEDDING_MODEL_ID,
        "dim": dim,
        "manifest_sha256": meta["manifest_sha256"],
        "chunks": encoded_chunks,
        "queries": encoded_queries,
    }
    return goldset, vectors, stats


# ---------------------------------------------------------------------------
# Probe-Vorbedingungen (Issue #790, --verify-probe-conditions)
# ---------------------------------------------------------------------------
# Design-Regel 5: der Decoy muss BEIDSEITIG stark sein. Ist sein
# Vektor-Paperrang schlechter als 2, gewinnt das Zielpaper schon im
# 'vorher'-Arm und der Fall belegt nichts ueber die Fusionsgranularitaet.
MAX_SPLIT_VEC_PAPER_RANK = 2

# Familie B (Crowding, M2): der 'Crowder' braucht genug eigene Chunks, um
# fremde Bestchunks nach hinten zu druecken, und der Bestchunk des fokussierten
# Dokuments muss deutlich hinter seinem Paperrang liegen -- sonst ist der
# Unterschied zwischen Paper- und Chunk-Rang gar nicht vorhanden.
CROWDING_MIN_CHUNKS = 9
CROWDING_MIN_TARGET_VEC_CHUNK_RANK = 7
CROWDING_MAX_TARGET_VEC_PAPER_RANK = 2


class ProbeConditionError(RuntimeError):
    """Mindestens eine Probe-Query verletzt ihre Design-Regel (#790).

    Harter Abbruch statt Warnung: ein Probe-Goldset, dessen Kippbedingungen
    nicht erfuellt sind, misst nicht den Mechanismus, sondern nur noch, was
    zufaellig herauskommt -- und sieht dabei genauso aus wie ein gelungenes.
    """


def probe_queries(goldset: dict) -> list[dict]:
    """Alle Queries mit ``probe_role`` (Issue #790), in Goldset-Reihenfolge."""
    return [q for q in goldset["queries"] if q.get("probe_role")]


def _rank_and_score(results: list[dict]) -> tuple[dict[str, int], dict[str, float]]:
    """Paper-Rang (1-basiert) und ``rrf_score`` je Paper aus einer Trefferliste."""
    ranks: dict[str, int] = {}
    scores: dict[str, float] = {}
    for idx, entry in enumerate(results):
        pid = entry["paper_id"]
        if pid in ranks:
            continue
        ranks[pid] = idx + 1
        scores[pid] = float(entry.get("rrf_score") or 0.0)
    return ranks, scores


def _full_token_chunks(conn, sanitized_query: str, paper_id: str) -> list[str]:
    """Alle Chunks EINES Papers, die saemtliche Query-Tokens enthalten.

    Dieselbe Bedingung, die ``server._attach_chunk_to_fts_hit`` intern stellt
    (``chunk_fts MATCH ... AND paper_id = ...``) -- nur ohne ``LIMIT 1``, damit
    die Design-Regel "GENAU EIN Volltreffer-Chunk" pruefbar wird statt nur
    "mindestens einer".
    """
    rows = conn.execute(
        "SELECT chunk_id FROM chunk_fts WHERE chunk_fts MATCH ? AND paper_id = ? ORDER BY rank",
        (sanitized_query, paper_id),
    ).fetchall()
    return [row["chunk_id"] for row in rows]


def _chunk_count_per_paper(goldset: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for chunk in goldset["chunks"]:
        counts[chunk["doc_id"]] = counts.get(chunk["doc_id"], 0) + 1
    return counts


def dense_paper_ranks(vec_best_chunk_rank: dict[str, int]) -> dict[str, int]:
    """Vektor-PAPERrang aus dem Chunkrang des jeweils besten Chunks je Paper.

    ``diagnose_query`` (#789) liefert unter ``vec_paper_rank`` die POSITION des
    besten Chunks eines Papers in der chunk-level Trefferliste -- also 1, 4, 5
    fuer drei Paper, deren Bestchunks auf den Chunkraengen 1, 4 und 5 liegen.
    Der 'vorher'-Arm rankt dagegen auf PAPER-Ebene und sieht dieselben drei
    Paper als Raenge 1, 2, 3 (``_vec0_search_paper_level``: bestes Chunk je
    Paper, danach nach Distanz sortiert). Design-Regel 5 aus #790 meint diesen
    dichten Paperrang; ihn mit dem Chunkrang zu verwechseln haette Familie A
    faelschlich als verletzt gemeldet.
    """
    ordered = sorted(vec_best_chunk_rank.items(), key=lambda kv: kv[1])
    return {paper_id: index + 1 for index, (paper_id, _) in enumerate(ordered)}


def _check_common_rules(query: dict, diagnosis: dict) -> dict[str, bool]:
    """Design-Regeln 1 und 2 -- gelten fuer JEDE Probe-Rolle."""
    text = query["query"]
    tokens = text.split()
    return {
        "rule1_no_comma": "," not in text,
        "rule1_at_most_four_tokens": 1 <= len(tokens) <= MAX_PROBE_QUERY_TOKENS,
        "rule1_no_fts5_syntax_error": diagnosis["fts5_syntax_error"] is None,
        "rule2_term_family_in_at_least_two_documents": diagnosis["papers_fts_hit_count"] >= 2,
    }


def _check_split_pair(
    probe: dict,
    diagnosis: dict,
    full_token_chunks: dict[str, list[str]],
    scores_before: dict[str, float],
    scores_after: dict[str, float],
) -> dict[str, bool]:
    """Design-Regeln 3-6 fuer die Rollen ``gain``/``harm`` (Mechanismus M1).

    ``split_doc`` traegt das aufgespaltene Signal (kein Chunk enthaelt alle
    Tokens -> ``_attach_chunk_to_fts_hit`` faellt auf ``fts-paper::<pid>``
    zurueck), ``coherent_doc`` die geschlossene Fundstelle. Welches der beiden
    das RELEVANTE ist, unterscheidet die Richtung: bei ``gain`` das kohaerente
    (erwartetes positives Delta), bei ``harm`` das gesplittete (erwartetes
    negatives Delta). Die Regeln selbst sind in beiden Faellen dieselben --
    genau deshalb ist Familie C kein anderer Mechanismus, sondern derselbe mit
    vertauschter Relevanz.
    """
    split_doc = probe["split_doc"]
    coherent_doc = probe["coherent_doc"]
    fts_ranking = diagnosis["fts_ranking"]
    fts_rank = {pid: idx + 1 for idx, pid in enumerate(fts_ranking)}

    def _gap(scores: dict[str, float]) -> float:
        return abs(scores.get(split_doc, 0.0) - scores.get(coherent_doc, 0.0))

    return {
        "rule3_split_doc_has_no_full_token_chunk": (
            split_doc in diagnosis["attached_chunk"]
            and diagnosis["attached_chunk"][split_doc] is None
            and full_token_chunks.get(split_doc) == []
        ),
        "rule4_coherent_doc_has_exactly_one_full_token_chunk": (
            len(full_token_chunks.get(coherent_doc, [])) == 1
        ),
        "rule4_coherent_chunk_is_vector_best_chunk": (
            diagnosis["attach_equals_vec_best"].get(coherent_doc) is True
        ),
        "rule5_split_doc_lexically_at_least_as_strong": (
            split_doc in fts_rank
            and coherent_doc in fts_rank
            and fts_rank[split_doc] <= fts_rank[coherent_doc]
        ),
        "rule5_split_doc_vector_paper_rank_at_most_2": (
            dense_paper_ranks(diagnosis["vec_paper_rank"]).get(split_doc, 10**6)
            <= MAX_SPLIT_VEC_PAPER_RANK
        ),
        "rule6_score_gap_before_above_threshold": _gap(scores_before) > MIN_SCORE_GAP,
        "rule6_score_gap_after_above_threshold": _gap(scores_after) > MIN_SCORE_GAP,
    }


def _check_control(
    probe: dict, diagnosis: dict, full_token_chunks: dict[str, list[str]]
) -> dict[str, bool]:
    """Familie D: bei ALLEN beteiligten Papern faellt Zuordnung und
    Vektor-Bestchunk zusammen -- dann darf die Fusionsgranularitaet nichts
    aendern, und ein gemessenes Delta ungleich 0 waere ein Befund ueber den
    Messaufbau, nicht ueber den Mechanismus."""
    papers = probe["papers"]
    return {
        "control_all_papers_are_fts_hits": all(p in diagnosis["attached_chunk"] for p in papers),
        "control_attach_equals_vec_best_for_all_papers": all(
            diagnosis["attach_equals_vec_best"].get(p) is True for p in papers
        ),
        "control_every_paper_has_exactly_one_full_token_chunk": all(
            len(full_token_chunks.get(p, [])) == 1 for p in papers
        ),
    }


def _check_crowding(probe: dict, diagnosis: dict, chunk_counts: dict[str, int]) -> dict[str, bool]:
    """Familie B: Effektgroesse von M2 (Crowding), nicht Fundament.

    Gemessen wird, ob ein chunkreiches Dokument die vorderen CHUNK-Raenge
    besetzt und damit den Bestchunk eines fremden Papers nach hinten drueckt,
    obwohl dessen PAPER-Rang vorn liegt. Genau diese Schere zwischen den beiden
    Raengen IST der Mechanismus: der 'vorher'-Arm sieht nur den Paperrang, der
    'nachher'-Arm rechnet mit dem Chunkrang.
    """
    crowder = probe["crowder_doc"]
    focused = probe["focused_doc"]
    chunk_rank = diagnosis["vec_paper_rank"].get(focused)
    paper_rank = dense_paper_ranks(diagnosis["vec_paper_rank"]).get(focused, 10**6)
    return {
        "crowding_crowder_has_enough_chunks": chunk_counts.get(crowder, 0) >= CROWDING_MIN_CHUNKS,
        "crowding_focused_vector_chunk_rank_is_deep": (
            chunk_rank is not None and chunk_rank >= CROWDING_MIN_TARGET_VEC_CHUNK_RANK
        ),
        "crowding_focused_vector_paper_rank_is_high": (
            paper_rank <= CROWDING_MAX_TARGET_VEC_PAPER_RANK
        ),
    }


def verify_probe_conditions(goldset: dict, vectors: dict[str, list[float]], k: int = 10) -> dict:
    """Prueft jede Probe-Query gegen die Design-Regeln aus #790.

    Laeuft gegen die ECHTEN Produktionsfunktionen (``server.search_papers``,
    ``server._attach_chunk_to_fts_hit``, ``server._vec0_search``,
    ``retrieval.reciprocal_rank_fusion``) auf einer hermetischen Wegwerf-DB mit
    den eingecheckten Vektoren -- dieselbe Grundlage wie der Diagnoseblock aus
    #789, den diese Funktion dafuer wiederverwendet.

    Returns:
        ``conditions.json``-Inhalt: je Query die Einzelchecks, das Sammelurteil
        ``conditions_met`` und die gemessenen Groessen (Raenge/Scores in beiden
        Fusionszustaenden), aus denen das Urteil entstanden ist.
    """
    from academic_vault.db import VaultDB
    from academic_vault.server import _sanitize_fts5_query, search_papers

    from scripts.eval.run_retrieval_ablation_729 import (
        _env_guard,
        diagnose_query,
        hermetic_goldset_db,
        search_papers_paper_level,
    )

    chunk_counts = _chunk_count_per_paper(goldset)
    queries = probe_queries(goldset)
    results: dict[str, Any] = {}

    with hermetic_goldset_db(goldset, vectors, name="probe-790") as db_path:
        for query in queries:
            text = query["query"]
            probe = query.get("probe") or {}
            role = query["probe_role"]
            diagnosis = diagnose_query(db_path, text, k=k)

            with _env_guard():
                before = search_papers_paper_level(db_path, text, k, attach_chunk=False)
                after = search_papers(db_path, text, k=k, rerank=True)
            ranks_before, scores_before = _rank_and_score(before)
            ranks_after, scores_after = _rank_and_score(after)

            sanitized = _sanitize_fts5_query(text)
            full_token_chunks: dict[str, list[str]] = {}
            if sanitized and diagnosis["fts5_syntax_error"] is None:
                conn = VaultDB._open(db_path)
                try:
                    for paper_id in sorted(diagnosis["attached_chunk"]):
                        full_token_chunks[paper_id] = _full_token_chunks(conn, sanitized, paper_id)
                finally:
                    conn.close()

            checks = _check_common_rules(query, diagnosis)
            if role in ("gain", "harm"):
                checks.update(
                    _check_split_pair(
                        probe, diagnosis, full_token_chunks, scores_before, scores_after
                    )
                )
                relevant = probe.get("relevant_doc")
                expected = probe["coherent_doc"] if role == "gain" else probe["split_doc"]
                checks["role_matches_relevance_direction"] = relevant == expected
            elif role == "control":
                checks.update(_check_control(probe, diagnosis, full_token_chunks))
            elif role == "crowding":
                checks.update(_check_crowding(probe, diagnosis, chunk_counts))
            else:
                raise ProbeConditionError(
                    f"Query {query['query_id']}: unbekannte probe_role {role!r} "
                    f"(erlaubt: {', '.join(PROBE_ROLES)})"
                )

            results[query["query_id"]] = {
                "probe_role": role,
                "case": query["case"],
                "query": text,
                "probe": probe,
                "conditions_met": all(checks.values()),
                "checks": checks,
                "violations": sorted(name for name, ok in checks.items() if not ok),
                "measured": {
                    "papers_fts_hit_count": diagnosis["papers_fts_hit_count"],
                    "papers_trgm_hit_count": diagnosis["papers_trgm_hit_count"],
                    "fts_ranking": diagnosis["fts_ranking"],
                    "attached_chunk": diagnosis["attached_chunk"],
                    "attach_equals_vec_best": diagnosis["attach_equals_vec_best"],
                    # Chunkrang des jeweils besten Chunks je Paper (so liefert
                    # ihn diagnose_query) UND der daraus abgeleitete dichte
                    # Paperrang, mit dem der 'vorher'-Arm rechnet.
                    "vec_best_chunk_rank": diagnosis["vec_paper_rank"],
                    "vec_paper_rank": dense_paper_ranks(diagnosis["vec_paper_rank"]),
                    "full_token_chunk_count": {
                        pid: len(cids) for pid, cids in sorted(full_token_chunks.items())
                    },
                    "paper_rank_before": ranks_before,
                    "paper_rank_after": ranks_after,
                    "paper_score_before": scores_before,
                    "paper_score_after": scores_after,
                },
            }

    violating = sorted(qid for qid, entry in results.items() if not entry["conditions_met"])
    return {
        "_comment": (
            "Geprueft mit build_retrieval_chunk_goldset.py --verify-probe-conditions "
            "gegen die echten Produktionsfunktionen (server.search_papers, "
            "server._attach_chunk_to_fts_hit, server._vec0_search). 'conditions_met' "
            "sagt, ob die Konstruktion haelt -- NICHT, ob das gemessene Delta "
            "positiv ausfaellt."
        ),
        "issue": goldset["meta"].get("issue"),
        "k": k,
        "model_id": goldset["meta"]["model_id"],
        "manifest_sha256": goldset["meta"]["manifest_sha256"],
        "query_count": len(queries),
        "queries_with_conditions_met": sum(
            1 for entry in results.values() if entry["conditions_met"]
        ),
        "violating_queries": violating,
        "queries": results,
    }


def derive_thresholds(report: dict, margin: float = DEFAULT_MARGIN) -> dict:
    """Leitet Schwellen aus einem gemessenen Report ab: Messwert minus Marge."""

    def _floor(values: dict) -> dict[str, float]:
        return {metric: round(max(0.0, values[metric] - margin), 4) for metric in METRICS}

    return {
        "_comment": (
            "Erzeugt aus dem gemessenen Lauf minus einer Marge von "
            f"{margin}. Neu ableiten: build_retrieval_chunk_goldset.py --write-thresholds"
        ),
        "k": report["k"],
        "margin": margin,
        "measured_at_model": report["model_id"],
        "overall": _floor(report["overall"]),
        "subsets": {case: _floor(values) for case, values in report["subsets"].items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--goldset-out", type=Path, default=GOLDSET_PATH)
    parser.add_argument("--vectors-out", type=Path, default=VECTORS_PATH)
    parser.add_argument("--thresholds-out", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument(
        "--write-thresholds",
        action="store_true",
        help="Schwellen aus dem frisch gemessenen Lauf neu ableiten (ueberschreibt!).",
    )
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    parser.add_argument(
        "--issue",
        type=int,
        default=708,
        help="Issue-Nummer fuer meta.issue im Goldset (708 = Basisset, 790 = Probe-Set).",
    )
    parser.add_argument(
        "--reuse-vectors",
        type=Path,
        default=None,
        help=(
            "vectors.json eines bestehenden Sets. Jeder Chunk/jede Query mit "
            "byteweise unveraendertem Text uebernimmt den eingecheckten Vektor; "
            "nur der Zuwachs wird neu embeddet (Issue #790)."
        ),
    )
    parser.add_argument(
        "--verify-probe-conditions",
        action="store_true",
        help=(
            "Design-Regeln je Probe-Query pruefen (Issue #790) und mit Exit 3 "
            "abbrechen, falls eine Vorbedingung verletzt ist."
        ),
    )
    parser.add_argument(
        "--conditions-out",
        type=Path,
        default=None,
        help="Zielpfad fuer conditions.json (nur mit --verify-probe-conditions).",
    )
    parser.add_argument(
        "--skip-thresholds-report",
        action="store_true",
        help=(
            "Den Chunk-Metrik-Report am Ende auslassen. Fuer das Probe-Set aus "
            "#790 sinnvoll: es hat keine thresholds.json und wird nicht ueber "
            "Recall/nDCG gegattert, sondern ueber conditions.json."
        ),
    )
    args = parser.parse_args(argv)

    if os.environ.get("VAULT_E5_LIVE_TEST") != "1":
        print(
            "VAULT_E5_LIVE_TEST=1 setzen — dieses Skript laedt Tokenizer und "
            "Embedding-Modell und laeuft bewusst nicht hermetisch.",
            file=sys.stderr,
        )
        return 2

    sources = load_sources(args.sources)
    reuse_index = load_reuse_index(args.reuse_vectors) if args.reuse_vectors else None
    goldset, vectors, stats = build(sources, issue=args.issue, reuse_index=reuse_index)

    args.goldset_out.parent.mkdir(parents=True, exist_ok=True)
    args.goldset_out.write_text(
        json.dumps(goldset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.vectors_out.write_text(json.dumps(vectors, indent=2) + "\n", encoding="utf-8")

    print(
        f"{len(goldset['chunks'])} Chunks, {len(goldset['queries'])} Queries, "
        f"Modell {goldset['meta']['model_id']} ({goldset['meta']['dim']}d), "
        f"manifest_sha256={goldset['meta']['manifest_sha256'][:16]}...",
        file=sys.stderr,
    )
    if reuse_index is not None:
        print(
            f"Vektoren wiederverwendet: {stats['chunks_reused']} Chunks / "
            f"{stats['queries_reused']} Queries; neu embeddet: "
            f"{stats['chunks_embedded']} Chunks / {stats['queries_embedded']} Queries.",
            file=sys.stderr,
        )

    from scripts.eval.run_retrieval_chunk_goldset import evaluate, load_vectors

    loaded_vectors = load_vectors(args.vectors_out)

    if args.verify_probe_conditions:
        conditions = verify_probe_conditions(goldset, loaded_vectors)
        target = args.conditions_out or args.goldset_out.parent / "conditions.json"
        target.write_text(
            json.dumps(conditions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Vorbedingungen geschrieben: {target}", file=sys.stderr)
        if conditions["violating_queries"]:
            for query_id in conditions["violating_queries"]:
                entry = conditions["queries"][query_id]
                print(
                    f"  VERLETZT {query_id} ({entry['probe_role']}): "
                    f"{', '.join(entry['violations'])}",
                    file=sys.stderr,
                )
            print(
                "Probe-Vorbedingungen verletzt — das Set misst so nicht den "
                "Mechanismus. Texte nachziehen und neu bauen.",
                file=sys.stderr,
            )
            return 3
        print(
            f"Alle {conditions['query_count']} Probe-Queries erfuellen ihre Vorbedingungen.",
            file=sys.stderr,
        )

    if args.skip_thresholds_report:
        return 0

    report = evaluate(goldset, loaded_vectors)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.write_thresholds:
        args.thresholds_out.write_text(
            json.dumps(derive_thresholds(report, args.margin), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Schwellen geschrieben: {args.thresholds_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
