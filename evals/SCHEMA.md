# Evals-Schema

> Welcher Komponente welcher Mess-Status zugeordnet ist (`metric` /
> `structural` / `removed`), steht in [`docs/evals/STRATEGY.md`](../docs/evals/STRATEGY.md).
> Dieses Dokument beschreibt nur die Dateiformate.

## `evals/<component>/evals.json`

Quality-Evals pro Skill oder Agent, nach Cookbook-Pattern `skill-creator`.

```json
{
  "component": "quote-extractor",
  "component_type": "agent",
  "prompts": [
    {
      "id": "qe-01",
      "input": "Extrahiere aus <pdf_path> zwei Zitate zum Thema 'DevOps Governance'.",
      "expected": {
        "type": "json_field",
        "path": "$.quotes[0].text",
        "check": "non_empty"
      },
      "mode": "both"
    }
  ]
}
```

**Felder:**
- `component`: Name des Skills/Agents (entspricht Verzeichnisname unter `evals/`)
- `component_type`: `"skill"` oder `"agent"`
- `prompts[].id`: Stabile ID (`<component-prefix>-NN`)
- `prompts[].input`: User-Prompt, der Claude geschickt wird
- `prompts[].expected.type`: `"substring"` | `"regex"` | `"json_field"`
- `prompts[].expected.value`: erwarteter Substring oder Regex (bei Typ `substring`/`regex`)
- `prompts[].expected.path`: JSONPath zum geprueften Feld (bei Typ `json_field`)
- `prompts[].expected.check`: `"exists"` | `"non_empty"` | `"equals:<wert>"` (bei Typ `json_field`)
- `prompts[].mode`: `"with_skill"` | `"without_skill"` | `"both"`

## `evals/<component>/trigger_evals.json`

Trigger-Evals pro Skill (Block C).

```json
{
  "component": "research-question-refiner",
  "should_trigger": [
    "Kannst du meine Forschungsfrage schaerfen?",
    "Meine Fragestellung ist zu breit, hilf mir bitte."
  ],
  "should_not_trigger": [
    "Wie richte ich meinen akademischen Kontext ein?",
    "Welche Methodik passt zu meiner Fallstudie?"
  ]
}
```

**Schwellen:**
- Quality-Evals: Baseline-Gap `PASS_rate(with_skill) - PASS_rate(without_skill) >= 20` Prozentpunkte
- Trigger-Evals: `recall_should_trigger >= 0.85`, `false_positive_should_not_trigger <= 0.10`

## Zweites Format: `cases[]` (Nicht-Skill-Komponenten)

Vier Verzeichnisse folgen nicht dem `prompts[]`-Schema oben, sondern einem
`cases[]`-Format. Das ist historisch gewachsen und bewusst **nicht**
normalisiert (ein Umbau wuerde `tests/test_figure_verifier.py`,
`tests/test_oa_fetchers.py` und `tests/test_publisher_fetchers.py` brechen,
ohne die Messqualitaet zu erhoehen — Begruendung in `docs/evals/STRATEGY.md`).

| Verzeichnis | Aufbau | Geprueft von |
|---|---|---|
| `fetch` | Objekt mit `component`/`component_type`/`cases[]` | `tests/test_fetch_command.py` |
| `publisher-fetchers` | Objekt mit `component`/`component_type`/`cases[]` | `tests/test_publisher_fetchers.py` |
| `figure-verifier` | **Top-Level-Array** von Cases, ohne `component`-Feld | `tests/test_figure_verifier.py` |
| `oa-fetchers` | **Top-Level-Array** von Cases, ohne `component`-Feld | `tests/test_oa_fetchers.py` |

```json
{
  "component": "fetch",
  "component_type": "command",
  "cases": [
    {
      "id": "fc-01",
      "description": "ISBN-13-Input wird korrekt als isbn erkannt",
      "type": "input_parsing",
      "input": { "raw": "978-3-16-148410-0" },
      "expected": {
        "type": "json_field",
        "path": "$.identifier_type",
        "check": "equals:isbn"
      }
    }
  ]
}
```

**Felder:**
- `cases[].id`: Stabile ID (`<component-prefix>-NN`)
- `cases[].description`: Was der Case zeigen soll
- `cases[].type`: Freitext-Kategorie (`input_parsing`, `trigger`, …)
- `cases[].input`: Eingabe-Objekt (komponentenspezifisch, kein User-Prompt)
- `cases[].expected`: entweder das `expected`-Objekt aus dem `prompts[]`-Schema
  (`fetch`, `publisher-fetchers`) oder ein flaches Erwartungs-Objekt
  (`figure-verifier`, `oa-fetchers`, z. B. `{"figure_id_non_empty": true}`)
- `cases[].agent` (optional): Ziel-Subagent bei Fetcher-Evals

Alle vier Verzeichnisse sind in `docs/evals/STRATEGY.md` als `structural`
gefuehrt: ihre Cases setzen Live-Downloads, Verlags-Auth oder einen VLM-Aufruf
voraus und sind daher nicht hermetisch ausfuehrbar.

## Offline-Runner (`runner.py`)

Komponenten mit Status `metric` liefern zusaetzlich eine `runner.py`, die eine
importierbare `run_eval_cases() -> dict` exportiert (kein `sys.exit`, kein
`print` im Kernpfad) und von einer pytest-Datei unter `tests/evals/` aufgerufen
wird. Bedingung: kein Netzwerk, kein `ANTHROPIC_API_KEY` — erzwungen durch
`tests/evals/test_eval_strategy.py::test_no_eval_runner_requires_api_key`.

Bestand: `verbatim-guard`, `humanizer-de-pipeline`, `auto-download`.
