"""Unit-Tests der Hilfsfunktionen in den Eval-Skripten (#729/#790).

Bewusst eine eigene Datei: ``tests/test_issue_790_probe_goldset.py`` steht
komplett unter einem ``skipif`` auf die #790-Fixture, und die Fixtures dieses
Repos loesen sich ab (#708 -> #789 -> #790). Ein Guard in ``embed_all()`` oder
``compare_against()`` haette dort mit dem naechsten Fixture-Umzug lautlos
aufgehoert, geprueft zu werden -- obwohl beide Funktionen von der Fixture
nichts wissen und im Produktionspfad der Skripte unveraendert scharf bleiben.

Getestet wird deshalb hier alles, was ohne Goldset-Dateien auskommt.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from scripts.eval.build_retrieval_chunk_goldset import embed_all
from scripts.eval.run_retrieval_ablation_729 import compare_against
from scripts.eval.run_retrieval_chunk_goldset import encode_vector


class _StubEmbedder:
    """Minimaler Embedder mit fester Dimension -- ohne Modell und ohne Netz."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.5] * self.dim for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.5] * self.dim


@pytest.fixture
def stub_embedder_3d(monkeypatch: pytest.MonkeyPatch) -> _StubEmbedder:
    """Patcht ``embedder_for`` an der Quelle: ``embed_all`` importiert lokal."""
    import academic_vault.embedding_model as em

    embedder = _StubEmbedder(dim=3)
    monkeypatch.setattr(em, "embedder_for", lambda *_args, **_kwargs: embedder)
    return embedder


# ---------------------------------------------------------------------------
# embed_all: Dimensionen und Leer-Eingabe
# ---------------------------------------------------------------------------
def test_embed_all_raises_a_clear_error_for_empty_input() -> None:
    """Xhigh-Review-Fund: leere Chunks *und* Queries duerfen nicht mit einem
    nackten ``StopIteration`` abbrechen. ``build()`` ruft ``embed_all()`` mit
    dem Ergebnis von ``build_chunks()``/``resolve_anchors()`` auf, die bei
    einer leeren/fehlkonfigurierten ``sources.json`` ebenfalls leer sein
    koennen."""
    with pytest.raises(ValueError, match="weder Chunks noch Queries"):
        embed_all([], [], reuse_index={})


def test_embed_all_rejects_reused_vectors_with_inconsistent_dimensions() -> None:
    """Bei voller ``--reuse-vectors``-Abdeckung darf ein beschaedigter/falsch
    langer Alt-Vektor nicht stillschweigend die Dimension des gesamten Laufs
    bestimmen."""
    chunks = [
        {"chunk_id": "c1", "embedding_text": "passage: eins"},
        {"chunk_id": "c2", "embedding_text": "passage: zwei"},
    ]
    reuse_index = {
        "c1": ("passage: eins", encode_vector([0.1, 0.2, 0.3])),
        "c2": ("passage: zwei", encode_vector([0.1, 0.2])),  # falsch lang
    }
    with pytest.raises(ValueError, match="widerspruechliche Vektordimensionen") as excinfo:
        embed_all(chunks, [], reuse_index=reuse_index)
    # Nicht nur DASS, sondern WELCHER Vektor: in einer Fixture mit ueber 50
    # Eintraegen ist die blosse Laengenmenge nicht triagierbar.
    assert "c2" in str(excinfo.value)
    # Und woher er stammt -- die Ursache kann ebenso das frisch geladene
    # Modell sein wie ein beschaedigter Alt-Vektor.
    assert "wiederverwendet" in str(excinfo.value)


def test_embed_all_checks_reused_vectors_in_the_incremental_path(
    stub_embedder_3d: _StubEmbedder,
) -> None:
    """Der dokumentierte Normalfall von ``--reuse-vectors``: Alt-Fixture
    uebernehmen, nur den Zuwachs neu embedden. Ein falsch langer Alt-Vektor
    steht hier neben frischen Vektoren der Modell-Dimension -- ungeprueft
    liefe er in die ``vectors.json``, denn ``verify_manifest`` hasht Texte und
    Metadaten, nie die Vektoren."""
    chunks = [
        {"chunk_id": "c1", "embedding_text": "passage: alt"},
        {"chunk_id": "c2", "embedding_text": "passage: neu"},
    ]
    reuse_index = {"c1": ("passage: alt", encode_vector([0.1, 0.2]))}  # 2d statt 3d
    with pytest.raises(ValueError, match="widerspruechliche Vektordimensionen") as excinfo:
        embed_all(chunks, [], reuse_index=reuse_index)
    assert "c1" in str(excinfo.value)


