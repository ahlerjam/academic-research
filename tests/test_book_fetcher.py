"""
Tests for book-fetcher Master-Agent routing logic.

Tests validate the routing algorithm in tests/helpers/book_fetcher_router.py,
which mirrors the agent prompt in agents/book-fetcher.md.
"""

import json
import pathlib
import unittest
from unittest.mock import patch

import yaml

from tests.helpers.book_fetcher_router import BookFetcherRouter

# Path to fixtures
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "book_fetcher_mocks"


def _load_json(name):
    return json.loads((FIXTURES / name).read_text())


def _load_yaml(name):
    return yaml.safe_load((FIXTURES / name).read_text())


class TestBookFetcherInputParsing(unittest.TestCase):
    """Test that ISBN, DOI, URL, and free-text inputs are correctly classified."""

    def setUp(self):
        profile = _load_yaml("active_profile_springer.yaml")
        self.router = BookFetcherRouter(profile=profile)

    def test_isbn_13_detected(self):
        t, v = self.router.parse_input("isbn: 978-3-16-148410-0")
        self.assertEqual(t, "isbn")
        self.assertEqual(v, "978-3-16-148410-0")

    def test_isbn_bare_detected(self):
        t, v = self.router.parse_input("978-3-662-54347-6")
        self.assertEqual(t, "isbn")

    def test_doi_detected(self):
        t, v = self.router.parse_input("10.1007/978-3-662-54347-6")
        self.assertEqual(t, "doi")

    def test_url_detected(self):
        t, v = self.router.parse_input("https://link.springer.com/book/10.1007/978")
        self.assertEqual(t, "url")

    def test_freetext_fallback(self):
        t, v = self.router.parse_input("Advanced Topics in Machine Learning")
        self.assertEqual(t, "title")


