"""Screening-Kaskade: Zirkularitaet, mechanischer Vorfilter, Ausschlussprotokoll (#892).

Die Bewertungskette lief in einer Reihenfolge, die ohne sich selbst nicht
auskam: Schritt "Ranking" rechnete den 5D-Score mit einer Relevanz, die erst
der spaetere ``relevance-scorer`` erzeugt. Dazu kam kein Vorfilter (jeder
Treffer kostete einen Modellaufruf) und kein Protokoll der mechanischen
Ausschluesse.

Getestet wird gegen die fuenf Akzeptanzkriterien des Issues:

1. Das Vorranking kommt ohne einen Wert aus dem Relevanz-Schritt aus.
2. Bei tausend Treffern laeuft das Modell auf deutlich weniger als hundert Batches.
3. Jeder Ausschluss ist mit Grund im Vault nachlesbar, auch die mechanischen.
4. Der PRISMA-Fluss laesst sich allein aus dem Protokoll aufstellen.
5. Eine Arbeit, die die Kriterien eindeutig verfehlt, kostet keinen Modellaufruf.
"""

from __future__ import annotations

import inspect
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCREENING_SCRIPTS = REPO_ROOT / "skills" / "parallel-screening" / "scripts"
if str(SCREENING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCREENING_SCRIPTS))

import screening_ledger  # noqa: E402
import screening_prefilter  # noqa: E402

import scoring  # noqa: E402  (scripts/ liegt via conftest auf sys.path)
from search import run_interactive_phase1  # noqa: E402
from text_utils import normalize_paper  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "screening_prefilter_892"
CORPUS = FIXTURE_DIR / "corpus.jsonl"
SEARCH_MD = REPO_ROOT / "commands" / "search.md"

BATCH_SIZE = 10

#: Schwellwert fuer AC2. "Deutlich weniger als hundert" wird hier als
#: hoechstens ein Drittel der bisherigen Batchzahl festgeschrieben.
MAX_BATCHES_AFTER = 33

FILTERS = {
    "year_min": 2015,
    "languages": ["de", "en"],
    "publication_types": ["journal-article", "proceedings-article"],
}

CONTEXT_MD = """# Akademischer Kontext

### Ein-/Ausschlusskriterien

**Einschluss**
- Peer-reviewed Arbeiten ab 2015

**Ausschluss**
- Editorials und Rezensionen

```screening_filters
year_min: 2015
languages: [de, en]
publication_types: [journal-article, proceedings-article]
```

### Gliederung
- unberuehrt
"""


def _corpus() -> list[dict]:
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# AC1 — das Vorranking braucht keinen Wert aus dem Relevanz-Schritt
# ---------------------------------------------------------------------------


def test_prescore_has_no_relevance_parameter():
    """AC1: ``prescore()`` nimmt gar keine Relevanz entgegen."""
    params = list(inspect.signature(scoring.prescore).parameters)
    assert "relevance" not in params, (
        "prescore() darf keinen Relevanzwert annehmen — sonst bleibt die Zirkularitaet"
    )
    assert params[0] == "paper"


def test_prescore_weights_are_renormalised_to_one():
    """AC1: die vier verbleibenden Dimensionen tragen zusammen 1.0."""
    weights = scoring.prescore_weights()
    assert set(weights) == {"recency", "quality", "authority", "access"}
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)
    # Verhaeltnis der Bestandsgewichte bleibt erhalten (0.20 : 0.15 : 0.15 : 0.15)
    assert weights["recency"] > weights["quality"]
    assert math.isclose(weights["quality"], weights["authority"])
    assert math.isclose(weights["quality"], weights["access"])


def test_prescore_stays_inside_unit_interval():
    """AC1: Ergebnis in [0, 1] — auch bei entarteten Eingaben."""
    best = {
        "year": 2030,
        "citations": 10_000,
        "venue": "IEEE Transactions",
        "oa_url": "https://example.org/a.pdf",
    }
    worst: dict[str, object] = {}
    assert 0.0 <= scoring.prescore(worst, current_year=2026) <= 1.0
    assert 0.0 <= scoring.prescore(best, current_year=2026) <= 1.0
    assert scoring.prescore(best, current_year=2026) > scoring.prescore(worst, current_year=2026)


