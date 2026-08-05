"""Akzeptanz-Guards fuer Issue #461 — Praxis-Leitfaden.

Jeder Test bildet ein Akzeptanzkriterium des Issues mechanisch ab:

AC1  Das Einstiegsdokument traegt allein von der Installation bis zum ersten
     verwertbaren Ergebnis — kein Schritt delegiert die Ausfuehrung nach aussen.
AC2  Jeder Arbeitsschritt des Durchlaufs hat eine Beispielformulierung, die das
     beschriebene Ergebnis wirklich ausloesen kann.
AC3  Fuer die wichtigsten Aufgabentypen steht eine Modellempfehlung mit Begruendung.
AC4  Der Token-Abschnitt nennt reale Stellschrauben statt allgemeiner Ratschlaege.
AC5  Die Seiten sind untereinander verknuepft und aus README und Doku-Uebersicht
     erreichbar.
AC6  Der Leitfaden benennt konkret, wofuer das Plugin nicht geeignet ist.

**Grenze dieser Guards (bewusst benannt, nicht ueberspielt):** Ob eine
Beispielformulierung im Live-Betrieb wirklich den gemeinten Skill aktiviert,
laesst sich statisch nicht beweisen. Geprueft wird die belegbare Kette
Beispiel -> realer Command/reales Flag bzw. Beispiel -> Trigger-Phrase aus
``docs/reference/skills.md``; dass diese Phrase in der ``description`` der
zugehoerigen ``SKILL.md`` steht, erzwingt bereits
``tests/test_skills_manifest.py``. Ein Live-Beweis waere eine LLM-Eval unter
``evals/`` — dafuer existiert kein Budget (siehe ``docs/SKIP_REASONS.md``).
"""

import re
from pathlib import Path

import pytest

from tests.helpers import docs as D

REPO_ROOT = D.REPO_ROOT
COMMANDS_DIR = REPO_ROOT / "commands"
AGENTS_DIR = REPO_ROOT / "agents"
SKILLS_DIR = REPO_ROOT / "skills"
SCRIPTS_DIR = REPO_ROOT / "scripts"
SEARCH_COMMAND = COMMANDS_DIR / "search.md"
SEARCH_SCRIPT = SCRIPTS_DIR / "search.py"

#: Belegte Bedeutung der Modell-Aliase laut Claude-Code-Doku "Model
#: configuration" (https://code.claude.com/docs/en/model-config, Stand
#: 2026-07-30, ueber context7 gegen die Seite geprueft). Je Alias die Begriffe,
#: die in seiner Erklaerung auf der Seite vorkommen muessen. Deutet die Seite
#: einen Alias spaeter um, wird dieser Guard rot.
ALIAS_DOC_MARKERS = {
    # "Uses Claude Fable 5 for your hardest and longest-running tasks";
    # Abschnitt "Work with Fable 5": haelt lange autonome Sitzungen durch.
    "fable": ("schwersten", "längsten"),
    # "Uses Fable 5 where your organization has access to it, otherwise the
    # latest Opus model" — kein pauschales "leistungsstaerkstes Modell".
    "best": ("Fable", "Opus"),
    # "uses opus during plan mode, then switches to sonnet for execution"
    "opusplan": ("Plan", "Sonnet"),
}

#: Deutungen, die die offizielle Doku fuer ``fable`` NICHT hergibt. Fable 5 ist
#: dort das Modell fuer die schwersten und laengsten Aufgaben — lange autonome
#: Laeufe mit eigener Recherche und Selbstverifikation, kein Kreativ- oder
#: Schreibmodell. Wer es so verkauft, empfiehlt auf einer erfundenen Grundlage.
FABLE_UNSUPPORTED_CLAIMS = ("kreativ", "schreibnah", "sprachlich")

#: Gueltige Claude-Code-Modell-Aliase (Frontmatter ``model:`` bzw. ``/model``).
VALID_MODEL_ALIASES = {
    "best",
    "fable",
    "sonnet",
    "opus",
    "haiku",
    "opusplan",
    "default",
    "inherit",
    "sonnet[1m]",
    "opus[1m]",
}

