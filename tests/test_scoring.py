"""Tests fuer das 5D-Scoring-Modul (#704, #705).

Portiert die vier gerechneten Dimensionen (Aktualitaet, Qualitaet, Autoritaet,
Zugaenglichkeit) aus der Prosa-Formel in ``commands/score.md`` (Abschnitt
"Schritt 3+4: 4 weitere Dimensionen berechnen...") nach Python. Verhaltensgleichheit
ist das Kriterium: die erwarteten Konstanten in ``test_total_score_matches_documented_formula``
sind von Hand aus genau dieser Formel berechnet (Gewichte 0.35/0.20/0.15/0.15/0.15,
Aktualitaets-Decay ``exp(-ln(2) * delta / 5)``, Qualitaet
``log10(citations / max(1, years_since_pub) + 1) / 2``).

Die Relevanz-Dimension (Gewicht 0.35) kommt weiterhin vom
``relevance-scorer``-Agenten und wird hier nur als Parameter durchgereicht,
nie berechnet.

Seit #705: Feldnormalisierung (fwci) in ``quality()``, profilabhaengige
Halbwertszeit/Gewichte via ``load_profile()``. ``quality()`` gibt seither ein
``QualityResult(value, source)``-NamedTuple zurueck statt eines nackten
Floats -- die bestehenden Tests darunter greifen entsprechend auf
``.value`` zu.
"""

import math
from pathlib import Path

import pytest
from scripts.scoring import (
    DEFAULT_HALF_LIFE_YEARS,
    DEFAULT_WEIGHTS,
    WEIGHT_ACCESS,
    WEIGHT_AUTHORITY,
    WEIGHT_QUALITY,
    WEIGHT_RECENCY,
    WEIGHT_RELEVANCE,
    access,
    authority,
    load_profile,
    quality,
    recency,
    total_score,
)

CURRENT_YEAR = 2026
PROFILES_DIR = Path(__file__).parent.parent / "library-profiles" / "profiles"


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
    result = quality(50, 2023, CURRENT_YEAR)
    assert result.value == pytest.approx(expected)
    assert result.source == "raw"


def test_quality_missing_citations_returns_documented_default():
    """Fehlendes/0 `citations` -> wie citations=0 behandelt (bestehende
    Formel), kein Absturz."""
    assert quality(None, 2020, CURRENT_YEAR).value == pytest.approx(
        quality(0, 2020, CURRENT_YEAR).value
    )


def test_quality_missing_year_returns_documented_default():
    """Fehlendes `year` -> years_since_pub nicht berechenbar -> 0.0
    (konservativ, analog `recency`)."""
    result = quality(50, None, CURRENT_YEAR)
    assert result.value == 0.0
    assert result.source == "raw"


def test_quality_uses_fwci_when_present():
    """AC1: liefert OpenAlex einen feldnormalisierten Wert (fwci), wird
    dieser verwendet -- Herkunft ist am Ergebnis erkennbar."""
    result = quality(50, 2023, CURRENT_YEAR, citations_normalized=1.5)
    assert result.value == pytest.approx(0.75)  # clamp(1.5 / 2, 0, 1)
    assert result.source == "fwci"


def test_quality_falls_back_to_raw_when_citations_normalized_missing():
    """AC1: fehlt der feldnormalisierte Wert, wird der rohe genutzt --
    identisch zum bisherigen Verhalten."""
    with_fwci = quality(50, 2023, CURRENT_YEAR, citations_normalized=None)
    without_fwci = quality(50, 2023, CURRENT_YEAR)
    assert with_fwci.source == "raw"
    assert with_fwci.value == pytest.approx(without_fwci.value)


def test_quality_fwci_is_clamped_to_zero_one():
    """fwci ist nach oben unbeschraenkt (Weltdurchschnitt=1.0, Ausreisser
    zweistellig moeglich) -- der [0,1]-Clamp haelt die `total_score`-
    Invariante (AC5) auch im fwci-Zweig."""
    result = quality(50, 2023, CURRENT_YEAR, citations_normalized=50.0)
    assert result.value == 1.0
    assert result.source == "fwci"


def test_quality_fwci_does_not_need_year():
    """fwci ist bereits altersnormalisiert -- anders als der Rohwert-Zweig
    braucht der fwci-Zweig kein `year`."""
    result = quality(None, None, CURRENT_YEAR, citations_normalized=2.0)
    assert result.value == 1.0
    assert result.source == "fwci"


