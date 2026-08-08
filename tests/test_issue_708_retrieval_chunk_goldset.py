"""Chunk-Goldset fuer Retrieval, hermetisch pruefbar (Issue #708).

Deckt die sechs Akzeptanzkriterien aus #708 ab. Der Schwerpunkt liegt auf drei
Eigenschaften, die ein Goldset erst belastbar machen:

* **Vertragstreue** — die Fixture-Chunks sind ueber ``chunk_pages()`` mit
  Kontextsatz entstanden und werden mit ``passage: `` eingebettet, also genau so
  wie im Betrieb. Geprueft wird das strukturell (jeder ``embedding_text`` ist
  exakt ``default_context_sentence(...) + " " + chunk_text``) und, unter
  ``VAULT_E5_LIVE_TEST=1``, durch ein erneutes Chunking der Quelltexte.
* **Hermetik** — der Lauf zieht weder Modell noch Tokenizer noch Netz. Ein Test
  fuehrt ihn mit hart blockiertem Socket und blockierten Ladepfaden aus; eine
  Gegenprobe belegt, dass derselbe Guard einen echten Ladeversuch stoppt.
* **Wirksamkeit der Schwelle** — ein Lauf mit absichtlich verschlechterter
  Rangfolge muss rot werden und die unterschrittene Metrik benennen.
"""

import base64
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml
from scripts.eval import run_retrieval_chunk_goldset as runner

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDSET_DIR = REPO_ROOT / "tests" / "fixtures" / "retrieval_goldset_chunks_708"
DOC_PATH = REPO_ROOT / "docs" / "evals" / "retrieval-chunk-goldset-708.md"
EVALS_README = REPO_ROOT / "docs" / "evals" / "README.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def goldset():
    return runner.load_goldset()


@pytest.fixture(scope="module")
def vectors():
    return runner.load_vectors()


@pytest.fixture(scope="module")
def thresholds():
    return runner.load_thresholds()


@pytest.fixture(scope="module")
def report(goldset, vectors):
    return runner.evaluate(goldset, vectors, k=runner.DEFAULT_K)


