# Embedding-Kandidaten auf dem Chunk-Goldset (Issue #731)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-08
**Komponente:** `academic_vault` (Retrieval-Pfad; **kein** Eingriff im
produktiven Code — aller Code dieses Laufs liegt unter `scripts/eval/`)
**Goldset:** Chunk-Goldset aus [#708](retrieval-chunk-goldset-708.md), 26 Queries
**Rohdaten:** [`2026-08-08-embedding-candidates-731-live-results.json`](2026-08-08-embedding-candidates-731-live-results.json)

## Fragestellung

Der A/B-Lauf aus [#628](recall-at-k-model-ab-hard-628.md) hat `"{title}. {abstract}"`
gemessen — nicht die Chunk-Pipeline, die tatsächlich läuft. Dieser Report
schließt die Lücke: jeder Kandidat geht denselben Weg wie im Betrieb
(`chunking.chunk_pages()` mit dem **eigenen** Tokenizer, Kontextsatz im
Embedding-Input, Ranking über `VaultDB.knn_chunks`), und Download-Größe sowie
CPU-Zeit stehen gleichrangig neben der Trefferqualität.

Der Report **entscheidet nichts**. Die Wechselentscheidung ist ausdrücklich
Sache eines Folge-Issues; hier stehen nur die Zahlen und ihre Belastbarkeit.

## Messaufbau

| | |
|---|---|
| Messhardware | Apple M4 Pro, 12 Kerne, 25,8 GB RAM, macOS-26.5.2-arm64 |
| Laufzeitumgebung | Python 3.12.13, torch 2.13.0 |
| Gerät | **CPU** (`device="cpu"` explizit gesetzt); CUDA nicht verfügbar, MPS verfügbar, aber **nicht genutzt** |
| Generator (live) | `scripts/eval/build_embedding_candidates_731.py` (env-gated `VAULT_E5_LIVE_TEST=1`) |
| Auswertung (hermetisch) | `scripts/eval/run_embedding_candidates_731.py` — kein Netz, kein Modell |
| Signifikanz | gepaarter Bootstrap über die 26 Queries, 10 000 Resamples, Seed 731, 95-%-Perzentilintervall |

Der Generator misst Modell-Downloads und CPU-Inferenz; die Metriken entstehen
im hermetischen Lauf aus den eingecheckten Vektoren. Der CI-Job
`retrieval-goldset` fährt diesen Lauf gegen die Rohdaten oben — weicht eine
Zahl ab, wird die Pipeline rot, statt dass der Report unbemerkt altert.

## Ergebnis je Kandidat

Zahlen über alle 26 Queries, `k = 10`:

| Kandidat | Modell | Dim | Chunks | Recall@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|---|
| `e5-small` *(Baseline)* | `intfloat/multilingual-e5-small` | 384 | 30 | 0,7692 | 0,6651 | 0,6314 |
| `qwen3-384` | `Qwen/Qwen3-Embedding-0.6B`, `truncate_dim=384` | 384 | 28 | 0,9615 | **0,8241** | **0,7923** |
| `qwen3-1024` | `Qwen/Qwen3-Embedding-0.6B`, nativ | 1024 | 28 | 0,9231 | 0,7859 | 0,7420 |
| `bge-m3` | `BAAI/bge-m3` | 1024 | 30 | **0,9808** | 0,8137 | 0,7660 |
| `e5-large` | `intfloat/multilingual-e5-large` | 1024 | 30 | 0,9231 | 0,7413 | 0,6979 |

Je Teilmenge (nDCG@10 / MRR):

| Kandidat | same-language | language-gap | cross-language |
|---|---|---|---|
| `e5-small` | 0,9170 / 0,8889 | 0,1311 / 0,0694 | 0,0000 / 0,0000 |
| `qwen3-384` | 0,9101 / 0,9167 | 0,6021 / 0,4750 | 0,7153 / 0,6250 |
| `qwen3-1024` | 0,9167 / 0,9074 | 0,4056 / 0,2708 | 0,7500 / 0,6667 |
| `bge-m3` | 0,8955 / 0,8796 | 0,5675 / 0,4306 | 0,8155 / 0,7500 |
| `e5-large` | 0,8719 / 0,8534 | 0,5966 / 0,4639 | 0,0000 / 0,0000 |

Der gesamte Abstand entsteht **nicht** im gleichsprachigen Fall — dort liegen
alle fünf Kandidaten zwischen 0,87 und 0,92 nDCG. Er entsteht an der
Sprachlücke: `e5-small` fällt bei einer deutschen Query auf einen englischen
Beleg auf 0,13 nDCG, und im cross-language-Fall (Query in der einen Sprache,
Antwort ausschließlich in der anderen) auf glatt 0. `e5-large` teilt diese
Schwäche im cross-language-Fall, obwohl es die Sprachlücke sonst schließt.

## Hardware-Seite: Download und CPU-Zeit

Alle Zeiten auf der oben genannten Maschine, CPU, Einzeltext-Encode (kein
Batch — AC3 fragt nach der Zeit *je Chunk*), zwei Warmläufe vorab verworfen:

| Kandidat | Download | Indexierung p50 | p95 | Suchlatenz p50 | p95 | Vault mit 200 Papern¹ |
|---|---|---|---|---|---|---|
| `e5-small` | 0,49 GB | **27,1 ms** | 30,0 ms | 5,848 ms | 6,247 ms | ≈ 2 min |
| `qwen3-384` | 1,21 GB | 2232,8 ms | 2423,7 ms | 5,970 ms | 6,973 ms | ≈ 2 h 45 min |
| `qwen3-1024` | 1,21 GB | 2368,4 ms | 2617,2 ms | 6,514 ms | 9,241 ms | ≈ 2 h 55 min |
| `bge-m3` | 2,29 GB | 168,6 ms | 176,2 ms | 6,259 ms | 7,485 ms | ≈ 12 min |
| `e5-large` | 2,26 GB | 173,5 ms | 180,3 ms | 6,500 ms | 7,060 ms | ≈ 13 min |

¹ Überschlag mit 22 Chunks je Paper (Mittel dieses Goldsets, 30 Chunks aus
sechs Dokumenten hochgerechnet auf typische Volltexte) — kein gemessener Wert,
sondern eine Größenordnung.

Der Größenunterschied ist die eigentliche Nachricht dieses Laufs:
**Qwen3-Embedding-0.6B rechnet auf CPU rund 80-mal so lange je Chunk wie
`e5-small` und rund 14-mal so lange wie BGE-M3.** Das deckt sich mit der
Vormessung aus dem Issue-Body (≈ 2146 ms/Chunk am 2026-08-06). Die Suchlatenz
trennt die Kandidaten dagegen nicht: sie liegt bei allen fünf zwischen 5,8 und
6,5 ms und wird vom SQLite-Pfad dominiert, nicht von der Dimension.

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
kostet — und die Antwort ist bemerkenswert: sie kostet **nichts**. Die
gekürzte 384d-Variante liegt auf diesem Goldset in allen drei Metriken
*über* der nativen (nDCG 0,8241 gegen 0,7859), im Wesentlichen aus einem
besseren language-gap-Verhalten. Der einzige migrationsfreie Kandidat ist
damit zugleich der beste gemessene. Bei 26 Queries ist dieser Binnenabstand
allerdings nicht von Rauschen zu trennen (siehe unten) — die belastbare
Aussage lautet: die Kürzung auf 384d verschlechtert hier **nicht** messbar.

## Trägt der Abstand?

Vorab festgeschriebene Regel (im Code als `SIGNIFICANCE_RULE` fixiert, bevor
der erste Messwert vorlag): ein Abstand zur Baseline trägt genau dann, wenn das
95-%-Intervall der gepaarten Bootstrap-Differenz die Null nicht enthält.

| Kandidat | Recall@10 | nDCG@10 | MRR |
|---|---|---|---|
| `qwen3-384` | +0,1923 [+0,0000; +0,3846] — trägt nicht | +0,1589 [+0,0149; +0,3021] — **trägt** | +0,1609 [+0,0147; +0,3051] — **trägt** |
| `qwen3-1024` | +0,1538 [+0,0000; +0,3462] — trägt nicht | +0,1208 [−0,0107; +0,2511] — trägt nicht | +0,1106 [−0,0256; +0,2404] — trägt nicht |
| `bge-m3` | +0,2115 [+0,0577; +0,3846] — **trägt** | +0,1485 [+0,0137; +0,2883] — **trägt** | +0,1346 [−0,0096; +0,2788] — trägt nicht |
| `e5-large` | +0,1538 [+0,0385; +0,3077] — **trägt** | +0,0762 [−0,0270; +0,1911] — trägt nicht | +0,0665 [−0,0479; +0,1885] — trägt nicht |

Was das heißt: **Jeder** der vier Kandidaten liegt der Punktschätzung nach
über der Baseline, aber nur `qwen3-384` und `bge-m3` halten das in mehr als
einer Metrik gegen die Streuung. Untereinander trennt der Lauf die Kandidaten
nicht — die Intervalle überlappen durchgehend.

### Auflösungsgrenze

26 Queries. Eine einzelne Query entspricht damit **0,038 Recall** — jeder
Unterschied unterhalb dieser Größenordnung ist eine Artefakt-Zahl, keine
Messung. Die beobachteten Abstände zur Baseline liegen mit 0,07 bis 0,21
darüber, die Abstände der Kandidaten *untereinander* (0,02 bis 0,04) jedoch
genau darauf oder darunter. Für die Frage „ist ein Wechsel besser als der
Status quo?" reicht dieses Goldset; für die Frage „welcher der vier ist der
beste?" reicht es **nicht**.

## Grenzen dieses Laufs

1. **Unterschiedliche Chunkzahl je Kandidat.** Jeder Kandidat chunkt mit
   seinem eigenen Tokenizer, so wie er es im Betrieb täte. Qwen3 kommt damit
   auf 28 Chunks, die übrigen auf 30. Der Korpus, gegen den gesucht wird, ist
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
3. **Synthetisches Goldset.** Die sechs Quelldokumente aus #708 sind für den
   Zweck geschrieben, nicht aus einer echten Bibliothek gezogen. Absolutwerte
   sind deshalb nicht auf einen realen Vault übertragbar; die *Rangfolge* ist
   die Aussage.
4. **Eine Maschine, ein Lauf.** Alle Zeiten stammen von derselben CPU. Auf
   x86 ohne die Apple-Silicon-Matrixeinheiten dürften die Abstände zwischen
   den Modellen anders ausfallen; die Größenordnung „Qwen3 ist zwei
   Zehnerpotenzen teurer als e5-small" wird davon nicht berührt.

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
