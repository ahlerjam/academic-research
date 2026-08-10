# Trägt der Umbau auf Chunk-Ebene? (#729)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand.
>
> **Datenstand 2026-08-10 (#800).** Das #708-Goldset wurde von 26 auf 60
> Queries (30 auf 61 Chunks) verbreitert. Der Report unten beschreibt weiterhin
> ausschließlich den ursprünglichen 26-Query/30-Chunk-Lauf vom 2026-08-08 und
> ist nicht auf den breiteren Stand nachgezogen — die Tabellen (0,7308
> Recall@10 für „vorher") und die eingecheckte
> `2026-08-08-chunk-fusion-ablation-729-live-results.json` gelten
> ausschließlich für diesen historischen 26-Query-Lauf. Der aktuell erwartete
> Wert auf dem #800-verbreiterten Goldset ist 0,5667 Recall@10 für „vorher"
> (`tests/test_issue_729_chunk_fusion_ablation.py::test_run_quality_ablation_matches_pre_708_baseline_values`,
> gegen die eingecheckte #708-Fixture nachgerechnet, kein eigener Report).

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-08 (historischer Referenzlauf, siehe Datenstands-Hinweis
oben) · **Goldset:** Chunk-Goldset aus [#708](retrieval-chunk-goldset-708.md),
11 Paper / 30 Chunks / 26 Queries · **Kosten-Korpus:** 60 synthetische Paper / 194 Chunks
**Rohdaten:** [`2026-08-08-chunk-fusion-ablation-729-live-results.json`](2026-08-08-chunk-fusion-ablation-729-live-results.json)
(einziger, durchgängiger Lauf — Tabellen unten und JSON stammen aus demselben Aufruf)

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

1. **Die Chunk-Anreicherung** (#726, über `server._attach_chunk_to_fts_hit`
   aus #727): jedem `papers_fts`/`papers_trgm`-Treffer wird sein
   best-passender Chunk zugeordnet.
2. **Die Fusionsgranularität** (#727): mehrere Chunks desselben Papers dürfen
   die RRF-Fusion einzeln durchlaufen, statt vorher auf einen Kandidaten pro
   Paper eingedampft zu werden.

**Wichtige Korrektur gegenüber einer früheren Fassung dieses Laufs** (PR-Review-Fund):
`chunk_fts` ist im echten Produktionscode **nie eine eigene lexikalische
Suchquelle**. Die Kandidaten-SUCHE läuft in jedem gemessenen Zustand über
`papers_fts`/`papers_trgm` (Titel/Abstract/Volltext, unverändert seit #703,
`server.search_papers` Zeilen 1011–1024). `chunk_fts` kommt erst danach ins
Spiel: `server._attach_chunk_to_fts_hit` (#727) nutzt den #726-Index
ausschließlich als **Lookup** — für ein bereits über `papers_fts` gefundenes
Paper wird der best-passende Chunk nachgeschlagen, nicht neu gesucht. Der
Harness (`scripts/eval/run_retrieval_ablation_729.py`) misst deshalb drei
Zustände, deren lexikalische Kandidatenquelle **immer** `papers_fts` ist:

| Zustand | Kandidaten-Suche | Chunk-Anreicherung | Fusion |
|---|---|---|---|
| **vorher** | `papers_fts`/`papers_trgm` | nein | `paper_id` (wie vor #727) |
| **Zwischenzustand A** | `papers_fts`/`papers_trgm` | ja (`_attach_chunk_to_fts_hit`, #726/#727) | `paper_id` (wie vor #727) |
| **nachher** | `papers_fts`/`papers_trgm` | ja | `chunk_id` (#727, aktueller Produktionscode) |

`Δ(A − vorher)` isoliert den Beitrag der Chunk-Anreicherung, `Δ(nachher − A)`
den Beitrag der Fusionsgranularität — bei gleichbleibender
Fusionsgranularität bzw. gleichbleibender Anreicherung in jeweils einem der
beiden Schritte.

## Ergebnis: Retrieval-Qualität (AC1/AC2)

Reranker in allen drei Zuständen konstant **aus**
(`VAULT_RERANK_LOCAL_DISABLE=1`) — Reranking (#702/#703/#714) ist bereits in
[#722](retrieval-ablation-722.md) separat vermessen und kein Teil dieses
Umbaus; konstant Aus macht diesen Lauf vollständig **hermetisch** (kein
Modell-Download, siehe [Reproduktion](#reproduktion)) und hält den Effekt
sauber auf Index+Fusion beschränkt.

| Zustand | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| **vorher** (papers_fts, keine Anreicherung, paper_id-Fusion) | 0,7308 | 0,6619 | 0,6394 |
| **Zwischenzustand A** (papers_fts + Chunk-Anreicherung, paper_id-Fusion) | 0,7308 | 0,6619 | 0,6394 |
| **nachher** (papers_fts + Chunk-Anreicherung, chunk_id-Fusion — aktueller Stand) | 0,7308 | 0,6619 | 0,6394 |

**Alle drei Zustände sind auf diesem Goldset identisch — nicht nur im
Aggregat, sondern Query für Query.** Damit sind sämtliche Deltas exakt null:

| Beitrag | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| Chunk-Anreicherung (A − vorher) | ±0,0000 | ±0,0000 | ±0,0000 |
| Chunk-Fusion (nachher − A) | ±0,0000 | ±0,0000 | ±0,0000 |
| Gesamt (nachher − vorher) | ±0,0000 | ±0,0000 | ±0,0000 |

Keine Metrik verschlechtert sich — es gibt aber auch keinen messbaren Gewinn.
**AC4 ist damit erfüllt, aber mit dem am wenigsten interessanten Ausgang**:
weder Regression noch Verbesserung.

### Warum die Nullen erklärbar sind — zwei verschiedene Gründe, nicht einer

Die beiden Nullen oben haben **unterschiedliche Ursachen** — das ist der
wichtigste Punkt dieses Abschnitts, nicht nur eine Fußnote:

- **Δ(Chunk-Anreicherung) = 0 ist eine mathematische Notwendigkeit, kein
  empirischer Befund.** Bei Paper-Ebene-RRF-Fusion (`paper_id`-Schlüssel)
  bestimmen ausschließlich die Rangpositionen von `paper_id` in den
  Vektor-/FTS-Ranglisten den `rrf_score` — `chunk_id` und `text`, die
  `_attach_chunk_to_fts_hit` ergänzt, fließen in diese Rechnung an keiner
  Stelle ein. Sie würden erst wirken, sobald ein Reranker das angereicherte
  `text`-Feld tatsächlich liest — und der ist in diesem Lauf konstant
  deaktiviert (siehe oben). `tests/test_issue_729_chunk_fusion_ablation.py::test_zwischenzustand_a_is_identical_to_vorher_when_reranker_disabled`
  hält das als Regressionstest fest: **ohne Reranker kann dieser Lauf den
  Beitrag der Chunk-Anreicherung strukturell nicht zeigen**, unabhängig vom
  Goldset. Um ihn zu messen, müsste der Reranker aktiv sein — das würde die
  Messung nicht mehr hermetisch machen und den bereits in #722 separat
  vermessenen Reranker-Effekt wieder hineinmischen.
- **Δ(Chunk-Fusion) = 0 ist dagegen ein empirischer, goldset-abhängiger
  Befund** — hier könnte die Fusionsgranularität durchaus etwas zeigen, tut es
  auf diesem Goldset aber nicht:
  - **Der Korpus ist mit 11 Papern winzig gegenüber `k=10`.** Fast der gesamte
    Bestand passt in die Trefferliste — derselbe Sättigungseffekt, den schon
    [#708](retrieval-chunk-goldset-708.md#grenzen) und
    [#722](retrieval-ablation-722.md#grenzen) für Recall@10 dokumentieren.
  - **Jedes Paper hat vollständige Chunk-Embeddings.** Jedes Paper, das
    `papers_fts` überhaupt findet, wird auch vom Vektorpfad gefunden.
  - **Die Paper-Aggregation nimmt ohnehin nur den besten Chunk je Paper**
    (MAX-Aggregation, #727). Bei nur 11 Papern und wenigen Chunks pro Paper
    reicht der zusätzliche Rangdruck durch fremde Zweit-/Drittchunks in der
    Praxis nicht aus, um die Reihenfolge der Paper-Bestwerte zu kippen.

Das ist derselbe Typ Befund wie schon in #722 für #702/#703: **eine gemessene
Null bestätigt nicht, dass die Änderung wirkungslos ist.** Für die
Chunk-Anreicherung gilt das im striktesten Sinn (per Konstruktion unter
diesem Messaufbau nicht zeigbar); für die Chunk-Fusion gilt es im
schwächeren, goldset-abhängigen Sinn (dieses kleine Set zeigt es nicht, ein
größeres könnte).

## Ergebnis: Index- und Laufzeitkosten (AC3)

Gemessen an einem synthetischen Vault mit **60 Papern / 194 Chunks**
(Minimum aus AC3: 50) — vollständig hermetisch: ein deterministischer
Fake-Embedder (`_DeterministicEmbedder`, seed-basiert, L2-normalisiert)
ersetzt das echte e5-Modell. Das ist für diese Messung ausreichend, weil
Index-Größe und Suchlatenz von Text-/Chunk-**Volumen** und der SQL-/vec0-
Mechanik abhängen, nicht von der semantischen Qualität der Vektoren — anders
als bei AC1/AC2 oben, wo echte, geurteilte Relevanz gebraucht wird.

### Index-Zuwachs

Beide Datenbanken (mit/ohne `chunk_fts`) enthalten denselben Chunk-Bestand
(194 Chunks über 60 Paper) und werden **gleich behandelt** — beide per
`PRAGMA wal_checkpoint` + `VACUUM` kompaktiert, damit der Größenvergleich
nicht durch unterschiedlich fragmentierte Dateien verzerrt wird (Korrektur
gegenüber einer früheren Fassung dieses Laufs, die nur eine Variante
VACUUMte).

| | ohne `chunk_fts` | mit `chunk_fts` | Zuwachs |
|---|---:|---:|---:|
| Dateigröße | 2.830.336 Bytes (2,70 MiB) | 3.182.592 Bytes (3,04 MiB) | **+352.256 Bytes (+12,45 %)** |

Der Index kostet an diesem Korpus rund ein Achtel der Vault-Größe.

### Suchlatenz

Einzelabfrage, Reranker aus (isoliert Index+Fusion von der — unveränderten,
in #722 separat vermessenen — Reranker-Kosten), 12 Queries × 3 Wiederholungen
(n=36 je Zustand). Der Vektor-Kandidatenpool ist an allen drei Stellen
`max(k*4, k)` — ein PR-Review-Fund an einer früheren Fassung dieses Skripts
hatte diesen Pool im `vorher`/`A`-Shim versehentlich auf das 16-Fache statt
das 4-Fache aufgeblasen (doppelte Multiplikation); korrigiert.

| Zustand | p50 | p95 | Mittelwert |
|---|---:|---:|---:|
| **vorher** (papers_fts, keine Anreicherung, paper_id-Fusion) | 4,830 ms | 6,234 ms | 5,326 ms |
| **Zwischenzustand A** (+ Chunk-Anreicherung, paper_id-Fusion) | 4,844 ms | 5,537 ms | 4,919 ms |
| **nachher** (+ Chunk-Fusion, aktueller Stand) | 7,018 ms | 8,785 ms | 7,141 ms |

Bei `p50` zeigt sich hier — konsistent mit der Qualitätsseite oben — dass die
**Chunk-Anreicherung selbst so gut wie nichts kostet** (4,830 → 4,844 ms,
+0,29 %; der eine zusätzliche `chunk_fts`-Lookup pro Kandidat ist billig).
**Der eigentliche Laufzeitpreis liegt in der Chunk-Ebene-Fusion**
(4,844 → 7,018 ms p50, **+44,9 %**): mehr Kandidaten (bis zu `k*4` Chunks
statt `k` Paper) durchlaufen RRF und die Paper-Aggregation danach. Bei `p95`
ist das Bild verrauschter (Zwischenzustand A liegt dort sogar *unter*
`vorher`, −11,2 % — bei n=36 und Millisekunden-Größenordnung ist das
Messrauschen, keine reale Beschleunigung durch die Anreicherung; siehe
[Grenzen](#grenzen)), aber auch hier trägt der Sprung von A zu `nachher`
(+58,7 % p95) den gesamten Effekt.

Auf absoluter Ebene bleibt der Umbau günstig: rund +2 ms Median-Latenz bei
k=10 gegen 60 Paper ist im Kontext einer Suche, die ohnehin durch Reranking
(Größenordnung Sekunden bei aktivem lokalem Modell, siehe #731) dominiert
wird, keine spürbare Größe.

## Empfehlung

**Nicht zurückrollen** — trotz der gemessenen Null bei der Qualität. Drei
Gründe:

1. Die Nullen sind Aussagen über diesen Messaufbau bzw. dieses Goldset, nicht
   über den Mechanismus (siehe [Erklärung oben](#warum-die-nullen-erklärbar-sind--zwei-verschiedene-gründe-nicht-einer)).
   Ein Zurückrollen wegen eines Nulleffekts, den dieser Aufbau (Reranker aus)
   bzw. dieses kleine Goldset gar nicht zeigen kann, würde einen echten, nur
   nicht gemessenen Nutzen kassieren.
2. Der strukturelle Fehler, den #727 behoben hat — zwei Chunks desselben
   Papers verdrängen sich in der Fusion gegenseitig — bleibt korrekt
   beschrieben und ist unabhängig von diesem Goldset nachvollziehbar (siehe
   #727-Issue-Text und Code-Kommentare in `academic_vault/retrieval.py`).
3. Die Kostenseite ist moderat (+12,45 % Indexgröße, rund +2 ms Median-Latenz
   bei 60 Papern, davon der Großteil durch die Fusion und nicht den Index)
   und rechtfertigt für sich allein keinen Rückbau, selbst ohne
   nachgewiesenen Qualitätsgewinn.

Sollte ein größeres, mit mehr thematisch überlappenden Papern gebautes
Goldset (siehe [Grenzen](#grenzen)) künftig eine Regression zeigen, ist das
ein eigener Befund und eigenes Issue — dieser Lauf liefert dafür keinen
Hinweis.

## Grenzen

- **Der Beitrag der Chunk-Anreicherung ist mit diesem Messaufbau (Reranker
  aus) grundsätzlich nicht zeigbar — das ist der wichtigste Vorbehalt dieses
  Laufs.** Δ(A − vorher) = 0 ist keine Messung, sondern eine Konsequenz aus
  Paper-Ebene-RRF, die `chunk_id`/`text` nicht konsultiert (siehe oben). Eine
  belastbare Aussage über den Nutzen der Anreicherung bräuchte den aktiven
  Reranker — und damit einen nicht mehr hermetischen, mit #722 überlappenden
  Lauf.
- **Das Goldset ist zu klein, um den Fusionseffekt zu zeigen.** 11 Paper und
  30 Chunks bei `k=10` sättigen praktisch den gesamten Bestand; die
  Fusionsgranularität kann unter diesen Bedingungen kaum eine andere
  Rangreihenfolge erzeugen als die Paper-Ebene-Fusion. Eine belastbare
  Aussage über den Qualitätsgewinn der Chunk-Fusion bräuchte ein Goldset mit
  deutlich mehr Papern pro Thema (viele Kandidaten, die um dieselbe Query
  konkurrieren) und mehreren Chunks pro Paper, die unterschiedlich stark zur
  Query passen — beides ist laut Scope dieses Issues **out of scope** (keine
  Goldset-Erweiterung).
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
  (`fts5_syntax_errors` in den Rohdaten). Außerhalb des Scopes dieses Issues
  (`area/vault` geschützt) — bereits als eigener Befund in #722 dokumentiert.
- **Der Kosten-Korpus ist synthetisch und bedeutungslos** (Wortsalat aus
  einem 40-Wörter-Vokabular). Das ist für Index-Größe und Latenz
  ausreichend — beide hängen an Volumen und SQL-/vec0-Mechanik, nicht an
  Bedeutung —, aber die absoluten Zahlen (194 Chunks über 60 Paper, im Mittel
  3,2 Chunks je Paper) sind kleiner als ein typischer realer Vault (deutlich
  mehr Chunks pro Paper bei echten Volltexten). Die *relativen* Kostenanteile
  (Index +12,45 %, Fusion +44,9 % p50-Latenz) sind die belastbare Aussage,
  nicht die absoluten Millisekunden/Bytes.
- **Eine Maschine, ein Lauf, n=36 je Zustand.** Latenzwerte stammen von einer
  einzelnen Messumgebung mit vergleichsweise wenigen Wiederholungen; die
  Größenordnung (Fusion kostet spürbar mehr als die Anreicherung) sollte über
  Hardware hinweg stabil sein, einzelne Millisekundenwerte (insbesondere
  `p95`, siehe die gegenläufige A-vs-vorher-Zahl oben) nicht.
- **`vorher`-Zustand ist ein Shim.** Weder #726 noch #727 sind über einen
  Produktionsschalter erreichbar (beide Pfade wurden vollständig ersetzt).
  Der Shim (`search_papers_paper_level` in
  `scripts/eval/run_retrieval_ablation_729.py`) reimplementiert die
  historische Fusion (`_paper_id_rrf`, bitgleich zu Commit `a32f570^`) und
  die historische Vektor-Aggregation (`_vec0_search_paper_level`, ruft die
  aktuelle, unveränderte KNN-Suche mit dem historischen `max(k*4, k)`-Pool
  auf und dedupliziert genau wie der historische Code) — differenziell gegen
  den dokumentierten historischen Stand geprüft in
  `tests/test_issue_729_chunk_fusion_ablation.py`, nicht durch
  Wiederausführung des historischen Codes selbst. Die lexikalische Seite
  (`papers_fts`/`papers_trgm`, optional `_attach_chunk_to_fts_hit`) ist dabei
  KEIN Shim, sondern ruft reale, unveränderte Produktionsfunktionen auf.

## Reproduktion

```bash
uv run python scripts/eval/run_retrieval_ablation_729.py \
  --out docs/evals/2026-08-08-chunk-fusion-ablation-729-live-results.json
```

Vollständig hermetisch — kein `VAULT_E5_LIVE_TEST=1` nötig, kein
Netzzugriff, kein Modell-Download. Laufzeit auf der Messmaschine unter
10 Sekunden. `--skip-cost` lässt AC3 (Index/Latenz) aus, falls nur die
Qualitätszahlen interessieren. Report-Tabellen und die eingecheckte JSON
stammen aus demselben Aufruf — bei einem erneuten Lauf beide Dateien
zusammen neu schreiben, nie nur eine von Hand nachziehen.

## Nachtrag (2026-08-09, #789): Die "Korpus zu klein"-Diagnose war unvollständig

> Dieser Abschnitt korrigiert eine Aussage weiter oben
> ([„Warum die Nullen erklärbar sind"](#warum-die-nullen-erklärbar-sind--zwei-verschiedene-gründe-nicht-einer)),
> ergänzt sie aber nur — der Rest des Dokuments bleibt als Momentaufnahme des
> ursprünglichen Laufs unverändert stehen (siehe Hinweis am Dokumentanfang).

Δ(Chunk-Fusion) = 0 wurde oben mit „Korpus zu klein / gesättigt gegenüber
`k=10`" erklärt. Diese Erklärung ist nicht falsch, aber **unvollständig** und
verdeckt die eigentliche, strukturelle Ursache: Eine mechanistische
Nachrechnung gegen die echten Produktionsfunktionen
(`retrieval.reciprocal_rank_fusion`, `server._attach_chunk_to_fts_hit`,
`server._vec0_search`) zeigt, dass die lexikalische Seite des #708-Goldsets
für die Chunk-Fusion praktisch **tot** ist — unabhängig von der Korpusgröße:

- **Nur 1 von 26 Queries erzielt überhaupt einen `papers_fts`-Treffer, 0 bei
  `papers_trgm`** (`scripts/eval/run_retrieval_ablation_729.py::run_diagnostics`,
  `tests/test_issue_789_fts_diagnosis.py::test_708_goldset_lexical_side_is_structurally_dead`).
  Ursache: Die Goldset-Queries sind ausgeschriebene Sätze
  (`"how can a pipeline enforce that the author of a change is not the one
  who releases it"`), FTS5-`MATCH` ohne `OR`-Operator verlangt implizit
  **jedes** Token im indizierten Feld (`AND`-Semantik) — ein einziges Token,
  das nicht wörtlich im Titel/Abstract/Volltext steht, lässt den gesamten
  Treffer scheitern. Das ist kein Korpusgrößeneffekt; ein Goldset mit 1.000
  statt 11 Papern hätte an dieser Query-Formulierung dieselbe Nullquote.
- **Mathematisch beweisbar, nicht nur beobachtet:** Bei leerer
  FTS-Trefferliste sind Paper-Ebene-Fusion (`vorher`) und Chunk-Ebene-Fusion +
  MAX-Aggregation (`nachher`) **ordnungsgleich** — `rrf_score = 1/(60+r)` ist
  streng monoton fallend in `r`, MAX über die Chunk-Ränge je Paper
  reproduziert deshalb exakt dieselbe Paper-Reihenfolge wie eine direkte
  Paper-Ebene-Dedup nach bestem Vektor-Rang. Formaler Beleg (kein Mock der
  Kernlogik, kein DB-Fixture nötig) in
  `tests/test_issue_789_fts_diagnosis.py::test_empty_fts_makes_chunk_and_paper_level_fusion_order_equivalent`
  und der randomisierten Ergänzung direkt danach. Mit anderen Worten: Bei 25
  von 26 Queries konnte die Chunk-Fusion die Reihenfolge schlicht **nicht**
  verändern, weil ihr eigener Eingabezustand (leere FTS-Liste) das
  algebraisch ausschließt — unabhängig davon, ob der Korpus 11 oder 10.000
  Paper groß ist.
- Bei der einen Query mit einem tatsächlichen `papers_fts`-Treffer
  (`q-en-01`) bestätigt der Diagnoseblock zusätzlich, dass
  `_attach_chunk_to_fts_hit` einen echten Chunk zuordnet (kein Rückfall auf
  den synthetischen Schlüssel `fts-paper::<pid>`) und dieser Chunk mit dem
  vektoriell besten Chunk desselben Papers übereinstimmt — auch hier bleibt
  kein Spielraum für eine abweichende Fusionsreihenfolge.

**Folge für die Empfehlung oben:** Die Empfehlung „nicht zurückrollen" bleibt
unverändert richtig, aber Grund 1 dort sollte um diesen Befund ergänzt
gelesen werden — die Null ist nicht nur „mit diesem Goldset nicht zeigbar",
sondern bei 25 von 26 Queries **strukturell nicht zeigbar**, ganz gleich wie
groß das Goldset gebaut würde. Ein aussagekräftiger Nachweis des
Chunk-Fusions-Beitrags braucht ein Goldset mit Queries, die tatsächlich
lexikalische Treffer erzeugen (kurze Stichwort-Queries statt ausgeschriebener
Sätze, oder ein `OR`-fähiges Query-Muster) — genau die Grundlage, die #789 für
ein künftiges Probe-Goldset-Issue legt (gezielt konstruierte Fälle, deren
Vorbedingungen maschinell prüfbar sind, statt eines weiteren Zufallstreffers
wie `q-en-01`).

Der Diagnoseblock deckt zusätzlich zwei vom Nullbefund unabhängige
Code-Befunde auf, die als eigene Folge-Issues laufen (nicht Teil dieses
Laufs, `academic_vault/` ist geschützt):
[#791](https://github.com/ahlerjam/academic-research/issues/791)
(`_attach_chunk_to_fts_hit` verliert den Hybrid-Bonus bei fehlgeschlagenem
Chunk-Lookup) und
[#792](https://github.com/ahlerjam/academic-research/issues/792)
(nichtdeterministischer Tie-Break in `reciprocal_rank_fusion` bei exakt
gleichem `rrf_score`).

**Eingelöst in [#790](2026-08-09-chunk-fusion-goldset-790.md):** Das dort
gebaute Probe-Goldset erzeugt genau solche Queries und zeigt den Effekt, den
dieser Lauf nicht zeigen konnte — in beide Richtungen (Familie A +0,3691
nDCG@10, Familie C betragsgleich negativ). Der Nullbefund hier bleibt richtig;
er war eine Aussage über dieses Goldset, nicht über den Mechanismus.

Diagnoseblock, Zahlen und Tests: `scripts/eval/run_retrieval_ablation_729.py`
(`diagnose_query`/`run_diagnostics`, `--goldset`/`--vectors`-Flags, Aggregation
je `case`) und `tests/test_issue_789_fts_diagnosis.py`. Vollständige
Herleitung: Issue [#789](https://github.com/ahlerjam/academic-research/issues/789).
