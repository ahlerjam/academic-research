"""Tests fuer den chunk-context-writer-Agenten und seine fetch.md-Einbindung (#784).

Der Agent selbst ruft `claude -p` (echte API-Kosten) und ist damit kein
Kandidat fuer einen hermetischen pytest-Lauf -- die reale Verhaltens- und
Kostenmessung deckt `scripts/eval/measure_context_enrichment_710.py` ab
(gated hinter `VAULT_CONTEXT_LIVE_TRANSFORM=1`, kein Teil dieser Suite).

Diese Datei deckt, was ohne API-Kosten pruefbar ist:

  AC1  Frontmatter: name/description (inkl. zwei <example>-Bloecke,
       AGENTS.md-Konvention)/model/tools/maxTurns.
  AC2  `tools:` referenziert exakt die zwei MCP-Tools aus #783, mit dem
       korrekten `mcp__academic-vault__`-Praefix (Issue-366-Regression).
  AC3  Live-Dispatch: beide deklarierten Tools sind ueber den echten
       academic-vault-MCP-Server real aufrufbar (kein API-Key/Budget noetig,
       Muster aus `tests/test_issue_366_agent_tool_prefix.py`).
  AC4  `commands/fetch.md`: `Agent(chunk-context-writer)` steht in
       `allowed-tools` UND wird im Body (Schritt 4, Bei `success`)
       tatsaechlich aufgerufen (Konsistenz-Muster aus
       `tests/test_issue_238_search_allowed_tools_consistency.py`).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
AGENT_PATH = REPO_ROOT / "agents" / "chunk-context-writer.md"
FETCH_COMMAND = REPO_ROOT / "commands" / "fetch.md"

EXPECTED_TOOLS = [
    "mcp__academic-vault__vault_pending_context_chunks",
    "mcp__academic-vault__vault_enrich_chunk_contexts",
]


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "Frontmatter-Start '---' fehlt"
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    assert end is not None, "Frontmatter-Ende '---' fehlt"
    frontmatter = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    return frontmatter, body


def _agent_frontmatter() -> dict:
    text = AGENT_PATH.read_text(encoding="utf-8")
    fm, _ = _split_frontmatter(text)
    return yaml.safe_load(fm)


# ---------------------------------------------------------------------------
# AC1 -- Frontmatter-Grundstruktur (AGENTS.md-Konvention)
# ---------------------------------------------------------------------------


def test_agent_file_exists():
    assert AGENT_PATH.exists(), f"Missing: {AGENT_PATH}"


def test_frontmatter_name_matches_filename():
    fm = _agent_frontmatter()
    assert fm.get("name") == "chunk-context-writer"


def test_frontmatter_description_present_and_nonempty():
    fm = _agent_frontmatter()
    desc = fm.get("description")
    assert desc and len(str(desc).strip()) > 40, "description fehlt oder ist zu kurz"


def test_frontmatter_description_has_two_example_blocks():
    """AGENTS.md/plugin-dev-Konvention: Pflicht-description + zwei <example>-Bloecke."""
    fm = _agent_frontmatter()
    desc = str(fm.get("description", ""))
    assert desc.count("<example>") == 2, (
        f"Erwartet genau 2 <example>-Bloecke, gefunden: {desc.count('<example>')}"
    )
    assert desc.count("</example>") == 2
    assert desc.count("<commentary>") == 2


def test_frontmatter_model_is_sonnet():
    fm = _agent_frontmatter()
    assert fm.get("model") == "sonnet"


def test_frontmatter_max_turns_is_six():
    fm = _agent_frontmatter()
    assert fm.get("maxTurns") == 6


# ---------------------------------------------------------------------------
# AC2 -- tools: exakt die zwei #783-MCP-Tools, korrektes Praefix
# ---------------------------------------------------------------------------


def test_frontmatter_tools_are_exactly_the_two_context_tools():
    fm = _agent_frontmatter()
    tools = fm.get("tools", [])
    assert isinstance(tools, list), f"tools muss eine Liste sein, ist: {type(tools)}"
    assert sorted(tools) == sorted(EXPECTED_TOOLS), (
        f"tools weicht von den erwarteten #783-Tools ab: {tools}"
    )


def test_no_wrong_underscore_prefix():
    """Regression wie Issue #366: mcp__academic_vault__ (Unterstrich) ist falsch."""
    text = AGENT_PATH.read_text(encoding="utf-8")
    assert "mcp__academic_vault__" not in text


# ---------------------------------------------------------------------------
# AC3 -- Live-Dispatch ueber den echten academic-vault-MCP-Server
# ---------------------------------------------------------------------------

