"""Akzeptanz-Guards fuer Issue #640 — vollstaendige, code-geprueste Referenz.

Jeder Test bildet ein Akzeptanzkriterium des Issues ab:

AC1  Jeder Skill, Agent, Command und jedes MCP-Tool hat einen Referenzeintrag
     in einheitlicher Form (drei Pflichtfelder je Eintrag).
AC2  Derselbe Guard schlaegt fehl, sobald eine neue Komponente ohne
     Referenzeintrag hinzukommt (Meta-Test mit injizierter Komponente, ohne
     echte Dateien zu mutieren).
AC3  Jede Zahlenangabe der Doku-Oberflaeche ist an ihre Code-Quelle gebunden
     (``component_inventory()``), nicht an eine zweite Doku-Stelle.
AC4  Die README nennt die richtige Anzahl Subagents.
AC5  Zu jedem Eintrag steht, woran ein Fehlschlag erkennbar ist.
AC6  Kein Inhalt steht gleichzeitig in Referenz und Anleitung; die Anleitung
     verweist in die Referenz, nicht umgekehrt.

Die Pflichtfelder liegen in zwei Darstellungsformen vor, weil die Referenz
zwei Darstellungsformen hat: Tabellenspalten (``skills.md``, ``agents.md``,
``vault.md``) und Marker-Zeilen in ``###``-Sektionen (``commands.md``).
Beide werden hier geparst und gegen dieselbe Feldmenge geprueft.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT

#: Pflichtfelder je Referenzeintrag — als Tabellenspalten geschrieben.
REQUIRED_COLUMNS = ("Voraussetzung", "Rückgabe", "Fehlschlag erkennbar an")

#: Dieselben Pflichtfelder als Marker-Zeilen in den ``###``-Sektionen von
#: ``commands.md`` (dort steht je Command ein Absatz, keine Tabellenzeile).
REQUIRED_MARKERS = ("**Voraussetzungen:**", "**Rückgabe:**", "**Fehlschlag:**")

#: Ein Feld gilt als ausgefuellt, wenn es mehr als eine Platzhalter-Geste ist.
MIN_FIELD_LENGTH = 8

#: Komponentenklasse -> (Referenzdokument, Regex fuer den Namen in Spalte 1).
TABLE_CLASSES: dict[str, tuple[Path, re.Pattern[str]]] = {
    "skills": (D.SKILLS_DOC, re.compile(r"`([a-z0-9-]+)`")),
    "agents": (D.AGENTS_DOC, re.compile(r"`([a-z0-9-]+)`")),
    "mcp_tools": (D.VAULT_DOC, re.compile(r"`(vault\.[a-z_]+)\(")),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _is_separator(cells: list[str]) -> bool:
    return set("".join(cells)) <= {"-", ":", " ", ""}


def table_entries(text: str, name_re: re.Pattern[str]) -> dict[str, dict[str, str]]:
    """Eintraege aus allen Tabellen, die die Pflichtspalten fuehren.

    Tabellen ohne die Pflichtspalten (Env-Variablen, Status-Modelle, externe
    Skills) werden uebersprungen — sie sind keine Komponenteneintraege.
    """
    entries: dict[str, dict[str, str]] = {}
    header: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if _is_separator(cells):
            continue
        if all(col in cells for col in REQUIRED_COLUMNS):
            header = cells
            continue
        if header is None:
            continue
        match = name_re.search(cells[0])
        if not match:
            continue
        entries[match.group(1)] = {
            col: (cells[header.index(col)] if header.index(col) < len(cells) else "")
            for col in REQUIRED_COLUMNS
        }
    return entries


def command_entries(text: str) -> dict[str, dict[str, str]]:
    """Eintraege aus den ``### `/academic-research:<name>```-Sektionen."""
    entries: dict[str, dict[str, str]] = {}
    sections = re.split(r"^### ", text, flags=re.M)[1:]
    for section in sections:
        head, _, body = section.partition("\n")
        match = re.match(r"`/academic-research:([a-z0-9-]+)`", head.strip())
        if not match:
            continue
        fields: dict[str, str] = {}
        for marker, column in zip(REQUIRED_MARKERS, REQUIRED_COLUMNS, strict=True):
            if marker not in body:
                fields[column] = ""
                continue
            rest = body.split(marker, 1)[1]
            # Der Feldwert reicht bis zur naechsten Leerzeile (Absatz-Grenze).
            fields[column] = re.split(r"\n\s*\n", rest, maxsplit=1)[0].strip()
        entries[match.group(1)] = fields
    return entries


def reference_entries() -> dict[str, dict[str, dict[str, str]]]:
    """Je Komponentenklasse die geparsten Referenzeintraege."""
    parsed = {
        name: table_entries(_read(doc), name_re) for name, (doc, name_re) in TABLE_CLASSES.items()
    }
    parsed["commands"] = command_entries(_read(D.COMMANDS_DOC))
    return parsed