def test_total_score_still_takes_relevance_unchanged():
    """Regression: der 5D-Gesamtscore bleibt, wo er hingehoert."""
    paper = {"year": 2024, "citations": 12, "venue": "Journal of X", "doi": "10.1/x"}
    assert scoring.total_score(0.9, paper, current_year=2026) != scoring.total_score(
        0.1, paper, current_year=2026
    )


def test_prescore_cli_needs_no_relevance_argument():
    """AC1: auch der CLI-Weg kommt ohne Relevanz aus."""
    paper = json.dumps({"year": 2024, "citations": 30, "venue": "IEEE Software", "doi": "10.1/x"})
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "scoring.py"), "prescore", paper, "2026"],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(out.stdout)
    assert "prescore" in payload
    assert 0.0 <= payload["prescore"] <= 1.0


def test_search_md_ranking_step_scores_without_relevance():
    """AC1: der Ranking-Schritt in commands/search.md nennt die Relevanz nicht mehr."""
    text = SEARCH_MD.read_text(encoding="utf-8")
    ranking = _section(text, "### Schritt 8:")
    assert "prescore" in ranking, "Ranking-Schritt muss auf das 4D-Vorranking verweisen"
    assert "5D" not in ranking, "der 5D-Gesamtscore darf hier noch nicht gerechnet werden"
    assert "relevance-scorer" not in ranking


def _section(text: str, heading_prefix: str) -> str:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading_prefix))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_run_interactive_phase1_sorts_by_prescore():
    """AC1: die Vorschau ordnet nach dem Vorranking, nicht nach dem 5D-Score."""
    papers = [
        {"paper_id": "a", "prescore": 0.1},
        {"paper_id": "b", "prescore": 0.9},
    ]
    preview = run_interactive_phase1(papers, query="q")
    assert [p["paper_id"] for p in preview["top_papers"]] == ["b", "a"]


def test_run_interactive_phase1_falls_back_to_score():
    """Bestandskompatibilitaet: alte ranked.json ohne prescore bleibt sortierbar."""
    papers = [{"paper_id": "a", "score": 0.2}, {"paper_id": "b", "score": 0.8}]
    preview = run_interactive_phase1(papers, query="q")
    assert [p["paper_id"] for p in preview["top_papers"]] == ["b", "a"]


# ---------------------------------------------------------------------------
# Metadaten fuer den Vorfilter
# ---------------------------------------------------------------------------


def test_normalize_paper_carries_language_and_publication_type():
    entry = normalize_paper(
        {"title": "T", "language": "en", "publication_type": "journal-article"}, "crossref"
    )
    assert entry["language"] == "en"
    assert entry["publication_type"] == "journal-article"


def test_normalize_paper_leaves_unknown_metadata_empty():
    entry = normalize_paper({"title": "T"}, "crossref")
    assert entry["language"] is None
    assert entry["publication_type"] is None


# ---------------------------------------------------------------------------
# Filterblock
# ---------------------------------------------------------------------------


def test_load_filters_reads_the_fenced_block_from_the_criteria_section():
    filters = screening_prefilter.load_filters(CONTEXT_MD)
    assert filters == FILTERS


def test_load_filters_ignores_a_block_outside_the_criteria_section():
    text = "### Gliederung\n\n```screening_filters\nyear_min: 1900\n```\n"
    assert screening_prefilter.load_filters(text) == {}


def test_load_filters_without_block_is_empty():
    assert screening_prefilter.load_filters("### Ein-/Ausschlusskriterien\n\nnur Prosa\n") == {}


# ---------------------------------------------------------------------------
# AC5 / AC2 — mechanische Vorauswahl
# ---------------------------------------------------------------------------


def test_missing_metadata_is_never_excluded():
    """AC5-Gegenprobe: Unwissen ist kein Ausschlussgrund (fail-open)."""
    papers = [
        {"paper_id": "no-year", "language": "en", "publication_type": "journal-article"},
        {"paper_id": "no-lang", "year": 2020, "publication_type": "journal-article"},
        {"paper_id": "no-type", "year": 2020, "language": "en"},
    ]
    result = screening_prefilter.apply_filters(papers, FILTERS)
    assert {p["paper_id"] for p in result["to_screen"]} == {"no-year", "no-lang", "no-type"}
    assert result["excluded"] == []


