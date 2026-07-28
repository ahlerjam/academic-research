"""
Regressionstest fuer Issue #370 — Versionsnummern synchronisieren.

Befund: pyproject.toml (6.6.0), plugin.json/marketplace.json (6.5.0) und der
oberste *versionierte* CHANGELOG-Eintrag liefen auseinander; der bestehende
`version-match`-Job in `.github/workflows/release.yml` prueft nur
Tag<->plugin.json und plugin.json<->marketplace.json, nicht pyproject.toml.

AC1: pyproject.toml, plugin.json, marketplace.json und der oberste
     versionierte CHANGELOG-Eintrag zeigen exakt dieselbe Versionsnummer.
AC2: Der `version-match`-Job bezieht pyproject.toml in den Abgleich mit ein.
AC3: siehe scripts/dev/test-release-version-match.sh (Bash-Trockenlauf der
     Job-Skriptlogik mit simuliertem Tag, Erfolgs- und Bruchfall).
"""

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
DRY_RUN_SCRIPT = REPO_ROOT / "scripts" / "dev" / "test-release-version-match.sh"


def _pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "pyproject.toml hat kein '^version = \"...\"'-Feld."
    return m.group(1)


def _plugin_json_version() -> str:
    return json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]


def _marketplace_json_version() -> str:
    data = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    return data["plugins"][0]["version"]


def _changelog_top_versioned_entry() -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(r"\[(\d+\.\d+\.\d+)\]", text)
    assert m, "Kein versionierter CHANGELOG-Eintrag (## [X.Y.Z]) gefunden."
    return m.group(1)


def test_pyproject_version_matches_plugin_json():
    """pyproject.toml und plugin.json muessen exakt dieselbe Version tragen."""
    assert _pyproject_version() == _plugin_json_version(), (
        f"Versions-Drift: pyproject.toml='{_pyproject_version()}', "
        f"plugin.json='{_plugin_json_version()}'"
    )


def test_pyproject_version_matches_marketplace_json():
    """pyproject.toml und marketplace.json muessen exakt dieselbe Version tragen."""
    assert _pyproject_version() == _marketplace_json_version(), (
        f"Versions-Drift: pyproject.toml='{_pyproject_version()}', "
        f"marketplace.json='{_marketplace_json_version()}'"
    )


def test_changelog_top_versioned_entry_matches_plugin_json():
    """Der oberste versionierte CHANGELOG-Eintrag muss zur Manifest-Version passen."""
    assert _changelog_top_versioned_entry() == _plugin_json_version(), (
        f"Versions-Drift: CHANGELOG-Top-Eintrag='{_changelog_top_versioned_entry()}', "
        f"plugin.json='{_plugin_json_version()}'"
    )


def test_release_workflow_compares_pyproject_toml_against_plugin_json():
    """Der version-match-Job muss pyproject.toml gegen plugin.json abgleichen."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "pyproject.toml" in text, (
        "release.yml version-match-Job erwaehnt pyproject.toml nicht — "
        "AC2 (#370) verlangt einen dritten Vergleichsschritt."
    )
    # Der neue Schritt muss tatsaechlich vergleichen (nicht nur den String erwaehnen).
    assert re.search(r"PYPROJECT.*!=.*PLUGIN|PLUGIN.*!=.*PYPROJECT", text) or re.search(
        r'if \[ "\$PYPROJECT" != "\$PLUGIN" \]', text
    ), "release.yml enthaelt keinen erkennbaren pyproject.toml<->plugin.json-Vergleich."


def test_dry_run_script_exists_and_is_executable():
    """Regressions-Skript fuer den Tag-Trockenlauf (AC3) muss vorhanden + ausfuehrbar sein."""
    assert DRY_RUN_SCRIPT.is_file(), f"Fehlt: {DRY_RUN_SCRIPT}"
    assert DRY_RUN_SCRIPT.stat().st_mode & 0o111, f"Nicht ausfuehrbar: {DRY_RUN_SCRIPT}"


def test_dry_run_script_passes_with_matching_tag():
    """AC3: simulierter Tag, der der gemeinsamen Version entspricht, ist gruen."""
    result = subprocess.run(
        ["bash", str(DRY_RUN_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Dry-run-Skript schlug fehl (rc={result.returncode}):\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
