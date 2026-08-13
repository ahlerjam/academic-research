"""Regressionstests fuer die NLI-Zitatscan-Kalibrierung (Issue #899).

Am 12.08.2026 meldete der Scan 22 von 24 Zitaten als verdaechtig -- praktisch
alle davon Fehlalarme. Drei Ursachen, alle in ``academic_vault/nli_prefilter.py``:

  AC1  Zuschreibungssaetze ("X berichtet, dass '...'") werden nicht mehr
       allein wegen des NLI-Urteils gemeldet -- nur, wenn der Rahmensatz
       einen lexikalischen Negationsmarker traegt.
  AC2  Ein tatsaechlicher Widerspruch im Rahmensatz wird weiterhin gemeldet.
  AC3  Ein Zitat mit eigenen Satzzeichen (Abkuerzungen, Ziffern, mehrere
       Saetze) wird gegen den Satz geprueft, der die GESAMTE Spanne
       umschliesst -- oder gar nicht (nie ein falscher Nachbarsatz).
  AC4  Bestehende #592/#717-Suiten bleiben unveraendert gruen (separat
       ausgefuehrt, hier nur als Cross-Check auf Kompatibilitaet).

Kein Modell-Download, kein Netz: der Scorer wird ausschliesslich gestubbt
(Muster: ``tests/test_issue_717_nli_quote_scan.py::StubScorer``).
"""

from __future__ import annotations

from academic_vault.nli_prefilter import (
    claim_sentence_for_span,
    extract_quote_spans,
    prefilter_quote,
    run_batch_prefilter,
    scan_chapter_quotes,
)


class StubScorer:
    """Deterministischer Scorer: verdict wird per Dictionary ueber die
    Hypothesis (chapter_claim) gesteuert -- kein Modell-Laden, kein Netz."""

    name = "stub"

    def __init__(self, verdict_by_hypothesis: dict[str, str] | None = None) -> None:
        self._verdicts = verdict_by_hypothesis or {}
        self.calls = 0

    def predict(self, premise: str, hypothesis: str) -> tuple[str, float]:
        self.calls += 1
        verdict = self._verdicts.get(hypothesis, "verzerrend")
        raw = 0.9 if verdict == "faithful" else 0.1
        return verdict, raw


# ---------------------------------------------------------------------------
# AC1 -- Zuschreibungssatz ohne Negationsmarker wird nicht gemeldet
# ---------------------------------------------------------------------------


def test_attribution_sentence_without_negation_marker_is_not_suspicious():
    """Direktzitat mit Rahmensatz: der Kapitelsatz enthaelt das Zitat selbst
    in Anfuehrungszeichen -- das ist Zuschreibung, keine Folgerung. Der
    Scorer liefert (absichtlich falsch fuer den Test) 'verzerrend', trotzdem
    darf das Item nicht gemeldet werden."""
    verbatim = "our debate approach outperforms single model baselines"
    chapter_claim = f'Du et al. (2023) report that "{verbatim}" for the given benchmark.'
    scorer = StubScorer({chapter_claim: "verzerrend"})

    result = prefilter_quote(
        scorer,
        quote_id="q1",
        chapter_claim=chapter_claim,
        paper_id="paper-1",
        context_before="Context before.",
        verbatim=verbatim,
        context_after="Context after.",
    )

    assert result["suspicious"] is False
    assert scorer.calls == 0, "Zuschreibung ohne Negationsmarker braucht keinen Scorer-Aufruf."


def test_attribution_sentence_without_negation_marker_not_in_batch_suspicious():
    """Dieselbe Zusicherung ueber den Batch-Pfad (run_batch_prefilter)."""
    verbatim = "our debate approach outperforms single model baselines"
    chapter_claim = f'Du et al. (2023) report that "{verbatim}" for the given benchmark.'
    items = [
        {
            "quote_id": "q1",
            "chapter_claim": chapter_claim,
            "paper_id": "paper-1",
            "context_before": "Context before.",
            "verbatim": verbatim,
            "context_after": "Context after.",
        }
    ]
    scorer = StubScorer({chapter_claim: "verzerrend"})
    result = run_batch_prefilter(items, scorer=scorer, enabled=True)

    assert result["suspicious"] == []
    assert len(result["forwarded"]) == 1, "Detektor-Modus: forwarded verliert kein Item."


# ---------------------------------------------------------------------------
# AC2 -- Widerspruch im Rahmensatz wird weiterhin gemeldet
# ---------------------------------------------------------------------------


