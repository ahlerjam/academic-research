"""Tests fuer den quote-fidelity-auditor-Agenten (Issue #523).

Der Agent urteilt ueber ein bestehendes Zitat (Kapitel-Behauptung vs.
Quote-Kontext vs. Paper-Abstract) und persistiert das gemappte Urteil ueber
das neue Vault-Tool ``vault.set_quote_stance``. Diese Datei deckt:

  AC1  Vault-Layer (`VaultDB.set_quote_stance`, `server.set_quote_stance`,
       MCP-Tool `vault.set_quote_stance`) + Agent-Frontmatter/Output-Format.
  AC2  Abstract-Abgleich ist dritte Pruefebene, nie alleiniger Grund fuer ein
       Negativ-Urteil (Textassertion auf den Agenten-Body).
  AC3  Kein Auto-Rewrite: kein Write/Edit/MultiEdit im Frontmatter, Output
       enthaelt ein Begruendungsfeld.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
AGENT_PATH = REPO_ROOT / "agents" / "quote-fidelity-auditor.md"


@pytest.fixture
def paper_id(temp_vault_db):
    """Legt Test-Paper an und gibt paper_id zurueck."""
    from academic_vault.server import add_paper

    pid = "test-paper-fidelity-001"
    add_paper(
        db_path=temp_vault_db,
        paper_id=pid,
        csl_json=json.dumps({"title": "Test Paper", "type": "article-journal"}),
    )
    return pid


@pytest.fixture
def quote_id(temp_vault_db, paper_id):
    """Legt ein Zitat ohne stance an und gibt die quote_id zurueck."""
    from academic_vault.server import add_quote

    return add_quote(
        db_path=temp_vault_db,
        paper_id=paper_id,
        verbatim="Der Effekt war in allen Kohorten nachweisbar.",
        extraction_method="manual",
    )


# ---------------------------------------------------------------------------
# AC1 — VaultDB.set_quote_stance
# ---------------------------------------------------------------------------


def test_set_quote_stance_persists_and_is_visible_via_get_quote(temp_vault_db, quote_id):
    """Ein Update auf eine bestehende quote_id ist ueber get_quote() sichtbar."""
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    db.set_quote_stance(quote_id, "contrasts")

    record = db.get_quote(quote_id)
    assert record is not None
    assert record["stance"] == "contrasts"


def test_set_quote_stance_rejects_invalid_value(temp_vault_db, quote_id):
    """Ein Wert ausserhalb VALID_STANCES wirft ValueError, nichts wird geschrieben."""
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    with pytest.raises(ValueError):
        db.set_quote_stance(quote_id, "polarity-flip")

    # Nichts geschrieben -- stance bleibt NULL.
    record = db.get_quote(quote_id)
    assert record["stance"] is None


def test_set_quote_stance_rejects_unknown_quote_id(temp_vault_db):
    """Eine unbekannte quote_id wirft ValueError statt still nichts zu tun."""
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    with pytest.raises(ValueError):
        db.set_quote_stance("does-not-exist", "supports")


def test_set_quote_stance_refuses_write_on_locked_passport(temp_vault_db, quote_id):
    """Issue #380: Der Audit-Schreibpfad respektiert den Material-Passport-Lock.

    ``set_quote_stance`` ist ein Schreibpfad wie ``add_quote`` -- ein
    gesperrter Vault muss ihn mit ``VaultLockedError`` abweisen, statt eine
    bereits eingefrorene Beleglage nachtraeglich zu veraendern.
    """
    from academic_vault.db import VaultDB, VaultLockedError

    db = VaultDB(temp_vault_db)
    db.lock_vault("proj")

    with pytest.raises(VaultLockedError):
        db.set_quote_stance(quote_id, "contrasts")

    assert db.get_quote(quote_id)["stance"] is None


# ---------------------------------------------------------------------------
# AC1 — server.set_quote_stance + MCP-Tool-Wrapper
# ---------------------------------------------------------------------------


def test_server_set_quote_stance_updates_record(temp_vault_db, quote_id):
    """server.set_quote_stance() aktualisiert den Record ueber die db_path-Schicht."""
    from academic_vault import server

    server.set_quote_stance(db_path=temp_vault_db, quote_id=quote_id, stance="mentions")

    record = server.get_quote(db_path=temp_vault_db, quote_id=quote_id)
    assert record is not None
    assert record["stance"] == "mentions"


def test_mcp_tool_vault_set_quote_stance_is_registered():
    """vault.set_quote_stance ist als MCP-Tool in server.py registriert."""
    content = (REPO_ROOT / "academic_vault" / "server.py").read_text(encoding="utf-8")
    assert '@mcp.tool(name="vault.set_quote_stance")' in content


# ---------------------------------------------------------------------------
# AC1 — Agent-Frontmatter und Grund-Struktur
# ---------------------------------------------------------------------------


def _parse_frontmatter(agent_path: Path) -> str:
    content = agent_path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert fm_match is not None, f"Kein YAML-Frontmatter in {agent_path.name}"
    return fm_match.group(1)


def test_quote_fidelity_auditor_agent_file_exists():
    assert AGENT_PATH.exists(), f"Agent-Datei fehlt: {AGENT_PATH}"


def test_quote_fidelity_auditor_agent_frontmatter():
    """Frontmatter enthaelt name, model und die benoetigten Vault-Tools."""
    fm = _parse_frontmatter(AGENT_PATH)
    assert "name: quote-fidelity-auditor" in fm
    assert "model: sonnet" in fm
    assert "mcp__academic-vault__vault_get_quote" in fm
    assert "mcp__academic-vault__vault_get_paper" in fm
    assert "mcp__academic-vault__vault_set_quote_stance" in fm


def test_quote_fidelity_auditor_agent_has_nonempty_description():
    """Regression #168: description-Feld darf nicht fehlen/leer sein."""
    fm = _parse_frontmatter(AGENT_PATH)
    assert re.search(r"^description\s*[:|>]", fm, re.MULTILINE), (
        "description-Feld fehlt im Frontmatter (Issue #168)"
    )
    content = AGENT_PATH.read_text(encoding="utf-8")
    desc_match = re.search(r"description\s*[:|>]\s*([\s\S]+?)(?=\n\w|\n---)", content)
    assert desc_match is not None
    assert len(desc_match.group(1).strip()) >= 10