#: Stellschrauben, die der Token-Abschnitt mindestens nennen muss.
REQUIRED_TOKEN_LEVERS = (
    "--mode metadata",
    "--mode quick",
    "--limit",
    # "--batch" entfiel mit #632 zusammen mit der Batch-API -- der Hebel liegt
    # seither vor dem Scoring (Treffermenge klein halten), nicht daneben.
    "--no-expand",
    "--no-browser",
)

#: Belegbare Grenzen, die der Nicht-Eignungs-Abschnitt namentlich nennen muss.
REQUIRED_LIMIT_MARKERS = (
    "SciHub",
    "document-skills",
    "deutschsprachige",
)

_FENCE_RE = re.compile(r"^```", re.M)
_SLASH_RE = re.compile(r"/academic-research:([a-z-]+)([^\n`]*)")
_FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_TRIGGER_RE = re.compile('„([^„"]+)"')


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _code_blocks(text: str) -> list[str]:
    """Inhalte aller ```-Bloecke einer Markdown-Datei."""
    parts = text.split("```")
    blocks = []
    for i in range(1, len(parts), 2):
        body = parts[i]
        # Erste Zeile ist die Sprachangabe (oder leer).
        blocks.append(body.split("\n", 1)[1] if "\n" in body else "")
    return blocks


def _sections(text: str, level: int = 2) -> dict[str, str]:
    """Ueberschriftentext -> Abschnittstext, ohne Code-Fence-Inhalte zu verwechseln."""
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


def _headings(text: str) -> list[str]:
    """Alle Ueberschriften ausserhalb von Code-Bloecken."""
    out = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("#"):
            out.append(line.lstrip("#").strip())
    return out


#: Blockanfaenge, die keinen Prompt ausweisen (Shell, Log, Slash-Command, Konfig).
_NON_PROMPT_PREFIXES = (
    "$",
    "#",
    "{",
    "/",
    "---",
    "mkdir",
    "cd ",
    "export ",
    "brew ",
    "pip ",
    "uv ",
    "INFO:",
    "claude ",
)


def _vault_tool_names() -> set[str]:
    """Real registrierte MCP-Tools des Vault-Servers."""
    src = _read(REPO_ROOT / "academic_vault" / "server.py")
    return set(re.findall(r'@mcp\.tool\(name="(vault\.[a-z_]+)"\)', src))


def _command_text(name: str) -> str | None:
    path = COMMANDS_DIR / f"{name}.md"
    return _read(path) if path.exists() else None


def _trigger_phrases() -> set[str]:
    """Reale Trigger-Phrasen aus der Spalte 'Aktiviert bei' in skills.md."""
    phrases = set()
    for line in _read(D.SKILLS_DOC).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        for phrase in _TRIGGER_RE.findall(cells[1]):
            cleaned = phrase.strip().lower()
            if cleaned:
                phrases.add(cleaned)
    return phrases


# ---------------------------------------------------------------------------
# AC1 — Einstiegsdokument traegt allein bis zum ersten Ergebnis
# ---------------------------------------------------------------------------

#: Marker der Einstiegsstrecke, in genau dieser Reihenfolge.
_ONBOARDING_STEPS = (
    "/plugin marketplace add ahlerjam/academic-research",
    "/plugin install academic-research@academic-research",
    "mkdir ",
    "/academic-research:setup",
    "academic_context.md",
    "/academic-research:search",
    "quote-extractor",
)


def test_getting_started_exists() -> None:
    """Ohne Einstiegsdokument gibt es keinen selbsttragenden Weg (AC1)."""
    assert D.GETTING_STARTED_DOC.exists(), f"{_rel(D.GETTING_STARTED_DOC)} fehlt."


