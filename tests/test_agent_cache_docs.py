"""
tests/test_agent_cache_docs.py

Doku-Regressionstests fuer Prompt-Caching-Konventionen in ``agents/*.md``
(urspruenglich Teil von Chunk B, Ticket #65 + #66; im Zuge von Issue #377 aus
der frueheren Testdatei fuer das zugehoerige (inzwischen als tote
Parallellogik entfernte) Files-API-Helper-Modul hierher verschoben — diese
Tests pruefen unabhaengig davon nur Markdown-Doku-Inhalte).
"""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Tests 6/7/8: Alle drei Agenten muessen cache_control ttl=1h enthalten
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_name",
    [
        "relevance-scorer",
        "quote-extractor",
        "quality-reviewer",
    ],
)
def test_agent_cache_ttl_1h(agent_name):
    agent_file = Path(__file__).parent.parent / "agents" / f"{agent_name}.md"
    assert agent_file.exists(), f"Datei nicht gefunden: {agent_file}"
    content = agent_file.read_text()
    assert '"ttl": "1h"' in content or "'ttl': '1h'" in content, (
        f"{agent_name}.md muss cache_control mit ttl=1h enthalten"
    )


# ---------------------------------------------------------------------------
# Test 9: quote-extractor.md dokumentiert source.type: "file"
# ---------------------------------------------------------------------------


def test_quote_extractor_file_source_documented():
    agent_file = Path(__file__).parent.parent / "agents" / "quote-extractor.md"
    content = agent_file.read_text()
    assert '"type": "file"' in content, (
        'quote-extractor.md muss source.type: "file" als primären Pfad dokumentieren'
    )


# ---------------------------------------------------------------------------
# Test 10 (bis #514): quote-extractor.md dokumentierte einen base64-Fallback
# fuer die Citations-API. Seit #514 ist die Citations-API selbst nur noch
# ein kurzer Opt-in-Hinweis (Standardpfad: vault.get_paper -> pdf_path ->
# Read, Persistenz via extraction_method="local-verbatim") -- der
# base64-Unterfallback der Files-API ist damit kein Doku-Pflichtinhalt des
# Agent-Files mehr, sondern Detail des referenzierten
# skills/chapter-writer/references/citations-api.md (dessen eigener
# Fallback ist Vault-Zitat-Text statt Citations-API, nicht base64).
# ---------------------------------------------------------------------------


def test_quote_extractor_opt_in_citations_api_references_details_doc():
    agent_file = Path(__file__).parent.parent / "agents" / "quote-extractor.md"
    content = agent_file.read_text()
    assert "Opt-in" in content, "quote-extractor.md muss die Citations-API als Opt-in kennzeichnen"
    assert "skills/chapter-writer/references/citations-api.md" in content, (
        "quote-extractor.md muss fuer Citations-API-Details auf die Referenzdatei verweisen"
    )