def test_attribution_sentence_with_negation_marker_still_checked_and_reported():
    """Traegt der Rahmensatz einen Negationsmarker (hier: 'bestreitet'), gilt
    er nicht mehr als reine Zuschreibung -- die NLI-Pruefung greift normal,
    ein 'verzerrend'-Urteil wird gemeldet."""
    verbatim = "our debate approach outperforms single model baselines"
    chapter_claim = f'Du et al. (2023) bestreitet jedoch, dass "{verbatim}" tatsaechlich zutrifft.'
    scorer = StubScorer({chapter_claim: "verzerrend"})

    result = prefilter_quote(
        scorer,
        quote_id="q1",
        chapter_claim=chapter_claim,
        paper_id="paper-1",
        context_before="Context before.",
        verbatim=verbatim,
        context_after="Context after.",
    )

    assert scorer.calls == 1, "Mit Negationsmarker greift die normale NLI-Pruefung."
    assert result["suspicious"] is True


def test_negation_marker_alone_does_not_force_suspicious_without_scorer_verdict():
    """Ein Negationsmarker allein ist kein Befund -- nur wenn der Scorer
    tatsaechlich 'verzerrend' urteilt."""
    verbatim = "our debate approach outperforms single model baselines"
    chapter_claim = f'Du et al. (2023) bestreitet jedoch, dass "{verbatim}" tatsaechlich zutrifft.'
    scorer = StubScorer({chapter_claim: "faithful"})

    result = prefilter_quote(
        scorer,
        quote_id="q1",
        chapter_claim=chapter_claim,
        paper_id="paper-1",
        context_before="Context before.",
        verbatim=verbatim,
        context_after="Context after.",
    )

    assert result["suspicious"] is False


# ---------------------------------------------------------------------------
# AC3 -- Satzzuordnung gegen Zitate mit eigenen Satzzeichen
# ---------------------------------------------------------------------------


def test_claim_sentence_for_span_returns_full_span_even_with_internal_period():
    """Zitat enthaelt selbst einen Satzschluss-Punkt gefolgt von einem
    Grossbuchstaben (mehrere Saetze im Zitat) -- die Satzzuordnung darf
    nicht mitten im Zitat abbrechen, sondern muss den Satz liefern, der die
    GESAMTE Spanne umschliesst."""
    content = (
        "Ein Satz davor ohne Belang. "
        'Die Studie zeigt "der Effekt war eindeutig. Dies galt fuer alle Durchlaeufe" '
        "fuer die zentrale These. Ein Satz danach."
    )
    spans = extract_quote_spans(content, min_len=5)
    assert len(spans) == 1
    span = spans[0]

    claim = claim_sentence_for_span(content, span)

    assert claim is not None, "Eine eindeutige umschliessende Satzgrenze existiert hier."
    assert "Die Studie zeigt" in claim
    assert "fuer die zentrale These" in claim
    assert "Ein Satz davor" not in claim
    assert "Ein Satz danach" not in claim


def test_claim_sentence_for_span_regression_smit_tuning_heading_case():
    """Regressionsfall des Issues: ein Zitat direkt nach einer Markdown-
    Ueberschrift darf nicht gegen den Satz VOR der Ueberschrift geprueft
    werden (der frueher fehlerhaft als umschliessend erkannt wurde, weil
    Ueberschriften keine Satzgrenze fuer _SENTENCE_SPLIT sind)."""
    content = (
        "The corpus offers indirect support for how much this matters. The benchmark\n"
        "distribution is concentrated across several standard sets, which makes results\n"
        "difficult to place alongside the rest.\n"
        "\n"
        "### 6.4 Asymmetric tuning\n"
        "\n"
        'Smit et al. (2023) observe that "when performing hyperparameter tuning, '
        'several MAD systems perform better", concluding that the protocols may not be\n'
        "inherently worse but more sensitive to configuration.\n"
        "\n"
        "This cuts both ways, and that is what makes it interesting."
    )
    spans = extract_quote_spans(content, min_len=5)
    assert len(spans) == 1
    span = spans[0]

    claim = claim_sentence_for_span(content, span)

    assert claim is not None
    assert "Smit et al." in claim, "Der richtige Satz beginnt bei 'Smit et al.'"
    assert "benchmark" not in claim.lower(), (
        "Der Satz VOR der Ueberschrift darf nicht mehr zugeordnet werden "
        "(Regressionsfall des Issues: Smit-Tuning-Zitat gegen Benchmark-Verteilungssatz)."
    )


def test_claim_sentence_for_span_returns_full_text_when_it_is_the_only_bound():
    """Steht das Zitat allein im gesamten Text (keine weitere Struktur- oder
    Satzgrenze), bildet der gesamte Text den einzigen Bound und umschliesst
    die Spanne vollstaendig -- ein gueltiger Fall, kein None-Fall."""
    content = '"Ein Zitat ohne jede erkennbare Satzgrenze drumherum"'
    spans = extract_quote_spans(content, min_len=5)
    assert len(spans) == 1
    claim = claim_sentence_for_span(content, spans[0])
    assert claim is not None
    assert "Ein Zitat ohne jede erkennbare Satzgrenze" in claim


