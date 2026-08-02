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
        # relevance-scorer und quote-extractor sind seit #632 raus: beide
        # beschrieben einen rohen SDK-Aufrufweg (client.messages.create bzw.
        # den Citations-API-Opt-in) mit eigenem ANTHROPIC_API_KEY. Diesen Weg
        # gibt es nicht mehr, also gibt es dafuer auch keine Doku-Pflicht.
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
# Bis #632: quote-extractor.md musste den Citations-API-Opt-in dokumentieren
# (source.type: "file", Verweis auf skills/chapter-writer/references/
# citations-api.md). Dieser Weg setzte einen eigenen ANTHROPIC_API_KEY voraus
# und ist entfallen -- der Agent liest das PDF ausschliesslich lokal. Der
# Guard dagegen, dass er zurueckkommt, sitzt in
# tests/test_issue_632_no_anthropic_sdk.py.
# ---------------------------------------------------------------------------
