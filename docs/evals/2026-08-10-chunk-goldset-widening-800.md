# Chunk-Goldset verbreitert: 26 auf 60 Queries (#800)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md); die
> laufend geprüfte Fassung der Zahlen ist `thresholds.json` neben dem Goldset.

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-10 · **Modell:** `intfloat/multilingual-e5-small` (384d) ·
**Korpus:** 61 Chunks aus 21 synthetischen Volltexten · **Queries:** 60

## Warum

Das #708-Chunk-Goldset trug 26 Queries auf 30 Chunks. Eine einzelne Query war
damit 0,0385 Recall@10 wert — die Auflösungsgrenze, die
[`2026-08-08-embedding-model-decision-732.md`](2026-08-08-embedding-model-decision-732.md)
selbst als Grund nennt, die Modellentscheidung später neu zu prüfen: bge-m3
(0,9808) und qwen3-384 (0,9615) trennten zwei Queries. Dieses Issue
verbreitert das Messgerät auf 60 Queries bei **unveränderter** Konstruktions-
disziplin — kein Modellwechsel, keine Änderung an der Retrieval-Logik.

## Was hinzugekommen ist

**10 neue Quelldokumente** (5 EN-Ziel, 3 DE-Ziel, 1 EN-Distraktor,
1 DE-Distraktor — dieselbe Rollenverteilung wie bei den elf #708-Dokumenten,
grob verdoppelt), vollständig selbst geschrieben, thematisch im selben Feld
(DevOps/Governance/Digitalisierung):

| doc_id | Sprache | Rolle | Thema |
|---|---|---|---|
| `en-feature-flag-governance` | en | Ziel | Feature-Flag-Lebenszyklus, Blast Radius, Audit |
| `en-capacity-forecasting` | en | Ziel | Kapazitätsplanung, Quotengrenzen, Prognosefehler |
| `en-onboarding-access` | en | Ziel | Zugriffsvergabe für neue Mitarbeitende |
| `en-vendor-risk` | en | Ziel | Betriebsrisiko bei Managed-Cloud-Diensten |
| `en-runbook-quality` | en | Ziel | Runbook-Qualität im Ernstfall |
| `en-training-metrics` | en | Distraktor | Wirksamkeit von Schulungsprogrammen |
| `de-cloud-auftragsverarbeitung` | de | Ziel | Auftragsverarbeitung bei Cloud-Diensten |
| `de-notfallwiederherstellung` | de | Ziel | Notfallwiederherstellung, Failover, RTO/RPO |
| `de-zugriffskonzept` | de | Ziel | Rollenbasiertes Zugriffskonzept, Rezertifizierung |
| `de-schulungsnachweis` | de | Distraktor | Nachweis von Sicherheitsschulungen |

**34 neue Queries** in denselben drei Fällen wie #708, mit demselben
Ankermechanismus (`resolve_anchors` in
`scripts/eval/build_retrieval_chunk_goldset.py`):

| `case` | neu | gesamt (#708 → #800) |
|---|---:|---:|
| `same-language` (14 EN, 9 DE) | 23 | 18 → 41 |
| `language-gap` (DE-Umgangssprache → EN-Text) | 8 | 6 → 14 |
| `cross-language` (EN-Frage → DE-Text) | 3 | 2 → 5 |
| **gesamt** | **34** | **26 → 60** |

Drei der acht neuen `language-gap`-Anker liegen bewusst in den **unveränderten**
#708-Dokumenten (`en-change-approval`, `en-supply-chain`,
`en-incident-response`) — an Textstellen, die von keiner bestehenden Query
referenziert wurden. Das nutzt Kapazität aus, die im 26er-Set brachlag, statt
für jeden neuen Fall zwingend ein neues Dokument zu brauchen.

## Verteilung: vorher/nachher

| | #708 (26 Queries) | #800 (60 Queries) |
|---|---:|---:|
| `lang` en/de | 13 / 13 (50,0 % / 50,0 %) | 30 / 30 (50,0 % / 50,0 %) |
| `same-language` | 18 (69,2 %) | 41 (68,3 %) |
| `language-gap` | 6 (23,1 %) | 14 (23,3 %) |
| `cross-language` | 2 (7,7 %) | 5 (8,3 %) |
| Dokumente | 11 (7 en / 4 de) | 21 (13 en / 8 de) |
| Chunks | 30 | 61 |

Die Sprachverteilung bleibt exakt 50/50. Der Anteil des leichtesten Falls
(`same-language`) sinkt leicht (69,2 % → 68,3 %) statt zu steigen; die beiden
schwierigen Fälle (`language-gap`, `cross-language`) wachsen relativ leicht
mit — `cross-language` bewusst etwas stärker, wie im Issue vorgeschlagen, weil
es der schwierigste Fall ist. Die Verteilung ist damit **nicht einseitiger**
geworden, sondern minimal ausgeglichener. Maschinell geprüft in
`tests/test_issue_800_goldset_widening.py::TestDistributionIsNotMoreSkewed`.

