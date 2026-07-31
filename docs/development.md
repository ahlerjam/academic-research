# Entwicklung, Tests und Evals

[← Doku-Übersicht](README.md)

Für Beitragende. Endnutzer brauchen diese Seite nicht — der Nutzerweg läuft über
`scripts/setup.sh` und pip, nicht über `uv`.

## Tests ausführen

```bash
uv sync --extra dev            # einmalig je Arbeitskopie
uv run pytest tests/
```

Die Kern-Suite ist **offline-hermetisch** und läuft ohne Netzwerk. Übersprungen werden nur
Tests mit externen Abhängigkeiten: die API-basierten Evals unter `tests/evals/` brauchen
einen `ANTHROPIC_API_KEY`, einige Integrations-Tests werden ohne optionale Pakete (z. B.
`requests`, `sqlite-vec`) automatisch geskippt. Die Gründe stehen in
[SKIP_REASONS.md](SKIP_REASONS.md).

**Wie viele Tests?** Die Zahl ändert sich mit fast jedem PR, und sie hängt von Plattform
und installierten Optionalpaketen ab. Deshalb steht sie weder in einem Badge noch als
Festwert in der Doku. Maßgeblich für deine Umgebung ist:

```bash
uv run pytest --collect-only -q | tail -1
```

Als Anhaltspunkt: der Lauf vom 2026-07-27 (macOS 26.5.2/arm64, Python 3.14.4) meldete
1874 bestanden und 148 übersprungen. Auf einer anderen Plattform oder mit anderen
Optionalpaketen sieht die Zahl anders aus — das ist kein Fehler.

Regression-Guards, die Doku und Code gekoppelt halten, liegen u. a. in
`tests/test_skill_naming.py`, `tests/test_cross_references.py` und
`tests/test_skills_manifest.py`. Ändert sich eine Zahl im Repo (Skills, Agents, Commands,
MCP-Tools, Uni-Profile), schlägt `tests/test_issue_402_readme_relaunch.py` fehl, bis die
Doku nachgezogen ist.

## Lint, Format, Typen

```bash
uv run ruff check .           # Linter
uv run ruff format --check .  # Formatter (CI-blockierend)
uv run mypy                   # Typprüfung (Pfade aus pyproject.toml)
bash scripts/dev/check-mjs-syntax.sh   # ESM-Syntax, alle getrackten *.mjs
bash scripts/dev/check-shell-syntax.sh # Shell-Syntax, alle getrackten *.sh
```

Konfiguration zentral in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`).

## pre-commit (empfohlen)

Für lokale Hygiene wird `pre-commit` empfohlen. Die Konfiguration liegt in
[`.pre-commit-config.yaml`](../.pre-commit-config.yaml) und blockt versehentlich
committete große Dateien, neue Submodule und private Schlüssel. OS-Artefakte wie
`.DS_Store` schließt bereits die `.gitignore` aus.

```bash
# Einmalig einrichten
pip install pre-commit
pre-commit install            # installiert den Git-Hook

