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
# Test 10: quote-extractor.md dokumentiert base64-Fallback
# ---------------------------------------------------------------------------


def test_quote_extractor_base64_fallback_documented():
    agent_file = Path(__file__).parent.parent / "agents" / "quote-extractor.md"
    content = agent_file.read_text()
    # base64 als Fallback muss noch vorhanden sein
    assert '"type": "base64"' in content, "quote-extractor.md muss base64-Fallback dokumentieren"
    # Und als Fallback bezeichnet
    assert "Fallback" in content or "fallback" in content, (
        "quote-extractor.md muss Fallback-Begriff enthalten"
    )
