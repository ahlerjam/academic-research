"""Fetcher-Konsolidierung: Ultimate Fetcher + 7 dedizierte Site-Agenten (Issue #840).

Die 15 fast identischen Site-Fetcher werden auf acht dispatchbare Fetcher
reduziert: sieben dedizierte Site-Agenten (Springer, JSTOR, Oxford Academic,
Cambridge Core, De Gruyter, TIB, Sci-Hub) plus den parametrisierten
``generic-fetcher`` ("Ultimate Fetcher"), der die uebrigen acht Sites ueber eine
Site-Config unter ``config/browser_guides/`` bedient.

Jeder Test hier haengt an genau einem Akzeptanzkriterium des Issues.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.helpers.book_fetcher_router import OA_SITES, BookFetcherRouter

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
GUIDES_DIR = REPO_ROOT / "config" / "browser_guides"
BOOK_FETCHER = AGENTS_DIR / "book-fetcher.md"
ULTIMATE_FETCHER = AGENTS_DIR / "generic-fetcher.md"
LIVE_FETCH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-fetch-weekly.yml"

#: AC1 -- die verbleibende Fetcher-Menge, die book-fetcher dispatchen darf.
CONSOLIDATED_FETCHERS = {
    "tib-fetcher",
    "springer-book",
    "degruyter",
    "cambridge-core",
    "oxford-academic",
    "jstor",
    "scihub-fetcher",
    "generic-fetcher",
}

#: AC1 -- diese Agent-Dateien entfallen ersatzlos zugunsten der Site-Configs.
RETIRED_AGENTS = [
    "doabooks-fetcher",
    "oapen-fetcher",
    "kvk-fetcher",
    "hathitrust-fetcher",
    "internetarchive-fetcher",
    "mdz-fetcher",
    "nationallizenzen",
    "ebook-central",
]

#: AC2 -- Site -> Guide-Datei der entfallenen Agenten.
RETIRED_SITE_GUIDES = {
    "doabooks-fetcher": "doab.md",
    "oapen-fetcher": "oapen.md",
    "kvk-fetcher": "kvk.md",
    "hathitrust-fetcher": "hathitrust.md",
    "internetarchive-fetcher": "internetarchive.md",
    "mdz-fetcher": "mdz.md",
    "nationallizenzen": "nationallizenzen.md",
    "ebook-central": "ebook-central.md",
}

#: AC2 -- je Site ein woertlicher Kernmarker aus dem geloeschten Agenten. Faellt
#: einer weg, ist real erkauftes Site-Wissen verloren gegangen.
MIGRATED_KNOWLEDGE_MARKERS = {
    "doab.md": ["metadata_only", "REST", "Aggregator"],
    "oapen.md": ["metadata_only", "Open Access"],
    "kvk.md": ["metadata_only", "kein Volltext", "Fernleihe"],
    "hathitrust.md": ["Zugriffsstufe: search-only", "Full view", "403"],
    "internetarchive.md": ["Borrow/CDL", "access-restricted-item", "403"],
    "mdz.md": ["Rechtehinweis", "Zugriffsstufe: nur Seitenansicht"],
    "nationallizenzen.md": ["metadata_only", "auth-helper", "DFN-AAI"],
    "ebook-central.md": ["metadata_only", "Adobe", "Download-Limit", "auth-helper"],
}


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert match, f"Kein Frontmatter in {path.name}"
    return match.group(1)


def _dispatchable_fetchers() -> set[str]:
    """Fetcher-Inventar aus den Agent(...)-Eintraegen des book-fetcher-Frontmatters.

    Abgeleitet statt hartkodiert: eine zweite Inventarliste im Test wuerde bei
    der naechsten Aenderung erneut auseinanderlaufen (Learning aus #612).
    """
    agents = set(re.findall(r'"Agent\(([a-z0-9-]+)\)"', _frontmatter(BOOK_FETCHER)))
    assert agents, "Keine Agent(...)-Tools im book-fetcher-Frontmatter gefunden"
    return agents - {"auth-helper"}


# ─── AC1: konsolidierte Agentenmenge ─────────────────────────────────────────


def test_fetcher_inventory_matches_consolidated_set():
    assert _dispatchable_fetchers() == CONSOLIDATED_FETCHERS


def test_auth_helper_stays_dispatchable():
    assert '"Agent(auth-helper)"' in _frontmatter(BOOK_FETCHER)


@pytest.mark.parametrize("agent_name", RETIRED_AGENTS)
def test_retired_agent_files_are_gone(agent_name):
    path = AGENTS_DIR / f"{agent_name}.md"
    assert not path.exists(), (
        f"{path} existiert noch — die Site laeuft jetzt ueber den Ultimate Fetcher"
    )


def test_agents_dir_contains_no_other_site_fetcher():
    """Kein uebersehener Site-Fetcher: jede Datei mit browser-guide-Frontmatter
    muss zur konsolidierten Menge gehoeren."""
    site_agents = {
        path.stem for path in AGENTS_DIR.glob("*.md") if "browser-guide:" in _frontmatter(path)
    }
    assert site_agents <= CONSOLIDATED_FETCHERS, (
        f"Site-Agenten ausserhalb der konsolidierten Menge: "
        f"{sorted(site_agents - CONSOLIDATED_FETCHERS)}"
    )


# ─── AC2: Site-Config je entfallener Site, kein Wissensverlust ────────────────


@pytest.mark.parametrize("guide_name", sorted(set(RETIRED_SITE_GUIDES.values())))
def test_every_retired_site_has_browser_guide(guide_name):
    path = GUIDES_DIR / guide_name
    assert path.exists(), f"Site-Config fehlt: {path}"
    assert len(path.read_text(encoding="utf-8").strip()) > 200, (
        f"Site-Config {guide_name} ist zu duenn fuer eine Fetch-Anleitung"
    )


@pytest.mark.parametrize("guide_name, markers", sorted(MIGRATED_KNOWLEDGE_MARKERS.items()))
def test_migrated_site_knowledge_markers(guide_name, markers):
    text = (GUIDES_DIR / guide_name).read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in text]
    assert not missing, (
        f"config/browser_guides/{guide_name}: Site-Wissen aus dem geloeschten "
        f"Agenten fehlt: {missing}"
    )


def test_ultimate_fetcher_documents_site_config_parameter():
    text = ULTIMATE_FETCHER.read_text(encoding="utf-8")
    assert "site_config" in text, "generic-fetcher.md kennt den site_config-Parameter nicht"
    assert "config/browser_guides/" in text, (
        "generic-fetcher.md nennt das Verzeichnis der Site-Configs nicht"
    )


def test_ultimate_fetcher_supports_metadata_only_status():
    """Ohne metadata_only faellt die gesamte Verlags-Stufe des Masters lautlos aus
    (book-fetcher Schritt 4 haengt an oa_had_metadata_only)."""
    text = ULTIMATE_FETCHER.read_text(encoding="utf-8")
    assert "metadata_only" in text


def test_ultimate_fetcher_carries_edition_and_site_fields():
    """#450 AC4: HathiTrust/IA/MDZ melden edition — das Feld darf durch die
    Konsolidierung nicht verschwinden; `site` macht die tries-Kette eindeutig."""
    text = ULTIMATE_FETCHER.read_text(encoding="utf-8")
    assert '"edition"' in text, "generic-fetcher.md fuehrt kein edition-Feld"
    assert '"site"' in text, "generic-fetcher.md fuehrt kein site-Feld"


def test_ultimate_fetcher_no_longer_forbids_site_guides():
    text = ULTIMATE_FETCHER.read_text(encoding="utf-8")
    assert "Kein site-spezifischer Guide" not in text, (
        "Das alte Verbot widerspricht dem site_config-Parameter"
    )


# ─── AC3: Fallback-Kette ohne geloeschte Agenten ─────────────────────────────


@pytest.mark.parametrize("agent_name", RETIRED_AGENTS)
def test_book_fetcher_mentions_no_retired_agent(agent_name):
    """Weder als dispatchbares Tool noch als Datei-Verweis.

    Der blosse Name bleibt zulaessig, wo er die *Site* meint
    (`nationallizenzen.de` als Host, `config/browser_guides/ebook-central.md`
    als Site-Config) — gesucht sind Verweise auf den geloeschten *Agenten*.
    """
    text = BOOK_FETCHER.read_text(encoding="utf-8")
    offenders = [
        pattern
        for pattern in (f"Agent({agent_name})", f"agents/{agent_name}.md")
        if pattern in text
    ]
    assert not offenders, (
        f"agents/book-fetcher.md referenziert den geloeschten Agenten {agent_name}: {offenders}"
    )


def test_oa_chain_order_is_unchanged():
    """#450 AC3: alle lizenzfreien Quellen vor jedem Verlags-Subagenten, und in
    unveraenderter Reihenfolge."""
    assert [entry["site"] for entry in OA_SITES] == [
        "doab",
        "oapen",
        "tib",
        "kvk",
        "hathitrust",
        "internetarchive",
        "mdz",
    ]


def test_oa_chain_dispatches_generic_with_site_config():
    router = BookFetcherRouter(profile={"licensed_sites": []})
    seen = []

    def side_effect(subagent, payload):
        seen.append((subagent, dict(payload)))
        return {"status": "no_match", "source": subagent}

    with patch.object(router, "dispatch_subagent", side_effect=side_effect):
        router.fetch("978-3-16-148410-0", output_path="/tmp/out.pdf")

    oa_calls = seen[: len(OA_SITES)]
    for call, entry in zip(oa_calls, OA_SITES, strict=True):
        subagent, payload = call
        expected = entry.get("subagent", "generic-fetcher")
        assert subagent == expected
        if expected == "generic-fetcher":
            assert payload.get("site_config") == entry["site_config"]


def test_tries_entries_carry_the_site_for_generic_dispatches():
    """Bis zu sechs tries-Eintraege lauten `generic-fetcher` — ohne `site` waere
    die Kette nicht mehr diagnostizierbar."""
    router = BookFetcherRouter(profile={"licensed_sites": []})

    with patch.object(
        router, "dispatch_subagent", side_effect=lambda name, payload: {"status": "no_match"}
    ):
        result = router.fetch("978-3-16-148410-0", output_path="/tmp/out.pdf")

    generic_oa = [t for t in result["tries"][: len(OA_SITES)] if t["subagent"] == "generic-fetcher"]
    assert generic_oa, "OA-Kette dispatcht keinen generic-fetcher mehr"
    assert all(t.get("site") for t in generic_oa), f"tries-Eintraege ohne site-Feld: {generic_oa}"


def test_metadata_only_from_generic_still_activates_publisher_tier():
    """Groesstes Risiko der Konsolidierung: Schritt 4 haengt an metadata_only.
    Meldet der Ultimate Fetcher es nicht durch, faellt die Verlags-Stufe aus."""
    router = BookFetcherRouter(profile={"licensed_sites": ["link.springer.com"]})
    called = []

    def side_effect(subagent, payload):
        called.append(subagent)
        if subagent == "springer-book":
            return {"status": "success", "file_path": "/tmp/out.pdf"}
        if subagent == "tib-fetcher":
            return {"status": "no_match"}
        return {"status": "metadata_only", "url": "https://example.org/x"}

    with patch.object(router, "dispatch_subagent", side_effect=side_effect):
        result = router.fetch("978-3-16-148410-0", output_path="/tmp/out.pdf")

    assert result["status"] == "success"
    assert result["source"] == "springer-book"
    assert "springer-book" in called


# ─── AC4: Live-Fetch-Workflow laeuft mit der neuen Struktur ──────────────────


def test_live_fetch_workflow_comment_states_current_fetcher_count():
    text = LIVE_FETCH_WORKFLOW.read_text(encoding="utf-8")
    counts = re.findall(r"(\d+)\s+Fetcher\b", text)
    assert counts, "Kommentarblock des Workflows nennt keine Fetcher-Zahl"
    actual = len(_dispatchable_fetchers())
    assert all(int(c) == actual for c in counts), (
        f"live-fetch-weekly.yml nennt {counts} Fetcher, dispatchbar sind {actual}"
    )


# ─── AC5: Frontmatter-Coverage-Gate bleibt gruen ─────────────────────────────


@pytest.mark.parametrize("agent_path", sorted(AGENTS_DIR.glob("**/*.md")), ids=lambda p: p.name)
def test_all_remaining_agents_have_description_frontmatter(agent_path):
    """Spiegelt den CI-Job 'Frontmatter-Coverage (commands + agents)' lokal."""
    lines = agent_path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{agent_path.name}: kein Frontmatter"
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    assert end is not None, f"{agent_path.name}: Frontmatter nicht geschlossen"
    fm = "\n".join(lines[1:end])
    assert re.search(r"^description:", fm, re.MULTILINE), (
        f"{agent_path.name}: description-Feld fehlt im Frontmatter"
    )
