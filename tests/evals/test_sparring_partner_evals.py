"""Evals fuer sparring-partner-Agent (Issue #454).

Deckt AC2 (substanzielle Schwaeche + konkrete Alternative statt Bestaetigung),
AC3b (Argumentation am konkreten Material aus academic_context.md/Vault) und
AC5 (Widerspruch bei bewusst schwacher Forschungsfrage) inhaltlich ab.
API-gated: ohne ANTHROPIC_API_KEY skippt die gesamte Suite (Muster
tests/evals/test_quality_reviewer_evals.py, kein API-Key/Budget in diesem
Runner-Kontext, vgl. Issue #55).
"""

import json
from pathlib import Path

import pytest

from tests.evals.eval_runner import (
    EVALS_ROOT,
    call_claude,
    check_expected,
    load_agent_content,
)

_EVALS_PATH: Path = EVALS_ROOT / "sparring-partner" / "evals.json"
pytestmark = pytest.mark.skipif(
    not _EVALS_PATH.exists(),
    reason=f"evals-Datei fehlt: {_EVALS_PATH}",
)
EVALS: dict = json.loads(_EVALS_PATH.read_text()) if _EVALS_PATH.exists() else {"prompts": []}


@pytest.mark.parametrize("prompt", EVALS["prompts"], ids=lambda p: p["id"])
def test_sparring_partner_eval(prompt):
    system = load_agent_content("sparring-partner")
    output = call_claude(system=system, user=prompt["input"])
    assert check_expected(output, prompt["expected"]), (
        f"{prompt['id']}: expected={prompt['expected']} actual={output[:300]}"
    )
