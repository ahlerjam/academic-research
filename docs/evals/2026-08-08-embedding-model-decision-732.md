# Modellentscheidung Embedding: Wechsel auf BAAI/bge-m3 (Issue #732)

> **Historisches Dokument.** Momentaufnahme der Entscheidung vom 2026-08-08 auf
> Basis der zu diesem Zeitpunkt vorliegenden Zahlen. Der Sollzustand — welches
> Modell aktuell produktiv läuft — steht im Code
> (`academic_vault/embedding_model.py`, `DEFAULT_MODEL_ID`) und in
> [`docs/reference/vault.md`](../reference/vault.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-08
**Vorgänger-Issues:** [#628](recall-at-k-model-ab-hard-628.md) (erster A/B-Verdacht),
[#730](embedding-truncatability-730.md) (Truncatierbarkeit belegt),
[#731](2026-08-08-embedding-candidates-731.md) (Zahlen auf dem Chunk-Goldset,
**die Datenbasis dieser Entscheidung**)
**Epic:** [#712](https://github.com/ahlerjam/academic-research/issues/712) — bleibt
offen, siehe [Epic-Status](#epic-status) unten
**Umgesetzt in:** `academic_vault/embedding_model.py` (`DEFAULT_MODEL_ID`),
`migrate.reindex_embeddings` (unverändert, aus #629, hier erprobt),
`tests/test_issue_732_bge_m3_reindex.py`

## Die Entscheidung

**Wechsel des Embedding-Default-Modells von `intfloat/multilingual-e5-small`
(384d) auf `BAAI/bge-m3` (1024d).**

Nicht gewählt: `qwen3-384` (Qwen3-Embedding-0.6B, truncatiert auf 384d) trotz
bester nDCG@10/MRR und Migrationsfreiheit. Nicht gewählt: „bleiben" bei
`e5-small` trotz Aufwandslosigkeit. Begründung unten.

## Ausgangslage: die drei ernsthaften Kandidaten

Alle Zahlen aus [#731](2026-08-08-embedding-candidates-731.md), 26 Queries,
`k = 10`, Apple M4 Pro, CPU (`device="cpu"` explizit, kein MPS/CUDA):

| Kandidat | Dim | Recall@10 | nDCG@10 | MRR | Indexierung p50 | Migration | Trägt ggü. Baseline? |
|---|---|---|---|---|---|---|---|
| `e5-small` (Baseline) | 384 | 0,7692 | 0,6651 | 0,6314 | 27,1 ms | — | — |
| `qwen3-384` | 384 | 0,9615 | **0,8241** | **0,7923** | 2232,8 ms | **keine** | nDCG, MRR |
| `bge-m3` | 1024 | **0,9808** | 0,8137 | 0,7660 | 168,6 ms | Schema+Reindex | Recall, nDCG |
| `e5-large` | 1024 | 0,9231 | 0,7413 | 0,6979 | 173,5 ms | Schema+Reindex | Recall |
| `qwen3-1024` | 1024 | 0,9231 | 0,7859 | 0,7420 | 2368,4 ms | Schema+Reindex | keine (Punktschätzung ja, CI nein) |

`e5-large` und `qwen3-1024` scheiden vorab aus: Ersteres trägt nur in einer
Metrik und hat gegenüber `bge-m3` keinen Vorteil, der einen zweiten
1024d-Kandidaten rechtfertigt; Letzteres ist von `qwen3-384` strikt dominiert
(schlechter in allen drei Metriken bei identischer Indexierungskosten-Klasse,
siehe „Kürzung kostet nichts" in #731). Die eigentliche Entscheidung liegt
zwischen `bge-m3`, `qwen3-384` und „bleiben".

## AC2: Hardwarekosten auf einem Laptop ohne GPU — gewichtet, nicht nur erwähnt

Das ist der Kern der Abwägung, deshalb zuerst, nicht als Fußnote.

**Die Indexierungszeit ist kein einmaliger Migrationskosten-Posten, sondern
eine dauerhafte Steuer auf jeden künftigen `add_paper()`-Aufruf.** Ein Vault
wächst über die gesamte Nutzungsdauer eines Studiums oder Forschungsprojekts —
jedes neu hinzugefügte Paper zahlt die Indexierungszeit erneut, unbegrenzt oft.
Ein Migrationsaufwand dagegen fällt genau einmal an, ist im Voraus bekannt und
lässt sich einplanen.

Auf dieser Unterscheidung kippt die Abwägung:

- **`qwen3-384` ist migrationsfrei, aber 2,2 Sekunden pro Chunk auf CPU.** Bei
  ~22 Chunks je Paper (Mittel aus #731) sind das ~49 Sekunden **pro Paper**,
  dauerhaft, bei jedem `add_paper()`-Aufruf ohne GPU. Ein 200-Paper-Vault läge
  laut #731 bei 2h45min für den Ersteinzug — das ist nicht der Einzelfall, den
  man einmal hinnimmt, sondern das WIEDERKEHRENDE Verhalten der Kernfunktion
  des Plugins auf der vom Repo selbst als Zielhardware benannten Konfiguration
  (`docs/guide/installation.md`: „Keine GPU nötig — alle drei Modelle laufen
  auch auf reiner CPU, dabei aber spürbar langsamer"). Für ein Tool, dessen
  Kernversprechen laut README Halluzinationsschutz über einen durchsuchbaren
  Vault ist, ist eine Indexierungszeit, die jedes neue Paper zum spürbaren
  Wartemoment macht, ein hartes Praxisproblem — nicht nur eine unschöne Zahl.
- **`bge-m3` braucht eine einmalige Migration, aber 168,6 ms pro Chunk auf
  CPU** — 14-mal schneller als `qwen3-384` und in derselben Größenordnung wie
  der aktuelle Status quo (`e5-small`: 27,1 ms/Chunk). Ein 200-Paper-Vault
  liegt bei ~12 Minuten statt ~2h45min. Der Migrationsaufwand (Schema-Änderung
  plus vollständiger Reindex) ist real, aber er ist ein **bekannter,
  begrenzter, einmaliger** Posten — und der bestehende Weg dafür ist bereits
  gebaut und getestet (#629, siehe „Migrationsprobe" unten), nicht neu zu
  entwickeln.
- **`e5-small` (bleiben) ist am schnellsten (27,1 ms/Chunk) und kostet
  nichts** — aber das ist der einzige Vorteil. Alle drei gemessenen Metriken
  liegen unter jedem Wechsel-Kandidaten, und der Abstand trägt statistisch
  (siehe unten): `e5-small` fällt bei einer Anfrage in der einen Sprache auf
  einen Beleg in der anderen auf 0,13 nDCG (`e5-small` same-language: 0,92,
  cross-language: 0,00 laut #731) — für ein Plugin, das laut eigener Doku
  ausdrücklich zweisprachige (deutsch/englisch) Literaturbestände bedienen
  soll, ist das eine strukturelle Lücke, kein Rauschen.

Fazit AC2: Die Hardwarekosten trennen `bge-m3` und `qwen3-384` scharf
voneinander, obwohl beide auf CPU „langsamer als mit GPU" sind — der
Unterschied zwischen 169 ms und 2233 ms pro Chunk ist keine graduelle
Verschlechterung, sondern der Unterschied zwischen „im Hintergrund kaum
merklich" und „ein Paper hinzufügen dauert eine Minute, ohne GPU".

## Trägt der Qualitätsvorsprung? (Signifikanz aus #731)

Vorab festgeschriebene Regel: ein Abstand zur Baseline trägt, wenn das
95-%-Intervall der gepaarten Bootstrap-Differenz (10 000 Resamples) die Null
nicht enthält.

- **Nur `qwen3-384` und `bge-m3` halten das in mehr als einer Metrik** gegen
  die Baseline — `e5-large` und `qwen3-1024` fallen dabei durch (nur eine
  Metrik bzw. keine, s. o.).
- **`bge-m3` und `qwen3-384` sind untereinander bei 26 Queries nicht
  unterscheidbar** (überlappende Konfidenzintervalle, Auflösungsgrenze 0,038
  Recall je Query). Es gibt also **keine belastbare Qualitätsdifferenz**
  zwischen den beiden verbleibenden Wechsel-Kandidaten — die Entscheidung
  zwischen ihnen fällt folgerichtig über AC2 (Hardwarekosten), nicht über eine
  eingebildete Recall-Nuance.

Das ist die eigentliche Pointe dieser Abwägung: **wenn zwei Kandidaten in der
Qualität nicht unterscheidbar sind, aber einer 14-mal so teuer ist wie der
andere, ist die Entscheidung nicht mehr knapp.** `bge-m3` liefert denselben
gemessenen Qualitätssprung wie `qwen3-384` (beide signifikant über der
Baseline, untereinander gleichauf) — nur ohne dessen Indexierungs-Kostenproblem
und dafür mit einem einmaligen, bereits erprobten Migrationsaufwand.

## Entscheidung: Wechsel auf `bge-m3`

**Begründung ausschließlich aus den gemessenen Zahlen, nicht aus Literatur
oder Modellgröße** (AC1):

1. `bge-m3` trägt gegenüber der Baseline signifikant in Recall@10 UND nDCG@10
   (#731-Bootstrap), schließt die Sprachlücke, an der `e5-small` scheitert
   (cross-language nDCG 0,0000 → 0,8155), und ist von `qwen3-384` — dem
   einzigen migrationsfreien Kandidaten mit vergleichbarem Vorsprung —
   statistisch nicht unterscheidbar.
2. Der einzige Vorteil von `qwen3-384` gegenüber `bge-m3` (keine Migration)
   wird durch dessen ~80-fach höhere Indexierungszeit gegenüber `e5-small`
   (~14-fach gegenüber `bge-m3`) auf einem Laptop ohne GPU aufgewogen — und
   zwar dauerhaft, nicht einmalig (AC2, s. o.).
3. Der Migrationsaufwand von `bge-m3` ist real, aber begrenzt: der Weg
   existiert bereits aus #629 (`migrate.reindex_embeddings`,
   `--reindex-embeddings`) und ist mit dem tatsächlichen Kandidaten erprobt
   (siehe unten) — kein unbekanntes Risiko.
4. „Bleiben" scheidet aus, weil `e5-small` in allen drei Metriken unter jedem
   ernsthaften Kandidaten liegt und die Sprachlücke für ein zweisprachig
   beworbenes Tool eine strukturelle, nicht kosmetische Schwäche ist.

## Migrationsprobe (AC3)

Der Reindex-Mechanismus selbst ist nicht neu — er stammt aus #629
(`migrate.reindex_embeddings`, CLI-Flag `--reindex-embeddings`) und ist dort
bereits mit einem synthetischen Breiten-Wechsel (384d → 1024d) ausführlich
getestet (`tests/test_issue_629_embedding_dim.py::TestReindex`: Neuberechnung,
verbreiterte vec0-Spalten, Suche nach dem Wechsel, Mischbestand,
gesperrter Vault, CLI). Was für #732 fehlte, war der Beleg, dass dieser Weg
mit dem TATSÄCHLICHEN neuen Modell funktioniert, nicht nur mit einer
synthetischen Breiten-Attrappe.

**Durchgeführt:** ein synthetischer Vault mit drei Papern (Themen: hybrides
Retrieval, Logistik, Klimaanpassung — bewusst thematisch verschieden, um die
inhaltliche Suche nach dem Wechsel prüfbar zu machen) plus einem Zitat, zuerst
mit einem 384d-Embedder befüllt, dessen Modell-ID exakt
`intfloat/multilingual-e5-small` trägt (simuliert einen echten Bestands-Vault
von vor #732), dann `migrate.reindex_embeddings()` mit dem ECHTEN, geladenen
`BAAI/bge-m3`-Backend aufgerufen (Apple M4 Pro, CPU, `VAULT_E5_LIVE_TEST=1`,
2026-08-08). Test: `tests/test_issue_732_bge_m3_reindex.py`.

**Ergebnis:**

- Re-Index vollständig in ~0,3–0,7 s (3 Chunks, 1 Zitat, inkl. Modell-Load aus
  warmem Cache) — die Größenordnung deckt sich mit der 731-Indexierungszeit
  (168,6 ms/Chunk: bei sehr kurzen Test-Chunks liegt die tatsächliche Zeit pro
  Aufruf niedriger, siehe Streuung nach Textlänge).
- `embedding_meta` zeigt danach korrekt `model_id = "BAAI/bge-m3"`,
  `dim = 1024`.
- Die vec0-Spalten (`chunk_vectors`, `quote_embeddings`) sind auf
  `FLOAT[1024]` verbreitert (DROP + CREATE, da vec0 die Breite nicht per
  `ALTER` ändern kann).
- Die KNN-Suche findet nach dem Wechsel für eine themenspezifische Anfrage
  wieder das inhaltlich passende Paper (nicht nur strukturell korrekt breite
  Vektoren).
- Zusätzlich erprobt: ein **frischer** Vault (kein Bestand) braucht **keinen**
  Reindex — `register_embedding_inventory()` erkennt den leeren Bestand beim
  ersten echten Embed mit `bge-m3` und baut `chunk_vectors`/`quote_embeddings`
  selbstheilend direkt in 1024d auf. Das bestätigt, warum
  `DEFAULT_EMBEDDING_DIM` bewusst bei 384 bleibt (siehe Kommentar in
  `embedding_model.py`): der Konstantenwert ist die Legacy-Breite für
  Bestands-Vaults ohne `embedding_meta`-Eintrag, keine Aussage über das aktuell
  konfigurierte Modell.

**Für echte Bestands-Vaults** (nicht dieser synthetische Test) ist der Weg
unverändert:

```bash
python -m academic_vault.migrate --db ~/.academic-research/projects/<slug>/vault.db --reindex-embeddings
```

Das Kommando berechnet **alle** Chunk- und Zitat-Vektoren mit dem jetzt
konfigurierten `BAAI/bge-m3` neu, verbreitert die vec0-Tabellen und schreibt
`embedding_meta` fort — vollständiger Ersatz des Bestands, keine Lücken-Füllung
(Details: `docs/reference/vault.md`, Abschnitt „Modellwechsel und Re-Index").
Ein bereits befüllter Vault verweigert das Schreiben mit einem neuen Modell
ohne diesen Schritt (`EmbeddingDimensionMismatchError`) — die Umstellung kann
also nicht versehentlich einen Mischbestand aus zwei Vektorräumen erzeugen.

## Was sich im Code ändert

- `academic_vault/embedding_model.py`: `DEFAULT_MODEL_ID` von
  `intfloat/multilingual-e5-small` auf `BAAI/bge-m3`. `DEFAULT_EMBEDDING_DIM`
  bleibt bei 384 (Legacy-Fallback-Breite für Bestands-Vaults, s. o. — bewusst
  entkoppelt von `DEFAULT_MODEL_ID`, das ist der Punkt von #629).
- Neue Klasse `BgeM3Embedder` (Unterklasse von `E5SmallEmbedder`, nur die
  Prompting-Praefixe unterscheiden sich): `bge-m3` verlangt laut Modellkarte
  ausdrücklich **kein** Instruktions-Praefix, anders als die e5-Familie
  (`passage: `/`query: `). `get_embedder()` wählt die Klasse über eine kleine
  Registrierung nach Modell-ID.
- `academic_vault/chunking.py`: das Chunk-Fenster (`MODEL_MAX_TOKENS = 512`)
  bleibt unverändert und wird jetzt explizit als bewusste, modellunabhängige
  Grenze dokumentiert — `bge-m3` trägt nativ ein 8192-Token-Fenster, das
  absichtlich NICHT ausgenutzt wird. Late Chunking (ein Long-Context-Modell
  vorausgesetzt) ist explizit Out-of-Scope von #732 und bleibt eine eigene,
  spätere Entscheidung.
- `academic_vault/_model_prefetchable.py`, `scripts/model_prefetch.py`: die
  Setup-Vorab-Download-Ankündigung und Größentabelle folgen automatisch, weil
  sie über `DEFAULT_MODEL_ID` bzw. `APPROX_BYTES` an das Modell gekoppelt
  sind.
- Dokumentation (README, `docs/guide/installation.md`,
  `docs/guide/getting-started.md`, `docs/guide/working-with-claude-code.md`,
  `docs/guide/limits.md`, `docs/quickstart-protocol.md`,
  `docs/reference/vault.md`) auf die neue Downloadgröße (~2,3 GB statt
  ~470 MB) und das neue Modell aktualisiert; historische Vergleichswerte
  („zuvor ~470 MB") bleiben bewusst als Kontext stehen, wo sie den
  Vorher-Nachher-Unterschied belegen.

## Epic-Status

Das übergeordnete Epic [#712](https://github.com/ahlerjam/academic-research/issues/712)
(„Embedding-Modellwahl und Late Chunking auf belastbarer Datenbasis") bleibt
**offen**: AC5 seines eigenen Textes verlangt das Schließen nur, wenn die
Entscheidung erneut auf „bleiben" fällt — hier fällt sie auf einen Wechsel.
Das Epic bleibt offen, weil sein zweiter Teil (Late Chunking, explizit
Out-of-Scope dieses Issues) noch aussteht und eine eigene, spätere Entscheidung
braucht, die diesen Wechsel als Voraussetzung hat (ein Long-Context-Modell ist
mit `bge-m3` jetzt erstmals technisch vorhanden, 8192 statt 512 Token, auch
wenn #732 das nicht ausnutzt).

## Wann diese Entscheidung erneut zu prüfen ist

Nicht ohne neue Daten (Out-of-Scope-Regel aus #732 selbst), aber konkret:

- **Ein neuer Kandidat**, der `qwen3-384`s Qualitätsprofil (nDCG/MRR-Sieger)
  mit einer CPU-Indexierungszeit in der Größenordnung von `bge-m3` (< 200 ms/
  Chunk) verbindet — dann entfiele der einzige Nachteil, der `qwen3-384` in
  dieser Abwägung ausgeschlossen hat.
- **Late Chunking wird eigenständig bewertet** (nächster Schritt laut Epic
  #712) und würde selbst einen Modellwechsel motivieren, z. B. weil es ein
  Long-Context-Modell voraussetzt, das `bge-m3` zwar technisch ist (8192
  Token), aber #732 nicht als Grund für DIESEN Wechsel herangezogen hat.
- **GPU wird zur angenommenen Zielhardware.** Diese Entscheidung gewichtet
  CPU-Indexierungszeit explizit hoch (AC2), weil `docs/guide/installation.md`
  „keine GPU nötig" als Zielzustand nennt. Ändert sich diese Annahme, verliert
  das Argument gegen `qwen3-384` an Gewicht.
- **Ein größeres Goldset** löst die Auflösungsgrenze aus #731 (0,038
  Recall/Query bei 26 Queries) auf und könnte `bge-m3` und `qwen3-384`
  doch trennen — dann wäre die AC2-Abwägung ggf. neu zu führen, falls sich
  herausstellt, dass einer der beiden klar vorn liegt.

Ohne eines dieser Signale bleibt die Frage geschlossen — das ist der Zweck
dieses Vermerks (AC4/AC5 aus #732).