class TestBookFetcherRouting(unittest.TestCase):
    """Test the full routing chain with mocked subagent dispatch."""

    def _make_router(self, profile_file="active_profile_springer.yaml"):
        profile = _load_yaml(profile_file)
        return BookFetcherRouter(profile=profile)

    def test_isbn_routes_to_doabooks_first(self):
        """ISBN input: doabooks-fetcher is first subagent called; on success, returns immediately."""
        router = self._make_router()
        doabooks_resp = _load_json("doabooks_success.json")

        with patch.object(router, "dispatch_subagent", return_value=doabooks_resp) as mock_dispatch:
            result = router.fetch("978-3-16-148410-0", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "doabooks-fetcher")
        self.assertEqual(result["tries"][0]["subagent"], "doabooks-fetcher")
        self.assertEqual(result["tries"][0]["status"], "success")
        # Only one subagent call (success on first try)
        self.assertEqual(mock_dispatch.call_count, 1)
        first_call_args = mock_dispatch.call_args_list[0]
        self.assertEqual(first_call_args[0][0], "doabooks-fetcher")

    def test_oa_subagent_edition_field_propagates_to_master_output(self):
        """AC4 (Issue #450): liefert der erfolgreiche OA-Subagent ein `edition`-
        Feld (Jahr/Ausgabe/Verlag des Digitalisats, z.B. hathitrust-fetcher),
        muss der Master-Output dieses Feld unveraendert weiterreichen -- sonst
        geht die Angabe an der Router-Grenze verloren, bevor sie ueberhaupt bei
        commands/fetch.md ankommen kann."""
        router = self._make_router()
        hathitrust_success = {
            "status": "success",
            "source_subagent": "hathitrust-fetcher",
            "pdf_path": "/tmp/kant.pdf",
            "url": "https://babel.hathitrust.org/cgi/pt?id=example",
            "edition": "1799, Ausgabe B, Verlag Hartknoch",
        }

        def side_effect(subagent, payload):
            if subagent == "hathitrust-fetcher":
                return hathitrust_success
            return {"status": "no_match", "source_subagent": subagent}

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Kritik der reinen Vernunft", output_path="/tmp/kant.pdf")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "hathitrust-fetcher")
        self.assertEqual(
            result.get("edition"),
            "1799, Ausgabe B, Verlag Hartknoch",
            "edition-Feld muss vom Subagenten-Output in den Master-Output "
            "durchgereicht werden (AC4, Issue #450)",
        )

    def test_success_without_edition_omits_edition_key(self):
        """Aeltere OA-Fetcher (vor #450) liefern kein edition-Feld -- der Master
        darf dafuer keinen Platzhalter erfinden, das Feld muss schlicht fehlen."""
        router = self._make_router()
        doabooks_resp = _load_json("doabooks_success.json")

        with patch.object(router, "dispatch_subagent", return_value=doabooks_resp):
            result = router.fetch("978-3-16-148410-0", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "success")
        self.assertNotIn("edition", result)

    def test_all_oa_metadata_only_then_springer_success(self):
        """OA subagents all return metadata_only; Springer (licensed) returns success."""
        router = self._make_router("active_profile_springer.yaml")
        meta_only = {
            "status": "metadata_only",
            "source_subagent": "doabooks-fetcher",
            "url": "https://example.com",
        }
        springer_success = _load_json("springer_success.json")

        call_count = [0]
        oa_subagents = {
            "doabooks-fetcher",
            "oapen-fetcher",
            "tib-fetcher",
            "kvk-fetcher",
            "hathitrust-fetcher",
            "internetarchive-fetcher",
            "mdz-fetcher",
        }

        def side_effect(subagent, payload):
            call_count[0] += 1
            if subagent in oa_subagents:
                return dict(meta_only, source_subagent=subagent)
            if subagent == "springer-book":
                return springer_success
            raise AssertionError(f"Unexpected subagent call: {subagent}")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("978-3-662-54347-6", output_path="/tmp/springer.pdf")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "springer-book")
        # tries must show all 7 free-archive subagents first, then springer-book (AC3)
        subagent_sequence = [t["subagent"] for t in result["tries"]]
        self.assertEqual(
            subagent_sequence[:7],
            [
                "doabooks-fetcher",
                "oapen-fetcher",
                "tib-fetcher",
                "kvk-fetcher",
                "hathitrust-fetcher",
                "internetarchive-fetcher",
                "mdz-fetcher",
            ],
        )
        self.assertIn("springer-book", subagent_sequence)

    def test_auth_required_triggers_auth_helper_then_retry(self):
        """Springer returns auth_required -> auth-helper called -> springer retried -> success."""
        router = self._make_router("active_profile_springer.yaml")
        meta_only = {"status": "metadata_only", "source_subagent": "x", "url": "https://x.com"}
        auth_req = _load_json("springer_auth_required.json")
        auth_ok = _load_json("auth_helper_authenticated.json")
        springer_ok = _load_json("springer_success.json")
        oa_subagents = {
            "doabooks-fetcher",
            "oapen-fetcher",
            "tib-fetcher",
            "kvk-fetcher",
            "hathitrust-fetcher",
            "internetarchive-fetcher",
            "mdz-fetcher",
        }
        springer_calls = [0]

        def side_effect(subagent, payload):
            if subagent in oa_subagents:
                return dict(meta_only, source_subagent=subagent)
            if subagent == "springer-book":
                springer_calls[0] += 1
                if springer_calls[0] == 1:
                    return auth_req
                return springer_ok
            if subagent == "auth-helper":
                return auth_ok
            raise AssertionError(f"Unexpected: {subagent}")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("978-3-662-54347-6", output_path="/tmp/springer.pdf")

        self.assertEqual(result["status"], "success")
        subagent_names = [t["subagent"] for t in result["tries"]]
        # auth-helper must appear in tries
        self.assertIn("auth-helper", subagent_names)
        # springer-book must appear twice
        self.assertEqual(subagent_names.count("springer-book"), 2)

    def test_captcha_propagates_immediately(self):
        """If any subagent returns captcha, master returns captcha immediately."""
        router = self._make_router()
        captcha_resp = _load_json("captcha.json")

        with patch.object(router, "dispatch_subagent", return_value=captcha_resp):
            result = router.fetch("978-3-16-148410-0", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "captcha")

    def test_all_fail_then_generic_fetcher_pickup_required(self):
        """All OA + no licensed publishers -> generic-fetcher -> pickup_required with hint."""
        router = self._make_router("active_profile_no_licensed.yaml")
        no_match = {
            "status": "no_match",
            "source_subagent": "doabooks-fetcher",
            "reason": "0 results",
        }
        generic_resp = _load_json("generic_pickup.json")
        oa_subagents = {
            "doabooks-fetcher",
            "oapen-fetcher",
            "tib-fetcher",
            "kvk-fetcher",
            "hathitrust-fetcher",
            "internetarchive-fetcher",
            "mdz-fetcher",
        }

        def side_effect(subagent, payload):
            if subagent in oa_subagents:
                return dict(no_match, source_subagent=subagent)
            if subagent == "generic-fetcher":
                return generic_resp
            raise AssertionError(f"Unexpected: {subagent}")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "pickup_required")
        self.assertIn("pickup_hint", result)
        self.assertIn("bib_pickup_url", result["pickup_hint"])
        self.assertIn("identifier", result["pickup_hint"])
        # generic-fetcher must be last in tries
        self.assertEqual(result["tries"][-1]["subagent"], "generic-fetcher")


