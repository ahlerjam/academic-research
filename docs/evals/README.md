# Evals-Reports

[← Doku-Übersicht](../README.md)

Dieses Verzeichnis enthaelt die Eval-Reports der Release-Kandidaten. Die Reports sind
**Momentaufnahmen** eines einzelnen Laufs und altern; der Sollzustand steht in der
Eval-Strategie. Wer wissen will, was heute gemessen wird, liest zuerst die Strategie und
danach höchstens den passenden Report.

> **Zuerst lesen:** [`STRATEGY.md`](STRATEGY.md) legt fuer jede Komponente unter
> `evals/` offen, ob sie real gemessen (`metric`), nur strukturell geprueft
> (`structural`) oder entfernt (`removed`) ist — plus die Bezifferung des
> API-Budgets, das echte Laeufe kosten wuerden. Die Strategie ist der Sollzustand
> und wird von `tests/evals/test_eval_strategy.py` erzwungen.

## Inhalt dieses Verzeichnisses

| Datei | Was drinsteht |
|-------|---------------|
| [`STRATEGY.md`](STRATEGY.md) | Sollzustand: Status je Eval-Komponente, Budgetbedarf (aktuell) |
| [`TEMPLATE.md`](TEMPLATE.md) | Leere Vorlage fuer einen neuen Report |
| [`2026-04-23-summary.md`](2026-04-23-summary.md) | Momentaufnahme: Eval-Infrastruktur zu v5.2.0 |
| [`recall-at-k-model-ab-375.md`](recall-at-k-model-ab-375.md) | Momentaufnahme: Recall@10-Goldset + Embedding-Modell-A/B (#375) |
| [`v6.2-tier-eval.md`](v6.2-tier-eval.md) | Momentaufnahme: Auto-Download-Tier-Pipeline v6.2 |

## Konvention

- `<datum>-<component>.md` — Report fuer eine einzelne Komponente, geschrieben vor einem Release
- `TEMPLATE.md` — leeres Report-Template zum Kopieren

## Ausfuehrung

```
export ANTHROPIC_API_KEY=sk-ant-...
pytest tests/evals/ -v
```

Reports entstehen manuell auf Basis der pytest-Ausgabe. Kein automatischer
Report-Generator (YAGNI — Reports werden nur ein paar Mal pro Release geschrieben).