def test_without_filter_block_prefilter_is_a_no_op():
    """Fail-open: ohne Kriterienblock verhaelt sich der Lauf wie vor #892."""
    papers = [{"paper_id": "x", "year": 1901, "language": "fr", "publication_type": "editorial"}]
    result = screening_prefilter.apply_filters(papers, {})
    assert [p["paper_id"] for p in result["to_screen"]] == ["x"]
    assert result["excluded"] == []


def test_each_rule_exclusion_names_its_criterion():
    papers = [
        {"paper_id": "old", "year": 2001, "language": "en", "publication_type": "journal-article"},
        {"paper_id": "fr", "year": 2020, "language": "fr", "publication_type": "journal-article"},
        {"paper_id": "ed", "year": 2020, "language": "en", "publication_type": "editorial"},
    ]
    result = screening_prefilter.apply_filters(papers, FILTERS)
    assert result["to_screen"] == []
    by_id = {row["paper_id"]: row for row in result["excluded"]}
    assert by_id["old"]["criterion"] == "Zeitraum"
    assert by_id["fr"]["criterion"] == "Sprache"
    assert by_id["ed"]["criterion"] == "Publikationstyp"
    for row in result["excluded"]:
        assert row["criterion"] in row["reason"]
        assert row["reason"].strip()


# ---------------------------------------------------------------------------
# Publikationstyp-Vokabulare (Regression: stiller Ausschluss foerderfaehiger Arbeiten)
# ---------------------------------------------------------------------------

#: Werte, die Semantic Scholar in ``publicationTypes`` liefert, die aber das
#: Studiendesign beschreiben und **nichts** ueber den Publikationstyp sagen.
#: Quelle: https://api.semanticscholar.org/graph/v1/swagger.json, Parameter
#: ``publicationTypes`` (Stand 2026-08-14).
S2_STUDY_DESIGN_VALUES = ["Study", "CaseReport", "ClinicalTrial", "MetaAnalysis"]

#: Reale Vokabularwerte, die einen Publikationstyp benennen und deshalb
#: weiterhin ausschliessen duerfen. Quellen: https://api.crossref.org/types,
#: https://api.openalex.org/works?group_by=type (Stand 2026-08-14).
KNOWN_NON_ALLOWED_TYPES = ["editorial", "erratum", "book-review", "letter", "dataset", "preprint"]


@pytest.mark.parametrize("value", S2_STUDY_DESIGN_VALUES)
def test_study_design_values_are_no_exclusion_reason(value):
    """Fail-open: ``Study`` & Co. benennen keinen Publikationstyp — kein Ausschluss.

    Ein Zeitschriftenaufsatz, den Semantic Scholar als ``Study`` fuehrt, ist
    eine foerderfaehige Primaerstudie. Wer ihn mechanisch ausschliesst,
    entwertet das Review — und niemand sieht ihn je, weil ``pending()``
    protokollierte IDs ueberspringt.
    """
    papers = [{"paper_id": "p", "year": 2020, "language": "en", "publication_type": value}]
    result = screening_prefilter.apply_filters(papers, FILTERS)
    assert result["excluded"] == []
    assert [p["paper_id"] for p in result["to_screen"]] == ["p"]


def test_unknown_vocabulary_value_is_no_exclusion_reason():
    """Fail-open: ein Wert, den kein Quellvokabular kennt, ist Unwissen."""
    papers = [
        {"paper_id": "p", "year": 2020, "language": "en", "publication_type": "Sonstiger Beitrag"}
    ]
    result = screening_prefilter.apply_filters(papers, FILTERS)
    assert result["excluded"] == []
    assert [p["paper_id"] for p in result["to_screen"]] == ["p"]


def test_multi_valued_publication_types_keep_the_known_article():
    """``publicationTypes`` ist mehrwertig — ein erlaubter Typ in der Liste genuegt."""
    papers = [
        {
            "paper_id": "study",
            "year": 2020,
            "language": "en",
            "publication_type": "Study",
            "publication_types": ["Study", "JournalArticle"],
        },
        {
            "paper_id": "editorial-and-article",
            "year": 2020,
            "language": "en",
            "publication_type": "Editorial",
            "publication_types": ["Editorial", "JournalArticle"],
        },
    ]
    result = screening_prefilter.apply_filters(papers, FILTERS)
    assert result["excluded"] == []
    assert {p["paper_id"] for p in result["to_screen"]} == {"study", "editorial-and-article"}