class TestGenericFetcherAuthRoute(unittest.TestCase):
    """Issue #448: generic-fetcher meldet auth_required -> auth-helper -> genau ein Retry."""

    OA_SUBAGENTS = {
        "doabooks-fetcher",
        "oapen-fetcher",
        "tib-fetcher",
        "kvk-fetcher",
        "hathitrust-fetcher",
        "internetarchive-fetcher",
        "mdz-fetcher",
    }

    def _router(self):
        return BookFetcherRouter(profile=_load_yaml("active_profile_no_licensed.yaml"))

    def _dispatcher(self, generic_second):
        """Baut ein side_effect, das OA scheitern laesst und generic-fetcher steuert."""
        calls = []
        auth_req = _load_json("generic_auth_required.json")
        auth_ok = _load_json("auth_helper_authenticated.json")
        generic_calls = [0]

        def side_effect(subagent, payload):
            calls.append((subagent, dict(payload)))
            if subagent in self.OA_SUBAGENTS:
                return {"status": "no_match", "source_subagent": subagent}
            if subagent == "generic-fetcher":
                generic_calls[0] += 1
                return auth_req if generic_calls[0] == 1 else generic_second
            if subagent == "auth-helper":
                return auth_ok
            raise AssertionError(f"Unexpected subagent: {subagent}")

        return side_effect, calls

    def test_auth_required_triggers_auth_helper_and_single_retry(self):
        router = self._router()
        side_effect, calls = self._dispatcher(_load_json("generic_success.json"))

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["file_path"], "/tmp/out.pdf")

        tail = [(t["subagent"], t["status"]) for t in result["tries"]][-3:]
        self.assertEqual(
            tail,
            [
                ("generic-fetcher", "auth_required"),
                ("auth-helper", "authenticated"),
                ("generic-fetcher", "success"),
            ],
        )
        # Genau ein Retry -- nicht mehr.
        generic_calls = [c for c in calls if c[0] == "generic-fetcher"]
        self.assertEqual(len(generic_calls), 2, generic_calls)
        # Der auth-helper bekommt die Profil-Route aus der auth_required-Antwort.
        auth_call = next(c for c in calls if c[0] == "auth-helper")
        self.assertEqual(
            auth_call[1]["target_url"],
            "https://publisher.example.org.proxy.ub.tum.de/book/9780123",
        )
        # Die bestehende Session wird an den Retry weitergereicht.
        self.assertNotIn("session_context", generic_calls[0][1])
        self.assertEqual(generic_calls[1][1]["session_context"], "browser-use:active:tum")

    def test_auth_required_never_leaks_to_the_master_output(self):
        """Der Retry scheitert -- der Master meldet trotzdem einen der vier /fetch-Stati."""
        router = self._router()
        generic_pickup = _load_json("generic_pickup.json")
        side_effect, _ = self._dispatcher(generic_pickup)

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "pickup_required", result)
        self.assertIn("pickup_hint", result)

    def test_master_status_enum_matches_fetch_command(self):
        """Das nach aussen gemeldete Status-Enum bleibt das 4er-Set aus commands/fetch.md."""
        fetch_md = (pathlib.Path(__file__).parent.parent / "commands" / "fetch.md").read_text()
        for status in ("success", "pickup_required", "captcha", "no_match"):
            self.assertIn(status, fetch_md)
        self.assertNotIn("auth_required", fetch_md)

    def test_session_context_is_not_passed_without_authentication(self):
        """Ohne auth_required gibt es keinen session_context im generic-fetcher-Payload."""
        router = self._router()
        seen = []

        def side_effect(subagent, payload):
            seen.append((subagent, dict(payload)))
            if subagent in self.OA_SUBAGENTS:
                return {"status": "no_match", "source_subagent": subagent}
            if subagent == "generic-fetcher":
                return _load_json("generic_pickup.json")
            raise AssertionError(f"Unexpected subagent: {subagent}")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        generic_payloads = [p for name, p in seen if name == "generic-fetcher"]
        self.assertEqual(len(generic_payloads), 1)
        self.assertNotIn("session_context", generic_payloads[0])


