# source-quality-audit — Offline-Qualitaetsmetrik (Issue #606)

**Status in `docs/evals/STRATEGY.md`: `metric`.**

## Was hier gemessen wird

**Der Audit-Report gegen den Quellenbestand.** `runner.py` rechnet die fuenf
gewichteten Dimensionen aus `skills/source-quality-audit/SKILL.md` aus dem
Inventar nach — `0.25*peer_review + 0.20*recency + 0.20*diversity +
0.15*web_ratio + 0.20*coverage` — und prueft, ob der zugehoerige Report
dieselben Zahlen und denselben Status nennt.

Bezugspunkt ist damit der **Bestand**, nicht der Report. Gemessen wird
Fabrikation im Ergebnis, nicht die Rubrik gegen sich selbst
(`test_report_is_checked_against_the_inventory_not_against_itself` faehrt
denselben Report gegen ein fremdes Inventar — das Urteil kippt).

| Pruefpfad | Was reisst |
| --- | --- |
| `dimension_scores` | eine der fuenf Zahlen weicht um mehr als die Toleranz ab |
| `overall_score` | der Gesamtscore ist nicht der gewichtete Wert des Bestands |
| `status` | OK/WARN/FAIL passt nicht zu den Schwellen (OK ≥ 70, WARN 50–69, FAIL < 50) |
| `source_count` | die genannte Quellenzahl deckt sich nicht mit dem Inventar |

## Korpus

| Bestand | Peer-Review | Aktualitaet | Diversitaet | Web | Abdeckung | **Gesamt** |
| --- | --- | --- | --- | --- | --- | --- |
| `inv-strong` (18 Quellen) | 75 | 96 | 95 | 94 | 100 | **91 (OK)** |
| `inv-weak` (12 Quellen) | 53 | 0 | 40 | 30 | 78 | **41 (FAIL)** |

Beide Bestaende sind vollstaendig ausbuchstabiert (Autor, Jahr, Venue, Typ,
Peer-Review-Status, Land, Position, Konzepte). Die Sollwerte sind in
`corpus.json` committet, nicht im Testcode hergeleitet.

Der schwache Bestand ist kein Zierstueck: ohne ihn haette die Skala keine
Spannweite, und eine Metrik, die nur gute Bestaende kennt, kann kein
Absinken anzeigen.

## Grundlagenwerke

`SKILL.md` nimmt Grundlagenwerke ausdruecklich von Aktualitaetsabzuegen aus.
Der Runner setzt das um, indem `foundational`-Quellen aus Zaehler **und** Nenner
der Aktualitaetsrechnung fallen. `test_foundational_works_are_exempt_from_recency`
belegt, dass die Ausnahme wirkt und nicht nur behauptet ist.

## Warum das offline geht

Reine Standardbibliothek (`re`, `json`, `collections`). Kein Netz, kein
`ANTHROPIC_API_KEY`.

## Gegenprobe

`counter_examples.json` haelt vier Reports fest, je mit genau **einem** Defekt:

- **`ce-sqa-01`** behauptet Gesamt 85, wo der Bestand 41 hergibt.
- **`ce-sqa-02`** nennt alle Zahlen korrekt, weist 41 aber als `OK` aus.
- **`ce-sqa-03`** behauptet 40 Quellen, wo 18 im Inventar stehen.
- **`ce-sqa-04`** schreibt allein den Peer-Review-Score von 75 auf 95 hoch.

Jeder muss ueber **genau** seinen Pruefpfad als FAIL gemeldet werden — sonst
waere nicht belegt, welcher Pfad ausschlaegt.

## Grenzen dieser Zahl

Die Baender aus `SKILL.md` sind in Prosa formuliert („ueberwiegend aeltere
Quellen"); der Runner operationalisiert sie linear innerhalb der dort genannten
Grenzen. Ein Report, der eine andere, ebenfalls vertretbare Operationalisierung
faehrt, faellt hier durch, ohne falsch zu sein. Gemessen wird deshalb
Konsistenz gegen eine festgelegte Lesart der Rubrik — kein Urteil ueber die
Rubrik selbst. Bestaende und Reports sind hand-autoriert und synthetisch.

## Ausfuehren

```
python3 evals/source-quality-audit/runner.py
uv run pytest tests/evals/test_source_quality_audit_metrics.py
```
