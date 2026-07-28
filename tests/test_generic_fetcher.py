"""Tests fuer agents/generic-fetcher.md (Issue #448: universeller Plattform-Navigator).

Strategie:
- Keine echten Browser-Aufrufe. Geprueft wird gegen
  1. YAML-Frontmatter aus agents/generic-fetcher.md
  2. den System-Prompt-Text (Kopplung Prompt <-> Python-Spiegel)
  3. den Navigations-Spiegel ``tests/helpers/generic_fetcher_nav.py``, der gegen
     gespeicherte DOM-Fixtures faehrt (etabliertes Repo-Muster, vgl.
     ``tests/helpers/book_fetcher_router.py``)

Output-Schema (Issue #448):
  {status, source, file_path?, url?, reason?, tries[{step, action, url, observation, decision}]}
"""

import json
import os
import re

import pytest

from tests.helpers.generic_fetcher_nav import (
    DECISIONS,
    PAGE_STATES,
    VIEWER_PATTERNS,
    GenericFetcherNavigator,
    load_max_steps,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_FILE = os.path.join(REPO_ROOT, "agents", "generic-fetcher.md")
AGENTS_DIR = os.path.join(REPO_ROOT, "agents")
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "dom_heuristics")
EVALS_FILE = os.path.join(REPO_ROOT, "evals", "generic-fetcher", "evals.json")

# Parsed once at module load to avoid repeated disk reads across test methods.
_AGENT_FM: dict = {}
_AGENT_BODY: str = ""


# ---------------------------------------------------------------------------
# Helper: parse frontmatter + body from agent markdown
# ---------------------------------------------------------------------------