class TestBookFetcherPromptDocumentsGenericAuth(unittest.TestCase):
    """agents/book-fetcher.md muss den neuen generic-fetcher-Pfad beschreiben."""

    def setUp(self):
        self.body = (
            pathlib.Path(__file__).parent.parent / "agents" / "book-fetcher.md"
        ).read_text()

    def test_prompt_documents_generic_auth_required(self):
        step5 = self.body.split("## Schritt 5", 1)[1].split("\n## ", 1)[0]
        self.assertIn("auth_required", step5)
        self.assertIn("auth-helper", step5)
        self.assertIn("session_context", step5)
        self.assertIn("einmalig", step5.lower())

    def test_prompt_keeps_outward_status_enum_at_four(self):
        schema = self.body.split("## Output-Schema", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("auth_required", schema)


class TestBookFetcherAgentMarkdown(unittest.TestCase):
    """Validate the agent Markdown file has correct frontmatter."""

    @staticmethod
    def _agent_path() -> pathlib.Path:
        # Robust: resolve from test file location upward to repo root
        return pathlib.Path(__file__).parent.parent / "agents" / "book-fetcher.md"

    def test_agent_file_exists(self):
        agent_path = self._agent_path()
        self.assertTrue(agent_path.exists(), f"agents/book-fetcher.md not found at {agent_path}")

    def test_frontmatter_fields(self):
        agent_path = self._agent_path()
        content = agent_path.read_text()
        # Extract YAML frontmatter between --- delimiters
        lines = content.split("\n")
        self.assertEqual(lines[0].strip(), "---", "Agent must start with ---")
        end = lines.index("---", 1)
        fm_text = "\n".join(lines[1:end])
        fm = yaml.safe_load(fm_text)
        self.assertEqual(fm.get("name"), "book-fetcher")
        self.assertIn("sonnet", fm.get("model", "").lower(), "model must be sonnet")
        self.assertIsInstance(fm.get("tools"), list, "tools must be a list")
        self.assertGreaterEqual(fm.get("maxTurns", 0), 8, "maxTurns must be >= 8")

    def test_no_bash_in_tools(self):
        agent_path = self._agent_path()
        content = agent_path.read_text()
        lines = content.split("\n")
        end = lines.index("---", 1)
        fm_text = "\n".join(lines[1:end])
        fm = yaml.safe_load(fm_text)
        tools = fm.get("tools", [])
        bash_tools = [t for t in tools if "Bash" in str(t)]
        self.assertEqual(
            bash_tools, [], f"Master agent must NOT have Bash tools, found: {bash_tools}"
        )


if __name__ == "__main__":
    unittest.main()
