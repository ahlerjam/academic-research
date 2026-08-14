"""
Frontmatter-Validierung und Output-Schema-Check fuer Publisher-Fetcher-Agents.
Keine Live-Browser-Calls. Prueft nur Struktur der Agent-Dateien.
"""

import re
from pathlib import Path

import pytest
import yaml

# Absoluter Pfad zum Repo-Root (relativ zu dieser Test-Datei)
REPO_ROOT = Path(__file__).parent.parent

#: Verlags-Plattformen mit eigenem Agenten. Nationallizenzen und Ebook Central
#: haben seit Issue #840 keinen mehr — sie laufen ueber den Ultimate Fetcher
#: `generic-fetcher` mit ihrer Site-Config (siehe GUIDE_SITES unten).
AGENTS = [
    "springer-book",
    "degruyter",
    "cambridge-core",
    "oxford-academic",
    "jstor",
]

#: Site-Schluessel -> Site-Config der agentenlosen Verlags-Plattformen (#840).
GUIDE_SITES = {
    "nationallizenzen": "nationallizenzen.md",
    "ebook-central": "ebook-central.md",
}

REQUIRED_FRONTMATTER_KEYS = {"name", "model", "tools", "maxTurns", "browser-guide"}

VALID_STATUSES = {
    "success",
    "pickup_required",
    "captcha",
    "no_match",
    "metadata_only",
}

REQUIRED_TOOL_PATTERNS = [
    r"browser-use",
]

EVALS_PATH = REPO_ROOT / "evals" / "publisher-fetchers" / "evals.json"

PAYWALL_KEYWORDS = [
    "paywall",
    "login-wall",
    "auth-trigger",
    "auth-helper",
]


def _parse_agent_frontmatter(agent_name: str) -> tuple[dict, str]:
    """Parst YAML-Frontmatter und Body eines Agent-Files."""
    agent_path = REPO_ROOT / "agents" / f"{agent_name}.md"
    assert agent_path.exists(), f"Agent-Datei fehlt: {agent_path}"
    content = agent_path.read_text(encoding="utf-8")
    # Frontmatter zwischen erstem und zweitem ---
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    assert match, f"Kein gueltiges Frontmatter in {agent_path}"
    fm = yaml.safe_load(match.group(1))
    body = match.group(2)
    return fm, body


@pytest.mark.parametrize("agent_name", AGENTS)
def test_agent_file_exists(agent_name):
    """Jede Agent-Datei muss existieren."""
    agent_path = REPO_ROOT / "agents" / f"{agent_name}.md"
    assert agent_path.exists(), f"Fehlende Agent-Datei: {agent_path}"


@pytest.mark.parametrize("agent_name", AGENTS)
def test_frontmatter_required_keys(agent_name):
    """Frontmatter muss alle Pflichtfelder enthalten."""
    fm, _ = _parse_agent_frontmatter(agent_name)
    missing = REQUIRED_FRONTMATTER_KEYS - set(fm.keys())
    assert not missing, f"{agent_name}: fehlende Frontmatter-Felder: {missing}"


@pytest.mark.parametrize("agent_name", AGENTS)
def test_frontmatter_model_is_sonnet(agent_name):
    """Alle Publisher-Fetcher muessen model: sonnet verwenden."""
    fm, _ = _parse_agent_frontmatter(agent_name)
    assert fm.get("model") == "sonnet", (
        f"{agent_name}: model muss 'sonnet' sein, ist '{fm.get('model')}'"
    )


@pytest.mark.parametrize("agent_name", AGENTS)
def test_frontmatter_tools_include_browser_use(agent_name):
    """Tools-Liste muss browser-use enthalten."""
    fm, _ = _parse_agent_frontmatter(agent_name)
    tools = fm.get("tools", [])
    # tools kann Liste von Strings oder String sein
    tools_str = str(tools)
    assert "browser-use" in tools_str, (
        f"{agent_name}: tools muss 'browser-use' enthalten, ist: {tools}"
    )


@pytest.mark.parametrize("agent_name", AGENTS)
def test_frontmatter_browser_guide_referenced(agent_name):
    """browser-guide Frontmatter-Feld muss gesetzt sein."""
    fm, _ = _parse_agent_frontmatter(agent_name)
    guide = fm.get("browser-guide", "")
    assert guide, f"{agent_name}: browser-guide Feld fehlt oder leer"
    assert guide.startswith("config/browser_guides/"), (
        f"{agent_name}: browser-guide muss mit 'config/browser_guides/' beginnen, ist: {guide}"
    )


@pytest.mark.parametrize("agent_name", AGENTS)
def test_body_documents_auth_trigger(agent_name):
    """Agent-Body muss Auth-Trigger-Bedingung dokumentieren."""
    _, body = _parse_agent_frontmatter(agent_name)
    body_lower = body.lower()
    found = any(kw in body_lower for kw in PAYWALL_KEYWORDS)
    assert found, (
        f"{agent_name}: Body dokumentiert keinen Auth-Trigger. "
        f"Erwartete eines von: {PAYWALL_KEYWORDS}"
    )


@pytest.mark.parametrize("agent_name", AGENTS)
def test_body_documents_auth_method(agent_name):
    """Agent-Body muss Auth-Methode (HAN/Shibboleth/EZproxy/DFN-AAI) nennen."""
    _, body = _parse_agent_frontmatter(agent_name)
    auth_methods = ["HAN", "Shibboleth", "EZproxy", "DFN-AAI", "oa-only"]
    found = any(method in body for method in auth_methods)
    assert found, f"{agent_name}: Body nennt keine Auth-Methode. Erwartet eines von: {auth_methods}"