def test_getting_started_walks_install_to_first_result_in_order() -> None:
    """Installation, Arbeitsordner, Setup, Kontext, Suche, Zitat — in dieser Folge."""
    text = _read(D.GETTING_STARTED_DOC)
    positions = []
    missing = []
    for marker in _ONBOARDING_STEPS:
        idx = text.find(marker)
        if idx < 0:
            missing.append(marker)
        else:
            positions.append((marker, idx))
    assert not missing, f"{_rel(D.GETTING_STARTED_DOC)}: Einstiegsschritte fehlen: {missing}"
    order = [idx for _, idx in positions]
    assert order == sorted(order), (
        f"{_rel(D.GETTING_STARTED_DOC)}: Schritte stehen nicht in der Reihenfolge "
        f"{[m for m, _ in _ONBOARDING_STEPS and positions]} — ein Einstieg, der "
        "vor- und zurueckspringt, traegt nicht allein."
    )


def test_getting_started_does_not_delegate_execution() -> None:
    """Kein Schritt schiebt die Ausfuehrung auf eine andere Seite ab (AC1).

    Verweise zum Vertiefen sind erlaubt; 'wie das geht, steht woanders' nicht.
    """
    text = _read(D.GETTING_STARTED_DOC)
    forbidden = (
        "steht in der README",
        "siehe README",
        "wie in der Installationsanleitung beschrieben",
        "erst die Installationsanleitung",
    )
    offenders = [needle for needle in forbidden if needle.lower() in text.lower()]
    assert not offenders, (
        f"{_rel(D.GETTING_STARTED_DOC)} delegiert die Ausfuehrung nach aussen: {offenders}"
    )


def _search_summary_pattern() -> re.Pattern[str]:
    """Regex der Abschlussmeldung, direkt aus dem ``log.info``-Format gebaut.

    Quelle ist ``scripts/search.py``; aendert sich dort der Wortlaut, zeigt der
    Leitfaden ab sofort ein Signal, das so nie auf dem Terminal steht — und der
    Guard wird rot, statt die Abweichung durchzulassen.
    """
    match = re.search(r'"(Found %d papers[^"]*)"', _read(SEARCH_SCRIPT))
    assert match, "Vorbedingung geaendert: scripts/search.py loggt keine 'Found ...'-Zeile mehr."
    parts = re.split(r"(%d)", match.group(1))
    return re.compile("".join(r"\d+" if p == "%d" else re.escape(p) for p in parts))


def test_getting_started_shows_the_real_success_signal() -> None:
    """Der Einstieg zeigt die Abschlussmeldung im echten Wortlaut (AC1/AC2).

    Ein gekuerztes Erfolgssignal ist schlimmer als keines: Wer die gezeigte
    Zeile nicht findet, haelt einen geglueckten Lauf fuer gescheitert.
    """
    text = _read(D.GETTING_STARTED_DOC)
    pattern = _search_summary_pattern()
    assert pattern.search(text), (
        f"{_rel(D.GETTING_STARTED_DOC)}: zeigt die Abschlussmeldung nicht so, wie "
        f"{_rel(SEARCH_SCRIPT)} sie loggt (erwartetes Muster: {pattern.pattern!r})."
    )


# ---------------------------------------------------------------------------
# AC2 — Beispielformulierung je Arbeitsschritt, die wirklich ausloest
# ---------------------------------------------------------------------------


def _numbered_steps(text: str) -> dict[str, str]:
    return {h: body for h, body in _sections(text).items() if re.match(r"^\d+\.", h)}


def test_walkthrough_has_numbered_steps() -> None:
    """Vorbedingung: Der Durchlauf ist in nummerierte Arbeitsschritte gegliedert."""
    steps = _numbered_steps(_read(D.WALKTHROUGH_DOC))
    assert len(steps) >= 10, f"{_rel(D.WALKTHROUGH_DOC)}: nur {len(steps)} Arbeitsschritte."


def test_every_walkthrough_step_has_an_example() -> None:
    """Jeder Arbeitsschritt zeigt eine Beispielformulierung als Code-Block (AC2)."""
    without = [
        heading
        for heading, body in _numbered_steps(_read(D.WALKTHROUGH_DOC)).items()
        if not any(block.strip() for block in _code_blocks(body))
    ]
    assert not without, f"{_rel(D.WALKTHROUGH_DOC)}: Schritte ohne Beispielformulierung: {without}"