def test_multi_valued_publication_types_without_allowed_type_still_exclude():
    """Die Gegenprobe: keiner der bekannten Typen passt — dann greift die Regel."""
    papers = [
        {
            "paper_id": "ed",
            "year": 2020,
            "language": "en",
            "publication_type": "Editorial",
            "publication_types": ["Editorial", "News"],
        }
    ]
    result = screening_prefilter.apply_filters(papers, FILTERS)
    assert [p["paper_id"] for p in result["to_screen"]] == []
    assert result["excluded"][0]["criterion"] == "Publikationstyp"


@pytest.mark.parametrize("value", KNOWN_NON_ALLOWED_TYPES)
def test_known_vocabulary_types_outside_the_allowlist_still_exclude(value):
    """Fail-open heisst nicht zahnlos: bekannte Typen schliessen weiter aus."""
    papers = [{"paper_id": "p", "year": 2020, "language": "en", "publication_type": value}]
    result = screening_prefilter.apply_filters(papers, FILTERS)
    assert [row["criterion"] for row in result["excluded"]] == ["Publikationstyp"]


@pytest.mark.parametrize(
    ("value", "canonical"),
    [
        ("journal-article", "journal-article"),  # CrossRef
        ("article", "journal-article"),  # OpenAlex
        ("JournalArticle", "journal-article"),  # Semantic Scholar
        ("conference-paper", "proceedings-article"),  # OpenAlex
        ("Conference", "proceedings-article"),  # Semantic Scholar
        ("BookSection", "book-chapter"),  # Semantic Scholar
        ("LettersAndComments", "letter"),  # Semantic Scholar
    ],
)
def test_publication_type_normalisation_maps_real_vocabulary_values(value, canonical):
    assert screening_prefilter._normalize_publication_type(value) == canonical


@pytest.mark.parametrize("value", [*S2_STUDY_DESIGN_VALUES, "other", "Sonstiger Beitrag", "  "])
def test_publication_type_normalisation_returns_none_where_nothing_is_known(value):
    assert screening_prefilter._normalize_publication_type(value) is None


