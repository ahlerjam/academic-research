# Chunk-Fusion sichtbar gemacht: das Probe-Goldset (#790)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-09 · **Modell:** `intfloat/multilingual-e5-small` (384d) ·
**Korpus:** 21 Paper / 71 Chunks · **Queries:** 38 (26 aus [#708](retrieval-chunk-goldset-708.md) + 12 neue Probe-Queries)
**Rohdaten:** [`2026-08-09-chunk-fusion-goldset-790-live-results.json`](2026-08-09-chunk-fusion-goldset-790-live-results.json)
(ein Aufruf, zwei Blöcke: Probe-Set als Hauptmessung, #708-Set als Regressionsanker)

## Was hier belegt wird — und was ausdrücklich nicht

Dieser Lauf belegt **einen Mechanismus**: Chunk-Ebene-Fusion (#727) kann die
Paper-Rangfolge gegenüber Paper-Ebene-Fusion verändern, in beide Richtungen,
und der Auslöser ist genau benennbar. Er belegt **nicht**, wie häufig dieser
Mechanismus in einem echten Vault auftritt.

Die Trennung ist keine Formalie. Das Goldset ist so gebaut, dass der
Mechanismus feuert — das ist sein Zweck. Die gemessenen Deltas sind deshalb
**Effektgrößen unter konstruierten Bedingungen**, keine Schätzung des Nutzens
im Betrieb. Wer diese Zahlen als „Chunk-Fusion bringt +0,37 nDCG" liest, liest
sie falsch. Die Häufigkeitsfrage — wie oft trifft ein realer Vault die
Kippbedingung? — braucht eine Stichprobe echter Vaults und echter Suchanfragen
und ist ein eigenes Vorhaben.

## Vorgeschichte in zwei Sätzen

[#729](2026-08-08-chunk-fusion-ablation-729.md) maß den Umbau auf Chunk-Ebene
gegen das #708-Goldset und fand einen vollständigen Nullbefund.
[#789](2026-08-08-chunk-fusion-ablation-729.md#nachtrag-2026-08-09-789-die-korpus-zu-klein-diagnose-war-unvollständig)
zeigte, dass das nicht an der Korpusgröße lag, sondern an einer strukturell
toten lexikalischen Seite: 1 von 26 Queries erzielte überhaupt einen
`papers_fts`-Treffer, und bei leerer FTS-Trefferliste sind beide
Fusionsvarianten **beweisbar ordnungsgleich**. Dieses Goldset schließt genau
diese Lücke.

## Der Mechanismus, auf den gebaut wird

Von den drei denkbaren Mechanismen ist einer dominant:

| | Mechanismus | Effektgröße |
|---|---|---|
| **M1** | **Signal-Split**: der von `_attach_chunk_to_fts_hit` zugeordnete Chunk ist nicht der Vektor-Bestchunk desselben Papers (oder es gibt gar keinen → synthetischer Schlüssel `fts-paper::<pid>`). Die MAX-Aggregation nimmt dann nur einen der beiden RRF-Summanden statt beider. | ~1,6·10⁻² |
| **M2** | **Crowding**: ein chunkreiches Paper besetzt die vorderen Chunk-Ränge und drückt fremde Bestchunks nach hinten. | ~10⁻³ |
| **M3** | **Tieferer Kandidatenpool** (`k` Paper vs. `k·4` Chunks) — erst bei >10 erreichbaren Papern sichtbar, hier nicht wirksam. | — |

Konkret an `p-gain-01` nachgerechnet, mit den gemessenen Rängen aus
`conditions.json`:

```
Decoy   fts-Rang 1, Vektor-Paperrang 1, KEIN Chunk mit allen Tokens
Ziel    fts-Rang 2, Vektor-Paperrang 2, GENAU EIN solcher Chunk = Vektor-Bestchunk

vorher   Decoy = 1/61 + 1/61 = 0,032787     Ziel = 1/62 + 1/62 = 0,032258   → Decoy vorn
nachher  Decoy = max(1/61, 1/64) = 0,016393  Ziel = 1/64 + 1/62 = 0,031754   → Ziel vorn
```

Der Decoy verliert im `nachher`-Arm einen ganzen RRF-Summanden, weil sein
lexikalischer Treffer unter einem synthetischen Schlüssel läuft, den die
Vektorseite nicht kennt. Das ist der gesamte Effekt.

## Aufbau des Sets

```
tests/fixtures/retrieval_goldset_chunk_fusion_790/
├── sources.json      11 Dokumente + 26 Queries WORTGLEICH aus #708, dazu 10 neue Dokumente und 12 Probe-Queries
├── goldset.json      71 Chunks aus chunk_pages(), Queries mit aufgelösten IDs und 'probe_role'
├── vectors.json      384d-Vektoren; die 30 Alt-Chunks und 26 Alt-Queries byteweise aus #708 übernommen
└── conditions.json   geprüfte Vorbedingungen je Probe-Query (Ergebnis von --verify-probe-conditions)
```

**Die zehn neuen Dokumente** (~12.200 Wörter Chunk-Text, vollständig selbst
geschrieben — wie beim #708-Set liegt bewusst kein fremder Text unter Copyright
im Repo, und nur so ist die Kontrolle über die Zuordnung von Termen zu Chunks
überhaupt herstellbar):

| doc_id | Sprache | Chunks | Rolle |
|---|---|---:|---|
| `en-probe-gain-target` | en | 3 | Ziel für p-gain-01/02/05, Kontrollpaper für p-control-01 |
| `en-probe-gain-decoy` | en | 5 | Decoy mit über Abschnitte verteilten Termen |
| `en-probe-gain-lexicon` | en | 3 | Glossar-Decoy mit termdichten Einzeleinträgen |
| `en-probe-crowd-many` | en | 10 | Crowder (Familie B) |
| `en-probe-crowd-few` | en | 3 | fokussiertes Gegenstück (Familie B) |
| `en-probe-harm-source` | en | 4 | relevantes Paper mit gesplittetem Signal (Familie C) |
| `en-probe-harm-counter` | en | 4 | Distraktor mit geschlossener Fundstelle (Familie C) |
| `de-probe-gain-target` | de | 3 | deutsches Ziel (Familie A) |
| `de-probe-gain-decoy` | de | 4 | deutscher Decoy (Familie A) |
| `de-probe-control-pair` | de | 2 | zweites Kontrollpaper (Familie D) |

**Die zwölf Probe-Queries** in vier Familien, jede mit einem `probe_role` und
einem `probe`-Block, der benennt, welches Paper das gesplittete und welches das
geschlossene Signal trägt:

| Familie | `probe_role` | Queries | Erwartung |
|---|---|---:|---|
| A — Signal-Split, Gewinnrichtung | `gain` | 5 (3 EN, 2 DE) | positives Delta |
| B — Crowding | `crowding` | 2 | schwacher Effekt, Messung der Effektgröße |
| C — Signal-Split, Schadensrichtung | `harm` | 3 | negatives Delta |
| D — Kontrolle | `control` | 2 (1 EN, 1 DE) | Delta exakt 0 |

## Die Vorbedingungen sind geprüft, nicht behauptet

`--verify-probe-conditions` rechnet jede Probe-Query gegen die **echten
Produktionsfunktionen** durch (`server.search_papers`,
`server._attach_chunk_to_fts_hit`, `server._vec0_search`,
`retrieval.reciprocal_rank_fusion`) und bricht mit Klarnamen der verletzenden
Query ab, wenn eine Design-Regel nicht hält. Das Ergebnis steht als
`conditions.json` neben dem Goldset; `conditions_met` ist für alle 12 Queries
`true`.

Die sechs Regeln und wie sie geprüft werden:

1. **Kurz und kommalos** — `","` nicht in der Query, ≤ 4 Tokens, kein
   FTS5-Syntaxfehler. (Ein Komma bricht `papers_fts MATCH` mit
   `sqlite3.OperationalError` ab; jedes zusätzliche Token senkt die
   Trefferchance multiplikativ, weil FTS5 ohne `OR` implizit UND verknüpft.)
2. **Term-Familie in ≥ 2 Dokumenten** — `papers_fts_hit_count >= 2`.
3. **Decoy ohne Volltreffer-Chunk** — `attached_chunk[split_doc] is None`
   (synthetischer Schlüssel) **und** kein `chunk_fts`-Treffer für dieses Paper.
4. **Ziel mit genau einem Volltreffer-Chunk, der zugleich Vektor-Bestchunk
   ist** — `chunk_fts MATCH … AND paper_id = …` liefert genau eine Zeile, und
   `attach_equals_vec_best[coherent_doc] is True`.
5. **Decoy beidseitig stark** — lexikalischer Rang ≤ Ziel-Rang **und**
   Vektor-Paperrang ≤ 2.
6. **Score-Abstand an der Kippstelle > 10⁻⁴** — in beiden Fusionszuständen.

Zu Regel 5 eine Falle, in die eine frühere Fassung dieser Prüfung selbst
getappt ist: `diagnose_query` liefert unter `vec_paper_rank` die **Position des
besten Chunks** eines Papers in der chunk-level Trefferliste (also 1, 4, 5 für
drei Paper), der `vorher`-Arm rankt aber auf **Paper-Ebene** und sieht dieselben
drei Paper als Ränge 1, 2, 3. Design-Regel 5 meint den dichten Paperrang;
`dense_paper_ranks()` rechnet ihn aus, und `conditions.json` führt beide
Größen getrennt (`vec_best_chunk_rank`, `vec_paper_rank`).

## Ergebnis

Reranker in allen drei Zuständen konstant **aus**
(`VAULT_RERANK_LOCAL_DISABLE=1`), wie in #729 — der Lauf ist damit vollständig
hermetisch und misst reinen Index-plus-Fusions-Effekt.

| Zustand | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| **vorher** (paper_id-Fusion) | 0,7895 | 0,6476 | 0,5987 |
| **Zwischenzustand A** (+ Chunk-Anreicherung) | 0,7895 | 0,6476 | 0,5987 |
| **nachher** (chunk_id-Fusion, aktueller Stand) | 0,7895 | **0,6670** | **0,6250** |

| Beitrag | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| Chunk-Anreicherung (A − vorher) | ±0,0000 | ±0,0000 | ±0,0000 |
| **Chunk-Fusion (nachher − A)** | ±0,0000 | **+0,0194** | **+0,0263** |
| Gesamt (nachher − vorher) | ±0,0000 | +0,0194 | +0,0263 |

Dass die Chunk-Anreicherung bei ±0 bleibt, ist auch hier keine Messung, sondern
eine mathematische Notwendigkeit: Paper-Ebene-RRF liest `chunk_id`/`text` an
keiner Stelle, und der Reranker, der sie lesen würde, ist abgeschaltet (siehe
[#729, Grenzen](2026-08-08-chunk-fusion-ablation-729.md#grenzen)).

### Je Familie — hier steckt die eigentliche Aussage

Das Gesamtmittel über 38 Queries verdünnt einen Effekt, der bauartbedingt nur
an 12 davon auftreten kann, und Gewinn- und Schadensfälle heben sich darin
teilweise gegenseitig auf. `deltas_by_case` trennt das:

| Familie | Queries | Δ nDCG@10 | Δ MRR | erwartet? |
|---|---:|---:|---:|---|
| **A — `probe-gain`** | 5 | **+0,3691** | **+0,5000** | ja |
| **B — `probe-crowding`** | 2 | ±0,0000 | ±0,0000 | ja (M2 zu schwach zum Kippen) |
| **C — `probe-harm`** | 3 | **−0,3691** | **−0,5000** | ja |
| **D — `probe-control`** | 2 | ±0,0000 | ±0,0000 | ja |
| `same-language` (#708) | 18 | ±0,0000 | ±0,0000 | ja (Invarianz) |
| `language-gap` (#708) | 6 | ±0,0000 | ±0,0000 | ja (Invarianz) |
| `cross-language` (#708) | 2 | ±0,0000 | ±0,0000 | ja (Invarianz) |

**Alle fünf Gewinn-Queries kippen, alle drei Schadens-Queries kippen, und zwar
jede einzelne um denselben Betrag**: das relevante Paper wandert von Rang 2 auf
Rang 1 (nDCG 0,6309 → 1,0000; MRR 0,5 → 1,0) beziehungsweise umgekehrt. Die
Gleichförmigkeit ist kein Zufall, sondern die Signatur des Mechanismus — ein
Paar aus genau einem relevanten und einem irrelevanten Paper tauscht die Plätze,
und mehr passiert nicht.

### Familie C ist der Punkt, an dem das Set glaubwürdig wird

Ein Goldset, das nur Gewinnfälle enthält, misst die Sorgfalt seines Autors und
nicht den Mechanismus. Familie C dreht **ausschließlich die Relevanz um** — die
Konstruktion ist Regel für Regel dieselbe wie in Familie A, nur trägt hier das
relevante Paper das gesplittete Signal und der Distraktor die geschlossene
Fundstelle. Ergebnis: −0,3691 nDCG, −0,5000 MRR, betragsgleich zu Familie A.

**Das ist ein Befund, kein Kollateralschaden.** Chunk-Fusion belohnt nicht
Relevanz, sondern *lexikalische Geschlossenheit auf Chunk-Ebene*. Wo beides
zusammenfällt, gewinnt sie; wo es auseinanderfällt, verliert sie — mit
derselben Effektgröße. Die Richtung entscheidet allein, ob der von
`_attach_chunk_to_fts_hit` zugeordnete Chunk beim relevanten oder beim
irrelevanten Paper mit dessen Vektor-Bestchunk zusammenfällt.

Das deckt sich mit dem Folge-Issue
[#791](https://github.com/ahlerjam/academic-research/issues/791): der Rückfall
auf den synthetischen Schlüssel `fts-paper::<pid>` kostet den Hybrid-Bonus,
unabhängig davon, ob das betroffene Paper relevant ist. Solange dieser Rückfall
existiert, ist die Richtung des Effekts eine Eigenschaft der Texte und nicht
des Verfahrens. Ob das Verhältnis von Gewinn- zu Schadensfällen im Betrieb
günstig ausfällt, ist genau die Häufigkeitsfrage, die dieses Goldset **nicht**
beantwortet.

### Familie B: M2 ist messbar und zu schwach zum Kippen

Der Crowder (10 Chunks) besetzt die vorderen Chunk-Ränge; der Bestchunk des
fokussierten Dokuments rutscht auf Chunkrang 10 (`p-crowd-01`) beziehungsweise
7 (`p-crowd-02`), während sein **Paperrang** in beiden Fällen 2 bleibt. Genau
diese Schere ist der Mechanismus. Sie verschiebt die Scores messbar, aber nicht
genug für einen Rangwechsel:

| Query | Abstand `vorher` | Abstand `nachher` | Rangwechsel |
|---|---:|---:|---|
| `p-crowd-01` | 5,29·10⁻⁴ | 1,36·10⁻³ | nein |
| `p-crowd-02` | 5,29·10⁻⁴ | 1,73·10⁻³ | nein |

Zum Vergleich: bei den Gewinn-Queries beträgt der Abstand im `nachher`-Arm
1,54·10⁻² — rund eine Größenordnung mehr. Die Vorhersage aus der Planung (M1
etwa 60-mal stärker als M2) hält damit auch empirisch. Familie B liefert die
Effektgröße, kein Fundament.

### Familie D und die 26 Altqueries: die Kontrollen halten

Bei den beiden Kontroll-Queries fällt für **jedes** beteiligte Paper der
zugeordnete Chunk mit dem Vektor-Bestchunk zusammen — unter dieser Bedingung
*kann* die Fusionsgranularität nichts ändern, und sie tut es auch nicht.

Die 26 Altqueries liefern im auf 21 Paper und 71 Chunks gewachsenen Korpus
Query für Query weiterhin Delta 0. Das ist der Invarianztest gegen die
naheliegende Sorge, das neue Material könne die Altmessung verschieben; er ist
als Test festgehalten
(`tests/test_issue_790_probe_goldset.py::test_old_26_queries_keep_a_delta_of_exactly_zero`),
nicht nur als Reportzahl. Der #708-Block der Rohdaten (`baseline`) zeigt
zusätzlich, dass dasselbe Set isoliert gefahren weiterhin den Nullbefund aus
#729 reproduziert.

## Nebenbefund: ein echter Gleichstand (#792)

Auf `p-gain-02` tragen Decoy und Glossar-Decoy im `nachher`-Arm **exakt
denselben** `rrf_score`. Ihre Reihenfolge auf den Rängen 2 und 3 hängt damit
von Pythons Hash-Randomisierung ab, weil `reciprocal_rank_fusion` über ein
`set` von `chunk_id`s iteriert — genau der in
[#792](https://github.com/ahlerjam/academic-research/issues/792) beschriebene
Defekt, hier zum ersten Mal an einem realen Datenstand statt als Konstruktion.

Auf die Metriken wirkt sich das nicht aus (beide Paper sind für diese Query
irrelevant), auf die eingecheckte Trefferliste schon. Der Replay-Schritt setzt
deshalb `PYTHONHASHSEED=0`. Das ist eine Krücke und als solche benannt: sie
macht den Vergleich reproduzierbar, sie behebt den Defekt nicht.

## Grenzen

- **Die Betriebshäufigkeit bleibt offen.** Das ist die wichtigste Grenze und
  steht deshalb schon oben. Dieses Set zeigt, *dass* und *wodurch* der
  Mechanismus wirkt, nicht *wie oft*.
- **Das Set ist konstruiert, und zwar sichtbar.** Die Probe-Queries sind kurze
  Stichwortfolgen mit seltenen Fachtermini; reale Nutzerfragen an das Vault
  sehen eher aus wie die 26 Altqueries (ausgeschriebene Sätze), und für die
  bleibt die lexikalische Seite tot. Die Familien A und C messen einen Effekt
  in einer Query-Sorte, die im Bestand des Vaults bisher kaum vorkommt.
- **Jede Familie hängt an einem einzigen Dokumentenpaar.** Fünf Gewinn-Queries
  sind fünf Term-Familien über drei Dokumentenpaare, nicht fünf unabhängige
  Beobachtungen. Die betragsgleichen Deltas sind deshalb keine Bestätigung
  durch Wiederholung, sondern dieselbe Konstruktion fünfmal.
- **Der Effekt ist ein reiner Rangtausch auf den Plätzen 1 und 2.** Recall@10
  bleibt in allen Familien unverändert; nur nDCG@10 und MRR bewegen sich. Bei
  21 Papern und `k=10` passt der halbe Bestand in die Trefferliste — dieselbe
  Sättigungsgrenze wie in #708 und #729.
- **Reranker konstant aus.** Der reale Produktivpfad hat den lokalen Reranker
  per Default aktiv. Ein aktiver Reranker sieht das von
  `_attach_chunk_to_fts_hit` angereicherte `text`-Feld und könnte den hier
  gemessenen Effekt sowohl verstärken als auch überschreiben; gemessen ist das
  nicht.
- **Chunkgrenzen sind Datenlage, nicht hermetisch reproduzierbar.** Wie beim
  #708-Set: hermetisch fällt `chunk_pages()` auf `approximate_token_count`
  zurück und setzt die Grenzen anders als der echte e5-Tokenizer. Die
  eingecheckten Chunks stammen aus einem Lauf mit dem echten Tokenizer.
- **`vorher` ist ein Shim.** Unverändert übernommen aus #729 (dort unter
  [Grenzen](2026-08-08-chunk-fusion-ablation-729.md#grenzen) beschrieben und
  differenziell gegen den historischen Code geprüft).

## Reproduktion

Messlauf (hermetisch, kein Modell-Download, unter 30 Sekunden):

```bash
PYTHONHASHSEED=0 uv run python scripts/eval/run_retrieval_ablation_729.py \
  --goldset tests/fixtures/retrieval_goldset_chunk_fusion_790/goldset.json \
  --vectors tests/fixtures/retrieval_goldset_chunk_fusion_790/vectors.json \
  --baseline-goldset tests/fixtures/retrieval_goldset_chunks_708/goldset.json \
  --baseline-vectors tests/fixtures/retrieval_goldset_chunks_708/vectors.json \
  --skip-cost \
  --out docs/evals/2026-08-09-chunk-fusion-goldset-790-live-results.json
```

Die Fixture neu erzeugen (lädt Tokenizer und e5-small, ~470 MB beim ersten Mal;
die 30 Alt-Chunk- und 26 Alt-Query-Vektoren werden byteweise übernommen, nur
der Zuwachs wird embeddet):

```bash
VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_retrieval_chunk_goldset.py \
  --sources tests/fixtures/retrieval_goldset_chunk_fusion_790/sources.json \
  --goldset-out tests/fixtures/retrieval_goldset_chunk_fusion_790/goldset.json \
  --vectors-out tests/fixtures/retrieval_goldset_chunk_fusion_790/vectors.json \
  --conditions-out tests/fixtures/retrieval_goldset_chunk_fusion_790/conditions.json \
  --reuse-vectors tests/fixtures/retrieval_goldset_chunks_708/vectors.json \
  --verify-probe-conditions --issue 790 --skip-thresholds-report
```

Exit 3 bedeutet: mindestens eine Probe-Query verletzt ihre Vorbedingungen, und
die verletzenden Regeln stehen mit Query-Namen auf stderr. Dann sind die Texte
nachzuziehen — **nicht** die Regeln.

Das Modell bleibt bewusst `intfloat/multilingual-e5-small` und folgt nicht dem
Produktionsdefault `BAAI/bge-m3` (#732): die 30 Alt-Chunks und 26 Alt-Queries
sollen ihre eingecheckten Vektoren behalten, der gemessene Mechanismus hängt an
der KNN-Reihenfolge und nicht am Modell, und der Download ist 470 MB statt
2,3 GB.

## Was als Nächstes zu klären wäre

- **Häufigkeit im Betrieb** (eigenes Vorhaben): Wie oft weicht in einem echten
  Vault der von `_attach_chunk_to_fts_hit` zugeordnete Chunk vom Vektor-Bestchunk
  ab, und wie verteilt sich das auf relevante und irrelevante Paper? Das
  entscheidet, ob Familie A oder Familie C den Alltag beschreibt.
- **[#791](https://github.com/ahlerjam/academic-research/issues/791)**: der
  synthetische Schlüssel kostet den Hybrid-Bonus. Fiele er auf den
  Vektor-Bestchunk statt auf `fts-paper::<pid>` zurück, verschwänden Familie A
  und Familie C beide — der Mechanismus wäre dann kein Ranking-Hebel mehr.
- **[#792](https://github.com/ahlerjam/academic-research/issues/792)**: der
  Gleichstand auf `p-gain-02` ist ein reproduzierbarer Testfall dafür.
