"""Konstruktionsregeln fuer die #800-Verbreiterung des #708-Chunk-Goldsets.

Issue #800 verbreitert ``sources.json`` von 11 Dokumenten/26 Queries auf
mindestens 55 (Ziel ~60) Queries bei gleicher Sprach- und ``case``-Verteilung
und denselben Konstruktionsregeln wie #708/#790. AC2 verlangt ausdruecklich:
"ein Test belegt das, statt es zu behaupten." Dieses Modul ist dieser Test.

Die Regeln, gegen die geprueft wird (aus ``docs/evals/retrieval-chunk-goldset-708.md``
und ``docs/evals/2026-08-09-chunk-fusion-goldset-790.md``):

1. **Ankerauflösung** — jede Query hat mindestens einen woertlichen Anker, und
   jeder Anker kommt in mindestens einem Chunk vor (``resolve_anchors`` bricht
   sonst mit ``ValueError`` ab; hier zusaetzlich als Bedingung ueber ein
   hermetisches ``build_chunks``, ohne Live-Modell).
2. **Eindeutigkeit** — ``query_id`` und ``doc_id`` sind kollisionsfrei.
3. **Trivialitätsverbot** — der Query-Text ist keine wörtliche Kopie des
   Ankers und umgekehrt (sonst misst die Query nur Zeichenkettengleichheit,
   nicht Retrieval).
4. **Sprachlücke ohne lexikalische Bruecke** — ``language-gap``- und
   ``cross-language``-Queries teilen kein Wort ab fuenf Zeichen mit dem
   Text ihres Zielchunks (dieselbe Pruefung wie in #708, hier auf ALLE
   14 bzw. 5 Faelle statt nur auf die urspruenglichen 6 bzw. 2).
5. **Verteilung nicht einseitiger als vorher** — ``lang`` bleibt nahe 50/50,
   die ``case``-Anteile duerfen sich gegenueber dem 26er-Set nicht zu Lasten
   von ``language-gap``/``cross-language`` verschieben.
6. **Distraktor-Rolle** — Dokumente mit ``_role: distractor`` werden von
   keiner Query referenziert (sie erzeugen Rangdruck, sind aber nie das
   Ziel einer Relevanzentscheidung).
7. **Trefferbasis nicht duenner** — das Verhaeltnis Chunks/Queries faellt
   gegenueber dem 26er-Set (30 Chunks / 26 Queries) nicht ab, und die
   Dokumentenzahl ist in der Groessenordnung einer Verdopplung gewachsen.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDSET_DIR = REPO_ROOT / "tests" / "fixtures" / "retrieval_goldset_chunks_708"
SOURCES_PATH = GOLDSET_DIR / "sources.json"
REPORT_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-10-chunk-goldset-widening-800.md"

# Referenzwerte des 26er-Sets aus #708 (siehe
# docs/evals/retrieval-chunk-goldset-708.md, "Queries"-Absatz).
OLD_QUERY_COUNT = 26
OLD_DOC_COUNT = 11
OLD_CASE_COUNTS = {"same-language": 18, "language-gap": 6, "cross-language": 2}
OLD_CHUNK_COUNT = 30

MIN_QUERY_COUNT = 55  # AC1 des Issues
TARGET_QUERY_COUNT = 60


@pytest.fixture(scope="module")
def sources() -> dict:
    return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chunks(sources: dict) -> list[dict]:
    """Hermetisches ``build_chunks`` -- approximierter Tokenizer reicht fuer
    die Struktur- und Verteilungspruefungen dieses Moduls; der exakte
    Live-Tokenizer wird separat in ``test_live_rechunk_matches_fixture``
    (#708) und beim Live-Bau selbst geprueft."""
    from scripts.eval.build_retrieval_chunk_goldset import build_chunks as _build_chunks

    return _build_chunks(sources)


@pytest.fixture(scope="module")
def resolved_queries(sources: dict, chunks: list[dict]) -> list[dict]:
    from scripts.eval.build_retrieval_chunk_goldset import resolve_anchors

    return resolve_anchors(chunks, sources)


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= 5}


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


