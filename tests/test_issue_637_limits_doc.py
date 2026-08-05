"""Akzeptanz-Guards fuer Issue #637 — eigenstaendiges Grenzen-Dokument.

Jeder Test bildet ein Akzeptanzkriterium des Issues mechanisch ab:

AC1  Das Dokument trennt technische, rechtliche und Pruef-Grenzen erkennbar
     (drei ``##``-Abschnitte: kann nicht / darf nicht / prueft nicht).
AC2  Jede genannte Grenze hat einen Beleg im Repo (Code-Pfad, Issue-Nummer
     oder Doku-Link).
AC3  README und Einstiegsanleitung verlinken das Dokument an sichtbarer
     Stelle, nicht im Anhang (Positions-Guard gegen ``best-practices.md``).
AC4  Die Pflicht zur Offenlegung der KI-Nutzung ist benannt.
AC5  Der Grenzen-Teil steht nach der Migration nicht mehr doppelt in
     ``best-practices.md`` — dort nur noch ein Verweis.
"""

import re
from pathlib import Path

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Ueberschriften der drei Grenzarten (AC1), Reihenfolge wie im Issue-Text:
#: kann nicht (technisch) / darf nicht (rechtlich) / prueft nicht (Kontrolle).
CATEGORY_HEADINGS = (
    "Was das Plugin nicht kann",
    "Was das Plugin nicht darf",
    "Was das Plugin nicht prüft",
)

#: Belegformen, die eine Grenzen-Zeile mindestens eine davon zeigen muss.
_CODE_PATH_RE = re.compile(r"`[\w./-]+\.[a-z]+`")
_ISSUE_RE = re.compile(r"#\d+")
_DOC_LINK_RE = re.compile(r"\[[^\]]*\]\([^)\s]+\.md[^)]*\)")

_OLD_HEADING = "Wofür das Plugin nicht geeignet ist"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _sections(text: str, level: int = 2) -> dict[str, str]:
    prefix = "#" * level + " "
    sections: dict[str, str] = {}
    current = ""
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if current:
                sections[current] += line + "\n"
            continue
        if not in_fence and line.startswith(prefix):
            current = line[len(prefix) :].strip()
            sections[current] = ""
            continue
        if current:
            sections[current] += line + "\n"
    return sections


def _bullets(section: str) -> list[str]:
    """Top-Level-Bulletpunkte, inklusive eingerueckter Folgezeilen desselben Punkts.

    Ein Beleg (Code-Pfad, Issue-Nummer, Doku-Link) steht oft erst in der
    zweiten Zeile eines umgebrochenen Bullets — ohne die Folgezeilen wuerde
    dieser Guard belegte Grenzen faelschlich als unbelegt melden.
    """
    bullets: list[str] = []
    for line in section.splitlines():
        if line.startswith(("- ", "* ")):
            bullets.append(line)
        elif bullets and line.startswith(("  ", "\t")) and line.strip():
            bullets[-1] += " " + line.strip()
    return bullets


# ---------------------------------------------------------------------------
# AC1 — drei getrennte Grenzarten
# ---------------------------------------------------------------------------


def test_limits_doc_exists() -> None:
    assert D.LIMITS_DOC.exists(), f"{_rel(D.LIMITS_DOC)} fehlt."


def test_limits_doc_has_three_categories() -> None:
    """Kann-nicht / darf-nicht / prueft-nicht stehen als eigene ##-Abschnitte,
    jeweils mit mindestens einer benannten Grenze."""
    sections = _sections(_read(D.LIMITS_DOC))
    missing = [h for h in CATEGORY_HEADINGS if h not in sections]
    assert not missing, (
        f"{_rel(D.LIMITS_DOC)}: Kategorien fehlen: {missing} (vorhanden: {sorted(sections)})"
    )
    empty = [h for h in CATEGORY_HEADINGS if len(_bullets(sections[h])) < 1]
    assert not empty, f"{_rel(D.LIMITS_DOC)}: Kategorien ohne Grenze: {empty}"


