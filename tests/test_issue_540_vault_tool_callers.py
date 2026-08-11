"""Regressionstest fuer Issue #540 — kein registriertes MCP-Tool ohne Aufrufer.

Befund: 9 der 37 in ``academic_vault/server.py`` per ``@mcp.tool(name=...)``
registrierten Vault-Tools hatten keinen einzigen Aufrufer in der
Workflow-Oberflaeche (``skills/``, ``agents/``, ``commands/``, ``hooks/``).
Sie kosteten in jeder Session Kontext (Tool-Liste fuer 24 Agents), ohne dass
ein Workflow sie ansprach.

Dieser Test koppelt Registrierung und Verdrahtung: jedes registrierte Tool
braucht mindestens eine Referenz in einem dieser vier Verzeichnisse. ``docs/``
zaehlt bewusst NICHT mit — sonst waere der Guard tautologisch gruen, weil
``docs/reference/vault.md`` jedes Tool ohnehin auflistet.

Akzeptiert werden die drei real vorkommenden Schreibweisen:

* ``vault.<name>(`` — Skill-/Command-Prosa (die MCP-Signatur)
* ``mcp__academic-vault__vault_<name>`` — ``tools:``-Frontmatter der Agents
* ``<name>(`` bzw. ``<modul>.<name>(`` in Dateien, die ``academic_vault`` selbst
  ansprechen — die Skript-Aufrufer rufen die Python-API direkt, nicht ueber MCP
  (z. B. ``skills/material-passport/scripts/build_passport.py`` fuer
  ``export_material_passport`` oder ``hooks/mid-session-reinforcement.mjs`` fuer
  ``list_decisions``). Die Bindung an ``academic_vault`` haelt diese Form eng:
  ein gleichnamiger Methodenaufruf auf einem fremden Objekt zaehlt nicht.
"""

import re
from pathlib import Path

import pytest

from tests.helpers import docs as _docs

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / "academic_vault" / "server.py"

#: Die vier Verzeichnisse, die die Workflow-Oberflaeche bilden.
CALLER_DIRS = ("skills", "agents", "commands", "hooks")

TOOL_NAME_RE = re.compile(r'@mcp\.tool\(name="vault\.([a-z_]+)"\)')

#: Signaturzeilen der Tool-Tabellen in docs/reference/vault.md: `vault.x(...)`.
DOC_SIGNATURE_RE = re.compile(r"^\|\s*`vault\.([a-z_]+)\(")


def _registered_tools() -> list[str]:
    """Die vom Code registrierten Tool-Namen (ohne ``vault.``-Praefix)."""
    return TOOL_NAME_RE.findall(SERVER_PY.read_text(encoding="utf-8"))


def _caller_files() -> list[Path]:
    """Alle Dateien der Workflow-Oberflaeche (nicht nur Markdown)."""
    files: list[Path] = []
    for rel in _docs.committed_paths(*CALLER_DIRS):
        path = REPO_ROOT / rel
        if path.is_file():
            files.append(path)
    return files