def test_semantic_scholar_carries_all_publication_types(monkeypatch):
    """``search.py`` darf die mehrwertige S2-Liste nicht auf ``[0]`` verkuerzen."""
    import httpx

    import search

    payload = {
        "data": [
            {
                "paperId": "abc",
                "title": "Governance in DevOps",
                "authors": [{"name": "A. Autorin"}],
                "year": 2020,
                "venue": "IEEE Software",
                "citationCount": 3,
                "externalIds": {"DOI": "10.1/x"},
                "publicationTypes": ["Study", "JournalArticle"],
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(search.httpx, "Client", patched_client)
    monkeypatch.setattr(search.time, "sleep", lambda *a, **k: None)

    entry = search.search_semantic_scholar("devops governance", limit=1)[0]
    assert entry["publication_types"] == ["Study", "JournalArticle"]
    result = screening_prefilter.apply_filters(
        [{**entry, "paper_id": "abc", "language": "en"}], FILTERS
    )
    assert result["excluded"] == []


def test_prefilter_orders_the_remaining_set_by_prescore():
    """Priorisierung: bei knappem Budget kommt das Aussichtsreichste zuerst."""
    papers = [
        {"paper_id": "weak", "year": 2016, "language": "en", "publication_type": "journal-article"},
        {
            "paper_id": "strong",
            "year": 2025,
            "language": "en",
            "publication_type": "journal-article",
            "citations": 200,
            "venue": "IEEE Software",
            "oa_url": "https://example.org/s.pdf",
        },
    ]
    result = screening_prefilter.apply_filters(papers, FILTERS, current_year=2026)
    assert [p["paper_id"] for p in result["to_screen"]] == ["strong", "weak"]


def test_prefilter_order_is_deterministic_on_ties():
    papers = [
        {"paper_id": "b", "year": 2020, "language": "en", "publication_type": "journal-article"},
        {"paper_id": "a", "year": 2020, "language": "en", "publication_type": "journal-article"},
    ]
    result = screening_prefilter.apply_filters(papers, FILTERS, current_year=2026)
    assert [p["paper_id"] for p in result["to_screen"]] == ["a", "b"]


def test_thousand_hits_stay_far_below_hundred_batches():
    """AC2: die Messung auf der dokumentierten Fixture."""
    papers = _corpus()
    assert len(papers) == 1000
    result = screening_prefilter.apply_filters(papers, FILTERS, current_year=2026)
    batches_before = math.ceil(len(papers) / BATCH_SIZE)
    batches_after = math.ceil(len(result["to_screen"]) / BATCH_SIZE)
    assert batches_before == 100
    assert batches_after <= MAX_BATCHES_AFTER, (
        f"{batches_after} Batches sind nicht 'deutlich weniger als hundert'"
    )
    assert batches_after == 14


def test_prefilter_report_states_before_and_after():
    """AC2: die Zahlen vor/nach stehen im Report — sie gehen woertlich ins Issue."""
    papers = _corpus()
    result = screening_prefilter.apply_filters(papers, FILTERS, current_year=2026)
    report = result["report"]
    assert report["n_input"] == 1000
    assert report["batches_before"] == 100
    assert report["batches_after"] == 14
    assert report["n_to_screen"] == 140
    assert report["n_excluded_by_rule"] == 860
    assert report["by_criterion"] == {"Zeitraum": 480, "Sprache": 250, "Publikationstyp": 130}
    assert report["filters_applied"] is True


# ---------------------------------------------------------------------------
# AC3 — jeder Ausschluss mit Grund im Vault
# ---------------------------------------------------------------------------


def test_rule_exclusions_reach_excluded_sources_with_reason(tmp_path, temp_vault_db):
    from academic_vault.db import VaultDB

    papers = [
        {"paper_id": "old", "year": 2001, "language": "en", "publication_type": "journal-article"},
        {"paper_id": "fr", "year": 2020, "language": "fr", "publication_type": "journal-article"},
        {"paper_id": "keep", "year": 2020, "language": "en", "publication_type": "journal-article"},
    ]
    session_dir = tmp_path / "session"
    report = screening_prefilter.prefilter(
        papers, FILTERS, session_dir=session_dir, db_path=temp_vault_db
    )
    assert report["n_excluded_by_rule"] == 2

    rows = {r["paper_id"]: r for r in VaultDB(temp_vault_db).list_excluded_sources()}
    assert set(rows) == {"old", "fr"}
    for paper_id, row in rows.items():
        assert row["reason"] and row["reason"].strip(), paper_id
        assert "screening" in row["reason"]
    assert "Zeitraum" in rows["old"]["reason"]
    assert "Sprache" in rows["fr"]["reason"]


def test_model_exclusions_still_reach_the_vault(tmp_path, temp_vault_db):
    """Regression fuer den Bestandspfad — der Modelldurchlauf schreibt wie bisher."""
    from academic_vault.db import VaultDB

    session_dir = tmp_path / "session"
    screening_ledger.record_decision(
        session_dir,
        {"paper_id": "m1", "decision": "exclude", "reason": "off-topic"},
        agent="screening-judge#1",
        db_path=temp_vault_db,
    )
    rows = VaultDB(temp_vault_db).list_excluded_sources()
    assert [r["paper_id"] for r in rows] == ["m1"]
    assert "off-topic" in rows[0]["reason"]


def test_rule_rows_are_marked_in_the_ledger(tmp_path):
    papers = [{"paper_id": "old", "year": 2001, "language": "en"}]
    session_dir = tmp_path / "session"
    screening_prefilter.prefilter(papers, FILTERS, session_dir=session_dir)
    rows = screening_ledger.read_ledger(session_dir)
    assert len(rows) == 1
    assert rows[0]["decided_by"] == "rule"
    assert rows[0]["decision"] == "exclude"
    assert rows[0]["stage"] == "screening"
    assert rows[0]["round"] == 1


def test_record_decision_keeps_agent_as_default_author(tmp_path):
    session_dir = tmp_path / "session"
    entry = screening_ledger.record_decision(
        session_dir, {"paper_id": "a", "decision": "include", "reason": "passt"}
    )
    assert entry["decided_by"] == "agent"


def test_rule_rows_stay_out_of_kappa_and_dissent(tmp_path):
    """Risiko 1: mechanische Zeilen duerfen die Uebereinstimmungsmessung nicht faelschen."""
    session_dir = tmp_path / "session"
    screening_prefilter.prefilter(
        [{"paper_id": "old", "year": 2001, "language": "en"}], FILTERS, session_dir=session_dir
    )
    for round_no, decision in ((1, "include"), (2, "exclude")):
        screening_ledger.record_decision(
            session_dir,
            {"paper_id": "judged", "decision": decision, "reason": "…"},
            agent=f"screening-judge#{round_no}",
            round=round_no,
        )
    agreement = screening_ledger.compute_agreement(session_dir)
    assert agreement["n"] == 1, "die Regel-Zeile darf kein Paar bilden"
    assert [c["paper_id"] for c in screening_ledger.dissent_cases(session_dir)] == ["judged"]


def test_merge_double_counts_rule_exclusions(tmp_path):
    """AC4 bei Doppel-Screening: die mechanischen Ausschluesse zaehlen mit."""
    session_dir = tmp_path / "session"
    screening_prefilter.prefilter(
        [{"paper_id": "old", "year": 2001, "language": "en"}], FILTERS, session_dir=session_dir
    )
    for round_no in (1, 2):
        screening_ledger.record_decision(
            session_dir,
            {"paper_id": "judged", "decision": "include", "reason": "passt"},
            agent=f"screening-judge#{round_no}",
            round=round_no,
        )
    buckets = screening_ledger.merge_double(session_dir)
    assert buckets["exclude"] == ["old"]
    assert buckets["include"] == ["judged"]
    counters = screening_ledger.to_prisma_counters_double(session_dir)
    assert counters["n_excluded_screening"] == 1
    assert counters["n_after_dedup"] == 2


# ---------------------------------------------------------------------------
# AC4 — PRISMA allein aus dem Protokoll
# ---------------------------------------------------------------------------


def test_prisma_counters_come_from_the_ledger_alone(tmp_path):
    session_dir = tmp_path / "session"
    screening_prefilter.prefilter(
        [
            {"paper_id": "old", "year": 2001, "language": "en"},
            {"paper_id": "fr", "year": 2020, "language": "fr"},
            {"paper_id": "keep1", "year": 2020, "language": "en"},
            {"paper_id": "keep2", "year": 2021, "language": "en"},
            {"paper_id": "keep3", "year": 2022, "language": "en"},
        ],
        FILTERS,
        session_dir=session_dir,
    )
    for paper_id, decision in (("keep1", "include"), ("keep2", "exclude"), ("keep3", "unclear")):
        screening_ledger.record_decision(
            session_dir,
            {"paper_id": paper_id, "decision": decision, "reason": "…"},
            agent="screening-judge#1",
        )
    counters = screening_ledger.to_prisma_counters(session_dir)
    assert counters["n_excluded_screening"] == 3  # 2 mechanisch + 1 vom Modell
    assert counters["n_included"] == 1
    assert counters["n_unclear_screening"] == 1
    assert (
        counters["n_after_dedup"]
        == counters["n_excluded_screening"]
        + counters["n_included"]
        + counters["n_unclear_screening"]
    )


def test_search_md_prefers_ledger_counters():
    """AC4: die Handzaehlung ist in commands/search.md nur noch der Fallback."""
    counters_section = _section(SEARCH_MD.read_text(encoding="utf-8"), "### Schritt 12:")
    ledger_pos = counters_section.find("screening_ledger.py")
    manual_pos = counters_section.find("build_prisma_counters")
    assert ledger_pos != -1 and manual_pos != -1
    assert ledger_pos < manual_pos, "der Ledger-Weg muss vor der Handzaehlung stehen"
    assert "Fallback" in counters_section


def test_search_md_has_a_prefilter_step_before_the_relevance_scoring():
    text = SEARCH_MD.read_text(encoding="utf-8")
    assert "screening_prefilter.py" in text
    assert text.index("screening_prefilter.py") < text.index("relevance-scorer`-Agent in Batches")


def test_search_md_no_longer_forbids_a_special_path():
    text = SEARCH_MD.read_text(encoding="utf-8")
    assert "es gibt keinen Sonderpfad" not in text


# ---------------------------------------------------------------------------
# AC5 — kein Modellaufruf fuer einen eindeutigen Fehltreffer
# ---------------------------------------------------------------------------


def test_prefiltered_ids_never_appear_in_pending(tmp_path):
    session_dir = tmp_path / "session"
    papers = [
        {"paper_id": "old", "year": 2001, "language": "en"},
        {"paper_id": "keep", "year": 2020, "language": "en"},
    ]
    screening_prefilter.prefilter(papers, FILTERS, session_dir=session_dir)
    assert screening_ledger.pending(["old", "keep"], session_dir) == ["keep"]


def test_planned_waves_contain_no_rule_excluded_id(tmp_path):
    session_dir = tmp_path / "session"
    papers = _corpus()
    result = screening_prefilter.prefilter(papers, FILTERS, session_dir=session_dir)
    all_ids = [p["paper_id"] for p in papers]
    todo = screening_ledger.pending(all_ids, session_dir)
    assert len(todo) == result["n_to_screen"]
    excluded = {row["paper_id"] for row in screening_ledger.read_ledger(session_dir)}
    waves = screening_ledger.plan_waves(todo, 4)
    assert all(pid not in excluded for wave in waves for pid in wave)


def test_without_filter_block_pending_is_unchanged(tmp_path):
    session_dir = tmp_path / "session"
    papers = [{"paper_id": "old", "year": 2001, "language": "fr"}]
    screening_prefilter.prefilter(papers, {}, session_dir=session_dir)
    assert screening_ledger.pending(["old"], session_dir) == ["old"]


# ---------------------------------------------------------------------------
# Schalter, ID-Ableitung, CLI
# ---------------------------------------------------------------------------


def test_prefilter_switch_defaults_to_on():
    assert screening_prefilter.resolve_prefilter() is True


def test_prefilter_switch_precedence(monkeypatch, tmp_path):
    config = tmp_path / "parallel_agents.json"
    config.write_text(json.dumps({"screening_prefilter": False}), encoding="utf-8")
    assert screening_prefilter.resolve_prefilter(config_path=config) is False
    monkeypatch.setenv("ACADEMIC_RESEARCH_SCREENING_PREFILTER", "true")
    assert screening_prefilter.resolve_prefilter(config_path=config) is True
    assert screening_prefilter.resolve_prefilter(False, config_path=config) is False


def test_config_file_declares_the_switch():
    data = json.loads((REPO_ROOT / "config" / "parallel_agents.json").read_text(encoding="utf-8"))
    assert data["screening_prefilter"] is True


@pytest.mark.parametrize(
    ("paper", "expected"),
    [
        ({"paper_id": "explicit", "doi": "10.1/x"}, "explicit"),
        ({"doi": "10.1000/J.Foo-1"}, "10.1000_j.foo-1"),
        ({"url": "https://example.org/a b"}, "https___example.org_a_b"),
        ({"title": "Ein Titel!"}, "ein_titel_"),
    ],
)
def test_derive_paper_id_is_stable(paper, expected):
    assert screening_prefilter.derive_paper_id(paper) == expected


def test_derive_paper_id_needs_something_to_work_with():
    with pytest.raises(ValueError):
        screening_prefilter.derive_paper_id({})


def test_prefilter_cli_writes_to_screen_and_report(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    papers_path = session_dir / "ranked.json"
    papers_path.write_text(
        json.dumps(
            [
                {"paper_id": "old", "year": 2001, "language": "en"},
                {"paper_id": "keep", "year": 2020, "language": "en"},
            ]
        ),
        encoding="utf-8",
    )
    context = tmp_path / "academic_context.md"
    context.write_text(CONTEXT_MD, encoding="utf-8")
    out = subprocess.run(
        [
            sys.executable,
            str(SCREENING_SCRIPTS / "screening_prefilter.py"),
            "prefilter",
            "--session-dir",
            str(session_dir),
            "--papers",
            str(papers_path),
            "--context",
            str(context),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(out.stdout)
    assert report["n_to_screen"] == 1
    to_screen = json.loads((session_dir / "to_screen.json").read_text(encoding="utf-8"))
    assert [p["paper_id"] for p in to_screen] == ["keep"]
    saved = json.loads((session_dir / "prefilter_report.json").read_text(encoding="utf-8"))
    assert saved == report


def test_prefilter_cli_off_switch_is_a_no_op(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    papers_path = session_dir / "ranked.json"
    papers_path.write_text(
        json.dumps([{"paper_id": "old", "year": 2001, "language": "fr"}]), encoding="utf-8"
    )
    context = tmp_path / "academic_context.md"
    context.write_text(CONTEXT_MD, encoding="utf-8")
    out = subprocess.run(
        [
            sys.executable,
            str(SCREENING_SCRIPTS / "screening_prefilter.py"),
            "prefilter",
            "--session-dir",
            str(session_dir),
            "--papers",
            str(papers_path),
            "--context",
            str(context),
            "--no-prefilter",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(out.stdout)
    assert report["n_excluded_by_rule"] == 0
    assert report["filters_applied"] is False
    assert screening_ledger.read_ledger(session_dir) == []


# ---------------------------------------------------------------------------
# Filterblock-Vorlage in den Skills
# ---------------------------------------------------------------------------


def test_render_protocol_emits_the_filter_block(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "skills" / "preregistration" / "scripts"))
    import render_protocol

    text = render_protocol.aktualisiere_academic_context(
        "# Kontext\n",
        suchstrategie="sieben Module",
        einschlusskriterien=["ab 2015"],
        ausschlusskriterien=["Editorials"],
        screening_filters=FILTERS,
    )
    assert "```screening_filters" in text
    filters = screening_prefilter.load_filters(text)
    assert filters == FILTERS


def test_render_protocol_without_filters_stays_as_before():
    sys.path.insert(0, str(REPO_ROOT / "skills" / "preregistration" / "scripts"))
    import render_protocol

    text = render_protocol.aktualisiere_academic_context(
        "# Kontext\n",
        suchstrategie="sieben Module",
        einschlusskriterien=["ab 2015"],
        ausschlusskriterien=["Editorials"],
    )
    assert "screening_filters" not in text


def test_skill_documents_the_prefilter():
    skill = (REPO_ROOT / "skills" / "parallel-screening" / "SKILL.md").read_text(encoding="utf-8")
    assert "screening_prefilter" in skill
    reference = REPO_ROOT / "skills" / "parallel-screening" / "references" / "prefilter.md"
    assert reference.is_file()
    assert "fail-open" in reference.read_text(encoding="utf-8").lower()


def test_prisma_flow_wording_covers_mechanical_exclusions():
    text = (REPO_ROOT / "skills" / "prisma-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert "relevance-scorer < 0.5" not in text, (
        "die Zeile stimmt nach #892 nicht mehr — mechanische Ausschluesse zaehlen mit"
    )


# ---------------------------------------------------------------------------
# Fixture-Konstruktionsregel (gegen Test-Gaming)
# ---------------------------------------------------------------------------


def test_fixture_topics_carry_no_signal():
    """Regel 1: der Titel trennt die Gruppen nicht."""
    papers = _corpus()
    result = screening_prefilter.apply_filters(papers, FILTERS, current_year=2026)
    kept = {p["title"].rsplit(" (", 1)[0] for p in result["to_screen"]}
    dropped_ids = {row["paper_id"] for row in result["excluded"]}
    dropped = {p["title"].rsplit(" (", 1)[0] for p in papers if p["paper_id"] in dropped_ids}
    assert kept == dropped


def test_fixture_has_a_missing_metadata_group():
    """Regel 2: 60 Datensaetze mit genau einer Luecke, alle bleiben drin."""
    papers = _corpus()
    incomplete = [
        p for p in papers if any(p.get(k) is None for k in ("year", "language", "publication_type"))
    ]
    assert len(incomplete) == 60
    result = screening_prefilter.apply_filters(papers, FILTERS, current_year=2026)
    kept_ids = {p["paper_id"] for p in result["to_screen"]}
    assert {p["paper_id"] for p in incomplete} <= kept_ids


def test_fixture_records_violate_at_most_one_criterion():
    """Regel 3: die Aufschluesselung im Report ist nicht prueffolgeabhaengig."""
    papers = _corpus()
    for paper in papers:
        violations = 0
        if paper.get("year") is not None and paper["year"] < FILTERS["year_min"]:
            violations += 1
        if paper.get("language") is not None and paper["language"] not in FILTERS["languages"]:
            violations += 1
        if (
            paper.get("publication_type") is not None
            and paper["publication_type"] not in FILTERS["publication_types"]
        ):
            violations += 1
        assert violations <= 1, paper["paper_id"]
