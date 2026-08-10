# Hilft ein inhaltlicher Kontextsatz gegenüber Metadaten? (#785, Epic #710-C)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Rohdaten liegen daneben in
> [`2026-08-08-context-ablation-710-live-results.json`](2026-08-08-context-ablation-710-live-results.json)
> und werden von `tests/test_issue_710_context_ablation.py` gegen einen
> frischen Lauf geprüft (nicht im CI-Job `retrieval-goldset` verdrahtet —
> siehe [Grenzen](#grenzen)).
>
> **Datenstand 2026-08-10 (#800/#809).** Das #708-Goldset wurde von 26 auf 60
> Queries (11 auf 21 Dokumente, 30 auf 61 Chunks) verbreitert; die
> Kontextsatz-Fixture (`tests/fixtures/context_sentences_710/`) wurde
> daraufhin komplett neu erzeugt (21 echte `claude`-CLI-Aufrufe für die
> Kontextsätze, danach die Vektoren neu gerechnet). Der Report unten
> beschreibt durchgehend diesen neuen Lauf auf 60 Queries — der ursprüngliche
> 26-Query-Lauf vom 2026-08-08 ist nicht mehr Gegenstand dieses Dokuments;
> seine Zahlen sind vollständig ersetzt, nicht nur ergänzt. **Der Befund
> kippt dabei:** Auf 26 Queries trug der Abstand `model_context` gegenüber
> `metadata_context` signifikant (Gesamtmittel und `language-gap`-Teilmenge).
> Auf dem breiteren 60-Query-Goldset trägt **kein einziger** der vier
> Arm-Vergleiche mehr — weder im Gesamtmittel noch in einer der drei
> Teilmengen. Siehe [Gesamtergebnis](#gesamtergebnis) und
> [Empfehlung](#empfehlung).

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-10 · Fixture neu erzeugt für [#800](2026-08-10-chunk-goldset-widening-800.md)/#809
(ursprünglicher Lauf 2026-08-08 auf dem 26er-Goldset) · **Goldset:** bge-m3-Fassung
des Chunk-Goldsets aus [#708](retrieval-chunk-goldset-708.md)/[#731](2026-08-08-embedding-candidates-731.md),
verbreitert durch #800, `tests/fixtures/embedding_candidates_731/bge-m3/goldset.json`,
21 Dokumente / 61 Chunks / 60 Queries · **Embedding:** `BAAI/bge-m3` (1024d,
produktiver Default seit [#732](2026-08-08-embedding-model-decision-732.md)) ·
**Kontextsätze:** `claude -p --model sonnet --output-format json`, eingeloggte
OAuth-Sitzung, kein API-Schlüssel

## Fragestellung

AC2 aus Epic #710: Der produktive Kontextsatz ist heute ein deterministischer
Metadaten-Satz (`chunking.default_context_sentence()`, z. B. *„Dieser Abschnitt
stammt aus 'Einleitung' (Seite 1-2, Chunk 0)."*) — immer deutsch, ohne
inhaltlichen Bezug zum Chunk. Der produktive Schreibweg (#783/#784, inzwischen
gebaut und in `commands/fetch.md` verdrahtet) erzeugt stattdessen einen
echten, modellgeschriebenen inhaltlichen Satz. Dieser Lauf beantwortet die
vorgelagerte Frage weiterhin rein hermetisch, jetzt auf dem breiteren
#800-Goldset: **Hilft ein inhaltlicher Satz beim Retrieval überhaupt — und
wenn ja, wodurch: Inhalt oder Sprache?**

Der Metadaten-Satz ist immer deutsch. Ein inhaltlicher Satz in Chunk-Sprache
unterscheidet sich von ihm deshalb gleichzeitig in **zwei** Dimensionen —
Inhalt und Sprache. Um das zu entwirren, misst dieser Lauf einen vierten Arm:
denselben Modellsatz, aber auf Deutsch erzwungen. Der Sprach-Confound ist damit
**isoliert, nicht nur vermerkt** — der optionale vierte Arm aus dem
Plan-Kommentar wurde gebaut.

## Basis: die bge-m3-Fassung, nicht die e5-Fassung

Das #708-Goldset existiert in mehreren Embedding-Fassungen (#731,
`tests/fixtures/embedding_candidates_731/<modell>/`). Dieser Lauf verwendet
**ausschließlich die bge-m3-Fassung**, weil [#732](2026-08-08-embedding-model-decision-732.md)
`BAAI/bge-m3` zum produktiven Default gemacht hat — gegen die ältere
e5-Fassung (`tests/fixtures/retrieval_goldset_chunks_708/`) zu messen würde
einen Effekt auf einem Modell belegen, das im Betrieb nicht mehr läuft.

## Die vier Arme

| Arm | Was eingebettet wird |
|---|---|
| `no_context` | nur `chunk_text`, kein Kontextsatz |
| `metadata_context` | der Produktionszustand: `context_sentence + " " + chunk_text`, **unverändert aus dem #731-Goldset übernommen** (keine Neuerzeugung) |
| `model_context` | ein echter, modellgeschriebener inhaltlicher Satz (≤ 25 Wörter) in der Sprache des Chunks + `chunk_text` |
| `model_context_de` | **derselbe Inhalt** wie `model_context`, aber auf Deutsch erzwungen, + `chunk_text` — isoliert den Sprach-Confound |

Alle vier Arme laufen über denselben echten Suchpfad wie #708/#729/#731: die
Vektoren gehen über `VaultDB.add_chunk_embedding()` in eine Wegwerf-DB und
werden mit `VaultDB.knn_chunks(k=10)` gerankt. Ausgewertet wird auf
**Chunk-Ebene** (die zurückgegebenen IDs sind `doc_id#chunk_index`, keine
Paper-Aggregation) — wie im gesamten #708/#731-Familienstamm.

## Kontrolltest: reproduziert `metadata_context` die #731-Zahlen?

**Ja, exakt.** `metadata_context` übernimmt für Chunks **und** Queries
unverändert die bereits eingecheckten #731-bge-m3-Vektoren (kein erneutes
Embedding — `build_context_sentences_710.py --stage vectors` kopiert sie).
Der Kontrolltest vergleicht den `metadata_context`-Arm dieses Harnesses gegen
einen **frischen** Lauf von `run_embedding_candidates_731.evaluate_candidate()`
auf derselben Fixture (keine im Report vorgeschriebene Zahl):

| Metrik | dieser Harness | #731-Referenz (frisch) | Δ |
|---|---:|---:|---:|
| Recall@10 | 0,9750 | 0,9750 | 0,0000000000 |
| nDCG@10 | 0,8104 | 0,8104 | 0,0000000000 |
| MRR | 0,7621 | 0,7621 | 0,0000000000 |

Alle drei Metriken, alle drei Teilmengen und die vollständige Rangfolge jeder
einzelnen Query stimmen bis auf Gleitkomma-Rundung (`< 1e-9`) überein
(`test_metadata_context_reproduces_731_numbers_exactly`,
`test_control_check_compares_against_a_fresh_731_run`). Dieser Harness misst
also denselben Suchpfad wie #731 — jeder unten gemeldete Unterschied ist ein
Befund über Kontextsätze, kein Artefakt eines anderen Codepfads.

## Gesamtergebnis

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 0,9750 | 0,8136 | 0,7660 |
| `metadata_context` (Produktionszustand) | 0,9750 | 0,8104 | 0,7621 |
| `model_context` | 0,9750 | 0,8068 | 0,7615 |
| `model_context_de` | 0,9583 | 0,8176 | 0,7803 |

Recall@10 ist auf dem breiteren Goldset **nicht mehr über alle vier Arme
identisch** — anders als im ursprünglichen 26-Query-Lauf. `no_context`,
`metadata_context` und `model_context` liegen gleichauf bei 0,9750;
`model_context_de` fällt auf 0,9583 (verliert netto eine Query gegenüber den
anderen drei Armen, siehe [Teilmengen](#teilmengen-das-gesamtmittel-verdeckt-den-interessanten-fall)).
Das Goldset bleibt mit 21 Dokumenten gegenüber `k=10` weiterhin überwiegend
gesättigt (derselbe Effekt wie in
[#708](retrieval-chunk-goldset-708.md#grenzen), [#729](2026-08-08-chunk-fusion-ablation-729.md#grenzen)) —
die meisten Recall-Unterschiede sind Ranggewinne/-verluste innerhalb bereits
gefundener Treffer, nicht neue Treffer.

**Der zentrale Befund kippt gegenüber dem 26-Query-Lauf.** Dort gewann
`model_context` gegenüber `metadata_context` signifikant (+0,0626 nDCG@10,
+0,0898 MRR im Gesamtmittel, CI schloss die Null aus). Auf 60 Queries ist der
Punktschätzer nicht nur kleiner, sondern **negativ**: `model_context` liegt
im Gesamtmittel leicht **unter** `metadata_context` (nDCG@10: −0,0036, MRR:
−0,0006) — und **kein** Vergleich trägt mehr nach der vorab festgelegten
Regel (95-%-Bootstrap-Intervall schließt die Null nicht ein):

| Vergleich | Δ Recall@10 | Δ nDCG@10 | Δ MRR |
|---|---:|---:|---:|
| `model_context` − `no_context` | +0,0000 | −0,0069 (n. s., CI [−0,0524; +0,0389]) | −0,0045 (n. s., CI [−0,0606; +0,0513]) |
| `model_context` − `metadata_context` | +0,0000 | −0,0036 (n. s., CI [−0,0549; +0,0521]) | −0,0006 (n. s., CI [−0,0642; +0,0685]) |
| `model_context_de` − `metadata_context` | −0,0167 (n. s., CI [−0,0833; +0,0333]) | +0,0073 (n. s., CI [−0,0436; +0,0578]) | +0,0181 (n. s., CI [−0,0435; +0,0797]) |
| `model_context` − `model_context_de` | +0,0167 (n. s., CI [0,0000; +0,0500]) | −0,0108 (n. s., CI [−0,0491; +0,0244]) | −0,0187 (n. s., CI [−0,0689; +0,0260]) |

„n. s." = nicht signifikant nach der Entscheidungsregel unten (Nullwert im
95-%-Intervall enthalten). Methode: gepaarter Bootstrap über die Queries,
10 000 Resamples, Seed 785, 95-%-Perzentilintervall
(`scripts/eval/run_context_ablation_710.py::_scope_delta`, dieselbe Formel wie
in [#731](2026-08-08-embedding-candidates-731.md)).

**Wichtig für die Lesart:** Alle vier Punktschätzer im Gesamtmittel liegen
nahe beieinander (0,8068–0,8176 nDCG@10; 0,7615–0,7803 MRR) und keiner der
sechs möglichen Richtungswechsel ist mit `n=60` von der Nullhypothese zu
unterscheiden. Das ist dasselbe Muster wie in [#729](2026-08-08-chunk-fusion-ablation-729.md):
ein Nullbefund im Gesamtmittel, keine überraschende Umkehr.

## Teilmengen: das Gesamtmittel verdeckt den interessanten Fall

Das Gesamtmittel bleibt auf 21 Dokumenten weitgehend gesättigt (wie in #729
dokumentiert). Die drei Teilmengen (`same-language`/`language-gap`/
`cross-language`) sind deshalb **getrennt** ausgewertet, nicht nur als
Durchschnitt — und sind mit #800 deutlich größer als im 26-Query-Lauf
(`language-gap`: 6 → 14 Queries, `cross-language`: 2 → 5 Queries).

### `language-gap` (14 Queries — deutsche Umgangssprache auf englischen Fachtext)

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 0,9286 | 0,5672 | 0,4556 |
| `metadata_context` | 0,9286 | 0,5361 | 0,4223 |
| `model_context` | 0,9286 | 0,5363 | 0,4221 |
| `model_context_de` | 0,8571 | 0,5820 | 0,5054 |

| Vergleich | Δ nDCG@10 | Δ MRR |
|---|---:|---:|
| `model_context` − `metadata_context` | +0,0002 (n. s., CI [−0,1260; +0,1471]) | −0,0002 (n. s., CI [−0,1402; +0,1679]) |
| `model_context_de` − `metadata_context` | +0,0459 (n. s., CI [−0,0963; +0,1900]) | +0,0831 (n. s., CI [−0,0723; +0,2470]) |
| `model_context` − `model_context_de` | −0,0456 (n. s., CI [−0,1859; +0,0831]) | −0,0833 (n. s., CI [−0,2619; +0,0774]) |

**Der im 26-Query-Lauf klarste Effekt trägt hier nicht mehr.** Damals gewann
`model_context` gegenüber `metadata_context` signifikant (+0,1804 nDCG@10,
+0,2361 MRR, CI schloss die Null aus). Auf 14 Queries liegt der
`model_context`-Punktschätzer praktisch bei null Differenz zu
`metadata_context`, mit einem entsprechend breiten Konfidenzintervall.
Recall@10 ist zudem nicht mehr für alle Arme gleich:

| Query | `no_context` | `metadata_context` | `model_context` | `model_context_de` |
|---|---:|---:|---:|---:|
| q-gap-01 | 4 | 2 | 3 | 1 |
| q-gap-02 | 2 | 6 | 1 | 2 |
| q-gap-03 | 1 | 2 | 4 | 1 |
| q-gap-04 | 9 | 7 | 10 | NF |
| q-gap-05 | 5 | 2 | 2 | 2 |
| q-gap-06 | 5 | 9 | 7 | 7 |
| q-gap-07 | NF | NF | 4 | 6 |
| q-gap-08 | 1 | 1 | 1 | 1 |
| q-gap-09 | 1 | 1 | 1 | 1 |
| q-gap-10 | 1 | 1 | 2 | 2 |
| q-gap-11 | 5 | 8 | NF | NF |
| q-gap-12 | 2 | 3 | 2 | 1 |
| q-gap-13 | 6 | 3 | 6 | 6 |
| q-gap-14 | 4 | 5 | 6 | 10 |

(„NF" = Zielchunk nicht in den Top-10, Rang sonst die Position des ersten
relevanten Treffers.) `model_context` gewinnt q-gap-07 gegenüber
`no_context`/`metadata_context` (Zielchunk taucht überhaupt erst auf), verliert
dafür q-gap-11 (vorher gefunden, jetzt nicht mehr) — im Saldo bleibt Recall@10
für `model_context` bei 13/14, identisch zu `no_context`/`metadata_context`,
aber mit anderer Query-Zusammensetzung. `model_context_de` verliert zusätzlich
q-gap-04 und landet bei 12/14. Das Bild ist also kein einheitlicher Gewinn wie
im 26-Query-Lauf, sondern ein **Austausch**: die Fälle, die durch einen
inhaltlichen Satz gewinnen, werden durch andere Fälle aufgewogen, die dadurch
verlieren.

### `same-language` (41 Queries)

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 0,9878 | 0,9209 | 0,9045 |
| `metadata_context` | 0,9878 | 0,9285 | 0,9122 |
| `model_context` | 0,9878 | 0,9123 | 0,8972 |
| `model_context_de` | 0,9878 | 0,9137 | 0,8974 |

Recall@10 ist mit 0,9878 (40/41) über alle vier Arme identisch — derselbe
strukturelle Miss (`q-de-07`) tritt in jedem Arm auf, unabhängig vom
Kontextsatz. Anders als im 26-Query-Lauf liegt `metadata_context` hier sogar
knapp **vor** `model_context` (nDCG@10 0,9285 gegen 0,9123); keiner der
Abstände trägt (siehe Deltas oben, same-language-Zeilen).

### `cross-language` (5 Queries — englische Frage auf deutschen Text)

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 1,0000 | 0,6236 | 0,5000 |
| `metadata_context` | 1,0000 | 0,6097 | 0,4833 |
| `model_context` | 1,0000 | 0,6985 | 0,6000 |
| `model_context_de` | 1,0000 | 0,6897 | 0,5900 |

**Anders als im 26-Query-Lauf sind die vier Arme hier nicht mehr identisch.**
Mit nur zwei Queries im ursprünglichen Goldset lieferten alle vier Arme exakt
dieselbe Rangfolge; mit fünf Queries zeigt sich Varianz:

| Query | `no_context` | `metadata_context` | `model_context` | `model_context_de` |
|---|---:|---:|---:|---:|
| q-cross-01 | 2 | 2 | 2 | 2 |
| q-cross-02 | 1 | 1 | 1 | 1 |
| q-cross-03 | 2 | 6 | 1 | 1 |
| q-cross-04 | 6 | 4 | 4 | 5 |
| q-cross-05 | 3 | 2 | 4 | 4 |

Recall@10 bleibt bei 1,0 für alle Arme (jede Variante findet den Zielchunk in
den Top-10), aber die Ränge streuen deutlich (q-cross-03: Rang 6 bei
`metadata_context`, Rang 1 bei `model_context`/`model_context_de`). Der
Punktschätzer für `model_context` liegt über `metadata_context` (+0,0887
nDCG@10, +0,1167 MRR), aber mit `n=5` ist das Konfidenzintervall so breit
(CI nDCG@10 [−0,1202; +0,3863]), dass es die Null einschließt — kein Beleg,
nur eine Beobachtung, siehe [Grenzen](#grenzen).

## Kosten und Latenz

Zwei getrennt gemessene Posten, wie im #733-Vorbild:

| Posten | n | p50 | p95 | Mittelwert |
|---|---:|---:|---:|---:|
| Kontextsatz-Erzeugung (`claude -p` je Dokument) | 21 | 19 179,9 ms | 27 301,6 ms | 19 177,7 ms |
| bge-m3-Embedding je Text (CPU) | 243 | 163,9 ms | 179,0 ms | 133,4 ms |

Gesamtkosten der Kontextsatz-Erzeugung laut `usage`-Feldern der CLI: **3,16 USD**
für 21 Dokumente / 61 Chunks (`sentences.json::meta.usage_totals`,
`total_cost_usd`). Ein Aufruf pro Dokument statt pro Chunk (alle Chunks eines
Dokuments in einem Prompt) hält die Kosten trotz Cache-Erstellung je Dokument
in diesem Rahmen — bei 61 Chunks über 21 Dokumente sind das rund 0,05 USD je
Chunk, damit im selben Rahmen wie im ursprünglichen 11-Dokumente-Lauf. Für ein
reales Paper mit deutlich mehr Chunks ist das **kein** verlässlicher
Hochrechnungsfaktor (siehe [Grenzen](#grenzen)): die realen Kosten für den
produktiven Schreibweg misst #710-B (#784), nicht dieses Issue.

## Kontrollergebnis: Sprach-Confound isoliert, nicht nur vermerkt

Der optionale vierte Arm (`model_context_de`) wurde **gebaut**, nicht wegen
Aufwands weggelassen — das bleibt richtig, unabhängig vom Ausgang. Anders als
im 26-Query-Lauf gibt es auf dem breiteren Goldset aber **gar keinen
signifikanten Effekt mehr, den ein Sprach-Confound erklären müsste**:
`model_context` gegenüber `metadata_context` trägt nicht (weder Inhalt noch
Sprache zeigen einen belastbaren Vorteil), und `model_context` gegenüber
`model_context_de` (isoliert die Sprache bei gleichem Inhalt) trägt ebenfalls
nicht. Die einzige auffällige Verschiebung ist der Recall-Rückgang von
`model_context_de` in der `language-gap`-Teilmenge (0,9286 → 0,8571, siehe
oben) — ein Verlust, kein Gewinn, und mit `n=14` nicht von Zufall zu
unterscheiden. **Der Sprach-Confound bleibt methodisch sauber isoliert, aber
es gibt auf diesem Goldset nichts mehr zu erklären:** weder Inhalt noch
Sprache liefern einen Effekt, der über das Bootstrap-Intervall hinausgeht.

## Empfehlung

**Historischer Hinweis:** Der produktive Schreibweg (#783/#784) war zum
Zeitpunkt dieses Datenstands bereits gebaut und in `commands/fetch.md`
verdrahtet — diese Aktualisierung ist deshalb keine Go/No-Go-Entscheidung
mehr, sondern eine ehrliche Nachmessung der ursprünglichen Empfehlung.

Der 26-Query-Lauf empfahl den Bau mit Vorbehalt, gestützt auf einen
signifikanten, wenn auch kleinen positiven Effekt. **Dieser Effekt trägt auf
dem breiteren #800-Goldset nicht mehr** — weder im Gesamtmittel noch in einer
der drei Teilmengen, in keiner der vier Arm-Paarungen. Das ändert die
ursprüngliche Empfehlung im Rückblick:

1. Der ursprüngliche Befund war mit `n=26` (bzw. `n=6` in der informativen
   Teilmenge) vermutlich zu klein, um verlässlich zu sein — genau die Sorge,
   die im „Grenzen"-Abschnitt des ursprünglichen Laufs bereits benannt war
   („Ein größeres Goldset könnte hier zwischen ‚Inhalt trägt' und
   ‚Signifikanz kippt nur an der Stichprobengröße' unterscheiden").
2. Auf 60 Queries ist das Bild ein Nullbefund wie in #729: die Punktschätzer
   liegen nah beieinander, keine Richtung ist von Null zu unterscheiden.
3. Recall@10 bleibt in keinem Arm verbessert — in `model_context_de` sogar
   leicht verschlechtert (`language-gap`-Teilmenge).

**Praktische Konsequenz für den bereits gebauten Schreibweg:** Dieser Lauf
liefert keinen empirischen Beleg mehr dafür, dass inhaltliche Kontextsätze
das Retrieval messbar verbessern — er widerlegt es aber auch nicht (die
Konfidenzintervalle sind breit genug, um einen kleinen Effekt in beide
Richtungen zuzulassen). Ein Rückbau des Schreibwegs ist mit diesem Lauf
allein nicht zu begründen; eine erneute, härtere Prüfung (z. B. an einem noch
größeren oder realen Korpus statt synthetischer Goldset-Dokumente) wäre der
saubere nächste Schritt, falls die Frage operativ relevant wird.

## Aufbau des Laufs

```
scripts/eval/build_context_sentences_710.py   Live-Generator (zwei Stufen, beide opt-in)
scripts/eval/run_context_ablation_710.py      hermetischer Messlauf, vier Arme
tests/fixtures/context_sentences_710/
├── sentences.json   61 Kontextsatz-Paare (sentence + sentence_de), usage/Latenz je Dokument
└── vectors.json     4 Arme × (61 Chunk- + 60 Query-Vektoren, 1024d), manifest_sha256
```

**Kontextsätze erzeugen** (21 `claude -p`-Aufrufe, ≈ 7 Minuten, ≈ 3,16 USD):

```bash
VAULT_CONTEXT_LIVE_TRANSFORM=1 uv run python \
    scripts/eval/build_context_sentences_710.py --stage sentences
```

**Vektoren erzeugen** (lädt `BAAI/bge-m3`, ≈ 2,3 GB, embeddet live; `metadata_context`
wird dabei NICHT neu embedded, sondern unverändert aus #731 übernommen):

```bash
VAULT_E5_LIVE_TEST=1 uv run python \
    scripts/eval/build_context_sentences_710.py --stage vectors
```

Editiert jemand einen Satz in `sentences.json`, ohne die Vektoren neu zu
rechnen, bricht der Messlauf mit Exit 2 ab (`manifest_sha256`-Prüfung über
alle vier Arme), statt eine still verschobene Metrik zu melden.

**Messlauf** (hermetisch, kein Netz, kein Modell):

```bash
uv run python scripts/eval/run_context_ablation_710.py
uv run python scripts/eval/run_context_ablation_710.py \
    --check-against docs/evals/2026-08-08-context-ablation-710-live-results.json
```

## Grenzen

- **Der zentrale Effekt aus dem 26-Query-Lauf hat sich als nicht robust
  erwiesen.** Er trug dort signifikant (Gesamtmittel und `language-gap`),
  verschwindet aber vollständig auf 60 Queries. Das ist selbst ein Befund
  über die Verlässlichkeit kleiner Goldsets, nicht nur eine Fußnote — siehe
  [Empfehlung](#empfehlung).
- **`cross-language` bleibt mit fünf Queries grob.** Recall@10 = 1,0 für alle
  Arme bleibt gesättigt; die Rang-Streuung ist real, aber mit `n=5` ist jede
  einzelne Query 20 Prozentpunkte wert — für einen belastbaren
  Modellvergleich reicht das weiterhin nicht.
- **Der Sprach-Confound ist isoliert gemessen, aber es gibt auf diesem
  Goldset nichts mehr zu erklären** — weder `model_context` noch
  `model_context_de` zeigen einen von Null unterscheidbaren Effekt gegenüber
  `metadata_context`.
- **Ein einziger Modellsatz je Chunk, aus einem Lauf.** Wie in
  [#733](2026-08-07-hyde-multiquery-733.md#grenzen): ein zweiter Lauf desselben
  Prompts liefert andere Sätze und damit andere Zahlen. Wie groß diese
  Streuung ist, ist hier nicht gemessen.
- **Recall@10 ist an diesem Goldset für die meisten Arme weiterhin nicht
  unterscheidbar** (weitgehende Sättigung bei 21 Dokumenten, wie in #708/#729
  dokumentiert), mit Ausnahme des `model_context_de`-Rückgangs in
  `language-gap`. Der überwiegende gemessene Effekt bleibt ein Rangeffekt
  (nDCG@10/MRR), kein Treffereffekt.
- **Kostenzahlen sind ein Einzellauf auf 21 Dokumenten / 61 Chunks**, nicht
  hochrechenbar auf reale Paper mit deutlich mehr Chunks (ein Aufruf pro
  Dokument mit allen Chunks im Prompt skaliert anders als ein Aufruf pro
  Chunk). Die belastbare Kostenmessung für den produktiven Schreibweg ist
  Aufgabe von #710-B (#784), nicht dieses Issues — und beruht selbst noch auf
  dem ursprünglichen 11-Dokumente-Goldset (siehe
  [`2026-08-09-context-enrichment-710.md`](2026-08-09-context-enrichment-710.md),
  nicht Teil dieser Aktualisierung).
- **Nicht im CI-Job `retrieval-goldset` verdrahtet.** `.github/workflows/`
  ist laut `AGENTS.md` protected area (`ci`) und außerhalb des Scopes dieses
  Issues; die Reproduzierbarkeit ist stattdessen über
  `tests/test_issue_710_context_ablation.py` (Teil des Standard-Pytest-Laufs)
  abgesichert. Eine CI-Verdrahtung wie bei #731/#733 wäre ein eigener,
  kleiner Nachtrag.
- **Der produktive Schreibweg selbst ist nicht Teil dieses Laufs.** Er ist
  inzwischen gebaut (#783/#784) und unabhängig von dieser Aktualisierung in
  Betrieb; dieser Lauf beantwortet ausschließlich die empirische
  Ausgangsfrage aus AC2 auf dem aktuellen Goldset, nicht ob der bereits
  gebaute Weg zurückgebaut werden sollte.