# ---------------------------------------------------------------------------
# AC2 — jede Grenze mit Repo-Beleg
# ---------------------------------------------------------------------------


def test_every_limit_cites_a_repo_path_or_issue() -> None:
    """Jede Zeile einer Grenzarten-Kategorie zeigt einen Code-Pfad, eine
    Issue-Nummer oder einen Doku-Link — keine unbelegte Behauptung."""
    sections = _sections(_read(D.LIMITS_DOC))
    unbacked = []
    for heading in CATEGORY_HEADINGS:
        for bullet in _bullets(sections.get(heading, "")):
            has_code = bool(_CODE_PATH_RE.search(bullet))
            has_issue = bool(_ISSUE_RE.search(bullet))
            has_doc = bool(_DOC_LINK_RE.search(bullet))
            if not (has_code or has_issue or has_doc):
                unbacked.append(f"{heading}: {bullet.strip()[:80]}")
    assert not unbacked, f"{_rel(D.LIMITS_DOC)}: Grenzen ohne Beleg: {unbacked}"


# ---------------------------------------------------------------------------
# AC4 — KI-Offenlegungspflicht benannt
# ---------------------------------------------------------------------------


def test_ai_disclosure_duty_is_named() -> None:
    """Das Dokument benennt die Offenlegungspflicht und verweist auf den
    real existierenden ``ai-disclosure``-Skill (ICMJE-Aufteilung)."""
    text = _read(D.LIMITS_DOC)
    assert "ai-disclosure" in text, (
        f"{_rel(D.LIMITS_DOC)}: verweist nicht auf den ai-disclosure-Skill."
    )
    assert (REPO_ROOT / "skills" / "ai-disclosure" / "SKILL.md").exists(), (
        "Vorbedingung geaendert: skills/ai-disclosure/SKILL.md fehlt."
    )
    assert re.search(r"ICMJE", text), f"{_rel(D.LIMITS_DOC)}: nennt die ICMJE-Aufteilung nicht."


# ---------------------------------------------------------------------------
# AC5 — kein Doppelinhalt in best-practices.md
# ---------------------------------------------------------------------------


def test_best_practices_no_longer_duplicates_limits() -> None:
    """Die alte Nicht-Eignungs-Ueberschrift ist aus best-practices.md verschwunden
    und wird stattdessen auf limits.md verwiesen."""
    text = _read(D.BEST_PRACTICES_DOC)
    headings = re.findall(r"^##\s+(.*?)\s*$", text, re.M)
    assert _OLD_HEADING not in headings, (
        f"{_rel(D.BEST_PRACTICES_DOC)}: alte Ueberschrift '{_OLD_HEADING}' existiert noch — "
        "Doppelinhalt zu limits.md."
    )
    assert "limits.md" in text, f"{_rel(D.BEST_PRACTICES_DOC)}: verweist nicht auf limits.md."


# ---------------------------------------------------------------------------
# AC3 — sichtbar verlinkt, nicht im Anhang
# ---------------------------------------------------------------------------


def test_limits_link_is_not_buried_in_best_practices_list() -> None:
    """README verlinkt limits.md vor der 'Besser arbeiten'-Liste (Loslegen-Rubrik),
    nicht erst dort, wo nur ankommt, wer schon ueberzeugt ist."""
    readme = _read(D.README)
    limits_idx = readme.find("guide/limits.md")
    besser_idx = readme.find("Besser arbeiten")
    assert limits_idx != -1, f"{_rel(D.README)}: verlinkt guide/limits.md nicht."
    assert besser_idx != -1, f"{_rel(D.README)}: Abschnitt 'Besser arbeiten' fehlt."
    assert limits_idx < besser_idx, (
        f"{_rel(D.README)}: guide/limits.md steht erst nach 'Besser arbeiten' — "
        "nicht sichtbar genug."
    )
