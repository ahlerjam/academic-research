# Embedding-Kandidaten auf dem Chunk-Goldset (Issue #731)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-08, Zahlen aktualisiert 2026-08-10 auf dem in [#800](2026-08-10-chunk-goldset-widening-800.md)
verbreiterten Goldset (26 → 60 Queries, 11 → 21 Dokumente)
**Komponente:** `academic_vault` (Retrieval-Pfad; **kein** Eingriff im
produktiven Code — aller Code dieses Laufs liegt unter `scripts/eval/`)
**Goldset:** Chunk-Goldset aus [#708](retrieval-chunk-goldset-708.md), 60 Queries seit [#800](2026-08-10-chunk-goldset-widening-800.md)
**Rohdaten:** [`2026-08-08-embedding-candidates-731-live-results.json`](2026-08-08-embedding-candidates-731-live-results.json)

## Fragestellung

Der A/B-Lauf aus [#628](recall-at-k-model-ab-hard-628.md) hat `"{title}. {abstract}"`
gemessen — nicht die Chunk-Pipeline, die tatsächlich läuft. Dieser Report
schließt die Lücke: jeder Kandidat geht denselben Weg wie im Betrieb
(`chunking.chunk_pages()` mit dem **eigenen** Tokenizer, Kontextsatz im
Embedding-Input, Ranking über `VaultDB.knn_chunks`), und Download-Größe sowie
CPU-Zeit stehen gleichrangig neben der Trefferqualität.

Der Report **entscheidet nichts**. Die Wechselentscheidung ist ausdrücklich
Sache eines Folge-Issues ([#732](2026-08-08-embedding-model-decision-732.md));
hier stehen nur die Zahlen und ihre Belastbarkeit.

## Messaufbau

| | |
|---|---|
| Messhardware | Apple M4 Pro, 12 Kerne, 25,8 GB RAM, macOS-26.5.2-arm64 |
| Laufzeitumgebung | Python 3.12.13, torch 2.13.0 |
| Gerät | **CPU** (`device="cpu"` explizit gesetzt); CUDA nicht verfügbar, MPS verfügbar, aber **nicht genutzt** |
| Generator (live) | `scripts/eval/build_embedding_candidates_731.py` (env-gated `VAULT_E5_LIVE_TEST=1`) |
| Auswertung (hermetisch) | `scripts/eval/run_embedding_candidates_731.py` — kein Netz, kein Modell |
| Signifikanz | gepaarter Bootstrap über die 60 Queries, 10 000 Resamples, Seed 731, 95-%-Perzentilintervall |

Der Generator misst Modell-Downloads und CPU-Inferenz; die Metriken entstehen
im hermetischen Lauf aus den eingecheckten Vektoren. Der CI-Job
`retrieval-goldset` fährt diesen Lauf gegen die Rohdaten oben — weicht eine
Zahl ab, wird die Pipeline rot, statt dass der Report unbemerkt altert.

## Ergebnis je Kandidat

Zahlen über alle 60 Queries, `k = 10`:

| Kandidat | Modell | Dim | Chunks | Recall@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|---|
| `e5-small` *(Baseline)* | `intfloat/multilingual-e5-small` | 384 | 61 | 0,8167 | 0,7097 | 0,6764 |
| `qwen3-384` | `Qwen/Qwen3-Embedding-0.6B`, `truncate_dim=384` | 384 | 59 | 0,9000 | 0,7936 | 0,7656 |
| `qwen3-1024` | `Qwen/Qwen3-Embedding-0.6B`, nativ | 1024 | 59 | 0,9000 | **0,8380** | **0,8200** |
| `bge-m3` | `BAAI/bge-m3` | 1024 | 61 | **0,9750** | 0,8104 | 0,7621 |
| `e5-large` | `intfloat/multilingual-e5-large` | 1024 | 61 | 0,8667 | 0,6995 | 0,6561 |

Je Teilmenge (nDCG@10 / MRR):

| Kandidat | same-language | language-gap | cross-language |
|---|---|---|---|
| `e5-small` | 0,9212 / 0,8974 | 0,2725 / 0,1994 | 0,2000 / 0,2000 |
| `qwen3-384` | 0,9098 / 0,8984 | 0,4511 / 0,3643 | 0,8000 / 0,8000 |
| `qwen3-1024` | 0,9615 / 0,9593 | 0,4661 / 0,4090 | 0,8667 / 0,8286 |
| `bge-m3` | 0,9285 / 0,9122 | 0,5361 / 0,4223 | 0,6097 / 0,4833 |
| `e5-large` | 0,8492 / 0,8185 | 0,5108 / 0,4147 | 0,0000 / 0,0000 |

Der gesamte Abstand entsteht **nicht** im gleichsprachigen Fall — dort liegen
alle fünf Kandidaten zwischen 0,85 und 0,96 nDCG. Er entsteht an der
Sprachlücke: `e5-small` fällt bei einer deutschen Query auf einen englischen
Beleg auf 0,27 nDCG. Bei `cross-language` (Query in der einen Sprache, Antwort
ausschließlich in der anderen) trennen sich die Kandidaten am deutlichsten:
`qwen3-1024` und `qwen3-384` liegen bei 0,87 respektive 0,80 nDCG,
`e5-small`/`bge-m3` dazwischen, und `e5-large` bleibt bei glatt 0 — dieselbe
Schwäche wie im 26er-Set, jetzt aber über 5 statt 2 Queries gemessen und damit
kein Einzelfall mehr.

## Hardware-Seite: Download und CPU-Zeit

Alle Zeiten auf der oben genannten Maschine, CPU, Einzeltext-Encode (kein
Batch — AC3 fragt nach der Zeit *je Chunk*), zwei Warmläufe vorab verworfen:

| Kandidat | Download | Indexierung p50 | p95 | Suchlatenz p50 | p95 | Vault mit 200 Papern¹ |
|---|---|---|---|---|---|---|
| `e5-small` | 0,49 GB | **26,3 ms** | 29,7 ms | 2,791 ms | 3,467 ms | ≈ 2 min |
| `qwen3-384` | 1,21 GB | 2351,6 ms | 2501,7 ms | 2,579 ms | 2,824 ms | ≈ 2 h 52 min |
| `qwen3-1024` | 1,21 GB | 2378,4 ms | 2515,3 ms | 5,437 ms | 6,006 ms | ≈ 2 h 54 min |
| `bge-m3` | 2,29 GB | 170,9 ms | 186,8 ms | 5,441 ms | 6,507 ms | ≈ 13 min |
| `e5-large` | 2,26 GB | 168,6 ms | 181,1 ms | 5,546 ms | 6,077 ms | ≈ 12 min |

¹ Überschlag mit 22 Chunks je Paper (Mittel dieses Goldsets, 61 Chunks aus 21
Dokumenten hochgerechnet auf typische Volltexte) — kein gemessener Wert,
sondern eine Größenordnung.

Der Größenunterschied ist die eigentliche Nachricht dieses Laufs:
**Qwen3-Embedding-0.6B rechnet auf CPU rund 90-mal so lange je Chunk wie
`e5-small` und rund 14-mal so lange wie BGE-M3.** Das deckt sich mit der
Vormessung aus dem Issue-Body (≈ 2146 ms/Chunk am 2026-08-06) und mit dem
2026-08-08-Lauf auf dem kleineren Goldset. Die Suchlatenz trennt die
Kandidaten dagegen kaum: sie liegt zwischen 2,6 und 5,5 ms und hängt vor allem
an der Vektordimension (1024d ruft mehr Distanzberechnungen auf als 384d),
nicht am Modell selbst.

Die Download-Größen sind hier als aufgelöster HuggingFace-Snapshot gemessen
(ohne die optionale ONNX-Variante, doppelt vorgehaltene Gewichte einmal
gezählt). Sie liegen erwartungsgemäß leicht über den reinen Gewichtsdateien aus
[#730](embedding-truncatability-730.md) (Qwen3 1,19 GB, BGE-M3 2,27 GB,
e5-large 2,24 GB), weil Tokenizer- und Konfigurationsdateien mitzählen.

## Preis einer Schema-Migration

`chunk_vectors` wird in `academic_vault/db.py` als
`vec0(chunk_id TEXT PRIMARY KEY, embedding FLOAT[dim])` angelegt. 384 ist der
Bestand; jede andere Dimension ist eine DDL-Änderung plus vollständige
Neuindizierung aller Bestands-Vaults.

| Kandidat | Dim | Migration nötig? | Preis | Beleg |
|---|---|---|---|---|
| `e5-small` | 384 | nein | keine Migration (384d, Bestandsschema) | nativ 384d |
| `qwen3-384` | 384 | **nein** | keine Migration (384d, Bestandsschema) | [#730](embedding-truncatability-730.md): „MRL Support: Yes", zulässiger Bereich 32–1024 |
| `qwen3-1024` | 1024 | ja | Schema-Migration FLOAT[384] → FLOAT[1024] plus vollständige Neuindizierung aller Bestands-Vaults | native Dimension |
| `bge-m3` | 1024 | ja | Schema-Migration FLOAT[384] → FLOAT[1024] plus vollständige Neuindizierung aller Bestands-Vaults | [#730](embedding-truncatability-730.md): Kürzung auf 384d **nicht belegt** |
| `e5-large` | 1024 | ja | Schema-Migration FLOAT[384] → FLOAT[1024] plus vollständige Neuindizierung aller Bestands-Vaults | [#730](embedding-truncatability-730.md): Kürzung auf 384d **nicht belegt** |

Der Vergleich `qwen3-384` gegen `qwen3-1024` beziffert, was die Kürzung
kostet — die Antwort bleibt: **fast nichts**. Recall@10 ist auf diesem Set für
beide Varianten identisch (0,9000), nDCG/MRR liegen bei der nativen 1024d-Fassung
leicht vorn (0,8380 gegen 0,7936), vor allem aus einem besseren
cross-language-Verhalten (0,87 gegen 0,80 nDCG). Der einzige migrationsfreie
Kandidat bleibt damit nahe am besten gemessenen, ohne ihn hier ganz zu
erreichen — anders als im 26er-Set, wo die 384d-Kürzung die 1024d-Variante
noch übertraf. Bei 60 statt 26 Queries ist dieser kleine Rückstand eher
belastbar (siehe Auflösungsgrenze unten), aber nicht groß: die belastbare
Aussage bleibt, dass die Kürzung auf 384d hier **keinen praktisch relevanten**
Nachteil erzeugt.

## Trägt der Abstand?

Vorab festgeschriebene Regel (im Code als `SIGNIFICANCE_RULE` fixiert, bevor
der erste Messwert vorlag): ein Abstand zur Baseline trägt genau dann, wenn das
95-%-Intervall der gepaarten Bootstrap-Differenz die Null nicht enthält.

| Kandidat | Recall@10 | nDCG@10 | MRR |
|---|---|---|---|
| `qwen3-384` | +0,0833 [−0,0167; +0,1833] — trägt nicht | +0,0839 [+0,0051; +0,1704] — **trägt** | +0,0892 [+0,0053; +0,1789] — **trägt** |
| `qwen3-1024` | +0,0833 [−0,0167; +0,2000] — trägt nicht | +0,1282 [+0,0491; +0,2128] — **trägt** | +0,1437 [+0,0620; +0,2322] — **trägt** |
| `bge-m3` | +0,1583 [+0,0583; +0,2667] — **trägt** | +0,1006 [+0,0244; +0,1798] — **trägt** | +0,0858 [+0,0004; +0,1697] — **trägt** |
| `e5-large` | +0,0500 [−0,0333; +0,1333] — trägt nicht | −0,0102 [−0,0834; +0,0610] — trägt nicht | −0,0203 [−0,1030; +0,0606] — trägt nicht |

Was das heißt: `qwen3-384`, `qwen3-1024` und `bge-m3` tragen jetzt **jeweils in
allen drei Metriken außer Recall@10** signifikant gegenüber der Baseline — mit
60 statt 26 Queries ist das eine deutlich breitere Bestätigung als im
Vorgängerlauf, in dem nur `qwen3-384` und `bge-m3` in mehr als einer Metrik
trugen. `e5-large` bleibt der einzige Kandidat, der auf keiner Metrik
signifikant über der Baseline liegt — bei nDCG/MRR ist der Punktschätzer sogar
leicht negativ, getragen vom vollständigen cross-language-Ausfall oben.
Recall@10 trägt bei keinem Kandidaten signifikant, weil `e5-small` in
`same-language` bereits bei 1,0 sättigt und der Unterschied fast vollständig
aus `language-gap`/`cross-language` kommt, wo die Stichprobe (14 bzw.
5 Queries) am kleinsten ist.

### Auflösungsgrenze

60 Queries. Eine einzelne Query entspricht damit **0,0167 Recall** — eine
Verbesserung um den Faktor 2,3 gegenüber dem 26er-Set (0,038). Die
beobachteten Abstände zur Baseline liegen zwischen 0,05 und 0,16 (Recall@10)
bzw. bis 0,14 (MRR), deutlich über dieser Auflösung; die Abstände der
Kandidaten *untereinander* (z. B. `qwen3-1024` gegen `bge-m3`: 0,03 nDCG)
liegen weiterhin nahe an der Auflösungsgrenze oder knapp darüber. Für die
Frage „ist ein Wechsel besser als der Status quo?" ist die Antwort mit diesem
Set klarer als vorher (drei von vier Kandidaten tragen jetzt in zwei von drei
Metriken); für die Frage „welcher der vier ist der beste?" bleibt der Lauf
ohne paarweisen Kandidat-gegen-Kandidat-Bootstrap ungenau — dieser Report
testet nur gegen die Baseline, nicht Kandidaten gegeneinander.

## Grenzen dieses Laufs

1. **Unterschiedliche Chunkzahl je Kandidat.** Jeder Kandidat chunkt mit
   seinem eigenen Tokenizer, so wie er es im Betrieb täte. Qwen3 kommt damit
   auf 59 Chunks, die übrigen auf 61. Der Korpus, gegen den gesucht wird, ist
   je Kandidat also nicht identisch. Ein Kontrolllauf auf eingefrorenen
   e5-Chunkgrenzen, der Chunking- und Embedding-Effekt trennt, steht **aus**
   und ist als Folgearbeit vorgemerkt. Die Richtung: ein kleinerer Korpus
   erleichtert Recall geringfügig — der Qwen3-Vorsprung ist damit eher eine
   Ober- als eine Untergrenze.
2. **Prompting je Kandidat statt eines einheitlichen `passage:`.** AC1 des
   Issues nennt den `passage:`-Präfix wörtlich, er gehört aber zum
   Trainings-Setup der e5-Familie. BGE-M3 verlangt laut Modellkarte
   ausdrücklich *keine* Instruktion („the BGE-M3 model no longer requires
   adding instructions to the queries"), Qwen3 nutzt den im Modell
   hinterlegten `prompt_name="query"` für Queries und keinen Präfix für
   Dokumente. Ein aufgezwungenes `passage: ` hätte die Fremdmodelle künstlich
   schlechter aussehen lassen. Das Prompting steht je Kandidat als Feld
   `prompting` in den Rohdaten.
3. **Synthetisches Goldset.** Die 21 Quelldokumente aus #708/#800 sind für den
   Zweck geschrieben, nicht aus einer echten Bibliothek gezogen. Absolutwerte
   sind deshalb nicht auf einen realen Vault übertragbar; die *Rangfolge* ist
   die Aussage.
4. **Eine Maschine, ein Lauf.** Alle Zeiten stammen von derselben CPU. Auf
   x86 ohne die Apple-Silicon-Matrixeinheiten dürften die Abstände zwischen
   den Modellen anders ausfallen; die Größenordnung „Qwen3 ist zwei
   Zehnerpotenzen teurer als e5-small" wird davon nicht berührt.
5. **Kein paarweiser Kandidatenvergleich.** Der Bootstrap ist gepaart gegen
   die Baseline `e5-small`, nicht Kandidat gegen Kandidat. Aussagen wie
   „`qwen3-1024` schlägt `bge-m3`" sind Punktschätzungen ohne eigenes
   Unsicherheitsintervall.

## Reproduktion

```bash
# hermetisch (kein Netz, kein Modell) — das ist auch, was CI fährt
uv run python scripts/eval/run_embedding_candidates_731.py \
  --check-against docs/evals/2026-08-08-embedding-candidates-731-live-results.json

# Rohdaten neu erzeugen (≈ 7 GB Modelle, ≈ 10 min CPU)
VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_embedding_candidates_731.py \
  --write-live-results
```

Je Kandidat liegen Chunks, Queries, aufgezeichnete Tokenzählungen und Vektoren
unter `tests/fixtures/embedding_candidates_731/<kandidat>/`. Die
Tokenzählungen sind der Grund, warum sich die Chunkgrenzen jedes Kandidaten
ohne Modell-Download nachrechnen lassen
(`rechunk_from_frozen_token_counts`); ein `manifest_sha256` über Texte,
Modell-ID und Dimension bricht den Lauf ab, sobald Fixture und Texte
auseinanderlaufen.

## Was dieser Report nicht leistet

Keine Wechselempfehlung, keine Änderung am produktiven Pfad, kein Late
Chunking, keine Binärquantisierung. Die Entscheidung trifft das Folge-Issue
auf Basis dieser Zahlen — mit der Auflösungsgrenze oben als Rahmen.
