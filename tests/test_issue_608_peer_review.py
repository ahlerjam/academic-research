"""Tests fuer Issue #608 — strukturiertes Peer-Review-Gutachten verfassen.

Deckt die sechs Akzeptanzkriterien des Issues ab. Geprueft wird ausschliesslich
die strukturelle Vertragsseite (Vorgaben in SKILL.md und der Referenzvorlage) —
ob ein konkretes, vom Modell erzeugtes Gutachten inhaltlich diesen Vorgaben
folgt, ist Sache der Evals (``evals/peer-review/``), nicht dieses Tests.

| AC | Testfaelle |
| --- | --- |
| Alle 5 Bereiche abgedeckt; nicht beurteilbarer Bereich wird ausgewiesen | ``test_all_five_bereiche_named_in_skill``, ``test_nicht_beurteilbar_rule_is_explicit``, ``test_reference_names_all_five_bereiche_with_fallback`` |
| Vertrauliche Redaktions- von Autoren-Anmerkungen getrennt | ``test_reference_has_two_disjoint_addressee_blocks``, ``test_skill_points_to_addressee_separation`` |
| Genau eine Empfehlung mit Begruendung | ``test_reference_defines_exactly_four_recommendation_options``, ``test_reference_requires_reasoning_next_to_recommendation``, ``test_skill_states_exactly_one_recommendation_rule`` |
| Anmerkungen nummeriert, mit Fundstelle | ``test_reference_notes_are_numbered_with_fundstelle_field``, ``test_skill_requires_number_and_fundstelle`` |
| Keine unbelegte "uebersehene Literatur" | ``test_skill_forbids_unverified_overlooked_literature`` |
| Aussagen am Manuskript-Text belegbar, keine Vermutung ueber Autor:innen | ``test_skill_requires_text_grounded_claims``, ``test_skill_forbids_assumptions_about_authors`` |
| Repo-weite Struktur-Gates (Abgrenzung, Rueckkopplung) | ``test_skill_description_names_neighbours``, ``test_abgrenzung_section_names_neighbours``, ``test_reviewer_response_points_back_to_peer_review`` |
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "peer-review"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCE_MD = SKILL_DIR / "references" / "gutachten-structure.md"
REVIEWER_RESPONSE_MD = REPO_ROOT / "skills" / "reviewer-response" / "SKILL.md"

BEREICHE = (
    "Fragestellung und Beitrag",
    "Methodik",
    "Ergebnisdarstellung",
    "Einordnung in die Literatur",
    "Darstellung und Sprache",
)

RECOMMENDATION_OPTIONS = (
    "Annahme",
    "Kleinere Überarbeitung",
    "Größere Überarbeitung",
    "Ablehnung",
)

NACHBARN = ("reviewer-response", "quality-reviewer", "risk-of-bias", "plagiarism-check")


def _text(path: Path) -> str:
    assert path.exists(), f"{path} fehlt"
    return path.read_text(encoding="utf-8")


def _frontmatter_description(path: Path) -> str:
    text = _text(path)
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, f"{path}: kein Frontmatter gefunden"
    dm = re.search(
        r"^description:\s*(.*?)(?=^[a-zA-Z_][a-zA-Z0-9_-]*:|\Z)", m.group(1), re.DOTALL | re.M
    )
    assert dm, f"{path}: keine description im Frontmatter"
    return " ".join(dm.group(1).split())


def _abgrenzung_section(path: Path) -> str:
    text = _text(path)
    m = re.search(r"^## Abgrenzung\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"{path}: keine '## Abgrenzung'-Section gefunden"
    return m.group(1)


# ---------------------------------------------------------------------------
# Grundgeruest
# ---------------------------------------------------------------------------


def test_skill_files_exist() -> None:
    assert SKILL_MD.exists(), f"{SKILL_MD} fehlt"
    assert REFERENCE_MD.exists(), f"{REFERENCE_MD} fehlt"


# ---------------------------------------------------------------------------
# AC — alle 5 Bereiche abgedeckt, "nicht beurteilbar" statt Uebergehen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bereich", BEREICHE)
def test_all_five_bereiche_named_in_skill(bereich: str) -> None:
    text = _text(SKILL_MD)
    assert bereich in text, f"SKILL.md nennt den Bereich '{bereich}' nicht."


def test_nicht_beurteilbar_rule_is_explicit() -> None:
    text = _text(SKILL_MD)
    assert re.search(r"[Nn]icht[- ]beurteilbar", text), (
        "SKILL.md muss eine explizite 'nicht beurteilbar'-Regel pro Bereich formulieren."
    )
    assert re.search(r"nie\s+stillschweigend\s+übergangen|nicht.{0,20}übergangen", text), (
        "SKILL.md muss ausschliessen, dass ein Bereich stillschweigend uebergangen wird."
    )


@pytest.mark.parametrize("bereich", BEREICHE)
def test_reference_names_all_five_bereiche_with_fallback(bereich: str) -> None:
    text = _text(REFERENCE_MD)
    assert bereich in text, f"references/gutachten-structure.md nennt '{bereich}' nicht."
    assert "Nicht beurteilbar" in text, (
        "references/gutachten-structure.md muss den 'Nicht beurteilbar'-Platzhalter je Bereich"
        " vorschreiben."
    )


# ---------------------------------------------------------------------------
# AC — vertrauliche Redaktions- von Autoren-Anmerkungen getrennt
# ---------------------------------------------------------------------------


def test_reference_has_two_disjoint_addressee_blocks() -> None:
    text = _text(REFERENCE_MD)
    redaktion_m = re.search(r"^## Vertraulich für die Redaktion\s*$", text, re.M)
    autoren_m = re.search(r"^## Für die Autor:innen\s*$", text, re.M)
    assert redaktion_m, "references/gutachten-structure.md ohne eigenen Redaktions-Block."
    assert autoren_m, "references/gutachten-structure.md ohne eigenen Autor:innen-Block."
    assert redaktion_m.start() != autoren_m.start(), "Redaktions- und Autoren-Block sind identisch."


def test_skill_points_to_addressee_separation() -> None:
    text = _text(SKILL_MD)
    assert "Redaktion" in text and "Autor" in text, (
        "SKILL.md muss die Trennung Redaktion/Autor:innen ausdrücklich benennen."
    )
    assert re.search(r"nie.{0,40}vermischt|dürfen nicht\s+vermischt", text, re.S), (
        "SKILL.md muss ausschliessen, dass beide Bloecke vermischt werden."
    )


# ---------------------------------------------------------------------------
# AC — genau eine Empfehlung mit Begruendung
# ---------------------------------------------------------------------------


def test_reference_defines_exactly_four_recommendation_options() -> None:
    text = _text(REFERENCE_MD)
    for option in RECOMMENDATION_OPTIONS:
        assert option in text, f"Empfehlungs-Skala fehlt Option '{option}'."


def test_reference_requires_reasoning_next_to_recommendation() -> None:
    text = _text(REFERENCE_MD)
    assert "Begründung" in text, "Referenzvorlage ohne Begruendungs-Feld neben der Empfehlung."
    assert "Gutachter-Empfehlung" in text, "Referenzvorlage ohne Empfehlungs-Feld."


def test_skill_states_exactly_one_recommendation_rule() -> None:
    text = _text(SKILL_MD)
    assert re.search(r"genau eine[nm]?\s+.{0,20}[Ee]mpfehlung", text), (
        "SKILL.md muss ausdruecklich verlangen, dass es genau eine Empfehlung gibt."
    )
    assert re.search(r"[Kk]eine\s+zweite.{0,40}[Ee]mpfehlung", text, re.S), (
        "SKILL.md muss eine zweite, konkurrierende Empfehlung ausschliessen."
    )


# ---------------------------------------------------------------------------
# AC — Anmerkungen nummeriert, mit Fundstelle
# ---------------------------------------------------------------------------


def test_reference_notes_are_numbered_with_fundstelle_field() -> None:
    text = _text(REFERENCE_MD)
    assert re.search(r"\*\*\[Fundstelle:", text), (
        "Referenzvorlage ohne Fundstelle-Pflichtfeld je Anmerkung."
    )
    assert re.search(r"^1\.\s", text, re.M), "Referenzvorlage ohne nummerierte Anmerkungsliste."


def test_skill_requires_number_and_fundstelle() -> None:
    text = _text(SKILL_MD)
    assert "fortlaufende Nummer" in text or "nummeriert" in text, (
        "SKILL.md muss Nummerierung der Anmerkungen vorschreiben."
    )
    assert "Fundstelle" in text, "SKILL.md muss eine Fundstelle je Anmerkung vorschreiben."


# ---------------------------------------------------------------------------
# AC — keine unbelegte "uebersehene Literatur"
# ---------------------------------------------------------------------------


def test_skill_forbids_unverified_overlooked_literature() -> None:
    text = _text(SKILL_MD)
    assert re.search(r"übersehen", text), (
        "SKILL.md muss das Wort 'übersehen' im Kontext eines Verbots führen."
    )
    assert re.search(r"nie[a-zäöü]*\s+Literatur\s+als\s+.{0,20}[„\"]?übersehen", text, re.S), (
        "SKILL.md muss ausdruecklich verbieten, Literatur unbelegt als 'übersehen' zu benennen."
    )


# ---------------------------------------------------------------------------
# AC — Aussagen am Manuskript-Text belegbar, keine Vermutung ueber Autor:innen
# ---------------------------------------------------------------------------


def test_skill_requires_text_grounded_claims() -> None:
    text = _text(SKILL_MD)
    assert re.search(r"[Tt]extbindung|[Tt]extstelle festmachbar", text), (
        "SKILL.md muss verlangen, dass Aussagen an einer Textstelle festgemacht werden."
    )


def test_skill_forbids_assumptions_about_authors() -> None:
    text = _text(SKILL_MD)
    assert re.search(r"[Kk]eine\s+Vermutungen?\s+über\s+Absicht", text), (
        "SKILL.md muss Vermutungen ueber Absicht/Motivation/Kompetenz der Autor:innen ausschliessen."
    )


# ---------------------------------------------------------------------------
# AC — Abgrenzung (beidseitig)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nachbar", NACHBARN)
def test_skill_description_names_neighbours(nachbar: str) -> None:
    desc = _frontmatter_description(SKILL_MD)
    section = _abgrenzung_section(SKILL_MD)
    assert nachbar in desc or nachbar in section, (
        f"Weder description noch '## Abgrenzung' nennen '{nachbar}' (AC6)."
    )


@pytest.mark.parametrize("nachbar", NACHBARN)
def test_abgrenzung_section_names_neighbours(nachbar: str) -> None:
    section = _abgrenzung_section(SKILL_MD)
    assert nachbar in section, f"'## Abgrenzung' von peer-review nennt '{nachbar}' nicht (AC6)."


def test_reviewer_response_points_back_to_peer_review() -> None:
    section = _abgrenzung_section(REVIEWER_RESPONSE_MD)
    assert "peer-review" in section, (
        f"{REVIEWER_RESPONSE_MD}: Abgrenzung verweist nicht rueckgekoppelt auf 'peer-review'"
        " (Lehre aus #610-Learning, Issue #608)."
    )


def test_no_academic_context_precondition_trigger() -> None:
    """Risiko 3 aus dem Plan: die Vorbedingungen-Ausnahme muss ausgesprochen sein."""
    text = _text(SKILL_MD)
    assert "Vorbedingungen" in text
    assert re.search(r"greift hier nicht|Ausnahme", text), (
        "SKILL.md muss klarstellen, dass die Preamble-Vorbedingung hier nicht greift."
    )