def test_every_walkthrough_step_names_its_result() -> None:
    """Jeder Schritt sagt, was dabei herauskommt — sonst ist das Beispiel blind (AC2)."""
    without = [
        heading
        for heading, body in _numbered_steps(_read(D.WALKTHROUGH_DOC)).items()
        if "Ergebnis:" not in body
    ]
    assert not without, f"{_rel(D.WALKTHROUGH_DOC)}: Schritte ohne 'Ergebnis:'-Angabe: {without}"


def _session_pdf_dir() -> str:
    """Realer PDF-Ablageort eines Suchlaufs, aus ``commands/search.md`` gelesen.

    Der Command legt pro Lauf ein Sitzungsverzeichnis an und schreibt die
    Volltexte dort hinein; ``scripts/session_index.py`` zaehlt sie ebenfalls
    unter ``<session_dir>/pdfs``. Der flache Ordner ``~/.academic-research/pdfs``
    wird von ``scripts/setup.sh`` nur leer angelegt und nie befuellt.
    """
    text = _read(SEARCH_COMMAND)
    match = re.search(r"SESSION_DIR=(\S+?)/\$\(date", text)
    assert match, "Vorbedingung geaendert: commands/search.md setzt SESSION_DIR nicht mehr."
    assert 'mkdir -p "$SESSION_DIR/pdfs"' in text, (
        "Vorbedingung geaendert: commands/search.md legt kein $SESSION_DIR/pdfs mehr an."
    )
    return match.group(1)


@pytest.mark.parametrize("doc", D.PRACTICE_GUIDE_DOCS, ids=lambda p: p.name)
def test_pdf_location_is_session_scoped(doc: Path) -> None:
    """Kein Praxisdokument schickt den Leser in einen Ordner, der leer bleibt (AC2).

    ``~/.academic-research/pdfs/`` existiert zwar nach dem Setup, wird von der
    Suche aber nie befuellt — wer dort nachsieht, haelt einen geglueckten Lauf
    fuer gescheitert.
    """
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} existiert noch nicht (eigener Test deckt das ab)")
    session_root = _session_pdf_dir()
    wrong = [
        m.group(1)
        for m in re.finditer(r"`(~/\.academic-research/[^`]*pdfs/?)`", _read(doc))
        if not m.group(1).startswith(session_root + "/")
    ]
    assert not wrong, (
        f"{_rel(doc)}: nennt {wrong} als PDF-Ablage; real schreibt "
        f"{_rel(SEARCH_COMMAND)} nach {session_root}/<zeitstempel>/pdfs/."
    )


@pytest.mark.parametrize("doc", D.PRACTICE_GUIDE_DOCS, ids=lambda p: p.name)
def test_slash_examples_use_real_commands_and_flags(doc: Path) -> None:
    """Jeder gezeigte Slash-Aufruf existiert und nutzt nur reale Flags (AC2).

    Faengt genau den Fall, der im alten Walkthrough stand: ein erfundenes
    ``--import-list`` an einem Command, der es nicht kennt.
    """
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} existiert noch nicht (eigener Test deckt das ab)")
    problems = []
    for name, tail in _SLASH_RE.findall(_read(doc)):
        command = _command_text(name)
        if command is None:
            problems.append(f"unbekannter Command /academic-research:{name}")
            continue
        for flag in _FLAG_RE.findall(tail):
            if flag not in command:
                problems.append(f"/academic-research:{name}: Flag {flag} steht in keinem Command")
    assert not problems, f"{_rel(doc)}: {problems}"


