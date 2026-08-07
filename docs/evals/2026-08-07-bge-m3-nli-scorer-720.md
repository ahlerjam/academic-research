# Eval-Report — NLI-Scorer-Wechsel auf bge-m3-zeroshot-v2.0 (Issue #720)

> **Historisches Dokument.** Momentaufnahme eines einzelnen A/B-Laufs, nicht
> der aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-07
**Komponente:** `academic_vault/nli_prefilter.py` (NLI-Batch-Vorfilter, Issue
#524/#592/#720), `evals/524-nli-prefilter/`
**Grundlage:** A/B-Messung vom 2026-08-06 auf Apple M4 Pro über **278 Fälle**
— `cases.json` (32, konstruiert, #524), `real-cases.json` (60, reale
ML/NLP-Paper, #592), `extended-cases.json` (186, reale Paper über acht
Fachrichtungen, #721).

## Entscheidung

Der produktive Scorer (`academic_vault/nli_prefilter.py`) wechselt von
`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` auf
`MoritzLaurer/bge-m3-zeroshot-v2.0`, Entscheidungsschwelle **0,95** (zuvor
0,50). `MDebertaScorer` bleibt als Eval-Kandidat erhalten (eigener Default
0,5, unverändert gegenüber #524/#592), ist aber nicht mehr Produktivmodell.

## Methode

Beide Modelle laufen mit identischer Metrik und Entscheidungsregel
(`evals/524-nli-prefilter/runner.py::_score_model`, wiederverwendet über
`run_eval_all_278_cases()`): `argmax == entailment` UND
`p(entailment) >= threshold`. Der Entailment-Index wird für beide Modelle
aus `model.config.id2label` gelesen (`academic_vault.nli_prefilter.NliModelScorer`)
statt fest verdrahtet — bge-m3-zeroshot ist **binär**
(`{0: entailment, 1: not_entailment}`), mDeBERTa **dreiklassig**
(`{0: entailment, 1: neutral, 2: contradiction}`). Ein hermetischer Unit-Test
(`tests/test_issue_720_bge_m3_scorer.py`) belegt mit gestubbten Modellen, dass
beide Schemata korrekt behandelt werden — inklusive eines Falls, in dem
Entailment absichtlich NICHT an Index 0 steht.

mDeBERTa reproduziert auf den Altsets (`cases.json`, `real-cases.json`) die
dokumentierten #524/#592-Werte exakt — der Lauf ist gegen den Bestand
kalibriert.

## Schwellenkurve, alle 278 Fälle

| Schwelle | bge-m3: FP | FN | Prec | Rec | mDeBERTa: FP | FN | Prec | Rec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0,50 | 22 | 18 | 0,845 | 0,870 | 16 | 32 | 0,869 | 0,768 |
| 0,70 | 18 | 30 | 0,857 | 0,783 | 15 | 37 | 0,871 | 0,732 |
| 0,80 | 12 | 39 | 0,892 | 0,717 | 12 | 44 | 0,887 | 0,681 |
| 0,90 | 5 | 52 | 0,945 | 0,623 | 10 | 51 | 0,897 | 0,630 |
| **0,95** | **1** | 69 | 0,986 | 0,500 | 10 | 57 | 0,890 | 0,587 |

Auf dem neuen Set allein (92 faithful / 94 verzerrend aus #721):

| Schwelle | durchgerutscht | Rauschen | `condition-stripped` erkannt |
| --- | --- | --- | --- |
| 0,90 | 5 | 50 % | 13/16 |
| **0,95** | **1** | **65 %** | **15/16** |
| 0,99 | 0 | 100 % | 16/16 |

**Tragend ist die Kalibrierbarkeit, nicht ein einzelner Precision-Vorsprung.**
bge-m3 lässt sich über die Schwelle von 22 auf 1 durchgerutschte Verzerrung
steuern. mDeBERTa **sättigt bei 10** und bleibt dort auch bei 0,95 — bei zehn
verzerrten Fällen ist mDeBERTa hoch überzeugt, sie seien gedeckt. Das ist ein
Fehler, an den keine Schwellenwahl herankommt, weil die Wahrscheinlichkeits-
masse selbst falsch liegt, nicht nur knapp unter der Schwelle.

Bei 0,99 werden alle Verzerrungen gefangen — und alle korrekten Zitate
ebenfalls gemeldet. Einen Arbeitspunkt mit wenig Durchrutschen *und* wenig
Rauschen gibt es nicht.

### Warum 0,95 trotz 65 % Rauschen

Ausschlaggebend ist die Fehlerasymmetrie im Detektor-Betrieb: Die Meldungen
prüft der `quote-fidelity-auditor` (Sonnet-Subagent), nicht der Mensch direkt.
Rauschen kostet Tokens im nachgelagerten Lauf, ein Durchrutschen kostet einen
unbemerkten Fehler in der Abschlussarbeit. Die teurere Richtung ist die
falsche — deshalb die hohe Schwelle trotz des Preises von 52 (bei 0,90) bzw.
69 (bei 0,95) zusätzlich gemeldeten treuen Zitaten.

## Priorisierer, nicht Torwächter

Der Batch-Vorfilter (`run_batch_prefilter`) entscheidet, **welches Zitat
zuerst** inhaltlich vom `quote-fidelity-auditor` geprüft wird — er entscheidet
**nicht, was durchgeht**. Ein Zitat ohne NLI-Meldung ist nicht "geprüft", nur
nicht priorisiert; der Prefilter ist standardmäßig aus
(`DEFAULT_PREFILTER_ENABLED = False`) und bleibt es, solange kein
gegenteiliger Produktentscheid vorliegt. Diese Klarstellung steht jetzt auch
im Modul-Docstring von `academic_vault/nli_prefilter.py`.

## Bekannte strukturelle Grenze — `condition-stripped`

Erkennungsrate je Verzerrungstyp, neues Set, Schwelle 0,80:

| Typ | n | bge-m3 | mDeBERTa |
| --- | --- | --- | --- |
| significance-flip | 8 | 8/8 | 8/8 |
| magnitude-inflation | 22 | 21/22 | 22/22 |
| overgeneralization | 24 | 23/24 | 22/24 |
| causal-overreach | 24 | 22/24 | 19/24 |
| **condition-stripped** | **16** | **8/16** | **11/16** |

Bei Schwelle 0,95 steigt die bge-m3-Erkennung auf `condition-stripped` auf
**15/16** — aber der eine verbleibende Durchrutscher ist strukturell, nicht
zufällig. Beispiel `x-med-034`, p = 0,977:

> Quelle: „**Among patients with** acute ischemic stroke **with a proximal
> vessel occlusion, a small infarct core, and moderate-to-good collateral
> circulation**, rapid endovascular treatment improved functional outcomes"
> Behauptung: „Die rasche endovaskuläre Behandlung verbessert bei akutem
> ischämischem Schlaganfall das funktionelle Ergebnis"

Das ist kein Widerspruch — die Behauptung *folgt* aus der Quelle, sie weitet
nur den Geltungsbereich aus. NLI beantwortet „folgt daraus?", nicht „gilt
derselbe Geltungsbereich?". Das Modell ist nicht unsicher, es beantwortet
korrekt eine andere Frage. Das ist eine **Eigenschaft der NLI-Aufgabe selbst**,
nicht der Modellwahl — kein anderes NLI-Modell würde dieses Muster ohne
Zusatzverfahren erkennen. `condition-stripped` ist zugleich der Typ, der in
Abschlussarbeiten am häufigsten vorkommt (eine Randbedingung fällt beim
Übertragen eines Befunds weg) und der einzige Typ, bei dem mDeBERTa vorn
liegt. Nach Fach konzentrieren sich die Durchrutscher erwartungsgemäß in der
Medizin (6 von 36 verzerrten Fällen bei beiden Modellen) — dort sind die
Einschlusskriterien am komplexesten.

**Konsequenz für die Doku:** Das Werkzeug darf nicht den Eindruck erwecken,
weggelassene Bedingungen zuverlässig zu finden.

## Verworfene Zusatzansätze

Zwei Abhilfen gegen `condition-stripped` wurden gemessen und verworfen —
damit sie nicht erneut untersucht werden.

### Lexikalischer Restriktor-Detektor

Regex auf Einschränkungsmuster in der Quelle (`among patients…`,
`only when…`, `in the … group`), dann Abgleich, ob deren Inhaltswörter in der
Behauptung vorkommen. Ergebnis auf dem neuen Set: **3 zusätzlich gefangene
Verzerrungen gegen 14 neue Fehlalarme.** Scheitert am Sprachwechsel —
„in the intensive-treatment group" wird korrekt zu „in der Gruppe mit
intensiver Behandlung", aber `treatment`/`Behandlung` teilen keinen
Wortstamm. Skript dokumentarisch aufbewahrt: `evals/524-nli-prefilter/bidir.py`
enthält die verwandte bidirektionale Messung; der reine Restriktor-Prototyp
selbst wurde nicht ins Repo übernommen (verworfen vor Commit).

### Bidirektionales NLI

Zusätzlich die Gegenrichtung prüfen (Behauptung als Prämisse, Quellsatz als
Hypothese, `evals/524-nli-prefilter/bidir.py`) — eine übergeneralisierte
Behauptung impliziert die spezifische Quelle nicht, das ist inhaltlich
richtig. Aber eine strengere Einzelschwelle leistet dasselbe billiger:

| Verfahren | FP | Rauschen | `condition-stripped` |
| --- | --- | --- | --- |
| **nur vorwärts, 0,95** | **1** | **65 %** | **15/16** |
| vorwärts 0,90 + rückwärts 0,30 | 1 | 70 % | 15/16 |
| nur vorwärts, 0,97 | 1 | 78 % | 15/16 |

Bei gleichem Ergebnis ist die einfache Variante besser und spart die doppelte
Inferenz (zwei Modellaufrufe statt einem, doppelte Latenz ohne messbaren
Recall-Gewinn).

## Kosten

| | mDeBERTa-XNLI (bisher) | bge-m3-zeroshot (neu) |
| --- | --- | --- |
| Parameter | 279 Mio. | 568 Mio. |
| Plattenbedarf | ~0,5 GB | ~1,1 GB |
| Latenz/Paar (warm, CPU) | ~95 ms | ~96 ms |

Laufzeit praktisch unverändert — beide Modelle schneiden den Kontext ohnehin
bei `max_length=512` ab, der Mehrbedarf steckt im Parametercount, nicht im
Inferenzpfad. `docs/evals/STRATEGY.md` ist auf den neuen Plattenbedarf
nachgezogen.

## Grenze: konstruierte Verzerrungen sind nicht dasselbe wie im Feld beobachtete

Wie bereits für die 32 Fälle aus #524 und in abgeschwächter Form für die 60
realen, aber händisch verzerrten Fälle aus #592 dokumentiert
(siehe [`2026-08-06-extended-nli-goldset-721.md`](2026-08-06-extended-nli-goldset-721.md)):
Die 186 Fälle aus #721 entstehen durch **feste Transformationsregeln**
(`overgeneralization`, `condition-stripped`, `causal-overreach`,
`magnitude-inflation`, `significance-flip`) auf unveränderten
Abstract-Ausschnitten — das Label folgt aus der Regel, nicht aus einer
Einzeleinschätzung. Das macht die Messung methodisch sauberer, aber nicht
repräsentativ für reale Fehler: konstruierte Verzerrungen kombinieren keine
Transformationstypen, fallen nicht so subtil aus wie eine über mehrere Sätze
schleichende Bedeutungsverschiebung, und decken nur die fünf benannten
Muster ab. Die Schwellenkurve und die Typ-Aufschlüsselung oben sind ein
Signal für die Trennschärfe zwischen einer treuen Wiedergabe und ihrer
geregelten Transformation — kein Beleg für die Fehlerrate auf im Feld
beobachteten, unregelmäßig entstandenen Verzerrungen.

## Reproduktion

`tests/evals/test_nli_prefilter_evals.py::test_live_threshold_curve_matches_720_report`
reproduziert die Schwelle-0,95-Zahlen (bge-m3: 1 Durchrutscher, mDeBERTa: 10)
gegen alle 278 im Repo liegenden Fälle — Opt-in per `RUN_LIVE_NLI_PREFILTER=1`
(Netz + Modell-Download, ~1,7 GB für beide Modelle zusammen). Struktur- und
id2label-Tests laufen immer, ohne Netz:

```bash
# Hermetisch, immer (id2label binaer/dreiklassig, Modell/Schwelle-Konstanten):
uv run pytest tests/test_issue_720_bge_m3_scorer.py -q

# Hermetisch, immer (Goldset-Struktur, Runner-Verdrahtung):
uv run pytest tests/evals/test_nli_prefilter_evals.py -q

# Live-Reproduktion der Schwellenkurve (Netz + Modell-Download):
RUN_LIVE_NLI_PREFILTER=1 uv run pytest tests/evals/test_nli_prefilter_evals.py -q -k threshold_curve

# 278-Faelle-A/B-Vergleich ueber den Runner direkt:
python3 -c "import sys; sys.path.insert(0,'evals/524-nli-prefilter'); import runner; print(runner.run_eval_all_278_cases())"
```

## Betroffene Dateien

- `academic_vault/nli_prefilter.py` — `MODEL_ID`/`MDEBERTA_MODEL_ID`,
  `DEFAULT_THRESHOLD` (0,95)/`MDEBERTA_DEFAULT_THRESHOLD` (0,5), generische
  `NliModelScorer` (id2label-Ableitung) mit den Spezialisierungen
  `BgeM3ZeroshotScorer` (Produktivscorer) und `MDebertaScorer` (Eval-Kandidat).
- `evals/524-nli-prefilter/runner.py` — `BgeM3ZeroshotScorer` als dritter
  Kandidat, `load_all_278_cases()`/`run_eval_all_278_cases()` für den
  Dreier-Vergleich über alle drei Goldsets.
- `tests/test_issue_720_bge_m3_scorer.py` — hermetischer id2label-Test
  (binär + dreiklassig, Entailment absichtlich nicht an Index 0).
- `tests/evals/test_nli_prefilter_evals.py` — Konsolidierung des vormals
  duplizierten `_BgeM3ZeroshotScorer`-Prototyps auf die kanonische Klasse.
- `docs/evals/STRATEGY.md` — Plattenbedarf und Modell-Zeile nachgezogen.
