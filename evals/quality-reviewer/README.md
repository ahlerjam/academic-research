# quality-reviewer — Offline-Qualitaetsmetrik (Issue #606)

**Status in `docs/evals/STRATEGY.md`: `metric`.**

## Was hier gemessen wird — und was ausdruecklich nicht

Der Agent ist selbst ein LLM-Judge. Ihn offline nachzubauen hiesse, einen Judge
durch einen Regex zu ersetzen; das waere die Scheinmetrik, vor der
`docs/evals/STRATEGY.md` warnt. Gemessen wird deshalb eine Ebene tiefer: die
**Trennschaerfe der Kriterien**, gegen die der Agent urteilt.

`runner.py` rechnet die vier Metriken exakt nach den `Metrik-Hinweise`n aus
`agents/quality-reviewer.md` nach — Satzlaengen-Median, Passiv-Quote,
Nominalstil, Quellen je 1000 Woerter — und leitet daraus das Verdict nach der
dort dokumentierten Regel ab:

- mindestens ein FAIL → `REVISE`
- mindestens ein FAIL **und** `iteration >= 2` → `ESCALATE`, `BLOCKIERT_VON: iteration-limit`
- kein FAIL → `PASS`, auch bei `iteration >= 2`

Nicht gemessen wird, ob das Modell diese Regel im Betrieb korrekt anwendet. Das
bleibt der API-gateten Suite `tests/evals/test_quality_reviewer_evals.py`.

## Gegenprobe: derselbe Text, eine Achse verschlechtert

`counter_examples.json` nimmt `qr-01` (PASS) und verschlechtert ihn je auf genau
einer Achse. Jede Variante muss das Verdict kippen — und zwar ueber genau das
verschlechterte Kriterium, geprueft von
`test_each_counter_example_fails_exactly_its_own_criterion`.

| Fall | Eingriff | Erwartet |
| --- | --- | --- |
| `ce-qr-01` | in Vorgangsform umgeschrieben | REVISE ueber `Passiv-Quote` |
| `ce-qr-02` | die beiden Klammerbelege entfernt | REVISE ueber `Quellen pro 1000 Woerter` |
| `ce-qr-03` | Punkte durch Kommata ersetzt | REVISE ueber `Satzlaenge Median` |

Ohne diese Kontrolle waere wiederholbar, was #454 bei `sparring-partner`
freigelegt hat: Kriterien, die Formattreue statt Verhalten messen.

## Ein belegter blinder Fleck (`qr-05`)

Die im Agent dokumentierte Passiv-Regex ist
`\bwerd(en|est|et)\b.*?(ge\w+|\w+iert)\b`. Sie erkennt **kein** Passiv mit
`wird`/`wurde` und keine Praefix-Partizipien wie `ausgewertet` oder
`uebermittelt`. `qr-05` besteht aus sechs solchen Saetzen und ist mit
`passive_share_pct: 0.0` committed: die Luecke wird ausgewiesen, nicht
geglaettet. Wer die Regel im Agent erweitert, muss diesen Sollwert bewusst
aendern — der Test macht die Aenderung sichtbar, statt sie durchrutschen zu
lassen. Die Regel selbst bleibt unangetastet (Scope #606: „hier wird gemessen,
nicht verbessert").

## Grenzen dieser Zahl

Die Texte sind **hand-autoriert und synthetisch**; alle Satzlaengen sind von Hand
ausgezaehlt und stimmten beim ersten Lauf mit der Messung ueberein. Gemessen wird
die Trennschaerfe gegen bekannte Defekte, nicht die Urteilsqualitaet des Modells.

## Ausfuehren

```
python3 evals/quality-reviewer/runner.py
uv run pytest tests/evals/test_quality_reviewer_metrics.py
```
