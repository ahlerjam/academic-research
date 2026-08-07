"""Tests fuer das 5D-Scoring-Modul (#704).

Portiert die vier gerechneten Dimensionen (Aktualitaet, Qualitaet, Autoritaet,
Zugaenglichkeit) aus der Prosa-Formel in ``commands/score.md:67-75`` nach
Python. Verhaltensgleichheit ist das Kriterium: die erwarteten Konstanten
in ``test_total_score_matches_documented_formula`` sind von Hand aus genau
dieser Formel berechnet (Gewichte 0.35/0.20/0.15/0.15/0.15,
Aktualitaets-Decay ``exp(-ln(2) * delta / 5)``, Qualitaet
``log10(citations / max(1, years_since_pub) + 1) / 2``).

Die Relevanz-Dimension (Gewicht 0.35) kommt weiterhin vom
``relevance-scorer``-Agenten und wird hier nur als Parameter durchgereicht,
nie berechnet.
"""

import math

import pytest
from scripts.scoring import (
    WEIGHT_ACCESS,
    WEIGHT_AUTHORITY,
    WEIGHT_QUALITY,
    WEIGHT_RECENCY,
    WEIGHT_RELEVANCE,
    access,
    authority,
    quality,
    recency,
    total_score,
)

CURRENT_YEAR = 2026


def test_recency_matches_exponential_decay_formula():
    # exp(-ln(2) * (2026-2023) / 5) -- 5-Jahres-Halbwertszeit, siehe score.md
    expected = math.exp(-math.log(2) * 3 / 5)
    assert recency(2023, CURRENT_YEAR) == pytest.approx(expected)


def test_recency_missing_year_returns_documented_default():
    """Fehlendes `year` -> 0.0 (konservativ: keine Aktualitaet attestiert)."""
    assert recency(None, CURRENT_YEAR) == 0.0


def test_recency_future_year_is_clamped_to_one():
    """Publikationsjahr in der Zukunft ergibt einen Exponenten > 1 (Rohwert
    > 1.0) -- wie bei `quality` wird das obere Ende auf 1.0 geklemmt, damit
    die Gesamtsumme im [0, 1]-Intervall bleibt (AC5)."""
    raw = math.exp(-math.log(2) * (CURRENT_YEAR - 2028) / 5)
    assert raw > 1.0  # Testannahme pruefen: dieser Fall waere ohne Clamp > 1
    assert recency(2028, CURRENT_YEAR) == 1.0


def test_quality_matches_log_scaled_citations_formula():
    # log10(50 / 3 + 1) / 2 -- years_since_pub = 2026-2023 = 3
    expected = min(math.log10(50 / 3 + 1) / 2, 1.0)
    assert quality(50, 2023, CURRENT_YEAR) == pytest.approx(expected)


def test_quality_missing_citation_count_returns_documented_default():
    """Fehlendes/0 `citation_count` -> wie citations=0 behandelt (bestehende
    Formel), kein Absturz."""
    assert quality(None, 2020, CURRENT_YEAR) == pytest.approx(quality(0, 2020, CURRENT_YEAR))


def test_quality_missing_year_returns_documented_default():
    """Fehlendes `year` -> years_since_pub nicht berechenbar -> 0.0
    (konservativ, analog `recency`)."""
    assert quality(50, None, CURRENT_YEAR) == 0.0


def test_authority_top_venue_scores_one():
    assert authority("IEEE Transactions on Software Engineering") == 1.0


def test_authority_indexed_journal_scores_zero_point_seven():
    assert authority("Journal of Cloud Computing") == 0.7


def test_authority_conference_scores_zero_point_four():
    assert authority("International DevOps Conference") == 0.4


def test_authority_unknown_venue_scores_zero_point_two():
    assert authority("Random Blog") == 0.2


def test_authority_missing_venue_returns_documented_default():
    assert authority(None) == 0.2


def test_access_open_access_scores_one():
    assert access({"open_access": True}) == 1.0


