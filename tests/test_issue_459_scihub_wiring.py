"""Regressionstest fuer Issue #459 — SciHub-Tier: stille Aktivierung ueber Flag.

Ausgangslage laut Plan-Kommentar (`gh issue view 459`): `agents/scihub-fetcher.md`
hatte bereits ein Opt-in-Gate und Provenance-Tagging, war aber in keinem
Orchestrator-Pfad erreichbar -- `book-fetcher.md` kannte kein
`Agent(scihub-fetcher)`. Dieser Test deckt die Verdrahtung sowie die uebrigen
Akzeptanzkriterien ab:

AC1 - Flag gesetzt -> Tier laeuft ohne weitere Rueckfrage/Wiederholungswarnung.
AC2 - Flag nicht gesetzt -> Tier wird vollstaendig uebersprungen (nie gedispatcht).
AC3 - Beschaffungsweg erscheint nicht im Kontext von Kapitel-/Zitations-Skills.
AC4 - Identische Quelle, unterschiedlicher Kanal -> identische Zitation/Behandlung.
AC5 - Direkte Herkunftsfrage bleibt beantwortbar (Vault-Ebene, Anschluss #195).
"""

import json
import pathlib
import unittest
from unittest.mock import patch

import yaml

from tests.helpers.book_fetcher_router import OA_SITES, BookFetcherRouter, is_free_tier_call

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "book_fetcher_mocks"
BOOK_FETCHER_AGENT = REPO_ROOT / "agents" / "book-fetcher.md"
SCIHUB_AGENT = REPO_ROOT / "agents" / "scihub-fetcher.md"
FETCH_COMMAND = REPO_ROOT / "commands" / "fetch.md"
CHAPTER_WRITER_SKILL = REPO_ROOT / "skills" / "chapter-writer" / "SKILL.md"
CITATION_EXTRACTION_SKILL = REPO_ROOT / "skills" / "citation-extraction" / "SKILL.md"

# Issue #450: die freie Stufe wuchs von 4 auf 7 Sites.
# Issue #840: sechs davon laufen ueber generic-fetcher mit site_config -- der
# Agent-Name allein unterscheidet sie nicht mehr vom Fallback aus Schritt 5,
# deshalb `is_free_tier_call` aus der gemeinsamen Quelle statt einer Namensmenge.
FREE_TIER_SITE_COUNT = len(OA_SITES)


def _load_json(name):
    return json.loads((FIXTURES / name).read_text())


def _load_yaml(name):
    return yaml.safe_load((FIXTURES / name).read_text())


def _all_oa_and_generic_no_match_dispatcher(final_generic_status_name, extra=None):
    """Baut ein side_effect: alle OA-Subagenten + generic-fetcher liefern
    Fehlschlaege, damit die Routing-Logik bei Schritt 6 (SciHub) ankommt."""
    calls = []
    generic_resp = _load_json(final_generic_status_name)

    def side_effect(subagent, payload):
        calls.append((subagent, dict(payload)))
        if is_free_tier_call(subagent, payload):
            return {"status": "no_match", "source": subagent}
        if subagent == "generic-fetcher":
            return generic_resp
        if extra and subagent in extra:
            return extra[subagent]
        raise AssertionError(f"Unexpected subagent call: {subagent}")

    return side_effect, calls


