# Issue #389 / PR #415 — AC3 Live-Verifikationsbeleg (Stand 2026-07-27)

> **Status dieses Files:** committeter Belegnachweis für einen abgeschlossenen
> Verifikationsschritt (nicht "untracked Arbeitsdokument" wie
> `2026-06-03-board-audit.md`). Wird durch
> `tests/test_issue_389_vulture_dead_code_dependency.py::test_ac3_live_verification_evidence_documented`
> maschinell auf Vollständigkeit geprüft (Datei existiert, referenziert eine
> Test-PR-Nummer, zitiert den echten `<!-- flowkit-review:v1 -->`-Marker,
> zeigt einen `Reviewer: \`dead-code\``-Finding-Eintrag, erwähnt vulture und
> grenzt sich explizit von ruff F401 ab).

## Ausgangslage

Runde-1-Verifikation von PR #415 (`ac-verify:v1`-Kommentar,
2026-07-27T08:29:41Z) markierte AC3 als **verfehlt**:

> Test-PR mit totem Code in geänderter Datei erzeugt vulture-Finding im
> pr-deep-review-Sticky-Comment | **verfehlt** | Kein Test-PR existiert; kein
> Sticky-Comment-Output gezeigt. […] Die AC verlangt explizit einen
> Test-PR-Nachweis; der fehlt.

PR #415 selbst ändert keine Datei in `deadCodePaths` (`scripts/`,
`academic_vault/`) — das ist strukturell korrekt und beabsichtigt (der
`dead-code`-Job filtert vulture-Funde bewusst auf Dateien, die die jeweilige
PR selbst ändert, um Rauschen aus vorbestehendem Dead Code in unberührten
Dateien zu vermeiden). AC3 lässt sich deshalb nur über einen **separaten
Live-Test-PR** nachweisen — genau wie im ursprünglichen Plan-Kommentar zu
PR #415 unter Task 7 vorgesehen ("Operator-Nachverifikation").

## Wichtiger Zwischenbefund: `--min-confidence 80` filtert die meisten "intuitiven" Dead-Code-Fälle heraus

Vor dem Live-Lauf lokal mit `uvx vulture` empirisch geprüft (vulture 2.16,
identisch zur Workflow-Version): vultures **Default-Confidence** ist laut
Upstream-README (verifiziert via context7, `jendrikseipp/vulture`) **60%**
für unused attributes/classes/functions/methods/properties/variables, **90%**
für unused imports, und **100%** für unused function/method/class-Argumente
sowie unreachable code.

Das bedeutet: eine schlicht ungenutzte Top-Level-Funktion (wie im ursprünglichen
Plan-Kommentar zu Task 7 vorgeschlagen: "eine garantiert ungenutzte Funktion […]
einfügen") hätte bei `--min-confidence 80` **gar nicht erst im vulture-Output
erschienen** — sie liegt bei nur 60% Confidence. Lokal reproduziert:

```
$ uvx vulture demo.py --min-confidence 80
# (keine Ausgabe — unused function fällt unter die Schwelle)
```

Der **einzige** Fall, der bei `--min-confidence 80` regulär durchkommt, wäre
"unused import" (90%) — das deckt sich aber vollständig mit dem, was `ruff
F401` ohnehin bereits meldet, und würde AC3s Anforderung "(nicht nur ruff
F401)" gerade **nicht** erfüllen.