def missing_entries(names: set[str], entries: dict[str, dict[str, str]]) -> list[str]:
    """Kernfunktion des Vollstaendigkeits-Guards — separat testbar (AC2)."""
    return sorted(name for name in names if name not in entries)


def entries_missing_field(entries: dict[str, dict[str, str]], field: str) -> list[str]:
    """Eintraege, deren Pflichtfeld fehlt oder nur eine Platzhalter-Geste ist."""
    incomplete = []
    for name, fields in sorted(entries.items()):
        value = fields.get(field, "").strip()
        if len(value.strip("—- ")) < MIN_FIELD_LENGTH:
            incomplete.append(name)
    return incomplete


# ---------------------------------------------------------------------------
# AC1 — jede Komponente hat einen Eintrag in einheitlicher Form
# ---------------------------------------------------------------------------

COMPONENT_CLASSES = ("skills", "agents", "commands", "mcp_tools")


@pytest.mark.parametrize("klass", COMPONENT_CLASSES)
def test_every_component_has_a_reference_entry(klass: str) -> None:
    """Kein Skill, Agent, Command und kein MCP-Tool ohne Referenzeintrag."""
    inventory = D.component_inventory()[klass]
    entries = reference_entries()[klass]
    missing = missing_entries(inventory, entries)
    assert not missing, f"{klass}: kein Referenzeintrag mit Pflichtfeldern fuer {missing}"


@pytest.mark.parametrize("klass", COMPONENT_CLASSES)
def test_reference_has_no_ghost_entries(klass: str) -> None:
    """Umgekehrt: die Referenz beschreibt nichts, was es im Code nicht gibt."""
    inventory = D.component_inventory()[klass]
    entries = reference_entries()[klass]
    ghosts = sorted(set(entries) - inventory)
    assert not ghosts, f"{klass}: Referenz nennt Eintraege ohne Code-Entsprechung: {ghosts}"


@pytest.mark.parametrize("klass", COMPONENT_CLASSES)
@pytest.mark.parametrize("field", ("Voraussetzung", "Rückgabe"))
def test_every_entry_declares_precondition_and_return(klass: str, field: str) -> None:
    """Voraussetzung und Rueckgabe stehen bei jedem Eintrag."""
    entries = reference_entries()[klass]
    incomplete = entries_missing_field(entries, field)
    assert not incomplete, f"{klass}: Feld '{field}' fehlt oder ist leer bei {incomplete}"


# ---------------------------------------------------------------------------
# AC5 — Fehlschlag-Signal je Eintrag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("klass", COMPONENT_CLASSES)
def test_every_entry_declares_a_failure_signal(klass: str) -> None:
    """Zu jedem Eintrag steht, woran ein Fehlschlag erkennbar ist."""
    entries = reference_entries()[klass]
    incomplete = entries_missing_field(entries, "Fehlschlag erkennbar an")
    assert not incomplete, f"{klass}: kein Fehlschlag-Signal bei {incomplete}"


# ---------------------------------------------------------------------------
# AC2 — der Guard wird rot, wenn eine Komponente ohne Eintrag dazukommt
# ---------------------------------------------------------------------------


def test_guard_flags_an_injected_component() -> None:
    """Eine synthetische Komponente ohne Eintrag meldet der Guard als fehlend.

    Meta-Test nach dem Muster aus #634: geprueft wird die Kernfunktion mit
    injiziertem Namen, nicht eine mutierte Doku-Datei.
    """
    entries = reference_entries()["skills"]
    injected = D.component_inventory()["skills"] | {"synthetischer-skill-ohne-eintrag"}
    assert missing_entries(injected, entries) == ["synthetischer-skill-ohne-eintrag"]


def test_guard_flags_an_entry_without_failure_signal() -> None:
    """Ein Eintrag mit leerem Fehlschlag-Feld faellt auf."""
    entries = {
        "vollstaendig": {
            "Voraussetzung": "Vault mit mindestens einem Paper",
            "Rückgabe": "Liste der Treffer",
            "Fehlschlag erkennbar an": "leere Trefferliste",
        },
        "luecke": {
            "Voraussetzung": "Vault mit mindestens einem Paper",
            "Rückgabe": "Liste der Treffer",
            "Fehlschlag erkennbar an": "—",
        },
    }
    assert entries_missing_field(entries, "Fehlschlag erkennbar an") == ["luecke"]


# ---------------------------------------------------------------------------
# AC3 + AC4 — Zahlenangaben haengen am Code
# ---------------------------------------------------------------------------

#: Label -> (Muster ueber die Doku-Oberflaeche, Schluessel im Inventar).
COUNT_CLAIMS: dict[str, tuple[tuple[str, ...], str]] = {
    "Skills": ((r"(\d+)\s+Skills\b", r"badge/skills-(\d+)"), "skills"),
    "Agents": ((r"(\d+)\s+Agents\b", r"(\d+)\s+Subagents\b", r"badge/agents-(\d+)"), "agents"),
    "Commands": ((r"(\d+)\s+Slash-Commands\b", r"badge/commands-(\d+)"), "commands"),
    "MCP-Tools": ((r"(\d+)\s+MCP-Tools\b", r"MCP-Tools\s*\(alle\s+(\d+)\)"), "mcp_tools"),
}


