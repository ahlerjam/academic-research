"""Tests fuer Issue #514: quote-extractor ohne Citations-API.

`agents/quote-extractor.md` wird auf den lokalen Verifikationspfad
(`vault.get_paper` -> `pdf_path` -> `Read`, Persistenz via
`extraction_method="local-verbatim"`) umgestellt, analog zu `figure-verifier`
(#533) und `risk-of-bias`. Der bisherige Citations-API-Block
(`client.beta.messages.create`, Files-API) entfaellt im Standardpfad zugunsten
eines kurzen Opt-in-Hinweises.

AC -> Testfall (siehe Issue #514 / Plan-Kommentar):
  - AC1 keine `client.beta.*`-Aufrufe mehr im Standardpfad:
    :func:`test_agent_default_workflow_has_no_client_beta_code_blocks`,
    :func:`test_tools_frontmatter_drops_ensure_file_and_requires_get_paper`
  - AC2 ohne ANTHROPIC_API_KEY werden Zitate extrahiert und landen mit
    `local-verbatim` im Vault: :class:`TestAc2LocalVerbatimWithoutApiKey`
  - AC3 Qualitaetsregeln bleiben erhalten (<=25 Woerter, max 3/Paper,
    `possible_pdf_mismatch`, "lieber 0 als schlechte Zitate"):
    :func:`test_quality_rules_still_documented`
"""

import os
import re
import sqlite3
from pathlib import Path

from academic_vault.db import VaultDB
from academic_vault.server import add_quote, get_quote

REPO_ROOT = Path(__file__).parent.parent
AGENT_PATH = REPO_ROOT / "agents" / "quote-extractor.md"

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "verbatim")
SOURCE_PDF = os.path.join(FIXTURES, "verbatim_source.pdf")

_PAPER_ID = "qe514-fixture"
_CSL = '{"title": "Quote Extractor Fixture"}'
CANDIDATE_EXACT_PAGE2 = 'Die Teilnehmenden beschrieben "implizites Wissen" als zentralen Faktor.'


def _agent_content() -> str:
    return AGENT_PATH.read_text(encoding="utf-8")


def _agent_frontmatter() -> dict:
    import yaml

    match = re.match(r"^---\n(.*?)\n---\n(.*)", _agent_content(), re.DOTALL)
    assert match, f"Kein gueltiges Frontmatter in {AGENT_PATH}"
    return yaml.safe_load(match.group(1))


def _quote_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0])
    finally:
        conn.close()


def _vault_with_paper(tmp_path, pdf_path: str | None) -> str:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(_PAPER_ID, _CSL, pdf_path=pdf_path)
    return db_path


# ---------------------------------------------------------------------------
# AC1: keine client.beta.*-Aufrufe mehr im Standardpfad
# ---------------------------------------------------------------------------


def test_agent_default_workflow_has_no_client_beta_code_blocks():
    """Kein ausfuehrbarer Code-Block im Agent-File ruft noch `client.beta.*` auf.

    Ein kurzer Opt-in-Prosa-Hinweis (ohne Code-Block) auf die Citations-API
    ist laut Issue-Body erlaubt -- ein `client.beta.messages.create(...)`-
    Aufruf innerhalb eines Fenced-Code-Blocks (der bisherige Pflichtpfad)
    nicht mehr.
    """
    content = _agent_content()
    code_blocks = re.findall(r"```(?:python|json)?\n(.*?)```", content, re.DOTALL)
    offending = [b for b in code_blocks if "client.beta" in b]
    assert not offending, (
        f"agents/quote-extractor.md enthaelt noch client.beta-Code-Bloecke im "
        f"Standardpfad: {offending}"
    )


def test_tools_frontmatter_drops_ensure_file_and_requires_get_paper():
    """`tools:`-Frontmatter: `vault_ensure_file` entfaellt, `vault_get_paper` ist Pflicht."""
    fm = _agent_frontmatter()
    tools = fm.get("tools", [])
    assert "mcp__academic-vault__vault_get_paper" in tools, (
        f"vault_get_paper fehlt im tools-Frontmatter: {tools}"
    )
    assert "mcp__academic-vault__vault_add_quote" in tools, (
        f"vault_add_quote fehlt im tools-Frontmatter: {tools}"
    )
    assert "mcp__academic-vault__vault_ensure_file" not in tools, (
        f"vault_ensure_file sollte im Standardpfad nicht mehr Pflicht-Tool sein: {tools}"
    )
    assert "Read" in tools, f"Read-Tool (fuer natives PDF-Lesen) fehlt: {tools}"


# ---------------------------------------------------------------------------
# AC2: ohne ANTHROPIC_API_KEY werden Zitate extrahiert und landen mit
# extraction_method="local-verbatim" im Vault.
# ---------------------------------------------------------------------------


class TestAc2LocalVerbatimWithoutApiKey:
    def test_local_verbatim_succeeds_without_api_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        db_path = _vault_with_paper(tmp_path, SOURCE_PDF)

        quote_id = add_quote(
            db_path=db_path,
            paper_id=_PAPER_ID,
            verbatim=CANDIDATE_EXACT_PAGE2,
            extraction_method="local-verbatim",
        )

        record = get_quote(db_path, quote_id)
        assert record is not None
        assert record["extraction_method"] == "local-verbatim"
        assert record["verbatim"] == CANDIDATE_EXACT_PAGE2
        assert record["pdf_page"] == 2
        assert _quote_count(db_path) == 1


# ---------------------------------------------------------------------------
# AC3: Qualitaetsregeln bleiben erhalten.
# ---------------------------------------------------------------------------


def test_quality_rules_still_documented():
    content = _agent_content()
    assert "25 Wörter" in content, "≤25-Woerter-Regel fehlt im Agent-File"
    assert re.search(r"max\.?\s*3", content), "max-3-Zitate-Regel fehlt im Agent-File"
    assert '"possible_pdf_mismatch"' in content, "possible_pdf_mismatch-Flag fehlt"
    assert "Lieber 0 Zitate" in content, "'Lieber 0 Zitate als schlechte Zitate' fehlt"


def test_agent_persistence_section_uses_local_verbatim():
    """Der Vault-Persistenz-Abschnitt referenziert lokale Verifikation statt Citations-API."""
    content = _agent_content()
    assert 'extraction_method="local-verbatim"' in content or (
        'extraction_method="local-verbatim"' in content
    )
    assert "vault.get_paper" in content
