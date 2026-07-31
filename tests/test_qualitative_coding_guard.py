"""Tests fuer Issue #473 AC4 — Interviewzitate unterliegen derselben Belegpruefung.

Ein Zitat aus eigenem Erhebungsmaterial durchlaeuft exakt denselben
``hooks/verbatim-guard.mjs``-Codepfad wie ein Literaturzitat: verifiziert →
``exit 0``, erfunden → ``exit 2``. Kein Sonderweg fuer Primaermaterial.

Der Hook wird als Node-Subprocess mit einer echten Test-DB (``VAULT_DB_PATH``)
gestartet — ohne DB waere der Guard fail-open und ein gruener Test bewiese
nichts (Issue #381).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export-literature-state.mjs"

INTERVIEW_QUOTE = "Die Abstimmung ist hilfreich, aber sie kostet auch Zeit"


def _run_hook(file_path: str, content: str, db_path: str) -> subprocess.CompletedProcess:
    payload = json.dumps(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }
    )
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = db_path
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@pytest.fixture
def vault_with_interview_quote(tmp_path):
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="interview-01",
        csl_json=json.dumps({"title": "Interview 01", "type": "article-journal"}),
        source_kind="primary",
    )
    db.add_quote(
        quote_id="q-interview-01-5",
        paper_id="interview-01",
        verbatim=INTERVIEW_QUOTE,
        extraction_method="manual",
        section="Abs. 5",
    )
    return db_path


def test_guard_allows_verified_interview_quote(vault_with_interview_quote):
    content = f'Die Befragte formuliert es so: "{INTERVIEW_QUOTE}".'
    result = _run_hook("kapitel/4-ergebnisse.md", content, vault_with_interview_quote)
    assert result.returncode == 0, (
        f"Erwartet 0 (verifiziertes Interviewzitat), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )


def test_guard_blocks_invented_interview_quote(vault_with_interview_quote):
    content = 'Die Befragte sagt: "Die Abstimmung im Team war fuer mich vollkommen nutzlos".'
    result = _run_hook("kapitel/4-ergebnisse.md", content, vault_with_interview_quote)
    assert result.returncode == 2, (
        f"Erwartet 2 (erfundenes Interviewzitat), got {result.returncode}. stderr: {result.stderr}"
    )
    assert "Vault" in result.stderr, (
        f"Block-Meldung nennt den Vault-Abgleich nicht: {result.stderr}"
    )


def test_transcript_not_listed_as_literature(tmp_path):
    """``export-literature-state`` fuehrt Primaermaterial nicht als Literatur."""
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="mueller2021",
        csl_json=json.dumps({"title": "Zusammenarbeit in Teams", "type": "article-journal"}),
    )
    db.add_paper(
        paper_id="interview-01",
        csl_json=json.dumps({"title": "Interview 01", "type": "article-journal"}),
        source_kind="primary",
    )

    out = tmp_path / "literature_state.md"
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = db_path
    result = subprocess.run(
        ["node", str(EXPORT_SCRIPT), "--output", str(out)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert "mueller2021" in text, "Literatur-Paper fehlt im Snapshot"
    assert "interview-01" not in text, (
        "Transkript erscheint als Literaturquelle im Literatur-Snapshot"
    )