@pytest.mark.parametrize("doc", D.PRACTICE_GUIDE_DOCS, ids=lambda p: p.name)
def test_free_text_examples_are_anchored_in_real_mechanics(doc: Path) -> None:
    """Jedes Freitext-Beispiel haengt an einer realen Trigger-Phrase (AC2).

    Ausnahme: Beispiele, die keinen Skill, sondern direkt den Vault ansprechen —
    dort muss der umgebende Abschnitt das reale MCP-Tool benennen, das antwortet.
    Beides ist gegen die Quelle geprueft: Trigger gegen
    ``docs/reference/skills.md``, Tool-Namen gegen ``academic_vault/server.py``.
    """
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} existiert noch nicht (eigener Test deckt das ab)")
    triggers = _trigger_phrases()
    vault_tools = _vault_tool_names()
    assert triggers, "Vorbedingung geaendert: skills.md nennt keine Trigger-Phrasen."
    assert vault_tools, "Vorbedingung geaendert: server.py registriert keine vault.*-Tools."
    misses = []
    for heading, section in _sections(_read(doc)).items():
        anchored = any(tool in section for tool in vault_tools)
        for block in _code_blocks(section):
            body = block.strip()
            if not body or "/academic-research:" in body or "/plugin" in body:
                continue
            if body.startswith(_NON_PROMPT_PREFIXES):
                continue
            if any(trigger in body.lower() for trigger in triggers) or anchored:
                continue
            misses.append(f"{heading}: {body.splitlines()[0][:70]}")
    assert not misses, (
        f"{_rel(doc)}: Freitext-Beispiele ohne reale Trigger-Phrase aus "
        f"{_rel(D.SKILLS_DOC)} und ohne benanntes vault.*-Tool: {misses}"
    )


@pytest.mark.parametrize("doc", D.PRACTICE_GUIDE_DOCS, ids=lambda p: p.name)
def test_named_skills_and_agents_exist(doc: Path) -> None:
    """Jeder namentlich genannte Skill/Agent existiert wirklich (AC2)."""
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} existiert noch nicht (eigener Test deckt das ab)")
    text = _read(doc)
    missing = []
    for name in re.findall(r"`([a-z][a-z0-9-]+)`-Skill", text):
        if not (SKILLS_DIR / name / "SKILL.md").exists():
            missing.append(f"Skill {name}")
    for name in re.findall(r"`([a-z][a-z0-9-]+)`-(?:Agent|Subagent)", text):
        if not (AGENTS_DIR / f"{name}.md").exists():
            missing.append(f"Agent {name}")
    assert not missing, f"{_rel(doc)}: nennt nicht existierende Komponenten: {missing}"


# ---------------------------------------------------------------------------
# AC3 — Modellempfehlung mit Begruendung
# ---------------------------------------------------------------------------


def _model_table_rows() -> list[list[str]]:
    """Datenzeilen der Modelltabelle: Aufgabentyp | Alias | Begruendung."""
    rows = []
    for line in _read(D.MODEL_CHOICE_DOC).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or set("".join(cells)) <= set("-: "):
            continue
        if cells[0].lower().startswith("aufgabe"):
            continue
        rows.append(cells)
    return rows


def _alias_table_rows() -> dict[str, str]:
    """Alias -> Bedeutung aus der zweispaltigen Alias-Tabelle."""
    rows: dict[str, str] = {}
    for line in _read(D.MODEL_CHOICE_DOC).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 2 or set("".join(cells)) <= set("-: "):
            continue
        for alias in re.findall(r"`([^`]+)`", cells[0]):
            rows[alias] = cells[1]
    return rows


def test_model_choice_doc_exists() -> None:
    """Ohne Modellseite gibt es keine Empfehlung (AC3)."""
    assert D.MODEL_CHOICE_DOC.exists(), f"{_rel(D.MODEL_CHOICE_DOC)} fehlt."


def test_alias_table_matches_the_official_model_config_doc() -> None:
    """Die Alias-Tabelle gibt wieder, was die Claude-Code-Doku sagt (AC3).

    Die Begriffe in ``ALIAS_DOC_MARKERS`` stammen woertlich aus
    https://code.claude.com/docs/en/model-config. Erfindet die Seite eine eigene
    Bedeutung, faellt der Guard.
    """
    rows = _alias_table_rows()
    assert rows, f"{_rel(D.MODEL_CHOICE_DOC)}: keine Alias-Tabelle gefunden."
    problems = []
    for alias, markers in ALIAS_DOC_MARKERS.items():
        meaning = rows.get(alias)
        if meaning is None:
            problems.append(f"{alias}: fehlt in der Alias-Tabelle")
            continue
        missing = [m for m in markers if m.lower() not in meaning.lower()]
        if missing:
            problems.append(f"{alias}: {missing} fehlen in {meaning!r}")
    assert not problems, f"{_rel(D.MODEL_CHOICE_DOC)}: {problems}"


