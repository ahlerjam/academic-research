# Evals-Reports

Dieses Verzeichnis enthaelt die Eval-Reports der Release-Kandidaten.

> **Zuerst lesen:** [`STRATEGY.md`](STRATEGY.md) legt fuer jede der 37
> Komponenten unter `evals/` offen, ob sie real gemessen (`metric`), nur
> strukturell geprueft (`structural`) oder entfernt (`removed`) ist — plus die
> Bezifferung des API-Budgets, das echte Laeufe kosten wuerden. Die Reports in
> diesem Verzeichnis sind Momentaufnahmen; die Strategie ist der Sollzustand
> und wird von `tests/evals/test_eval_strategy.py` erzwungen.

## Konvention

- `2026-04-23-<component>.md` — Report fuer eine einzelne Komponente, generiert vor Release v5.2.0
- `TEMPLATE.md` — Leeres Report-Template

## Ausfuehrung

```
export ANTHROPIC_API_KEY=sk-ant-...
pytest tests/evals/ -v
```

Reports entstehen manuell auf Basis der pytest-Ausgabe. Kein automatischer Report-Generator (YAGNI — Reports werden nur ein paar Mal pro Release geschrieben).
