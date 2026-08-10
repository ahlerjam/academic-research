"""HyDE und Multi-Query prototypisch gemessen (Issue #733).

Der Lauf misst zwei Query-Umformungen gegen das unveraenderte Chunk-Goldset aus
#708. Drei Eigenschaften machen die Messung ueberhaupt erst belastbar, und genau
die pruefen diese Tests:

* **Derselbe Suchpfad** — der Baseline-Arm muss die #708-Zahlen exakt
  reproduzieren. Weicht er ab, misst der neue Pfad etwas anderes und jeder
  gemeldete Gewinn waere ein Artefakt.
* **Keine Leckage** — die Umformungen sind entstanden, ohne dass das Modell
  Goldset, Anker oder Zieltext gesehen hat. Geprueft an den eingecheckten
  Texten, nicht an einer Zusicherung im Prompt.
* **Nichts Verstecktes** — negative Deltas stehen woertlich im Report, und die
  Empfehlung folgt den gemessenen Zahlen statt einer Vorliebe.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.eval import query_expansion_prototypes as proto

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "hyde_multiquery_733"
TRANSFORMS_PATH = FIXTURE_DIR / "transforms.json"
VECTORS_PATH = FIXTURE_DIR / "vectors.json"
DOC_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-07-hyde-multiquery-733.md"
RESULTS_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-07-hyde-multiquery-733-live-results.json"
EVALS_README = REPO_ROOT / "docs" / "evals" / "README.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "eval" / "build_hyde_multiquery_fixture.py"


def _transforms_cover_current_goldset() -> bool:
    """``False``, wenn ``transforms.json`` nicht jede Query des aktuellen
    #708-Goldsets kennt (z. B. nach einer Verbreiterung wie #800)."""
    try:
        from scripts.eval import run_hyde_multiquery_eval as hm
        from scripts.eval import run_retrieval_chunk_goldset as base

        goldset_ids = {q["query_id"] for q in base.load_goldset()["queries"]}
        transform_ids = {t["query_id"] for t in hm.load_transforms()["transforms"]}
    except FileNotFoundError:
        return False
    return goldset_ids <= transform_ids


#: #800 hat das #708-Goldset von 26 auf 60 Queries verbreitert; die
#: Umform-Fixture kennt nur die alten 26 Query-IDs. Der Rebuild braucht
#: ``VAULT_HYDE_LIVE_TRANSFORM=1`` (echte ``claude``-CLI-Aufrufe, ~120 Stueck
#: fuer HyDE+Multi-Query ueber alle 60 Queries) und ist bewusst NICHT Teil
#: von #800 -- siehe docs/evals/2026-08-10-chunk-goldset-widening-800.md,
#: Abschnitt "Abhaengige Gatter". Nachgeholt in #808.
STALE_TRANSFORMS_REASON = (
    "transforms.json deckt nicht alle Queries des aktuellen #708-Goldsets ab "
    "(#800 hat 26 -> 60 Queries verbreitert) -- Rebuild braucht "
    "VAULT_HYDE_LIVE_TRANSFORM=1 (echte claude-CLI-Aufrufe), siehe #808."
)
TRANSFORMS_COVER_GOLDSET = _transforms_cover_current_goldset()


