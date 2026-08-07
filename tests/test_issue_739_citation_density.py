"""Tests fuer die Belegdichte in der Kapitel-Pruefbilanz (Issue #739).

Deckt:
  AC1  Bilanz nennt Zahl Aussagesaetze, Zahl belegter Aussagesaetze, Anteil.
  AC2  Aussagesatz-Klassifikation ist an Beispielen belegt: Ueberschriften,
       Listenpunkte, Fragen und reine Ueberleitungen zaehlen nicht mit.
  AC3  Laengste zusammenhaengende Strecke ohne Beleg mit Fundstelle.
  AC4  Es wird nichts gemeldet, gewarnt oder blockiert -- auch bei 0 % Dichte.
  AC5  Doku benennt explizit: hohe Belegdichte ist kein Qualitaetsmerkmal.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def paper_id(temp_vault_db):
    from academic_vault.server import add_paper

    pid = "test-paper-739"
    add_paper(
        db_path=temp_vault_db,
        paper_id=pid,
        csl_json=json.dumps({"title": "Test Paper 739", "type": "article-journal"}),
    )
    return pid


@pytest.fixture
def belegter_quote(temp_vault_db, paper_id):
    from academic_vault.server import add_quote

    verbatim = "Der Effekt war in allen Kohorten nachweisbar und robust."
    quote_id = add_quote(
        db_path=temp_vault_db,
        paper_id=paper_id,
        verbatim=verbatim,
        extraction_method="manual",
    )
    return quote_id, verbatim


# ---------------------------------------------------------------------------
# AC2 -- Aussagesatz-Klassifikation (nli_prefilter.extract_statement_sentences)
# ---------------------------------------------------------------------------


def test_heading_line_is_not_a_statement_sentence():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = "## Methodik\n\nDies ist ein echter Aussagesatz im Fliesstext."
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert not any("Methodik" in t for t in texts)
    assert "Dies ist ein echter Aussagesatz im Fliesstext." in texts


def test_list_item_is_not_a_statement_sentence():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = (
        "- Erster Listenpunkt ohne eigene Aussagekraft.\n\n"
        "Dies ist ein echter Aussagesatz im Fliesstext."
    )
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert not any("Listenpunkt" in t for t in texts)
    assert "Dies ist ein echter Aussagesatz im Fliesstext." in texts


def test_numbered_list_item_is_not_a_statement_sentence():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = (
        "1. Erster nummerierter Punkt ohne Aussagekraft.\n\n"
        "Dies ist ein echter Aussagesatz im Fliesstext."
    )
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert not any("nummerierter" in t for t in texts)
    assert "Dies ist ein echter Aussagesatz im Fliesstext." in texts


def test_question_is_not_a_statement_sentence():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = "Ist das plausibel? Dies ist ein echter Aussagesatz im Fliesstext."
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert "Ist das plausibel?" not in texts
    assert "Dies ist ein echter Aussagesatz im Fliesstext." in texts


def test_transition_sentence_is_not_a_statement_sentence():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = (
        "Im Folgenden wird die Methodik erlaeutert. Dies ist ein echter Aussagesatz im Fliesstext."
    )
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert not any("Im Folgenden" in t for t in texts)
    assert "Dies ist ein echter Aussagesatz im Fliesstext." in texts


def test_ordinary_claim_sentence_is_counted():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = "DevOps-Governance hat sich seit 2015 in der Praxis durchgesetzt."
    sentences = extract_statement_sentences(content)

    assert [s["text"] for s in sentences] == [content]


def test_sentence_before_a_quote_opening_character_is_split_off():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = 'Der Effekt war robust. "Ein Zitat beginnt hier" schreibt Mueller.'
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert "Der Effekt war robust." in texts
    assert '"Ein Zitat beginnt hier" schreibt Mueller.' in texts


def test_sentence_before_a_digit_initial_sentence_is_split_off():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = "Der Effekt war robust. 2026 wurde er repliziert."
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert "Der Effekt war robust." in texts
    assert "2026 wurde er repliziert." in texts


def test_blank_line_between_paragraphs_is_a_hard_sentence_boundary():
    from academic_vault.nli_prefilter import extract_statement_sentences

    content = "Absatz eins endet hier.\n\nAbsatz zwei beginnt hier."
    sentences = extract_statement_sentences(content)

    texts = [s["text"] for s in sentences]
    assert "Absatz eins endet hier." in texts
    assert "Absatz zwei beginnt hier." in texts


# ---------------------------------------------------------------------------
# AC1 -- compute_citation_density: Zahl, Anzahl belegt, Anteil
# ---------------------------------------------------------------------------


def test_compute_citation_density_counts_total_and_covered(temp_vault_db, belegter_quote):
    from academic_vault.nli_prefilter import compute_citation_density

    quote_id, verbatim = belegter_quote
    content = (
        "Erster Satz ohne Beleg und mit ausreichender Laenge fuer den Test. "
        "Zweiter Satz ohne jeden Beleg im Kapiteltext hier drin. "
        f'Dritter Satz enthaelt den Beleg: "{verbatim}"'
    )

    density = compute_citation_density(content, temp_vault_db)

    assert density["statement_sentences_total"] == 3
    assert density["statement_sentences_covered"] == 1
    assert density["citation_density"] == pytest.approx(1 / 3)


def test_compute_citation_density_zero_statements_yields_none_ratio(temp_vault_db):
    from academic_vault.nli_prefilter import compute_citation_density

    density = compute_citation_density(
        "## Nur eine Ueberschrift\n\n- Und ein Punkt.", temp_vault_db
    )

    assert density["statement_sentences_total"] == 0
    assert density["statement_sentences_covered"] == 0
    assert density["citation_density"] is None


def test_unquoted_span_does_not_count_as_covered_without_vault_match(temp_vault_db):
    """Ein Anfuehrungszeichen ohne Vault-Treffer ist kein Beleg -- sonst
    zaehlte ein erfundenes Zitat faelschlich als gedeckt."""
    from academic_vault.nli_prefilter import compute_citation_density

    content = '"Dies ist ein frei erfundenes Zitat ohne Vault-Eintrag hier." -- Quelle unbekannt.'
    density = compute_citation_density(content, temp_vault_db)

    assert density["statement_sentences_covered"] == 0


# ---------------------------------------------------------------------------
# AC3 -- laengste zusammenhaengende Strecke ohne Beleg, mit Fundstelle
# ---------------------------------------------------------------------------


def test_longest_uncovered_run_picks_the_longer_gap(temp_vault_db, belegter_quote):
    from academic_vault.nli_prefilter import compute_citation_density

    quote_id, verbatim = belegter_quote
    beleg_satz = f'Satz mit Beleg: "{verbatim}".'
    content = (
        f"{beleg_satz} "
        "Kurze Luecke ohne Beleg hier drin. "
        f"{beleg_satz} "
        "Erster Satz der langen Luecke ohne Beleg. "
        "Zweiter Satz der langen Luecke ohne Beleg. "
        "Dritter Satz der langen Luecke ohne Beleg."
    )

    density = compute_citation_density(content, temp_vault_db)
    run = density["longest_uncovered_run"]

    assert run is not None
    assert run["sentence_count"] == 3
    assert run["excerpt"] == "Erster Satz der langen Luecke ohne Beleg."
    assert run["line"] == 1


def test_longest_uncovered_run_none_when_fully_covered(temp_vault_db, belegter_quote):
    from academic_vault.nli_prefilter import compute_citation_density

    quote_id, verbatim = belegter_quote
    content = f'"{verbatim}" -- so die Quelle.'

    density = compute_citation_density(content, temp_vault_db)

    assert density["longest_uncovered_run"] is None


# ---------------------------------------------------------------------------
# AC4 -- nichts wird gemeldet, gewarnt oder blockiert
# ---------------------------------------------------------------------------


def test_zero_percent_density_raises_nothing_and_logs_nothing(
    temp_vault_db, tmp_path, capsys, caplog
):
    from academic_vault.server import chapter_quote_balance

    chapter_file = tmp_path / "kapitel-ohne-beleg.md"
    chapter_file.write_text(
        "Ein Aussagesatz ohne jeden Beleg im gesamten Kapitel. "
        "Ein weiterer Aussagesatz ohne jeden Beleg.",
        encoding="utf-8",
    )

    balance = chapter_quote_balance(db_path=temp_vault_db, chapter_path=str(chapter_file))

    assert balance["citation_density"] == 0.0
    assert balance["statement_sentences_covered"] == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# Integration: chapter_quote_balance traegt die neuen Felder additiv
# ---------------------------------------------------------------------------


def test_chapter_quote_balance_carries_additive_density_fields(
    temp_vault_db, belegter_quote, tmp_path
):
    from academic_vault.server import chapter_quote_balance

    quote_id, verbatim = belegter_quote
    chapter_file = tmp_path / "kapitel-mit-beleg.md"
    chapter_file.write_text(f'"{verbatim}" -- so die Quelle.', encoding="utf-8")

    balance = chapter_quote_balance(db_path=temp_vault_db, chapter_path=str(chapter_file))

    # Bestehende Keys aus Issue #737 bleiben unveraendert erreichbar.
    assert balance["total_quotes"] == 1
    # Neue, additive Keys aus Issue #739.
    assert balance["statement_sentences_total"] == 1
    assert balance["statement_sentences_covered"] == 1
    assert balance["citation_density"] == 1.0
    assert balance["longest_uncovered_run"] is None


def test_chapter_quote_balance_empty_chapter_density_fields_stay_zero(temp_vault_db, tmp_path):
    from academic_vault.server import chapter_quote_balance

    chapter_file = tmp_path / "leeres-kapitel-739.md"
    chapter_file.write_text(
        "Reine Prosa ohne jedes Anfuehrungszeichen und ohne belegte Aussage.",
        encoding="utf-8",
    )

    balance = chapter_quote_balance(db_path=temp_vault_db, chapter_path=str(chapter_file))

    assert balance["statement_sentences_total"] == 1
    assert balance["statement_sentences_covered"] == 0
    assert balance["citation_density"] == 0.0


# ---------------------------------------------------------------------------
# AC5 -- Doku benennt "keine Qualitaetsaussage" explizit
# ---------------------------------------------------------------------------


def test_docs_state_high_density_is_not_a_quality_signal():
    docs = (REPO_ROOT / "docs" / "reference" / "vault.md").read_text(encoding="utf-8")
    assert "kein Qualitätsmerkmal" in docs or "kein Qualitaetsmerkmal" in docs


def test_docs_document_statement_sentence_definition_with_examples():
    docs = (REPO_ROOT / "docs" / "reference" / "vault.md").read_text(encoding="utf-8")
    assert "Belegdichte" in docs
    assert "Ueberschrift" in docs or "Überschrift" in docs
