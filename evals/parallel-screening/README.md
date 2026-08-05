# parallel-screening — Offline-Qualitaetsmetrik (Issue #606)

**Status in `docs/evals/STRATEGY.md`: `metric`.**

## Was hier gemessen wird

Die **Ausbeute des Rankings**, nicht die Form einer Ausgabe. `runner.py` faehrt
mit `skills/parallel-screening/scripts/active_learning.py::validate_ranking()`
ein vollstaendiges Screening gegen `gold_screening.json` — ein Set aus 60
Kurzeintraegen mit committeten Ein-/Ausschluss-Urteilen — und liest die
Recall-Kurve ab.

| Bezugspunkt | Recall nach 30 % der Liste |
| --- | --- |
| Ausgangsreihenfolge, ohne Umsortierung | 20,0 % |
| Zufall (Diagonale) | 30,0 % |
| **Mit Umsortierung durch Active Learning** | **73,3 %** |

Die Schwelle liegt bei 60 % und damit deutlich ueber der Diagonalen: eine
Metrik, die durch Nichtstun erfuellbar waere, misst nichts.

## Warum das offline geht

`active_learning.py` ist reine Standardbibliothek (multinomialer Naive Bayes mit
Laplace-Glaettung ueber Titel + Abstract). Kein Netz, kein Modell-Download, kein
`ANTHROPIC_API_KEY`. Das Retrain-Intervall wird explizit auf 10 gesetzt, damit
weder Umgebungsvariable noch Config-Datei das Ergebnis verschieben.

## Gegenprobe

`counter_examples.json` haelt zwei absichtliche Verschlechterungen fest, die
beide die Schwelle reissen muessen:

- **`ce-ps-01`** rotiert die Labels um 7 Positionen — das Vokabular hat mit den
  Urteilen nichts mehr zu tun, der Recall faellt auf 33,3 %.
- **`ce-ps-02`** entleert Titel und Abstract aller Eintraege — ohne
  unterscheidbaren Text faellt die Kurve auf die Ausgangsreihenfolge (20,0 %).

## Grenzen dieser Zahl

Der Korpus ist **hand-autoriert und synthetisch**, keine Stichprobe echter
Publikationen. Gemessen wird die Trennschaerfe des Rankings gegen bekannte
Defekte, nicht die Qualitaet eines Live-Screenings. Ein hoher Wert hier belegt,
dass das Verfahren relevante von irrelevanten Texten unterscheiden kann — nicht,
dass es das auf einer realen Trefferliste in gleicher Hoehe tut.

## Ausfuehren

```
python3 evals/parallel-screening/runner.py
uv run pytest tests/evals/test_parallel_screening_metrics.py
```
