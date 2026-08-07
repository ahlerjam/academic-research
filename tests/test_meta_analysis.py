"""Tests for meta_analysis.py — DerSimonian-Laird Random-Effects Meta-Analysis.

TDD: Tests written before implementation.
Expected values pre-computed manually for 5-study example.
"""

from __future__ import annotations

import json
import math

import pytest

# Ensure scripts/ is importable
from meta_analysis import (
    MetaAnalysisResult,
    Study,
    _load_studies,
    build_forest_plot_mermaid,
    dersimonianlaird,
)

# ---------------------------------------------------------------------------
# Fixture: 5 Beispiel-Studien (yi, vi) aus Ticket-Prompt
# ---------------------------------------------------------------------------
STUDIES = [
    Study(name="Smith 2020", yi=0.50, vi=0.0625),
    Study(name="Jones 2021", yi=0.30, vi=0.0900),
    Study(name="Chen 2019", yi=0.70, vi=0.0400),
    Study(name="Brown 2022", yi=0.20, vi=0.0625),
    Study(name="Liu 2023", yi=0.55, vi=0.0500),
]


class TestDerSimonianLaird:
    """Numerical correctness of the DL algorithm."""

    def test_returns_meta_analysis_result(self):
        result = dersimonianlaird(STUDIES)
        assert isinstance(result, MetaAnalysisResult)

    def test_pooled_effect_size(self):
        result = dersimonianlaird(STUDIES)
        assert abs(result.pooled_es - 0.4884) < 0.001

    def test_tau_squared_zero_when_q_lt_df(self):
        # Q=2.92 < df=4 → τ²=0 (clamped at 0)
        result = dersimonianlaird(STUDIES)
        assert result.tau2 == pytest.approx(0.0, abs=1e-9)

    def test_i_squared_zero(self):
        result = dersimonianlaird(STUDIES)
        assert result.i2 == pytest.approx(0.0, abs=0.01)

    def test_q_statistic(self):
        result = dersimonianlaird(STUDIES)
        assert abs(result.Q - 2.9226) < 0.001

    def test_se_pooled(self):
        result = dersimonianlaird(STUDIES)
        assert abs(result.se_pool - 0.1065) < 0.001

    def test_ci_lower(self):
        result = dersimonianlaird(STUDIES)
        assert abs(result.ci_lo - 0.2796) < 0.001

    def test_ci_upper(self):
        result = dersimonianlaird(STUDIES)
        assert abs(result.ci_hi - 0.6972) < 0.001

    def test_k_equals_number_of_studies(self):
        result = dersimonianlaird(STUDIES)
        assert result.k == 5

    def test_minimum_three_studies_required(self):
        with pytest.raises(ValueError, match="at least 3"):
            dersimonianlaird(STUDIES[:2])

    def test_nonzero_tau_squared_with_heterogeneous_studies(self):
        """Heterogeneous studies should yield τ²>0."""
        heterogeneous = [
            Study(name="A", yi=0.10, vi=0.01),
            Study(name="B", yi=0.90, vi=0.01),
            Study(name="C", yi=0.50, vi=0.01),
        ]
        result = dersimonianlaird(heterogeneous)
        assert result.tau2 > 0
        assert result.i2 > 0


class TestForestPlotMermaid:
    """Forest-plot Mermaid output."""

    def test_returns_string(self):
        result = dersimonianlaird(STUDIES)
        mermaid = build_forest_plot_mermaid(STUDIES, result)
        assert isinstance(mermaid, str)

    def test_starts_with_graph_lr(self):
        result = dersimonianlaird(STUDIES)
        mermaid = build_forest_plot_mermaid(STUDIES, result)
        assert mermaid.strip().startswith("graph LR")

    def test_contains_all_study_names(self):
        result = dersimonianlaird(STUDIES)
        mermaid = build_forest_plot_mermaid(STUDIES, result)
        for study in STUDIES:
            assert study.name in mermaid, f"Study '{study.name}' missing from Forest-Plot"

    def test_contains_pool_node(self):
        result = dersimonianlaird(STUDIES)
        mermaid = build_forest_plot_mermaid(STUDIES, result)
        assert "Pool" in mermaid

    def test_contains_i_squared(self):
        result = dersimonianlaird(STUDIES)
        mermaid = build_forest_plot_mermaid(STUDIES, result)
        assert "I²" in mermaid or "I&sup2;" in mermaid or "I2" in mermaid

    def test_all_studies_point_to_pool(self):
        result = dersimonianlaird(STUDIES)
        mermaid = build_forest_plot_mermaid(STUDIES, result)
        # Each study should have an arrow to Pool
        assert mermaid.count("-->") >= len(STUDIES)

    def test_pooled_effect_in_plot(self):
        result = dersimonianlaird(STUDIES)
        mermaid = build_forest_plot_mermaid(STUDIES, result)
        # Pooled ES rounded to 2 decimal places should appear
        assert "0.49" in mermaid or "0.488" in mermaid