def test_fable_is_not_sold_as_a_writing_model() -> None:
    """``fable`` wird nicht zum Kreativmodell umgedeutet (AC3).

    Die Doku ordnet Fable 5 den schwersten und laengsten Aufgaben zu — lange
    autonome Laeufe mit eigener Verifikation. Eine Empfehlung, die stattdessen
    mit Sprachqualitaet begruendet wird, steht auf erfundener Grundlage.
    """
    offenders = []
    meaning = _alias_table_rows().get("fable", "")
    offenders += [
        f"Alias-Tabelle: '{c}' in {meaning!r}"
        for c in FABLE_UNSUPPORTED_CLAIMS
        if c in meaning.lower()
    ]
    for cells in _model_table_rows():
        if "`fable`" not in cells[1]:
            continue
        reason = cells[2]
        offenders += [
            f"{cells[0]!r}: '{c}' in der Begruendung"
            for c in FABLE_UNSUPPORTED_CLAIMS
            if c in reason.lower()
        ]
        if not any(m.lower() in reason.lower() for m in ALIAS_DOC_MARKERS["fable"]):
            offenders.append(f"{cells[0]!r}: Begruendung nennt die belegte Fable-Eignung nicht")
    assert not offenders, f"{_rel(D.MODEL_CHOICE_DOC)}: {offenders}"


def test_model_table_covers_task_types_with_reasons() -> None:
    """Mindestens vier Aufgabentypen, je gueltiger Alias und echte Begruendung (AC3)."""
    rows = _model_table_rows()
    assert len(rows) >= 4, f"{_rel(D.MODEL_CHOICE_DOC)}: nur {len(rows)} Aufgabentypen."
    problems = []
    for cells in rows:
        aliases = re.findall(r"`([a-z]+(?:\[1m\])?)`", cells[1])
        if not any(alias in VALID_MODEL_ALIASES for alias in aliases):
            problems.append(f"{cells[0]!r}: kein gueltiger Alias in {cells[1]!r}")
        if len(cells[2]) < 25:
            problems.append(f"{cells[0]!r}: Begruendung zu duenn ({cells[2]!r})")
    assert not problems, f"{_rel(D.MODEL_CHOICE_DOC)}: {problems}"


def test_model_table_names_no_invented_alias() -> None:
    """Die Tabelle erfindet keinen Alias, den Claude Code nicht kennt (AC3)."""
    invented = sorted(
        {
            alias
            for cells in _model_table_rows()
            for alias in re.findall(r"`([a-z]+(?:\[1m\])?)`", cells[1])
            if alias not in VALID_MODEL_ALIASES
        }
    )
    assert not invented, f"{_rel(D.MODEL_CHOICE_DOC)}: unbekannte Modell-Aliase: {invented}"


def test_model_page_matches_agent_frontmatter() -> None:
    """Jeder real gesetzte ``model:``-Wert der Agents kommt auf der Seite vor (AC3).

    Wechselt ein Agent das Modell, wird dieser Test rot — die Seite kann nicht
    unbemerkt vom Repo-Stand wegdriften.
    """
    used = {
        m.group(1)
        for path in sorted(AGENTS_DIR.glob("*.md"))
        for m in [re.search(r"^model:\s*(\S+)", _read(path), re.M)]
        if m
    }
    assert used, "Vorbedingung geaendert: kein Agent setzt model: im Frontmatter."
    text = _read(D.MODEL_CHOICE_DOC)
    missing = sorted(alias for alias in used if f"`{alias}`" not in text)
    assert not missing, (
        f"{_rel(D.MODEL_CHOICE_DOC)} nennt diese real genutzten Agent-Modelle nicht: {missing}"
    )