@pytest.mark.parametrize("agent_name", AGENTS)
def test_body_references_auth_helper(agent_name):
    """Agent-Body muss auth-helper als Delegations-Ziel referenzieren."""
    _, body = _parse_agent_frontmatter(agent_name)
    assert "auth-helper" in body, (
        f"{agent_name}: Body muss 'auth-helper' als Delegations-Ziel referenzieren"
    )


@pytest.mark.parametrize("agent_name", AGENTS)
def test_body_contains_valid_status_values(agent_name):
    """Agent-Body muss alle Output-Status-Werte (success/pickup_required/etc.) erwaehnen."""
    _, body = _parse_agent_frontmatter(agent_name)
    # Mindestens 3 der 5 Status-Werte muessen im Body erwaehnt sein
    found = [s for s in VALID_STATUSES if s in body]
    assert len(found) >= 3, (
        f"{agent_name}: Body nennt zu wenige Status-Werte ({found}). "
        f"Erwartet min. 3 aus: {VALID_STATUSES}"
    )


@pytest.mark.parametrize("agent_name", AGENTS)
def test_body_documents_metadata_only_for_missing_license(agent_name):
    """Agent-Body muss metadata_only fuer fehlende Lizenz dokumentieren."""
    _, body = _parse_agent_frontmatter(agent_name)
    assert "metadata_only" in body, (
        f"{agent_name}: Body muss 'metadata_only' als Fallback fuer fehlende Lizenz dokumentieren"
    )


@pytest.mark.parametrize("agent_name", AGENTS)
def test_body_references_browser_guide(agent_name):
    """Agent-Body muss den config/browser_guides/-Pfad referenzieren."""
    fm, body = _parse_agent_frontmatter(agent_name)
    # Body muss den Pfad 'config/browser_guides/' referenzieren
    assert "browser_guides" in body, (
        f"{agent_name}: Body muss 'browser_guides' (config/browser_guides/-Pfad) referenzieren"
    )


def test_eval_cases_file_exists():
    """evals/publisher-fetchers/evals.json muss existieren."""
    assert EVALS_PATH.exists(), f"Eval-Datei fehlt: {EVALS_PATH}"


def test_eval_cases_structure():
    """evals.json muss valide Struktur haben."""
    import json

    if not EVALS_PATH.exists():
        pytest.skip("evals.json noch nicht vorhanden")
    data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    assert "component" in data
    assert "cases" in data
    assert len(data["cases"]) >= 4, "Mindestens 4 Eval-Cases erwartet"
    for case in data["cases"]:
        assert "id" in case
        assert "description" in case
        assert "agent" in case


# ─── Site-Configs der agentenlosen Verlags-Plattformen (Issue #840) ──────────

GUIDES_DIR = REPO_ROOT / "config" / "browser_guides"


def _guide_text(guide_name: str) -> str:
    return (GUIDES_DIR / guide_name).read_text(encoding="utf-8")


@pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
def test_guide_site_has_browser_guide(site, guide_name):
    """Nationallizenzen und Ebook Central brauchen ohne eigenen Agenten eine
    vollstaendige Site-Config — sonst ist ihr Zugriffsweg ersatzlos weg."""
    assert (GUIDES_DIR / guide_name).exists(), f"Site-Config fehlt fuer {site}"


@pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
def test_guide_site_documents_auth_trigger(site, guide_name):
    body_lower = _guide_text(guide_name).lower()
    assert any(kw in body_lower for kw in PAYWALL_KEYWORDS), (
        f"{guide_name}: Site-Config dokumentiert keinen Auth-Trigger. "
        f"Erwartete eines von: {PAYWALL_KEYWORDS}"
    )


@pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
def test_guide_site_documents_auth_method(site, guide_name):
    auth_methods = ["HAN", "Shibboleth", "EZproxy", "DFN-AAI", "oa-only"]
    text = _guide_text(guide_name)
    assert any(method in text for method in auth_methods), (
        f"{guide_name}: Site-Config nennt keine Auth-Methode. Erwartet eines von: {auth_methods}"
    )


@pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
def test_guide_site_delegates_auth_to_auth_helper(site, guide_name):
    assert "auth-helper" in _guide_text(guide_name), (
        f"{guide_name}: Site-Config muss 'auth-helper' als Delegations-Ziel nennen — "
        "der Ultimate Fetcher verarbeitet nie selbst Credentials"
    )


@pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
def test_guide_site_documents_metadata_only_for_missing_license(site, guide_name):
    assert "metadata_only" in _guide_text(guide_name), (
        f"{guide_name}: Site-Config muss 'metadata_only' fuer die fehlende Lizenz "
        "dokumentieren — daran haengt die Verlags-Stufe des Masters"
    )


@pytest.mark.parametrize("site, guide_name", sorted(GUIDE_SITES.items()))
def test_guide_site_contains_valid_status_values(site, guide_name):
    text = _guide_text(guide_name)
    found = [s for s in VALID_STATUSES if s in text]
    assert len(found) >= 3, (
        f"{guide_name}: Site-Config nennt zu wenige Status-Werte ({found}). "
        f"Erwartet min. 3 aus: {VALID_STATUSES}"
    )


def test_book_fetcher_dispatches_guide_sites_via_site_config():
    """AC3 (#840): beide Plattformen stehen als Site-Config in der Verlags-Stufe."""
    text = (REPO_ROOT / "agents" / "book-fetcher.md").read_text(encoding="utf-8")
    step4 = text.split("## Schritt 4", 1)[1].split("\n## Schritt 5", 1)[0]
    for guide_name in GUIDE_SITES.values():
        assert f"config/browser_guides/{guide_name}" in step4, (
            f"{guide_name} fehlt in der Verlags-Stufe von agents/book-fetcher.md"
        )
