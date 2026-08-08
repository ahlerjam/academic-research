# Hilft ein inhaltlicher Kontextsatz gegenüber Metadaten? (#785, Epic #710-C)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Rohdaten liegen daneben in
> [`2026-08-08-context-ablation-710-live-results.json`](2026-08-08-context-ablation-710-live-results.json)
> und werden von `tests/test_issue_710_context_ablation.py` gegen einen
> frischen Lauf geprüft (nicht im CI-Job `retrieval-goldset` verdrahtet —
> siehe [Grenzen](#grenzen)).

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-08 · **Goldset:** bge-m3-Fassung des Chunk-Goldsets aus
[#708](retrieval-chunk-goldset-708.md)/[#731](2026-08-08-embedding-candidates-731.md),
`tests/fixtures/embedding_candidates_731/bge-m3/goldset.json`, 11 Dokumente /
30 Chunks / 26 Queries, unverändert · **Embedding:** `BAAI/bge-m3` (1024d,
produktiver Default seit [#732](2026-08-08-embedding-model-decision-732.md)) ·
**Kontextsätze:** `claude -p --model sonnet --output-format json`, eingeloggte
OAuth-Sitzung, kein API-Schlüssel

## Fragestellung

AC2 aus Epic #710: Der produktive Kontextsatz ist heute ein deterministischer
Metadaten-Satz (`chunking.default_context_sentence()`, z. B. *„Dieser Abschnitt
stammt aus 'Einleitung' (Seite 1-2, Chunk 0)."*) — immer deutsch, ohne
inhaltlichen Bezug zum Chunk. Der geplante Schreibweg (#783) würde stattdessen
einen echten, modellgeschriebenen inhaltlichen Satz erzeugen. Bevor der
Schreibweg gebaut wird, beantwortet dieser Lauf die vorgelagerte Frage rein
hermetisch: **Hilft ein inhaltlicher Satz beim Retrieval überhaupt — und wenn
ja, wodurch: Inhalt oder Sprache?**

Der Metadaten-Satz ist immer deutsch. Ein inhaltlicher Satz in Chunk-Sprache
unterscheidet sich von ihm deshalb gleichzeitig in **zwei** Dimensionen —
Inhalt und Sprache. Um das zu entwirren, misst dieser Lauf einen vierten Arm:
denselben Modellsatz, aber auf Deutsch erzwungen. Der Sprach-Confound ist damit
**isoliert, nicht nur vermerkt** — der optionale vierte Arm aus dem
Plan-Kommentar wurde gebaut.

## Basis: die bge-m3-Fassung, nicht die e5-Fassung

Das #708-Goldset existiert in fünf Embedding-Fassungen (#731,
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
| Recall@10 | 0,9808 | 0,9808 | 0,0000000000 |
| nDCG@10 | 0,8137 | 0,8137 | 0,0000000000 |
| MRR | 0,7660 | 0,7660 | 0,0000000000 |

Alle drei Metriken, alle drei Teilmengen und die vollständige Rangfolge jeder
einzelnen Query stimmen bis auf Gleitkomma-Rundung (`< 1e-9`) überein
(`test_metadata_context_reproduces_731_numbers_exactly`,
`test_control_check_compares_against_a_fresh_731_run`). Dieser Harness misst
also denselben Suchpfad wie #731 — jeder unten gemeldete Unterschied ist ein
Befund über Kontextsätze, kein Artefakt eines anderen Codepfads.

## Gesamtergebnis

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 0,9808 | 0,8396 | 0,7994 |
| `metadata_context` (Produktionszustand) | 0,9808 | 0,8137 | 0,7660 |
| `model_context` | 0,9808 | **0,8763** | **0,8558** |
| `model_context_de` | 0,9808 | 0,8602 | 0,8337 |

Recall@10 ist über alle vier Arme identisch (0,9808) — das Goldset ist mit elf
Dokumenten gegenüber `k=10` gesättigt (derselbe Effekt wie in
[#708](retrieval-chunk-goldset-708.md#grenzen), [#729](2026-08-08-chunk-fusion-ablation-729.md#grenzen)):
fast jeder Chunk passt in die Top-10, ein Kontextsatz kann höchstens noch den
**Rang** verschieben, nicht mehr den Treffer selbst. Genau das zeigen nDCG@10
und MRR.

**Anders als der Nullbefund in [#729](2026-08-08-chunk-fusion-ablation-729.md)
ist das hier kein flacher Ausgang:** `model_context` gewinnt gegenüber
`metadata_context` **+0,0626 nDCG@10** und **+0,0898 MRR** im Gesamtmittel —
und dieser Abstand **trägt** nach der vorab festgelegten Regel (95-%-Bootstrap-
Intervall schließt die Null nicht ein):

| Vergleich | Δ Recall@10 | Δ nDCG@10 | Δ MRR |
|---|---:|---:|---:|
| `model_context` − `no_context` | +0,0000 | +0,0367 (n. s.) | +0,0564 (n. s.) |
| `model_context` − `metadata_context` | +0,0000 | **+0,0626** (95-%-CI [+0,0055; +0,1320]) | **+0,0898** (95-%-CI [+0,0160; +0,1795]) |
| `model_context_de` − `metadata_context` | +0,0000 | +0,0465 (n. s., CI [-0,0095; +0,1142]) | +0,0677 (n. s., CI [-0,0026; +0,1551]) |
| `model_context` − `model_context_de` | +0,0000 | +0,0161 (n. s.) | +0,0221 (n. s.) |

„n. s." = nicht signifikant nach der Entscheidungsregel unten (Nullwert im
95-%-Intervall enthalten). Methode: gepaarter Bootstrap über die Queries,
10 000 Resamples, Seed 785, 95-%-Perzentilintervall
(`scripts/eval/run_context_ablation_710.py::_scope_delta`, dieselbe Formel wie
in [#731](2026-08-08-embedding-candidates-731.md)).

**Wichtig für die Lesart:** `model_context` (Inhalt in Chunk-Sprache) trägt im
Gesamtmittel gegen die Metadaten, `model_context_de` (derselbe Inhalt, aber
Deutsch erzwungen) trägt **nicht** — obwohl beide Punktschätzer nahe beieinander
liegen (+0,0626 gegen +0,0465). Der direkte Vergleich `model_context` gegen
`model_context_de` (isoliert die Sprache bei gleichem Inhalt) trägt ebenfalls
nicht. Mit 26 Queries reicht die Auflösung nicht, um zwischen „Inhalt trägt,
Sprache ist Nebensache" und „das Signifikanzergebnis kippt an der
Entscheidungsgrenze" zu unterscheiden — siehe [Grenzen](#grenzen).

## Teilmengen: das Gesamtmittel verdeckt den interessanten Fall

Das Gesamtmittel ist auf 11 Dokumenten gesättigt (wie in #729 dokumentiert).
Die drei Teilmengen (`same-language`/`language-gap`/`cross-language`) sind
deshalb **getrennt** ausgewertet, nicht nur als Durchschnitt.

### `language-gap` (6 Queries — deutsche Umgangssprache auf englischen Fachtext)

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 1,0000 | 0,6184 | 0,4917 |
| `metadata_context` | 1,0000 | 0,5675 | 0,4306 |
| `model_context` | 1,0000 | **0,7479** | **0,6667** |
| `model_context_de` | 1,0000 | 0,7440 | 0,6627 |

| Vergleich | Δ nDCG@10 | Δ MRR |
|---|---:|---:|
| `model_context` − `metadata_context` | **+0,1804** (95-%-CI [+0,0240; +0,3701]) | **+0,2361** (95-%-CI [+0,0278; +0,4861]) |
| `model_context_de` − `metadata_context` | +0,1766 (n. s., CI [-0,0114; +0,3762]) | +0,2321 (n. s., CI [-0,0119; +0,5000]) |
| `model_context` − `model_context_de` | +0,0038 (n. s.) | +0,0040 (n. s.) |

**Hier liegt der klarste Effekt des Laufs.** Recall@10 ist in allen vier Armen
bereits 1,0 — jede Variante findet den Zielchunk. Der Unterschied liegt im
Rang, Erster Treffer je Query:

| Query | `no_context` | `metadata_context` | `model_context` | `model_context_de` |
|---|---:|---:|---:|---:|
| q-gap-01 | 2 | 2 | 2 | 1 |
| q-gap-02 | 2 | 4 | 1 | 1 |
| q-gap-03 | 1 | 1 | 1 | 1 |
| q-gap-04 | 5 | 6 | 6 | 7 |
| q-gap-05 | 4 | 2 | 1 | 3 |
| q-gap-06 | 2 | 6 | 3 | 2 |

`model_context` verbessert q-gap-02 (Rang 4 → 1) und q-gap-06 (Rang 6 → 3)
gegenüber `metadata_context` deutlich; q-gap-04 verschlechtert sich leicht
(Rang 6 → 6, unverändert) bzw. bei `model_context_de` sogar (Rang 6 → 7). Der
Gewinn ist also nicht gleichmäßig über alle sechs Queries verteilt, sondern
konzentriert sich auf zwei bis drei Fälle — bei `n=6` ist das die eigentliche
Evidenz, kein Widerspruch zum signifikanten Mittelwert.

### `same-language` (18 Queries)

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 0,9722 | 0,9160 | 0,9074 |
| `metadata_context` | 0,9722 | 0,8955 | 0,8796 |
| `model_context` | 0,9722 | **0,9258** | **0,9306** |
| `model_context_de` | 0,9722 | 0,9038 | 0,9000 |

`model_context` liegt auch hier vorn, aber der Abstand zu `metadata_context`
(+0,0303 nDCG@10, +0,0509 MRR) trägt nach der Entscheidungsregel **nicht**
(95-%-CI schließt die Null ein) — 18 Queries, von denen die meisten bereits
Recall@10 = 1,0 und einen sehr hohen Rang haben, lassen wenig Spielraum für
einen weiteren Ranggewinn.

### `cross-language` (2 Queries — englische Frage auf deutschen Text)

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `no_context` | 1,0000 | 0,8155 | 0,7500 |
| `metadata_context` | 1,0000 | 0,8155 | 0,7500 |
| `model_context` | 1,0000 | 0,8155 | 0,7500 |
| `model_context_de` | 1,0000 | 0,8155 | 0,7500 |

**Alle vier Arme sind hier identisch — Query für Query, nicht nur im
Mittel.** Das ist kein Mess-Artefakt: bei `q-cross-01` liegt der Zielchunk in
allen vier Armen auf Rang 2, bei `q-cross-02` auf Rang 1; die Kandidaten auf
den Rängen 3-5 wechseln zwar zwischen den Armen, das ändert aber weder Recall,
nDCG noch MRR. Mit zwei Queries ist das eine Beobachtung, keine Stichprobe
(siehe [Grenzen](#grenzen)).

## Kosten und Latenz

Zwei getrennt gemessene Posten, wie im #733-Vorbild:

| Posten | n | p50 | p95 | Mittelwert |
|---|---:|---:|---:|---:|
| Kontextsatz-Erzeugung (`claude -p` je Dokument) | 11 | 17 867,6 ms | 22 162,8 ms | 15 129,8 ms |
| bge-m3-Embedding je Text (CPU) | 116 | 150,3 ms | 177,1 ms | 140,7 ms |

Gesamtkosten der Kontextsatz-Erzeugung laut `usage`-Feldern der CLI: **1,50 USD**
für 11 Dokumente / 30 Chunks (`sentences.json::meta.usage_totals`,
`total_cost_usd`). Ein Aufruf pro Dokument statt pro Chunk (alle Chunks eines
Dokuments in einem Prompt) hält die Kosten trotz Cache-Erstellung je Dokument
in diesem Rahmen — bei 30 Chunks über 11 Dokumente sind das rund 0,05 USD je
Chunk. Für ein reales Paper mit deutlich mehr Chunks ist das **kein**
verlässlicher Hochrechnungsfaktor (siehe [Grenzen](#grenzen)): die realen
Kosten für den produktiven Schreibweg misst #710-B (#784), nicht dieses Issue.

## Kontrollergebnis: Sprach-Confound isoliert, nicht nur vermerkt

Der optionale vierte Arm (`model_context_de`) wurde **gebaut**, nicht wegen
Aufwands weggelassen. Er zeigt: der signifikante Effekt von `model_context`
gegenüber `metadata_context` verschwindet, sobald der Modellsatz auf Deutsch
erzwungen wird (`model_context_de` gegen `metadata_context`: n. s.), und der
direkte Sprachvergleich (`model_context` gegen `model_context_de`, gleicher
Inhalt) trägt selbst nicht. Beides zusammen lässt sich **nicht** eindeutig zu
„der Effekt ist Sprache, nicht Inhalt" verdichten — die Punktschätzer von
`model_context_de` liegen ebenfalls über `metadata_context` (+0,0465 nDCG@10),
nur eben knapp außerhalb der Signifikanzschwelle bei `n=26`. Ehrlich berichtet:
**dieser Lauf kann Inhalt und Sprache als Ursache nicht sauber trennen**, er
kann nur ausschließen, dass der gemessene Effekt ausschließlich an der Sprache
hängt (dann müsste `model_context_de` denselben Effekt zeigen wie
`model_context`, tut es aber in der Tendenz — nur nicht signifikant — auch).

## Empfehlung

**Ein inhaltlicher Kontextsatz ist ein plausibler Kandidat für den Schreibweg
aus #783**, mit folgendem Vorbehalt: Der Effekt ist im Gesamtmittel und in der
`language-gap`-Teilmenge signifikant und in eine positive Richtung, aber

1. er ist klein (< 0,1 nDCG@10/MRR) und beruht auf 26 (bzw. 6) Queries,
2. Recall@10 ändert sich in keinem Fall — der Nutzen ist reines Reranking
   innerhalb bereits gefundener Treffer,
3. der Sprachanteil ist nicht sauber isolierbar (siehe oben).

Das ist kein Nullbefund wie in #729, aber auch kein eindeutiger, robuster
Gewinn. Die produktive Anbindung (Weg C, #783/#784) ist damit **weiterhin
gerechtfertigt** zu bauen — der jetzt vorliegende Nachweis liefert einen
positiven, wenn auch schwachen Erstbeleg dafür, dass sich der Aufwand lohnen
kann. Eine harte Go/No-Go-Schwelle folgt aus diesem Lauf nicht.

## Aufbau des Laufs

```
scripts/eval/build_context_sentences_710.py   Live-Generator (zwei Stufen, beide opt-in)
scripts/eval/run_context_ablation_710.py      hermetischer Messlauf, vier Arme
tests/fixtures/context_sentences_710/
├── sentences.json   30 Kontextsatz-Paare (sentence + sentence_de), usage/Latenz je Dokument
└── vectors.json     4 Arme × (30 Chunk- + 26 Query-Vektoren, 1024d), manifest_sha256
```

**Kontextsätze erzeugen** (11 `claude -p`-Aufrufe, ≈ 3 Minuten, ≈ 1,50 USD):

```bash
VAULT_CONTEXT_LIVE_TRANSFORM=1 uv run python \
    scripts/eval/build_context_sentences_710.py --stage sentences
```

**Vektoren erzeugen** (lädt `BAAI/bge-m3`, ≈ 2,3 GB, embeddet 90 Chunk- + 26
Query-Texte live; `metadata_context` wird dabei NICHT neu embedded, sondern
unverändert aus #731 übernommen):

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

- **Kleine Stichprobe in den informativen Teilmengen.** `language-gap` hat
  sechs Queries, `cross-language` zwei. Die Bootstrap-Konfidenzintervalle
  spiegeln das (z. B. `language-gap` nDCG@10: CI-Breite ≈ 0,35) — die
  Richtung ist deutlich, die genaue Größe des Effekts nicht. `cross-language`
  ist mit zwei identischen Beobachtungen eine Anekdote, kein Beleg für
  Wirkungslosigkeit des Kontextsatzes in diesem Fall.
- **Der Sprach-Confound ist isoliert gemessen, aber nicht eindeutig
  aufgelöst** (siehe Abschnitt oben) — `model_context_de` zeigt densel­ben
  Trend wie `model_context`, nur nicht signifikant. Ein größeres Goldset
  könnte hier zwischen „Inhalt trägt" und „Signifikanz kippt nur an der
  Stichprobengröße" unterscheiden; dieser Lauf kann es nicht.
- **Ein einziger Modellsatz je Chunk, aus einem Lauf.** Wie in
  [#733](2026-08-07-hyde-multiquery-733.md#grenzen): ein zweiter Lauf desselben
  Prompts liefert andere Sätze und damit andere Zahlen. Wie groß diese
  Streuung ist, ist hier nicht gemessen.
- **Recall@10 ist an diesem Goldset für keinen Arm unterscheidbar** (Sättigung
  bei elf Dokumenten, wie in #708/#729 dokumentiert). Der gesamte gemessene
  Effekt ist ein Rangeffekt (nDCG@10/MRR), kein Treffereffekt. Ob ein
  inhaltlicher Kontextsatz an einem größeren Korpus auch Recall@10 verändert,
  ist mit diesem Goldset nicht zu beantworten.
- **Kostenzahlen sind ein Einzellauf auf 11 Dokumenten / 30 Chunks**, nicht
  hochrechenbar auf reale Paper mit deutlich mehr Chunks (ein Aufruf pro
  Dokument mit allen Chunks im Prompt skaliert anders als ein Aufruf pro
  Chunk). Die belastbare Kostenmessung für den produktiven Schreibweg ist
  Aufgabe von #710-B (#784), nicht dieses Issues.
- **Nicht im CI-Job `retrieval-goldset` verdrahtet.** `.github/workflows/`
  ist laut `AGENTS.md` protected area (`ci`) und außerhalb des Scopes dieses
  Issues; die Reproduzierbarkeit ist stattdessen über
  `tests/test_issue_710_context_ablation.py` (Teil des Standard-Pytest-Laufs)
  abgesichert. Eine CI-Verdrahtung wie bei #731/#733 wäre ein eigener,
  kleiner Nachtrag.
- **Der produktive Schreibweg selbst ist nicht Teil dieses Laufs.** Weder
  `academic_vault/**` noch der Ingest-Pfad sind angefasst — dieser Lauf
  beantwortet ausschließlich die vorgelagerte Frage aus AC2. Die produktive
  Umsetzung folgt (falls überhaupt) als eigenes Issue, wie im #710-Scope
  festgehalten.
