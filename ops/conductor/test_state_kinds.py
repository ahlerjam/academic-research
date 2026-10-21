"""Tests of state.py: each unit kind maps to its saved workflow; issue-only kinds never block a build unit."""

from __future__ import annotations

import unittest

import state
from test_state import NOW, live, unit, world

CFG = state.load_config()


class Kinds(unittest.TestCase):
    """The workflow comes from the kind, ar-team only for build units tagged contract-team."""

    def test_every_kind_has_its_workflow(self) -> None:
        expected = {"build": "ar-unit", "spike": "ar-spike", "plan": "ar-plan", "fix": "ar-fix", "rebase": "ar-fix",
                    "judge": "ar-judge", "critic": "ar-critic", "triage": "ar-triage", "proof": "ar-judge"}
        for kind, workflow in expected.items():
            with self.subTest(kind=kind):
                s = state.compute(world([unit(1, kind=kind, labels=[f"kind:{kind}"])]), CFG, NOW)
                self.assertEqual(s["next"][0], {"do": "start-unit", "unit": 1, "kind": kind, "workflow": workflow})

    def test_contract_team_tag(self) -> None:
        s = state.compute(world([unit(1, tags=["contract-team"])]), CFG, NOW)
        self.assertEqual(s["pick"][0]["workflow"], "ar-team")
        s = state.compute(world([unit(1, kind="spike", tags=["contract-team"])]), CFG, NOW)
        self.assertEqual(s["pick"][0]["workflow"], "ar-spike")

    def test_unknown_kind_is_blocked(self) -> None:
        s = state.compute(world([unit(1, labels=["kind:dance"])]), CFG, NOW)
        self.assertEqual(s["ready"], [])
        self.assertEqual(s["blocked"][0]["why"], "unknown kind dance")

    def test_plan_card_without_paths_does_not_block_a_build_unit(self) -> None:
        many = [{"number": 80 + i, "merged_at": "2027-01-14T00:00:00Z", "head": {"ref": f"claude/unit-{40 + i}-x"}}
                for i in range(3)]
        g = world([unit(1, kind="plan", labels=["kind:plan", "state:building"], paths=[]),
                   unit(2, paths=["packages/core/**"])], merged=many, progress=live([1]))
        s = state.compute(g, CFG, NOW)
        self.assertEqual([u["unit"] for u in s["in_flight"]], [1])
        self.assertEqual([u["number"] for u in s["pick"]], [2])
        self.assertEqual(s["deferred_overlap"], [])

    def test_build_unit_without_paths_still_blocks_other_builds(self) -> None:
        many = [{"number": 80 + i, "merged_at": "2027-01-14T00:00:00Z", "head": {"ref": f"claude/unit-{40 + i}-x"}}
                for i in range(3)]
        g = world([unit(1, labels=["state:building"], paths=[]), unit(2, paths=["packages/core/**"])], merged=many,
                  progress=live([1]))
        s = state.compute(g, CFG, NOW)
        self.assertEqual(s["pick"], [])
        self.assertEqual(s["deferred_overlap"], [2])


if __name__ == "__main__":
    unittest.main()
