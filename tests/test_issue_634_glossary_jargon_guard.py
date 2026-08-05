"""Akzeptanz-Guards fuer Issue #634 — Fachbegriffs-Guard fuer den Einstiegspfad.

AC4  Das Glossar erklaert jeden Fachbegriff, den der Einstiegspfad verwendet.
AC5  Ein Test schlaegt fehl, wenn im Einstiegspfad ein Fachbegriff ungeklaert
     auftaucht.

Mechanik (Plan-Risiko "Fachbegriff-Erkennung ist der unsicherste Teil"):
statt Freitext-NLP wird eine gepflegte Kandidatenliste (ENTRY_PATH_JARGON)
gegen zwei unabhaengige Quellen geprueft:

1. Praesenz-Selbstcheck: jeder Kandidat muss wirklich (woertlich, als
   Wort) im Einstiegspfad vorkommen — sonst ist die Liste veraltet/erfunden.
2. Abdeckungs-Check: jeder Kandidat muss ein fetter Glossar-Schluessel sein.

AC5 wird nicht durch Mutation echter Doku-Dateien bewiesen (fragil, riskiert
Drift), sondern durch einen direkten Unit-Test der Kernfunktion
``_uncovered_terms`` mit einem injizierten, garantiert unbekannten Begriff —
das ist der Meta-Test, der zeigt, dass der Guard bei einer Luecke wirklich
rot wird.

Bekannte Grenze (dokumentiert statt verschwiegen, vgl. Ehrlichkeits-Kultur
dieses Repos): ein komplett NEUER Fachbegriff, der in den Einstiegspfad
aufgenommen wird, OHNE zugleich in ENTRY_PATH_JARGON eingetragen zu werden,
faellt durch dieses Netz. Das ist der bewusste Trade-off gegen ein
Styleguide-Werkzeug (Vale/textlint), das der Issue-Scope ausschliesst.
"""

import re
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Fachbegriff-Kandidaten, die im Einstiegspfad tatsächlich vorkommen
#: (Stand Issue #634 — manuell durch Lesen der fünf Seiten ermittelt).
#: Jeder Eintrag wird unten sowohl gegen den Einstiegspfad-Text als auch
#: gegen das Glossar verifiziert.
ENTRY_PATH_JARGON: tuple[str, ...] = (
    "Vault",
    "Subagent",
    "Material-Passport",
    "Repro-Lock",
    "output_targets",
    "PRISMA",
    "HAN",
    "Abstract",
    "IMRaD",
    "Skill",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _entry_path_text() -> str:
    return "\n".join(_read(p) for p in D.ENTRY_PATH_DOCS if p.exists())


def _word_present(term: str, text: str) -> bool:
    pattern = re.compile(r"(?<![\wÄÖÜäöüß])" + re.escape(term) + r"(?![\wÄÖÜäöüß])")
    return bool(pattern.search(text))


def _glossary_terms() -> set[str]:
    text = _read(D.GLOSSARY_DOC)
    return set(re.findall(r"^\|\s*\*\*(.+?)\*\*\s*\|", text, re.M))


def _uncovered_terms(used: tuple[str, ...], glossary_terms: set[str]) -> list[str]:
    """Kernfunktion des Guards: Begriffe aus ``used``, die nicht im Glossar stehen.

    Unabhaengig testbar (AC5-Meta-Test) und von den Guards gegen den echten
    Bestand wiederverwendet — dieselbe Funktion, zwei Eingaben.
    """
    return [t for t in used if t not in glossary_terms]


# ---------------------------------------------------------------------------
# Vorbedingungen der Kandidatenliste (verhindert eine erfundene/veraltete Liste)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("term", ENTRY_PATH_JARGON)
def test_jargon_candidate_actually_occurs_in_entry_path(term: str) -> None:
    """Jeder Kandidat muss real im Einstiegspfad stehen — sonst ist die Liste
    Behauptung statt Befund (Faktendisziplin)."""
    assert _word_present(term, _entry_path_text()), (
        f"'{term}' steht nicht (mehr) im Einstiegspfad — ENTRY_PATH_JARGON "
        "in tests/test_issue_634_glossary_jargon_guard.py pflegen."
    )


def test_entry_path_docs_are_defined_and_exist() -> None:
    assert D.ENTRY_PATH_DOCS, "ENTRY_PATH_DOCS ist leer — Vorbedingung verletzt."
    missing = [str(p) for p in D.ENTRY_PATH_DOCS if not p.exists()]
    assert not missing, f"Einstiegspfad-Seiten fehlen: {missing}"


# ---------------------------------------------------------------------------
# AC4 — jeder im Einstiegspfad verwendete Fachbegriff steht im Glossar
# ---------------------------------------------------------------------------


def test_glossary_covers_every_entry_path_jargon_term() -> None:
    glossary_terms = _glossary_terms()
    assert glossary_terms, "Glossar liefert keine Begriffe — Vorbedingung verletzt."
    uncovered = _uncovered_terms(ENTRY_PATH_JARGON, glossary_terms)
    assert not uncovered, f"Fachbegriffe im Einstiegspfad ohne Glossar-Eintrag (AC4): {uncovered}"


# ---------------------------------------------------------------------------
# AC5 — Meta-Test: der Guard schlaegt bei einem ungeklaerten Begriff fehl
# ---------------------------------------------------------------------------


def test_guard_flags_an_injected_unknown_term() -> None:
    """Beweist, dass _uncovered_terms tatsaechlich greift (AC5).

    Ein garantiert erfundener Begriff wird als 'im Einstiegspfad verwendet'
    simuliert und muss als ungeklaert zurueckkommen — sonst waere der Guard
    wirkungslos (immer gruen, egal was passiert).
    """
    glossary_terms = _glossary_terms()
    fake_term = "Zwiebelfischalgorithmus-XYZ-9912"
    assert fake_term not in glossary_terms, "Test-Fixture ungueltig: Fake-Begriff kollidiert."

    uncovered = _uncovered_terms((*ENTRY_PATH_JARGON, fake_term), glossary_terms)

    assert fake_term in uncovered, (
        "_uncovered_terms hat den injizierten unbekannten Begriff nicht erkannt "
        "— der Guard waere wirkungslos."
    )


def test_guard_does_not_flag_known_terms() -> None:
    """Gegenprobe zum Meta-Test: bekannte, glossierte Begriffe bleiben unbeanstandet."""
    glossary_terms = _glossary_terms()
    uncovered = _uncovered_terms(ENTRY_PATH_JARGON, glossary_terms)
    assert uncovered == [], f"Unerwartet ungeklaerte Begriffe: {uncovered}"