# ---------------------------------------------------------------------------
# Prototyp-Bausteine: Fusion und Prompts
# ---------------------------------------------------------------------------
class TestReciprocalRankFusion:
    """``fuse_rankings`` ist von Hand nachgerechnet, nicht nur ausprobiert."""

    def test_single_ranking_is_returned_unchanged(self):
        assert proto.fuse_rankings([["a", "b", "c"]], k=60) == ["a", "b", "c"]

    def test_agreement_of_two_lists_beats_a_single_first_place(self):
        """b: 1/62 + 1/61 = 0,032522 > a: 1/61 + 1/63 = 0,032266 > c: 1/63 + 1/62 = 0,032002."""
        fused = proto.fuse_rankings([["a", "b", "c"], ["b", "c", "a"]], k=60)
        assert fused[0] == "b"
        assert fused == ["b", "a", "c"]

    def test_scores_match_hand_computed_rrf(self):
        scored = proto.fuse_rankings_with_scores([["a", "b"], ["b", "a"]], k=60)
        assert scored == [
            ("a", pytest.approx(1 / 61 + 1 / 62)),
            ("b", pytest.approx(1 / 61 + 1 / 62)),
        ]

    def test_document_missing_from_one_list_scores_only_where_it_appears(self):
        """x steht nur in Liste 2 auf Rang 1: 1/61 gegen y mit 1/62 + 1/62."""
        fused = proto.fuse_rankings_with_scores([["y"], ["x", "y"]], k=60)
        assert dict(fused)["x"] == pytest.approx(1 / 61)
        assert dict(fused)["y"] == pytest.approx(1 / 61 + 1 / 62)

    def test_ties_break_deterministically_by_first_appearance(self):
        """Gleicher Score darf nicht von der Mengen-Iterationsreihenfolge abhaengen."""
        first = proto.fuse_rankings([["a", "b"], ["b", "a"]], k=60)
        assert first == ["a", "b"]
        assert proto.fuse_rankings([["b", "a"], ["a", "b"]], k=60) == ["b", "a"]

    def test_empty_input_yields_empty_result(self):
        assert proto.fuse_rankings([], k=60) == []
        assert proto.fuse_rankings([[], []], k=60) == []

    def test_k_constant_changes_the_weighting(self):
        """Kleines k gewichtet vordere Raenge staerker — sonst waere der Parameter Zierde."""
        rankings = [["a", "b", "c", "d"], ["d", "c", "b", "a"]]
        assert proto.fuse_rankings(rankings, k=0)[0] == "a"
        assert proto.fuse_rankings_with_scores(rankings, k=0)[0][1] == pytest.approx(1 / 1 + 1 / 4)


class TestPrompts:
    def test_hyde_prompt_contains_only_the_query(self, transforms):
        prompt = proto.hyde_passage_prompt("wie misst man DevOps-Erfolg")
        assert "wie misst man DevOps-Erfolg" in prompt
        assert proto.HYDE_PROMPT_ID == transforms["meta"]["hyde_prompt_id"]

    def test_multi_query_prompt_states_the_variant_count(self):
        prompt = proto.multi_query_prompt("wie misst man DevOps-Erfolg", n=3)
        assert "3" in prompt
        assert "wie misst man DevOps-Erfolg" in prompt

    def test_prompt_ids_change_when_the_template_changes(self):
        """Prompt-ID ist ein Hash ueber die Vorlage, keine handgepflegte Zahl."""
        assert proto.HYDE_PROMPT_ID.startswith("hyde-")
        assert proto.MULTI_QUERY_PROMPT_ID.startswith("mq-")
        assert proto.HYDE_PROMPT_ID == proto.prompt_id("hyde", proto.HYDE_PROMPT_TEMPLATE)


# ---------------------------------------------------------------------------
# Fixture: Umformungen und ihre Vektoren
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def goldset():
    from scripts.eval import run_retrieval_chunk_goldset as base

    return base.load_goldset()


@pytest.fixture(scope="module")
def transforms():
    from scripts.eval import run_hyde_multiquery_eval as hm

    return hm.load_transforms()


@pytest.fixture(scope="module")
def report(goldset, transforms):
    from scripts.eval import run_hyde_multiquery_eval as hm
    from scripts.eval import run_retrieval_chunk_goldset as base

    return hm.evaluate_all_arms(
        goldset=goldset,
        goldset_vectors=base.load_vectors(),
        transforms=transforms,
        transform_vectors=hm.load_transform_vectors(),
    )


@pytest.fixture(scope="module")
def results_json():
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