## Die neue Auflösung je Query

| | #708 | #800 |
|---|---:|---:|
| Queries | 26 | 60 |
| Recall@10-Punktwert einer einzelnen Query | 0,0385 | 0,0167 |

Eine einzelne Query ist jetzt 0,0167 statt 0,0385 Recall@10-Punkte wert — eine
Verbesserung um den Faktor 2,3. Der bge-m3/qwen3-384-Abstand aus #732
(0,9808 vs. 0,9615, ein Unterschied von 2 Queries auf 26) bräuchte auf diesem
Set nur noch 1 Query Unterschied, um denselben Abstand abzubilden; ob er sich
auf 60 Queries reproduziert, ist eine eigene Messung (#801) und keine, die
dieses Issue beantwortet.

## Ergebnis des Referenzlaufs (e5-small, #708-Modell)

| Teilmenge | Queries | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|---:|
| **gesamt** | 60 | **0,8167** | **0,7097** | **0,6764** |
| `same-language` | 41 | 1,0000 | 0,9212 | 0,8974 |
| `language-gap` | 14 | 0,5000 | 0,2725 | 0,1994 |
| `cross-language` | 5 | 0,2000 | 0,2000 | 0,2000 |

Zum Vergleich der #708-Referenzlauf (26 Queries, 30 Chunks):

| Teilmenge | Queries | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|---:|
| **gesamt** | 26 | 0,7692 | 0,6651 | 0,6314 |
| `same-language` | 18 | 1,0000 | 0,9170 | 0,8889 |
| `language-gap` | 6 | 0,3333 | 0,1311 | 0,0694 |
| `cross-language` | 2 | 0,0000 | 0,0000 | 0,0000 |

`same-language` bleibt bei Recall@10 = 1,0 gesättigt (61 Chunks bei k=10 sind
immer noch klein genug, dass die Zielchunks der einfachen Fälle fast immer in
die Top 10 passen) — erwartbar, das Set löst dieses Problem nicht, es macht
die schwierigen Fälle nur belastbarer. Der eigentliche Fortschritt liegt bei
`cross-language`: **zum ersten Mal ein von 0 verschiedener Messwert**
(0,2 statt 0,0), weil eine von fünf statt keiner von zwei Queries trifft. Eine
einzelne Schwelle von exakt 0,0 war bislang kein Gatter, sondern eine
Kapitulation vor der Auflösungsgrenze — das ändert sich mit diesem Set.

## Wie die neuen Schwellen zustande kamen

Wie in #708: **gemessener Referenzlauf minus 0,02 Marge**
(`build_retrieval_chunk_goldset.py --write-thresholds`, `DEFAULT_MARGIN`
unverändert). Die Marge bleibt klein, weil der Lauf bei fixen Vektoren
deterministisch ist — sie fängt Rundungsunterschiede zwischen Plattformen ab,
keine Qualitätsschwankung.

```json
{
  "overall":         {"recall_at_10": 0.7967, "ndcg_at_10": 0.6897, "mrr": 0.6564},
  "same-language":   {"recall_at_10": 0.9800, "ndcg_at_10": 0.9012, "mrr": 0.8774},
  "language-gap":    {"recall_at_10": 0.4800, "ndcg_at_10": 0.2525, "mrr": 0.1794},
  "cross-language":  {"recall_at_10": 0.1800, "ndcg_at_10": 0.1800, "mrr": 0.1800}
}
```

**Alle alten Schwellen sind ungültig und wurden ersetzt**, nicht angepasst:
sie galten für ein Set mit anderer Chunk- und Query-Zahl, und ein direkter
Vergleich der Zahlenwerte (z. B. `cross-language` 0,0 → 0,18) ist kein
Qualitätssprung, sondern eine Folge der größeren Stichprobe. Die harte Regel
aus dem Auftrag ist eingehalten: keine Schwelle wurde gewählt, um ein Gatter
grün zu bekommen — alle vier Blöcke sind exakt `Messwert - 0,02`, mechanisch
erzeugt, nicht von Hand nachjustiert.
`tests/test_issue_708_retrieval_chunk_goldset.py::test_thresholds_stay_below_measured_values`
prüft das (keine Schwelle über dem Messwert, keine mehr als 0,15 darunter).

## Konstruktionsregeln (extrahiert aus #708/#790, unverändert angewandt)

1. **Ankerauflösung statt Chunk-Indizes.** Jede Query trägt einen wörtlichen
   Anker; `resolve_anchors` löst ihn auf die Chunks auf, die ihn enthalten
   (case-sensitiv, whitespace-normalisiert). Ein Anker, der in keinem Chunk
   vorkommt, bricht den Generator mit `ValueError` ab.
2. **Trivialitätsverbot.** Query-Text und Anker dürfen sich nicht wörtlich
   enthalten — Queries sind umformulierte Fragen, keine Zitate.
3. **Sprachlücke ohne lexikalische Brücke.** `language-gap`- und
   `cross-language`-Queries teilen kein Wort ab fünf Zeichen mit dem Text
   ihres Zielchunks (sonst würde die Query lexikalische statt semantische
   Ähnlichkeit messen).
4. **Verteilung nicht einseitiger als vorher.** `lang` nahe 50/50, die
   `case`-Anteile mindestens proportional zum Vorgängerset — der schwierigste
   Fall (`cross-language`) darf überproportional wachsen.
5. **Distraktor-Rolle der Dokumente.** Ein fester Anteil der Dokumente
   (~27 % in #708, hier 6 von 21) trägt Vokabular, das mit den Zieldokumenten
   überlappt, wird aber von keiner Query referenziert — sie erzeugen
   Rangdruck, ohne je das Ziel einer Relevanzentscheidung zu sein.
6. **Trefferbasis nicht dünner.** Korpusgröße relativ zu `k=10` darf nicht
   sinken (#708: 30/10 = 3,0×; #800: 61/10 = 6,1×) — sonst sättigt Recall@10
   noch schneller als vorher.

`tests/test_issue_800_goldset_widening.py` prüft alle sechs Regeln
maschinell, nicht nur die neuen 34 Queries, sondern das gesamte 60er-Set.

## Abhängige Gatter

Die Erweiterung von `sources.json` entwertet jede Fixture, die byteweise auf
dem alten #708-Textstand aufbaut. Nachgezogen wurden:

| Gatter | Skript | Status |
|---|---|---|
| #708-Schwellen | `run_retrieval_chunk_goldset.py --check-thresholds` | grün, neue Schwellen (siehe oben) |
| #790-Replay (Probe-Goldset + #708-Baseline) | `run_retrieval_ablation_729.py --check-against …790-live-results.json` | grün, Rohdaten neu erzeugt |
| #731-Kandidatenvergleich | `run_embedding_candidates_731.py --check-against …731-live-results.json` | grün, alle 5 Kandidaten neu erzeugt |

Details je Gatter, mit den tatsächlich ausgeführten Kommandos, stehen im
Abschluss-Report der Umsetzung (PR-Beschreibung / Commit-Historie auf
`feat/800-goldset-verbreitern`).

`docs/evals/2026-08-08-chunk-fusion-ablation-729-live-results.json` (der
direkte #729-Report, nicht der #790-Replay) ist **nicht** neu erzeugt — er
wird von keinem CI-Job und keinem Test gegengeprüft (nur im Docstring von
`run_retrieval_ablation_729.py` als Reproduktionsbeispiel referenziert) und
bleibt wie andere historische Reports in diesem Verzeichnis eine
Momentaufnahme des damaligen Laufs.

`scripts/eval/run_hyde_multiquery_eval.py` (#733) lädt das #708-Goldset über
denselben Default-Pfad und ist **nicht** Teil dieses Issues, hängt aber am
selben CI-Job (`retrieval-goldset`). Seine Fixture
(`tests/fixtures/hyde_multiquery_733/transforms.json`) kennt nur die
ursprünglichen 26 Query-IDs; die 34 neuen Queries fehlen darin. Das erfordert
`VAULT_HYDE_LIVE_TRANSFORM=1` (echte `claude`-CLI-Aufrufe, ~120 Stück für
Hyde+Multi-Query über alle 60 Queries) gefolgt von
`VAULT_E5_LIVE_TEST=1 build_hyde_multiquery_fixture.py --stage vectors` — ein
Live-Lauf anderer Art als der reine Vektor-Rebuild dieses Issues, deshalb hier
bewusst nicht mitgezogen. Siehe Abschluss-Report für den Status dieses Gates.

## Grenzen

- **`same-language` bleibt gesättigt.** Recall@10 = 1,0 unverändert; die
  Aussagekraft liegt weiterhin bei nDCG/MRR und den beiden schwierigen
  Fällen.
- **`cross-language` hat jetzt einen wirksamen, aber sehr groben Messwert.**
  5 Queries heißt: jede einzelne ist 20 Prozentpunkte wert. Für einen
  belastbaren Modellvergleich auf dieser Teilmenge allein reicht das noch
  nicht — der Fortschritt ist, dass sie überhaupt misst, nicht dass sie fein
  auflöst.
- **Die neuen Texte sind synthetisch**, wie die elf #708-Dokumente — Fachprosa
  imitiert, nicht zitiert, keine Formeln oder PDF-Extraktionsartefakte.
- **Die nächste Verbreiterung folgt denselben sechs Regeln oben** und sollte
  dieselbe Prüfkette einhalten: `build_chunks`/`resolve_anchors` hermetisch
  gegen die neuen Anker fahren, den Test in
  `tests/test_issue_800_goldset_widening.py` grün bekommen, dann erst den
  Live-Bau auslösen.