def test_model_setup_is_documented() -> None:
    """Einrichtung erklaert: ``/model`` und das Subagent-Feld inkl. ``inherit`` (AC3)."""
    text = _read(D.MODEL_CHOICE_DOC)
    for needle in ("/model", "model:", "inherit"):
        assert needle in text, f"{_rel(D.MODEL_CHOICE_DOC)}: '{needle}' nicht erklaert."


# ---------------------------------------------------------------------------
# AC4 — Token-Verbrauch senken, konkret statt allgemein
# ---------------------------------------------------------------------------


def test_token_budget_doc_exists() -> None:
    """Ohne Token-Seite gibt es keinen Spar-Abschnitt (AC4)."""
    assert D.TOKEN_BUDGET_DOC.exists(), f"{_rel(D.TOKEN_BUDGET_DOC)} fehlt."


def test_token_page_names_real_levers() -> None:
    """Die genannten Stellschrauben existieren als Command-Flags (AC4)."""
    text = _read(D.TOKEN_BUDGET_DOC)
    search = _command_text("search") or ""
    missing = [lever for lever in REQUIRED_TOKEN_LEVERS if lever not in text]
    assert not missing, f"{_rel(D.TOKEN_BUDGET_DOC)}: Stellschrauben fehlen: {missing}"
    unbacked = [lever for lever in REQUIRED_TOKEN_LEVERS if lever.split()[0] not in search]
    assert not unbacked, f"commands/search.md kennt diese Flags nicht: {unbacked}"


def test_token_page_has_concrete_examples() -> None:
    """Mindestens fuenf Befehlsbeispiele statt allgemeiner Ratschlaege (AC4)."""
    blocks = [b for b in _code_blocks(_read(D.TOKEN_BUDGET_DOC)) if b.strip()]
    assert len(blocks) >= 5, (
        f"{_rel(D.TOKEN_BUDGET_DOC)}: nur {len(blocks)} Beispiele — 'sei sparsam' ist kein Beispiel."
    )


def test_token_page_covers_context_and_checkpoints() -> None:
    """Die Abschnitte 'eigener Kontext' und 'Zwischenstand sichern' existieren (AC4)."""
    headings = " | ".join(_headings(_read(D.TOKEN_BUDGET_DOC))).lower()
    for needle in ("eigener kontext", "zwischenstand"):
        assert needle in headings, f"{_rel(D.TOKEN_BUDGET_DOC)}: kein Abschnitt zu '{needle}'."


def test_token_page_references_real_checkpoint_mechanics() -> None:
    """Die Sicherungs-Mechanik ist real verdrahtet, nicht behauptet (AC4)."""
    text = _read(D.TOKEN_BUDGET_DOC)
    hook = REPO_ROOT / "hooks" / "pre-compact.mjs"
    assert hook.exists(), "Vorbedingung geaendert: hooks/pre-compact.mjs fehlt."
    assert "hooks/pre-compact.mjs" in text, (
        f"{_rel(D.TOKEN_BUDGET_DOC)}: nennt den Snapshot-Hook nicht."
    )
    assert "--restore" in text and "--restore" in (_command_text("history") or ""), (
        f"{_rel(D.TOKEN_BUDGET_DOC)}: Wiederherstellung nicht an /academic-research:history gekoppelt."
    )


# ---------------------------------------------------------------------------
# AC5 — verknuepft und erreichbar
# ---------------------------------------------------------------------------


def _internal_targets(doc: Path) -> set[Path]:
    out = set()
    for target in _LINK_RE.findall(_read(doc)):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_part = target.split("#", 1)[0]
        if path_part:
            out.add((doc.parent / path_part).resolve())
    return out


@pytest.mark.parametrize("doc", D.PRACTICE_GUIDE_DOCS, ids=lambda p: p.name)
def test_guide_pages_cross_link(doc: Path) -> None:
    """Jede Leitfaden-Seite verweist auf mindestens zwei andere (AC5)."""
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} existiert noch nicht (eigener Test deckt das ab)")
    others = {p.resolve() for p in D.PRACTICE_GUIDE_DOCS if p != doc}
    linked = _internal_targets(doc) & others
    assert len(linked) >= 2, (
        f"{_rel(doc)} verlinkt nur {len(linked)} andere Leitfaden-Seiten — "
        "ein Leitfaden ohne Querverweise ist eine Sammlung von Zetteln."
    )


