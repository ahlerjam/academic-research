"""Evals fuer abstract-generator-Skill."""

import json
from pathlib import Path

import pytest

from tests.evals.eval_runner import (
    CONTEXT_FS_DIR,
    EVALS_ROOT,
    call_claude_for_component,
    check_expected,
    load_skill_content,
)

_EVALS_PATH: Path = EVALS_ROOT / "abstract-generator" / "evals.json"
pytestmark = [
    pytest.mark.skipif(
        not _EVALS_PATH.exists(),
        reason=f"evals-Datei fehlt: {_EVALS_PATH}",
    ),
    pytest.mark.eval_core_set,
]
EVALS: dict = json.loads(_EVALS_PATH.read_text()) if _EVALS_PATH.exists() else {"prompts": []}


@pytest.mark.parametrize("prompt", EVALS["prompts"], ids=lambda p: p["id"])
@pytest.mark.parametrize("mode", ["with_skill", "without_skill"])
def test_abstract_generator_eval(prompt, mode):
    if prompt["mode"] not in ("both", mode):
        pytest.skip(f"Prompt {prompt['id']} nicht fuer Mode {mode}")
    system = load_skill_content("abstract-generator") if mode == "with_skill" else ""
    # abstract-generator laedt das gemeinsame Preamble (Issue #823) und
    # setzt ./academic_context.md + ./writing_state.md voraus. Das
    # "context-fs"-Profil (Issue #830) liefert allowed_tools="Read" und den
    # Root-Leak-Schutz automatisch; die Fixture selbst (cwd=CONTEXT_FS_DIR)
    # kommt als Override von hier, ausser der Case will sie explizit nicht
    # (`"cwd": "none"`).
    cwd = CONTEXT_FS_DIR if prompt.get("cwd") != "none" else None
    output = call_claude_for_component(
        "abstract-generator", system=system, user=prompt["input"], cwd=cwd
    )
    assert check_expected(output, prompt["expected"]), (
        f"[{mode}] {prompt['id']}: expected={prompt['expected']} actual={output[:200]}"
    )