def test_quote_fidelity_auditor_documents_input_and_output_format():
    """Body enthaelt Input- und Output-JSON-Beispiel sowie die 5 Verdicts."""
    content = AGENT_PATH.read_text(encoding="utf-8")
    for verdict in ("faithful", "overstated", "context-stripped", "polarity-flip", "unsupported"):
        assert verdict in content, f"Verdict '{verdict}' fehlt im Agent-Body"
    assert "```json" in content, "Kein JSON-Beispiel im Agent-Body"


# ---------------------------------------------------------------------------
# AC2 — Abstract ist dritte Pruefebene, nie alleiniger Grund fuer ein Negativ-Urteil
# ---------------------------------------------------------------------------


def test_quote_fidelity_auditor_abstract_is_third_tier_only():
    """Der Agent-Body benennt explizit, dass ein reiner Abstract-Widerspruch
    ohne Widerspruch in Kontext/Verbatim kein Negativ-Urteil allein ausloesen
    darf -- Detail-Zitate jenseits des Abstracts sind ausdruecklich legitim."""
    content = AGENT_PATH.read_text(encoding="utf-8").lower()
    assert "abstract" in content
    assert "dritte" in content and "ebene" in content
    assert "legitim" in content, (
        "Body muss explizit benennen, dass Detail-Zitate jenseits des Abstracts legitim sind"
    )


def test_quote_fidelity_auditor_handles_missing_abstract():
    """Fehlt csl_json.abstract, wird das explizit behandelt (kein Raten)."""
    content = AGENT_PATH.read_text(encoding="utf-8").lower()
    assert "abstract" in content and ("fehlt" in content or "fehlen" in content)


# ---------------------------------------------------------------------------
# AC3 — kein Auto-Rewrite, Urteil + Begruendung fuer den User
# ---------------------------------------------------------------------------


def test_quote_fidelity_auditor_has_no_write_tools_in_frontmatter():
    fm = _parse_frontmatter(AGENT_PATH)
    tools_block_match = re.search(r"tools:\s*(\[[^\]]*\]|(?:\n\s*-.*)+)", fm)
    assert tools_block_match is not None, "tools:-Frontmatter nicht gefunden"
    tools_block = tools_block_match.group(1)
    for forbidden in ("Write", "Edit", "MultiEdit"):
        assert forbidden not in re.findall(r"[\w.]+", tools_block), (
            f"tools:-Frontmatter enthaelt verbotenes Schreib-Tool: {forbidden}"
        )


def test_quote_fidelity_auditor_output_includes_reasoning_field():
    content = AGENT_PATH.read_text(encoding="utf-8")
    assert '"reasoning"' in content, "Output-JSON-Schema muss ein reasoning-Feld deklarieren"


def test_quote_fidelity_auditor_documents_no_auto_rewrite():
    content = AGENT_PATH.read_text(encoding="utf-8").lower()
    assert "kein auto-rewrite" in content or "kein automatisches umschreiben" in content


def test_quote_fidelity_auditor_documents_verdict_to_stance_mapping():
    """Die Mapping-Tabelle Verdict -> stance ist im Body dokumentiert,
    inklusive der 'unsupported -> kein Persist'-Regel."""
    content = AGENT_PATH.read_text(encoding="utf-8").lower()
    assert "supports" in content and "contrasts" in content and "mentions" in content
    assert "unsupported" in content
    # 'kein' im Umfeld von 'unsupported' -- die Regel, dass unsupported NICHT
    # persistiert wird.
    assert re.search(r"unsupported[\s\S]{0,200}kein", content), (
        "Body muss dokumentieren, dass 'unsupported' NICHT via set_quote_stance persistiert wird"
    )