def test_access_doi_with_institutional_access_scores_zero_point_eight():
    assert access({"doi": "10.1/x", "institutional_access": True}) == 0.8


def test_access_doi_only_scores_zero_point_five():
    assert access({"doi": "10.1/x"}) == 0.5


def test_access_url_only_scores_zero_point_two():
    assert access({"url": "http://example.org"}) == 0.2


def test_access_nothing_available_scores_zero():
    assert access({}) == 0.0


@pytest.mark.parametrize(
    "relevance,paper,expected",
    [
        (
            0.9,
            {
                "year": 2023,
                "citation_count": 50,
                "venue": "IEEE Transactions on Software Engineering",
                "open_access": True,
            },
            0.8404873871933739,
        ),
        (
            0.6,
            {
                "citation_count": 30,
                "venue": "Journal of Cloud Computing",
                "doi": "10.1/x",
                "institutional_access": True,
            },
            0.435,
        ),
        (
            0.5,
            {
                "year": 2020,
                "venue": "International DevOps Conference",
                "doi": "10.1/y",
            },
            0.3970550563296124,
        ),
        (
            0.3,
            {
                "year": 2028,
                "citation_count": 10,
                "venue": "Unknown Blog",
                "url": "http://x",
            },
            0.44310445138686694,
        ),
        (
            1.0,
            {
                "year": 2026,
                "citation_count": 10**9,
                "venue": "Nature",
                "open_access": True,
            },
            1.0,
        ),
    ],
)
def test_total_score_matches_documented_formula(relevance, paper, expected):
    """Fuenf Eingabefaelle, erwartete Werte von Hand aus der in
    commands/score.md:67-75 dokumentierten Formel berechnet (AC2)."""
    assert total_score(relevance, paper, CURRENT_YEAR) == pytest.approx(expected)


@pytest.mark.parametrize(
    "relevance,paper",
    [
        (
            0.9,
            {
                "year": 2023,
                "citation_count": 50,
                "venue": "IEEE Transactions on Software Engineering",
                "open_access": True,
            },
        ),
        (0.6, {"citation_count": 30, "venue": "Journal of Cloud Computing", "doi": "10.1/x"}),
        (0.5, {"year": 2020, "venue": "International DevOps Conference", "doi": "10.1/y"}),
        (0.3, {"year": 2028, "citation_count": 10, "venue": "Unknown Blog", "url": "http://x"}),
        (1.0, {"year": 2026, "citation_count": 10**9, "venue": "Nature", "open_access": True}),
        (0.0, {}),
        (1.0, {}),
    ],
)
def test_total_score_bounds(relevance, paper):
    """AC5: Gesamtsumme liegt fuer jede getestete Eingabe in [0, 1],
    auch bei fehlenden Feldern und Zukunftsjahr."""
    result = total_score(relevance, paper, CURRENT_YEAR)
    assert 0.0 <= result <= 1.0


def test_relevance_weight_is_035():
    """AC4: Relevanz geht mit Gewicht 0.35 in die Summe ein -- nachgewiesen
    ueber die Ableitung (Differenz zweier total_score-Aufrufe bei sonst
    gleichem Paper), nicht ueber einen erzwungenen Nullpunkt der anderen
    Dimensionen (deren Minimum liegt formelbedingt ueber 0)."""
    assert WEIGHT_RELEVANCE == 0.35
    paper = {"year": 2020, "citation_count": 5, "venue": "Some Venue", "url": "http://x"}
    low = total_score(0.2, paper, CURRENT_YEAR)
    high = total_score(0.9, paper, CURRENT_YEAR)
    assert high - low == pytest.approx(0.35 * (0.9 - 0.2))


def test_weights_sum_to_one():
    assert (
        WEIGHT_RELEVANCE + WEIGHT_RECENCY + WEIGHT_QUALITY + WEIGHT_AUTHORITY + WEIGHT_ACCESS
        == pytest.approx(1.0)
    )