@pytest.mark.parametrize("doc", D.PRACTICE_GUIDE_DOCS, ids=lambda p: p.name)
def test_docs_index_links_guide_page(doc: Path) -> None:
    """Die Doku-Uebersicht fuehrt jede Leitfaden-Seite direkt (AC5)."""
    rel = doc.relative_to(D.DOCS_DIR).as_posix()
    assert rel in _read(D.INDEX), f"{_rel(D.INDEX)} verlinkt {rel} nicht."


def test_walkthrough_links_getting_started() -> None:
    """Der Durchlauf fuehrt zurueck auf den Einstieg (AC5)."""
    assert D.GETTING_STARTED_DOC.resolve() in _internal_targets(D.WALKTHROUGH_DOC), (
        f"{_rel(D.WALKTHROUGH_DOC)} verlinkt {_rel(D.GETTING_STARTED_DOC)} nicht."
    )


# ---------------------------------------------------------------------------
# AC6 — ehrliche Nicht-Eignung
# ---------------------------------------------------------------------------


def _limits_section() -> str:
    """Alle drei Grenzarten-Abschnitte von ``limits.md`` zusammen (Issue #637).

    Das Dokument trennt kann-nicht/darf-nicht/prueft-nicht in eigene
    ##-Abschnitte (siehe ``tests/test_issue_637_limits_doc.py``); dieser Helper
    bleibt fuer die aelteren, kategorie-uebergreifenden AC6-Guards zustaendig.
    """
    sections = _sections(_read(D.LIMITS_DOC))
    matches = [
        body
        for heading, body in sections.items()
        if heading.lower().startswith("was das plugin nicht")
    ]
    assert matches, (
        f"{_rel(D.LIMITS_DOC)}: keine ##-Abschnitte zu Nicht-Eignung "
        f"(vorhanden: {sorted(sections)})."
    )
    return "\n".join(matches)


def test_best_practices_doc_exists() -> None:
    """Ohne die Seite gibt es kein bewaehrtes Vorgehen (AC6)."""
    assert D.BEST_PRACTICES_DOC.exists(), f"{_rel(D.BEST_PRACTICES_DOC)} fehlt."


def test_limits_section_is_concrete() -> None:
    """Mindestens fuenf benannte Grenzen statt einer Floskel (AC6)."""
    items = [ln for ln in _limits_section().splitlines() if ln.startswith(("- ", "* "))]
    assert len(items) >= 5, (
        f"{_rel(D.LIMITS_DOC)}: nur {len(items)} Grenzen benannt — "
        "eine Nicht-Eignung mit zwei Zeilen ist ein Feigenblatt."
    )


def test_limits_cover_the_known_boundaries() -> None:
    """Die belegbaren Grenzen sind namentlich genannt (AC6)."""
    section = _limits_section()
    missing = [needle for needle in REQUIRED_LIMIT_MARKERS if needle not in section]
    assert not missing, f"{_rel(D.LIMITS_DOC)}: Grenzen ungenannt: {missing}"
    assert re.search(r"gegenpr(ü|ue)f", section, re.I), (
        f"{_rel(D.LIMITS_DOC)}: die Zitat-Gegenpruefung fehlt als Grenze."
    )


def test_limits_are_reachable_from_the_entry_point() -> None:
    """Der Einstieg fuehrt zu den Grenzen — nicht erst die letzte Seite (AC6)."""
    assert D.LIMITS_DOC.resolve() in _internal_targets(D.GETTING_STARTED_DOC), (
        f"{_rel(D.GETTING_STARTED_DOC)} verlinkt {_rel(D.LIMITS_DOC)} nicht — "
        "wer die Grenzen erst am Ende findet, hat sie zu spaet gefunden."
    )