class TestScihubDispatchedWhenOptedIn(unittest.TestCase):
    """AC1: Flag gesetzt -> Tier laeuft ohne weitere Rueckfrage/Wiederholung."""

    def _router(self):
        return BookFetcherRouter(profile=_load_yaml("active_profile_scihub_optin.yaml"))

    def test_scihub_dispatched_after_generic_pickup_required(self):
        router = self._router()
        scihub_success = _load_json("scihub_success.json")
        side_effect, calls = _all_oa_and_generic_no_match_dispatcher(
            "generic_pickup.json", extra={"scihub-fetcher": scihub_success}
        )

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/scihub-out.pdf")

        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["source"], "scihub-fetcher")
        self.assertEqual(result["file_path"], "/tmp/scihub-out.pdf")

        scihub_calls = [c for c in calls if c[0] == "scihub-fetcher"]
        self.assertEqual(len(scihub_calls), 1, "scihub-fetcher muss genau einmal aufgerufen werden")

    def test_no_extra_confirmation_call_before_scihub_dispatch(self):
        """Der Master fragt nicht nach -- scihub-fetcher folgt direkt auf generic-fetcher."""
        router = self._router()
        scihub_success = _load_json("scihub_success.json")
        side_effect, calls = _all_oa_and_generic_no_match_dispatcher(
            "generic_pickup.json", extra={"scihub-fetcher": scihub_success}
        )

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            router.fetch("Advanced Topics in AI", output_path="/tmp/scihub-out.pdf")

        subagent_sequence = [c[0] for c in calls]
        self.assertEqual(subagent_sequence[-2:], ["generic-fetcher", "scihub-fetcher"])

    def test_scihub_captcha_propagates_immediately(self):
        router = self._router()
        scihub_captcha = _load_json("scihub_captcha.json")
        side_effect, _ = _all_oa_and_generic_no_match_dispatcher(
            "generic_pickup.json", extra={"scihub-fetcher": scihub_captcha}
        )

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "captcha")
        self.assertEqual(result["source"], "scihub-fetcher")

    def test_scihub_no_match_falls_back_to_pickup_required(self):
        """SciHub selbst findet nichts -- Master faellt auf das bisherige pickup_required zurueck."""
        router = self._router()
        scihub_no_match = _load_json("scihub_no_match.json")
        side_effect, calls = _all_oa_and_generic_no_match_dispatcher(
            "generic_pickup.json", extra={"scihub-fetcher": scihub_no_match}
        )

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "pickup_required", result)
        self.assertIn("pickup_hint", result)
        self.assertEqual([c[0] for c in calls if c[0] == "scihub-fetcher"], ["scihub-fetcher"])


class TestScihubSkippedWhenOptinFalseOrMissing(unittest.TestCase):
    """AC2: Flag nicht gesetzt -> Tier wird vollstaendig uebersprungen."""

    def test_scihub_never_dispatched_when_optin_false(self):
        router = BookFetcherRouter(profile=_load_yaml("active_profile_no_licensed.yaml"))
        side_effect, calls = _all_oa_and_generic_no_match_dispatcher("generic_pickup.json")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "pickup_required")
        subagent_names = [c[0] for c in calls]
        self.assertNotIn("scihub-fetcher", subagent_names)

    def test_scihub_never_dispatched_when_key_missing(self):
        """Profil ganz ohne scihub_optin-Key -- Safety-Default False."""
        profile = _load_yaml("active_profile_no_licensed.yaml")
        self.assertNotIn("scihub_optin", profile, "Fixture darf den Key nicht bereits setzen")
        router = BookFetcherRouter(profile=profile)
        side_effect, calls = _all_oa_and_generic_no_match_dispatcher("generic_pickup.json")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertNotIn("scihub-fetcher", [c[0] for c in calls])

    def test_result_unchanged_from_pre_wiring_behavior_when_optin_false(self):
        """Ohne Opt-in bleibt das Ergebnis identisch zum bisherigen (Vor-#459-)Verhalten."""
        router = BookFetcherRouter(profile=_load_yaml("active_profile_no_licensed.yaml"))
        generic_resp = _load_json("generic_pickup.json")

        def side_effect(subagent, payload):
            if is_free_tier_call(subagent, payload):
                return {"status": "no_match", "source": subagent}
            if subagent == "generic-fetcher":
                return generic_resp
            raise AssertionError(f"Unexpected: {subagent}")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("Advanced Topics in AI", output_path="/tmp/out.pdf")

        self.assertEqual(result["status"], "pickup_required")
        self.assertEqual(result["tries"][-1]["subagent"], "generic-fetcher")


class TestScihubSuccessSkipsPublisherAndOaOnRetry(unittest.TestCase):
    """success bleibt am Router-Level unabhaengig davon, ob OA metadata_only lieferte."""

    def test_scihub_reached_after_licensed_publisher_all_fail_too(self):
        router = BookFetcherRouter(profile=_load_yaml("active_profile_scihub_optin.yaml"))
        scihub_success = _load_json("scihub_success.json")
        generic_resp = _load_json("generic_pickup.json")

        def side_effect(subagent, payload):
            if is_free_tier_call(subagent, payload):
                return {"status": "no_match", "source": subagent}
            if subagent == "generic-fetcher":
                return generic_resp
            if subagent == "scihub-fetcher":
                return scihub_success
            raise AssertionError(f"Unexpected: {subagent}")

        with patch.object(router, "dispatch_subagent", side_effect=side_effect):
            result = router.fetch("10.1234/example", output_path="/tmp/scihub-out.pdf")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "scihub-fetcher")