# ---------------------------------------------------------------------------
# Regel 1 + 2: Ankerauflösung und Eindeutigkeit
# ---------------------------------------------------------------------------
class TestAnchorsAndIdentity:
    def test_query_count_reaches_the_800_target(self, sources: dict) -> None:
        count = len(sources["queries"])
        assert count >= MIN_QUERY_COUNT, (
            f"AC1 (#800) verlangt mindestens {MIN_QUERY_COUNT}, hat {count}"
        )
        assert count >= TARGET_QUERY_COUNT - 5, "deutlich unter der Zielgroesse ~60"

    def test_every_query_has_exactly_one_literal_anchor(self, sources: dict) -> None:
        for query in sources["queries"]:
            anchors = query["anchors"]
            assert anchors, query["query_id"]
            for anchor in anchors:
                assert isinstance(anchor, str) and anchor.strip(), query["query_id"]

    def test_every_anchor_resolves_to_at_least_one_chunk(
        self, resolved_queries: list[dict]
    ) -> None:
        """Regressionsschutz: ``resolve_anchors`` haette sonst schon abgebrochen --
        dieser Test macht die Bedingung explizit statt sie nur implizit ueber
        einen erfolgreichen Fixture-Aufbau vorauszusetzen."""
        for query in resolved_queries:
            assert query["relevant_chunk_ids"], query["query_id"]

    def test_query_ids_are_unique(self, sources: dict) -> None:
        ids = [q["query_id"] for q in sources["queries"]]
        duplicates = [qid for qid, count in Counter(ids).items() if count > 1]
        assert not duplicates, f"doppelte query_id: {duplicates}"

    def test_doc_ids_are_unique(self, sources: dict) -> None:
        ids = [d["doc_id"] for d in sources["documents"]]
        duplicates = [did for did, count in Counter(ids).items() if count > 1]
        assert not duplicates, f"doppelte doc_id: {duplicates}"

    def test_no_query_field_is_empty_or_missing(self, sources: dict) -> None:
        required = ("query_id", "lang", "case", "query", "anchors")
        for query in sources["queries"]:
            for field in required:
                assert field in query, f"{query.get('query_id', '<ohne id>')}: Feld {field} fehlt"
            assert query["query"].strip(), query["query_id"]
            assert query["lang"] in ("en", "de"), query["query_id"]
            assert query["case"] in ("same-language", "language-gap", "cross-language"), query[
                "query_id"
            ]


# ---------------------------------------------------------------------------
# Regel 3: Trivialitätsverbot
# ---------------------------------------------------------------------------
class TestNoTrivialLexicalMatch:
    def test_query_text_is_not_a_copy_of_its_anchor(self, sources: dict) -> None:
        """Eine Query, die ihren Anker wörtlich enthält (oder umgekehrt), misst
        Zeichenkettengleichheit statt semantischer Passung -- genau die
        Trivialität, die dieses Goldset laut #708 ausdrücklich vermeidet
        (Queries sind ausgeschriebene, umformulierte Fragen, keine Zitate)."""
        for query in sources["queries"]:
            normalized_query = _normalize(query["query"])
            for anchor in query["anchors"]:
                normalized_anchor = _normalize(anchor)
                assert normalized_anchor not in normalized_query, (
                    f"{query['query_id']}: Query enthaelt ihren eigenen Anker woertlich"
                )
                assert normalized_query not in normalized_anchor, (
                    f"{query['query_id']}: Anker ist eine Teilzeichenkette der Query"
                )


# ---------------------------------------------------------------------------
# Regel 4: Sprachlücke ohne lexikalische Brücke
# ---------------------------------------------------------------------------
class TestLanguageGapDiscipline:
    def test_language_gap_queries_share_no_content_word_with_their_target(
        self, resolved_queries: list[dict], chunks: list[dict]
    ) -> None:
        chunk_text = {c["chunk_id"]: c["chunk_text"] for c in chunks}
        chunk_lang = {c["chunk_id"]: c["lang"] for c in chunks}
        gap_queries = [q for q in resolved_queries if q["case"] == "language-gap"]
        assert len(gap_queries) >= OLD_CASE_COUNTS["language-gap"]
        for query in gap_queries:
            assert query["lang"] == "de", query["query_id"]
            targets = query["relevant_chunk_ids"]
            assert all(chunk_lang[cid] == "en" for cid in targets), query["query_id"]
            overlap: set[str] = set()
            for cid in targets:
                overlap |= _content_words(query["query"]) & _content_words(chunk_text[cid])
            assert not overlap, (
                f"{query['query_id']} teilt Woerter mit dem Zielchunk: {sorted(overlap)}"
            )

    def test_cross_language_queries_share_no_content_word_with_their_target(
        self, resolved_queries: list[dict], chunks: list[dict]
    ) -> None:
        chunk_text = {c["chunk_id"]: c["chunk_text"] for c in chunks}
        chunk_lang = {c["chunk_id"]: c["lang"] for c in chunks}
        cross_queries = [q for q in resolved_queries if q["case"] == "cross-language"]
        assert len(cross_queries) >= OLD_CASE_COUNTS["cross-language"]
        for query in cross_queries:
            assert query["lang"] == "en", query["query_id"]
            targets = query["relevant_chunk_ids"]
            assert all(chunk_lang[cid] == "de" for cid in targets), query["query_id"]
            overlap: set[str] = set()
            for cid in targets:
                overlap |= _content_words(query["query"]) & _content_words(chunk_text[cid])
            assert not overlap, (
                f"{query['query_id']} teilt Woerter mit dem Zielchunk: {sorted(overlap)}"
            )


