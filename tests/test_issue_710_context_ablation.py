"""Vier-Arme-Kontextsatz-Vergleich (#785, Kind-Issue von Epic #710).

Misst, ob ein echter, modellgeschriebener inhaltlicher Kontextsatz das
Retrieval gegenueber dem deterministischen Metadaten-Satz (Produktionszustand)
und gegenueber gar keinem Kontextsatz verbessert -- auf dem bge-m3-Chunk-
Goldset aus #731 (nicht der aelteren e5-Fassung aus #708, siehe #732).

Drei Eigenschaften machen die Messung ueberhaupt erst belastbar, und genau die
pruefen diese Tests:

* **Derselbe Suchpfad** -- der ``metadata_context``-Arm muss die #731-bge-m3-
  Zahlen exakt reproduzieren (Toleranz 1e-9). Weicht er ab, misst dieser
  Harness etwas anderes als #731, und jeder gemeldete Unterschied waere ein
  Artefakt des neuen Codes statt ein Befund ueber Kontextsaetze.
* **Kontraktkonforme Fixture** -- jeder Satz haelt die 25-Woerter-Grenze aus
  dem #710-Plan-Kommentar ein, jeder Goldset-Chunk hat genau einen Modellsatz.
* **Teilmengen getrennt** -- das Gesamtmittel ist auf 11 Dokumenten gesaettigt;
  ``same-language``/``language-gap``/``cross-language`` muessen einzeln
  auswertbar bleiben, nicht nur im Aggregat.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.eval import build_context_sentences_710 as builder
from scripts.eval import run_context_ablation_710 as ablation
from scripts.eval import run_embedding_candidates_731 as candidates_731

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-08-context-ablation-710.md"
RESULTS_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-08-context-ablation-710-live-results.json"
EVALS_README = REPO_ROOT / "docs" / "evals" / "README.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def goldset():
    return ablation.load_base_goldset()


@pytest.fixture(scope="module")
def sentences():
    return ablation.load_sentences()


@pytest.fixture(scope="module")
def vectors_meta():
    return ablation.load_vectors_meta()


@pytest.fixture(scope="module")
def report():
    return ablation.build_report()


@pytest.fixture(scope="module")
def results_json():
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fixture-Vertrag: Saetze, Manifest, Abdeckung
# ---------------------------------------------------------------------------
class TestSentenceFixture:
    def test_every_goldset_chunk_has_exactly_one_sentence_pair(self, goldset, sentences):
        goldset_ids = {c["chunk_id"] for c in goldset["chunks"]}
        sentence_ids = [e["chunk_id"] for e in sentences["sentences"]]
        assert set(sentence_ids) == goldset_ids
        assert len(sentence_ids) == len(set(sentence_ids)), "doppelte chunk_id in sentences.json"

    def test_no_sentence_exceeds_the_25_word_limit(self, sentences):
        for entry in sentences["sentences"]:
            for field in ("sentence", "sentence_de"):
                words = len(entry[field].split())
                assert words <= ablation.MAX_SENTENCE_WORDS, (entry["chunk_id"], field, words)

    def test_sentences_are_not_the_metadata_boilerplate(self, sentences):
        """Ein Modellsatz darf nicht zufaellig wieder die Herkunftsfloskel sein."""
        for entry in sentences["sentences"]:
            assert "Dieser Abschnitt stammt aus" not in entry["sentence"]
            assert "Dieser Abschnitt stammt aus" not in entry["sentence_de"]

    def test_sentence_de_is_german_even_for_english_chunks(self, sentences):
        """Stichprobe: die Woerter 'the'/'and' duerfen in sentence_de nicht dominieren."""
        english_only_markers = {" the ", " and ", " that "}
        for entry in sentences["sentences"]:
            padded = f" {entry['sentence_de'].lower()} "
            hits = sum(1 for marker in english_only_markers if marker in padded)
            assert hits == 0, (entry["chunk_id"], entry["sentence_de"])

    def test_usage_totals_are_real_recorded_fields(self, sentences):
        meta = sentences["meta"]
        assert meta["usage_totals"]["output_tokens"] > 0
        assert meta["total_cost_usd"] > 0.0
        assert meta["sentence_latency_ms"]["n"] == len(sentences["documents"])
        for doc in sentences["documents"]:
            assert doc["usage"], doc["doc_id"]
            assert doc["duration_ms"] > 0.0

    def test_build_script_needs_no_api_key(self):
        """Kein Plugin-Pfad darf einen ANTHROPIC_API_KEY brauchen (#632)."""
        text = (REPO_ROOT / "scripts" / "eval" / "build_context_sentences_710.py").read_text(
            encoding="utf-8"
        )
        assert "ANTHROPIC_API_KEY" not in text
        assert "VAULT_CONTEXT_LIVE_TRANSFORM" in text
        assert "VAULT_E5_LIVE_TEST" in text


class TestManifest:
    def test_manifest_matches_the_checked_in_vectors(self, goldset, sentences, vectors_meta):
        """Kein Drift -- die eingecheckte Fixture ist in sich konsistent."""
        arm_texts = ablation.verify_manifest(goldset, sentences, vectors_meta)
        assert set(arm_texts) == set(ablation.ARMS)

    def test_edited_sentence_text_is_fatal(self, goldset, sentences, vectors_meta):
        """Ein nachtraeglich geaenderter Modellsatz mit altem Vektor faellt hier auf."""
        tampered = copy.deepcopy(sentences)
        tampered["sentences"][0]["sentence"] += " angehaengter Text"
        with pytest.raises(ablation.ManifestMismatchError):
            ablation.verify_manifest(goldset, tampered, vectors_meta)

    def test_missing_sentence_is_fatal(self, goldset, sentences, vectors_meta):
        tampered = copy.deepcopy(sentences)
        del tampered["sentences"][0]
        with pytest.raises(ablation.ManifestMismatchError):
            ablation.verify_manifest(goldset, tampered, vectors_meta)

    def test_oversized_sentence_in_fixture_is_fatal(self, goldset, sentences, vectors_meta):
        """Selbst wenn der Hash zufaellig passen wuerde: die 25-Woerter-Grenze ist ein Hard-Gate."""
        tampered = copy.deepcopy(sentences)
        tampered["sentences"][0]["sentence"] = " ".join(["wort"] * 30)
        with pytest.raises(ablation.ManifestMismatchError):
            ablation.verify_manifest(goldset, tampered, vectors_meta)

    def test_cli_exits_2_on_manifest_drift(self, tmp_path):
        """End-to-End: eine getamperte sentences.json bricht den Runner ab, nicht nur die Funktion."""
        tampered_dir = tmp_path / "context_sentences_710"
        tampered_dir.mkdir()
        sentences_data = json.loads(ablation.SENTENCES_PATH.read_text(encoding="utf-8"))
        sentences_data["sentences"][0]["sentence"] += " nachtraeglich angehaengt"
        tampered_sentences = tampered_dir / "sentences.json"
        tampered_sentences.write_text(
            json.dumps(sentences_data, ensure_ascii=False), encoding="utf-8"
        )
        tampered_vectors = tampered_dir / "vectors.json"
        tampered_vectors.write_text(
            ablation.VECTORS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_context_ablation_710.py"),
                "--sentences",
                str(tampered_sentences),
                "--vectors",
                str(tampered_vectors),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode == 2, proc.stdout[-2000:] + proc.stderr[-2000:]
        assert "manifest" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# Kontrolltest: metadata_context reproduziert #731
# ---------------------------------------------------------------------------
class TestControlCheck:
    def test_metadata_context_reproduces_731_numbers_exactly(self, report):
        assert report["control_check"]["passed"], report["control_check"]["problems"]

    def test_control_check_compares_against_a_fresh_731_run(self, report):
        """Referenz ist ein FRISCHER #731-Lauf, keine im Report vorgeschriebene Zahl."""
        goldset_731, vectors_731 = candidates_731.load_candidate_fixture("bge-m3")
        fresh_reference = candidates_731.evaluate_candidate(goldset_731, vectors_731, k=10)
        for metric, value in report["reports"]["metadata_context"]["overall"].items():
            assert value == pytest.approx(fresh_reference["overall"][metric], abs=1e-9), metric

    def test_metadata_context_uses_the_exact_731_embedding_texts(self, goldset):
        """Der Arm darf den #731-Text NICHT rekonstruieren, sondern muss ihn 1:1 uebernehmen."""
        for chunk in goldset["chunks"]:
            context_sentence, embedding_text = ablation.arm_embedding_text(
                "metadata_context", chunk, None
            )
            assert context_sentence == chunk["context_sentence"]
            assert embedding_text == chunk["embedding_text"]

    def test_tampering_metadata_context_breaks_the_control_check(self):
        """Gegenprobe: ein manipulierter metadata_context-Report faellt beim Kontrolltest auf."""
        goldset_731, vectors_731 = candidates_731.load_candidate_fixture("bge-m3")
        fresh_reference = candidates_731.evaluate_candidate(goldset_731, vectors_731, k=10)
        tampered = copy.deepcopy(fresh_reference)
        tampered["overall"]["ndcg_at_10"] += 0.1
        result = ablation.control_check(tampered)
        assert not result["passed"]
        assert result["problems"]


# ---------------------------------------------------------------------------
# AC1: alle vier Arme, gleiche Queries, Chunk-Ebene
# ---------------------------------------------------------------------------
class TestArms:
    def test_all_four_arms_present(self, report):
        assert set(report["reports"]) == set(ablation.ARMS)
        assert len(ablation.ARMS) == 4

    def test_all_arms_measure_exactly_the_same_queries(self, goldset, report):
        expected_ids = [q["query_id"] for q in goldset["queries"]]
        for arm in ablation.ARMS:
            rows = report["reports"][arm]["per_query"]
            assert [r["query_id"] for r in rows] == expected_ids, arm

    def test_evaluation_is_chunk_level_not_paper_aggregated(self, goldset, report):
        """Ranked IDs sind Chunk-IDs (``doc#index``), keine Paper-IDs."""
        doc_ids = {d["doc_id"] for d in goldset["documents"]}
        for arm in ablation.ARMS:
            for row in report["reports"][arm]["per_query"]:
                for chunk_id in row["retrieved"]:
                    assert chunk_id not in doc_ids
                    assert "#" in chunk_id

    def test_metrics_are_present_and_bounded(self, report):
        for arm in ablation.ARMS:
            overall = report["reports"][arm]["overall"]
            for metric in ("recall_at_10", "ndcg_at_10", "mrr"):
                assert 0.0 <= overall[metric] <= 1.0, (arm, metric)

    def test_subsets_are_reported_separately_from_the_overall_mean(self, report):
        """Das Gesamtmittel darf die Teilmengen nicht verdecken (#729-Lektion)."""
        for arm in ablation.ARMS:
            entry = report["reports"][arm]
            assert set(entry["subsets"]) == {"same-language", "language-gap", "cross-language"}
            assert entry["subset_counts"] == {
                "same-language": 18,
                "language-gap": 6,
                "cross-language": 2,
            }
            # Mindestens eine Teilmenge muss vom Gesamtmittel abweichen, sonst
            # waere die getrennte Ausweisung Kosmetik ohne Informationsgehalt.
            assert any(entry["subsets"][case] != entry["overall"] for case in entry["subsets"]), arm

    def test_no_context_arm_has_no_context_sentence_content(self, goldset, report):
        """Der no_context-Arm embeddet nur chunk_text -- ohne Leerzeichen-Praefix."""
        for chunk in goldset["chunks"]:
            _context, embedding_text = ablation.arm_embedding_text("no_context", chunk, None)
            assert embedding_text == chunk["chunk_text"]


# ---------------------------------------------------------------------------
# Deltas zwischen den Armen
# ---------------------------------------------------------------------------
class TestDeltas:
    def test_all_delta_pairs_present(self, report):
        expected_keys = {f"{c}_vs_{b}" for c, b, _label in ablation.DELTA_PAIRS}
        assert set(report["deltas"]) == expected_keys

    def test_deltas_computed_overall_and_per_subset(self, report):
        for block in report["deltas"].values():
            assert set(block["subsets"]) == {"same-language", "language-gap", "cross-language"}
            for scope in (block["overall"], *block["subsets"].values()):
                for metric in ("recall_at_10", "ndcg_at_10", "mrr"):
                    assert metric in scope

    def test_language_gap_subset_has_only_six_queries(self, report):
        for block in report["deltas"].values():
            for metric_block in block["subsets"]["language-gap"].values():
                assert metric_block["n"] == 6

    def test_cross_language_subset_has_only_two_queries(self, report):
        for block in report["deltas"].values():
            for metric_block in block["subsets"]["cross-language"].values():
                assert metric_block["n"] == 2


# ---------------------------------------------------------------------------
# Reproduzierbarkeit: frischer Lauf deckt sich mit den eingecheckten Rohdaten
# ---------------------------------------------------------------------------
class TestReproducibility:
    def test_fresh_run_matches_checked_in_live_results(self, report, results_json):
        problems = ablation.compare_against(report, results_json)
        assert not problems, problems

    def test_cli_exits_zero_against_current_live_results(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_context_ablation_710.py"),
                "--check-against",
                str(RESULTS_PATH),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]


# ---------------------------------------------------------------------------
# Report und Doku-Verdrahtung
# ---------------------------------------------------------------------------
class TestReportDocument:
    def test_report_exists(self):
        assert DOC_PATH.is_file()

    def test_report_states_the_control_check_result(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        assert "Kontrolltest" in text
        assert "731" in text

    def test_report_covers_all_four_arms(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        for arm in ablation.ARMS:
            assert arm in text, arm

    def test_report_shows_subset_tables_not_only_overall(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        assert "same-language" in text
        assert "language-gap" in text
        assert "cross-language" in text

    def test_report_numbers_match_the_live_results(self, results_json):
        text = DOC_PATH.read_text(encoding="utf-8")
        for arm in ablation.ARMS:
            overall = results_json["reports"][arm]["overall"]
            for metric in ("recall_at_10", "ndcg_at_10", "mrr"):
                formatted = f"{overall[metric]:.4f}".replace(".", ",")
                assert formatted in text, f"{arm}.overall.{metric} ({formatted}) fehlt im Report"

    def test_report_discloses_language_confound_handling(self):
        """model_context_de muss entweder gebaut ODER als Luecke benannt sein -- nie stillschweigend."""
        text = DOC_PATH.read_text(encoding="utf-8")
        assert "model_context_de" in text
        assert "Sprach-Confound" in text or "Sprachconfound" in text

    def test_report_links_from_evals_readme(self):
        text = EVALS_README.read_text(encoding="utf-8")
        assert DOC_PATH.name in text

    def test_changelog_mentions_the_issue(self):
        text = CHANGELOG_PATH.read_text(encoding="utf-8")
        assert "785" in text


# ---------------------------------------------------------------------------
# Prompt-Vertrag des Builders
# ---------------------------------------------------------------------------
class TestBuilderPrompt:
    def test_prompt_asks_for_both_languages(self):
        prompt = builder.context_sentence_prompt(
            "doc-1",
            "Ein Titel",
            "en",
            [{"chunk_index": 0, "chunk_text": "Some text."}],
        )
        assert "sentence_de" in prompt
        assert "25 Woerter" in prompt

    def test_json_extractor_ignores_trailing_prose(self):
        """Regressionsfall aus dem Referenzlauf: eine nachtraegliche Selbstkorrektur."""
        answer = (
            '[{"chunk_index": 0, "sentence": "a", "sentence_de": "b"}]\n\n'
            "Ich korrigiere das Format: "
            '[{"chunk_index": 0, "sentence": "c", "sentence_de": "d"}]'
        )
        extracted = builder._extract_json_array(answer)
        assert extracted == [{"chunk_index": 0, "sentence": "a", "sentence_de": "b"}]

    def test_json_extractor_ignores_code_fences(self):
        answer = '```json\n[{"chunk_index": 0, "sentence": "a", "sentence_de": "b"}]\n```'
        extracted = builder._extract_json_array(answer)
        assert extracted == [{"chunk_index": 0, "sentence": "a", "sentence_de": "b"}]

    def test_validate_sentences_rejects_oversized_sentence(self):
        chunks = [{"chunk_index": 0, "chunk_text": "x"}]
        answer = json.dumps(
            [{"chunk_index": 0, "sentence": " ".join(["w"] * 26), "sentence_de": "kurz"}]
        )
        assert builder._validate_sentences(answer, chunks) is None

    def test_validate_sentences_rejects_missing_chunk_index(self):
        chunks = [
            {"chunk_index": 0, "chunk_text": "x"},
            {"chunk_index": 1, "chunk_text": "y"},
        ]
        answer = json.dumps([{"chunk_index": 0, "sentence": "a", "sentence_de": "b"}])
        assert builder._validate_sentences(answer, chunks) is None

    def test_validate_sentences_accepts_a_well_formed_answer(self):
        chunks = [{"chunk_index": 0, "chunk_text": "x"}, {"chunk_index": 1, "chunk_text": "y"}]
        answer = json.dumps(
            [
                {"chunk_index": 0, "sentence": "a", "sentence_de": "b"},
                {"chunk_index": 1, "sentence": "c", "sentence_de": "d"},
            ]
        )
        parsed = builder._validate_sentences(answer, chunks)
        assert parsed == {
            0: {"sentence": "a", "sentence_de": "b"},
            1: {"sentence": "c", "sentence_de": "d"},
        }


# ---------------------------------------------------------------------------
# Regressionsfall: Resume-Cache ueberlebt den JSON-Roundtrip (int-Keys)
# ---------------------------------------------------------------------------
class TestBuilderCacheResume:
    """``by_index`` hat int-Schluessel im Speicher, aber JSON kennt nur String-Keys.

    ``transform_one_document`` liefert ``by_index`` mit int-Schluesseln
    (siehe ``_validate_sentences``). Landet das Record ueber
    ``json.dumps``/``json.loads`` im Cache und zurueck, werden daraus
    ``"0"``/``"1"``/... -- der Lesepfad in ``build_sentences`` greift aber mit
    ``chunk["chunk_index"]`` (ein int) zu. Ohne Ruecktausch stirbt jeder
    Wiederanlauf nach einem Abbruch (Timeout, erschoepfte Versuche) mit
    ``KeyError``, obwohl genau dafuer der Cache existiert.
    """

    @staticmethod
    def _tiny_goldset() -> dict:
        return {
            "meta": {"manifest_sha256": "test-manifest"},
            "documents": [{"doc_id": "doc-a", "lang": "en", "title": "Titel A"}],
            "chunks": [
                {
                    "chunk_id": "doc-a#0",
                    "doc_id": "doc-a",
                    "lang": "en",
                    "chunk_index": 0,
                    "chunk_text": "Erster Chunk.",
                },
                {
                    "chunk_id": "doc-a#1",
                    "doc_id": "doc-a",
                    "lang": "en",
                    "chunk_index": 1,
                    "chunk_text": "Zweiter Chunk.",
                },
            ],
        }

    def test_build_sentences_resumes_from_a_cache_file_without_keyerror(self, tmp_path):
        record = {
            "doc_id": "doc-a",
            "by_index": {
                0: {"sentence": "a", "sentence_de": "a-de"},
                1: {"sentence": "b", "sentence_de": "b-de"},
            },
            "duration_ms": 123.4,
            "attempts": 1,
            "session_id": "sess-1",
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
        cache_path = tmp_path / "sentences.partial.jsonl"
        # Derselbe Roundtrip wie im echten Lauf: build_sentences schreibt mit
        # json.dumps, ein Wiederanlauf liest mit json.loads -- die Testdaten
        # muessen also durch genau diesen Roundtrip, sonst waeren int-Keys
        # (die ``dict`` in Python zulaesst) nie zu String-Keys geworden und
        # der Test wuerde den Bug gar nicht auf die Probe stellen.
        cache_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        assert json.loads(cache_path.read_text(encoding="utf-8").strip())["by_index"] == {
            "0": {"sentence": "a", "sentence_de": "a-de"},
            "1": {"sentence": "b", "sentence_de": "b-de"},
        }, "Testvoraussetzung: JSON macht aus den int-Keys String-Keys"

        payload = builder.build_sentences(self._tiny_goldset(), "sonnet", cache_path=cache_path)

        assert [s["sentence"] for s in payload["sentences"]] == ["a", "b"]
        assert [s["sentence_de"] for s in payload["sentences"]] == ["a-de", "b-de"]
        assert [s["chunk_index"] for s in payload["sentences"]] == [0, 1]

    def test_cache_survives_a_second_load_after_being_read_once(self, tmp_path):
        """Der Ruecktausch darf den Cache selbst nicht veraendern (kein Re-Dump noetig)."""
        record = {
            "doc_id": "doc-a",
            "by_index": {0: {"sentence": "a", "sentence_de": "a-de"}},
            "duration_ms": 1.0,
            "attempts": 1,
            "session_id": "sess-1",
            "total_cost_usd": 0.0,
            "usage": {},
        }
        cache_path = tmp_path / "sentences.partial.jsonl"
        cache_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

        goldset = self._tiny_goldset()
        goldset["chunks"] = goldset["chunks"][:1]
        builder.build_sentences(goldset, "sonnet", cache_path=cache_path)
        # Zweiter Aufruf mit derselben (unveraenderten) Cache-Datei muss
        # ebenso funktionieren -- kein einmaliger Seiteneffekt, der den
        # zweiten Lauf wieder auf int-Keys angewiesen macht.
        payload_again = builder.build_sentences(goldset, "sonnet", cache_path=cache_path)
        assert payload_again["sentences"][0]["sentence"] == "a"