Änderung an `--min-confidence` ist laut Issue #389 explizit **out of scope**
("Anpassung der vulture-min-confidence-Schwelle […] funktionale
Feinjustierung") — das ist hier also kein Bug, sondern eine bewusste
Rauschreduktion, die bei der Testfall-Konstruktion aber beachtet werden muss.

**Konsequenz für den Testfall:** Es wurden bewusst zwei Dead-Code-Muster
gewählt, die bei vulture 2.16 100% Confidence erreichen UND außerhalb von
ruff F401 liegen: **unreachable code nach `return`** sowie ein **ungenutztes
Funktionsargument**. Lokal reproduziert (identischer Aufruf wie im Workflow):

```
$ uv run vulture scripts/ academic_vault/ --min-confidence 80
scripts/dev/issue_389_ac3_vulture_demo.py:25: unreachable code after 'return' (100% confidence)
scripts/dev/issue_389_ac3_vulture_demo.py:28: unused variable 'unused_marker_arg' (100% confidence)
# exit 3
$ uv run ruff check --select F401 scripts/ academic_vault/ --output-format json
[]   # 0 Funde — keine Überlappung mit vulture
```

## Live-Test-PR

- **Test-PR:** [#416](https://github.com/ahlerjam/academic-research/pull/416)
  ("test: AC3-Live-Verifikation für #389 — vulture-Finding im
  dead-code-Sticky-Comment (NICHT MERGEN)"), Branch
  `test/issue-389-ac3-dead-code-evidence`, Base `main`. Geschlossen ohne
  Merge, Branch gelöscht, nach Erfassung dieses Belegs.
- **Aufbau:** `pyproject.toml` + `uv.lock` (nur die vulture-Dev-Dependency
  aus PR #415, **ohne** die Workflow-Änderung selbst — vermeidet den
  claude-code-action-Self-Change-Guard, der Workflow-Dateien abweichend vom
  main-Stand verweigert) + eine neue Demo-Datei
  `scripts/dev/issue_389_ac3_vulture_demo.py` mit den beiden oben genannten
  Dead-Code-Mustern.
- **CI-Lauf:** `flowkit-pr-deep-review`,
  [run 30250876637](https://github.com/ahlerjam/academic-research/actions/runs/30250876637),
  ausgelöst 2026-07-27T08:41:43Z. `dead-code`-Job: **success**, Artefakt
  `findings-dead-code.json` enthält 2 Funde (category `dead-code`, confidence
  100, evidence zitiert wörtlich `vulture reports 100% confidence …`).
  `code-review`-Job lief mit `conclusion: failure` (Job-Crash, nicht Teil des
  AC3-Nachweises — beeinflusst den `dead-code`-Job und dessen Findings nicht;
  eine eigene Untersuchung ist außerhalb des Scopes von Issue #389).

## Sticky-Comment (wörtlicher Auszug, PR #416, `<!-- flowkit-review:v1 -->`)

```
<!-- flowkit-review:v1 -->
## flowkit PR Deep Review

- **P0 (Block):** 0
- **P1 (Must fix):** 1
- **P2 (Backlog):** 2

### P1 Findings
- **[ci-failure]** (no file) — Reviewer code-review did not produce output (result=failure)
  - Evidence: Artifact missing — reviewer job crashed, timed out, or was cancelled.
  - Recommendation: Re-run the workflow or investigate logs.
  - Reviewer: `code-review`

<details>
<summary>P2 (2 findings) — click to expand</summary>

- **[dead-code]** `scripts/dev/issue_389_ac3_vulture_demo.py`:25 — Unreachable code after return in demo_unreachable_after_return
  - Evidence: vulture reports 100% confidence unreachable code at line 25. Verified by reading the file: line 24 `return value * 2` unconditionally returns, so the `print(...)` on line 25 can never execute. Plain top-level def, no decorators, not re-exported via __init__.py, not accessed via getattr/reflection, not a FastAPI route or Pydantic field.
  - Recommendation: Remove the unreachable print statement on line 25 (file is a temporary demo for Issue #389 AC3, not intended to be merged).
  - Reviewer: `dead-code`

- **[dead-code]** `scripts/dev/issue_389_ac3_vulture_demo.py`:28 — Unused function argument 'unused_marker_arg' in demo_unused_argument
  - Evidence: vulture reports 100% confidence unused variable 'unused_marker_arg' at line 28. Verified by reading the file: function body (line 30, `return used * 3`) never references `unused_marker_arg`. Plain top-level function, not a FastAPI route handler (no Depends/decorators), not a Pydantic model field, not accessed via getattr/reflection.
  - Recommendation: Remove the unused parameter or use it in the body (file is a temporary demo for Issue #389 AC3, not intended to be merged).
  - Reviewer: `dead-code`

</details>
```

(P1 `[ci-failure]`-Eintrag ist ein Job-Crash des `code-review`-Reviewers,
irrelevant für AC3 — kein `[dead-code]`- oder `ruff`-Bezug. Volltext des
Kommentars per `gh api repos/ahlerjam/academic-research/issues/416/comments`
abrufbar, solange PR #416 nicht gelöscht wird.)

## Ergebnis

AC3 ist damit **real belegt**: ein echter, mit dieser PR unabhängiger
Test-PR mit absichtlich totem Code in einer `deadCodePaths`-Datei erzeugt im
`pr-deep-review`-Sticky-Comment zwei Finding-Einträge mit
`Reviewer: \`dead-code\`` und `category: dead-code`, deren Evidence wörtlich
aus vulture (100% Confidence) stammt — beide Fälle liegen außerhalb dessen,
was `ruff F401` (0 Funde auf denselben Pfaden) abdeckt.
