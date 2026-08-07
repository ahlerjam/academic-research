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
>
> **Update #592 (04.08.2026):** Die Validierung an echtem Zitatmaterial liegt
> vor — siehe [„Validierung an echtem Zitatmaterial (#592)"](#validierung-an-echtem-zitatmaterial-592)
> unten. Der Vorfilter (`academic_vault/nli_prefilter.py`) ist implementiert,
> per Konfiguration abschaltbar und im Auslieferungsstand zunächst AUS.
>
> **Update #717 (07.08.2026):** Der Scan ist produktiv angebunden
> (`hooks/nli-quote-scan.mjs`, `PostToolUse`) und läuft als **Detektor statt
> Filter**: Er entfernt kein Zitat mehr aus dem Prüfpfad, sondern meldet
> verdächtige zusätzlich. Damit fällt das Hauptargument gegen Default-an weg
> (siehe [„Einschalt-Empfehlung"](#einschalt-empfehlung-ac6-erledigt-mit-717)),
> und der Auslieferungsstand ist **AN**
> (`config/parallel_agents.json` → `nli_prefilter_enabled: true`).
> Bedienung und gemessene Laufzeit: `docs/reference/hooks.md`, Abschnitt
> „NLI-Zitatscan".

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

## Validierung an echtem Zitatmaterial (#592)

Issue #592 macht die Validierung an echtem Zitatmaterial zur Vorbedingung
fuers Scharfschalten des Vorfilters: 32 KONSTRUIERTE Faelle (oben) sind ein
Signal, kein Systembeleg. `real-cases.json` enthaelt darum 60 Zitat-Kapitel-
Paare, deren `verbatim`-Feld ein woertliches, kurzes Fair-Use-Zitat
(< 150 Zeichen) aus einem real veroeffentlichten, oeffentlich zugaenglichen
arXiv-Paper ist — 15 Paper, je 2 Zitat-Stellen, je Stelle eine treue und eine
bewusst verzerrte deutsche Kapitelbehauptung. Jeder Case traegt in `source`
Titel, arXiv-ID und URL; die Zitate wurden per WebFetch gegen den
Originaltext verifiziert (kurze Fair-Use-Ausschnitte statt Volltext-
Reproduktion — WebFetch verweigert Volltext-Abstracts aus Urheberrechtsgruenden,
was hier bewusst genutzt wird: die Ausschnitte bleiben unter 150 Zeichen).
`context_before`/`context_after` bleiben leer — nur das woertliche Zitat
selbst ist als real verifiziert dokumentiert, ein erfundener Kontext waere
false Praezision.

**Nur `MDebertaScorer`** laeuft gegen dieses Set (`run_real_validation.py`) —
HHEM-2.1-Open ist laut Empfehlung oben bereits verworfen, ein zweiter Lauf
gegen echtes Material haette daran nichts geaendert.

### Ergebnis (Lauf vom 04.08.2026, `real-validation-results.json`)

| n | TP | FP | FN | TN | Precision | Recall | Accuracy | FP-Rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 60 (30 faithful / 30 verzerrend) | 23 | 0 | 7 | 30 | 1.000 | 0.767 | 0.883 | 0.000 |

**FP = 0 auf 30 `verzerrend`-Faellen ist kein Beleg fuer FP = 0 in der
Produktion.** Rule-of-Three-Vorbehalt (wie in #524): bei 0 Fehlern aus 30
Versuchen liegt die plausible Obergrenze der realen FPR bei rund 3/30 ≈ 10 %.
Das ist enger als der Vorbehalt aus #524 (bis ~19 % bei n=16), aber weiterhin
kein Nullbeleg. Recall sinkt leicht gegenueber den 32 konstruierten Faellen
(0.767 vs. 0.812) — plausibel, weil `real-cases.json` KEINEN konstruierten
`context_before`/`context_after` mitliefert (siehe oben) und die Modellentscheidung
damit ausschliesslich auf dem kurzen Verbatim-Ausschnitt beruht, waehrend
`cases.json` zusaetzlichen synthetischen Kontext liefert.

### Einschalt-Empfehlung (AC6) — erledigt mit #717

**Stand #592 (Default AUS).** Die Empfehlung lautete: nicht scharfschalten,
obwohl FP = 0 gemessen wurde.

1. **FP = 0 ist ein Signal, kein Beweis** — die Rule-of-Three-Grenze (~10 %)
   ist real. Ein durchgewunkenes verzerrtes Zitat bleibt unbemerkt in der
   Arbeit stehen; das ist der teurere Fehler als ein unnoetiger Sonnet-Lauf.
2. **`real-cases.json` deckt vier Verzerrungs-Subtypen zu je 7-8 Faellen ab,
   aber nur 15 Quell-Paper aus einer einzigen Domaene** (ML/NLP-Paper,
   englischsprachig). Reale Kapitel zitieren breiter gestreute Quellen
   (Methodik-, Sozial-, Geisteswissenschaften) — die Uebertragbarkeit auf
   diese Bandbreite ist mit diesem Set nicht geprueft.

**Stand #717 (Default AN).** Punkt 1 war kein Argument gegen den Scan an sich,
sondern gegen die damalige **Filter**-Semantik: ein Fehlurteil entfernte ein
Zitat dauerhaft aus dem Pruefpfad. Seit #717 laeuft der Scan als **Detektor** —
er ueberspringt nichts, sondern meldet zusaetzlich. Ein Fehlurteil kostet
seither hoechstens eine ausgebliebene Meldung und stellt damit exakt den
Zustand her, der ohne Scan ohnehin gilt. Die Rule-of-Three-Grenze bleibt als
Aussage ueber die Erkennungsguete richtig, taugt aber nicht mehr als Argument
gegen Default-an.

Punkt 2 gilt unveraendert weiter: die Uebertragbarkeit auf andere Fachdomaenen
ist ungeprueft. Er begruendet nicht mehr Default-aus, sondern die Einordnung
jeder Meldung als **Verdacht, nicht als Urteil** — die inhaltliche Entscheidung
bleibt beim `quote-fidelity-auditor`.

Abschalten (Vorrang: Env > Configdatei > Default an):
`ACADEMIC_RESEARCH_NLI_PREFILTER=0` oder `nli_prefilter_enabled: false` in
`config/parallel_agents.json`.

Offen als Folgearbeit: ein zweiter Validierungslauf gegen ein breiter
gestreutes, groesseres Set (Zielgroesse dreistellig, mehrere Fachdomaenen).

### Dateien (Validierung)

| Datei | Inhalt |
| --- | --- |
| `real-cases.json` | 60 ECHTE Zitat-Kapitel-Paare (Quelle je Case in `source`) |
| `run_real_validation.py` | Fuehrt `MDebertaScorer` gegen `real-cases.json`, schreibt `real-validation-results.json` |
| `real-validation-results.json` | Ergebnis des Laufs vom 04.08.2026 (Modell-/`transformers`-Version, TP/FP/FN/TN, `fp_examples`, Case-Details) |

## Erweitertes Goldset (#721): 186 Fälle, 30 echte Paper, acht Fächer

Issue #592 nannte die Lücke selbst: `real-cases.json` deckt „nur 15
Quell-Paper aus einer einzigen Domäne (ML/NLP-Paper, englischsprachig)" ab.
Issue #721 schließt sie mit **186 zusätzlichen Fällen aus 30 echten
Open-Access-Papern über acht Fachrichtungen** (Medizin, Public Health,
Psychologie, Pädagogik, Soziologie, Wirtschaft, Umwelt, Informatik) —
zusammen mit den 92 bestehenden Fällen (32 aus #524 + 60 aus #592) die
Grundlage der 278-Fälle-Modellentscheidung in Issue #720.

**Labels folgen einer Konstruktionsregel, nicht einem Einzelurteil.** Jede
`verzerrend`-Variante entsteht durch eine feste Transformation der treuen
Wiedergabe — nicht durch eine gesonderte Einschätzung:

| Verzerrungstyp | Regel |
| --- | --- |
| `overgeneralization` | Quantor oder Geltungsbereich ausweiten |
| `condition-stripped` | Bedingung, Population oder Einschränkung weglassen |
| `causal-overreach` | Assoziation als Kausalität darstellen |
| `magnitude-inflation` | Effektgröße über den berichteten Wert hinaus steigern |
| `significance-flip` | nicht signifikanten Befund als Wirkung darstellen |

Balance: 92 `faithful` / 94 `verzerrend`. Jeder Fall trägt in `source.doi`
die DOI seines Quellpapers (Rückführbarkeit). Ausführlicher Eval-Report samt
der reproduzierten #720-Schwellenkurve und der methodischen Grenze
(konstruierte Verzerrungen ≠ im Feld beobachtete):
[`docs/evals/2026-08-06-extended-nli-goldset-721.md`](../../docs/evals/2026-08-06-extended-nli-goldset-721.md).

### Dateien (erweitertes Goldset)

| Datei | Inhalt |
| --- | --- |
| `set_med.json` / `set_soz.json` | Rohdaten der 186 Fälle (unverändert aus den Issue-#721-Kommentaren) |
| `picks.json` | 30 Paper mit Quellsätzen, Kontext, Feld, DOI, Titel, Jahr |
| `fetch_abstracts.py` | Ruft Open-Access-Abstracts über die OpenAlex-API ab |
| `pick_sentences.py` | Wählt aus jedem Abstract die zitierfähigen Ergebnissätze |
| `run_big.py` | 278-Fälle-A/B-Vergleich `mDeBERTa-v3-XNLI` vs. `bge-m3-zeroshot-v2.0` (Grundlage von #720) |
| `bidir.py` | Verworfener bidirektionaler NLI-Ansatz (dokumentarisch aufbewahrt, siehe #720) |
| `build_extended_cases.py` | Baut `extended-cases.json` aus den drei Rohdateien |
| `extended-cases.json` | Generiertes Ergebnis: 186 Fälle im `real-cases.json`-Feldformat |

### Ausführen (erweitertes Goldset)

```bash
# Struktur-Checks (immer, ohne Netz):
uv run pytest tests/evals/test_nli_prefilter_evals.py -q

# Erweitertes Set neu generieren:
python3 evals/524-nli-prefilter/build_extended_cases.py

# Live-Reproduktion der #720-Schwellenkurve (Netz + Modell-Download):
RUN_LIVE_NLI_PREFILTER=1 uv run pytest tests/evals/test_nli_prefilter_evals.py -q -k threshold_curve
```

## Dateien

| Datei | Inhalt |
| --- | --- |
| `cases.json` | 32 synthetische Cases (`cases[]`-Format nach `evals/SCHEMA.md`), 16 `faithful` / 16 `verzerrend` (je 4 pro Subtyp: `overstated`, `context-stripped`, `polarity-flip`, `unsupported`) |
| `runner.py` | Lazy-laedt beide Modelle, berechnet Precision/Recall/Accuracy/Latenz; `run_eval_cases()` ohne `sys.exit`/Kernpfad-`print` (importiert `MDebertaScorer` aus `academic_vault/nli_prefilter.py`, Issue #592) |
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

# Validierung an ECHTEM Zitatmaterial (#592, 60 reale Paare, nur mDeBERTa,
# Netz + Modell-Download beim ersten Lauf):
uv run python evals/524-nli-prefilter/run_real_validation.py
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