@pytest.mark.parametrize("label", sorted(COUNT_CLAIMS))
def test_component_count_claims_match_the_code(label: str) -> None:
    """Jede Komponenten-Zahl der Doku ist gegen das Code-Inventar gedeckt."""
    patterns, key = COUNT_CLAIMS[label]
    actual = len(D.component_inventory()[key])
    wrong: list[str] = []
    for doc in D.doc_surface():
        if not doc.exists():
            continue
        text = _read(doc)
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                if int(match.group(1)) != actual:
                    line = text[: match.start()].count("\n") + 1
                    wrong.append(
                        f"{doc.relative_to(REPO_ROOT)}:{line}: '{match.group(0)}' != {actual}"
                    )
    assert not wrong, f"{label}: Doku-Zahlen weichen vom Code-Stand ({actual}) ab: {wrong}"


def test_readme_agent_count_matches_agents_dir() -> None:
    """Die README nennt die Subagenten-Zahl aus ``agents/`` (AC4)."""
    actual = len(D.component_inventory()["agents"])
    text = _read(D.README)
    claims = [int(m) for m in re.findall(r"(\d+)\s+Subagents\b", text)]
    assert claims, "README nennt gar keine Subagenten-Zahl mehr."
    assert all(claim == actual for claim in claims), (
        f"README nennt {claims} Subagents, agents/ enthaelt {actual} Dateien."
    )


def test_reference_repeats_no_count_the_inventory_cannot_confirm() -> None:
    """Die Referenz nennt jede Klasse mit ihrer Zahl mindestens einmal.

    Ohne diesen Test koennte eine Referenzseite ihre Bestandsangabe einfach
    weglassen und der Guard oben liefe ins Leere.
    """
    inventory = D.component_inventory()
    expected = {
        D.SKILLS_DOC: f"{len(inventory['skills'])} Skills",
        D.AGENTS_DOC: f"{len(inventory['agents'])} Agents",
        D.COMMANDS_DOC: f"{len(inventory['commands'])} Slash-Commands",
        D.VAULT_DOC: f"{len(inventory['mcp_tools'])} MCP-Tools",
    }
    missing = [
        f"{doc.relative_to(REPO_ROOT)}: '{claim}'"
        for doc, claim in expected.items()
        if claim not in _read(doc)
    ]
    assert not missing, f"Referenzseite ohne code-gedeckte Bestandsangabe: {missing}"


# ---------------------------------------------------------------------------
# AC6 — Referenz und Anleitung ueberschneiden sich nicht
# ---------------------------------------------------------------------------

#: Fensterbreite des Duplikat-Vergleichs (Muster aus test_issue_451).
DUPLICATE_WINDOW = 3


def _comparable_lines(text: str) -> list[str]:
    """Zeilen ohne Tabellen-Trenner und ohne reine Kurz-/Label-Zeilen.

    Eine Zeile wie ``**Beispiele:**`` oder ein Codefence steht in beiden
    Dokumentklassen und ist kein dupliziertes Referenzmaterial.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if _is_separator([c.strip() for c in stripped.strip("|").split("|")]) and stripped:
            kept.append("")
            continue
        if len(stripped) < 40:
            kept.append("")
            continue
        kept.append(stripped)
    return kept


def test_guide_does_not_duplicate_reference_blocks() -> None:
    """Kein Block von >= 3 Zeilen steht wortgleich in Anleitung und Referenz."""
    reference = {doc: _read(doc) for doc in sorted(D.REFERENCE_DIR.glob("*.md")) if doc.exists()}
    duplicates: list[str] = []
    for guide in sorted(D.GUIDE_DIR.glob("*.md")):
        lines = _comparable_lines(_read(guide))
        for i in range(len(lines) - DUPLICATE_WINDOW + 1):
            chunk = lines[i : i + DUPLICATE_WINDOW]
            if any(not ln for ln in chunk):
                continue
            needle = "\n".join(chunk)
            for doc, text in reference.items():
                if needle in text:
                    duplicates.append(
                        f"{guide.relative_to(REPO_ROOT)}:{i + 1} == {doc.relative_to(REPO_ROOT)}"
                    )
                    break
    assert not duplicates, f"Anleitung dupliziert Referenzmaterial statt zu verlinken: {duplicates}"


def test_guides_link_into_the_reference() -> None:
    """Jede Anleitungsseite verweist in die Referenz — Richtung Anleitung → Referenz."""
    without_link = [
        guide.relative_to(REPO_ROOT).as_posix()
        for guide in sorted(D.GUIDE_DIR.glob("*.md"))
        if not re.search(r"\.\./reference/[a-z-]+\.md", _read(guide))
    ]
    assert not without_link, f"Anleitungsseite ohne Link in die Referenz: {without_link}"
