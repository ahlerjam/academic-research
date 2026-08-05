# abstract-generator — Offline-Qualitaetsmetrik (Issue #606)

**Status in `docs/evals/STRATEGY.md`: `metric`.**

## Was hier gemessen wird

Die **Treue eines Abstracts gegen den Quelltext**, nicht die Form der Ausgabe.
`runner.py` rechnet die Qualitaetspruefungen nach, die
`skills/abstract-generator/SKILL.md` selbst auffuehrt:

| Pruefpfad | Regel | Herkunft |
| --- | --- | --- |
| `word_count` | 150–250 Woerter | SKILL.md, Kriterium „Wortzahl" |
| `no_cross_references` | keine Zitate, Kapitel-, Abbildungs- oder Tabellenverweise | SKILL.md, „Keine Zitate, Abbildungs- oder Kapitelverweise im Abstract" |
| `imrad_moves` | Hintergrund, Methode, Ergebnis, Einordnung vorhanden | SKILL.md, Abschnitt „IMRaD" |
| `keyword_count` | 5–8 Keywords | SKILL.md, „5-8 Keywords" |
| `language_parity` | EN-Laenge innerhalb 10 % der DE-Laenge | sonst ist eine Fassung eine Kuerzung, keine Uebersetzung |
| `no_fabricated_numbers` | jede Zahl im Abstract kommt im Quelltext vor | SKILL.md, „keine Informationen, die nicht in der Arbeit stehen" |

Der letzte Pfad ist der inhaltliche Kern: er vergleicht das Ergebnis gegen die
Quelle, nicht gegen sich selbst. `test_fabrication_check_reads_the_source_not_the_abstract`
belegt das, indem es denselben Abstract gegen einen fremden Quelltext faehrt —
das Urteil kippt.

## Warum das offline geht

Reine Standardbibliothek (`re`, `json`). Kein Netz, kein `ANTHROPIC_API_KEY`.

## Gegenprobe

`counter_examples.json` haelt vier Abstracts zum Quelltext von `ag-01` fest, je
mit genau **einem** Defekt. Jeder muss ueber genau seinen Pruefpfad als FAIL
gemeldet werden:

- **`ce-ag-01`** behauptet eine Kennzahl (27 %), die der Quelltext nicht hergibt.
- **`ce-ag-02`** verweist auf „Kapitel 4" — ausserhalb der Arbeit wertlos.
- **`ce-ag-03`** laesst den Methoden-Zug weg.
- **`ce-ag-04`** nennt nur drei Keywords.

## Grenzen dieser Zahl

Der Korpus ist **hand-autoriert und synthetisch**. Gemessen wird die
Trennschaerfe gegen bekannte Defekte, nicht die Qualitaet eines Live-Abstracts.
Insbesondere prueft `no_fabricated_numbers` nur Zahlen — eine erfundene
Behauptung ohne Zahl bleibt unsichtbar. Dafuer braeuchte es ein Modell; genau
das ist hier bewusst ausgeschlossen.

## Ausfuehren

```
python3 evals/abstract-generator/runner.py
uv run pytest tests/evals/test_abstract_generator_metrics.py
```