class TestBookFetcherPromptDocumentsScihubStep(unittest.TestCase):
    """agents/book-fetcher.md muss Schritt 6 (SciHub-Last-Resort) beschreiben."""

    def setUp(self):
        self.body = BOOK_FETCHER_AGENT.read_text(encoding="utf-8")

    def test_tools_list_includes_scihub_agent(self):
        lines = self.body.split("\n")
        end = lines.index("---", 1)
        fm = yaml.safe_load("\n".join(lines[1:end]))
        self.assertIn("Agent(scihub-fetcher)", fm.get("tools", []))

    def test_step_6_documents_scihub_last_resort(self):
        self.assertIn("## Schritt 6", self.body)
        step6 = self.body.split("## Schritt 6", 1)[1].split("\n## ", 1)[0]
        self.assertIn("scihub-fetcher", step6)
        self.assertIn("scihub_optin", step6)

    def test_step_6_documents_no_runtime_confirmation(self):
        """Schritt 6 muss explizit ausschliessen, dass zur Laufzeit nachgefragt wird."""
        step6 = self.body.split("## Schritt 6", 1)[1].split("\n## ", 1)[0]
        lowered = step6.lower()
        self.assertTrue(
            "kein" in lowered and ("rueckfrage" in lowered or "rückfrage" in lowered),
            "Schritt 6 muss ausdruecklich 'keine Rueckfrage' dokumentieren",
        )
        self.assertIn("ausschliesslich", lowered)

    def test_output_schema_allows_scihub_as_source(self):
        schema = self.body.split("## Output-Schema", 1)[1].split("\n## ", 1)[0]
        self.assertIn("scihub-fetcher", schema)


class TestScihubFetcherDropsRepeatedDisclaimer(unittest.TestCase):
    """agents/scihub-fetcher.md: kein Wiederholungshinweis pro Fund mehr (AC1)."""

    def setUp(self):
        self.body = SCIHUB_AGENT.read_text(encoding="utf-8")

    def test_no_longer_mandates_output_disclaimer_per_success(self):
        self.assertNotIn(
            "IMMER diesen Hinweis ausgeben",
            self.body,
            "Der pro-Fund-Wiederholungshinweis muss entfallen (Issue #459)",
        )

    def test_still_tags_provenance_on_success(self):
        self.assertIn("provenance:scihub", self.body)

    def test_documents_one_time_clarification_at_optin(self):
        lowered = self.body.lower()
        self.assertTrue(
            "einmalig" in lowered and "opt-in" in lowered,
            "Der Prompt muss klarstellen, dass die Aufklaerung einmalig beim Opt-in erfolgt",
        )


class TestFetchCommandDropsQuelleField(unittest.TestCase):
    """AC3: Beschaffungsweg (`Quelle`) verschwindet aus dem literature_state.md-Block."""

    def setUp(self):
        self.body = FETCH_COMMAND.read_text(encoding="utf-8")

    def test_success_block_has_no_quelle_field(self):
        success_section = self.body.split("#### Bei `success`", 1)[1].split("\n#### ", 1)[0]
        self.assertNotIn("**Quelle:**", success_section)

    def test_user_output_still_shows_source_status_only_not_channel_wording(self):
        """Die reine Konsolen-Ausgabe an den User darf bestehen bleiben -- nur der
        persistente literature_state.md-Block (der von schreibenden Skills gelesen
        werden darf) verliert das Feld."""
        success_section = self.body.split("#### Bei `success`", 1)[1].split("\n#### ", 1)[0]
        # Der literature_state.md-Codeblock (```markdown ... ```) darf 'Quelle' nicht enthalten.
        md_block = success_section.split("```markdown", 1)[1].split("```", 1)[0]
        self.assertNotIn("Quelle", md_block)


