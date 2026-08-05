"""Akzeptanz-Guards fuer Issue #611 — Einstieg nach Vorhaben statt nach Komponenten.

``docs/guide/project-paths.md`` gruppiert die vier im Issue genannten Vorhaben
(systematische Uebersichtsarbeit, empirische Qualifikationsarbeit mit eigener
Erhebung, Literaturarbeit, Zeitschriftenbeitrag) und listet je Vorhaben die
real existierenden Skills in Einsatzreihenfolge. Jeder Test bildet ein
Akzeptanzkriterium des Issues mechanisch ab (siehe Plan-Kommentar
``<!-- plan:v1 -->``):

AC1  Gliederung nach Vorhaben mit Skill-Sequenz je Pfad.
AC2  Abhaengigkeiten zwischen Schritten ausgesprochen.
AC3  Kuerzester Weg Installation -> sichtbares Ergebnis.
AC4  Jeder genannte Skill existiert unter diesem Namen.
AC5  Kein Skill inhaltlich doppelt erklaert, nur verwiesen.
AC6  Vier Wege belegt oder als Annahme gekennzeichnet.
"""

import re

import pytest

from tests.helpers import docs as D

DOC = D.GUIDE_DIR / "project-paths.md"
SKILLS_DIR = D.REPO_ROOT / "skills"

#: Die vier im Issue benannten Vorhaben, als exakte ``##``-Ueberschriften.
VORHABEN = (
    "Systematische Übersichtsarbeit",
    "Empirische Qualifikationsarbeit mit eigener Erhebung",
    "Literaturarbeit",
    "Zeitschriftenbeitrag",
)

#: Mindestzahl an Skills je Pfad-Abschnitt (AC1).
MIN_SKILLS_PER_PATH = 2

#: Zeilenfenster ab Abschnittsanfang, in dem der Beleg-/Annahme-Marker stehen
#: muss (AC6) — analog zu ``MARKER_LINE_BUDGET`` in test_issue_452.
MARKER_LINE_BUDGET = 6

#: Marker-Vokabular, analog zur globalen Faktendisziplin-Konvention
#: ("Vermutung:"/"ungetestet:") und zum Plan-Kommentar ("Attestierungs-/
#: Annahme-Marker").
ASSUMPTION_MARKERS = ("Annahme:", "Vermutung:")
EVIDENCE_MARKERS = ("Beleg:",)

#: Woerter/Muster, die eine ausgesprochene Abhaengigkeit anzeigen (AC2).
PREREQUISITE_PATTERNS = ("davor", "setzt voraus", "vorausgesetzt", "nach ")

#: Gesamtzeilenbudget der Seite — erzwingt Kuerze statt Skill-Prosa (AC5).
MAX_LINES = 170

_SKILL_TOKEN_RE = re.compile(r"`([a-z][a-z0-9-]*)`")
_HEADING_RE = re.compile(r"^##\s+(.*?)\s*$")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _lines() -> list[str]:
    return _text().splitlines()