def test_embed_all_accepts_the_incremental_path_with_consistent_dimensions(
    stub_embedder_3d: _StubEmbedder,
) -> None:
    """Gegenprobe: passt die Alt-Dimension, laeuft der Teil-Reuse-Pfad durch."""
    chunks = [
        {"chunk_id": "c1", "embedding_text": "passage: alt"},
        {"chunk_id": "c2", "embedding_text": "passage: neu"},
    ]
    reuse_index = {"c1": ("passage: alt", encode_vector([0.1, 0.2, 0.3]))}
    encoded_chunks, _encoded_queries, dim, stats = embed_all(chunks, [], reuse_index=reuse_index)
    assert dim == 3
    assert list(encoded_chunks) == ["c1", "c2"]
    assert stats["chunks_reused"] == 1
    assert stats["chunks_embedded"] == 1


def test_embed_all_rejects_a_model_whose_output_width_contradicts_its_dim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``embedder.dim`` ist ein vom Backend *gemeldeter* Wert und geht
    ungeprueft in ``meta.dim``, ``vectors.dim`` und den Manifest-Hash. Liefert
    das Modell eine andere Breite als es meldet, waere die Fixture in sich
    stimmig und trotzdem falsch -- auffallen wuerde das erst beim
    vec0-Insert."""
    import academic_vault.embedding_model as em

    class _LyingEmbedder(_StubEmbedder):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.5, 0.5] for _ in texts]  # 2 statt der gemeldeten 3

    monkeypatch.setattr(em, "embedder_for", lambda *_a, **_kw: _LyingEmbedder(dim=3))

    with pytest.raises(ValueError, match="Der Embedder meldet dim=3"):
        embed_all([{"chunk_id": "c1", "embedding_text": "passage: neu"}], [], reuse_index={})


def test_embed_all_names_the_vector_behind_a_corrupt_blob() -> None:
    """Ein base64-Blob, dessen Laenge kein Vielfaches von 4 ist, muss mit der
    betroffenen ID abbrechen -- sonst durchsucht der Operator die
    ``vectors.json`` von Hand."""
    chunks = [{"chunk_id": "c1", "embedding_text": "passage: eins"}]
    reuse_index = {"c1": ("passage: eins", "AAAA")}  # dekodiert zu 3 Byte

    with pytest.raises(ValueError, match="kein Vielfaches von 4") as excinfo:
        embed_all(chunks, [], reuse_index=reuse_index)
    assert "c1" in str(excinfo.value)

    # Auch der Fall "gar kein gueltiges base64" (binascii.Error erbt von
    # ValueError) muss die ID tragen, nicht nur die Byte-Arithmetik.
    with pytest.raises(ValueError, match="c1") as excinfo:
        embed_all(chunks, [], reuse_index={"c1": ("passage: eins", "AAAAA")})


def test_embed_all_reuses_consistent_vectors_without_loading_the_embedder() -> None:
    chunks = [{"chunk_id": "c1", "embedding_text": "passage: eins"}]
    queries = [{"query_id": "q1", "query": "query: eins"}]
    reuse_index = {
        "c1": ("passage: eins", encode_vector([0.1, 0.2, 0.3])),
        "q1": ("query: eins", encode_vector([0.4, 0.5, 0.6])),
    }
    encoded_chunks, encoded_queries, dim, stats = embed_all(
        chunks, queries, reuse_index=reuse_index
    )
    assert dim == 3
    assert stats == {
        "chunks_reused": 1,
        "chunks_embedded": 0,
        "queries_reused": 1,
        "queries_embedded": 0,
    }


# ---------------------------------------------------------------------------
# compare_against: das --check-against-Gatter
# ---------------------------------------------------------------------------
def _report(per_query: list[dict], by_case: Any = None) -> dict:
    """Kleinster Report, den ``compare_against`` verarbeitet (ein Zustand)."""
    return {
        "quality": {
            "results": {
                "nachher": {
                    "overall": {},
                    "per_query": per_query,
                    "by_case": {} if by_case is None else by_case,
                }
            },
            "deltas": {},
            "deltas_by_case": {},
        }
    }


def _only(problems: list[str], prefix: str) -> str:
    """Die eine Meldung mit diesem Praefix -- mit lesbarem Fehler, falls nicht.

    Bewusst ein Praefix und kein Teilwort: ``by_case`` steckt auch in
    ``quality.deltas_by_case``. Und bewusst ein ``assert`` statt ``next()``:
    faellt die Meldung bei einer Regression ganz weg, soll im Testprotokoll
    die Ursache stehen und nicht ein nacktes ``StopIteration``.
    """
    matching = [problem for problem in problems if problem.startswith(prefix)]
    assert len(matching) == 1, f"erwartet: genau eine Meldung {prefix!r}, bekommen: {problems!r}"
    return matching[0]


def test_compare_against_reports_a_missing_baseline_block() -> None:
    """Rohdaten mit Regressionsanker, Lauf ohne: das muss auffallen, sonst
    altert die Haelfte der eingecheckten Daten ungeprueft weiter."""
    stored = {
        "quality": {"results": {}, "deltas": {}, "deltas_by_case": {}},
        "baseline": {"quality": {"results": {}, "deltas": {}, "deltas_by_case": {}}},
    }
    fresh = {"quality": {"results": {}, "deltas": {}, "deltas_by_case": {}}}
    problems = compare_against(fresh, stored)
    assert any(problem.startswith("baseline") for problem in problems)


def test_compare_against_reports_a_missing_diagnostics_block() -> None:
    """Dieselbe Asymmetrie eine Ebene tiefer: ``--skip-diagnostics`` im
    CI-Schritt liesse den im Report zitierten Diagnoseblock unbemerkt altern."""
    empty = {"results": {}, "deltas": {}, "deltas_by_case": {}}
    stored = {"quality": empty, "diagnostics": {"summary": {"query_count": 38}}}
    problems = compare_against({"quality": empty}, stored)
    assert any(problem.startswith("diagnostics") for problem in problems)


def test_compare_against_names_the_diverging_query_and_case() -> None:
    """Ein CI-Diff darf nicht nur melden, DASS eine Query oder ein Case
    abweicht, sondern muss sagen WELCHE -- und mit welchen Werten, sonst ist
    die Abweichung nur mit einem kompletten lokalen Re-Run triagierbar."""
    fresh = _report(
        per_query=[
            {"query_id": "q1", "retrieved": ["a", "b"]},
            {"query_id": "q2", "retrieved": ["x"]},
        ],
        by_case={"case1": {"ndcg_at_10": 0.5}, "case2": {"ndcg_at_10": 0.9}},
    )
    stored = json.loads(json.dumps(fresh))
    stored["quality"]["results"]["nachher"]["per_query"][1]["retrieved"] = ["y"]
    stored["quality"]["results"]["nachher"]["by_case"]["case2"] = {"ndcg_at_10": 0.1}

    problems = compare_against(fresh, stored)

    retrieved_problem = _only(problems, "quality.results.nachher.per_query.retrieved")
    assert "q2" in retrieved_problem
    assert "q1" not in retrieved_problem
    # Nicht nur die query_id, auch die beiden Trefferlisten -- sonst weiss der
    # Operator zwar welche Query, aber nicht was sich geaendert hat.
    assert "['x']" in retrieved_problem and "['y']" in retrieved_problem

    by_case_problem = _only(problems, "quality.results.nachher.by_case")
    assert "case2" in by_case_problem
    assert "case1" not in by_case_problem


def test_compare_against_survives_raw_data_without_query_id() -> None:
    """Aeltere/handgekuerzte Rohdaten ohne ``query_id`` duerfen das Gatter
    nicht mit einem ``TypeError`` aus ``sorted()`` sprengen -- der CI-Schritt
    soll die Abweichung melden, nicht mit einem Traceback abbrechen."""
    fresh = _report([{"query_id": "q1", "retrieved": ["a"]}])
    stored = _report([{"retrieved": ["a"]}])

    problems = compare_against(fresh, stored)

    assert "q1" in _only(problems, "quality.results.nachher.per_query.retrieved")


def test_compare_against_keeps_comparing_non_string_query_ids_by_key() -> None:
    """Eine numerische ``query_id`` darf den Vergleich nicht still auf einen
    Positionsvergleich zurueckdrehen: sonst passiert ein Report, der eine ganz
    andere Query beschreibt, das Gatter mit Exit 0."""
    fresh = _report([{"query_id": 1, "retrieved": ["a"]}])
    stored = _report([{"query_id": 2, "retrieved": ["a"]}])

    problems = compare_against(fresh, stored)

    problem = _only(problems, "quality.results.nachher.per_query.retrieved")
    assert "1" in problem and "2" in problem
    assert "ohne query_id" not in problem


def test_compare_against_reports_a_reordered_per_query_block() -> None:
    """Der schluesselbasierte Vergleich ist von sich aus reihenfolgeblind; die
    Reihenfolge muss trotzdem gattern, sonst laufen die im Report zitierten
    Per-Query-Tabellen unbemerkt gegen den Lauf auseinander."""
    rows = [
        {"query_id": "q1", "retrieved": ["a"]},
        {"query_id": "q2", "retrieved": ["b"]},
    ]
    problems = compare_against(_report(rows), _report(list(reversed(rows))))

    assert any("Reihenfolge" in problem for problem in problems)


def test_compare_against_reports_order_and_value_drift_together() -> None:
    """Die Reihenfolgepruefung darf nicht hinter der Wertpruefung verschwinden:
    sonst meldet der erste CI-Lauf nur den Wert, der Operator zieht genau den
    nach, und der zweite Lauf ist wegen der bis dahin verschwiegenen
    Reihenfolge erneut rot."""
    fresh = _report(
        [
            {"query_id": "q1", "retrieved": ["a"]},
            {"query_id": "q2", "retrieved": ["b"]},
        ]
    )
    stored = _report(
        [
            {"query_id": "q2", "retrieved": ["b"]},
            {"query_id": "q1", "retrieved": ["ANDERS"]},
        ]
    )

    problems = compare_against(fresh, stored)

    assert "q1" in _only(problems, "quality.results.nachher.per_query.retrieved")
    assert any("Reihenfolge" in problem for problem in problems)


def test_compare_against_reports_a_completely_missing_per_query_block() -> None:
    """Fehlt der Block ganz, gehoert das als eine Zeile gemeldet -- nicht als
    Dump aller Queries mit ``<Zeile fehlt>``. ``diverged_mapping`` macht das
    fuer ``by_case`` bereits so."""
    fresh = _report([{"query_id": "q1", "retrieved": ["a"]}])
    stored = _report([])
    del stored["quality"]["results"]["nachher"]["per_query"]

    problems = compare_against(fresh, stored)

    assert _only(problems, "quality.results.nachher.per_query").endswith(
        "fehlt in den eingecheckten Rohdaten"
    )


def test_compare_against_reports_duplicate_query_ids() -> None:
    """Ein Dict kollabiert Dubletten auf den letzten Eintrag. Dass dabei ein
    Vergleich unter den Tisch faellt, muss in der Ausgabe stehen."""
    fresh = _report([{"query_id": "q1", "retrieved": ["a"]}])
    stored = _report(
        [
            {"query_id": "q1", "retrieved": ["z"]},
            {"query_id": "q1", "retrieved": ["a"]},
        ]
    )

    problems = compare_against(fresh, stored)

    assert any("doppelte query_id" in problem for problem in problems)


def test_compare_against_reports_a_stored_entry_without_retrieved() -> None:
    """Ein ueberzaehliger Eintrag ohne ``retrieved`` darf nicht mit einer gar
    nicht vorhandenen Query verwechselt werden.

    Die Assertion haengt bewusst an der ``per_query.retrieved``-Meldung: mit
    einem blossen ``any("q2" in ...)`` war dieser Test schon einmal gruen,
    weil die (sachlich falsche) Reihenfolge-Meldung die query_id ebenfalls
    enthielt -- die gepruefte Eigenschaft war damit gar nicht abgedeckt."""
    fresh = _report([{"query_id": "q1", "retrieved": ["a"]}])
    stored = _report([{"query_id": "q1", "retrieved": ["a"]}, {"query_id": "q2"}])

    problems = compare_against(fresh, stored)

    problem = _only(problems, "quality.results.nachher.per_query.retrieved")
    assert "q2" in problem
    # Die beiden Fehlzustaende muessen in der Meldung unterscheidbar sein.
    assert "<Zeile fehlt>" in problem and "<Zeile ohne dieses Feld>" in problem


def test_compare_against_reports_a_non_numeric_stored_metric() -> None:
    """Steht in den Rohdaten statt einer Zahl ein String (handeditiert,
    fremder Export), darf ``abs(other - value)`` das Gatter nicht mit einem
    ``TypeError`` sprengen: ``main()`` faengt nur ``ManifestMismatchError``,
    der CI-Schritt endete sonst ohne jede Problemliste."""
    fresh = _report([])
    fresh["quality"]["results"]["nachher"]["overall"] = {"recall_at_10": 0.62}
    stored = json.loads(json.dumps(fresh))
    stored["quality"]["results"]["nachher"]["overall"]["recall_at_10"] = "0.62"

    problems = compare_against(fresh, stored)

    assert "kein vergleichbarer Zahlenwert" in _only(
        problems, "quality.results.nachher.overall.recall_at_10"
    )


def test_compare_against_reports_a_by_case_block_of_the_wrong_type() -> None:
    """Schema-Drift (oder der falsche Report-Pfad) muss als Problem
    herauskommen, nicht als ``TypeError`` aus den Set-Operationen."""
    fresh = _report([], by_case={"case1": {"ndcg_at_10": 0.5}})
    stored = _report([], by_case=[{"case1": {"ndcg_at_10": 0.5}}])

    problems = compare_against(fresh, stored)

    assert any("by_case" in problem for problem in problems)


def test_compare_against_reports_a_completely_missing_by_case_block() -> None:
    """Fehlt der Block in den Rohdaten ganz, ist das eine Abweichung -- auch
    gegenueber einem leeren frischen Block. Sonst faellt ``by_case`` aus
    derselben Asymmetrie heraus, die baseline und diagnostics absichern."""
    fresh = _report([], by_case={})
    stored = _report([])
    del stored["quality"]["results"]["nachher"]["by_case"]

    problems = compare_against(fresh, stored)

    assert any("by_case" in problem for problem in problems)
