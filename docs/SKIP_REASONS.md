# Skip-Reasons

[← Doku-Übersicht](README.md)

Strukturierte Übersicht aller bewussten Test-Skips in `tests/`. Sie macht beim
Review eindeutig, ob ein Skip **permanent** (umweltabhängig, nie auf jeder
Maschine lauffähig) oder **todo** (temporär, bis ein Feature/Asset existiert) ist.

Pflege-Regel: Wer einen neuen `@pytest.mark.skip(if)` oder `pytest.skip(...)`
einführt, ergänzt hier eine Zeile. `permanent` = Skip ist erwartet und bleibt
(z.B. fehlende optionale Dependency, kein API-Key in CI). `todo:<datum|issue>` =
Skip soll wegfallen, sobald das genannte Artefakt vorhanden ist.

## Klassifikation

| Test / Datei | Skip-Grund | Reason-Text | Klasse |
| --- | --- | --- | --- |
| `tests/evals/eval_runner.py` | Kein `ANTHROPIC_API_KEY` in CI | `ANTHROPIC_API_KEY nicht gesetzt - Eval uebersprungen` | permanent (im regulären `pytest tests/`-Lauf; der separate `eval-behavior.yml`-Workflow, Issue #470, setzt den Key und führt real aus) |
| `tests/evals/eval_runner.py` | `anthropic`-Package fehlt | `anthropic-Package nicht installiert` | permanent (defensiver Fallback; `anthropic>=0.40` ist seit #390 Pflicht-Dependency in `pyproject.toml`, dieser Zweig greift nur bei kaputter Installation) |
| `tests/evals/test_triggers.py` | Keine `trigger_evals.json` für Skill | `Keine trigger_evals.json fuer <skill>` | permanent |
| `tests/evals/test_*_evals.py` | Prompt nicht für aktiven Mode | `Prompt <id> nicht fuer Mode <mode>` | permanent |
| `tests/test_project_bootstrap.py` | `git` nicht im PATH (CI-Umgebung) | `git not in PATH` | permanent |

## Regenerieren

Liste der aktuellen Skip-Stellen:

```bash
grep -rn "@pytest.mark.skip\|pytest.skip(" tests/ --include="*.py"
```

Neue Zeilen oben einsortieren und mit `permanent` bzw. `todo:<…>` klassifizieren.

## Wie skippe ich Tests oder Hooks bewusst?

**Einzelne Tests überspringen (im Test-Code):**

```python
import pytest


@pytest.mark.skip(reason="permanent: optionale Dependency fehlt")
def test_optional(): ...


@pytest.mark.skipif(not _FEATURE, reason="todo:#123 — Feature noch nicht da")
def test_feature(): ...
```

**Beim lokalen Lauf gezielt auslassen** (ohne Code-Änderung):

```bash
pytest -k "not slow"            # nach Namensmuster filtern
pytest --deselect tests/x.py::test_y
```

**Pre-Commit-/Git-Hooks überspringen** — nur in Notfällen und nie auf `main`:

```bash
git commit --no-verify         # überspringt die lokalen Git-Hooks
```

`--no-verify` ist die Ausnahme, nicht die Regel: Es umgeht die lokalen Checks,
ersetzt aber nicht die CI-Gates. Jeder so umgangene Check läuft trotzdem in
GitHub Actions (`.github/workflows/ci.yml`) — die CI ist die maßgebliche Quelle.
