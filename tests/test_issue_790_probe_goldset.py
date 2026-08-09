"""Regressionstests fuer das Probe-Goldset aus Issue #790.

#711-B, Nachfolger von #789 (711-A). #789 hat belegt, WARUM der #729-Lauf
einen Nullbefund lieferte: die lexikalische Seite des #708-Goldsets ist
strukturell tot (1 von 26 Queries mit ``papers_fts``-Treffer), und bei leerer
FTS-Liste sind Paper-Ebene-Fusion und Chunk-Ebene-Fusion beweisbar
ordnungsgleich. Dieses Issue baut daraufhin ein zweites, gezielt
konstruiertes Goldset, dessen Queries die Kippbedingung des dominanten
Mechanismus (M1, Signal-Split) tatsaechlich erfuellen.

Die Tests hier pruefen drei Dinge getrennt:

1. **Die Fixture ist das, was sie zu sein behauptet** -- Alt-Dokumente und
   Alt-Vektoren byteweise unveraendert, Probe-Queries nach den Design-Regeln
   gebaut, ``conditions.json`` deckungsgleich mit dem Goldset.
2. **Die Konstruktion haelt** -- jede ``gain``/``harm``-Query erfuellt ihre
   Vorbedingungen, jede ``control``-Query hat ``attach_equals_vec_best`` fuer
   alle beteiligten Paper.
3. **Die Messung faellt so aus wie vorhergesagt** -- Familie A positiv,
   Familie C negativ, Familie D exakt 0, und die 26 Altqueries im
   erweiterten Korpus weiterhin exakt 0 (Invarianztest).

Punkt 3 ist bewusst als Test formuliert und nicht nur als Reportzahl: ein
Probe-Goldset, dessen Effekt sich beim naechsten Umbau des Suchpfads
lautlos aufloest, waere schlimmer als keins.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.eval.build_retrieval_chunk_goldset import (
    MAX_PROBE_QUERY_TOKENS,
    REQUIRED_PROBE_FIELDS,
    dense_paper_ranks,
    load_reuse_index,
    min_score_gap,
    probe_queries,
    relevant_doc_ids,
)
from scripts.eval.run_retrieval_ablation_729 import (
    compare_against,
    compute_deltas_by_case,
    run_quality_ablation,
)
from scripts.eval.run_retrieval_chunk_goldset import GOLDSET_DIR as BASE_DIR
from scripts.eval.run_retrieval_chunk_goldset import load_goldset, load_vectors

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_DIR = REPO_ROOT / "tests" / "fixtures" / "retrieval_goldset_chunk_fusion_790"
PROBE_SOURCES = PROBE_DIR / "sources.json"
PROBE_GOLDSET = PROBE_DIR / "goldset.json"
PROBE_VECTORS = PROBE_DIR / "vectors.json"
PROBE_CONDITIONS = PROBE_DIR / "conditions.json"
LIVE_RESULTS = (
    REPO_ROOT / "docs" / "evals" / "2026-08-09-chunk-fusion-goldset-790-live-results.json"
)

pytestmark = pytest.mark.skipif(not PROBE_GOLDSET.exists(), reason="#790-Fixture nicht vorhanden")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def probe_goldset() -> dict:
    return load_goldset(PROBE_GOLDSET)


@pytest.fixture(scope="module")
def probe_vectors() -> dict[str, list[float]]:
    return dict(load_vectors(PROBE_VECTORS))


@pytest.fixture(scope="module")
def conditions() -> dict:
    return _read(PROBE_CONDITIONS)


@pytest.fixture(scope="module")
def ablation(probe_goldset: dict, probe_vectors: dict) -> dict:
    """Ein einziger Ablationslauf fuer alle Messtests (hermetisch, ~20 s)."""
    return run_quality_ablation(probe_goldset, probe_vectors, k=10)


# ---------------------------------------------------------------------------
# 1. Die Fixture ist das, was sie zu sein behauptet
# ---------------------------------------------------------------------------
def test_old_documents_are_word_for_word_identical_to_the_708_sources() -> None:
    """Die elf #708-Dokumente sind der Regressionsanker -- ein einziges
    geaendertes Wort verschoebe Chunkgrenzen und entwertete die
    wiederverwendeten Vektoren."""
    old = _read(BASE_DIR / "sources.json")
    new = _read(PROBE_SOURCES)
    old_by_id = {d["doc_id"]: d for d in old["documents"]}
    new_by_id = {d["doc_id"]: d for d in new["documents"]}
    assert set(old_by_id) <= set(new_by_id)
    for doc_id, document in old_by_id.items():
        assert new_by_id[doc_id] == document, doc_id
    assert len(new_by_id) == len(old_by_id) + 10, "zehn neue Dokumente laut #790-Bestand"


def test_old_queries_are_word_for_word_identical_to_the_708_sources() -> None:
    old = _read(BASE_DIR / "sources.json")
    new = _read(PROBE_SOURCES)
    assert new["queries"][: len(old["queries"])] == old["queries"]
    assert len(new["queries"]) == len(old["queries"]) + 12


def test_old_vectors_are_reused_byte_for_byte(probe_goldset: dict) -> None:
    """Task-AC: die 30 Alt-Chunk- und 26 Alt-Query-Vektoren im neuen
    ``vectors.json`` sind byteweise identisch zum #708-Set.

    Verglichen wird die base64-Kodierung selbst, nicht der dekodierte
    Float-Vektor: ein neu berechneter Vektor kann in der letzten Stelle
    abweichen, ohne dass ein Toleranzvergleich das je meldete."""
    old_vectors = _read(BASE_DIR / "vectors.json")
    new_vectors = _read(PROBE_VECTORS)

    assert len(old_vectors["chunks"]) == 30
    assert len(old_vectors["queries"]) == 26
    for chunk_id, encoded in old_vectors["chunks"].items():
        assert new_vectors["chunks"][chunk_id] == encoded, chunk_id
    for query_id, encoded in old_vectors["queries"].items():
        assert new_vectors["queries"][query_id] == encoded, query_id
    # ... und der Zuwachs ist tatsaechlich neu, nicht etwa aus Versehen leer.
    assert len(new_vectors["chunks"]) > len(old_vectors["chunks"])
    assert len(new_vectors["queries"]) == 38


def test_reuse_index_matches_id_and_text(tmp_path: Path) -> None:
    """``--reuse-vectors`` uebernimmt nur bei gleicher ID UND gleichem Text.

    Der Textvergleich ist die eigentliche Bedingung: eine gleichnamige
    ``chunk_id`` mit geaendertem Text bekaeme sonst still einen Vektor, der zu
    einem anderen Textstand gehoert."""
    index = load_reuse_index(BASE_DIR / "vectors.json")
    old_goldset = load_goldset(BASE_DIR / "goldset.json")
    first_chunk = old_goldset["chunks"][0]
    text, encoded = index[first_chunk["chunk_id"]]
    assert text == first_chunk["embedding_text"]
    assert encoded == _read(BASE_DIR / "vectors.json")["chunks"][first_chunk["chunk_id"]]

    (tmp_path / "vectors.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_reuse_index(tmp_path / "vectors.json")


def test_goldset_meta_pins_the_legacy_model(probe_goldset: dict) -> None:
    """Das Probe-Set bleibt auf e5-small (wie #708), nicht auf dem
    bge-m3-Produktionsdefault -- sonst waeren die uebernommenen Altvektoren aus
    einem anderen Raum."""
    assert probe_goldset["meta"]["model_id"] == "intfloat/multilingual-e5-small"
    assert probe_goldset["meta"]["dim"] == 384
    assert probe_goldset["meta"]["issue"] == 790


def test_probe_queries_carry_role_and_probe_block(probe_goldset: dict) -> None:
    probes = probe_queries(probe_goldset)
    assert len(probes) == 12
    by_role: dict[str, int] = {}
    for query in probes:
        assert query["probe"], query["query_id"]
        by_role[query["probe_role"]] = by_role.get(query["probe_role"], 0) + 1
    assert by_role == {"gain": 5, "crowding": 2, "harm": 3, "control": 2}


# ---------------------------------------------------------------------------
# 2. Die Konstruktion haelt
# ---------------------------------------------------------------------------
def test_every_probe_query_is_short_comma_free_and_lexically_alive(
    probe_goldset: dict, conditions: dict
) -> None:
    """Task-AC: keine Probe-Query enthaelt ein Komma, hat mehr als vier Tokens
    oder weniger als zwei FTS-Treffer.

    Alle drei Eigenschaften sind direkte Konsequenzen des #789-Befunds: ein
    Komma bricht ``papers_fts`` MATCH mit ``sqlite3.OperationalError`` ab, und
    jedes zusaetzliche Token senkt die Trefferwahrscheinlichkeit multiplikativ,
    weil FTS5 ohne ``OR`` implizit UND verknuepft."""
    for query in probe_queries(probe_goldset):
        text = query["query"]
        assert "," not in text, query["query_id"]
        assert 1 <= len(text.split()) <= MAX_PROBE_QUERY_TOKENS, query["query_id"]
        measured = conditions["queries"][query["query_id"]]["measured"]
        assert measured["papers_fts_hit_count"] >= 2, query["query_id"]


def test_every_gain_and_harm_query_meets_its_preconditions(conditions: dict) -> None:
    """Task-AC: jede ``gain``/``harm``-Query erfuellt ihre Vorbedingungen laut
    ``conditions.json``.

    ``conditions_met`` sagt NICHT, dass das Delta positiv ausfaellt -- nur,
    dass die Konstruktion die Kippbedingung herstellt. Genau diese Trennung
    macht ein negatives Delta zu einem Befund statt zu einem Baufehler."""
    checked = 0
    for query_id, entry in conditions["queries"].items():
        if entry["probe_role"] not in ("gain", "harm"):
            continue
        checked += 1
        assert entry["conditions_met"], (query_id, entry["violations"])
        checks = entry["checks"]
        assert checks["rule3_split_doc_has_no_full_token_chunk"], query_id
        assert checks["rule4_coherent_doc_has_exactly_one_full_token_chunk"], query_id
        assert checks["rule4_coherent_chunk_is_vector_best_chunk"], query_id
        assert checks["rule5_split_doc_lexically_at_least_as_strong"], query_id
        assert checks["rule5_split_doc_vector_paper_rank_at_most_2"], query_id
        assert checks["rule6_score_gap_before_above_threshold"], query_id
        assert checks["rule6_score_gap_after_above_threshold"], query_id
    assert checked == 8, "5 gain + 3 harm"


def test_every_control_query_has_attach_equals_vector_best_for_all_papers(
    conditions: dict,
) -> None:
    """Task-AC: jede ``control``-Query hat ``attach_equals_vec_best == true``
    fuer alle beteiligten Paper -- die Vorbedingung dafuer, dass die
    Fusionsgranularitaet hier gar nichts aendern KANN."""
    checked = 0
    for query_id, entry in conditions["queries"].items():
        if entry["probe_role"] != "control":
            continue
        checked += 1
        assert entry["conditions_met"], (query_id, entry["violations"])
        for paper_id in entry["probe"]["papers"]:
            assert entry["measured"]["attach_equals_vec_best"][paper_id] is True, (
                query_id,
                paper_id,
            )
    assert checked == 2


def test_conditions_file_covers_exactly_the_probe_queries(
    probe_goldset: dict, conditions: dict
) -> None:
    assert set(conditions["queries"]) == {q["query_id"] for q in probe_queries(probe_goldset)}
    assert conditions["violating_queries"] == []
    assert conditions["queries_with_conditions_met"] == conditions["query_count"] == 12
    assert conditions["manifest_sha256"] == probe_goldset["meta"]["manifest_sha256"]


def test_no_probe_query_has_an_exact_score_tie(conditions: dict) -> None:
    """Vorbedingung des Replay-Gatters: kein Paper teilt sich mit einem anderen
    exakt denselben ``rrf_score``.

    Bei einem Gleichstand entscheidet die Iterationsreihenfolge eines ``set``
    ueber die Rangfolge, und die ist pro Lauf verschieden (#792). Das Gatter
    ``--check-against`` vergleicht Trefferlisten und wuerde davon sporadisch
    rot -- ohne dass sich an einer Metrik etwas geaendert haette."""
    for query_id, entry in conditions["queries"].items():
        assert entry["checks"]["no_exact_score_tie_before"], query_id
        assert entry["checks"]["no_exact_score_tie_after"], query_id
        for field in ("min_paper_score_gap_before", "min_paper_score_gap_after"):
            gap = entry["measured"][field]
            assert gap is None or gap > 0.0, (query_id, field, gap)


def test_declared_relevant_doc_matches_the_goldset_relevance(conditions: dict) -> None:
    """Das Familienlabel haengt an der tatsaechlichen Relevanz, nicht nur an
    sich selbst.

    Die uebrigen Rollenpruefungen vergleichen Felder des handgeschriebenen
    ``probe``-Blocks miteinander. Rutscht beim naechsten Textnachzug ein Anker
    in das Decoy-Dokument, kippt das Delta der Query ins Gegenteil, waehrend
    jene Pruefungen weiter zufrieden waeren -- dieser Check nicht."""
    for query_id, entry in conditions["queries"].items():
        assert entry["checks"]["relevant_doc_matches_goldset"], query_id
        assert entry["measured"]["relevant_docs"] == [entry["probe"]["relevant_doc"]], query_id


def test_declared_relevant_doc_matches_the_live_goldset(probe_goldset: dict) -> None:
    """Dieselbe Bindung, aber aus ``goldset.json`` nachgerechnet statt aus
    ``conditions.json`` gelesen.

    Notwendig, weil ``manifest_sha256`` bauartbedingt nur ``embedding_text``,
    Query-Text, Modell-ID und Dimension abdeckt -- die ``anchors`` und die
    daraus abgeleiteten ``relevant_chunk_ids`` stehen NICHT im Hash. Wer nur
    einen Anker praeziser formuliert, sodass er auf einen Chunk des
    Decoy-Dokuments faellt, laesst Texte und Hash unveraendert; die
    eingecheckte ``conditions.json`` saehe weiterhin gueltig aus. Dieser Test
    laeuft ohne Ablation und ohne Live-Embedding und schliesst genau die
    Luecke."""
    chunk_owner = {c["chunk_id"]: c["doc_id"] for c in probe_goldset["chunks"]}
    for query in probe_queries(probe_goldset):
        declared = query["probe"]["relevant_doc"]
        assert relevant_doc_ids(query, chunk_owner) == [declared], query["query_id"]


def test_relevant_doc_ids_resolve_chunks_to_documents() -> None:
    owner = {"a#0": "doc-a", "a#1": "doc-a", "b#0": "doc-b"}
    assert relevant_doc_ids({"relevant_chunk_ids": ["a#0", "a#1"]}, owner) == ["doc-a"]
    assert relevant_doc_ids({"relevant_chunk_ids": ["b#0", "a#0"]}, owner) == ["doc-a", "doc-b"]
    assert relevant_doc_ids({}, owner) == []


def test_every_probe_block_carries_the_fields_its_role_needs(probe_goldset: dict) -> None:
    """Ein vergessenes Feld im ``probe``-Block soll als verletzte Vorbedingung
    auffallen, nicht als ``KeyError`` mitten im Lauf.

    Der Task-AC verlangt Exit 3 mit Klarnamen der verletzenden Query UND eine
    geschriebene ``conditions.json`` -- beides gaebe es nicht, wenn der
    Generator vorher abstuerzte."""
    for query in probe_queries(probe_goldset):
        required = REQUIRED_PROBE_FIELDS[query["probe_role"]]
        missing = [field for field in required if not query["probe"].get(field)]
        assert missing == [], (query["query_id"], missing)


def test_conditions_record_the_probe_block_completeness(conditions: dict) -> None:
    for query_id, entry in conditions["queries"].items():
        assert entry["checks"]["probe_block_is_complete"], query_id
        assert entry["measured"]["missing_probe_fields"] == [], query_id


@pytest.mark.parametrize(
    "argv",
    [
        ["--write-thresholds", "--skip-thresholds-report"],
        ["--conditions-out", "irgendwo.json"],
    ],
)
def test_generator_rejects_contradictory_flag_combinations(argv: list[str]) -> None:
    """Flags, die einander aufheben, sollen abweisen statt still nichts zu tun.

    ``--skip-thresholds-report`` springt vor dem Schwellen-Block heraus, und
    ``--conditions-out`` schreibt nur, wenn auch geprueft wird. Ohne diese
    Pruefung endete beides mit Exit 0, ohne die erwartete Datei zu schreiben."""
    from scripts.eval.build_retrieval_chunk_goldset import main as generator_main

    with pytest.raises(SystemExit) as excinfo:
        generator_main(argv)
    assert excinfo.value.code == 2


def test_min_score_gap_flags_an_exact_tie() -> None:
    assert min_score_gap({"a": 0.5, "b": 0.4}) == pytest.approx(0.1)
    assert min_score_gap({"a": 0.5, "b": 0.5}) == 0.0
    assert min_score_gap({"a": 0.5}) is None
    assert min_score_gap({}) is None


def test_reuse_index_rejects_a_fixture_from_another_model(tmp_path: Path) -> None:
    """``--reuse-vectors`` darf keinen Vektor aus einem anderen Vektorraum
    uebernehmen.

    Text- und ID-Gleichheit allein genuegen nicht: eine bge-m3-Fassung
    desselben Goldsets (1024d, #732/#710) hat byteweise dieselben
    ``embedding_text``e. Ohne diese Pruefung entstuende eine ``vectors.json``
    mit gemischten Dimensionen, die ``verify_manifest`` nicht bemerkt, weil der
    Manifest-Hash Texte und Metadaten abdeckt, nicht die Vektoren."""
    source = tmp_path / "vectors.json"
    source.write_text(json.dumps({"model_id": "BAAI/bge-m3", "chunks": {}, "queries": {}}))
    (tmp_path / "goldset.json").write_text(
        json.dumps({"meta": {"model_id": "BAAI/bge-m3", "dim": 1024}, "chunks": [], "queries": []})
    )
    with pytest.raises(ValueError, match="bge-m3"):
        load_reuse_index(source)


# Die fixture-unabhaengigen Unit-Tests zu ``embed_all()`` und
# ``compare_against()`` stehen in ``tests/test_eval_script_helpers.py``: unter
# dem modulweiten ``skipif`` dieser Datei haetten sie mit dem naechsten
# Fixture-Umzug lautlos aufgehoert zu pruefen.


def test_dense_paper_ranks_compress_chunk_ranks_to_paper_ranks() -> None:
    """Der 'vorher'-Arm rankt auf Paper-Ebene: drei Paper mit Bestchunks auf
    den Chunkraengen 1, 4 und 5 sind dort die Paperraenge 1, 2 und 3.
    Design-Regel 5 meint diesen dichten Rang."""
    assert dense_paper_ranks({"a": 1, "b": 4, "c": 5}) == {"a": 1, "b": 2, "c": 3}
    assert dense_paper_ranks({"b": 4, "a": 1}) == {"a": 1, "b": 2}
    assert dense_paper_ranks({}) == {}


# ---------------------------------------------------------------------------
# 3. Die Messung faellt so aus wie vorhergesagt
# ---------------------------------------------------------------------------
def _per_query_delta(ablation: dict, query_id: str, metric: str) -> float:
    before = {q["query_id"]: q for q in ablation["results"]["vorher"]["per_query"]}
    after = {q["query_id"]: q for q in ablation["results"]["nachher"]["per_query"]}
    return after[query_id][metric] - before[query_id][metric]


def test_old_26_queries_keep_a_delta_of_exactly_zero(ablation: dict) -> None:
    """Task-AC: das Delta ueber die 26 Altqueries ist im erweiterten Set exakt
    0 -- Invarianztest gegen den groesseren Korpus.

    Die Altqueries sind ausgeschriebene Saetze; ihre lexikalische Seite bleibt
    auch bei 21 statt 11 Papern leer, und bei leerer FTS-Liste sind beide
    Fusionsvarianten ordnungsgleich (#789). Ein Delta ungleich 0 hier waere
    ein Befund ueber den Suchpfad, kein Befund ueber das neue Goldset."""
    old_ids = {q["query_id"] for q in _read(BASE_DIR / "sources.json")["queries"]}
    assert len(old_ids) == 26
    for query_id in sorted(old_ids):
        for metric in ("recall_at_10", "ndcg_at_10", "reciprocal_rank"):
            assert _per_query_delta(ablation, query_id, metric) == 0.0, (query_id, metric)


def test_family_a_shows_a_positive_delta(ablation: dict, conditions: dict) -> None:
    """AC1: mindestens eine Query aus Familie A zeigt ein positives Delta in
    nDCG@10/MRR gegenueber der Paper-Ebene-Fusion, mit ``conditions_met``."""
    gains = [
        query_id
        for query_id, entry in conditions["queries"].items()
        if entry["probe_role"] == "gain" and entry["conditions_met"]
    ]
    positive = [
        query_id
        for query_id in gains
        if _per_query_delta(ablation, query_id, "ndcg_at_10") > 0
        and _per_query_delta(ablation, query_id, "reciprocal_rank") > 0
    ]
    assert positive, "keine einzige gain-Query kippt -- das Set belegt den Mechanismus nicht"


def test_family_c_shows_the_expected_negative_delta(ablation: dict, conditions: dict) -> None:
    """AC2: mindestens eine Query aus Familie C zeigt das erwartete (negative)
    Delta -- das Set ist nicht einseitig gestellt.

    Familie C ist dieselbe Konstruktion mit vertauschter Relevanz. Faende sich
    hier kein negatives Delta, waere entweder die Konstruktion asymmetrisch
    oder der Mechanismus doch ein anderer als angenommen."""
    harms = [
        query_id
        for query_id, entry in conditions["queries"].items()
        if entry["probe_role"] == "harm" and entry["conditions_met"]
    ]
    negative = [
        query_id for query_id in harms if _per_query_delta(ablation, query_id, "ndcg_at_10") < 0
    ]
    assert negative, "Familie C zeigt keinen Schadensfall -- das Set waere gestellt"


def test_family_d_confirms_a_delta_of_exactly_zero(ablation: dict, conditions: dict) -> None:
    """AC3: Familie D bestaetigt Delta 0 als Kontrolle."""
    controls = [
        query_id
        for query_id, entry in conditions["queries"].items()
        if entry["probe_role"] == "control"
    ]
    assert controls
    for query_id in controls:
        for metric in ("recall_at_10", "ndcg_at_10", "reciprocal_rank"):
            assert _per_query_delta(ablation, query_id, metric) == 0.0, (query_id, metric)


def test_deltas_by_case_separates_the_four_families(ablation: dict) -> None:
    """Ein Gesamtmittel ueber 38 Queries verduennt einen Effekt, der bauartbedingt
    nur an 12 davon auftreten kann -- und Gewinn- und Schadensfaelle heben sich
    darin teilweise gegenseitig auf."""
    by_case = ablation["deltas_by_case"]
    assert {"probe-gain", "probe-harm", "probe-control", "probe-crowding"} <= set(by_case)
    assert by_case["probe-gain"]["chunk_fusion_beitrag"]["ndcg_at_10"] > 0
    assert by_case["probe-harm"]["chunk_fusion_beitrag"]["ndcg_at_10"] < 0
    assert by_case["probe-control"]["chunk_fusion_beitrag"]["ndcg_at_10"] == 0
    for case in ("same-language", "language-gap", "cross-language"):
        assert by_case[case]["gesamt"] == {
            "recall_at_10": 0.0,
            "ndcg_at_10": 0.0,
            "mrr": 0.0,
        }, case


def test_chunk_enrichment_alone_stays_at_zero(ablation: dict) -> None:
    """Der Beitrag der Chunk-Anreicherung bleibt bei abgeschaltetem Reranker
    eine mathematische Null (#729/#789), auch auf diesem Goldset: Paper-Ebene-RRF
    liest ``chunk_id``/``text`` an keiner Stelle."""
    assert ablation["deltas"]["chunk_fts_index_beitrag"] == {
        "recall_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "mrr": 0.0,
    }


def test_compute_deltas_by_case_is_pure_grouping() -> None:
    results = {
        "vorher": {
            "by_case": {
                "x": {"query_count": 2, **dict.fromkeys(("recall_at_10", "ndcg_at_10", "mrr"), 0.5)}
            }
        },
        "zwischenzustand_a": {
            "by_case": {
                "x": {"query_count": 2, **dict.fromkeys(("recall_at_10", "ndcg_at_10", "mrr"), 0.5)}
            }
        },
        "nachher": {
            "by_case": {
                "x": {
                    "query_count": 2,
                    **dict.fromkeys(("recall_at_10", "ndcg_at_10", "mrr"), 0.75),
                }
            }
        },
    }
    deltas = compute_deltas_by_case(results)
    assert deltas["x"]["query_count"] == 2
    assert deltas["x"]["chunk_fts_index_beitrag"]["ndcg_at_10"] == 0.0
    assert deltas["x"]["chunk_fusion_beitrag"]["ndcg_at_10"] == 0.25
    assert deltas["x"]["gesamt"]["mrr"] == 0.25


# ---------------------------------------------------------------------------
# Replay-Gatter (Muster #731/#733)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not LIVE_RESULTS.exists(), reason="Rohdaten des Messlaufs fehlen")
def test_checked_in_results_contain_both_goldset_blocks() -> None:
    stored = _read(LIVE_RESULTS)
    assert stored["goldset"].endswith("retrieval_goldset_chunk_fusion_790/goldset.json")
    assert stored["baseline"]["goldset"].endswith("retrieval_goldset_chunks_708/goldset.json")
    # Der #708-Anker bleibt bei seinem Nullbefund aus #729.
    assert stored["baseline"]["quality"]["deltas"]["gesamt"] == {
        "recall_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "mrr": 0.0,
    }


@pytest.mark.skipif(not LIVE_RESULTS.exists(), reason="Rohdaten des Messlaufs fehlen")
def test_check_against_detects_a_stale_report() -> None:
    """AC des Replay-Schritts: ``--check-against`` schlaegt an, sobald Lauf und
    eingecheckte Rohdaten auseinanderlaufen."""
    stored = _read(LIVE_RESULTS)
    assert compare_against(stored, stored) == []

    tampered = json.loads(json.dumps(stored))
    tampered["quality"]["deltas"]["chunk_fusion_beitrag"]["ndcg_at_10"] = 0.9999
    problems = compare_against(tampered, stored)
    assert any("deltas" in problem for problem in problems)

    tampered_baseline = json.loads(json.dumps(stored))
    tampered_baseline["baseline"]["quality"]["results"]["nachher"]["overall"]["mrr"] = 0.1234
    problems = compare_against(tampered_baseline, stored)
    assert any(problem.startswith("baseline.") for problem in problems)


@pytest.mark.skipif(not LIVE_RESULTS.exists(), reason="Rohdaten des Messlaufs fehlen")
@pytest.mark.parametrize("hash_seed", ["0", "524287"])
def test_cli_check_against_exits_zero_on_the_checked_in_results(hash_seed: str) -> None:
    """Ende-zu-Ende ueber die CLI -- derselbe Aufruf, den der CI-Job faehrt.

    Zweimal mit unterschiedlichem ``PYTHONHASHSEED``, weil die beiden
    Paper-Ebene-Arme (``vorher``/``zwischenzustand_a``) ueber ein ``set`` von
    STABILEN ``paper_id``-Strings fusionieren: dort entscheidet bei einem
    Gleichstand die Hash-Reihenfolge, die innerhalb eines Prozesses fest,
    zwischen Prozessen aber seed-abhaengig ist. Ein solcher Gleichstand bliebe
    in einem einzelnen Prozess unsichtbar und machte den CI-Job sporadisch rot
    (Folge-Issue #792)."""
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "eval" / "run_retrieval_ablation_729.py"),
            "--goldset",
            str(PROBE_GOLDSET),
            "--vectors",
            str(PROBE_VECTORS),
            "--baseline-goldset",
            str(BASE_DIR / "goldset.json"),
            "--baseline-vectors",
            str(BASE_DIR / "vectors.json"),
            "--skip-cost",
            "--check-against",
            str(LIVE_RESULTS),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr[-4000:]


@pytest.mark.skipif(not LIVE_RESULTS.exists(), reason="Rohdaten des Messlaufs fehlen")
def test_ranking_is_reproducible_across_runs(probe_goldset: dict, probe_vectors: dict) -> None:
    """Das Replay-Gatter vergleicht ``per_query.retrieved`` -- das setzt voraus,
    dass zwei Laeufe dieselbe Reihenfolge liefern.

    Das ist keine Selbstverstaendlichkeit: ``reciprocal_rank_fusion`` iteriert
    ueber ein ``set`` von ``chunk_id``s, und die Chunk-IDs sind UUID4, die beim
    Aufbau jeder Wegwerf-DB neu vergeben werden. Bei zwei exakt gleichen
    ``rrf_score``-Werten faellt die Reihenfolge deshalb pro Lauf anders aus --
    auch mit gepinntem ``PYTHONHASHSEED``, denn nicht der Hash-Seed ist
    zufaellig, sondern die Schluessel selbst (Folge-Issue #792). Eine fruehe
    Fassung dieses Goldsets hatte genau so einen Gleichstand (Decoy und
    Glossar-Decoy auf den Raengen 2 und 3 von ``p-gain-02``); die Texte wurden
    daraufhin so nachgezogen, dass er verschwindet. Dieser Test haelt fest,
    dass es dabei bleibt -- er wuerde ein wiedereingefuehrtes Unentschieden
    hier melden statt als sporadisch rote CI.

    Was er NICHT abdeckt: die beiden Paper-Ebene-Arme fusionieren ueber stabile
    ``paper_id``-Strings, deren ``set``-Reihenfolge innerhalb eines Prozesses
    fest ist -- ein Gleichstand dort saehe hier zweimal gleich aus. Dafuer ist
    ``test_cli_check_against_exits_zero_on_the_checked_in_results`` ueber zwei
    ``PYTHONHASHSEED``-Werte parametrisiert."""
    first = run_quality_ablation(probe_goldset, probe_vectors, k=10)
    second = run_quality_ablation(probe_goldset, probe_vectors, k=10)
    for state in first["results"]:
        left = [q["retrieved"] for q in first["results"][state]["per_query"]]
        right = [q["retrieved"] for q in second["results"][state]["per_query"]]
        assert left == right, state
