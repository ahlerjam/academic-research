"""Evals fuer die restlichen 8 Skills + 2 Agents (minimale Baseline)."""

import json

import pytest

from tests.evals.eval_runner import (
    CONTEXT_FS_DIR,
    EVALS_ROOT,
    call_claude_for_component,
    check_expected,
    load_agent_content,
    load_skill_content,
)

pytestmark = pytest.mark.eval_core_set

REST_SKILLS = [
    "academic-context",
    "research-question-refiner",
    "advisor",
    "methodology-advisor",
    "literature-gap-analysis",
    "style-evaluator",
    "plagiarism-check",
    "title-generator",
    "submission-checker",
]
REST_AGENTS = ["query-generator"]

# Alle REST_SKILLS + REST_AGENTS sind in eval_runner.COMPONENT_PROFILES als
# "context-fs" hinterlegt (Issue #830) -- sie laden das gemeinsame Preamble
# (skills/_common/preamble.md) und setzen ./academic_context.md +
# ./literature_state.md voraus (Issue #823). call_claude_for_component
# liefert allowed_tools="Read" bereits automatisch ueber das Profil; die
# Fixture selbst (cwd=CONTEXT_FS_DIR) kommt als Override von hier, sofern
# der Case nicht explizit "cwd": "none" setzt (Negativfall: Vorbedingung
# bewusst ohne Kontextdateien pruefen).


def _collect_prompts() -> list[tuple[str, dict]]:
    items: list[tuple[str, dict]] = []
    for c in REST_SKILLS + REST_AGENTS:
        path = EVALS_ROOT / c / "evals.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for p in data.get("prompts", []):
            items.append((c, p))
    return items


PROMPTS = _collect_prompts()


@pytest.mark.parametrize(
    "component,prompt",
    PROMPTS,
    ids=[f"{c}-{p['id']}" for c, p in PROMPTS],
)
@pytest.mark.parametrize("mode", ["with_skill", "without_skill"])
def test_rest_eval(component, prompt, mode):
    if prompt["mode"] not in ("both", mode):
        pytest.skip(f"{component}/{prompt['id']} nicht fuer Mode {mode}")
    if component in REST_SKILLS:
        system = load_skill_content(component) if mode == "with_skill" else ""
    else:
        system = load_agent_content(component) if mode == "with_skill" else ""
    cwd = CONTEXT_FS_DIR if prompt.get("cwd") != "none" else None
    output = call_claude_for_component(component, system=system, user=prompt["input"], cwd=cwd)
    assert check_expected(output, prompt["expected"]), (
        f"[{component}/{mode}] {prompt['id']}: expected={prompt['expected']} actual={output[:200]}"
    )