def test_recency_custom_half_life_years():
    """AC2: `half_life_years` ist konfigurierbar (Default weiterhin 5,
    verhaltensgleich zum bisherigen Test oben)."""
    expected = math.exp(-math.log(2) * 3 / 15)
    assert recency(2023, CURRENT_YEAR, half_life_years=15) == pytest.approx(expected)
    assert recency(2023, CURRENT_YEAR, half_life_years=15) != pytest.approx(
        recency(2023, CURRENT_YEAR)
    )


def test_load_profile_missing_file_returns_documented_defaults():
    """AC2: fehlt der Eintrag (keine Datei), gelten die heutigen Werte als
    Default."""
    profile = load_profile(PROFILES_DIR / "does-not-exist.yaml")
    assert profile["half_life_years"] == DEFAULT_HALF_LIFE_YEARS
    assert profile["weights"] == DEFAULT_WEIGHTS


def test_load_profile_none_path_returns_documented_defaults():
    profile = load_profile(None)
    assert profile["half_life_years"] == DEFAULT_HALF_LIFE_YEARS
    assert profile["weights"] == DEFAULT_WEIGHTS


def test_load_profile_reads_weights_and_half_life_from_yaml(tmp_path):
    """AC2: Halbwertszeit und die fuenf Gewichte kommen aus `active.yaml`."""
    path = tmp_path / "active.yaml"
    path.write_text(
        "scoring:\n"
        "  half_life_years: 12\n"
        "  weights:\n"
        "    relevance: 0.4\n"
        "    recency: 0.1\n"
        "    quality: 0.2\n"
        "    authority: 0.2\n"
        "    access: 0.1\n",
        encoding="utf-8",
    )
    profile = load_profile(path)
    assert profile["half_life_years"] == 12.0
    assert profile["weights"] == {
        "relevance": 0.4,
        "recency": 0.1,
        "quality": 0.2,
        "authority": 0.2,
        "access": 0.1,
    }


def test_load_profile_missing_scoring_key_returns_documented_defaults(tmp_path):
    """Bestandsprofile ohne `scoring:`-Abschnitt (z. B. via scihub_optin.py
    ausgerollte active.yaml) duerfen nicht crashen."""
    path = tmp_path / "active.yaml"
    path.write_text("uni: 'TUM'\nscihub_optin: false\n", encoding="utf-8")
    profile = load_profile(path)
    assert profile["half_life_years"] == DEFAULT_HALF_LIFE_YEARS
    assert profile["weights"] == DEFAULT_WEIGHTS


def test_load_profile_parse_error_returns_documented_defaults(tmp_path):
    path = tmp_path / "active.yaml"
    path.write_text("scoring: [this, is, not, a, mapping\n", encoding="utf-8")
    profile = load_profile(path)
    assert profile["half_life_years"] == DEFAULT_HALF_LIFE_YEARS
    assert profile["weights"] == DEFAULT_WEIGHTS


def test_load_profile_partial_weights_fall_back_per_field(tmp_path):
    """Fehlt nur ein einzelnes Gewicht, faellt genau dieses auf den Default
    zurueck -- nicht das gesamte Profil."""
    path = tmp_path / "active.yaml"
    path.write_text(
        "scoring:\n  weights:\n    recency: 0.5\n",
        encoding="utf-8",
    )
    profile = load_profile(path)
    assert profile["half_life_years"] == DEFAULT_HALF_LIFE_YEARS
    assert profile["weights"]["recency"] == 0.5
    assert profile["weights"]["relevance"] == DEFAULT_WEIGHTS["relevance"]
    assert profile["weights"]["quality"] == DEFAULT_WEIGHTS["quality"]


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
    assert access({"oa_url": "https://arxiv.org/..."}) == 1.0