def _existing_skill_names() -> set[str]:
    return {p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md")}


def _sections() -> dict[str, tuple[int, list[str]]]:
    """Ueberschrift -> (Startzeile 0-indiziert, Zeilen des Abschnitts)."""
    lines = _lines()
    sections: dict[str, tuple[int, list[str]]] = {}
    current: str | None = None
    start = 0
    buf: list[str] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            if current is not None:
                sections[current] = (start, buf)
            current = m.group(1)
            start = i
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = (start, buf)
    return sections


def test_doc_exists() -> None:
    assert DOC.exists(), f"Einstiegsdokument fehlt: {DOC.relative_to(D.REPO_ROOT)}"


def test_project_paths_has_four_sections() -> None:
    """AC1 — fuer jedes benannte Vorhaben gibt es einen eigenen Abschnitt."""
    sections = _sections()
    missing = [v for v in VORHABEN if v not in sections]
    assert not missing, f"Abschnitte fuer diese Vorhaben fehlen: {missing}"


@pytest.mark.parametrize("vorhaben", VORHABEN)
def test_each_path_lists_an_ordered_skill_sequence(vorhaben: str) -> None:
    """AC1 — mindestens zwei Skills je Pfad, als Backtick-Token in Reihenfolge."""
    sections = _sections()
    assert vorhaben in sections, f"Abschnitt '{vorhaben}' fehlt."
    _, body = sections[vorhaben]
    existing = _existing_skill_names()
    tokens = [t for t in _SKILL_TOKEN_RE.findall("\n".join(body)) if t in existing]
    # Reihenfolge ist implizit durch findall (Textreihenfolge) gegeben — hier nur
    # die Mindestzahl pruefen, Duplikate zaehlen als ein Schritt nicht doppelt.
    ordered_unique = list(dict.fromkeys(tokens))
    assert len(ordered_unique) >= MIN_SKILLS_PER_PATH, (
        f"Abschnitt '{vorhaben}' nennt nur {len(ordered_unique)} real existierende "
        f"Skills, erwartet mindestens {MIN_SKILLS_PER_PATH}."
    )


@pytest.mark.parametrize("vorhaben", VORHABEN)
def test_each_path_states_a_prerequisite(vorhaben: str) -> None:
    """AC2 — jeder Pfad spricht eine Abhaengigkeit aus (Wort oder Link)."""
    sections = _sections()
    _, body = sections[vorhaben]
    body_text = "\n".join(body)
    has_pattern = any(p in body_text.lower() for p in PREREQUISITE_PATTERNS)
    has_link = "getting-started.md" in body_text
    assert has_pattern or has_link, (
        f"Abschnitt '{vorhaben}': keine ausgesprochene Abhaengigkeit "
        f"(Muster {PREREQUISITE_PATTERNS} oder Link auf getting-started.md)."
    )


@pytest.mark.parametrize("vorhaben", VORHABEN)
def test_each_path_has_evidence_or_assumption_marker(vorhaben: str) -> None:
    """AC6 — Beleg- oder Annahme-Marker in den ersten Zeilen des Abschnitts."""
    sections = _sections()
    _, body = sections[vorhaben]
    head = body[:MARKER_LINE_BUDGET]
    head_text = "\n".join(head)
    has_marker = any(m in head_text for m in ASSUMPTION_MARKERS + EVIDENCE_MARKERS)
    assert has_marker, (
        f"Abschnitt '{vorhaben}': kein Beleg-/Annahme-Marker in den ersten "
        f"{MARKER_LINE_BUDGET} Zeilen ({ASSUMPTION_MARKERS + EVIDENCE_MARKERS})."
    )


def test_shortest_path_links_getting_started() -> None:
    """AC3 — eigener Abschnitt/Absatz verweist auf getting-started.md, ohne
    dessen Schritte zu wiederholen (keine nummerierte Schrittliste)."""
    text = _text()
    assert "guide/getting-started.md" in text or "](getting-started.md)" in text, (
        "Seite verlinkt getting-started.md nicht."
    )
    # Keine eigene "Schritt N"-Nummerierung -- das waere eine Wiederholung
    # statt eines Verweises.
    assert not re.search(r"##\s*Schritt\s+\d", text), (
        "Seite wiederholt eine eigene Schritt-Nummerierung statt auf "
        "getting-started.md zu verweisen."
    )


def test_all_named_skills_exist_on_disk() -> None:
    """AC4 — jeder als Skill referenzierte Backtick-Token existiert unter skills/."""
    existing = _existing_skill_names()
    text = _text()
    # Nur Tokens, die tatsaechlich auf ein skills/-Verzeichnis zeigen sollen:
    # alle Kleinbuchstaben-Bindestrich-Tokens in Backticks ausserhalb von
    # Code-Fences, abzueglich bekannter Nicht-Skill-Begriffe (Dateinamen etc.).
    non_skill_tokens = {
        "academic_context.md",
        "getting-started.md",
        "skills.md",
    }
    missing = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for token in _SKILL_TOKEN_RE.findall(line):
            if token in non_skill_tokens or token in existing:
                continue
            if "." in token or "/" in token:
                continue
            missing.append(token)
    assert not missing, f"Genannte Skills existieren nicht unter skills/: {sorted(set(missing))}"


def test_no_skill_prose_duplication() -> None:
    """AC5 — die Seite verlinkt die Skills-Referenz statt Skills zu erklaeren."""
    text = _text()
    assert "reference/skills.md" in text, "Seite verlinkt docs/reference/skills.md nicht."


def test_page_stays_within_line_budget() -> None:
    """AC5 (Kuerze erzwingen) — Gesamtzeilenbudget der Seite."""
    n = len(_lines())
    assert n <= MAX_LINES, f"{DOC.relative_to(D.REPO_ROOT)}: {n} Zeilen, Budget ist {MAX_LINES}."


def test_project_paths_doc_registered_in_docs_helpers() -> None:
    """Die zentrale Pfadregistratur kennt die neue Seite (sonst greifen die
    README-/LINKED_DOCS-Guards aus #402 nicht dafuer)."""
    assert DOC in D.LINKED_DOCS, "docs/guide/project-paths.md fehlt in D.LINKED_DOCS."