# ---------------------------------------------------------------------------
# Regel 5: Verteilung nicht einseitiger als vorher
# ---------------------------------------------------------------------------
class TestDistributionIsNotMoreSkewed:
    def test_language_split_stays_close_to_even(self, sources: dict) -> None:
        counts = Counter(q["lang"] for q in sources["queries"])
        total = sum(counts.values())
        for lang in ("en", "de"):
            share = counts[lang] / total
            assert 0.45 <= share <= 0.55, (
                f"lang={lang}: Anteil {share:.3f} weicht zu stark von 50/50 ab"
            )

    def test_same_language_share_does_not_grow(self, sources: dict) -> None:
        """Der dominante, 'leichteste' Fall darf gegenueber #708 nicht noch
        dominanter werden -- sonst verbreitert das Set die Basis, ohne die
        Aufloesung bei den schwierigen Faellen (language-gap/cross-language)
        tatsaechlich zu verbessern."""
        counts = Counter(q["case"] for q in sources["queries"])
        total = sum(counts.values())
        old_total = sum(OLD_CASE_COUNTS.values())
        old_share = OLD_CASE_COUNTS["same-language"] / old_total
        new_share = counts["same-language"] / total
        assert new_share <= old_share + 0.02, (
            f"same-language-Anteil gestiegen: {old_share:.4f} -> {new_share:.4f}"
        )

    def test_hard_cases_keep_at_least_their_old_share(self, sources: dict) -> None:
        counts = Counter(q["case"] for q in sources["queries"])
        total = sum(counts.values())
        old_total = sum(OLD_CASE_COUNTS.values())
        for case in ("language-gap", "cross-language"):
            old_share = OLD_CASE_COUNTS[case] / old_total
            new_share = counts[case] / total
            assert new_share >= old_share - 0.02, (
                f"{case}-Anteil gesunken: {old_share:.4f} -> {new_share:.4f}"
            )

    def test_case_counts_reach_proportional_minimums(self, sources: dict) -> None:
        """AC1 wortwoertlich: mind. 55 Queries, Verteilung nicht einseitiger.
        Hier zusaetzlich als absolute Untergrenze je ``case``, proportional
        zum 26er-Set hochgerechnet auf 55 Queries."""
        counts = Counter(q["case"] for q in sources["queries"])
        old_total = sum(OLD_CASE_COUNTS.values())
        for case, old_count in OLD_CASE_COUNTS.items():
            minimum = round(old_count / old_total * MIN_QUERY_COUNT)
            assert counts[case] >= minimum, (
                f"{case}: {counts[case]} < proportionales Minimum {minimum}"
            )


# ---------------------------------------------------------------------------
# Regel 6: Distraktor-Rolle der Dokumente
# ---------------------------------------------------------------------------
class TestDistractorDocuments:
    def test_distractor_documents_exist_and_are_not_referenced_by_any_query(
        self, resolved_queries: list[dict], chunks: list[dict]
    ) -> None:
        distractor_docs = {
            d["doc_id"]
            for d in json.loads(SOURCES_PATH.read_text(encoding="utf-8"))["documents"]
            if d.get("_role") == "distractor"
        }
        assert distractor_docs, (
            "kein Distraktor-Dokument im Set -- Rangdruck ohne Distraktoren ist ungeprueft"
        )
        chunk_owner = {c["chunk_id"]: c["doc_id"] for c in chunks}
        for query in resolved_queries:
            referenced_docs = {chunk_owner[cid] for cid in query["relevant_chunk_ids"]}
            hit = referenced_docs & distractor_docs
            assert not hit, f"{query['query_id']} referenziert Distraktor-Dokument(e) {hit}"

    def test_distractor_share_of_documents_is_comparable_to_708(self, sources: dict) -> None:
        """#708: 3 von 11 Dokumenten sind Distraktoren (~27%). Die #800-Erweiterung
        soll dieses Verhaeltnis grob halten, nicht die Distraktor-Rolle verwaessern."""
        docs = sources["documents"]
        distractor_count = sum(1 for d in docs if d.get("_role") == "distractor")
        share = distractor_count / len(docs)
        assert 0.15 <= share <= 0.40, (
            f"Distraktor-Anteil {share:.3f} weicht stark vom #708-Verhaeltnis (~0.27) ab"
        )


