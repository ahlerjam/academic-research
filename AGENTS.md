# academic-research — Agent Guide

Claude-Code-Plugin für akademisches Arbeiten: 28 Skills, 19 Agents,
9 Slash-Commands, MCP-Server `academic_vault/` (SQLite+FTS5+sqlite-vec).
Details: README.md (lang!), CHANGELOG.md.

## Commands
- Tests: `pytest tests/` (Matrix-CI: Ubuntu+macOS, py3.11-3.13)
- Lint: `ruff check .` und `ruff format --check .` (format ist CI-blockierend;
  check wird blockierend, sobald #340 abgearbeitet ist)
- Types: `mypy` (Konfig in pyproject.toml; blockierend nach #341)
- Hooks-Syntax: `node --check hooks/*.mjs`

## Verzeichnisgrenzen (wichtig)
- `tests/` = klassisches pytest; `evals/` = LLM-Verhaltens-Evals (KEIN normales pytest).
- Vendored / von Lint+Typecheck ausgeschlossen: `skills/xlsx/scripts/office/`,
  Referenzdateien unter `skills/humanizer-de/references/`.
- `docs/superpowers/` = HISTORISCHE Planungsdokumente, nicht aktueller Sollzustand.
- `scripts/bootstrap/CLAUDE.md` ist eine Endnutzer-Vorlage, keine Repo-Anleitung.

## Konventionen
Fast jeder Commit referenziert eine Issue-Nummer; Typen-Präfixe fix:/chore:/ci:/deps:/test:.
Frontmatter-`description` ist Pflicht in allen Skills/Agents/Commands (CI-erzwungen).
