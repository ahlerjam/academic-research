---
name: hardening
description: Use when a review, an incident or a failed run produced findings and the operator wants this class of error to never happen again - turning findings into gates (formatter, linter, types, boundaries, ast-grep house rules, gate.py modules, drift checks, tests, AGENTS.md lines, ADRs) and deciding which layer catches each finding.
---

# Hardening: findings become gates

A finding is done when the same error turns red before the merge next time, or when it is shown
that no tool can see it. The fix closes the case, the gate closes the class. A gate that an agent
satisfies with one cosmetic line is not a gate.

## Layers, cheapest first

Always pick the lowest layer that catches the finding; first check whether it already does.

| Layer | Catches | Where | Already there? |
| --- | --- | --- | --- |
| Formatter | style, diff noise | component tool config | `make fix` |
| Linter | syntax pattern with a ready rule | ruff, ESLint, ktlint, sqlfluff, Stylelint config | rule list of the tool |
| Types | types, Any, dead names | pyright strict, tsc strict, Kotlin warnings as errors | `make typecheck` |
| Boundaries | forbidden imports | import-linter, eslint-plugin-boundaries, ArchUnit, `feature_imports` | contract list |
| House rule | structure without a ready rule | `gates/rules/<lang>/<ID>.yml` (ast-grep) plus test and fixture | `ast-grep scan --filter <ID>` |
| gate.py module | budgets, layout, test duties, migrations, ADRs | `gates/lib/` | `make check-repo` |
| Drift | two sources that must agree | `gates/lib/drift.py` | `make lint` |
| Core test | a domain decision | the component's core tests | test names |
| Adapter test | translation of a foreign answer | port double or mock transport | test names |
| Behaviour test | a feature end to end | behaviour test per feature | `make test` |
| AGENTS.md line | binds only in review | operator only | `(review)` count |
| ADR | a choice between two ways, never a rule | `decisions/` | `make adr-find` |

## Steps

1. Classify every finding (style, structure, drift, domain, infrastructure, process) and ask which
   file would have shown it before the merge.
2. Pick the layer and write the sentence "lowest layer because ...".
3. Goodhart probe: how does an agent turn the gate green without fixing the error (comment,
   rename, default value, allowlist, suppression, a new file outside the role paths)? If that works,
   rebuild the gate until only the real change makes it green.
4. Red consequence: does the new gate turn main red at once? Ask the operator before building it;
   never ship it as a warning. Red or nothing.
5. Ownership: `gates/`, `.claude/`, `.github/`, `Makefile`, `mk/`, AGENTS.md and tool configs are
   operator only. Deliver a patch in the report, never write them, never work around them.
6. Build: catalog entry in `gates/catalog.json` (id, role, carrier, fixture, why, fix, example),
   rule plus rule test, a `bad` fixture that must report exactly this id and a `good` twin. Watch
   `make gates-selftest` turn red on the fixture before the rule exists, then green.
7. Report one line per finding: layer, file, Goodhart answer, red consequence; name every finding
   that cannot be gated and why.

## Excuses seen in practice

| Excuse | Reality |
| --- | --- |
| "The hook can check this directly" | The hook only wires. A rule in a hook has no test and exists twice. |
| "Start as a warning, make it strict later" | Later never comes. Red or nothing, the operator decides. |
| "Values with a default are optional, skip them" | The default hid the error. The check knows no defaults. |
| "I will add the line to AGENTS.md quickly" | Operator only. Deliver the text, do not write it. |
| "A separate check script is cleaner" | One catalog, one gate.py, so hook, CI and selftest find every rule. |
