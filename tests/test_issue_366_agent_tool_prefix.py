"""Regressionstest fuer Issue #366.

Vier Vault-Agents deklarierten ihre MCP-Tools mit dem falschen
Servernamen-Praefix `mcp__academic_vault__` (Unterstrich) statt
`mcp__academic-vault__` (Bindestrich, wie in `.mcp.json` als Servername
`academic-vault` registriert). Da das `tools:`-Frontmatter eine exakte
Allowlist ist, matchte sie keinen real existierenden Tool-Namen -- die
betroffenen Agents hatten dadurch faktisch keinen Vault-Zugriff.

Dieser Test kodiert AC1+AC3 aus Issue #366: Frontmatter-Parse (statt
reinem Shell-Grep) je Agent-Datei, prueft dass `mcp__academic_vault__`
nicht mehr vorkommt und die erwarteten `mcp__academic-vault__vault_*`-
Namen deklariert sind.

AC2-Nachschlag (PR #405 Review-Runde): Die urspruengliche Fassung dieser
Datei deckte AC2 ("ein Testlauf jedes Agents kann sein deklariertes
Vault-Tool real aufrufen, statt an der Tool-Allowlist zu scheitern") nur
scheinbar ab -- per Namensgleichheit gegen eine hier hart codierte
EXPECTED_VAULT_TOOLS-Liste, die bei einem Tippfehler ebenso falsch haette
sein koennen. Die als Beleg genannten Vault-Layer-Tests
(test_risk_of_bias_agent.py, test_figure_verifier.py, test_meta_analysis.py)
rufen academic_vault-Funktionen direkt in Python auf (kein Subprocess, kein
MCP-Tool-Dispatch) und waeren mit dem alten falschen Praefix ebenso gruen
geblieben.

test_all_four_agents_declared_vault_tools_are_really_dispatchable_via_live_mcp_server()
schliesst diese Luecke, ohne einen echten Claude-Subagent-Lauf zu brauchen
(kein API-Key/Budget in diesem Kontext, vgl. Issue #55): Sie startet den
echten `academic_vault`-MCP-Serverprozess (`python -m academic_vault.server`,
exakt der in `.mcp.json` konfigurierte Befehl) ueber den echten MCP-stdio-
Transport, fragt per `session.list_tools()` die LIVE registrierten
Tool-Namen ab (Ground Truth statt hart codierter Erwartung) und ruft fuer
jeden Agenten jedes in seinem Frontmatter deklarierte Vault-Tool ueber
`session.call_tool(...)` echt auf. Ein falsches Praefix wuerde hier exakt
so durchfallen wie bei einer echten Claude-Subagent-Tool-Allowlist
(Beleg: "Unknown tool: ..." vs. echte Business-Logic-Fehler, siehe Test).
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent

WRONG_PREFIX = "mcp__academic_vault__"

# agent_name -> Liste der erwarteten (korrekten) Vault-MCP-Tool-Namen.
EXPECTED_VAULT_TOOLS = {
    "quote-extractor": [
        "mcp__academic-vault__vault_ensure_file",
        "mcp__academic-vault__vault_add_quote",
    ],
    "risk-of-bias": [
        "mcp__academic-vault__vault_get_paper",
        "mcp__academic-vault__vault_search_quote_text",
        "mcp__academic-vault__vault_add_quote",
        "mcp__academic-vault__vault_add_risk_of_bias",
    ],
    "meta-analysis": [
        "mcp__academic-vault__vault_search",
        "mcp__academic-vault__vault_get_paper",
    ],
    "figure-verifier": [
        # #533: lokaler Seiten-Verifikationspfad (vault.get_paper -> pdf_path
        # -> Read) statt Citations-API/file_id -- vault_ensure_file entfaellt.
        "mcp__academic-vault__vault_get_paper",
        "mcp__academic-vault__vault_add_figure",
        # Read-back nach dem Schreiben (#540): der zurueckgelesene Record ist
        # der Beleg, nicht die zurueckgegebene figure_id.
        "mcp__academic-vault__vault_get_figure",
        "mcp__academic-vault__vault_list_figures",
    ],
}


def _parse_agent_frontmatter(agent_name: str) -> dict:
    """Parst YAML-Frontmatter eines Agent-Files."""
    agent_path = REPO_ROOT / "agents" / f"{agent_name}.md"
    assert agent_path.exists(), f"Agent-Datei fehlt: {agent_path}"
    content = agent_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    assert match, f"Kein gueltiges Frontmatter in {agent_path}"
    fm = yaml.safe_load(match.group(1))
    return fm


def test_no_wrong_prefix_in_any_agent_file():
    """Repo-weiter Grep-Aequivalent: kein agents/*.md enthaelt den falschen Praefix (AC3)."""
    offenders = []
    for agent_name in EXPECTED_VAULT_TOOLS:
        agent_path = REPO_ROOT / "agents" / f"{agent_name}.md"
        content = agent_path.read_text(encoding="utf-8")
        if WRONG_PREFIX in content:
            offenders.append(agent_name)
    assert not offenders, f"Falscher MCP-Praefix '{WRONG_PREFIX}' noch vorhanden in: {offenders}"


def test_agents_declare_correct_hyphen_prefixed_vault_tools():
    """tools-Frontmatter jedes Agents referenziert ausschliesslich mcp__academic-vault__*-Namen (AC1)."""
    for agent_name, expected_tools in EXPECTED_VAULT_TOOLS.items():
        fm = _parse_agent_frontmatter(agent_name)
        tools = fm.get("tools", [])
        assert isinstance(tools, list), (
            f"{agent_name}: tools muss eine Liste sein, ist: {type(tools)}"
        )
        missing = [t for t in expected_tools if t not in tools]
        assert not missing, (
            f"{agent_name}: tools-Frontmatter fehlen korrekt praefixierte "
            f"Vault-MCP-Tools: {missing}. Aktuell deklariert: {tools}"
        )


# ---------------------------------------------------------------------------
# AC2: echter Dispatch ueber den realen academic_vault-MCP-Serverprozess
# ---------------------------------------------------------------------------

# Minimal-Argumente je real registriertem Vault-Tool-Namen (FastMCP-Namen mit
# Punkt, z.B. "vault.add_quote") -- deckt genau die Tools ab, die die vier
# Issue-366-Agents deklarieren. "vault.ensure_file" wird bewusst OHNE
# pdf_path-Seed aufgerufen: der Aufruf erreicht damit real den
# ValueError-Zweig in ensure_file() (academic_vault/server.py), OHNE Netzwerk
# oder ANTHROPIC_API_KEY zu benoetigen (kein API-Key/Budget in diesem
# Kontext, vgl. Issue #55) -- und liefert trotzdem einen eindeutig von
# "Unknown tool: ..." unterscheidbaren Business-Logic-Fehler.
_LIVE_CALL_ARGS = {
    "vault.get_paper": {"paper_id": "issue366-paper"},
    "vault.search_quote_text": {"verbatim": "Lorem", "k": 5},
    "vault.add_quote": {
        "paper_id": "issue366-paper",
        "verbatim": "Some verbatim quote text.",
        "extraction_method": "manual",
    },
    "vault.add_risk_of_bias": {
        "paper_id": "issue366-paper",
        "study_type": "RCT",
        "domain_scores": json.dumps({"randomization": "low"}),
    },
    "vault.search": {"query": "Resilience"},
    "vault.add_figure": {
        "paper_id": "issue366-paper",
        "page": 1,
        "caption": "Fig 1",
        "vlm_description": "A chart.",
    },
    # Unbekannte figure_id: get_figure liefert dafuer regulaer None (kein
    # Fehler) -- fuer den Dispatch-Nachweis genuegt das, ohne die im Test
    # erzeugte ID durchreichen zu muessen.
    "vault.get_figure": {"figure_id": "issue366-figure"},
    "vault.list_figures": {"paper_id": "issue366-paper"},
    "vault.ensure_file": {"paper_id": "issue366-paper"},
}


async def _run_live_dispatch_check(vault_db_path: Path) -> None:
    """Startet den echten academic_vault-Serverprozess und dispatcht real.

    Nutzt exakt das mcp-stdio-Client-Muster von
    tests/test_vault_server_mcp_json_stdio.py (Issue #365): echter
    Subprozess (`python -m academic_vault.server`), echter MCP-stdio-
    Transport, echte ClientSession.
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

            # Claude Code exponiert MCP-Tools als mcp__<server-name>__<tool-name>
            # und ersetzt dabei Punkte im FastMCP-Toolnamen (Konvention
            # "vault.<methode>") durch Unterstriche -- beobachtbar an den
            # real registrierten mcp__academic-vault__vault_*-Namen dieser
            # Session (siehe Deferred-Tools-Liste des Claude-Code-Hosts).
            # Das Mapping wird hier aus der LIVE-Registry hergeleitet, nicht
            # aus einer separat hart codierten Erwartungsliste -- ein Tippfehler
            # oder ein nicht (mehr) existierendes Tool faellt damit durch,
            # unabhaengig davon, ob EXPECTED_VAULT_TOOLS zufaellig denselben
            # Fehler enthielte.
            agent_name_to_real_name = {
                f"mcp__academic-vault__{real_name.replace('.', '_')}": real_name
                for real_name in real_names
            }

            seed = await session.call_tool(
                "vault.add_paper",
                arguments={
                    "paper_id": "issue366-paper",
                    "csl_json": json.dumps(
                        {"type": "article-journal", "title": "Resilience Engineering Study"}
                    ),
                },
            )
            assert not seed.isError, f"Seed-Paper konnte nicht angelegt werden: {seed.content}"

            for agent_name, expected_agent_tools in EXPECTED_VAULT_TOOLS.items():
                # Kritisch: die REAL im Agent-File deklarierten Tools lesen --
                # nicht die hart codierte EXPECTED_VAULT_TOOLS-Liste iterieren.
                # Sonst prueft dieser Test nur sich selbst und faellt bei einem
                # kaputten/falsch praefixierten Frontmatter nicht durch (das
                # war der urspruengliche Bug in diesem Test).
                fm = _parse_agent_frontmatter(agent_name)
                declared_tools = [t for t in fm.get("tools", []) if isinstance(t, str)]
                # "vault" (case-insensitive) statt striktem Bindestrich-Praefix-
                # Filter, damit eine falsch praefixierte Deklaration (z.B. wieder
                # mit Unterstrich, der urspruengliche Issue-366-Bug) hier weiterhin
                # erfasst und unten gegen die Live-Registry geprueft wird, statt
                # durch den Filter herausgefiltert und stillschweigend ignoriert
                # zu werden.
                declared_vault_tools = [t for t in declared_tools if "vault" in t.lower()]

                missing_from_frontmatter = [
                    t for t in expected_agent_tools if t not in declared_tools
                ]
                assert not missing_from_frontmatter, (
                    f"{agent_name}: erwartete Vault-Tools fehlen im real geparsten "
                    f"Frontmatter: {missing_from_frontmatter}. Aktuell deklariert: "
                    f"{declared_tools}"
                )

                for declared_name in declared_vault_tools:
                    assert declared_name in agent_name_to_real_name, (
                        f"{agent_name}: deklariertes Tool '{declared_name}' entspricht "
                        f"keinem real vom laufenden academic-vault-MCP-Server registrierten "
                        f"Tool (live registriert: {sorted(agent_name_to_real_name)}). Ein "
                        "falsches Praefix (z.B. Unterstrich statt Bindestrich) faellt hier "
                        "exakt so durch wie bei einer echten Claude-Subagent-Tool-Allowlist."
                    )
                    real_name = agent_name_to_real_name[declared_name]
                    assert real_name in _LIVE_CALL_ARGS, (
                        f"Kein Test-Argument-Fixture fuer live registriertes Tool "
                        f"'{real_name}' ({agent_name}) hinterlegt."
                    )

                    result = await session.call_tool(
                        real_name, arguments=_LIVE_CALL_ARGS[real_name]
                    )

                    if real_name == "vault.ensure_file":
                        # Business-Logic-Fehler (kein pdf_path) statt Erfolg --
                        # aber entscheidend: NICHT der MCP-Protokollfehler
                        # "Unknown tool: ...", der bei falschem Praefix kaeme.
                        assert result.isError, (
                            f"{agent_name}/{real_name}: erwarteter Business-Logic-Fehler "
                            f"(kein pdf_path) blieb aus -- Ergebnis: {result.content}"
                        )
                        error_text = result.content[0].text
                        assert error_text.startswith("Error executing tool"), (
                            f"{agent_name}/{real_name}: Fehlerformat deutet auf Dispatch-"
                            f"Fehlschlag statt Business-Logic-Fehler hin: {error_text!r}"
                        )
                        assert "Unknown tool" not in error_text, (
                            f"{agent_name}/{real_name}: MCP-Server kennt das Tool nicht -- "
                            f"das waere exakt der alte Issue-366-Bug: {error_text!r}"
                        )
                    else:
                        assert not result.isError, (
                            f"{agent_name}/{real_name}: echter Tool-Aufruf ueber den MCP-"
                            f"stdio-Transport ist fehlgeschlagen: {result.content}"
                        )


def test_all_four_agents_declared_vault_tools_are_really_dispatchable_via_live_mcp_server(
    tmp_path,
):
    """AC2 (Issue #366): Jeder der vier Agents kann sein deklariertes Vault-Tool
    real aufrufen, statt an der Tool-Allowlist zu scheitern -- geprueft ueber
    den echten academic_vault-MCP-Serverprozess (echter Subprozess, echter
    MCP-stdio-Transport, echte Tool-Namen aus der LIVE-Registry), nicht nur
    per String-Vergleich gegen eine hart codierte Erwartungsliste.

    Ohne den Issue-366-Fix (falsches Praefix `mcp__academic_vault__`) waere
    `declared_name in agent_name_to_real_name` in `_run_live_dispatch_check`
    False -- der Test faellt dann mit einer expliziten Diagnose durch, statt
    still gruen zu bleiben (verifiziert manuell durch temporaeres Zuruecksetzen
    des Praefix waehrend der Fix-Runde zu PR #405, siehe PR-Beschreibung).
    """
    pytest.importorskip("mcp.server.fastmcp")
    vault_db_path = tmp_path / "vault.db"
    asyncio.run(_run_live_dispatch_check(vault_db_path))