def test_claim_sentence_for_span_returns_none_when_span_crosses_a_structural_boundary():
    """Kein Guess-Pfad mehr: traegt das Zitat selbst einen Absatzumbruch (eine
    Leerzeile INNERHALB der Spanne), gibt es keinen ``_non_structural_runs``-
    Block, der Anfang UND Ende der Spanne vollstaendig umschliesst -- die
    Funktion liefert None statt eines Zeichenfenster-Rateversuchs."""
    content = '"Zitat mit\n\ninnerem Absatzumbruch, das keine Satzgrenze eindeutig umschliesst"'
    spans = extract_quote_spans(content, min_len=5)
    assert len(spans) == 1
    assert claim_sentence_for_span(content, spans[0]) is None


def test_ambiguous_claim_item_is_forwarded_but_never_reported_suspicious():
    """scan_chapter_quotes: ein Item ohne eindeutige Satzzuordnung bleibt im
    Pruefpfad (wird an den Auditor weitergereicht), taucht aber nie in
    ``suspicious`` auf -- kein Scorer-Aufruf noetig."""
    verbatim = (
        "Zitat mit e.g. einer Abkuerzung mitten drin, das die Satzgrenzen "
        "durcheinanderbringt und keinen sauberen umschliessenden Satz mehr hat"
    )
    chapter_claim_ambiguous_marker = True
    items = [
        {
            "quote_id": "q-ambiguous",
            "chapter_claim": "irrelevanter Fallback-Text fuers Forwarding.",
            "paper_id": "paper-1",
            "context_before": "vor",
            "verbatim": verbatim,
            "context_after": "nach",
            "claim_ambiguous": chapter_claim_ambiguous_marker,
        }
    ]
    scorer = StubScorer({})  # wuerde alles als 'verzerrend' werten, wenn aufgerufen
    result = run_batch_prefilter(items, scorer=scorer, enabled=True)

    assert len(result["forwarded"]) == 1
    assert result["forwarded"][0]["quote_id"] == "q-ambiguous"
    assert result["suspicious"] == []
    assert scorer.calls == 0


# ---------------------------------------------------------------------------
# scan_chapter_quotes -- Integration: unaufloesbare Zuordnung erzeugt
# claim_ambiguous statt eines geratenen Kapitelsatzes
# ---------------------------------------------------------------------------


def test_scan_chapter_quotes_marks_claim_ambiguous_for_unresolvable_span(temp_vault_db):
    """Ein Zitat, dessen Spanne selbst einen Absatzumbruch traegt, hat keine
    umschliessende ``_non_structural_runs``-Grenze -- ``claim_ambiguous`` muss
    ``True`` sein, nicht bloss als Key existieren (P1-Fund PR #926: der alte
    Test pruefte nur Key-Praesenz und die Fixture war gar nicht unaufloesbar,
    ``claim_sentence_for_span`` fand dort einen eindeutigen Satz)."""
    from academic_vault.server import add_paper, add_quote

    add_paper(
        db_path=temp_vault_db,
        paper_id="paper-899",
        csl_json='{"title": "Test Paper 899", "type": "article-journal"}',
    )
    ambiguous_verbatim = (
        "several MAD systems perform\n\nbetter after extensive tuning across benchmarks"
    )
    add_quote(
        db_path=temp_vault_db,
        paper_id="paper-899",
        verbatim=ambiguous_verbatim,
        extraction_method="manual",
    )
    unambiguous_verbatim = "the model outperforms all baselines on the held-out test set"
    add_quote(
        db_path=temp_vault_db,
        paper_id="paper-899",
        verbatim=unambiguous_verbatim,
        extraction_method="manual",
    )
    content = (
        f'Autor (2023) findet: "{ambiguous_verbatim}", was interessant ist.\n'
        "\n"
        f'Weiter berichtet Autor (2023), dass "{unambiguous_verbatim}".'
    )
    items = scan_chapter_quotes(content, temp_vault_db)
    by_verbatim = {item["verbatim"]: item for item in items}
    assert len(items) == 2

    ambiguous_item = by_verbatim[ambiguous_verbatim]
    assert ambiguous_item["claim_ambiguous"] is True

    unambiguous_item = by_verbatim[unambiguous_verbatim]
    assert unambiguous_item["claim_ambiguous"] is False
    assert "outperforms all baselines" in unambiguous_item["chapter_claim"]