# ---------------------------------------------------------------------------
# AC1: Chunks haben denselben Weg genommen wie im Betrieb
# ---------------------------------------------------------------------------
class TestChunkContract:
    def test_fixture_files_exist(self):
        for name in ("sources.json", "goldset.json", "vectors.json", "thresholds.json"):
            assert (GOLDSET_DIR / name).is_file(), f"Fixture fehlt: {name}"

    def test_embedding_text_matches_chunk_pages_contract(self, goldset):
        """embedding_text == default_context_sentence(...) + " " + chunk_text."""
        from academic_vault.chunking import default_context_sentence
        from academic_vault.embeddings import build_contextual_embedding_text

        assert goldset["chunks"], "Goldset enthaelt keine Chunks"
        for chunk in goldset["chunks"]:
            expected_context = default_context_sentence(
                chunk["section_title"],
                chunk["chunk_index"],
                chunk["page_start"],
                chunk["page_end"],
            )
            assert chunk["context_sentence"] == expected_context, chunk["chunk_id"]
            assert chunk["embedding_text"] == build_contextual_embedding_text(
                chunk["context_sentence"], chunk["chunk_text"]
            ), chunk["chunk_id"]

    def test_manifest_records_passage_prefix_and_model(self, goldset, vectors):
        """Fixture-Manifest ist eine Momentaufnahme (#708), keine Live-Ableitung.

        Verglichen wird gegen den Kandidaten, mit dem die eingecheckten
        Vektoren TATSAECHLICH erzeugt wurden -- nicht gegen den heutigen
        ``DEFAULT_MODEL_ID``. Der wechselte mit #732 auf ``BAAI/bge-m3``; das
        macht dieses Manifest nicht falsch, nur historisch (siehe Kopf von
        ``docs/evals/retrieval-chunk-goldset-708.md``: "Historisches Dokument").
        Eine Kopplung an die Live-Konstante wuerde bei jedem kuenftigen
        Modellwechsel erneut brechen, ohne dass die Fixture selbst veraltet
        waere.
        """
        from academic_vault.embedding_model import PASSAGE_PREFIX

        meta = goldset["meta"]
        assert meta["model_id"] == "intfloat/multilingual-e5-small"
        assert meta["passage_prefix"] == PASSAGE_PREFIX
        assert meta["query_prefix"] == "query: "
        assert meta["dim"] == 384
        assert all(len(vec) == 384 for vec in vectors.values())

    def test_chunk_pages_and_indices_are_monotone(self, goldset):
        by_doc: dict[str, list[dict]] = {}
        for chunk in goldset["chunks"]:
            by_doc.setdefault(chunk["doc_id"], []).append(chunk)
        for doc_id, chunks in by_doc.items():
            indices = [c["chunk_index"] for c in chunks]
            assert indices == sorted(indices) == list(range(len(chunks))), doc_id
            starts = [c["page_start"] for c in chunks]
            assert starts == sorted(starts), doc_id
            for chunk in chunks:
                assert chunk["page_end"] >= chunk["page_start"], chunk["chunk_id"]

    def test_corpus_is_large_enough_to_rank(self, goldset):
        """Weniger Chunks als 3x k, und Recall@10 misst nur noch die Korpusgroesse."""
        assert len(goldset["chunks"]) >= 3 * runner.DEFAULT_K
        assert len(goldset["queries"]) > 8, "mehr Queries als das Set aus #628 (AC: >8)"

    def test_manifest_hash_covers_embedding_texts(self, goldset):
        """Fixture-Drift-Schutz: Text geaendert, Vektoren alt -> Hash bricht."""
        recomputed = runner.compute_manifest_sha256(
            [c["embedding_text"] for c in goldset["chunks"]],
            [q["query"] for q in goldset["queries"]],
            goldset["meta"]["model_id"],
            goldset["meta"]["dim"],
        )
        assert recomputed == goldset["meta"]["manifest_sha256"], (
            "Goldset und Vektoren passen nicht mehr zusammen — neu erzeugen mit "
            "VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_retrieval_chunk_goldset.py"
        )

    def test_every_query_has_at_least_one_relevant_chunk(self, goldset):
        known = {c["chunk_id"] for c in goldset["chunks"]}
        for query in goldset["queries"]:
            assert query["relevant_chunk_ids"], query["query_id"]
            assert set(query["relevant_chunk_ids"]) <= known, query["query_id"]

    def test_live_rechunk_matches_fixture(self):
        """Harter Identitaetsbeweis mit echtem Tokenizer (nur mit Live-Gate).

        Hermetisch laeuft ``chunk_pages`` auf ``approximate_token_count`` und
        setzt die Grenzen anders — die Fixture ist deshalb eingecheckte Datenlage,
        nicht hermetisch reproduzierbar. Dieser Test schliesst die Luecke, wenn
        der echte Tokenizer verfuegbar ist.
        """
        import os

        if os.environ.get("VAULT_E5_LIVE_TEST") != "1":
            pytest.skip("Live-Test: VAULT_E5_LIVE_TEST=1 setzen (laedt den e5-Tokenizer)")

        builder = pytest.importorskip("scripts.eval.build_retrieval_chunk_goldset")
        fixture = runner.load_goldset()
        rebuilt = builder.build_chunks(builder.load_sources())
        assert [c["chunk_id"] for c in rebuilt] == [c["chunk_id"] for c in fixture["chunks"]]
        for new, old in zip(rebuilt, fixture["chunks"], strict=True):
            assert new == old, new["chunk_id"]


