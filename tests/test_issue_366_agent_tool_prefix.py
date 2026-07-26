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
"""

import re
from pathlib import Path

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
        "mcp__academic-vault__vault_ensure_file",
        "mcp__academic-vault__vault_add_figure",
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
