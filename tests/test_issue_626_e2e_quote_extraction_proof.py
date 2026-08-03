"""Akzeptanz-Guards fuer Issue #626 — Ende-zu-Ende-Beleg der Zitatextraktion.

`docs/quickstart-protocol.md` behauptete bislang nur die zweite Haelfte der Kette
(der Guard laesst ein bereits vorhandenes Zitat durch); die erste Haelfte (ein
Zitat entsteht aus einem echten `quote-extractor`-Lauf) war nie belegt. Dieser
Test bildet die Akzeptanzkriterien aus dem Issue ab:

AC1  Datiertes Protokoll eines Laufs existiert, in dem der lokale Extraktionspfad
     (`local-verbatim`) tatsaechlich ausgefuehrt wurde.
AC2  Kein Schritt von Hand nachgeholfen: das Protokoll referenziert eine echte,
     server-generierte `quote_id` -- kein Platzhalter wie `msg_01demo`.
AC3  Modellkennung und verwendete Quelle sind genannt.
AC4  Weicht das README von der belegten Realitaet ab (Default-Pfad), ist es
     angepasst -- `Claude-Citations-API` steht nicht mehr als alleinige
     Default-Aussage in der Warnbox.

Nicht-Regression: der bestehende Cast-Kopplungstest
(`test_issue_451_readme_showcase.py::test_demo_commands_are_covered_by_the_protocol`)
verlangt, dass Schritt 4 des Protokolls (die alten `citations-api`-Zeilen aus dem
Demo-Cast) unveraendert stehen bleibt -- dieser Test prueft deshalb nur auf
Ergaenzung, nie auf Ersetzung.
"""

from __future__ import annotations

import re

from tests.helpers import docs as D

PROTOCOL_TEXT = D.QUICKSTART_PROTOCOL_DOC.read_text(encoding="utf-8")
README_TEXT = D.README.read_text(encoding="utf-8")

#: Der alte, nie real erzeugte Platzhalter aus dem urspruenglichen Befund (Issue #626).
FAKE_API_RESPONSE_ID = "msg_01demo"


# ---------------------------------------------------------------------------
# AC1 -- datiertes Protokoll eines echten local-verbatim-Laufs
# ---------------------------------------------------------------------------


def test_protocol_has_a_dated_local_verbatim_run_section() -> None:
    """Ein neuer, datierter Abschnitt zum echten local-verbatim-Lauf existiert."""
    assert re.search(r"local-verbatim.*-Lauf.*\(2026-\d{2}-\d{2}\)", PROTOCOL_TEXT), (
        "Kein datierter Abschnitt zum realen local-verbatim-Lauf in "
        f"{D.QUICKSTART_PROTOCOL_DOC.relative_to(D.REPO_ROOT)} gefunden."
    )


def test_protocol_names_extraction_method_local_verbatim_for_the_new_run() -> None:
    """Der neue Abschnitt nennt explizit extraction_method=local-verbatim."""
    assert '"local-verbatim"' in PROTOCOL_TEXT or "'local-verbatim'" in PROTOCOL_TEXT


# ---------------------------------------------------------------------------
# AC2 -- kein Handeingriff: echte quote_id statt Platzhalter
# ---------------------------------------------------------------------------

#: Server-generierte UUIDs aus dem realen Lauf (vault.add_quote-Rueckgabewerte).
REAL_QUOTE_IDS = (
    "aed4bcbc-73fc-447b-974a-fc8c145318be",
    "99fc1d18-bca5-4a2b-bf64-ecceb0166981",
)


def test_protocol_references_a_real_server_generated_quote_id() -> None:
    """Mindestens eine echte, server-vergebene quote_id steht im neuen Abschnitt."""
    assert any(qid in PROTOCOL_TEXT for qid in REAL_QUOTE_IDS), (
        "Keine der server-generierten quote_ids aus dem realen Lauf im Protokoll "
        "gefunden -- Verdacht auf nicht tatsaechlich ausgefuehrten Lauf."
    )