# ---------------------------------------------------------------------------
# AC3: Lauf ohne Netz und ohne Modell-Download
# ---------------------------------------------------------------------------
class TestHermeticRun:
    def test_goldset_run_is_hermetic(self, goldset, vectors, monkeypatch):
        """Vollstaendiger Lauf mit blockiertem Socket und blockierten Ladepfaden."""
        import socket

        import academic_vault.chunking as chunking
        import academic_vault.embedding_model as embedding_model

        def _no_network(*_args, **_kwargs):
            raise AssertionError("Der Goldset-Lauf hat eine Netzwerkverbindung versucht")

        monkeypatch.setattr(socket, "socket", _no_network)
        monkeypatch.setattr(socket, "create_connection", _no_network)
        monkeypatch.setattr(embedding_model, "_load_backend_model", _no_network)
        monkeypatch.setattr(chunking, "_load_tokenizer", _no_network)

        result = runner.evaluate(goldset, vectors, k=runner.DEFAULT_K)

        assert result["overall"]["recall_at_10"] > 0.0
        assert result["overall"]["ndcg_at_10"] > 0.0
        assert result["overall"]["mrr"] > 0.0
        assert result["chunk_count"] == len(goldset["chunks"])

    def test_blocked_backend_guard_actually_bites(self, monkeypatch):
        """Gegenprobe: derselbe Guard stoppt einen echten Ladeversuch."""
        import academic_vault.embedding_model as embedding_model

        def _no_network(*_args, **_kwargs):
            raise AssertionError("blockiert")

        monkeypatch.setattr(embedding_model, "_load_backend_model", _no_network)
        with pytest.raises(AssertionError):
            embedding_model.E5SmallEmbedder().load()

    def test_playback_embedder_refuses_unknown_text(self, goldset, vectors):
        """Ein Text ohne hinterlegten Vektor darf NICHT still zu einem Nullvektor werden."""
        embedder = runner.PlaybackEmbedder(vectors, goldset["meta"])
        with pytest.raises(KeyError):
            embedder.embed_documents(["ein Text, der nie eingebettet wurde"])

    def test_both_knn_paths_rank_identically(self, goldset, vectors, report):
        """Schwellen sind nur dann plattformunabhaengig, wenn beide KNN-Pfade gleich ranken.

        ``knn_chunks`` nutzt die vec0-Virtual-Table, wo die sqlite-vec-Extension
        ladbar ist, und sonst eine Python-Schleife ueber die BLOBs. Waeren die
        Reihenfolgen verschieden, waere die in der CI gemessene Metrik eine
        andere als die lokal gemessene — und die Schwellen aus dem Referenzlauf
        waeren wertlos.
        """
        from academic_vault.db import VaultDB

        with mock.patch.object(VaultDB, "load_vec_extension", return_value=False):
            fallback = runner.evaluate(goldset, vectors, k=runner.DEFAULT_K)

        assert [r["retrieved"] for r in fallback["per_query"]] == [
            r["retrieved"] for r in report["per_query"]
        ]
        assert fallback["overall"] == report["overall"]


# ---------------------------------------------------------------------------
# AC5: Sprachluecke
# ---------------------------------------------------------------------------
class TestLanguageGap:
    @staticmethod
    def _content_words(text: str) -> set[str]:
        return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= 5}

    def test_language_gap_pair_exists_and_is_measured(self, goldset, report):
        gap = [q for q in goldset["queries"] if q["case"] == "language-gap"]
        assert gap, "kein language-gap-Query im Goldset"

        chunk_lang = {c["chunk_id"]: c["lang"] for c in goldset["chunks"]}
        chunk_text = {c["chunk_id"]: c["chunk_text"] for c in goldset["chunks"]}
        for query in gap:
            assert query["lang"] == "de", query["query_id"]
            targets = query["relevant_chunk_ids"]
            assert all(chunk_lang[cid] == "en" for cid in targets), query["query_id"]
            overlap = set()
            for cid in targets:
                overlap |= self._content_words(query["query"]) & self._content_words(
                    chunk_text[cid]
                )
            assert not overlap, (
                f"{query['query_id']} teilt Fachwoerter mit dem Zielchunk ({sorted(overlap)}) — "
                "dann misst der Fall lexikalische Ueberlappung statt der Sprachluecke"
            )

        measured = {row["query_id"] for row in report["per_query"] if row["case"] == "language-gap"}
        assert measured == {q["query_id"] for q in gap}

    def test_language_gap_subset_has_own_threshold(self, thresholds, report):
        assert "language-gap" in thresholds["subsets"]
        assert "language-gap" in report["subsets"]
        for metric in ("recall_at_10", "ndcg_at_10", "mrr"):
            assert metric in thresholds["subsets"]["language-gap"]
            assert metric in report["subsets"]["language-gap"]