def test_access_open_access_pdf_scores_one():
    assert access({"open_access_pdf": "https://example.org/paper.pdf"}) == 1.0


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
                "citations": 50,
                "venue": "IEEE Transactions on Software Engineering",
                "oa_url": "https://arxiv.org/pdf/2305.12345.pdf",
            },
            0.8404873871933739,
        ),
        (
            0.6,
            {
                "citations": 30,
                "venue": "Journal of Cloud Computing",
                "doi": "10.1/x",
            },
            0.39,
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
                "citations": 10,
                "venue": "Unknown Blog",
                "url": "http://x",
            },
            0.44310445138686694,
        ),
        (
            1.0,
            {
                "year": 2026,
                "citations": 10**9,
                "venue": "Nature",
                "oa_url": "https://arxiv.org/pdf/2305.12345.pdf",
            },
            1.0,
        ),
    ],
)
def test_total_score_matches_documented_formula(relevance, paper, expected):
    """Fuenf Eingabefaelle, erwartete Werte von Hand aus der in
    commands/score.md (Abschnitt "Schritt 3+4: 4 weitere Dimensionen...")
    dokumentierten Formel berechnet (AC2)."""
    assert total_score(relevance, paper, CURRENT_YEAR) == pytest.approx(expected)


@pytest.mark.parametrize(
    "relevance,paper",
    [
        (
            0.9,
            {
                "year": 2023,
                "citations": 50,
                "venue": "IEEE Transactions on Software Engineering",
                "oa_url": "https://arxiv.org/pdf/2305.12345.pdf",
            },
        ),
        (0.6, {"citations": 30, "venue": "Journal of Cloud Computing", "doi": "10.1/x"}),
        (0.5, {"year": 2020, "venue": "International DevOps Conference", "doi": "10.1/y"}),
        (0.3, {"year": 2028, "citations": 10, "venue": "Unknown Blog", "url": "http://x"}),
        (
            1.0,
            {
                "year": 2026,
                "citations": 10**9,
                "venue": "Nature",
                "oa_url": "https://arxiv.org/pdf/2305.12345.pdf",
            },
        ),
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
    paper = {"year": 2020, "citations": 5, "venue": "Some Venue", "url": "http://x"}
    low = total_score(0.2, paper, CURRENT_YEAR)
    high = total_score(0.9, paper, CURRENT_YEAR)
    assert high - low == pytest.approx(0.35 * (0.9 - 0.2))


def test_weights_sum_to_one():
    assert (
        WEIGHT_RELEVANCE + WEIGHT_RECENCY + WEIGHT_QUALITY + WEIGHT_AUTHORITY + WEIGHT_ACCESS
        == pytest.approx(1.0)
    )


def test_systematic_review_and_fachhausarbeit_profiles_differ():
    """AC3: mindestens zwei Profile sind hinterlegt und unterscheiden sich
    nachweisbar -- ein Systematic Review gewichtet anders als eine
    Fachhausarbeit, sowohl in Rohkonfiguration als auch im Ergebnis fuer
    dasselbe Paper."""
    review = load_profile(PROFILES_DIR / "systematic-review.yaml")
    fachhausarbeit = load_profile(PROFILES_DIR / "fachhausarbeit.yaml")

    assert review["half_life_years"] != fachhausarbeit["half_life_years"]
    assert review["weights"] != fachhausarbeit["weights"]
    for profile in (review, fachhausarbeit):
        assert sum(profile["weights"].values()) == pytest.approx(1.0)

    paper = {
        "year": 2010,
        "citations": 200,
        "citations_normalized": 2.0,
        "venue": "Journal of Cloud Computing",
        "doi": "10.1/x",
    }
    review_score = total_score(0.7, paper, CURRENT_YEAR, review)
    fachhausarbeit_score = total_score(0.7, paper, CURRENT_YEAR, fachhausarbeit)
    assert review_score != pytest.approx(fachhausarbeit_score)


def test_review_profile_keeps_landmark_1998_paper_in_top_cluster():
    """AC4: ein hoch zitiertes/fwci-starkes Grundlagenwerk von 1998 faellt
    unter dem Review-Profil nicht mehr allein durch sein Alter aus den
    Top-Raengen (Kernliteratur-Schwelle aus score.md: total >= 0.75) --
    unter dem heutigen 5-Jahre-Default-Profil dagegen schon."""
    paper = {
        "year": 1998,
        "citations": 4000,
        "citations_normalized": 3.0,
        "venue": "Journal of Software Engineering",
        "oa_url": "https://arxiv.org/pdf/x.pdf",
    }
    relevance = 0.8

    review = load_profile(PROFILES_DIR / "systematic-review.yaml")
    review_score = total_score(relevance, paper, CURRENT_YEAR, review)
    default_score = total_score(relevance, paper, CURRENT_YEAR, None)

    assert review_score >= 0.75
    assert default_score < 0.75
    assert review_score > default_score
