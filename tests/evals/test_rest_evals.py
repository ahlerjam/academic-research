"""Quality-Evals fuer die Skills/Agents ohne eigene Eval-Suite (minimale Baseline).

Der Bestand steht in ``REST_SKILLS``/``REST_AGENTS``; alle Faelle brauchen
``ANTHROPIC_API_KEY`` und skippen sonst (siehe ``docs/evals/STRATEGY.md``).
"""

import json

import pytest

from tests.evals.eval_runner import (
    EVALS_ROOT,
    call_claude,
    check_expected,
    load_agent_content,
    load_skill_content,
)

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
    # #471: Die Quality-Prompts von topic-brainstorm (inkl. der Fach-Kontrast-
    # Prompts tb-04/tb-05) wurden bis dahin von keinem Runner eingesammelt —
    # `test_triggers.py` liest nur trigger_evals.json. Damit liefen sie auch mit
    # ANTHROPIC_API_KEY nie. Guard: tests/test_topic_brainstorm.py::
    # TestEvalContrastPromptsAreWired.
    "topic-brainstorm",
]
REST_AGENTS = ["query-generator"]


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
    output = call_claude(system=system, user=prompt["input"])
    assert check_expected(output, prompt["expected"]), (
        f"[{component}/{mode}] {prompt['id']}: expected={prompt['expected']} actual={output[:200]}"
    )