class TestWritingSkillsProvenanceBlindness(unittest.TestCase):
    """AC3/AC4: chapter-writer und citation-extraction duerfen Provenance nie verwenden.

    Die Regel steht im gemeinsamen `skills/_common/preamble.md` (nicht inline
    in den einzelnen SKILL.md-Dateien): beide Skills laden dieses Preamble am
    Aktivierungsbeginn und muessen laut eigener Vorgabe "alle dort
    definierten Bloecke" befolgen (siehe Preamble-Ladeaufruf oben in jeder
    SKILL.md) -- das ist ebenso bindend wie ein Inline-Absatz. Inline waere
    hier nicht moeglich: `chapter-writer/SKILL.md` und
    `citation-extraction/SKILL.md` liegen beide < 40 Bytes unter dem in
    #185/#186 etablierten 8-KB-Progressive-Disclosure-Limit
    (`test_skill_md_under_8kb`).
    """

    PREAMBLE = REPO_ROOT / "skills" / "_common" / "preamble.md"

    def test_preamble_has_provenance_blindness_rule(self):
        body = self.PREAMBLE.read_text(encoding="utf-8")
        lowered = body.lower()
        self.assertTrue(
            "beschaffungsweg" in lowered or "provenance" in lowered,
            "skills/_common/preamble.md muss eine Provenance-Blindheits-Regel enthalten",
        )
        self.assertIn("chapter-writer", body)
        self.assertIn("citation-extraction", body)

    def test_chapter_writer_still_loads_preamble(self):
        body = CHAPTER_WRITER_SKILL.read_text(encoding="utf-8")
        self.assertIn("preamble.md", body)

    def test_citation_extraction_still_loads_preamble(self):
        body = CITATION_EXTRACTION_SKILL.read_text(encoding="utf-8")
        self.assertIn("preamble.md", body)

    def test_chapter_writer_skill_md_stays_under_8kb_budget(self):
        self.assertLess(CHAPTER_WRITER_SKILL.stat().st_size, 8 * 1024)

    def test_citation_extraction_skill_md_stays_under_8kb_budget(self):
        self.assertLess(CITATION_EXTRACTION_SKILL.stat().st_size, 8 * 1024)


class TestCitationReferencesDoNotBranchOnProvenance(unittest.TestCase):
    """AC4 (Negativ-Regression): keine Zitationsregel unterscheidet nach Kanal/Provenance."""

    def test_no_reference_file_mentions_scihub_or_provenance(self):
        refs_dir = REPO_ROOT / "skills" / "citation-extraction" / "references"
        offenders = []
        for path in sorted(refs_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8").lower()
            if "scihub" in text or "provenance" in text:
                offenders.append(path.name)
        self.assertEqual(
            offenders, [], f"Zitationsregeln duerfen nicht nach Kanal unterscheiden: {offenders}"
        )


class TestIdenticalCitationAcrossProvenance(unittest.TestCase):
    """AC4: zwei identische Quellen mit unterschiedlichem Kanal -> identisches csl_json."""

    def setUp(self):
        import tempfile

        from academic_vault.db import VaultDB

        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.db = VaultDB(self.db_path)
        self.db.init_schema()

    def tearDown(self):
        import os

        os.unlink(self.db_path)

    def test_same_csl_json_regardless_of_provenance(self):
        csl = json.dumps(
            {
                "type": "article-journal",
                "title": "Identisches Paper",
                "author": [{"family": "Muster", "given": "A."}],
                "issued": {"date-parts": [[2021]]},
            }
        )
        self.db.add_paper(paper_id="via-oa", csl_json=csl, doi="10.1234/dup", provenance="oa")
        self.db.add_paper(
            paper_id="via-scihub", csl_json=csl, doi="10.1234/dup", provenance="scihub"
        )

        oa_paper = self.db.get_paper("via-oa")
        sci_paper = self.db.get_paper("via-scihub")

        self.assertEqual(oa_paper["csl_json"], sci_paper["csl_json"])
        self.assertNotEqual(oa_paper["provenance"], sci_paper["provenance"])


class TestProvenanceStillAnswerableOnDirectQuestion(unittest.TestCase):
    """AC5: direkte Herkunftsfrage bleibt ueber die MCP-Ebene beantwortbar."""

    def setUp(self):
        import tempfile

        from academic_vault import server as vault_server

        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.vault_server = vault_server

    def tearDown(self):
        import os

        os.unlink(self.db_path)

    def test_mcp_get_paper_reports_provenance(self):
        self.vault_server.add_paper(
            self.db_path,
            paper_id="mcp-scihub",
            csl_json=json.dumps({"type": "article-journal", "title": "MCP Test"}),
            provenance="scihub",
        )
        paper = self.vault_server.get_paper(self.db_path, "mcp-scihub")
        self.assertEqual(paper["provenance"], "scihub")

    def test_mcp_list_papers_by_provenance_finds_it(self):
        self.vault_server.add_paper(
            self.db_path,
            paper_id="mcp-scihub-2",
            csl_json=json.dumps({"type": "article-journal", "title": "MCP Test 2"}),
            provenance="scihub",
        )
        rows = self.vault_server.list_papers_by_provenance(self.db_path, "scihub")
        ids = {r["paper_id"] for r in rows}
        self.assertIn("mcp-scihub-2", ids)


if __name__ == "__main__":
    unittest.main()
