"""Tests fuer den NLI-Batch-Vorfilter vor dem quote-fidelity-auditor (Issue #592).

Deckt die Akzeptanzkriterien aus der Issue:

  AC1  Vorfilter laeuft ohne ANTHROPIC_API_KEY/Netz (kein solcher Aufruf in
       diesen Tests -- der Scorer wird ausschliesslich gestubbt).
  AC2  Ein Weg, ALLE Zitate eines Kapitels in einem Durchgang zu pruefen --
       nicht nur die mit Drift-Warnung.
  AC3  Verdaechtig -> unveraendert an den Auditor; treu -> Skip mit
       Report-Marker "vorgefiltert, nicht inhaltlich geprueft".
  AC4  Abschaltbar, Default AUS, deaktiviert = exakt heutiges Verhalten
       (kein Quote wird uebersprungen).

Der echte Modell-Download/-Lauf ist NICHT Teil dieser Datei (siehe
tests/evals/test_nli_prefilter_evals.py fuer die strukturellen Checks und
evals/524-nli-prefilter/run_real_validation.py fuer den Live-Lauf) -- hier
wird ausschliesslich mit einem gestubbten Scorer getestet.
"""

from __future__ import annotations

import json

import pytest
from academic_vault.nli_prefilter import (
    SKIP_MARKER,
    build_premise,
    claim_sentence_for_span,
    extract_quote_spans,
    resolve_nli_prefilter_enabled,
    run_batch_prefilter,
    scan_chapter_quotes,
)


class StubScorer:
    """Deterministischer Scorer: verdict wird per Dictionary ueber die
    Hypothesis (chapter_claim) gesteuert -- kein Modell-Laden, kein Netz."""

    name = "stub"

    def __init__(self, verdict_by_hypothesis: dict[str, str]) -> None:
        self._verdicts = verdict_by_hypothesis

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        verdict = self._verdicts.get(hypothesis, "verzerrend")
        raw = 0.9 if verdict == "faithful" else 0.1
        return verdict, raw


# ---------------------------------------------------------------------------
# AC4 -- Toggle-Praezedenz und Default
# ---------------------------------------------------------------------------