def _parse_agent_md(path: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) from a --- fenced markdown file."""
    import yaml

    with open(path, encoding="utf-8") as fh:
        content = fh.read()

    # Expect frontmatter between first two '---' fences
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not match:
        return {}, content

    fm = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    return fm, body


def _agent() -> tuple[dict, str]:
    """Return cached (frontmatter, body) for agents/generic-fetcher.md."""
    global _AGENT_FM, _AGENT_BODY
    if not _AGENT_FM and not _AGENT_BODY:
        _AGENT_FM, _AGENT_BODY = _parse_agent_md(AGENT_FILE)
    return _AGENT_FM, _AGENT_BODY


def _fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_eval_cases() -> list[dict]:
    with open(EVALS_FILE, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------

VALID_STATUSES = {"success", "pickup_required", "captcha", "no_match", "auth_required"}

TRY_KEYS = {"step", "action", "url", "observation", "decision"}


def _validate_output_schema(output: dict) -> list[str]:
    """Return list of validation errors (empty = valid)."""
    errors = []

    if "status" not in output:
        errors.append("missing 'status' field")
    elif output["status"] not in VALID_STATUSES:
        errors.append(f"invalid status: {output['status']!r}")

    if "source" not in output:
        errors.append("missing 'source' field")
    elif output["source"] != "generic-fetcher":
        errors.append(f"source must be 'generic-fetcher', got {output['source']!r}")

    if "tries" not in output:
        errors.append("missing 'tries' field")
    elif not isinstance(output["tries"], list):
        errors.append("'tries' must be a list")
    else:
        for i, entry in enumerate(output["tries"]):
            if not isinstance(entry, dict):
                errors.append(f"tries[{i}] must be an object, got {type(entry).__name__}")
                continue
            missing = TRY_KEYS - set(entry)
            if missing:
                errors.append(f"tries[{i}] missing keys: {sorted(missing)}")

    if output.get("status") == "success" and "file_path" not in output:
        errors.append("status=success requires 'file_path'")

    if output.get("status") == "auth_required" and not output.get("url"):
        errors.append("status=auth_required requires 'url'")

    return errors


# ---------------------------------------------------------------------------
# Frontmatter validation
# ---------------------------------------------------------------------------


class TestFrontmatter:
    """agents/generic-fetcher.md must have all required frontmatter fields."""

    def test_agent_file_exists(self):
        assert os.path.isfile(AGENT_FILE), f"agents/generic-fetcher.md not found at {AGENT_FILE}"

    def test_frontmatter_name(self):
        fm, _ = _agent()
        assert fm.get("name") == "generic-fetcher"

    def test_frontmatter_model(self):
        fm, _ = _agent()
        assert fm.get("model") == "sonnet"

    def test_frontmatter_max_turns(self):
        fm, _ = _agent()
        assert fm.get("maxTurns") == 20

    def test_frontmatter_tools_contains_browser_use(self):
        fm, _ = _agent()
        tools = fm.get("tools", [])
        tool_str = " ".join(str(t) for t in tools)
        assert "browser-use" in tool_str, f"tools must reference browser-use, got: {tools}"

    def test_frontmatter_tools_contains_read_write(self):
        fm, _ = _agent()
        tools = fm.get("tools", [])
        tool_str = " ".join(str(t) for t in tools)
        assert "Read" in tool_str and "Write" in tool_str, (
            f"tools must include Read and Write, got: {tools}"
        )


# ---------------------------------------------------------------------------
# DOM heuristic keyword checks in system prompt
# ---------------------------------------------------------------------------


class TestDOMHeuristics:
    """System prompt must contain all required DOM heuristic keywords."""

    POSITIVE_PDF_INDICATORS = [
        "Download PDF",
        "PDF herunterladen",
        "Get PDF",
        "Volltext (PDF)",
        "Full Text",
        "View PDF",
    ]

    NEGATIVE_PDF_INDICATORS = [
        "Vorschau",
        "Preview",
        "Sample Chapter",
    ]

    PAYWALL_SIGNALS = [
        "Get Access",
        "Purchase",
        "Subscribe",
        "Sign in to view",
        "Anmelden für Volltext",
    ]

    def test_positive_pdf_indicators_present(self):
        _, body = _agent()
        missing = [kw for kw in self.POSITIVE_PDF_INDICATORS if kw not in body]
        assert not missing, f"System prompt missing positive PDF indicators: {missing}"

    def test_negative_pdf_indicators_present(self):
        _, body = _agent()
        missing = [kw for kw in self.NEGATIVE_PDF_INDICATORS if kw not in body]
        assert not missing, f"System prompt missing negative PDF indicators: {missing}"

    def test_paywall_signals_present(self):
        _, body = _agent()
        missing = [kw for kw in self.PAYWALL_SIGNALS if kw not in body]
        assert not missing, f"System prompt missing paywall signals: {missing}"

    def test_captcha_detection_present(self):
        _, body = _agent()
        assert "captcha" in body.lower() or "reCAPTCHA" in body, (
            "System prompt must mention captcha detection"
        )

    def test_levenshtein_threshold_mentioned(self):
        _, body = _agent()
        assert "30" in body and ("levenshtein" in body.lower() or "Levenshtein" in body), (
            "System prompt must mention Levenshtein threshold of 30%"
        )

    def test_pickup_required_safety_boundary(self):
        _, body = _agent()
        assert "pickup_required" in body, (
            "System prompt must mention pickup_required as safety-boundary default"
        )

    def test_distinguishes_a_vs_button(self):
        _, body = _agent()
        assert "<a>" in body or "<a " in body, "System prompt must distinguish <a> elements"
        assert "<button>" in body or "<button " in body, (
            "System prompt must distinguish <button> elements"
        )


# ---------------------------------------------------------------------------
# Kopplung Prompt <-> Python-Spiegel (Risiko 1 aus dem Plan: Spiegel-Drift)
# ---------------------------------------------------------------------------


class TestPromptMirrorCoupling:
    """Der Spiegel darf nicht vom Prompt abdriften — beide Richtungen geprueft."""

    def test_viewer_patterns_documented_in_prompt(self):
        """Jedes Viewer-Muster des Spiegels steht woertlich im Agent-Prompt (AC4)."""
        _, body = _agent()
        missing = [p.prompt_marker for p in VIEWER_PATTERNS if p.prompt_marker not in body]
        assert not missing, f"Viewer-Muster fehlen im Prompt: {missing}"

    def test_every_state_of_the_mirror_is_documented(self):
        """Vorwaerts: jeder Zustand des Spiegels steht im Prompt."""
        _, body = _agent()
        missing = [s for s in PAGE_STATES if f"`{s}`" not in body]
        assert not missing, f"Zustaende fehlen im Prompt: {missing}"

    def test_prompt_declares_no_state_beyond_the_mirror(self):
        """Rueckwaerts: die Zustandstabelle des Prompts nennt genau die Spiegel-Zustaende."""
        _, body = _agent()
        marker = "## Zustandsmodell"
        assert marker in body, "Prompt braucht einen Abschnitt '## Zustandsmodell'."
        section = body.split(marker, 1)[1].split("\n## ", 1)[0]
        rows = re.findall(r"^\|\s*`([a-z_]+)`\s*\|", section, re.M)
        assert set(rows) == set(PAGE_STATES), (
            f"Zustandstabelle im Prompt: {sorted(set(rows))} != Spiegel: {sorted(PAGE_STATES)}"
        )

    def test_every_decision_of_the_mirror_is_documented(self):
        """Jede protokollierbare Entscheidung steht woertlich im Prompt."""
        _, body = _agent()
        missing = [d for d in DECISIONS if d not in body]
        assert not missing, f"decision-Werte fehlen im Prompt: {missing}"

    def test_try_object_keys_documented_in_prompt(self):
        """Das tries[]-Objektschema ist im Prompt beschrieben (kein Freitext-String mehr)."""
        _, body = _agent()
        missing = [k for k in sorted(TRY_KEYS) if f"`{k}`" not in body]
        assert not missing, f"tries[]-Felder fehlen im Prompt: {missing}"


# ---------------------------------------------------------------------------
# Sicherheitsgrenze: keine Umgehung (AC2, Scope-Grenze des Issues)
# ---------------------------------------------------------------------------


class TestSafetyBoundaries:
    def test_prompt_forbids_circumvention(self):
        """Der Prompt verbietet Umgehungsversuche explizit (Scope 'Out' des Issues)."""
        _, body = _agent()
        lowered = body.lower()
        required = [
            "scihub",
            "cookie",
            "header",
            "proxy",
            "captcha",
        ]
        missing = [kw for kw in required if kw not in lowered]
        assert not missing, f"Verbots-Kapitel nennt nicht: {missing}"
        assert "## Verbotene Aktionen" in body, "Prompt braucht '## Verbotene Aktionen'."
        section = body.split("## Verbotene Aktionen", 1)[1].split("\n## ", 1)[0]
        for kw in ("Proxy", "Cookie", "Header", "SciHub", "curl"):
            assert kw.lower() in section.lower(), (
                f"'{kw}' fehlt im Verbots-Kapitel: {section[:200]!r}"
            )

    def test_prompt_does_not_change_scihub_logic(self):
        """Der Agent ruft SciHub nicht auf — die SciHub-Logik bleibt unangetastet."""
        _, body = _agent()
        section = body.split("## Verbotene Aktionen", 1)[1].split("\n## ", 1)[0]
        assert re.search(r"kein.{0,40}scihub", section, re.I | re.S), (
            "Der Prompt muss den SciHub-Umweg ausdruecklich verbieten."
        )


# ---------------------------------------------------------------------------
# Output-Schema (inkl. neuem tries[]-Objektschema)
# ---------------------------------------------------------------------------


def _try(step: int, action: str, decision: str) -> dict:
    return {
        "step": step,
        "action": action,
        "url": "https://example.com/a",
        "observation": "beobachtet",
        "decision": decision,
    }


class TestOutputSchema:
    def test_case_success_pdf_link(self):
        output = {
            "status": "success",
            "source": "generic-fetcher",
            "file_path": "/tmp/advanced-topics-ai.pdf",
            "reason": "Found 'Download PDF' link, downloaded successfully.",
            "tries": [
                _try(1, "load_page", "pdf_link_detected"),
                _try(2, "download_pdf", "downloaded"),
            ],
        }
        assert not _validate_output_schema(output)

    def test_case_pickup_required_paywall(self):
        output = {
            "status": "pickup_required",
            "source": "generic-fetcher",
            "reason": "Paywall detected ('Get Access'), no matching library profile.",
            "tries": [_try(1, "load_page", "paywall_no_license")],
        }
        assert not _validate_output_schema(output)

    def test_case_auth_required_carries_profile_route(self):
        output = {
            "status": "auth_required",
            "source": "generic-fetcher",
            "url": "https://link.springer.com.proxy.uni.de/book/1",
            "reason": "Licensed host, profile route available.",
            "tries": [_try(1, "load_page", "licensed_route")],
        }
        assert not _validate_output_schema(output)

    def test_all_statuses_are_schema_valid(self):
        cases = [
            {
                "status": "success",
                "source": "generic-fetcher",
                "file_path": "/tmp/test.pdf",
                "tries": [],
            },
            {"status": "pickup_required", "source": "generic-fetcher", "tries": []},
            {"status": "captcha", "source": "generic-fetcher", "tries": []},
            {"status": "no_match", "source": "generic-fetcher", "tries": []},
            {
                "status": "auth_required",
                "source": "generic-fetcher",
                "url": "https://x.de/a",
                "tries": [],
            },
        ]
        for i, case in enumerate(cases):
            errors = _validate_output_schema(case)
            assert not errors, f"Case {i + 1} ({case['status']}) schema errors: {errors}"

    def test_invalid_status_rejected(self):
        errors = _validate_output_schema(
            {"status": "unknown_status", "source": "generic-fetcher", "tries": []}
        )
        assert any("invalid status" in e for e in errors)

    def test_missing_file_path_on_success_rejected(self):
        errors = _validate_output_schema(
            {"status": "success", "source": "generic-fetcher", "tries": []}
        )
        assert any("file_path" in e for e in errors)

    def test_string_tries_rejected(self):
        """Schema-Umstellung: Freitext-Strings im tries-Array sind nicht mehr gueltig."""
        errors = _validate_output_schema(
            {"status": "pickup_required", "source": "generic-fetcher", "tries": ["Loaded page"]}
        )
        assert any("must be an object" in e for e in errors)

    def test_prompt_examples_use_object_tries(self):
        """Alle JSON-Beispiele im Prompt zeigen das Objekt-Schema."""
        _, body = _agent()
        for block in re.findall(r"```json\n(.*?)```", body, re.DOTALL):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or "tries" not in data:
                continue
            for entry in data["tries"]:
                assert isinstance(entry, dict), f"Prompt-Beispiel nutzt String-tries: {entry!r}"
                assert TRY_KEYS <= set(entry), f"Unvollstaendiger tries-Eintrag im Prompt: {entry}"


# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------


class TestHTMLFixtures:
    def test_pdf_link_fixture_has_download_pdf(self):
        assert "Download PDF" in _fixture("pdf_link.html")

    def test_paywall_fixture_has_get_access(self):
        content = _fixture("paywall.html")
        assert "Get Access" in content or "Subscribe" in content

    def test_ambiguous_fixture_has_no_pdf_link_and_no_paywall(self):
        content = _fixture("ambiguous.html")
        assert "Download PDF" not in content
        assert "Get PDF" not in content
        assert "Get Access" not in content
        assert "Subscribe" not in content
        assert "Purchase" not in content

    @pytest.mark.parametrize(
        "name",
        [
            "embedded_viewer.html",
            "embedded_object.html",
            "licensed_gate.html",
            "login_wall.html",
            "redirect_hop.html",
        ],
    )
    def test_new_fixtures_exist(self, name):
        assert os.path.isfile(os.path.join(FIXTURES_DIR, name)), f"Fixture fehlt: {name}"


# ---------------------------------------------------------------------------
# AC1: Volltext von >= 3 Plattformen ohne dedizierten Agent
# ---------------------------------------------------------------------------

PLATFORM_CASES = [c for c in _load_eval_cases() if c.get("type") == "platform_navigation"]


class TestPlatformCases:
    def test_at_least_three_platform_cases(self):
        assert len(PLATFORM_CASES) >= 3, (
            f"AC1 verlangt >= 3 Plattform-Cases, gefunden: {len(PLATFORM_CASES)}"
        )

    def test_platform_cases_have_no_dedicated_agent(self):
        """Gegenprobe: keine der Plattformen hat einen eigenen Agent unter agents/."""
        agent_names = {f[:-3] for f in os.listdir(AGENTS_DIR) if f.endswith(".md")}
        for case in PLATFORM_CASES:
            platform = case["platform"]
            assert platform not in agent_names, (
                f"{platform} hat einen dedizierten Agent — taugt nicht als Fallback-Nachweis."
            )

    @pytest.mark.parametrize("case", PLATFORM_CASES, ids=lambda c: c["id"])
    def test_platform_fulltext_with_logged_path(self, case):
        nav = GenericFetcherNavigator(
            profile={}, pages={case["input"]["url"]: _fixture(case["input"]["fixture"])}
        )
        result = nav.navigate(case["input"]["url"], title=case["input"].get("title"))

        assert not _validate_output_schema(result), _validate_output_schema(result)
        assert result["status"] == "success", f"{case['id']}: {result}"
        assert result["file_path"], f"{case['id']}: kein file_path"
        assert len(result["tries"]) >= 2, (
            f"{case['id']}: Weg nicht protokolliert: {result['tries']}"
        )
        for entry in result["tries"]:
            assert TRY_KEYS <= set(entry), f"{case['id']}: unvollstaendiger tries-Eintrag {entry}"
            assert entry["observation"], f"{case['id']}: leere observation"
            assert entry["decision"] in DECISIONS, f"{case['id']}: unbekannte decision {entry}"


# ---------------------------------------------------------------------------
# AC2: Paywall ohne Lizenz -> Abbruch mit Grund, keine Umgehung
# ---------------------------------------------------------------------------


class TestPaywallAbort:
    def test_paywall_without_license_aborts_with_reason(self):
        url = "https://publisher.example.org/book/9780123"
        nav = GenericFetcherNavigator(
            profile={"licensed_sites": ["link.springer.com"]},
            pages={url: _fixture("paywall.html")},
        )
        result = nav.navigate(url, title="Machine Learning Methods")

        assert result["status"] == "pickup_required", result
        assert "Get Access" in result["reason"], result["reason"]
        assert "lizenz" in result["reason"].lower() or "license" in result["reason"].lower()
        # Terminierung statt Weiterklicken: nach der Zustandsfeststellung keine Aktion mehr.
        assert len(result["tries"]) == 1, result["tries"]
        assert result["tries"][0]["decision"] == "paywall_no_license"

    def test_login_wall_without_license_aborts(self):
        url = "https://publisher.example.org/article/7"
        nav = GenericFetcherNavigator(
            profile={"licensed_sites": []}, pages={url: _fixture("login_wall.html")}
        )
        result = nav.navigate(url, title="Hidden Article")

        assert result["status"] == "pickup_required", result
        assert result["tries"][-1]["decision"] == "login_wall_no_license"
        assert len(result["tries"]) == 1

    def test_ambiguous_page_still_hits_safety_boundary(self):
        """Negativkontrolle zur neuen Viewer-Heuristik: nicht alles ist ein PDF."""
        url = "https://unknown-publisher.net/quantum-overview"
        nav = GenericFetcherNavigator(profile={}, pages={url: _fixture("ambiguous.html")})
        result = nav.navigate(url, title="Quantum Overview")

        assert result["status"] == "pickup_required", result
        assert result["tries"][-1]["decision"] == "safety_boundary"

    def test_page_that_does_not_load_is_no_match(self):
        url = "https://gone.example.org/x"
        nav = GenericFetcherNavigator(profile={}, pages={})
        result = nav.navigate(url, title="Gone")

        assert result["status"] == "no_match", result
        assert result["tries"][-1]["decision"] == "page_unavailable"


# ---------------------------------------------------------------------------
# AC3: Lizenzierte Domain -> Profil-Zugangsweg statt anonymer Kopien
# ---------------------------------------------------------------------------


LICENSED_PROFILE = {
    "uni": "tum",
    "auth_url": "https://login.tum.de/idp/",
    "licensed_sites": ["publisher.example.org"],
    "proxy_pattern": "https://{host}.proxy.ub.tum.de{path}",
}


class TestLicensedRoute:
    def test_licensed_host_takes_profile_route(self):
        url = "https://publisher.example.org/book/9780123"
        nav = GenericFetcherNavigator(
            profile=LICENSED_PROFILE, pages={url: _fixture("licensed_gate.html")}
        )
        result = nav.navigate(url, title="ML Methods")

        assert result["status"] == "auth_required", result
        assert result["url"] == "https://publisher.example.org.proxy.ub.tum.de/book/9780123"
        assert result["tries"][-1]["decision"] == "licensed_route"
        # Keine Suche nach anonymen Kopien auf Fremdplattformen.
        for entry in result["tries"]:
            assert "publisher.example.org" in entry["url"], entry

    def test_licensed_host_without_proxy_pattern_uses_auth_url(self):
        url = "https://publisher.example.org/book/9780123"
        profile = dict(LICENSED_PROFILE)
        profile.pop("proxy_pattern")
        nav = GenericFetcherNavigator(profile=profile, pages={url: _fixture("licensed_gate.html")})
        result = nav.navigate(url, title="ML Methods")

        assert result["status"] == "auth_required", result
        assert result["url"] == "https://login.tum.de/idp/"

    def test_session_context_reuses_existing_session(self):
        """Mit bestehender Session wird der Profil-Weg direkt genutzt statt erneut Auth zu melden."""
        url = "https://publisher.example.org/book/9780123"
        proxied = "https://publisher.example.org.proxy.ub.tum.de/book/9780123"
        nav = GenericFetcherNavigator(
            profile=LICENSED_PROFILE,
            pages={url: _fixture("licensed_gate.html"), proxied: _fixture("pdf_link.html")},
        )
        result = nav.navigate(
            url, title="Advanced Topics in AI", session_context="browser-use:active:tum"
        )

        assert result["status"] == "success", result
        assert result["file_path"]
        actions = [t["action"] for t in result["tries"]]
        assert "open_profile_route" in actions, actions

    def test_unlicensed_host_never_reports_auth_required(self):
        url = "https://publisher.example.org/book/9780123"
        nav = GenericFetcherNavigator(
            profile={"licensed_sites": [], "auth_url": "https://login.tum.de/idp/"},
            pages={url: _fixture("licensed_gate.html")},
        )
        result = nav.navigate(url, title="ML Methods")
        assert result["status"] == "pickup_required", result


# ---------------------------------------------------------------------------
# AC4: Eingebettetes PDF hinter JS-Viewer
# ---------------------------------------------------------------------------


class TestEmbeddedViewer:
    @pytest.mark.parametrize(
        ("fixture", "expected_pdf"),
        [
            ("embedded_viewer.html", "https://viewer.example.org/docs/paper.pdf"),
            ("embedded_object.html", "https://viewer.example.org/docs/paper.pdf"),
        ],
    )
    def test_embedded_pdf_detected_and_saved(self, fixture, expected_pdf):
        url = "https://viewer.example.org/read/42"
        nav = GenericFetcherNavigator(profile={}, pages={url: _fixture(fixture)})
        result = nav.navigate(url, title="Embedded Paper")

        assert result["status"] == "success", result
        assert result["file_path"], result
        assert result["pdf_url"] == expected_pdf, result
        decisions = [t["decision"] for t in result["tries"]]
        assert "embedded_pdf_detected" in decisions, decisions

    def test_content_type_pdf_after_redirect_is_detected(self):
        url = "https://viewer.example.org/download/42"
        nav = GenericFetcherNavigator(
            profile={}, pages={url: "Content-Type: application/pdf\n\n%PDF-1.7 binary"}
        )
        result = nav.navigate(url, title="Direct PDF Response")

        assert result["status"] == "success", result
        assert result["pdf_url"] == url


# ---------------------------------------------------------------------------
# AC5: Terminierung innerhalb eines definierten Schritt-Budgets
# ---------------------------------------------------------------------------


class TestStepBudget:
    def test_frontmatter_declares_step_budget(self):
        fm, body = _agent()
        max_steps = fm.get("maxSteps")
        assert isinstance(max_steps, int) and max_steps > 0, (
            f"Frontmatter braucht ein positives int 'maxSteps', gefunden: {max_steps!r}"
        )
        assert "maxSteps" in body, "Das Schritt-Budget muss auch im Prompt-Body dokumentiert sein."
        assert "step_budget_exhausted" in body

    def test_mirror_reads_budget_from_frontmatter(self):
        fm, _ = _agent()
        assert load_max_steps() == fm["maxSteps"]

    def test_navigator_terminates_at_budget(self):
        """Endlose Weiterverweisung endet nach genau maxSteps Aktionen."""
        max_steps = load_max_steps()
        hop = _fixture("redirect_hop.html")
        nav = GenericFetcherNavigator(profile={}, pages=lambda url: hop)
        result = nav.navigate("https://loop.example.org/start", title="Loop")

        assert result["status"] == "pickup_required", result
        assert result["reason"] == "step_budget_exhausted", result
        assert len(result["tries"]) == max_steps, len(result["tries"])

    def test_every_fixture_terminates_within_budget(self):
        max_steps = load_max_steps()
        url = "https://any.example.org/x"
        for name in sorted(os.listdir(FIXTURES_DIR)):
            if not name.endswith(".html") or name == "redirect_hop.html":
                continue
            nav = GenericFetcherNavigator(profile={}, pages={url: _fixture(name)})
            result = nav.navigate(url, title="Whatever")
            assert result["status"] in VALID_STATUSES, (name, result)
            assert len(result["tries"]) <= max_steps, (name, result["tries"])
