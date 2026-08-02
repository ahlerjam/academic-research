"""Tests fuer Issue #537: Interactive-Gates sind Default statt Opt-in.

Die beiden Human-Gates aus #105 existieren bereits, standen aber auf
default off. Geprueft wird hier die Default-Polaritaet in den
Instruktionsdateien (das Artefakt ist die Markdown-Anweisung, nicht
Python-Verhalten):

- AC1: `/search` ohne Flags durchlaeuft Phase 1 mit Preview und Gate;
  `--interactive=off` stellt das alte Verhalten her.
- AC2: chapter-writer legt die Outline per Default zur Freigabe vor.
- AC3: Batch-/nicht-interaktive Pfade bleiben gate-frei und dokumentiert.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_MD = REPO_ROOT / "commands" / "search.md"
CHAPTER_WRITER_MD = REPO_ROOT / "skills" / "chapter-writer" / "SKILL.md"
COMMANDS_DOC = REPO_ROOT / "docs" / "reference" / "commands.md"
CONTEXT_STUB = REPO_ROOT / "scripts" / "bootstrap" / "academic_context.stub.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _arg_table_default(content: str, arg: str) -> str:
    """Liefert die Default-Spalte der Argumenttabellenzeile fuer `arg`."""
    pattern = re.compile(r"^\|\s*`" + re.escape(arg) + r"`\s*\|([^|]*)\|", re.MULTILINE)
    match = pattern.search(content)
    assert match, f"Keine Argumenttabellenzeile fuer `{arg}` in commands/search.md"
    return match.group(1).strip()


def _step_section(content: str, keyword: str) -> str:
    """Liefert den Text des `### Schritt N: ...`-Abschnitts, der `keyword` enthaelt."""
    parts = re.split(r"^### Schritt \d+: ", content, flags=re.MULTILINE)
    matches = [p for p in parts[1:] if keyword in p.splitlines()[0]]
    assert matches, f"Kein Schritt-Abschnitt mit '{keyword}' in commands/search.md"
    return matches[0]


def _numbered_section(content: str, keyword: str) -> str:
    """Liefert den Text des `### N. ...`-Abschnitts, der `keyword` enthaelt."""
    parts = re.split(r"^### \d+\. ", content, flags=re.MULTILINE)
    matches = [p for p in parts[1:] if keyword in p.splitlines()[0]]
    assert matches, f"Kein nummerierter Abschnitt mit '{keyword}' in chapter-writer/SKILL.md"
    return matches[0]


# ---------------------------------------------------------------------------
# AC1: /search ohne Flags laeuft Phase 1 mit Preview und Gate
# ---------------------------------------------------------------------------


def test_search_md_interactive_default_on() -> None:
    """Die Argumenttabelle muss fuer `--interactive` den Default `on` fuehren."""
    default = _arg_table_default(_read(SEARCH_MD), "--interactive")
    assert "`on`" in default, (
        f"Default-Spalte von --interactive ist {default!r} — erwartet wird `on` (#537)"
    )
    assert "off" not in default.lower(), (
        f"Default-Spalte von --interactive nennt weiterhin 'off': {default!r} (#537)"
    )


def test_search_md_no_interactive_off_default_claim() -> None:
    """Keine Formulierung darf `off` noch als Default/Standard behaupten."""
    content = _read(SEARCH_MD)
    offenders = re.findall(
        r"`?--?interactive=off`?[^\n]{0,40}\((?:default|Default|Standard|standard)\)",
        content,
    )
    assert not offenders, f"'--interactive=off' wird noch als Default beschrieben: {offenders}"


def test_search_md_gate_step_not_conditional() -> None:
    """Der Gate-Schritt darf nicht mehr an `--interactive` gekoppelt sein."""
    section = _step_section(_read(SEARCH_MD), "Phase 1")
    assert "diesen Schritt überspringen" not in section, (
        "Gate-Schritt enthaelt noch die Skip-Anweisung fuer den Default-Fall (#537)"
    )
    assert "nur bei `--interactive`" not in section, (
        "Gate-Schritt ist noch als 'nur bei --interactive' markiert (#537)"
    )
    assert "AskUserQuestion" in section
    for option in ("Weiter", "Anders formulieren", "Mehr Quellen", "Modul-Wahl ändern"):
        assert option in section, f"Approval-Option '{option}' fehlt im Gate-Schritt"


def test_search_md_gate_shows_query_expansion() -> None:
    """Das Preview muss die expandierten Queries aus queries.json zeigen (AC1)."""
    section = _step_section(_read(SEARCH_MD), "Phase 1")
    assert "queries.json" in section, (
        "Gate-Schritt zeigt die Query-Expansion nicht an (queries.json fehlt, #537)"
    )


def test_search_md_gate_precedes_relevance_scoring() -> None:
    """Das Gate muss VOR dem LLM-Relevanz-Scoring stehen, sonst ist es wirkungslos."""
    content = _read(SEARCH_MD)
    headings = re.findall(r"^### Schritt \d+: (.+)$", content, flags=re.MULTILINE)
    gate_idx = next(i for i, h in enumerate(headings) if "Phase 1" in h)
    scoring_idx = next(i for i, h in enumerate(headings) if "Relevanz-Scoring" in h)
    assert gate_idx < scoring_idx, (
        f"Gate steht an Position {gate_idx}, Scoring an {scoring_idx} — "
        "das Gate greift erst nach dem teuren Scoring (#537)"
    )


def test_search_md_optout_documented() -> None:
    """`--interactive=off` muss als Opt-out beschrieben sein."""
    content = _read(SEARCH_MD)
    assert "--interactive=off" in content
    assert re.search(r"Opt-out", content), (
        "commands/search.md beschreibt kein Opt-out fuer das Gate (#537)"
    )


def test_search_md_argument_hint_shows_optout() -> None:
    """Der `argument-hint` im Frontmatter muss das Opt-out zeigen, nicht das Opt-in."""
    hint = re.search(r"^argument-hint:\s*(.+)$", _read(SEARCH_MD), flags=re.MULTILINE)
    assert hint, "Kein argument-hint im Frontmatter von commands/search.md"
    assert "--interactive=off" in hint.group(1), (
        f"argument-hint bewirbt noch das Opt-in: {hint.group(1)!r} (#537)"
    )


# ---------------------------------------------------------------------------
# AC2: chapter-writer legt die Outline per Default vor
# ---------------------------------------------------------------------------


def test_chapter_writer_outline_gate_unconditional() -> None:
    """Das Outline-Gate darf keinen `/search --interactive`-Vorkontext voraussetzen."""
    section = _numbered_section(_read(CHAPTER_WRITER_MD), "Approval-Gate")
    assert "Wenn `/search --interactive` aktiv war" not in section, (
        "Outline-Gate haengt noch am /search-Vorkontext (#537)"
    )
    assert "kein Gate)" not in section, (
        "Outline-Gate hat noch einen gate-freien Default-Zweig (#537)"
    )


def test_chapter_writer_outline_gate_is_default() -> None:
    """Das Outline-Gate muss als Default formuliert sein."""
    section = _numbered_section(_read(CHAPTER_WRITER_MD), "Approval-Gate")
    assert re.search(r"standardmäßig|per Default|Default", section), (
        "Outline-Gate ist nicht als Default formuliert (#537)"
    )
    assert "AskUserQuestion" in section
    assert "Freigeben" in section


# ---------------------------------------------------------------------------
# AC3: Batch-/nicht-interaktive Pfade bleiben gate-frei und dokumentiert
# ---------------------------------------------------------------------------


def test_search_md_non_interactive_is_gate_free() -> None:
    """Die gate-freien Pfade muessen explizit benannt sein.

    Bis #632 war `--batch` einer davon; die Option ist mit der Batch-API
    entfallen, uebrig bleiben `--interactive=off` und headless-Laeufe.
    """
    section = _step_section(_read(SEARCH_MD), "Phase 1")
    assert "--batch" not in section, (
        "Gate-Schritt nennt weiterhin `--batch` -- die Option ist mit #632 entfallen"
    )
    assert "--interactive=off" in section, (
        "Gate-Schritt benennt das dokumentierte Opt-out `--interactive=off` nicht (#537)"
    )
    assert re.search(r"gate-frei|kein Gate|ohne Gate", section), (
        "Gate-Schritt benennt keinen gate-freien Pfad (#537)"
    )
    assert re.search(r"headless|nicht-interaktiv", section, re.IGNORECASE), (
        "Gate-Schritt benennt den nicht-interaktiven/headless Pfad nicht (#537)"
    )


def test_chapter_writer_optout_documented() -> None:
    """Das Outline-Gate braucht einen benannten Opt-out-Weg."""
    section = _numbered_section(_read(CHAPTER_WRITER_MD), "Approval-Gate")
    assert "Opt-out" in section, "Outline-Gate dokumentiert kein Opt-out (#537)"


def test_bootstrap_stub_documents_outline_gate() -> None:
    """Das in der SKILL.md genannte `outline_gate` muss in der Vorlage auffindbar sein.

    Ein Opt-out, das nur im Skill-Text steht, findet kein Nutzer — `humanizer_de`
    ist dafuer das Vorbild: Schluessel mit Default in
    `scripts/bootstrap/academic_context.stub.md`, Opt-out im Kommentar.
    """
    line = re.search(r"^- outline_gate:\s*(\S+)(.*)$", _read(CONTEXT_STUB), flags=re.MULTILINE)
    assert line, "`outline_gate` fehlt in scripts/bootstrap/academic_context.stub.md (#537)"
    assert line.group(1) == "on", f"Default von outline_gate ist {line.group(1)!r} — erwartet 'on'"
    assert "off" in line.group(2), f"Opt-out `off` nicht im Kommentar erklaert: {line.group(2)!r}"


def test_commands_doc_mentions_interactive() -> None:
    """docs/reference/commands.md muss `--interactive` in der /search-Syntax fuehren."""
    content = _read(COMMANDS_DOC)
    syntax = re.search(
        r"^\*\*Syntax:\*\* `/academic-research:search .*$", content, flags=re.MULTILINE
    )
    assert syntax, "Keine Syntax-Zeile fuer /academic-research:search gefunden"
    assert "--interactive" in syntax.group(0), (
        f"Syntax-Zeile fuehrt --interactive nicht: {syntax.group(0)!r} (#537)"
    )