def test_resolve_prefilter_enabled_default_is_false(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_RESEARCH_NLI_PREFILTER", raising=False)
    missing_config = tmp_path / "does-not-exist.json"
    assert resolve_nli_prefilter_enabled(config_path=missing_config) is False


def test_resolve_prefilter_enabled_explicit_wins_over_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_RESEARCH_NLI_PREFILTER", "0")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"nli_prefilter_enabled": False}), encoding="utf-8")
    assert resolve_nli_prefilter_enabled(True, config_path=config) is True


def test_resolve_prefilter_enabled_env_wins_over_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ACADEMIC_RESEARCH_NLI_PREFILTER", "1")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"nli_prefilter_enabled": False}), encoding="utf-8")
    assert resolve_nli_prefilter_enabled(config_path=config) is True


def test_resolve_prefilter_enabled_reads_config_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ACADEMIC_RESEARCH_NLI_PREFILTER", raising=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"nli_prefilter_enabled": True}), encoding="utf-8")
    assert resolve_nli_prefilter_enabled(config_path=config) is True


def test_repo_default_config_has_prefilter_disabled():
    """AC: Auslieferungsstand ist AUS."""
    from academic_vault.nli_prefilter import DEFAULT_CONFIG_PATH

    data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert data["nli_prefilter_enabled"] is False


# ---------------------------------------------------------------------------
# AC3 + AC4 -- run_batch_prefilter
# ---------------------------------------------------------------------------


def _items(n: int = 3) -> list[dict]:
    return [
        {
            "quote_id": f"q{i}",
            "chapter_claim": f"Behauptung {i}",
            "paper_id": "paper-1",
            "context_before": "vor",
            "verbatim": f"verbatim {i}",
            "context_after": "nach",
        }
        for i in range(n)
    ]


def test_batch_prefilter_disabled_forwards_everything_unfiltered():
    """AC4: bei enabled=False erreichen ALLE Items ungefiltert die
    Weiterleitung -- kein Skip, exakt wie ohne Vorfilter."""
    items = _items(3)
    result = run_batch_prefilter(items, enabled=False)

    assert result["enabled"] is False
    assert result["skipped"] == []
    assert len(result["forwarded"]) == 3
    forwarded_ids = {f["quote_id"] for f in result["forwarded"]}
    assert forwarded_ids == {"q0", "q1", "q2"}
    # Unveraendertes Input-Format: quote_id/chapter_claim/paper_id, sonst nichts.
    for item in result["forwarded"]:
        assert set(item.keys()) == {"quote_id", "chapter_claim", "paper_id"}


def test_batch_prefilter_enabled_forwards_only_suspicious_unchanged():
    """AC3: verdaechtig -> unveraendertes {quote_id, chapter_claim, paper_id}
    an den Auditor; treu -> Skip mit Report-Marker."""
    items = _items(3)
    scorer = StubScorer(
        {
            "Behauptung 0": "faithful",
            "Behauptung 1": "verzerrend",
            "Behauptung 2": "faithful",
        }
    )
    result = run_batch_prefilter(items, scorer=scorer, enabled=True)

    assert result["enabled"] is True
    assert len(result["forwarded"]) == 1
    assert result["forwarded"][0] == {
        "quote_id": "q1",
        "chapter_claim": "Behauptung 1",
        "paper_id": "paper-1",
    }
    assert len(result["skipped"]) == 2
    for skipped in result["skipped"]:
        assert skipped["report"] == SKIP_MARKER
        assert skipped["verdict"] == "faithful"
    skipped_ids = {s["quote_id"] for s in result["skipped"]}
    assert skipped_ids == {"q0", "q2"}


def test_batch_prefilter_report_never_calls_a_skipped_item_geprueft():
    """Report-Marker darf nicht 'geprueft' suggerieren (Issue-AC-Wortlaut)."""
    items = _items(1)
    scorer = StubScorer({"Behauptung 0": "faithful"})
    result = run_batch_prefilter(items, scorer=scorer, enabled=True)
    assert result["skipped"][0]["report"] == "vorgefiltert, nicht inhaltlich geprueft"


def test_batch_prefilter_empty_items_returns_empty_lists():
    result = run_batch_prefilter([], enabled=True, scorer=StubScorer({}))
    assert result["forwarded"] == []
    assert result["skipped"] == []


# ---------------------------------------------------------------------------
# build_premise
# ---------------------------------------------------------------------------


def test_build_premise_joins_context_and_verbatim():
    assert build_premise("before", "verbatim", "after") == "before verbatim after"


def test_build_premise_handles_missing_context():
    assert build_premise(None, "verbatim", None) == "verbatim"
    assert build_premise("", "verbatim", "") == "verbatim"


# ---------------------------------------------------------------------------
# AC2 -- Vollkapitel-Scan (extract_quote_spans, claim_sentence_for_span, scan_chapter_quotes)
# ---------------------------------------------------------------------------


def test_extract_quote_spans_finds_spans_anywhere_in_a_long_document():
    """Kein Aenderungsfenster-Limit (Unterschied zu claim-drift-guard.mjs)."""
    filler = "Fuellsatz ohne Zitat. " * 200
    content = (
        filler
        + '"Dies ist ein hinreichend langes woertliches Zitat fuer den Test." '
        + filler
        + "„Und ein zweites, ebenfalls hinreichend langes deutsches Zitat.“"
    )
    spans = extract_quote_spans(content)
    assert len(spans) == 2
    assert "hinreichend langes woertliches" in spans[0]["text"]
    assert "zweites" in spans[1]["text"]


def test_extract_quote_spans_ignores_short_fragments():
    content = '"zu kurz" und "dieses hier ist definitiv lang genug fuer die Mindestlaenge"'
    spans = extract_quote_spans(content, min_len=20)
    assert len(spans) == 1


def test_claim_sentence_for_span_returns_enclosing_sentence():
    content = (
        "Erster Satz ohne Belang. "
        'Die Studie zeigt laut Quelle "ein deutliches Ergebnis in der Stichprobe" fuer die These. '
        "Ein weiterer Satz danach."
    )
    spans = extract_quote_spans(content, min_len=5)
    assert len(spans) == 1
    claim = claim_sentence_for_span(content, spans[0])
    assert "Die Studie zeigt" in claim
    assert "Erster Satz" not in claim
    assert "Ein weiterer Satz danach" not in claim


def test_scan_chapter_quotes_finds_all_vault_quotes_not_just_drifted_one(temp_vault_db):
    """AC2: alle drei im Kapitel zitierten UND im Vault vorhandenen Zitate
    werden gefunden -- nicht nur eines mit simulierter Drift-Warnung."""
    from academic_vault.server import add_paper, add_quote

    add_paper(
        db_path=temp_vault_db,
        paper_id="paper-592",
        csl_json=json.dumps({"title": "Test Paper 592", "type": "article-journal"}),
    )
    verbatims = [
        "Der erste Befund zeigt einen deutlichen Zusammenhang zwischen beiden Variablen.",
        "Der zweite Befund widerspricht dieser Interpretation in wesentlichen Teilen.",
        "Der dritte Befund bleibt in der Stichprobe statistisch nicht signifikant.",
    ]
    quote_ids = [
        add_quote(
            db_path=temp_vault_db,
            paper_id="paper-592",
            verbatim=v,
            extraction_method="manual",
        )
        for v in verbatims
    ]

    chapter = (
        "Einleitung ohne Zitat. "
        f'Wie Mueller (2021) schreibt: "{verbatims[0]}" -- das stuetzt These A. '
        "Ein Absatz ohne jeden Beleg dazwischen, nur Flieesstext ueber die Methodik. "
        f'Dagegen haelt Schmidt (2019) fest: "{verbatims[1]}" -- ein Gegenbefund. '
        "Noch mehr Fliesstext zur Einordnung, der nichts zitiert. "
        f'Zuletzt bleibt unklar: "{verbatims[2]}" -- offene Frage fuer Kapitel 4. '
        'Ein nicht im Vault vorhandenes Fantasiezitat: "Dieses Zitat existiert nirgendwo in der Datenbank ueberhaupt."'
    )

    items = scan_chapter_quotes(chapter, temp_vault_db)

    found_ids = {item["quote_id"] for item in items}
    assert found_ids == set(quote_ids), (
        "Alle drei Vault-Zitate muessen gefunden werden, nicht nur eines mit Drift-Warnung."
    )
    for item in items:
        assert item["paper_id"] == "paper-592"
        assert item["chapter_claim"].strip()

    # Das erfundene, nicht im Vault vorhandene Zitat darf NICHT auftauchen.
    all_verbatims = {item["verbatim"] for item in items}
    assert "Dieses Zitat existiert nirgendwo in der Datenbank ueberhaupt." not in all_verbatims


def test_scan_chapter_quotes_then_batch_prefilter_end_to_end(temp_vault_db):
    """Kombiniert AC2 (Scan) mit AC3/AC4 (Batch) -- der volle Pfad eines
    Kapitel-Durchgangs mit gestubbtem Scorer."""
    from academic_vault.server import add_paper, add_quote

    add_paper(
        db_path=temp_vault_db,
        paper_id="paper-592b",
        csl_json=json.dumps({"title": "Test Paper 592b", "type": "article-journal"}),
    )
    verbatim = "Dieser Befund war in der Replikationsstudie durchgehend reproduzierbar."
    quote_id = add_quote(
        db_path=temp_vault_db,
        paper_id="paper-592b",
        verbatim=verbatim,
        extraction_method="manual",
    )
    chapter = f'Text davor. "{verbatim}" -- das belegt die Kernthese der Arbeit. Text danach.'

    items = scan_chapter_quotes(chapter, temp_vault_db)
    assert len(items) == 1

    scorer = StubScorer({items[0]["chapter_claim"]: "verzerrend"})
    result = run_batch_prefilter(items, scorer=scorer, enabled=True)

    assert len(result["forwarded"]) == 1
    assert result["forwarded"][0]["quote_id"] == quote_id


def test_scan_chapter_quotes_ignores_non_vault_spans(temp_vault_db):
    """Keine Fabrikation: ein Zitat, das nicht im Vault steht, wird
    uebersprungen statt geraten."""
    from academic_vault.server import add_paper

    add_paper(
        db_path=temp_vault_db,
        paper_id="paper-592c",
        csl_json=json.dumps({"title": "Test Paper 592c", "type": "article-journal"}),
    )
    chapter = (
        '"Ein Zitat, das definitiv nicht im Vault existiert und dort niemals hinterlegt wurde."'
    )
    items = scan_chapter_quotes(chapter, temp_vault_db)
    assert items == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