def _caller_texts() -> list[tuple[Path, str]]:
    texts: list[tuple[Path, str]] = []
    for path in _caller_files():
        try:
            texts.append((path, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue  # Binaerdateien (z. B. Beispiel-PDFs) sind keine Aufrufer.
    return texts


def _callers_of(tool: str, texts: list[tuple[Path, str]]) -> list[str]:
    """Dateien, die ``tool`` in einer der akzeptierten Formen referenzieren.

    Die Python-Form akzeptiert neben ``<tool>(`` auch ``<tool>_report(``: einige
    MCP-Tools sind duenne Huellen um eine ``_report``-Variante, die dasselbe tut,
    aber statt eines Bool das vollstaendige Ergebnis-dict liefert (``restore_snapshot``
    -> ``restore_snapshot_report``, #857). Ein Aufrufer, der die Report-Variante
    nutzt, ruft dieselbe Operation auf und ist damit kein verwaistes Tool -- worum
    es diesem Test geht. ``commands/history.md`` etwa muss den Python-Weg nehmen
    (``allowed-tools`` erlaubt dort bewusst kein MCP), weil ``/history --restore``
    gerade dann tragen muss, wenn die Vault beschaedigt ist und der MCP-Server
    womoeglich nicht startet.
    """
    workflow_form = re.compile(rf"(?:vault\.{tool}\(|mcp__academic-vault__vault_{tool}\b)")
    python_form = re.compile(rf"(?<![\w]){tool}(?:_report)?\(")
    callers = []
    for path, text in texts:
        if workflow_form.search(text) or ("academic_vault" in text and python_form.search(text)):
            callers.append(str(path.relative_to(REPO_ROOT)))
    return callers


def test_every_registered_mcp_tool_has_a_caller() -> None:
    """AC1: Jedes ``@mcp.tool`` wird von skills/agents/commands/hooks aufgerufen."""
    texts = _caller_texts()
    orphans = [tool for tool in _registered_tools() if not _callers_of(tool, texts)]
    assert not orphans, (
        f"{len(orphans)} registrierte MCP-Tools haben keinen Aufrufer in "
        f"{'/'.join(CALLER_DIRS)}: {orphans}. Entweder verdrahten oder die "
        "@mcp.tool-Registrierung entfernen (die Python-Funktion darf interner "
        "Helfer bleiben)."
    )


def test_guard_detects_a_planted_orphan() -> None:
    """Meta-Test: der Guard ist nicht tautologisch gruen.

    Ein erfundener Tool-Name darf in keiner Datei der Workflow-Oberflaeche
    gefunden werden — faende ``_callers_of`` auch dafuer Treffer, waere die
    Suche zu lax und AC1 wertlos.
    """
    texts = _caller_texts()
    assert not _callers_of("definitely_not_a_real_vault_tool", texts)


def test_guard_does_not_count_documentation_as_a_caller() -> None:
    """Meta-Test: ``docs/`` gehoert nicht zur Aufrufer-Oberflaeche.

    ``docs/reference/vault.md`` nennt jedes Tool; zaehlte es mit, koennte der
    Guard nie rot werden. ``_caller_files()`` liefert absolute Pfade (``REPO_ROOT
    / rel``), daher hier relativ zu ``REPO_ROOT`` pruefen — ein Vergleich auf dem
    absoluten String waere immer wahr (beginnt nie mit ``"docs/"``) und der Test
    koennte nie fehlschlagen.
    """
    assert "docs" not in CALLER_DIRS
    caller_files = _caller_files()
    assert all(not str(p.relative_to(REPO_ROOT)).startswith("docs/") for p in caller_files)
    assert _docs.VAULT_DOC.exists()
    assert _docs.VAULT_DOC not in caller_files

    # Positiver Nachweis, dass der Ausschluss auch etwas bewirkt: waere
    # docs/reference/vault.md Teil der Aufrufer-Oberflaeche, wuerde JEDES
    # registrierte Tool automatisch einen "Aufrufer" bekommen, weil die
    # Referenzseite jede Signatur `vault.<name>(` auflistet — genau der Fall,
    # den dieser Guard verhindern soll.
    sample_tool = _registered_tools()[0]
    doc_text = _docs.VAULT_DOC.read_text(encoding="utf-8")
    workflow_form = re.compile(
        rf"(?:vault\.{sample_tool}\(|mcp__academic-vault__vault_{sample_tool}\b)"
    )
    assert workflow_form.search(doc_text), (
        "Testannahme verletzt: docs/reference/vault.md sollte jede "
        f"Tool-Signatur (hier {sample_tool!r}) im Format `vault.<name>(` "
        "auflisten — sonst waere die docs-Ausnahme oben ungetestet."
    )


def test_vault_doc_lists_exactly_the_registered_tools() -> None:
    """AC2: Die Tool-Tabellen der Referenz decken sich mit den Registrierungen.

    Deregistrierte Tools duerfen nicht als MCP-Signatur weiterleben (sonst
    verspricht die Doku ein Tool, das ``tools/list`` nicht kennt), und ein neu
    registriertes Tool muss dokumentiert sein.
    """
    documented = {
        match.group(1)
        for line in _docs.VAULT_DOC.read_text(encoding="utf-8").splitlines()
        if (match := DOC_SIGNATURE_RE.match(line))
    }
    registered = set(_registered_tools())
    assert not documented - registered, (
        f"docs/reference/vault.md bewirbt nicht (mehr) registrierte Tools: "
        f"{sorted(documented - registered)}"
    )
    assert not registered - documented, (
        f"Registrierte Tools fehlen in den Tabellen von docs/reference/vault.md: "
        f"{sorted(registered - documented)}"
    )


@pytest.mark.parametrize(
    ("tool", "expected_caller"),
    [
        ("add_chapter", "skills/book-handler/SKILL.md"),
        ("extract_fulltext", "skills/book-handler/SKILL.md"),
        ("get_figure", "agents/figure-verifier.md"),
        ("is_excluded", "skills/reading-list-import/SKILL.md"),
        ("list_excluded_sources", "skills/prisma-flow/SKILL.md"),
        ("add_score_snapshot", "skills/source-quality-audit/SKILL.md"),
        ("get_score_history", "skills/source-quality-audit/SKILL.md"),
        ("add_decision", "skills/academic-context/SKILL.md"),
        ("supersede_decision", "skills/academic-context/SKILL.md"),
    ],
)
def test_orphaned_tools_are_wired_into_their_workflow(tool: str, expected_caller: str) -> None:
    """AC1 konkret: die 9 Waisen haengen am fachlich passenden Workflow.

    Ein generischer "irgendwo referenziert"-Guard liesse sich mit einer
    Sammelliste erschlagen; diese Parametrisierung nagelt fest, dass der
    Aufruf dort steht, wo der Workflow ihn braucht.
    """
    callers = _callers_of(tool, _caller_texts())
    assert expected_caller in callers, (
        f"vault.{tool} ist nicht in {expected_caller} verdrahtet (Aufrufer: {callers})"
    )