# Manuell über alle Dateien laufen lassen
pre-commit run --all-files
```

Die Hooks umfassen `ruff` (Lint + Format), `mypy`, `end-of-file-fixer`, `check-yaml` und
`check-json`. Reproduzierbare Installs liefert der gepinnte `uv.lock`
(`uv sync --extra dev`).

## Mitwirken (CONTRIBUTING)

- Konventionen, Verzeichnisgrenzen und rote Linien stehen in
  [AGENTS.md](../AGENTS.md) — das ist die maßgebliche Datei, auch für menschliche
  Beitragende.
- Fast jeder Commit referenziert eine Issue-Nummer; Typ-Präfixe: `fix:`, `chore:`, `ci:`,
  `deps:`, `test:`, `docs:`, `feat:`.
- Frontmatter-`description` ist Pflicht in allen Skills, Agents und Commands
  (CI-erzwungen).
- Jeder nicht-Draft-PR durchläuft die Review-Pipeline
  `.github/workflows/pr-deep-review.yml`; der `coordinator`-Job ist das Merge-Gate.

## Versionierte `.claude/`-Dateien

`.claude/` ist normalerweise ein lokaler Ordner. In diesem Repository sind sechs Dateien
davon bewusst **versioniert** (Issue #343) — sie gehören zur Infrastruktur, nicht zur
Arbeitsumgebung einer einzelnen Person. Die Mechanik dahinter steht in der `.gitignore`:
`.claude/*` ist ausgeschlossen, und genau diese Einträge sind per `!`-Ausnahme wieder
zugelassen.

| Versionierte Datei | Rolle |
|--------------------|-------|
| `.claude/settings.json` | Verdrahtet die Hooks unten an `SessionStart`/`PreToolUse`/`PostToolUse`, aktiviert die Plugins (u. a. flowkit) und trägt die Permission-Allowlist. |
| `.claude/hooks/pretooluse-blocker.sh` | Einzige Quelle der Wahrheit für das Gefahrenmuster-Regex der roten Linien (Force-Push auf `main`, `--no-verify`, `gh api`-Mutationen, `gh --admin`). |
| `.claude/hooks/inject-context.sh` | `SessionStart`-Hook: meldet Branch und Arbeitsstand, warnt bei veralteten flowkit-Templates. Rein informativ, fail-open. |
| `.claude/hooks/pushci-guard.sh` | Erinnert an den konfigurierten CI-Push-Alias. Reiner Komfort, fail-open. |
| `.claude/workflow.config.json` | flowkit-Konfiguration: `areas` und `protectedAreas` (siehe [AGENTS.md](../AGENTS.md)). |
| `.claude/flowkit-version` | Stempel der zuletzt installierten flowkit-Template-Version; Vergleichsbasis für die Drift-Warnung in `inject-context.sh`. |

**Was bricht, wenn eine dieser Dateien verschwindet:**

- **CI wird rot.** Der Job `flowkit-hook-harness` in `.github/workflows/ci.yml` ruft
  `scripts/dev/test-pretooluse-blocker.sh` auf, und dieses Harness testet die
  *deployte* Datei `.claude/hooks/pretooluse-blocker.sh` — nicht eine Vorlage. Fehlt
  sie, schlägt der Job fehl.
- **Die lokale Sitzung blockiert.** `.claude/settings.json` startet den Blocker so, dass
  ein fehlendes oder nicht ausführbares Skript jeden `Bash`-Aufruf **vorsorglich
  ablehnt** — bewusst so gebaut, damit ein gelöschter Guard nicht stillschweigend zu
  „keine Prüfung" wird.
- **flowkit verliert seine Grenzen.** Ohne `.claude/workflow.config.json` kennt der
  Workflow die geschützten Bereiche nicht mehr, und Änderungen an `vault`, `hooks`,
  `security` oder `ci` laufen ohne die dafür vorgesehene Sonderbehandlung.

Alles andere unter `.claude/` (`settings.local.json`, `worktrees/`, eigene `agents/`)
bleibt lokal und gehört nicht ins Repository.

## Evals

`evals/` und `tests/evals/` sind **keine** normale pytest-Suite, sondern
LLM-Verhaltens-Evals. Sie kosten API-Budget und laufen nicht in CI.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run pytest tests/evals/ -v
```

- **Quality-Evals:** `with_skill` vs. `without_skill`, Schwelle Δ ≥ 20 pp PASS-Rate
  (erzwungen via `eval_runner.check_quality_delta`, konfigurierbar über
  `EVAL_DELTA_THRESHOLD`, Default `0.20`).
- **Trigger-Evals:** Recall ≥ 85 %, FPR ≤ 10 % je Skill.

Kein CI-Trigger — Evals laufen lokal vor jedem Release. Reports unter `docs/evals/`.

**Was ohne API-Key wirklich läuft.** `uv run pytest tests/evals/` ergibt ohne
`ANTHROPIC_API_KEY` **188 bestandene und 152 übersprungene** Tests. Die Skips
kommen ganz überwiegend aus `require_api_key()` in
`tests/evals/eval_runner.py` und bedeuten: hier wird derzeit keine
LLM-Qualität gemessen. Von den
40 Komponenten unter `evals/` haben genau **3** einen Runner, der offline
Inhalt bewertet (`verbatim-guard`, `humanizer-de-pipeline`, `auto-download`);
die übrigen 37 werden nur strukturell geprüft. Welche Komponente in welchem
Zustand ist und warum, steht vollständig in
[`docs/evals/STRATEGY.md`](evals/STRATEGY.md) — inklusive der Bezifferung
des API-Budgets, das nötig wäre, um daraus echte Metriken zu machen. Der Guard
`tests/evals/test_eval_strategy.py` hält Tabelle und Dateisystem synchron.
