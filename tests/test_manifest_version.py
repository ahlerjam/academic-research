"""
Tests für Issue #738: Manifest-Version 6.7.0 -> 8.0.0 + Description-Sync (45 Skills)

Regressions-Tests, die sicherstellen, dass:
- plugin.json und marketplace.json beide Version 8.0.0 deklarieren
- plugin.json description "45" enthält
- Beide JSON-Dateien valide sind
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"


def test_plugin_json_version():
    """plugin.json muss Version 8.0.0 deklarieren."""
    data = json.loads(PLUGIN_JSON.read_text())
    version = data["version"]
    assert re.match(r"^8\.0\.", version), (
        f"plugin.json version erwartet ^8.0.x, got '{version}' — "
        "vermutlich noch auf altem Stand (6.7.0)"
    )


def test_marketplace_json_version():
    """marketplace.json plugins[0].version muss 8.0.0 deklarieren."""
    data = json.loads(MARKETPLACE_JSON.read_text())
    version = data["plugins"][0]["version"]
    assert re.match(r"^8\.0\.", version), (
        f"marketplace.json plugins[0].version erwartet ^8.0.x, got '{version}' — "
        "vermutlich noch auf altem Stand (6.7.0)"
    )


def test_plugin_json_description_mentions_current_skill_count():
    """plugin.json description soll die aktuelle Skill-Zahl (45, Issue #607) nennen."""
    data = json.loads(PLUGIN_JSON.read_text())
    description = data["description"]
    assert "45" in description, f"plugin.json description enthält nicht '45': '{description}'"


def test_plugin_json_version_matches_marketplace():
    """Beide Manifeste müssen exakt dieselbe version tragen."""
    plugin_data = json.loads(PLUGIN_JSON.read_text())
    marketplace_data = json.loads(MARKETPLACE_JSON.read_text())
    plugin_version = plugin_data["version"]
    marketplace_version = marketplace_data["plugins"][0]["version"]
    assert plugin_version == marketplace_version, (
        f"Versions-Diskrepanz: plugin.json='{plugin_version}', "
        f"marketplace.json='{marketplace_version}'"
    )


def test_plugin_json_keywords_contain_vault():
    """plugin.json keywords sollen 'vault' enthalten (Issue #166 AC)."""
    data = json.loads(PLUGIN_JSON.read_text())
    keywords = data.get("keywords", [])
    assert "vault" in keywords, f"'vault' fehlt in plugin.json keywords: {keywords}"


def test_plugin_json_keywords_contain_latex():
    """plugin.json keywords sollen 'latex' enthalten (Issue #166 AC)."""
    data = json.loads(PLUGIN_JSON.read_text())
    keywords = data.get("keywords", [])
    assert "latex" in keywords, f"'latex' fehlt in plugin.json keywords: {keywords}"


def test_plugin_json_valid_json():
    """plugin.json muss valides JSON sein."""
    try:
        json.loads(PLUGIN_JSON.read_text())
    except json.JSONDecodeError as e:
        raise AssertionError(f"plugin.json ist kein valides JSON: {e}") from e


def test_marketplace_json_valid_json():
    """marketplace.json muss valides JSON sein."""
    try:
        json.loads(MARKETPLACE_JSON.read_text())
    except json.JSONDecodeError as e:
        raise AssertionError(f"marketplace.json ist kein valides JSON: {e}") from e
