# Embedding-Kandidaten auf dem Chunk-Goldset (Issue #731)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-08, Zahlen aktualisiert 2026-08-10 auf dem in [#800](2026-08-10-chunk-goldset-widening-800.md)
verbreiterten Goldset (26 → 60 Queries, 11 → 21 Dokumente), um Snowflake
Arctic-Embed L v2.0 erweitert 2026-08-10 ([#801](https://github.com/ahlerjam/academic-research/issues/801))
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
| `bge-m3` | `BAAI/bge-m3` | 1024 | 61 | 0,9750 | 0,8104 | 0,7621 |
| `e5-large` | `intfloat/multilingual-e5-large` | 1024 | 61 | 0,8667 | 0,6995 | 0,6561 |
| `arctic-l-v2-1024` | `Snowflake/snowflake-arctic-embed-l-v2.0`, nativ | 1024 | 61 | **0,9833** | 0,8236 | 0,7767 |
| `arctic-l-v2-256` | `Snowflake/snowflake-arctic-embed-l-v2.0`, `truncate_dim=256` | 256 | 61 | 0,9667 | 0,8116 | 0,7689 |

Je Teilmenge (nDCG@10 / MRR):

| Kandidat | same-language | language-gap | cross-language |
|---|---|---|---|
| `e5-small` | 0,9212 / 0,8974 | 0,2725 / 0,1994 | 0,2000 / 0,2000 |
| `qwen3-384` | 0,9098 / 0,8984 | 0,4511 / 0,3643 | 0,8000 / 0,8000 |
| `qwen3-1024` | 0,9615 / 0,9593 | 0,4661 / 0,4090 | 0,8667 / 0,8286 |
| `bge-m3` | 0,9285 / 0,9122 | 0,5361 / 0,4223 | 0,6097 / 0,4833 |
| `e5-large` | 0,8492 / 0,8185 | 0,5108 / 0,4147 | 0,0000 / 0,0000 |
| `arctic-l-v2-1024` | 0,9156 / 0,8951 | 0,5175 / 0,3857 | 0,9262 / 0,9000 |
| `arctic-l-v2-256` | 0,9297 / 0,9228 | 0,4605 / 0,3191 | 0,8262 / 0,7667 |

Der gesamte Abstand entsteht **nicht** im gleichsprachigen Fall — dort liegen
alle sieben Kandidaten zwischen 0,85 und 0,96 nDCG. Er entsteht an der
Sprachlücke: `e5-small` fällt bei einer deutschen Query auf einen englischen
Beleg auf 0,27 nDCG. Bei `cross-language` (Query in der einen Sprache, Antwort
ausschließlich in der anderen) trennen sich die Kandidaten am deutlichsten:
`arctic-l-v2-1024` führt hier mit 0,93 nDCG knapp vor `qwen3-1024` (0,87) und
`qwen3-384` (0,80), `e5-small`/`bge-m3` liegen dazwischen, und `e5-large`
bleibt bei glatt 0 — dieselbe Schwäche wie im 26er-Set, jetzt aber über
5 statt 2 Queries gemessen und damit kein Einzelfall mehr.

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
| `arctic-l-v2-1024`² | 2,29 GB | 185,2 ms | 207,3 ms | 2,248 ms | 2,703 ms | ≈ 14 min |
| `arctic-l-v2-256`² | 2,29 GB | 178,7 ms | 186,9 ms | 1,820 ms | 2,240 ms | ≈ 13 min |

¹ Überschlag mit 22 Chunks je Paper (Mittel dieses Goldsets, 61 Chunks aus 21
Dokumenten hochgerechnet auf typische Volltexte) — kein gemessener Wert,
sondern eine Größenordnung.

² **Andere Lastbedingungen als die übrigen fünf Kandidaten (#801-Nachtrag).**
Die Arctic-Zeiten entstanden auf derselben Maschine, aber an einem Tag mit
zwei parallel laufenden Hintergrund-Runnern (`load average` 6–11 auf 12
Kernen, gegenüber einer sonst freien Maschine für die übrigen fünf
Kandidaten). Eine Gegenmessung von `bge-m3` unter denselben
Lastbedingungen im selben Zeitfenster ergab 182,6 ms/Chunk gegenüber den
eingecheckten 170,9 ms — ein Kontentions-Aufschlag von rund **+7 %**. Ein
naiv um diesen Faktor korrigierter Schätzwert für `arctic-l-v2-1024` läge bei
≈ 173 ms/Chunk, für `arctic-l-v2-256` bei ≈ 167 ms/Chunk — beide weiterhin in
`bge-m3`s Größenordnung, keine andere Größenordnung wie bei Qwen3. Die
Tabelle zeigt bewusst die **rohen, unkorrigierten** Messwerte statt eines
geschätzten Korrekturwerts; die Kontentions-Spanne ist damit als
Unsicherheit ausgewiesen, nicht weggerechnet. Eine unbelastete Nachmessung
steht aus.

Der Größenunterschied ist die eigentliche Nachricht dieses Laufs:
**Qwen3-Embedding-0.6B rechnet auf CPU rund 90-mal so lange je Chunk wie
`e5-small` und rund 14-mal so lange wie BGE-M3 und Arctic-Embed L v2.0.** Das
deckt sich mit der Vormessung aus dem Issue-Body (≈ 2146 ms/Chunk am
2026-08-06) und mit dem 2026-08-08-Lauf auf dem kleineren Goldset. Arctic
reiht sich trotz der Kontentionslast klar in `bge-m3`s Klasse ein (170–207 ms)
und NICHT in Qwen3s Klasse (2350–4800 ms) — der Abstand zwischen den beiden
Klassen ist mit Faktor 12–20 so groß, dass die Kontentionsunsicherheit von
±7 % am qualitativen Befund nichts ändert. Die Suchlatenz trennt die
Kandidaten dagegen kaum: sie liegt zwischen 1,8 und 6,5 ms und hängt vor allem
an der Vektordimension (1024d ruft mehr Distanzberechnungen auf als 384d bzw.
256d), nicht am Modell selbst.

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
| `arctic-l-v2-1024` | 1024 | ja (ggü. 384d-Bestandsschema) | Schema-Migration FLOAT[384] → FLOAT[1024] plus vollständige Neuindizierung aller Bestands-Vaults | native Dimension — 384d nicht belegt (s. u.) |
| `arctic-l-v2-256` | 256 | ja (ggü. 384d-Bestandsschema) | Schema-Migration FLOAT[384] → FLOAT[256] plus vollständige Neuindizierung aller Bestands-Vaults | [#730](embedding-truncatability-730.md): `config.json` `matryoshka_dimensions: [256]` — 256d ist der einzige vom Anbieter zugesicherte MRL-Punkt, NICHT 384d |

**Wichtig für Arctic — anderer Vergleichsmaßstab als die Tabelle oben
zeigt.** Die Spalte „Migration nötig?" prüft gegen das historische
384d-Bestandsschema aus #730/#731, nicht gegen den heutigen Produktivstand.
Produktiv läuft seit [#732](2026-08-08-embedding-model-decision-732.md)
bereits `BAAI/bge-m3` mit **1024d**. `arctic-l-v2-1024` misst dieselben
1024 Dimensionen — ein Wechsel von `bge-m3` auf `arctic-l-v2-1024` bräuchte
also **keine Schema-Migration**, nur einen Reindex. `arctic-l-v2-256` wäre
dagegen tatsächlich eine Schema-Änderung gegenüber dem heutigen Stand
(`FLOAT[1024]` → `FLOAT[256]`), nicht nur gegenüber dem historischen 384d.
Zudem gilt für Arctic ausdrücklich **nicht**, was für `qwen3-384` gilt: eine
384d-Truncation ist für dieses Modell laut Modellkarte **nicht zugesichert**
— nur 256d. Details: [`embedding-truncatability-730.md`](embedding-truncatability-730.md#snowflake-arctic-embed-l-v20-seit-801).

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
| `arctic-l-v2-1024` | +0,1667 [+0,0667; +0,2833] — **trägt** | +0,1139 [+0,0362; +0,1961] — **trägt** | +0,1003 [+0,0160; +0,1879] — **trägt** |
| `arctic-l-v2-256` | +0,1500 [+0,0500; +0,2667] — **trägt** | +0,1019 [+0,0299; +0,1776] — **trägt** | +0,0925 [+0,0165; +0,1735] — **trägt** |

Was das heißt: `qwen3-384`, `qwen3-1024` und `bge-m3` tragen **jeweils in
allen drei Metriken außer Recall@10** signifikant gegenüber der Baseline — mit
60 statt 26 Queries ist das eine deutlich breitere Bestätigung als im
Vorgängerlauf, in dem nur `qwen3-384` und `bge-m3` in mehr als einer Metrik
trugen. `arctic-l-v2-1024` und `arctic-l-v2-256` gehen noch einen Schritt
weiter: Sie tragen als bislang **einzige** Kandidaten in **allen drei**
Metriken einschließlich Recall@10 signifikant gegenüber der Baseline. `e5-large`
bleibt der einzige Kandidat, der auf keiner Metrik
signifikant über der Baseline liegt — bei nDCG/MRR ist der Punktschätzer sogar
leicht negativ, getragen vom vollständigen cross-language-Ausfall oben.
Recall@10 trägt bei keinem Kandidaten signifikant, weil `e5-small` in
`same-language` bereits bei 1,0 sättigt und der Unterschied fast vollständig
aus `language-gap`/`cross-language` kommt, wo die Stichprobe (14 bzw.
5 Queries) am kleinsten ist.

### Auflösungsgrenze

60 Queries. Eine einzelne Query entspricht damit **0,0167 Recall** — eine
Verbesserung um den Faktor 2,3 gegenüber dem 26er-Set (0,038). Die
beobachteten Abstände zur Baseline liegen zwischen 0,05 und 0,17 (Recall@10)
bzw. bis 0,14 (MRR), deutlich über dieser Auflösung; die Abstände der
Kandidaten *untereinander* (z. B. `qwen3-1024` gegen `bge-m3`: 0,03 nDCG)
liegen weiterhin nahe an der Auflösungsgrenze oder knapp darüber. Für die
Frage „ist ein Wechsel besser als der Status quo?" ist die Antwort mit diesem
Set klarer als vorher (fünf von sechs Kandidaten tragen jetzt in mindestens
zwei von drei Metriken, `arctic-l-v2-1024` und `arctic-l-v2-256` sogar in
allen drei); für die Frage „welcher der sechs ist der beste?" bleibt der
offizielle Lauf ohne paarweisen Kandidat-gegen-Kandidat-Bootstrap ungenau —
dieser Report testet planmäßig nur gegen die Baseline, nicht Kandidaten
gegeneinander (siehe aber die ergänzende Ad-hoc-Prüfung unten für
`arctic-l-v2-1024` gegen `bge-m3` und `qwen3-1024`).

### Ergänzung (#801): trägt Arctic gegenüber `bge-m3` und `qwen3-1024`?

Das Standard-Framework oben testet nur gegen die Baseline `e5-small`
(Grenze 5 unten). Weil #801 ausdrücklich fragt, ob Arctic die #732-Entscheidung
neu aufrollt, wurde für diese beiden Vergleiche zusätzlich ein gepaarter
Bootstrap gerechnet (dieselbe Methode, derselbe Seed 731, 10 000 Resamples —
aber **nicht** Teil von `build_report()`/`compute_deltas()`, sondern eine
Ad-hoc-Auswertung für diesen Abschnitt):

| Vergleich | Recall@10 | nDCG@10 | MRR |
|---|---|---|---|
| `arctic-l-v2-1024` vs. `bge-m3` | +0,0083 [−0,0417; +0,0583] — trägt nicht | +0,0133 [−0,0467; +0,0761] — trägt nicht | +0,0145 [−0,0624; +0,0934] — trägt nicht |
| `arctic-l-v2-256` vs. `bge-m3` | −0,0083 [−0,0667; +0,0500] — trägt nicht | +0,0013 [−0,0592; +0,0636] — trägt nicht | +0,0068 [−0,0673; +0,0834] — trägt nicht |
| `arctic-l-v2-1024` vs. `qwen3-1024` | +0,0833 [+0,0167; +0,1500] — **trägt** | −0,0144 [−0,0812; +0,0519] — trägt nicht | −0,0434 [−0,1235; +0,0338] — trägt nicht |

Ergebnis: `arctic-l-v2-1024` liegt bei allen drei Metriken vor `bge-m3` als
Punktschätzer (0,9833 vs. 0,9750 Recall, 0,8236 vs. 0,8104 nDCG, 0,7767 vs.
0,7621 MRR) — aber **keiner** dieser Abstände trägt nach der vorab
festgeschriebenen Regel. `bge-m3` und Arctic sind auf diesem 60er-Set
statistisch **nicht unterscheidbar**, genauso wie `bge-m3` und `qwen3-384` es
in der #732-Entscheidung selbst waren. Gegen `qwen3-1024` (den nDCG/MRR-
Sieger aus #731) gewinnt Arctic nur bei Recall@10 signifikant; bei nDCG/MRR
liegt der Punktschätzer sogar leicht hinter `qwen3-1024`, ohne dass der
Abstand trägt.

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
   adding instructions to the queries"), Qwen3 und Arctic-Embed L v2.0 (#801)
   nutzen den im Modell hinterlegten `prompt_name="query"` für Queries und
   keinen Präfix für Dokumente. Ein aufgezwungenes `passage: ` hätte die
   Fremdmodelle künstlich schlechter aussehen lassen. Das Prompting steht je
   Kandidat als Feld `prompting` in den Rohdaten.
3. **Synthetisches Goldset.** Die 21 Quelldokumente aus #708/#800 sind für den
   Zweck geschrieben, nicht aus einer echten Bibliothek gezogen. Absolutwerte
   sind deshalb nicht auf einen realen Vault übertragbar; die *Rangfolge* ist
   die Aussage.
4. **Eine Maschine, ein Lauf.** Alle Zeiten stammen von derselben CPU. Auf
   x86 ohne die Apple-Silicon-Matrixeinheiten dürften die Abstände zwischen
   den Modellen anders ausfallen; die Größenordnung „Qwen3 ist zwei
   Zehnerpotenzen teurer als e5-small" wird davon nicht berührt.
5. **Kein paarweiser Kandidatenvergleich im Standard-Framework.** Der
   eingebaute Bootstrap ist gepaart gegen die Baseline `e5-small`, nicht
   Kandidat gegen Kandidat. Für `arctic-l-v2-*` gegen `bge-m3`/`qwen3-1024`
   wurde das seit #801 ergänzend als Ad-hoc-Auswertung nachgerechnet (siehe
   Abschnitt oben); für alle übrigen Kandidatenpaare bleiben Aussagen wie
   „`qwen3-1024` schlägt `bge-m3`" Punktschätzungen ohne eigenes
   Unsicherheitsintervall.
6. **Arctic-Zeiten unter anderer Systemlast (#801).** `arctic-l-v2-1024` und
   `arctic-l-v2-256` wurden an einem Tag mit zwei parallel laufenden
   Hintergrund-Runnern gemessen (`load average` 6–11 auf 12 Kernen); die
   übrigen fünf Kandidaten liefen auf einer sonst freien Maschine. Eine
   Gegenmessung von `bge-m3` unter dem Arctic-Lauf ergab einen
   Kontentions-Aufschlag von rund +7 % — die Arctic-Zeiten in der Tabelle
   oben sind also tendenziell leicht zu hoch, aber nicht um eine
   Größenordnung. Eine unbelastete Nachmessung steht aus.

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
