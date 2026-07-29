# Issue #389 / PR #415 — AC3+AC4 Live-Verifikationsbeleg (Stand 2026-07-27)

> **Historisches Dokument.** Verifikationsbeleg vom 2026-07-27, kein aktueller
> Sollzustand. Massgeblich fuer den aktuellen AC3/AC4-Stand sind PR #415 und
> CHANGELOG.md.

[← Doku-Übersicht](../README.md)

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

---

## AC4 — Nachtrag Fix-Runde 2 (2026-07-27): Exit-Code allein ist untauglich

### Befund der Runde-2-Verifikation

Die erste Fassung des Guards prüfte ausschließlich den Exit-Code
(`VULTURE_EXIT ∉ {0, 3}` ⇒ Fehlschlag). Die Verifikation wies das als
**verfehlt** zurück: im realen `deadCodePaths`-Scope greift diese Prüfung nie.

### Root-Cause (verifiziert an vulture 2.16, nicht vermutet)

`vulture/core.py::report()` setzt für **jeden** gemeldeten Fund
bedingungslos `self.exit_code = ExitCode.DeadCode` (3):

```python
for item in self.get_unused_code(...):
    self._log(...)
    self.exit_code = ExitCode.DeadCode  # core.py:364
return self.exit_code
```

Damit überschreibt `report()` ein zuvor in `scan()`/`scavenge()` gesetztes
`ExitCode.InvalidInput` (1) — **unabhängig davon, in welcher Datei** der
Eingabefehler auftrat. `main()` ruft `scavenge()` und danach `report()` auf,
der Rückgabewert von `report()` ist der Prozess-Exit-Code.

Der reale Scope enthält mit `academic_vault/db.py:147` dauerhaft einen Fund
oberhalb der Schwelle. Der Exit-Code ist dadurch faktisch auf 3 festgenagelt.
Lokal im Worktree reproduziert (identischer Aufruf wie im Workflow):

```
$ uv run vulture scripts/ academic_vault/ --min-confidence 80
academic_vault/db.py:147: unused variable 'exc_tb' (100% confidence)
academic_vault/db.py:147: unused variable 'exc_val' (100% confidence)
# exit 3

$ printf 'def broken(:\n    pass\n' > scripts/dev/_tmp_syntax_probe.py
$ uv run vulture scripts/ academic_vault/ --min-confidence 80
scripts/dev/_tmp_syntax_probe.py:1: invalid syntax at "def broken(:"   # -> stderr
academic_vault/db.py:147: unused variable 'exc_tb' (100% confidence)   # -> stdout
academic_vault/db.py:147: unused variable 'exc_val' (100% confidence)  # -> stdout
# exit 3   <-- InvalidInput (1) wurde von DeadCode (3) ueberschrieben
```

### Fix

vulture trennt die Kanäle sauber: Funde gehen nach **stdout**, jeder echte
Eingabefehler nach **stderr**. In vulture 2.16 gibt es exakt vier
`file=sys.stderr`-Stellen — Syntaxfehler (`core.py:237`), ungültiger
Quelltext/Null-Bytes (`core.py:252`), nicht lesbare Datei (`core.py:292`) und
Config-`InputError` (`core.py:668`). Alle vier sind Fehlerpfade; im Normalbetrieb
bleibt stderr leer.

Der Guard fängt stderr deshalb **getrennt** auf (`2> "$RUNNER_TEMP/vulture_stderr.txt"`
statt `2>&1`) und wertet zwei unabhängige Signale aus:

1. Exit-Code ∉ {0, 3} — fängt u. a. `InvalidCmdlineArguments` (2), das vor
   `report()` per `sys.exit()` greift und deshalb nicht maskiert wird.
2. stderr nicht leer — fängt die von `report()` maskierten Eingabefehler.

Zusätzlich nötig: `uv run --quiet`. Ein **kaltes** `uv run` schreibt
Fortschrittsmeldungen nach stderr und würde Signal 2 sonst bei jedem PR
fälschlich auslösen. Empirisch geprüft gegen ein leeres `UV_PROJECT_ENVIRONMENT`:

```
$ UV_PROJECT_ENVIRONMENT=/tmp/cold uv run --extra dev vulture --version
Using CPython 3.12.13                      # -> stderr
Creating virtual environment at: /tmp/cold # -> stderr
Installed 92 packages in 788ms             # -> stderr

$ UV_PROJECT_ENVIRONMENT=/tmp/cold2 uv run --quiet --extra dev vulture --version
# stderr: 0 Bytes
```

`--quiet` (einfach, **nicht** `-qq`) unterdrückt laut uv-CLI-Referenz nur die
Informationsausgabe; echte uv-Fehler bleiben sichtbar — verifiziert:
`uv run --quiet does-not-exist-cmd` → `error: Failed to spawn: …` auf stderr,
Exit 2 (von Signal 1 gefangen).

Nebeneffekt des Kanal-Splits: `vulture.txt` speist den `dead-code`-Reviewer und
wird nach `pfad:zeile:`-Präfix gefiltert. Fehlermeldungen haben dasselbe Präfix
und wären dem Reviewer vorher als echte Funde untergeschoben worden; jetzt
enthält die Datei nur noch Funde.

### Live-Beleg des Fixes (realer Scope, extrahierter Workflow-Block)

Der vulture-Teil wurde wörtlich aus `pr-deep-review.yml` extrahiert und mit
`DEAD_PATHS="scripts/ academic_vault/"` ausgeführt:

```
===== A) realer Scope, sauber =====
GUARD_EXIT=0                                # kein False Positive trotz vulture-Exit 3

===== B) realer Scope + injizierter Syntaxfehler =====
::error::vulture konnte Eingaben nicht auswerten (Exit-Code 3 wurde durch regulaere Dead-Code-Funde maskiert):
academic_vault/_tmp_probe.py:1: invalid syntax at "def broken(:"
GUARD_EXIT=1                                # sichtbarer Fehlschlag trotz maskiertem Exit-Code

===== C) Reviewer-Input (vulture.txt) nach B =====
academic_vault/db.py:147: unused variable 'exc_tb' (100% confidence)
academic_vault/db.py:147: unused variable 'exc_val' (100% confidence)
# keine Kontamination durch die stderr-Meldung
```

### Warum der Defekt vorher durchrutschte — und was das jetzt verhindert

Die Runde-1-Tests prüften nur den **YAML-Text** (Regex auf `::error::`,
`exit 1`, `$?`). Ein Guard, der nie auslöst, besteht solche Tests problemlos.

Die drei neuen Tests in
`tests/test_issue_389_vulture_dead_code_dependency.py` schneiden den Block
stattdessen wörtlich aus dem Workflow und **führen ihn aus** — gegen einen
Fixture-Baum, der die reale Situation nachstellt (vorbestehender 100%-Fund
plus nicht parsebare Datei). `uv` wird dabei durch einen Shim auf dem PATH
ersetzt, der das stderr-Rauschen eines kalten `uv run` reproduziert; die
`uv run`-Zeile selbst bleibt unverändert Prüfgegenstand.

Mutationstest gegen den gefixten Stand (jede Mutation wird gefangen):

| Mutation am Workflow | fehlschlagender Test |
|---|---|
| `--quiet` entfernt | `test_vulture_guard_stays_green_on_regular_dead_code_finding` |
| `2>&1` statt getrenntem stderr | `test_vulture_guard_fails_when_input_error_is_masked_by_dead_code_exit_code` + `test_vulture_findings_file_is_not_contaminated_by_error_output` |
| stderr-Guard-Block entfernt | `test_vulture_guard_fails_when_input_error_is_masked_by_dead_code_exit_code` |
