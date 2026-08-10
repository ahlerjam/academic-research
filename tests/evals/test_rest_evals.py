"""Evals fuer die restlichen 8 Skills + 2 Agents (minimale Baseline)."""

import json

import pytest

from tests.evals.eval_runner import (
    CONTEXT_FS_DIR,
    EVALS_ROOT,
    call_claude,
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

# Alle REST_SKILLS laden das gemeinsame Preamble (skills/_common/preamble.md)
# und setzen ./academic_context.md + ./literature_state.md voraus (Issue
# #823). Sie bekommen die context-fs-Fixture per cwd= durchgereicht, sofern
# der Case nicht explizit "cwd": "none" setzt (Negativfall: Vorbedingung
# bewusst ohne Kontextdateien pruefen).
CONTEXT_FS_SKILLS = set(REST_SKILLS)


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
    use_context_fs = component in CONTEXT_FS_SKILLS and prompt.get("cwd") != "none"
    cwd = CONTEXT_FS_DIR if use_context_fs else None
    allowed_tools = ["Read"] if use_context_fs else None
    output = call_claude(system=system, user=prompt["input"], cwd=cwd, allowed_tools=allowed_tools)
    assert check_expected(output, prompt["expected"]), (
        f"[{component}/{mode}] {prompt['id']}: expected={prompt['expected']} actual={output[:200]}"
    )