class TestTransformFixture:
    pytestmark = pytest.mark.skipif(not TRANSFORMS_COVER_GOLDSET, reason=STALE_TRANSFORMS_REASON)

    def test_every_goldset_query_has_both_transforms(self, goldset, transforms):
        by_id = {t["query_id"]: t for t in transforms["transforms"]}
        assert set(by_id) == {q["query_id"] for q in goldset["queries"]}
        for query in goldset["queries"]:
            entry = by_id[query["query_id"]]
            assert entry["query"] == query["query"], query["query_id"]
            assert entry["hyde_text"].strip(), query["query_id"]
            assert len(entry["mq_variants"]) >= 2, query["query_id"]
            assert all(v.strip() for v in entry["mq_variants"]), query["query_id"]

    def test_transforms_carry_no_goldset_leakage(self, goldset, transforms):
        """Kein Anker und kein Zielchunk-Wortlaut steht in den Umformungen.

        Das Modell hat beim Umformen ausschliesslich den Query-Text gesehen.
        Stuende ein Anker woertlich in der HyDE-Passage, waere der Gewinn kein
        Verfahrensgewinn, sondern durchgereichte Loesung.
        """
        anchors = [a for q in goldset["queries"] for a in q.get("anchors", [])]
        assert anchors, "Goldset fuehrt keine Anker — der Leakage-Test misst dann nichts"
        for entry in transforms["transforms"]:
            haystack = " ".join([entry["hyde_text"], *entry["mq_variants"]]).lower()
            for anchor in anchors:
                needle = " ".join(anchor.lower().split())
                assert needle not in haystack, f"{entry['query_id']} enthaelt Anker {anchor!r}"

    def test_manifest_hash_covers_every_transform_text(self, transforms):
        from scripts.eval import run_hyde_multiquery_eval as hm

        recomputed = hm.compute_transform_manifest(transforms)
        assert recomputed == transforms["meta"]["manifest_sha256"]

    def test_transform_latency_provenance_is_documented(self, transforms):
        """Messmethode, Modell, Stichprobengroesse und Perzentile stehen in der Fixture."""
        meta = transforms["meta"]
        for arm in ("hyde", "multi_query"):
            latency = meta["transform_latency_ms"][arm]
            assert latency["n"] >= 26
            assert 0.0 < latency["p50"] <= latency["p95"]
            assert latency["method"], arm
        assert meta["transform_model"]
        assert meta["embedding_latency_ms"]["n"] > 0
        assert meta["embedding_latency_ms"]["p50"] > 0.0

    def test_build_script_needs_no_api_key(self):
        """Kein Plugin-Pfad darf einen ANTHROPIC_API_KEY brauchen (#632)."""
        text = BUILD_SCRIPT.read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" not in text
        assert "VAULT_E5_LIVE_TEST" in text

    def test_transform_vectors_cover_all_texts(self, transforms):
        from scripts.eval import run_hyde_multiquery_eval as hm

        vectors = hm.load_transform_vectors()
        for entry in transforms["transforms"]:
            qid = entry["query_id"]
            assert len(vectors[f"{qid}::hyde::query"]) == 384
            assert len(vectors[f"{qid}::hyde::passage"]) == 384
            for idx in range(len(entry["mq_variants"])):
                assert len(vectors[f"{qid}::mq::{idx}"]) == 384

    def test_drifted_transform_text_is_fatal(self, tmp_path):
        """Text geaendert, Vektor alt: Exit 2 statt stiller Metrikverschiebung."""
        data = json.loads(TRANSFORMS_PATH.read_text(encoding="utf-8"))
        data["transforms"][0]["hyde_text"] += " nachtraeglich angehaengt"
        tampered = tmp_path / "transforms-tampered.json"
        tampered.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_hyde_multiquery_eval.py"),
                "--transforms",
                str(tampered),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode == 2, proc.stdout[-2000:]
        assert "manifest" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# AC1/AC2: beide Verfahren gemessen, Metriken je Arm
