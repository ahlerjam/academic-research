"""Tests für Issue #605 — KI-Offenlegungserklärung nach ICMJE 01/2026.

Reiner Prosa-Skill (kein Skript): die Ausgabe selbst ist eine Modellleistung
und nicht deterministisch prüfbar. Deterministisch prüfbar ist die
Vertragsseite — dass SKILL.md die vier Akzeptanzkriterien aus dem
Plan-Kommentar (getrennte Danksagung/Methodenteil-Abschnitte, Vault-Spuren als
Vorschlag statt Behauptung, Kennzeichnung unbelegter Angaben, DE/EN-Fassung,
keine unbestätigte/weggelassene Nutzung, Fundstelle mit Locator) tatsächlich
als Anleitung führt, sowie dass die Referenzdatei die zugrunde gelegte
ICMJE-Fassung mit Fundstelle nennt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / "skills" / "ai-disclosure" / "SKILL.md"
REFERENCE_MD = REPO_ROOT / "skills" / "ai-disclosure" / "references" / "icmje-2026.md"


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _reference_text() -> str:
    return REFERENCE_MD.read_text(encoding="utf-8")


def _description() -> str:
    m = re.match(r"^---\n(.*?)\n---", _text(), re.DOTALL)
    assert m, "kein Frontmatter"
    dm = re.search(
        r"^description:\s*(.*?)(?=^[a-zA-Z_][a-zA-Z0-9_-]*:|\Z)", m.group(1), re.DOTALL | re.M
    )
    assert dm, "keine description im Frontmatter"
    return " ".join(dm.group(1).split())


def _section(heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", _text(), re.M | re.S)
    assert m, f"Section '## {heading}' fehlt in {SKILL_MD}"
    return m.group(1)


def test_skill_exists():
    assert SKILL_MD.exists(), f"{SKILL_MD} fehlt"


def test_reference_file_exists():
    assert REFERENCE_MD.exists(), f"{REFERENCE_MD} fehlt"


def test_description_targets_ai_disclosure():
    desc = _description()
    for phrase in ("KI-Nutzung offenlegen", "Offenlegungserklärung erstellen"):
        assert phrase in desc, f"Trigger-Phrase '{phrase}' fehlt in der description"


def test_allowed_tools_declares_ask_user_question():
    """Voraussetzung für die strukturierte Rückfrage (AC2)."""
    content = _text()
    frontmatter = content.split("---")[1]
    assert "AskUserQuestion" in frontmatter, (
        "SKILL.md nutzt AskUserQuestion für den Kategorien-Scan, "
        "muss es aber auch in allowed-tools deklarieren"
    )


# ---------------------------------------------------------------------------
# AC1: getrennte Abschnitte Danksagung/Methodenteil nach ICMJE-Aufteilung
# ---------------------------------------------------------------------------


def test_output_template_has_all_four_sections():
    text = _text()
    for heading in (
        "## Danksagung (Deutsch)",
        "## Methodenteil (Deutsch)",
        "## Acknowledgement (English)",
        "## Methods (English)",
    ):
        assert heading in text, f"Output-Template-Abschnitt '{heading}' fehlt"


def test_icmje_usage_split_documented():
    """Sprachpolitur/Übersetzung -> Danksagung, Analyse/Klassifikation -> Methodenteil."""
    text = _text()
    assert re.search(r"Sprachpolitur.*Danksagung", text, re.S), (
        "Zuordnung Sprachpolitur -> Danksagung fehlt"
    )
    assert re.search(r"(Analyse|Klassifikation).*Methodenteil", text, re.S), (
        "Zuordnung Analyse/Klassifikation -> Methodenteil fehlt"
    )


# ---------------------------------------------------------------------------
# AC2: Vault-Spur wird als Vorschlag vorgelegt statt blind erfragt
# ---------------------------------------------------------------------------


def test_vault_tools_documented_as_read_only():
    text = _text()
    for tool in (
        "vault.list_papers_by_provenance",
        "vault.find_quotes",
        "vault.list_codings",
        "vault.list_risk_of_bias",
    ):
        assert tool in text, f"Vault-Tool '{tool}' wird nicht als Belegquelle genannt"
    assert "read-only" in text, "Vault-Tools sind nicht explizit als read-only markiert"


def test_vault_trace_is_proposal_not_assertion():
    text = _text()
    assert "**Vorschlag**" in text, "Vault-Treffer wird nicht als Vorschlag ausgewiesen"
    assert "nie stillschweigend übernehmen" in text, (
        "Kein expliziter Hinweis, Vault-Treffer nicht stillschweigend zu übernehmen"
    )


def test_missing_trace_triggers_structured_question():
    text = _text()
    scan = _section("Workflow")
    assert "AskUserQuestion" in scan, "Kategorien-Scan nutzt AskUserQuestion nicht"
    assert "Kein Treffer" in text, "Fehlender Vault-Treffer führt nicht zur Rückfrage"


# ---------------------------------------------------------------------------
# AC3: Angaben ohne Vault-Beleg sind gekennzeichnet
# ---------------------------------------------------------------------------


def test_unverified_lines_carry_explicit_marker():
    text = _text()
    assert "(Nutzerangabe, kein Vault-Beleg)" in text, (
        "Marker für unbelegte Angaben fehlt im Output-Template"
    )
    assert "(Vault-Beleg:" in text, "Marker für vault-belegte Angaben fehlt im Output-Template"
    assert "Eine Zeile ohne Markierung ist ein Fehler" in text, (
        "Pflicht zur Markierung jeder Zeile ist nicht als harte Regel formuliert"
    )


def test_acknowledgment_category_always_unverified():
    """Sprachpolitur/Übersetzung/Textaufbereitung hinterlassen im Vault keine Spur."""
    text = _text()
    danksagung_step = _section("Übersicht")
    assert "keine Spur" in text or "hinterlassen in diesem Vault" in text, (
        "Kein Hinweis, dass die Danksagungs-Kategorie im Vault unbelegbar ist"
    )
    assert "immer** per `AskUserQuestion`" in text or "immer per `AskUserQuestion`" in text, (
        "Danksagung wird nicht als zwingend abzufragende Kategorie beschrieben"
    )
    assert danksagung_step  # Übersicht referenziert die Vault-Grenze


# ---------------------------------------------------------------------------
# AC4: deutsche und englische Fassung
# ---------------------------------------------------------------------------


def test_german_and_english_versions_paired():
    text = _text()
    assert "(Deutsch)" in text and "(English)" in text, "DE/EN-Kennzeichnung fehlt"
    assert text.count("(Deutsch)") == 2, (
        "Erwartet genau 2 deutsche Abschnitte (Danksagung + Methodenteil)"
    )
    assert text.count("(English)") == 2, (
        "Erwartet genau 2 englische Abschnitte (Acknowledgement + Methods)"
    )


# ---------------------------------------------------------------------------
# AC5: keine unbestätigte Nutzung behauptet, keine bestätigte weggelassen
# ---------------------------------------------------------------------------


def test_confirmation_step_documents_correction_scenario():
    text = _text()
    assert "Widerspricht der Nutzer" in text, "Korrektur-Szenario (Widerspruch) fehlt"
    assert "Korrektur" in text and "Rohspur" in text, (
        "Kein Hinweis, dass die Nutzer-Korrektur die Vault-Rohspur ersetzt, nicht umgekehrt"
    )
    assert "zusätzliche Kategorie ohne jede Vault-Spur" in text, (
        "Szenario 'bestätigte Zusatzkategorie ohne Vault-Spur' fehlt"
    )
    assert (
        "behauptet nie eine Nutzung, die der Nutzer nicht bestätigt hat" in text
        and "lässt keine bestätigte Nutzung weg" in text
    ), "Kernregel AC5 fehlt wörtlich"


# ---------------------------------------------------------------------------
# AC6: Quelle der Anforderung mit Fundstelle
# ---------------------------------------------------------------------------


def test_skill_references_source_file_with_locator():
    text = _text()
    assert "references/icmje-2026.md" in text, "Kein Verweis auf die Fundstellen-Referenzdatei"
    assert "Januar 2026" in text and "Section V" in text, (
        "Fundstelle (Datum + Abschnitt) fehlt im SKILL.md-Fließtext"
    )


def test_reference_file_names_concrete_locator():
    text = _reference_text()
    assert "Januar 2026" in text, "Referenzdatei nennt kein Datum der ICMJE-Fassung"
    assert "Section V" in text, "Referenzdatei nennt keine Abschnittsangabe"
    assert "icmje.org" in text, "Referenzdatei verweist nicht auf die Primärquelle"


def test_reference_file_explains_no_faculty_template():
    text = _reference_text()
    assert "keine Vorlage" in text.lower() or "Warum keine Vorlage" in text, (
        "Referenzdatei begründet nicht, warum keine Fakultäts-/Zeitschriftvorlage mitgeliefert wird"
    )


# ---------------------------------------------------------------------------
# Abgrenzung
# ---------------------------------------------------------------------------


def test_delimits_against_submission_checker_and_word_export():
    abgrenzung = _section("Abgrenzung")
    assert "submission-checker" in abgrenzung, "Abgrenzung zu submission-checker fehlt"
    assert "word-export" in abgrenzung, "Abgrenzung zu word-export fehlt"


def test_does_not_introduce_new_activity_log():
    """Scope 'Out': kein neues Vault-Aktivitätsprotokoll."""
    text = _text()
    assert "Kein neues Aktivitätsprotokoll" in text, (
        "Kein expliziter Hinweis, dass kein neues Aktivitätsprotokoll eingeführt wird"
    )
    assert "ausschließlich lesend" in text, (
        "Vault-Tools sind nicht als reine Leseoperationen markiert"
    )


def test_does_not_evaluate_permissibility():
    """Scope 'Out': keine Bewertung der Zulässigkeit."""
    abgrenzung = _section("Abgrenzung")
    assert re.search(r"(Fakultät und Zeitschrift entscheiden|zulässig ist)", abgrenzung), (
        "Kein Hinweis, dass die Zulässigkeitsbewertung außerhalb des Skills liegt"
    )


# ---------------------------------------------------------------------------
# Bookkeeping: Skill-Zähler-Baselines
# ---------------------------------------------------------------------------


def test_skill_sizes_baseline_contains_ai_disclosure():
    sizes_path = REPO_ROOT / "tests" / "baselines" / "skill_sizes.json"
    sizes = json.loads(sizes_path.read_text())
    assert "ai-disclosure" in sizes, "skill_sizes.json enthält keinen 'ai-disclosure'-Eintrag"
    assert sizes["ai-disclosure"] > 0


def test_token_baseline_contains_ai_disclosure():
    tokens_path = REPO_ROOT / "tests" / "baselines" / "tokens.json"
    tokens = json.loads(tokens_path.read_text())
    assert "ai-disclosure" in tokens, "tokens.json enthält keinen 'ai-disclosure'-Eintrag"
    assert tokens["ai-disclosure"] > 0