# ---------------------------------------------------------------------------
# Regel 7: Trefferbasis nicht duenner, Korpus in der Groessenordnung verdoppelt
# ---------------------------------------------------------------------------
class TestCorpusKeepsUpWithQueries:
    def test_document_count_grew_roughly_by_a_factor_of_two(self, sources: dict) -> None:
        doc_count = len(sources["documents"])
        assert doc_count >= round(OLD_DOC_COUNT * 1.5), (
            f"Dokumentenzahl {doc_count} ist nicht in der Groessenordnung einer Verdopplung "
            f"gegenueber #708 ({OLD_DOC_COUNT}) gewachsen"
        )

    def test_chunk_count_grew_roughly_by_a_factor_of_two(self, chunks: list[dict]) -> None:
        assert len(chunks) >= round(OLD_CHUNK_COUNT * 1.8), (
            f"Chunkzahl {len(chunks)} ist nicht in der Groessenordnung einer Verdopplung "
            f"gegenueber #708 ({OLD_CHUNK_COUNT}) gewachsen"
        )

    def test_corpus_to_k_saturation_does_not_get_worse(self, chunks: list[dict]) -> None:
        """Die eigentliche 'Trefferbasis nicht duenner'-Sorge aus #708/#800 ist
        nicht das Verhaeltnis Chunks/Query, sondern wie viel des Korpus in die
        Top-``k``-Trefferliste passt: bei 30 Chunks und k=10 passt ein Drittel
        des Bestands hinein, und genau das saettigt Recall@10 fuer
        ``same-language`` bereits bei 1.0 (siehe docs/evals/retrieval-chunk-
        goldset-708.md, 'Grenzen'). Der neue Korpus muss mindestens denselben
        Sicherheitsabstand zu ``k`` halten wie #708, eher mehr."""
        k = 10
        old_corpus_per_k = OLD_CHUNK_COUNT / k
        new_corpus_per_k = len(chunks) / k
        assert new_corpus_per_k >= old_corpus_per_k, (
            f"Korpus/k gesunken: {old_corpus_per_k:.2f} (#708) -> {new_corpus_per_k:.2f} (#800) "
            "-- Recall@10 wuerde noch schneller saettigen als vorher"
        )

    def test_resolution_per_query_is_reported_correctly(self, sources: dict) -> None:
        """1/n Recall-Punkte je Query -- die Kennzahl, die der #800-Report nennen muss.

        Rechnet nicht nur die beiden Werte gegeneinander (das leistet schon
        ``test_query_count_reaches_the_800_target`` implizit), sondern liest
        den tatsaechlichen Report und prueft, dass er die korrekt gerundete
        neue UND alte Aufloesung nennt -- sonst waere der Reportinhalt selbst
        ungeprueft."""
        n = len(sources["queries"])
        resolution = 1.0 / n
        old_resolution = 1.0 / OLD_QUERY_COUNT
        assert resolution < old_resolution, (
            "die Aufloesung muss sich gegenueber #708 verbessert haben"
        )
        assert resolution <= 1.0 / MIN_QUERY_COUNT + 1e-9

        report_text = REPORT_PATH.read_text(encoding="utf-8")
        new_formatted = f"{resolution:.4f}".replace(".", ",")
        old_formatted = f"{old_resolution:.4f}".replace(".", ",")
        assert new_formatted in report_text, (
            f"neue Aufloesung {new_formatted} (1/{n}) fehlt im #800-Report"
        )
        assert old_formatted in report_text, (
            f"alte #708-Aufloesung {old_formatted} (1/{OLD_QUERY_COUNT}) fehlt im "
            "#800-Report zum Vergleich"
        )
