# Entwicklung, Tests und Evals

[← zurück zur README](../README.md)

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
node --check hooks/*.mjs      # Hook-Syntax
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