# ---------------------------------------------------------------------------
class TestArms:
    pytestmark = pytest.mark.skipif(not TRANSFORMS_COVER_GOLDSET, reason=STALE_TRANSFORMS_REASON)

    def test_both_arms_run_on_same_goldset(self, goldset, report):
        expected_ids = [q["query_id"] for q in goldset["queries"]]
        assert set(report["arms"]) == set(proto.ARMS)
        for arm in proto.ARMS:
            rows = report["arms"][arm]["per_query"]
            assert [r["query_id"] for r in rows] == expected_ids, arm
        assert report["manifest_sha256"] == goldset["meta"]["manifest_sha256"]

    def test_baseline_arm_reproduces_708_numbers(self, goldset, report):
        """Gleicher Suchpfad wie #708 — sonst misst der Vergleich nichts."""
        from scripts.eval import run_retrieval_chunk_goldset as base

        reference = base.evaluate(goldset, base.load_vectors(), k=base.DEFAULT_K)
        measured = report["arms"]["baseline"]
        for metric in base.METRICS:
            assert measured["overall"][metric] == pytest.approx(
                reference["overall"][metric], abs=1e-9
            ), metric
        assert [r["retrieved"] for r in measured["per_query"]] == [
            r["retrieved"] for r in reference["per_query"]
        ]

    def test_ndcg_and_mrr_present_for_all_three_arms(self, report):
        for arm in proto.ARMS:
            overall = report["arms"][arm]["overall"]
            for metric in ("ndcg_at_10", "mrr"):
                assert isinstance(overall[metric], float), (arm, metric)
                assert 0.0 <= overall[metric] <= 1.0, (arm, metric)

    def test_language_gap_subset_reported_per_arm(self, goldset, report):
        gap_ids = {q["query_id"] for q in goldset["queries"] if q["case"] == "language-gap"}
        assert len(gap_ids) == 14
        for arm in proto.ARMS:
            subset = report["arms"][arm]["subsets"]["language-gap"]
            rows = [r for r in report["arms"][arm]["per_query"] if r["query_id"] in gap_ids]
            assert len(rows) == 14, arm
            recomputed = sum(r["ndcg_at_10"] for r in rows) / 14
            assert subset["ndcg_at_10"] == pytest.approx(recomputed, abs=1e-9), arm
            assert subset != report["arms"][arm]["overall"], arm

    def test_deltas_present_with_sign(self, report):
        for arm in proto.ARMS:
            if arm == "baseline":
                continue
            deltas = report["arms"][arm]["deltas"]
            for scope in ("overall", "language-gap"):
                for metric in ("ndcg_at_10", "mrr"):
                    value = deltas[scope][metric]
                    assert isinstance(value, float), (arm, scope, metric)
                    baseline = (
                        report["arms"]["baseline"]["overall"][metric]
                        if scope == "overall"
                        else report["arms"]["baseline"]["subsets"][scope][metric]
                    )
                    measured = (
                        report["arms"][arm]["overall"][metric]
                        if scope == "overall"
                        else report["arms"][arm]["subsets"][scope][metric]
                    )
                    assert value == pytest.approx(measured - baseline, abs=1e-9)

    def test_latency_block_covers_transform_and_embedding(self, report):
        for arm in proto.ARMS:
            latency = report["latency"][arm]
            assert latency["total_ms"] == pytest.approx(
                latency["transform_ms"] + latency["embed_ms"] + latency["search_ms"], abs=1e-6
            ), arm
            assert latency["search_ms"] > 0.0, arm
        assert report["latency"]["baseline"]["transform_ms"] == 0.0
        for arm in proto.ARMS:
            if arm != "baseline":
                assert report["latency"][arm]["transform_ms"] > 0.0, arm

    def test_multi_query_uses_fusion_over_all_variants(self, goldset, report):
        """Der Multi-Query-Arm fusioniert mehr als eine Rangliste je Query."""
        rows = {r["query_id"]: r for r in report["arms"]["multi_query"]["per_query"]}
        for query in goldset["queries"]:
            assert rows[query["query_id"]]["fused_rankings"] >= 3, query["query_id"]