_LIVE_CALL_ARGS = {
    "vault.pending_context_chunks": {"paper_id": "issue784-paper", "limit": 16},
    # chunk_id "nicht-vorhanden" landet regulaer in skipped (reason "not-found"),
    # kein Fehler -- ausreichend, um den echten Dispatch zu belegen, ohne vorher
    # ueber pending_context_chunks eine echte chunk_id auflösen zu muessen.
    "vault.enrich_chunk_contexts": {
        "items": [{"chunk_id": "nicht-vorhanden", "context_sentence": "Ein Testsatz."}]
    },
}


async def _run_live_dispatch_check(vault_db_path: Path) -> None:
    """Startet den echten academic_vault-MCP-Serverprozess, ruft beide Tools real auf.

    Muster aus `tests/test_issue_366_agent_tool_prefix.py::_run_live_dispatch_check`
    -- kein API-Key/Budget noetig (Issue #55), echter stdio-Transport, echte
    ClientSession.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["SQLITE_VEC_PATH"] = ""
    env["VAULT_DB_PATH"] = str(vault_db_path)
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "academic_vault.server"],
        env=env,
        cwd=str(REPO_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            live_tools = await session.list_tools()
            real_names = {t.name for t in live_tools.tools}
            agent_name_to_real_name = {
                f"mcp__academic-vault__{real_name.replace('.', '_')}": real_name
                for real_name in real_names
            }

            seed = await session.call_tool(
                "vault.add_paper",
                arguments={
                    "paper_id": "issue784-paper",
                    "csl_json": json.dumps({"type": "article-journal", "title": "Issue 784 Test"}),
                },
            )
            assert not seed.isError, f"Seed-Paper konnte nicht angelegt werden: {seed.content}"

            fm = _agent_frontmatter()
            declared_tools = [t for t in fm.get("tools", []) if isinstance(t, str)]
            for declared_name in declared_tools:
                assert declared_name in agent_name_to_real_name, (
                    f"'{declared_name}' entspricht keinem real registrierten Tool "
                    f"(live registriert: {sorted(agent_name_to_real_name)})"
                )
                real_name = agent_name_to_real_name[declared_name]
                assert real_name in _LIVE_CALL_ARGS, (
                    f"Kein Test-Argument-Fixture fuer '{real_name}' hinterlegt."
                )
                result = await session.call_tool(real_name, arguments=_LIVE_CALL_ARGS[real_name])
                assert not result.isError, (
                    f"{real_name}: echter Tool-Aufruf ueber den MCP-stdio-Transport "
                    f"ist fehlgeschlagen: {result.content}"
                )


def test_both_declared_tools_are_really_dispatchable_via_live_mcp_server(tmp_path):
    pytest.importorskip("mcp.server.fastmcp")
    vault_db_path = tmp_path / "vault.db"
    asyncio.run(_run_live_dispatch_check(vault_db_path))


# ---------------------------------------------------------------------------
# AC4 -- fetch.md: allowed-tools <-> Body-Konsistenz
# ---------------------------------------------------------------------------


def _fetch_frontmatter_and_body() -> tuple[str, str]:
    text = FETCH_COMMAND.read_text(encoding="utf-8")
    return _split_frontmatter(text)


def _allowed_tools_line(frontmatter: str) -> str:
    for line in frontmatter.splitlines():
        if line.strip().startswith("allowed-tools:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("Kein 'allowed-tools:' in fetch.md-Frontmatter gefunden")


def test_fetch_allowed_tools_declares_chunk_context_writer():
    frontmatter, _ = _fetch_frontmatter_and_body()
    allowed = _allowed_tools_line(frontmatter)
    assert "Agent(chunk-context-writer)" in allowed, (
        f"'Agent(chunk-context-writer)' nicht in fetch.md allowed-tools: {allowed!r}"
    )


def test_fetch_body_invokes_chunk_context_writer():
    _, body = _fetch_frontmatter_and_body()
    assert "Agent(chunk-context-writer)" in body, (
        "fetch.md deklariert den Agenten in allowed-tools, ruft ihn aber nie im Body auf "
        "(Konsistenz-Regel aus Issue #238)."
    )


def test_fetch_body_documents_non_blocking_failure():
    """AC aus #784: ein Ausbleiben/Scheitern des Aufrufs blockiert den Rest des Ablaufs nicht."""
    _, body = _fetch_frontmatter_and_body()
    success_section_match = re.search(r"#### Bei `success`.*?(?=\n#### Bei|\Z)", body, re.DOTALL)
    assert success_section_match, "Abschnitt 'Bei success' nicht gefunden"
    success_section = success_section_match.group(0)
    assert "Agent(chunk-context-writer)" in success_section
    assert "folgenlos" in success_section.lower() or "blockiert" in success_section.lower(), (
        "Der success-Abschnitt muss explizit machen, dass ein Scheitern des "
        "Anreicherungs-Aufrufs den restlichen Ablauf nicht blockiert."
    )