# ---------------------------------------------------------------------------
# AC4: CI-Job und Schwellenwirkung
# ---------------------------------------------------------------------------
class TestThresholdGate:
    def test_current_fixture_meets_thresholds(self, report, thresholds):
        assert runner.check_thresholds(report, thresholds) == []

    def test_runner_exits_zero_on_current_fixture(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_retrieval_chunk_goldset.py"),
                "--check-thresholds",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["overall"]["ndcg_at_10"] > 0.0

    def test_runner_exits_nonzero_below_threshold(self, tmp_path, goldset, vectors):
        """Query-Vektoren rotiert -> jede Query zieht die Antwort einer anderen."""
        raw = json.loads((GOLDSET_DIR / "vectors.json").read_text(encoding="utf-8"))
        query_ids = [q["query_id"] for q in goldset["queries"]]
        rotated = {
            qid: raw["queries"][query_ids[(i + 1) % len(query_ids)]]
            for i, qid in enumerate(query_ids)
        }
        raw["queries"] = rotated
        broken = tmp_path / "vectors-rotated.json"
        broken.write_text(json.dumps(raw), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_retrieval_chunk_goldset.py"),
                "--check-thresholds",
                "--vectors",
                str(broken),
                "--skip-manifest-check",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode != 0
        assert "ndcg_at_10" in proc.stderr or "recall_at_10" in proc.stderr or "mrr" in proc.stderr

    def test_manifest_mismatch_is_fatal(self, tmp_path):
        """Ein manipuliertes Goldset ohne passende Vektoren bricht den Lauf ab."""
        data = json.loads((GOLDSET_DIR / "goldset.json").read_text(encoding="utf-8"))
        data["chunks"][0]["embedding_text"] += " nachtraeglich angehaengt"
        tampered = tmp_path / "goldset-tampered.json"
        tampered.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_retrieval_chunk_goldset.py"),
                "--goldset",
                str(tampered),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode != 0
        assert "manifest" in proc.stderr.lower()

    def test_thresholds_stay_below_measured_values(self, report, thresholds):
        """Schwellen sind Messwert minus Marge — nie darueber, nie beliebig tief."""
        for scope, measured in [("overall", report["overall"])] + [
            (f"subsets.{name}", values) for name, values in report["subsets"].items()
        ]:
            configured = (
                thresholds["overall"]
                if scope == "overall"
                else thresholds["subsets"].get(scope.split(".", 1)[1])
            )
            if configured is None:
                continue
            for metric, limit in configured.items():
                assert limit <= measured[metric] + 1e-9, f"{scope}.{metric} ueber dem Messwert"
                assert limit >= measured[metric] - 0.15, (
                    f"{scope}.{metric}: Schwelle {limit} liegt mehr als 0.15 unter dem "
                    f"Messwert {measured[metric]} und wuerde eine Regression durchlassen"
                )


class TestCiWiring:
    def test_ci_workflow_runs_retrieval_goldset(self):
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        # PyYAML liest das YAML-Schluesselwort `on` als True (YAML-1.1-Bool).
        triggers = workflow.get("on", workflow.get(True))
        assert "pull_request" in triggers

        job = workflow["jobs"].get("retrieval-goldset")
        assert job is not None, "CI-Job 'retrieval-goldset' fehlt"
        commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
        assert "run_retrieval_chunk_goldset.py" in commands
        assert "--check-thresholds" in commands
        env = {**workflow.get("env", {}), **job.get("env", {})}
        assert env.get("HF_HUB_OFFLINE") == "1"
        assert env.get("TRANSFORMERS_OFFLINE") == "1"


# ---------------------------------------------------------------------------
# AC6: Doku
# ---------------------------------------------------------------------------
class TestDocumentation:
    def test_goldset_doc_is_complete(self):
        assert DOC_PATH.is_file(), f"Report fehlt: {DOC_PATH}"
        text = DOC_PATH.read_text(encoding="utf-8")
        for heading in (
            "## Aufbau des Sets",
            "## Wie die Schwellen zustande kamen",
            "## Vektoren nach einem Modellwechsel neu erzeugen",
            "## Grenzen",
        ):
            assert heading in text, f"Abschnitt fehlt: {heading}"
        assert "VAULT_E5_LIVE_TEST=1" in text
        assert "scripts/eval/build_retrieval_chunk_goldset.py" in text

    def test_doc_is_linked_from_evals_readme(self):
        assert "retrieval-chunk-goldset-708.md" in EVALS_README.read_text(encoding="utf-8")


class TestVectorEncoding:
    def test_vectors_are_base64_float32(self, goldset):
        raw = json.loads((GOLDSET_DIR / "vectors.json").read_text(encoding="utf-8"))
        sample_id = goldset["chunks"][0]["chunk_id"]
        blob = base64.b64decode(raw["chunks"][sample_id])
        assert len(blob) == 384 * 4
        decoded = list(struct.unpack("<384f", blob))
        norm = sum(v * v for v in decoded) ** 0.5
        assert norm == pytest.approx(1.0, abs=1e-4), "Vektoren sind nicht L2-normalisiert"
