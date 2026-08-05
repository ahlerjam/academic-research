"""Baseline-Skript fuer die Trigger-Evals -- Issue #614.

Klassifiziert alle Faelle aus ``evals/*/trigger_evals.json`` real ueber den
``claude``-CLI-OAuth-Pfad (Issue #631, ``eval_runner.call_claude_with_tokens``)
und sammelt je Skill Recall, Falsch-Positiv-Rate (FPR) und die konkreten
Fehlklassifikationen -- kein Duplikat der Klassifikationslogik aus
``tests/evals/test_triggers.py``, sondern Wiederverwendung per Import.

Kein ``ANTHROPIC_API_KEY``-Pfad hier (repo-weit verboten, Issue #632): dieses
Skript nutzt ausschliesslich den OAuth-CLI-Pfad aus ``eval_runner``, der ohne
gesetzten Key automatisch greift, sofern die ``claude``-CLI im PATH liegt.

Aufruf (aus dem Repo-Root, damit ``tests`` und ``scripts`` importierbar sind):

    uv run python -m scripts.dev.run_trigger_baseline --out docs/evals/results.json
    uv run python -m scripts.dev.run_trigger_baseline --skills literature-excel --workers 4  # Kalibrierung

``ClaudeCliError`` (Auth-/Rate-Limit-Fehler) wird je Fall getrennt gezaehlt,
nicht stillschweigend als Fehlklassifikation in Recall/FPR gewertet (Issue
#631 AC5, Plan-Risiko 6 aus dem Issue-614-Plankommentar).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from tests.evals.eval_runner import ClaudeCliError, call_claude_with_tokens, claude_cli_available
from tests.evals.test_triggers import (
    ALL_SKILLS,
    EXTERNAL_COLLISION_CANDIDATES,
    TRIGGER_SYSTEM_TEMPLATE,
    _load_all_descriptions,
    _load_trigger_evals,
)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class CaseResult:
    skill: str
    kind: str  # "should_trigger" | "should_not_trigger"
    prompt: str
    classification: str | None
    error: str | None
    tokens_in: int
    tokens_out: int


def collect_cases(skills: list[str]) -> list[tuple[str, str, str]]:
    """(skill, kind, prompt)-Tupel fuer alle vorhandenen trigger_evals.json.

    Zaehlt live nach statt eine Konstante zu uebernehmen (Plan-Risiko 2): die
    Fallzahl kann zwischen Planung und Ausfuehrung abweichen.
    """
    cases: list[tuple[str, str, str]] = []
    for skill in skills:
        evals = _load_trigger_evals(skill)
        if not evals:
            continue
        for prompt in evals.get("should_trigger", []):
            cases.append((skill, "should_trigger", prompt))
        for prompt in evals.get("should_not_trigger", []):
            cases.append((skill, "should_not_trigger", prompt))
    return cases


def build_system_prompt(skill: str) -> str:
    extra = EXTERNAL_COLLISION_CANDIDATES.get(skill)
    return TRIGGER_SYSTEM_TEMPLATE.format(descriptions=_load_all_descriptions(extra))


def classify_case(skill: str, kind: str, prompt: str, model: str = DEFAULT_MODEL) -> CaseResult:
    system = build_system_prompt(skill)
    try:
        text, tokens_in, tokens_out = call_claude_with_tokens(
            system=system, user=prompt, model=model
        )
    except ClaudeCliError as exc:
        return CaseResult(skill, kind, prompt, None, str(exc), 0, 0)
    classification = text.strip().lower().split()[0] if text.strip() else "none"
    return CaseResult(skill, kind, prompt, classification, None, tokens_in, tokens_out)


def run_baseline(
    cases: list[tuple[str, str, str]],
    model: str = DEFAULT_MODEL,
    workers: int = 8,
) -> list[CaseResult]:
    results: list[CaseResult] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(classify_case, skill, kind, prompt, model)
            for skill, kind, prompt in cases
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def aggregate(results: list[CaseResult]) -> dict[str, dict]:
    per_skill: dict[str, dict] = {}
    for r in results:
        st = per_skill.setdefault(
            r.skill,
            {
                "should_trigger_total": 0,
                "should_trigger_hits": 0,
                "should_not_trigger_total": 0,
                "should_not_trigger_false_pos": 0,
                "errors": [],
                "misclassified": [],
                "tokens_in": 0,
                "tokens_out": 0,
            },
        )
        if r.error is not None:
            st["errors"].append({"kind": r.kind, "prompt": r.prompt, "error": r.error})
            continue
        st["tokens_in"] += r.tokens_in
        st["tokens_out"] += r.tokens_out
        hit = r.classification == r.skill
        if r.kind == "should_trigger":
            st["should_trigger_total"] += 1
            if hit:
                st["should_trigger_hits"] += 1
            else:
                st["misclassified"].append(
                    {"kind": r.kind, "prompt": r.prompt, "got": r.classification}
                )
        else:
            st["should_not_trigger_total"] += 1
            if hit:
                st["should_not_trigger_false_pos"] += 1
                st["misclassified"].append(
                    {"kind": r.kind, "prompt": r.prompt, "got": r.classification}
                )
    for st in per_skill.values():
        st["recall"] = (
            st["should_trigger_hits"] / st["should_trigger_total"]
            if st["should_trigger_total"]
            else None
        )
        st["fpr"] = (
            st["should_not_trigger_false_pos"] / st["should_not_trigger_total"]
            if st["should_not_trigger_total"]
            else None
        )
    return per_skill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skills", nargs="*", default=None, help="Teilmenge der Skills (Default: alle)"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", required=True, help="Pfad fuer die Rohdaten-JSON")
    args = parser.parse_args(argv)

    if not claude_cli_available():
        print("claude-CLI nicht im PATH gefunden -- kein Lauf moeglich.", file=sys.stderr)
        return 2

    skills = args.skills if args.skills else ALL_SKILLS
    cases = collect_cases(skills)
    if not cases:
        print(
            "Keine trigger_evals.json-Faelle fuer die gewaehlten Skills gefunden.", file=sys.stderr
        )
        return 2

    print(
        f"[run_trigger_baseline] {len(cases)} Faelle, {len(skills)} Skills, "
        f"model={args.model}, workers={args.workers}",
        file=sys.stderr,
    )
    start = time.monotonic()
    results = run_baseline(cases, model=args.model, workers=args.workers)
    wall_seconds = time.monotonic() - start
    per_skill = aggregate(results)

    total_errors = sum(len(st["errors"]) for st in per_skill.values())
    total_tokens_in = sum(st["tokens_in"] for st in per_skill.values())
    total_tokens_out = sum(st["tokens_out"] for st in per_skill.values())

    payload = {
        "model": args.model,
        "call_path": "claude-CLI/OAuth (Issue #631)",
        "total_cases": len(cases),
        "total_errors": total_errors,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "wall_seconds": wall_seconds,
        "workers": args.workers,
        "per_skill": per_skill,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(
        f"[run_trigger_baseline] fertig in {wall_seconds:.1f}s, "
        f"{total_errors} CLI-Fehler, geschrieben nach {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
