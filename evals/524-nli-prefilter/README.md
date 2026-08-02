# Eval · 524-nli-prefilter

Investigation zu Issue #524: taugt ein lokales NLI-Modell als Batch-Vorfilter
VOR dem Richter-Subagenten `quote-fidelity-auditor` (Issue #523)? Getestet
werden **HHEM-2.1-Open** (Vectara, Apache-2.0) und **mDeBERTa-v3-XNLI**
(MoritzLaurer, MIT) gegen 32 **synthetisch konstruierte** DE-Kapitelbehauptung
/ EN-Quellkontext-Paare — der reale Fall dieses Plugins (deutsche Kapitelprosa
zitiert englische Quellen).

> **Kein echtes Datenmaterial.** academic-research ist ein Tool-Plugin, keine
> Abschlussarbeit. Alle 32 Paare in `cases.json` sind konstruiert, keine
> echten Zitate.
>
> **Zielsystem ist vorhanden.** `quote-fidelity-auditor` (#523) liegt auf
> `main` (PR #582). Der Revert-PR #584 beruhte auf einer Fehlmessung — der
> Post-Merge-CI-Lauf war `cancelled` (abgebrochen durch den naechsten Merge,
> `concurrency: cancel-in-progress` auf main), nicht `failure`; der
> nachfolgende Lauf auf main war gruen. #584 wurde am 2026-08-01 mit Belegen
> geschlossen. Ein Produktiv-Anschlusspunkt fuer einen Vorfilter existiert
> also. Die Empfehlung unten bleibt davon unberuehrt: Sie stuetzt sich auf die
> Datenlage (32 konstruierte Faelle), nicht auf das Fehlen eines Zielsystems.
>
> **Folge-Issue:** #592 nimmt mDeBERTa-v3-XNLI als Vorfilter auf — mit
> konservativer Schwelle, Default AUS und einer Validierung an echtem
> Zitatmaterial als Vorbedingung fuers Scharfschalten.

## Ergebnis auf einen Blick

**Empfehlung: verwerfen** — für einen produktiven Einbau *jetzt*. Details
und die Ausnahme (mDeBERTa-XNLI als möglicher Folge-Kandidat) unten.

| Modell | Precision | Recall | Accuracy | FP | Ø Latenz/Paar (warm) |
| --- | --- | --- | --- | --- | --- |
| HHEM-2.1-Open | 1.00 | 0.125 (2/16) | 0.56 | 0 | ~26 ms (CPU) |
| mDeBERTa-v3-XNLI | 1.00 | 0.812 (13/16) | 0.91 | 0 | ~39 ms (CPU) |

*Precision/Recall beziehen sich auf die Klasse `faithful` (positive Klasse);
FP = ein `verzerrend`-Case wird faelschlich als `faithful` durchgewunken —
der fuer einen Vorfilter gefaehrliche Fehler.* Volle Rohdaten inkl. Case-Details:
[`live-verification.json`](./live-verification.json).

## Lizenz

| Modell | Lizenz (HF-Model-Card) | Quelle | Abgerufen |
| --- | --- | --- | --- |
| `vectara/hallucination_evaluation_model` (HHEM-2.1-Open) | Apache-2.0 | https://huggingface.co/vectara/hallucination_evaluation_model | 2026-08-01 |
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | MIT | https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 | 2026-08-01 |

Beide Lizenzen sind mit dem MIT-Plugin kompatibel — anders als das im Issue-Body
genannte Bespoke-MiniCheck-7B (CC-BY-NC, fuer dieses Repo tabu und darum nicht
getestet).

## Sprachabdeckung

* **HHEM-2.1-Open ist englisch-zentriert.** Die Model-Card trainiert/evaluiert
  auf den englischsprachigen Benchmarks AggreFact und RAGTruth (Quellen-LLMs:
  GPT-4, Llama-2, Mistral). Cross-lingualer Support (u. a. Deutsch) existiert
  laut Model-Card nur in **HHEM-2.3**, einer kommerziellen Version exklusiv
  ueber Vectaras Plattform — nicht in der Open-Source-Gewichtsdatei enthalten.
  Das erklaert den gemessenen Recall-Einbruch unten direkt.
* **mDeBERTa-v3-XNLI ist multilingual.** Vortraining auf CC100 (100 Sprachen),
  NLI-Finetuning explizit auf 27 Sprachen inkl. `de` und `en` (XNLI-Format:
  `ar, bn, de, es, fa, fr, he, hi, id, it, ja, ko, mr, nl, pl, ps, pt, ru, sv,
  sw, ta, tr, uk, ur, vi, zh` + Englisch). Cross-lingualer Transfer auf die
  restlichen ~73 vortrainierten Sprachen ist laut Model-Card moeglich, aber
  ohne dedizierte NLI-Finetuning-Daten schwaecher belegt — fuer unseren
  DE/EN-Fall liegt Deutsch jedoch in den 27 explizit gefinetunten Sprachen.

**Crosslingual-Befund (Kernfrage des Issues):** Alle 32 Cases sind DE-Claim /
EN-Kontext (`claim_lang: "de"`, `context_lang: "en"`) — es gibt in diesem
Datensatz bewusst keine EN/EN-Baseline, weil genau der crosslinguale Fall die
Produktionsrealitaet ist. Der Recall-Unterschied (0.125 vs. 0.812) ist damit
unmittelbar ein Beleg fuer die im Issue vermutete Sprachluecke bei HHEM, nicht
ein Artefakt eines gemischten Datensatzes.

## Precision/Recall je Modell

### HHEM-2.1-Open

| | Vorhergesagt faithful | Vorhergesagt verzerrend |
| --- | --- | --- |
| **Tatsaechlich faithful** (16) | TP = 2 | FN = 14 |
| **Tatsaechlich verzerrend** (16) | FP = 0 | TN = 16 |

Precision 1.00, Recall 0.125, Accuracy 0.56 (kaum ueber Zufallsniveau — ein
Modell, das fast alles als "inconsistent" einstuft, weil es die deutsche
Hypothese nicht zuverlaessig gegen den englischen Kontext abgleichen kann).

### mDeBERTa-v3-XNLI

| | Vorhergesagt faithful | Vorhergesagt verzerrend |
| --- | --- | --- |
| **Tatsaechlich faithful** (16) | TP = 13 | FN = 3 |
| **Tatsaechlich verzerrend** (16) | FP = 0 | TN = 16 |

Precision 1.00, Recall 0.812, Accuracy 0.91 — deutlich brauchbarer, und in
beiden Modellen **keine** falsch durchgewunkene Verzerrung (FP = 0 auf 32
Cases). Bei nur 16 `verzerrend`-Cases pro Modell ist das kein belastbarer
FPR-Nachweis (Faustregel-Obergrenze nach der "Rule of Three" bei 0 Fehlern aus
16 Versuchen: reale FPR koennte bis ~19 % betragen und waere mit diesem
Datensatz nicht sichtbar) — der Befund ist ein positives Signal, kein Beweis.

## Laufzeit / Batch-Tauglichkeit

Gemessen auf CPU (kein GPU im Runner-Environment), warmes Modell (erster Case
pro Modell inkludiert Ladezeit und ist als Ausreisser exkludiert — Rohwerte in
`live-verification.json`):

| Modell | Ø Inferenz/Paar (warm) | Cold-Start (1. Aufruf) | Hochgerechnet (1000 Paare, CPU, seriell) |
| --- | --- | --- | --- |
| HHEM-2.1-Open | ~26 ms | ~5.7 s | ~26 s |
| mDeBERTa-v3-XNLI | ~39 ms | ~0.8 s | ~39 s |

Beide Modelle sind fuer Batch-Vorfilterung auf CPU schnell genug (< 1 Minute
fuer 1000 Paare seriell, ohne Batching-Optimierung) — Laufzeit ist **nicht**
das Ausschlusskriterium in dieser Untersuchung.

## Risiken / Einschraenkungen

* **HHEM-2.1-Open ist mit dem gepinnten `transformers==5.14.1` dieses Repos
  inkompatibel.** `AutoModelForSequenceClassification.from_pretrained(...,
  trust_remote_code=True)` bricht mit `AttributeError:
  'HHEMv2ForSequenceClassification' object has no attribute
  'all_tied_weights_keys'` — die von HHEM mitgelieferte Remote-Code-Datei
  (`modeling_hhem_v2.py`) ist gegen eine aeltere `transformers`-API
  geschrieben. Verifiziert lauffaehig mit `transformers==4.46.3` (ephemere
  `uv run --with`-Umgebung, siehe `live-verification.json`). Ein produktiver
  Einbau muesste entweder das Repo-Pin fuer diesen einen Pfad unterlaufen
  (separate venv/Prozess) oder auf eine kompatible HHEM-Revision warten — ein
  zusaetzlicher Kostenpunkt, unabhaengig von der Precision/Recall-Zahl oben.
* **`trust_remote_code=True`**: HHEM liefert eigenen Python-Inferenzcode mit,
  der beim Laden ausgefuehrt wird (kein reines Gewichte-Artefakt). Fuer ein
  Investigations-Skript unter `evals/` mit manuellem Opt-in vertretbar; fuer
  einen automatisierten Produktivpfad waere das ein zusaetzlicher
  Sicherheits-Abwaegungspunkt.
* **Synthetischer Datensatz, n=32.** Die Zahlen sind ein Signal, keine
  belastbare Systemvalidierung — insbesondere die FPR-Aussage (siehe oben).
* **Kein Zielsystem.** `quote-fidelity-auditor` (#523) ist aktuell revertet;
  ein Vorfilter ohne Richter-Subagent dahinter hat keinen Produktiv-Zweck.

## Empfehlung

**Empfehlung: verwerfen** — fuer einen produktiven Einbau zum jetzigen
Zeitpunkt, gestuetzt auf:

1. **HHEM-2.1-Open** faellt klar durch: Recall 0.125 bei DE/EN-Crosslingual
   (Model-Card bestaetigt englisch-zentriertes Training) UND aktuell technisch
   inkompatibel mit dem gepinnten `transformers`-Stack dieses Repos.
2. **mDeBERTa-v3-XNLI** zeigt ein vielversprechendes Signal (Precision 1.00,
   Recall 0.81, 0 falsche Freigaben auf 32 synthetischen Cases, MIT-Lizenz,
   ~39 ms/Paar auf CPU) — aber: kein produktives Zielsystem (#523 revertiert),
   kein realer Datensatz, und n=16 pro Klasse ist zu klein fuer eine
   FPR-Zusage. Ein Einbau *jetzt* waere verfrueht.

Falls #523 wieder aufgesetzt wird, ist mDeBERTa-v3-XNLI der einzig
ernstzunehmende Kandidat fuer ein Folge-Issue — mit realen (nicht
synthetischen) DE-Kapitel/EN-Quote-Paaren und einer belastbaren
FPR-Stichprobengroesse als Voraussetzung.

## Dateien

| Datei | Inhalt |
| --- | --- |
| `cases.json` | 32 synthetische Cases (`cases[]`-Format nach `evals/SCHEMA.md`), 16 `faithful` / 16 `verzerrend` (je 4 pro Subtyp: `overstated`, `context-stripped`, `polarity-flip`, `unsupported`) |
| `runner.py` | Lazy-laedt beide Modelle, berechnet Precision/Recall/Accuracy/Latenz; `run_eval_cases()` ohne `sys.exit`/Kernpfad-`print` |
| `live-verification.json` | Realer Eval-Lauf (Modell-/`transformers`-Versionen, Zeitstempel, Ergebnis je Case) — nachfahrbares Artefakt, Muster wie `evals/publisher-fetchers/live-verification.json` |
| `README.md` | Diese Datei |

## Ausfuehren

```bash
cd /path/to/academic-research

# Struktur-Checks (immer, ohne Netz):
uv run pytest tests/evals/test_nli_prefilter_evals.py -q

# Realer Modell-Lauf (Netz + ~1 GB Download, Repo-Pin transformers==5.14.1 —
# HHEM schlaegt darunter fehl, siehe Risiken):
RUN_LIVE_NLI_PREFILTER=1 uv run pytest tests/evals/test_nli_prefilter_evals.py -q

# CLI-Report direkt:
RUN_LIVE_NLI_PREFILTER=1 uv run python evals/524-nli-prefilter/runner.py

# HHEM lauffaehig machen (ephemere Umgebung, umgeht das Repo-Pin lokal):
RUN_LIVE_NLI_PREFILTER=1 uv run --with "transformers==4.46.3" --with torch \
  python evals/524-nli-prefilter/runner.py
```

## Case-Format

```json
{
  "id": "np-01",
  "claim_lang": "de",
  "context_lang": "en",
  "verzerrend_type": null,
  "chapter_claim": "Deutsche Kapitelbehauptung (Hypothesis)",
  "context_before": "Englischer Kontext vor dem Zitat",
  "verbatim": "Englisches Zitat (Premise-Kern, Vault-Quote-Format)",
  "context_after": "Englischer Kontext nach dem Zitat",
  "label": "faithful"
}
```

| Feld | Werte |
| --- | --- |
| `label` | `"faithful"` oder `"verzerrend"` |
| `verzerrend_type` | bei `label: "verzerrend"`: `"overstated"` \| `"context-stripped"` \| `"polarity-flip"` \| `"unsupported"` (buendelt die vier Negativ-Verdicts aus dem `quote-fidelity-auditor`-Schema, #523); sonst `null` |
| `claim_lang` / `context_lang` | immer `"de"` / `"en"` in diesem Datensatz (Kernfrage des Issues) |