# ---------------------------------------------------------------------------
# AC5/AC6: Report deckt sich mit den Rohdaten
# ---------------------------------------------------------------------------
class TestReportAndRecommendation:
    pytestmark = pytest.mark.skipif(not TRANSFORMS_COVER_GOLDSET, reason=STALE_TRANSFORMS_REASON)

    def test_raw_results_match_a_fresh_run(self, report, results_json):
        """Die eingecheckten Rohdaten stammen aus genau diesem Code."""
        for arm in proto.ARMS:
            for scope in ("overall",):
                for metric in ("recall_at_10", "ndcg_at_10", "mrr"):
                    assert results_json["arms"][arm][scope][metric] == pytest.approx(
                        report["arms"][arm][scope][metric], abs=1e-9
                    ), (arm, metric)
            for case, values in report["arms"][arm]["subsets"].items():
                for metric, value in values.items():
                    assert results_json["arms"][arm]["subsets"][case][metric] == pytest.approx(
                        value, abs=1e-9
                    ), (arm, case, metric)

    def test_report_numbers_match_raw_results(self, results_json):
        """Jede Zahl der Report-Tabellen steht so in den Rohdaten."""
        text = DOC_PATH.read_text(encoding="utf-8")
        for arm in proto.ARMS:
            for scope in ("overall", "language-gap"):
                values = (
                    results_json["arms"][arm]["overall"]
                    if scope == "overall"
                    else results_json["arms"][arm]["subsets"][scope]
                )
                for metric in ("ndcg_at_10", "mrr"):
                    formatted = f"{values[metric]:.4f}".replace(".", ",")
                    assert formatted in text, (
                        f"{arm}/{scope}/{metric} ({formatted}) fehlt im Report"
                    )

    def test_doc_has_language_gap_table(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        assert "## Sprachlücke" in text
        assert "language-gap" in text

    def test_report_does_not_hide_negative_deltas(self, results_json):
        """Jedes negative Delta aus den Rohdaten steht woertlich im Report."""
        text = DOC_PATH.read_text(encoding="utf-8")
        checked = 0
        for arm in proto.ARMS:
            if arm == "baseline":
                continue
            for scope in ("overall", "language-gap"):
                for metric in ("ndcg_at_10", "mrr"):
                    delta = results_json["arms"][arm]["deltas"][scope][metric]
                    if delta >= 0:
                        continue
                    formatted = f"{delta:+.4f}".replace(".", ",")
                    assert formatted in text, f"negatives Delta {formatted} fehlt im Report"
                    checked += 1
        assert checked > 0, "kein negatives Delta gemessen — dieser Test prueft dann nichts"

    def test_recommendation_matches_measured_deltas(self, results_json):
        """Die Empfehlung folgt der im Report offengelegten Entscheidungsregel.

        Regel (Abschnitt „Entscheidungsregel" des Reports): empfohlen wird nur
        ein Verfahren, das in **keiner** Teilmenge Recall@10 verliert; unter den
        so uebrigbleibenden gewinnt das mit dem groessten Zugewinn bei
        ``language-gap`` nDCG@10. Bleibt keines uebrig, lautet die Empfehlung
        „keines". Der Test rechnet die Regel aus den Rohdaten nach — eine
        Empfehlung, die den Zahlen widerspricht, faellt hier auf.
        """
        text = DOC_PATH.read_text(encoding="utf-8")
        match = re.search(r"^## Empfehlung\n+\*\*(.+?)\*\*", text, re.MULTILINE)
        assert match, "Abschnitt '## Empfehlung' fehlt oder nennt kein fettes Verfahren"
        verdict = match.group(1)
        assert verdict in {"HyDE", "Multi-Query", "Keines der beiden Verfahren"}
        assert "## Entscheidungsregel" in text, "Der Report legt die Regel nicht offen"

        subsets = list(results_json["arms"]["baseline"]["subsets"])
        eligible = {
            arm: results_json["arms"][arm]["deltas"]["language-gap"]["ndcg_at_10"]
            for arm in proto.ARMS
            if arm != "baseline"
            and all(
                results_json["arms"][arm]["deltas"][case]["recall_at_10"] >= -1e-9
                for case in subsets
            )
        }
        if not eligible:
            assert verdict == "Keines der beiden Verfahren"
            return
        best = max(eligible, key=lambda arm: eligible[arm])
        expected = "HyDE" if best.startswith("hyde") else "Multi-Query"
        assert verdict == expected, (
            f"Bester zulaessiger Arm ist {best} ({expected}), der Report empfiehlt {verdict!r}"
        )

    def test_recommendation_cites_language_gap_number(self, results_json):
        """Die Begruendung zitiert die Sprachluecken-Zahl, statt sie zu behaupten."""
        text = DOC_PATH.read_text(encoding="utf-8")
        section = text.split("## Empfehlung", 1)[1]
        gap_numbers = {
            f"{results_json['arms'][arm]['subsets']['language-gap'][metric]:.4f}".replace(".", ",")
            for arm in proto.ARMS
            for metric in ("ndcg_at_10", "mrr")
        }
        assert any(number in section for number in gap_numbers), (
            "die Empfehlung nennt keine der gemessenen language-gap-Zahlen"
        )

    def test_doc_is_linked_from_evals_readme(self):
        assert "2026-08-07-hyde-multiquery-733.md" in EVALS_README.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Hermetik und CI
# ---------------------------------------------------------------------------
class TestHermeticRun:
    pytestmark = pytest.mark.skipif(not TRANSFORMS_COVER_GOLDSET, reason=STALE_TRANSFORMS_REASON)

    def test_run_is_hermetic(self, goldset, transforms, monkeypatch):
        import socket

        import academic_vault.chunking as chunking
        import academic_vault.embedding_model as embedding_model
        from scripts.eval import run_hyde_multiquery_eval as hm
        from scripts.eval import run_retrieval_chunk_goldset as base

        def _no_network(*_args, **_kwargs):
            raise AssertionError("Der Lauf hat eine Netzwerkverbindung versucht")

        monkeypatch.setattr(socket, "socket", _no_network)
        monkeypatch.setattr(socket, "create_connection", _no_network)
        monkeypatch.setattr(embedding_model, "_load_backend_model", _no_network)
        monkeypatch.setattr(chunking, "_load_tokenizer", _no_network)

        result = hm.evaluate_all_arms(
            goldset=goldset,
            goldset_vectors=base.load_vectors(),
            transforms=transforms,
            transform_vectors=hm.load_transform_vectors(),
        )
        assert result["arms"]["baseline"]["overall"]["ndcg_at_10"] > 0.0

    def test_blocked_backend_guard_actually_bites(self, monkeypatch):
        """Gegenprobe: derselbe Guard stoppt einen echten Ladeversuch."""
        import academic_vault.embedding_model as embedding_model

        def _no_network(*_args, **_kwargs):
            raise AssertionError("blockiert")

        monkeypatch.setattr(embedding_model, "_load_backend_model", _no_network)
        with pytest.raises(AssertionError):
            embedding_model.E5SmallEmbedder().load()

    def test_runner_exits_zero_and_prints_report(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_hyde_multiquery_eval.py"),
                "--check-against",
                str(RESULTS_PATH),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        payload = json.loads(proc.stdout)
        assert set(payload["arms"]) == set(proto.ARMS)

    def test_check_against_detects_a_stale_report(self, tmp_path):
        """Das CI-Gatter beisst: veraenderte Rohdaten -> Exit 1."""
        data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        data["arms"]["baseline"]["overall"]["ndcg_at_10"] += 0.1
        stale = tmp_path / "stale.json"
        stale.write_text(json.dumps(data), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "eval" / "run_hyde_multiquery_eval.py"),
                "--check-against",
                str(stale),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.returncode == 1
        assert "ndcg_at_10" in proc.stderr


class TestCiWiring:
    def test_ci_workflow_runs_the_new_eval(self):
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        job = workflow["jobs"]["retrieval-goldset"]
        commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
        assert "run_hyde_multiquery_eval.py" in commands
        assert "--check-against" in commands
