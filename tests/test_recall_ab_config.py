"""Hermetische Konfigurations-/Struktur-Tests fuer das A/B-Skript (Issue #628).

``scripts/eval/recall_at_k_model_ab.py`` bleibt bewusst ausserhalb der
pytest-Discovery (nicht in ``tests/``), damit ``uv run pytest tests/`` nie
echte HuggingFace-Downloads ausloest (AC5). Dieses Modul prueft daher nur die
*Konfiguration* des Skripts (``MODEL_CONFIGS``, ``GOLDSET_PATHS``) sowie die
Recall-Logik von ``run_model_ab`` mit einem via ``monkeypatch`` gestubbten
``SentenceTransformer`` -- keine echten Modellgewichte, kein Netzwerk.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

# REPO_ROOT liegt bereits ueber tests/conftest.py auf sys.path; scripts/eval/
# ist seit #628 ein regulaeres Package (scripts/eval/__init__.py), daher kein
# zusaetzliches sys.path.insert noetig (vgl. test_no_duplicated_repo_root_
# sys_path_boilerplate in test_issue_183_conftest_fixtures.py).
from scripts.eval import recall_at_k_model_ab as ab_module

# ---------------------------------------------------------------------------
# AC3 (Teil 1): Skript kennt BAAI/bge-m3 und intfloat/multilingual-e5-large.
# ---------------------------------------------------------------------------


class TestModelConfigsRegistered:
    def test_bge_m3_registered(self):
        assert "bge-m3" in ab_module.MODEL_CONFIGS
        cfg = ab_module.MODEL_CONFIGS["bge-m3"]
        assert cfg.model_id == "BAAI/bge-m3"

    def test_bge_m3_uses_no_prefix(self):
        """BGE-M3-Modellkarte: kein Instruktions-Praefix mehr noetig."""
        cfg = ab_module.MODEL_CONFIGS["bge-m3"]
        assert cfg.query_prefix == ""
        assert cfg.passage_prefix == ""
        assert cfg.query_prompt_name is None

    def test_e5_large_registered(self):
        assert "e5-large" in ab_module.MODEL_CONFIGS
        cfg = ab_module.MODEL_CONFIGS["e5-large"]
        assert cfg.model_id == "intfloat/multilingual-e5-large"

    def test_e5_large_uses_query_passage_prefix_schema(self):
        """e5-large-Modellkarte: 'query: '/'passage: '-Praefixe wie e5-small."""
        cfg = ab_module.MODEL_CONFIGS["e5-large"]
        assert cfg.query_prefix == "query: "
        assert cfg.passage_prefix == "passage: "

    def test_all_five_candidates_present(self):
        assert set(ab_module.MODEL_CONFIGS) == {
            "e5-small",
            "minilm",
            "qwen3-embedding-0.6b",
            "bge-m3",
            "e5-large",
        }


# ---------------------------------------------------------------------------
# AC3 (Teil 2) + AC5: --goldset-Parametrisierung, kein echter Modell-Zugriff.
# ---------------------------------------------------------------------------


class TestGoldsetParametrization:
    def test_goldset_paths_has_default_and_hard(self):
        assert set(ab_module.GOLDSET_PATHS) == {"default", "hard"}

    def test_default_goldset_path_unchanged(self):
        assert ab_module.GOLDSET_PATHS["default"] == ab_module.GOLDSET_PATH

    def test_hard_goldset_path_points_to_628_fixture(self):
        assert ab_module.GOLDSET_PATHS["hard"].name == ("retrieval_goldset_hard_overlap_628.json")
        assert ab_module.GOLDSET_PATHS["hard"].is_file()

    def test_load_goldset_defaults_to_de_en_set(self):
        data = ab_module._load_goldset()
        assert "clusters" in data  # Signatur-Feld des #375-Sets

    def test_load_goldset_hard_returns_topics_field(self):
        data = ab_module._load_goldset(ab_module.GOLDSET_PATHS["hard"])
        assert "topics" in data  # Signatur-Feld des #628-Sets


# ---------------------------------------------------------------------------
# AC3 (Teil 3): run_model_ab() liefert Per-Query-Aufschluesselung -- mit
# gestubbtem SentenceTransformer (kein echter Download/Modellaufruf).
# ---------------------------------------------------------------------------


class _FakeSentenceTransformer:
    """Deterministischer Fake: bildet Text-Praefix auf einen Basisvektor ab.

    Keine echten Gewichte, kein Netzwerk -- rein string-basiertes Hashing in
    einen 8-dimensionalen Vektorraum, ausreichend um encode()-Aufrufe des
    Skripts hermetisch zu pruefen.
    """

    def __init__(self, model_id: str, **kwargs) -> None:
        self.model_id = model_id
        self.init_kwargs = kwargs

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False, **kwargs):
        vectors = []
        for text in texts:
            rng = np.random.default_rng(abs(hash(text)) % (2**32))
            vectors.append(rng.random(8))
        return np.asarray(vectors)


class TestRunModelAbPerQueryBreakdown:
    def test_run_model_ab_returns_one_row_per_query(self, monkeypatch):
        """``run_model_ab`` importiert ``SentenceTransformer`` lokal bei jedem
        Aufruf (``from sentence_transformers import SentenceTransformer``) --
        gestubbt wird deshalb ueber ``sys.modules``, nicht ueber ein
        Modul-Attribut von ``ab_module`` (das es so nicht gibt)."""
        fake_module = type(sys)("sentence_transformers")
        fake_module.SentenceTransformer = _FakeSentenceTransformer
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

        data = {
            "papers": [
                {"paper_id": "p1", "title": "Title One", "abstract": "Abstract one."},
                {"paper_id": "p2", "title": "Title Two", "abstract": "Abstract two."},
                {"paper_id": "p3", "title": "Title Three", "abstract": "Abstract three."},
            ],
            "queries": [
                {"query_id": "q1", "lang": "en", "query": "one", "relevant_paper_ids": ["p1"]},
                {"query_id": "q2", "lang": "de", "query": "two", "relevant_paper_ids": ["p2"]},
            ],
        }
        cfg = ab_module.MODEL_CONFIGS["e5-small"]

        result = ab_module.run_model_ab(cfg, data, k=10)

        assert result["model"] == "e5-small"
        assert len(result["per_query"]) == len(data["queries"])
        returned_ids = {row["query_id"] for row in result["per_query"]}
        assert returned_ids == {"q1", "q2"}
        for row in result["per_query"]:
            assert 0.0 <= row["recall_at_k"] <= 1.0
        assert 0.0 <= result["mean_recall"] <= 1.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