def test_new_section_does_not_use_the_original_fake_placeholder_as_a_value() -> None:
    """Der neue Abschnitt darf den alten Fake-Platzhalter nicht als eigenen Beleg fuehren.

    Schritt 4 (oberhalb des neuen Abschnitts) darf ``msg_01demo`` weiterhin zeigen
    -- das ist der dokumentierte historische Fund, nicht Gegenstand dieses Tests.
    Der neue Abschnitt darf den String zwar KONTRASTIEREND erwaehnen ("kein
    Platzhalter wie msg_01demo"), ihn aber nirgends als ``quote_id``- oder
    ``api_response_id``-WERT ausgeben.
    """
    marker = "## Realer"
    idx = PROTOCOL_TEXT.find(marker)
    assert idx != -1, "Neuer Abschnitt (Ueberschrift 'Realer ...') nicht gefunden."
    new_section = PROTOCOL_TEXT[idx:]
    forbidden_as_value = re.compile(
        r"(quote_id|api_response_id)\s*[:=]\s*['\"]?" + re.escape(FAKE_API_RESPONSE_ID)
    )
    assert not forbidden_as_value.search(new_section), (
        f"Neuer Abschnitt gibt {FAKE_API_RESPONSE_ID!r} als quote_id/api_response_id-Wert "
        "aus -- das waere eine Wiederholung des urspruenglichen Fehlers."
    )


def test_old_step_4_placeholder_reference_is_preserved_not_deleted() -> None:
    """Die alte Cast-Kopplung (Schritt 4) darf nicht geloescht worden sein.

    Regressionsschutz fuer
    test_issue_451_readme_showcase.py::test_demo_commands_are_covered_by_the_protocol,
    das dieselben Zeilen im Protokoll voraussetzt.
    """
    assert FAKE_API_RESPONSE_ID in PROTOCOL_TEXT, (
        "Schritt 4 mit dem historischen api_response_id-Platzhalter fehlt -- "
        "wurde er versehentlich geloescht statt nur ergaenzt?"
    )
    assert "citations-api" in PROTOCOL_TEXT, (
        "Der alte citations-api-Beleg aus Schritt 4 fehlt -- Cast-Kopplungstest wuerde brechen."
    )


# ---------------------------------------------------------------------------
# AC3 -- Modellkennung und Quelle genannt
# ---------------------------------------------------------------------------


def test_protocol_names_the_model_used_for_the_run() -> None:
    """Der neue Abschnitt nennt eine Modellkennung (sonnet)."""
    marker = "## Realer"
    idx = PROTOCOL_TEXT.find(marker)
    assert idx != -1
    new_section = PROTOCOL_TEXT[idx:]
    assert re.search(r"sonnet", new_section, re.IGNORECASE), (
        "Modellkennung 'sonnet' fehlt im neuen Abschnitt."
    )


def test_protocol_names_the_source_pdf_used_for_the_run() -> None:
    """Der neue Abschnitt nennt die verwendete PDF-Quelle."""
    marker = "## Realer"
    idx = PROTOCOL_TEXT.find(marker)
    assert idx != -1
    new_section = PROTOCOL_TEXT[idx:]
    assert "verbatim_source.pdf" in new_section, (
        "Quellenangabe (PDF-Datei) fehlt im neuen Abschnitt."
    )
    source_path = D.REPO_ROOT / "tests" / "fixtures" / "verbatim" / "verbatim_source.pdf"
    assert source_path.exists(), (
        f"Im Protokoll referenzierte Quelle existiert nicht: {source_path.relative_to(D.REPO_ROOT)}"
    )


# ---------------------------------------------------------------------------
# AC4 -- README bei Abweichung angepasst
# ---------------------------------------------------------------------------


def test_readme_warning_box_names_local_verbatim_as_the_default_path() -> None:
    """Die README-Warnbox nennt local-verbatim als Standardpfad, nicht nur Citations-API."""
    assert "local-verbatim" in README_TEXT, (
        "README nennt local-verbatim nirgends -- die Warnbox (Zeile ~32-36) sollte "
        "seit #514/#632 den tatsaechlichen Default-Pfad benennen."
    )


def test_readme_no_longer_claims_citations_api_as_the_sole_default() -> None:
    """`Claude-Citations-API ... und liefert` (alte Alleinstellungs-Formulierung) ist weg."""
    assert "Claude-Citations-API und liefert" not in README_TEXT, (
        "README behauptet weiterhin, der citation-extraction-Skill arbeite per "
        "Default mit der Claude-Citations-API -- seit #514 falsch."
    )


def test_readme_still_mentions_citations_api_as_optional_legacy_path() -> None:
    """Die Citations-API wird nicht totgeschwiegen, sondern korrekt als Opt-in geframt."""
    assert "Citations-API" in README_TEXT, (
        "README erwaehnt die Citations-API gar nicht mehr -- sie existiert als "
        "Alt-Pfad fuer Bestandszitate weiter und sollte nicht verschwiegen werden."
    )
