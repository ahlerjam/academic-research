# academic-research — Claude Code Project Config

> Harness-neutraler Einstieg (Commands, Verzeichnisgrenzen, Konventionen): @AGENTS.md

Antworte auf Deutsch (volle Orthografie). Code-Identifier und Commit-Messages Englisch.
Vor „fertig": `pytest tests/ --ignore=tests/evals` + `ruff check .` real ausführen —
Evidence before assertions (vgl. Epic #243). `--ignore=tests/evals` ist Pflicht: die
Eval-Suiten rufen lokal die echte claude-CLI auf (`tests/evals/eval_runner.py`,
`call_claude`), skippen also nur dort, wo weder CLI noch API-Key vorhanden sind — in CI.
Die Evals laufen separat über `.github/workflows/eval-behavior.yml`.
