"""Integrationstest fuer Issue #365 -- realer Server-Prozess via MCP-stdio.

Startet ``python -m academic_vault.server`` als echten Subprozess mit genau
dem Env-Muster, das ``.mcp.json`` nach dem Fix verwendet (PYTHONPATH,
SQLITE_VEC_PATH -- OHNE manuell gesetztes VAULT_DB_PATH) und ruft
``vault.add_paper`` ueber den echten MCP-stdio-Transport auf. Beweist AC3:
kein ``sqlite3.OperationalError``, DB-Datei landet am erwarteten
kanonischen Pfad.

``HOME`` wird pro Testlauf strikt auf ``tmp_path`` isoliert, damit reale
Nutzer-Vaults nicht beruehrt werden.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.fastmcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


async def _run_add_paper_via_stdio(env: dict[str, str], cwd: str) -> dict:
    """Startet den echten Server-Prozess, ruft vault.add_paper auf und gibt
    das anschliessend per vault.get_paper gelesene Paper zurueck."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "academic_vault.server"],
        env=env,
        cwd=cwd,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "vault.add_paper" in names, f"vault.add_paper fehlt: {sorted(names)}"

            csl_json = json.dumps({"type": "article-journal", "title": "Issue 365 Regressionstest"})
            await session.call_tool(
                "vault.add_paper",
                arguments={
                    "paper_id": "issue365-paper",
                    "csl_json": csl_json,
                },
            )

            result = await session.call_tool(
                "vault.get_paper",
                arguments={"paper_id": "issue365-paper"},
            )
            assert not result.isError, f"vault.get_paper meldete Fehler: {result.content}"
            payload = json.loads(result.content[0].text)
            return payload


def test_real_mcp_json_server_process_add_paper_writes_without_operational_error(
    tmp_path,
):
    """AC3: unveraenderter .mcp.json-Serverprozess (kein manuelles
    VAULT_DB_PATH) schreibt add_paper erfolgreich in die DB."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    project_dir = tmp_path / "mein-forschungsprojekt"
    project_dir.mkdir()

    # Env exakt wie .mcp.json nach dem Fix: PYTHONPATH + SQLITE_VEC_PATH,
    # OHNE VAULT_DB_PATH. HOME isoliert auf tmp_path, CLAUDE_PROJECT_DIR wie
    # Claude Code es an den gespawnten Server-Subprozess uebergeben wuerde.
    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["SQLITE_VEC_PATH"] = ""
    env.pop("VAULT_DB_PATH", None)

    payload = asyncio.run(_run_add_paper_via_stdio(env, str(project_dir)))

    assert payload is not None, "vault.get_paper lieferte None -- add_paper hat nicht geschrieben"
    assert payload["paper_id"] == "issue365-paper"

    expected_db = (
        fake_home / ".academic-research" / "projects" / "mein-forschungsprojekt" / "vault.db"
    )
    assert expected_db.exists(), f"vault.db wurde nicht am kanonischen Pfad angelegt: {expected_db}"
