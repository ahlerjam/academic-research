# Trägt der Umbau auf Chunk-Ebene? (#729)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand.

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-08 · **Goldset:** Chunk-Goldset aus [#708](retrieval-chunk-goldset-708.md),
11 Paper / 30 Chunks / 26 Queries · **Kosten-Korpus:** 60 synthetische Paper / 194 Chunks
**Rohdaten:** [`2026-08-08-chunk-fusion-ablation-729-live-results.json`](2026-08-08-chunk-fusion-ablation-729-live-results.json)

## Fragestellung

[#726](https://github.com/ahlerjam/academic-research/issues/726) fügte den
chunk-level FTS5-Index `chunk_fts` hinzu.
[#727](https://github.com/ahlerjam/academic-research/issues/727) stellte
`reciprocal_rank_fusion()` von `paper_id`- auf `chunk_id`-Schlüsselung um und
verschob die Paper-Aggregation (`server._aggregate_chunks_to_papers`) NACH die
Fusion statt davor. Beide Änderungen sind strukturell begründet — zwei Chunks
desselben Papers sollen sich in der Fusion nicht mehr gegenseitig verdrängen —,
aber bislang nicht gegen ein Goldset gemessen. Dieser Lauf holt das nach und
trennt zwei Beiträge, die in einer einzigen Vorher/Nachher-Zahl untergehen
würden:

1. **Der Chunk-FTS-Index selbst** (#726): lexikalische Treffer aus dem vollen
   Chunk-Text statt nur aus Titel/Abstract (`papers_fts`/`papers_trgm`).
2. **Die Fusionsgranularität** (#727): mehrere Chunks desselben Papers dürfen
   die RRF-Fusion einzeln durchlaufen, statt vorher auf einen Kandidaten pro
   Paper eingedampft zu werden.

Dafür misst der Harness (`scripts/eval/run_retrieval_ablation_729.py`) drei
Zustände statt zwei:

| Zustand | Lexikalische Seite | Fusion |
|---|---|---|
| **vorher** | `papers_fts`/`papers_trgm` (Titel/Abstract, wie vor #726) | `paper_id` (wie vor #727) |
| **Zwischenzustand A** | `chunk_fts` (voller Chunk-Text, #726) | `paper_id` (wie vor #727) |
| **nachher** | `chunk_fts` | `chunk_id` (#727, aktueller Produktionscode) |

`Δ(A − vorher)` isoliert den Indexbeitrag, `Δ(nachher − A)` den
Fusionsbeitrag — bei gleichbleibender Fusionsgranularität bzw. gleichbleibendem
Index in jeweils einem der beiden Schritte.

## Ergebnis: Retrieval-Qualität (AC1/AC2)

Reranker in allen drei Zuständen konstant **aus**
(`VAULT_RERANK_LOCAL_DISABLE=1`) — Reranking (#702/#703/#714) ist bereits in
[#722](retrieval-ablation-722.md) separat vermessen und kein Teil dieses
Umbaus; konstant Aus macht diesen Lauf vollständig **hermetisch** (kein
Modell-Download, siehe [Reproduktion](#reproduktion)) und hält den Effekt
sauber auf Index+Fusion beschränkt.

| Zustand | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| **vorher** (papers_fts, paper_id-Fusion) | 0,7308 | 0,6619 | 0,6394 |
| **Zwischenzustand A** (chunk_fts, paper_id-Fusion) | 0,7308 | 0,6619 | 0,6394 |
| **nachher** (chunk_fts, chunk_id-Fusion — aktueller Stand) | 0,7308 | 0,6619 | 0,6394 |

**Alle drei Zustände sind auf diesem Goldset identisch — nicht nur im
Aggregat, sondern Query für Query.** Ein Vergleich der vollständigen
Trefferlisten (`retrieved`) zeigt für alle 26 Queries dieselbe Paper-Reihenfolge
in allen drei Zuständen; auch die Teilmengen-Aufschlüsselung (`same-language`
0,9444/0,8829/0,8611, `language-gap` 0,1667/0,1667/0,1667, `cross-language`
0,5000/0,1577/0,0625, je Recall/nDCG/MRR) ist über alle drei Zustände
bitgleich. Damit sind sämtliche Deltas exakt null:

| Beitrag | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| Chunk-FTS-Index (A − vorher) | ±0,0000 | ±0,0000 | ±0,0000 |
| Chunk-Fusion (nachher − A) | ±0,0000 | ±0,0000 | ±0,0000 |
| Gesamt (nachher − vorher) | ±0,0000 | ±0,0000 | ±0,0000 |

Keine Metrik verschlechtert sich — es gibt aber auch keinen messbaren Gewinn.
**AC4 ist damit erfüllt, aber mit dem am wenigsten interessanten Ausgang**:
weder Regression noch Verbesserung.

### Warum die Nullen strukturell erklärbar sind (nicht verschwiegen)

Ein manueller Vergleich der Zwischenwerte zeigt, dass die Nullen keine
Bugs sind, sondern eine Eigenschaft dieses konkreten, kleinen Goldsets:

- **Der Korpus ist mit 11 Papern winzig gegenüber `k=10`.** Fast der gesamte
  Bestand passt in die Trefferliste — genau der Sättigungseffekt, den schon
  [#708](retrieval-chunk-goldset-708.md#grenzen) und
  [#722](retrieval-ablation-722.md#grenzen) für Recall@10 dokumentieren.
- **Jedes Paper hat vollständige Chunk-Embeddings.** Jedes Paper, das
  `chunk_fts` oder `papers_fts` überhaupt findet, wird auch vom Vektorpfad
  gefunden — der Index-Wechsel (Titel/Abstract → voller Chunk-Text) verändert
  deshalb nie, WELCHE Paper in der Trefferliste landen, nur potenziell ihre
  Rangposition über den RRF-Score.
- **Die Fusionsgranularität ändert Rangzahlen, nicht zwingend die
  Rangreihenfolge.** Chunk-Level-Fusion lässt mehrere Chunks desselben Papers
  gemeinsam durch die Fusion laufen; die Paper-Aggregation danach nimmt aber
  ohnehin nur den JEWEILS BESTEN Chunk je Paper (MAX-Aggregation, #727). Bei
  nur 11 Papern und wenigen Chunks pro Paper reicht der zusätzliche
  "Rangdruck" durch fremde Zweit-/Drittchunks in der Praxis nicht aus, um die
  Reihenfolge der Paper-Bestwerte zu kippen — er verschiebt Rangzahlen
  (siehe [Kosten](#ergebnis-index--und-laufzeitkosten-ac3)), aber nicht die
  finale Sortierung.

Das ist dieselbe Art Befund wie schon in #722 für #702/#703: **eine gemessene
Null bestätigt nicht, dass die Änderung wirkungslos ist — sie bestätigt, dass
dieses Goldset zu klein ist, um den Effekt zu zeigen.** Der strukturelle
Vorteil des Umbaus (kein gegenseitiges Verdrängen von Chunks desselben Papers,
präzisere Rangwerte) bleibt plausibel; er kommt nur bei mehr Papern pro Thema
und mehr Chunks pro Paper zum Tragen, als dieses 11-Paper-Set bietet.

## Ergebnis: Index- und Laufzeitkosten (AC3)

Gemessen an einem synthetischen Vault mit **60 Papern / 194 Chunks**
(Minimum aus AC3: 50) — vollständig hermetisch: ein deterministischer
Fake-Embedder (`_DeterministicEmbedder`, seed-basiert, L2-normalisiert)
ersetzt das echte e5-Modell. Das ist für diese Messung ausreichend, weil
Index-Größe und Suchlatenz von Text-/Chunk-**Volumen** und der SQL-/vec0-
Mechanik abhängen, nicht von der semantischen Qualität der Vektoren — anders
als bei AC1/AC2 oben, wo echte, geurteilte Relevanz gebraucht wird.

### Index-Zuwachs

| | ohne `chunk_fts` | mit `chunk_fts` | Zuwachs |
|---|---:|---:|---:|
| Dateigröße | 2.830.336 Bytes (2,70 MiB) | 3.207.168 Bytes (3,06 MiB) | **+376.832 Bytes (+13,31 %)** |

Beide Datenbanken enthalten denselben Chunk-Bestand (194 Chunks über 60
Paper) — der einzige Unterschied ist die An-/Abwesenheit der
`chunk_fts`-Tabelle samt Triggern. Der Index kostet an diesem Korpus rund ein
Achtel der Vault-Größe.

### Suchlatenz

Einzelabfrage, Reranker aus (isoliert Index+Fusion von der — unveränderten,
in #722 separat vermessenen — Reranker-Kosten), 12 Queries × 3 Wiederholungen
(n=36 je Zustand):

| Zustand | p50 | p95 | Mittelwert |
|---|---:|---:|---:|
| **vorher** (papers_fts, paper_id-Fusion) | 5,776 ms | 6,830 ms | 5,948 ms |
| **Zwischenzustand A** (chunk_fts, paper_id-Fusion) | 5,934 ms | 7,530 ms | 6,096 ms |
| **nachher** (chunk_fts, chunk_id-Fusion) | 7,092 ms | 10,237 ms | 7,556 ms |

Der **Chunk-FTS-Index allein kostet kaum etwas** (5,776 → 5,934 ms p50, rund
+2,7 %) — die zusätzliche Abfrage über `chunk_fts` statt `papers_fts` ist
günstig. Der **eigentliche Laufzeitpreis liegt in der Chunk-Ebene-Fusion**
(5,934 → 7,092 ms p50, rund +19,5 %; p95 sogar +36 %): mehr Kandidaten
(bis zu `k*4` Chunks statt `k` Paper) durchlaufen RRF und die
Paper-Aggregation danach. Das ist genau die Kostenseite, die AC3 verlangt,
getrennt nach Index und Fusion ausgewiesen wie bei der Qualität oben.

Auf absoluter Ebene bleibt der Umbau günstig: +1,3 ms Median-Latenz bei k=10
gegen 60 Paper ist im Kontext einer Suche, die ohnehin durch Reranking
(Größenordnung Sekunden bei aktivem lokalem Modell, siehe #731) dominiert
wird, keine spürbare Größe.

## Empfehlung

**Nicht zurückrollen** — trotz der gemessenen Null bei der Qualität. Drei
Gründe:

1. Die Null ist eine Aussage über dieses Goldset (11 Paper, gesättigt), nicht
   über den Mechanismus (siehe [Erklärung oben](#warum-die-nullen-strukturell-erklärbar-sind-nicht-verschwiegen)).
   Ein Zurückrollen wegen eines Nulleffekts, den ein zu kleines Set gar nicht
   zeigen kann, würde einen echten, nur nicht gemessenen Nutzen kassieren.
2. Der strukturelle Fehler, den #727 behoben hat — zwei Chunks desselben
   Papers verdrängen sich in der Fusion gegenseitig — bleibt korrekt
   beschrieben und ist unabhängig von diesem Goldset nachvollziehbar (siehe
   #727-Issue-Text und Code-Kommentare in `academic_vault/retrieval.py`).
3. Die Kostenseite ist moderat (+13 % Indexgröße, +1,3 ms Median-Latenz bei
   60 Papern) und rechtfertigt für sich allein keinen Rückbau, selbst ohne
   nachgewiesenen Qualitätsgewinn.

Sollte ein größeres, mit mehr thematisch überlappenden Papern gebautes
Goldset (siehe [Grenzen](#grenzen)) künftig eine Regression zeigen, ist das
ein eigener Befund und eigenes Issue — dieser Lauf liefert dafür keinen
Hinweis.

## Grenzen

- **Das Goldset ist zu klein, um den Effekt zu zeigen — das ist der
  Kernbefund dieses Laufs, nicht nur eine Fußnote.** 11 Paper und 30 Chunks
  bei `k=10` sättigen praktisch den gesamten Bestand; die Fusionsgranularität
  kann unter diesen Bedingungen kaum eine andere Rangreihenfolge erzeugen als
  die Paper-Ebene-Fusion. Eine belastbare Aussage über den Qualitätsgewinn des
  Umbaus bräuchte ein Goldset mit deutlich mehr Papern pro Thema (viele
  Kandidaten, die um dieselbe Query konkurrieren) und mehreren
  Chunks pro Paper, die unterschiedlich stark zur Query passen — beides ist
  laut Scope dieses Issues **out of scope** (keine Goldset-Erweiterung).
- **Reranker konstant deaktiviert.** Der reale Produktivpfad hat den lokalen
  Reranker per Default aktiv; die hier gemessenen Qualitätszahlen bilden
  reinen Index+Fusion-Effekt ab, nicht die vollständige Pipeline inklusive
  Reranking. #722 hat den Reranker-Beitrag bereits separat vermessen
  (+0,0107 nDCG / +0,0144 MRR auf demselben Goldset); dieser Lauf ergänzt ihn,
  ersetzt ihn nicht.
- **Derselbe vorbestehende FTS5-Komma-Defekt wie in #722** entfernt 7 von 26
  Queries aus der Qualitätsmessung (`db._sanitize_fts5_query` haertet kein
  Komma ab, MATCH bricht mit `sqlite3.OperationalError` ab) — betroffen sind
  dieselben sieben Queries wie in [#722](retrieval-ablation-722.md#grenzen)
  (`fts5_syntax_errors` in den Rohdaten), unabhängig davon, ob `chunk_fts`
  oder `papers_fts` befragt wird. Außerhalb des Scopes dieses Issues
  (`area/vault` geschützt) — bereits als eigener Befund in #722 dokumentiert.
- **Der Kosten-Korpus ist synthetisch und bedeutungslos** (Wortsalat aus
  einem 40-Wörter-Vokabular). Das ist für Index-Größe und Latenz
  ausreichend — beide hängen an Volumen und SQL-/vec0-Mechanik, nicht an
  Bedeutung —, aber die absoluten Zahlen (194 Chunks über 60 Paper, im Mittel
  3,2 Chunks je Paper) sind kleiner als ein typischer realer Vault (deutlich
  mehr Chunks pro Paper bei echten Volltexten). Die *relativen* Kostenanteile
  (Index +13 %, Fusion +19,5 % Median-Latenz) sind die belastbare Aussage,
  nicht die absoluten Millisekunden/Bytes.
- **Eine Maschine, ein Lauf.** Latenzwerte stammen von einer einzelnen
  Messumgebung; die Größenordnung (Fusion kostet mehr als der Index) sollte
  über Hardware hinweg stabil sein, die genauen Millisekundenwerte nicht.
- **`vorher`-Zustand ist ein Shim.** Weder #726 noch #727 sind über einen
  Produktionsschalter erreichbar (beide Pfade wurden vollständig ersetzt).
  Der Shim (`search_papers_paper_level` in
  `scripts/eval/run_retrieval_ablation_729.py`) reimplementiert die
  historische Fusion (`_paper_id_rrf`, bitgleich zu Commit `a32f570^`) und
  die historische Vektor-Aggregation (`_vec0_search_paper_level`, ruft die
  aktuelle, unveränderte KNN-Suche auf und dedupliziert genau wie der
  historische Code) — differenziell gegen den dokumentierten historischen
  Stand geprüft in `tests/test_issue_729_chunk_fusion_ablation.py`, nicht
  durch Wiederausführung des historischen Codes selbst.

## Reproduktion

```bash
uv run python scripts/eval/run_retrieval_ablation_729.py \
  --out docs/evals/2026-08-08-chunk-fusion-ablation-729-live-results.json
```

Vollständig hermetisch — kein `VAULT_E5_LIVE_TEST=1` nötig, kein
Netzzugriff, kein Modell-Download. Laufzeit auf der Messmaschine unter
5 Sekunden. `--skip-cost` lässt AC3 (Index/Latenz) aus, falls nur die
Qualitätszahlen interessieren.