class TestEdgeCases:
    """Edge-cases and robustness."""

    def test_exactly_three_studies(self):
        three = STUDIES[:3]
        result = dersimonianlaird(three)
        assert result.k == 3
        assert isinstance(result.pooled_es, float)

    def test_studies_with_identical_effect_sizes(self):
        same = [Study(name=f"S{i}", yi=0.5, vi=0.04) for i in range(4)]
        result = dersimonianlaird(same)
        assert abs(result.pooled_es - 0.5) < 0.001
        assert result.tau2 == pytest.approx(0.0, abs=1e-9)


class TestInputValidation:
    """Issue #706: unplausible values from user-supplied JSON must be rejected
    before dersimonianlaird() computes with them, with a clear message that
    names the offending study."""

    def test_zero_variance_rejected_with_study_name(self):
        studies = [
            Study(name="Smith 2020", yi=0.5, vi=0.0625),
            Study(name="ZeroVar Study", yi=0.3, vi=0.0),
            Study(name="Chen 2019", yi=0.7, vi=0.04),
        ]
        with pytest.raises(ValueError, match="ZeroVar Study"):
            dersimonianlaird(studies)

    def test_negative_variance_rejected_with_study_name_and_value(self):
        studies = [
            Study(name="Smith 2020", yi=0.5, vi=0.0625),
            Study(name="NegVar Study", yi=0.3, vi=-0.05),
            Study(name="Chen 2019", yi=0.7, vi=0.04),
        ]
        with pytest.raises(ValueError, match="NegVar Study"):
            dersimonianlaird(studies)
        with pytest.raises(ValueError, match=r"-0\.05"):
            dersimonianlaird(studies)

    def test_nan_yi_rejected(self):
        studies = [
            Study(name="Smith 2020", yi=0.5, vi=0.0625),
            Study(name="NaN Study", yi=math.nan, vi=0.04),
            Study(name="Chen 2019", yi=0.7, vi=0.04),
        ]
        with pytest.raises(ValueError, match="NaN Study"):
            dersimonianlaird(studies)

    def test_inf_vi_rejected(self):
        studies = [
            Study(name="Smith 2020", yi=0.5, vi=0.0625),
            Study(name="Inf Study", yi=0.3, vi=math.inf),
            Study(name="Chen 2019", yi=0.7, vi=0.04),
        ]
        with pytest.raises(ValueError, match="Inf Study"):
            dersimonianlaird(studies)

    def test_inf_yi_rejected(self):
        studies = [
            Study(name="Smith 2020", yi=0.5, vi=0.0625),
            Study(name="Inf Study", yi=math.inf, vi=0.04),
            Study(name="Chen 2019", yi=0.7, vi=0.04),
        ]
        with pytest.raises(ValueError, match="Inf Study"):
            dersimonianlaird(studies)

    def test_valid_studies_still_produce_same_result_as_before(self):
        result = dersimonianlaird(STUDIES)
        assert abs(result.pooled_es - 0.4884) < 0.001

    def test_minimum_three_studies_message_unchanged(self):
        with pytest.raises(ValueError, match="at least 3"):
            dersimonianlaird(STUDIES[:2])


class TestLoadStudiesValidation:
    """_load_studies() must reject missing/non-numeric yi/vi with a clear
    message instead of raw KeyError/ValueError from the cast."""

    def test_missing_yi_key_raises_clear_value_error(self, tmp_path):
        path = tmp_path / "studies.json"
        path.write_text(
            json.dumps(
                [
                    {"name": "Smith 2020", "yi": 0.5, "vi": 0.0625},
                    {"name": "Missing YI", "vi": 0.04},
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Missing YI"):
            _load_studies(str(path))

    def test_missing_vi_key_raises_clear_value_error(self, tmp_path):
        path = tmp_path / "studies.json"
        path.write_text(
            json.dumps(
                [
                    {"name": "Smith 2020", "yi": 0.5, "vi": 0.0625},
                    {"name": "Missing VI", "yi": 0.3},
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Missing VI"):
            _load_studies(str(path))

    def test_non_numeric_yi_raises_clear_value_error(self, tmp_path):
        path = tmp_path / "studies.json"
        path.write_text(
            json.dumps(
                [
                    {"name": "Smith 2020", "yi": 0.5, "vi": 0.0625},
                    {"name": "Bad YI", "yi": "not-a-number", "vi": 0.04},
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Bad YI"):
            _load_studies(str(path))

    def test_valid_json_still_loads_correctly(self, tmp_path):
        path = tmp_path / "studies.json"
        path.write_text(
            json.dumps(
                [
                    {"name": "Smith 2020", "yi": 0.5, "vi": 0.0625},
                    {"name": "Jones 2021", "yi": 0.3, "vi": 0.09},
                    {"name": "Chen 2019", "yi": 0.7, "vi": 0.04},
                ]
            ),
            encoding="utf-8",
        )
        studies = _load_studies(str(path))
        assert len(studies) == 3
        assert studies[0].name == "Smith 2020"
        assert studies[0].yi == pytest.approx(0.5)
