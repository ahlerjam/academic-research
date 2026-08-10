# Truncatierbarkeit der Embedding-Kandidaten (Issue #730)

> **Historisches Dokument.** Momentaufnahme des Abrufstands unten, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-07, um Snowflake Arctic-Embed L v2.0 erweitert 2026-08-10 ([#801](2026-08-08-embedding-candidates-731.md))
**Komponente:** keine (reine Recherche-/Doku-Aufgabe, kein Code) — Vorarbeit für
eine mögliche Modellwahl-Entscheidung im Anschluss an
[`recall-at-k-model-ab-hard-628.md`](recall-at-k-model-ab-hard-628.md)
**Abrufstand:** 2026-08-07 (die ersten drei Quellen), 2026-08-10 (Arctic-Embed L v2.0, #801)

## Fragestellung

`chunk_vectors` wird in `academic_vault/db.py` mit fester Dimension (384)
angelegt. Ein Kandidat mit nativ höherer Dimension bedeutet deshalb nicht nur
andere Vektoren, sondern eine Schema-Migration (`FLOAT[384]` → `FLOAT[1024]`)
plus vollständige Neuindizierung aller Bestands-Vaults. Dieser Report prüft
für die drei in #628 als aussichtsreich benannten Kandidaten sowie (seit #801)
für Snowflake Arctic-Embed L v2.0, ob der Anbieter selbst eine verlustarme
Kürzung auf 384 Dimensionen zulässt (Matryoshka Representation Learning / MRL
bzw. eine vergleichbare Trunkierungsgarantie) — **ohne** zu messen und **ohne**
eine Wechsel-Empfehlung auszusprechen (beides Out-of-Scope für #730, siehe
Issue-Body).

> **Hinweis seit #732 / #801:** Die Schema-Migrationsfrage oben ist am
> historischen Stand von #730 formuliert, als `intfloat/multilingual-e5-small`
> (384d) produktiv lief. Produktiv läuft seit [#732](2026-08-08-embedding-model-decision-732.md)
> `BAAI/bge-m3` mit **1024d**. Der eigentliche Migrationsmaßstab für einen
> *heutigen* Wechsel ist also 1024d, nicht 384d — ein Kandidat, der wie Arctic
> nativ 1024d misst, bräuchte gegenüber dem produktiven Stand nur einen
> Reindex, keine Schema-Änderung. Die Tabelle unten beantwortet weiterhin die
> ursprüngliche, damals gestellte 384d-Frage (das war ihr Auftrag), aber die
> Einordnung „braucht Migration" bezieht sich auf den 384d-Stand vor #732.

## Ergebnis je Kandidat

| Modell | Model-ID | Truncation lt. Anbieter (Zitat + Fundstelle) | 384d ohne Schema-Migration? | Download-Größe | Lizenz |
|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B | `Qwen/Qwen3-Embedding-0.6B` | „MRL Support: Yes" und „Up to 1024, supports user-defined output dimensions ranging from 32 to 1024" — [Modellkarte](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), abgerufen 2026-08-07 | **Ja** — 384 liegt innerhalb des vom Anbieter selbst genannten Bereichs 32–1024 | `model.safetensors` ≈ 1,19 GB (Gesamtrepo inkl. Tokenizer-Dateien ≈ 1,21 GB) — [HF-API `siblings`](https://huggingface.co/api/models/Qwen/Qwen3-Embedding-0.6B?blobs=true), abgerufen 2026-08-07 | Apache-2.0 — [Modellkarte](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), abgerufen 2026-08-07 |
| BGE-M3 | `BAAI/bge-m3` | Modellkarte enthält **keine** Aussage zu „Matryoshka", „MRL" oder „truncat*" (Volltextsuche im README negativ) — [Modellkarte](https://huggingface.co/BAAI/bge-m3), abgerufen 2026-08-07 | **nicht belegt** | `pytorch_model.bin` ≈ 2,27 GB (zusätzlich `onnx/model.onnx_data` ≈ 2,27 GB als optionale ONNX-Variante) — [HF-API `siblings`](https://huggingface.co/api/models/BAAI/bge-m3?blobs=true), abgerufen 2026-08-07 | MIT — [Modellkarte](https://huggingface.co/BAAI/bge-m3), abgerufen 2026-08-07 |
| multilingual-e5-large | `intfloat/multilingual-e5-large` | Modellkarte enthält **keine** Aussage zu „Matryoshka", „MRL" oder „truncat*" (Volltextsuche im README negativ) — [Modellkarte](https://huggingface.co/intfloat/multilingual-e5-large), abgerufen 2026-08-07 | **nicht belegt** | `pytorch_model.bin` / `model.safetensors` ≈ 2,24 GB — [HF-API `siblings`](https://huggingface.co/api/models/intfloat/multilingual-e5-large?blobs=true), abgerufen 2026-08-07 | MIT — [Modellkarte](https://huggingface.co/intfloat/multilingual-e5-large), abgerufen 2026-08-07 |
| Arctic-Embed L v2.0 | `Snowflake/snowflake-arctic-embed-l-v2.0` | „like our v1.5 model, the MRL for this model is 256 dimensions" — [Modellkarte](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0), abgerufen 2026-08-10; `config.json`: `"matryoshka_dimensions": [256]` | **Nein — 384 ist nicht der zugesicherte Punkt.** Zugesichert ist ausschließlich 256d | `model.safetensors` gesamter aufgelöster Snapshot ≈ 2,29 GB (gemessen, `huggingface_hub.snapshot_download`, lokal aufgelöst) | Apache-2.0 (Repo-Tag `license: apache-2.0`) — [Modellkarte](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0), abgerufen 2026-08-10 |

## Details je Kandidat

### Qwen3-Embedding-0.6B

Die Modellkarte führt in ihrer Modellübersichtstabelle eine Spalte „MRL
Support" mit der Erläuterung „indicates whether the embedding model supports
custom dimensions for the final embedding" und trägt für die 0.6B-Variante
„Yes" ein. Direkt daneben nennt die Karte die zulässige Bandbreite wörtlich:
„Up to 1024, supports user-defined output dimensions ranging from 32 to
1024." Der Wert 384 wird nicht als Einzelzahl genannt, liegt aber innerhalb
des explizit zugesicherten Bereichs — das ist dieselbe Konfiguration
(`truncate_dim=384`), die bereits im #628-Report produktiv gemessen wurde
(Recall@10 = 0,9583 auf dem harten Goldset). Damit ist 384d für dieses Modell
vom Anbieter selbst als zulässig ausgewiesen, nicht nur aus der
Modellarchitektur abgeleitet.

Lizenz: Apache-2.0 (Tag `license:apache-2.0` in den Repo-Metadaten).
Download-Größe: Hauptgewichtsdatei `model.safetensors` 1.191.649.088 Byte
(≈ 1,19 GB); Tokenizer-Dateien (`tokenizer.json`, `vocab.json`,
`merges.txt`) addieren rund 16 MB.

### BAAI/bge-m3

Die README-Modellkarte wurde vollständig nach den Zeichenketten
„Matryoshka", „MRL", „truncat" (inkl. Varianten „truncation"/„truncate") und
„384" durchsucht. Der einzige Treffer für „384" bezieht sich auf ein
**anderes** Modell derselben Familie (`BAAI/bge-small-en-v1.5`, ein separat
trainiertes, kleineres englischsprachiges Modell mit nativ 384 Dimensionen)
— das ist keine Aussage über die Kürzbarkeit von `bge-m3` selbst und wird
hier bewusst nicht als Beleg gewertet, um nicht in die in AC2 ausgeschlossene
Ableitungsfalle zu laufen. Für „Matryoshka", „MRL" und „truncat*" liefert die
Karte **keinen** Treffer. Damit gilt für BGE-M3: **nicht belegt**, ob 384d
ohne nennenswerten Qualitätsverlust möglich wären — exakt die in #628 offen
gelassene Frage.

Lizenz: MIT (Tag `license:mit`). Download-Größe: Hauptgewichtsdatei
`pytorch_model.bin` 2.271.064.986 Byte (≈ 2,27 GB); das Repo enthält
zusätzlich eine ONNX-Variante (`onnx/model.onnx_data`, ≈ 2,27 GB) als
Alternative, die für einen `sentence-transformers`-Einsatz nicht benötigt
wird.

### intfloat/multilingual-e5-large

Dieselbe Volltextsuche wie bei BGE-M3, angewandt auf die
`multilingual-e5-large`-Modellkarte: **kein** Treffer für „Matryoshka",
„MRL", „truncat*" oder „384". Die Karte dokumentiert lediglich das aus #628
bereits bekannte Query-/Passage-Präfixschema, keine Aussage zur
Dimensionskürzung. Damit gilt auch hier: **nicht belegt**.

Lizenz: MIT (Tag `license:mit`). Download-Größe: Hauptgewichtsdatei
`pytorch_model.bin` bzw. `model.safetensors` 2.239.652.980 Byte
(≈ 2,24 GB).

### Snowflake Arctic-Embed L v2.0 (seit #801)

Die README-Modellkarte nennt Matryoshka Representation Learning explizit,
aber **nicht** für 384 Dimensionen: „Compression-friendly: Achieves
high-quality retrieval with embeddings as small as 128 bytes/vector using
Matryoshka Representation Learning (MRL) and quantization-aware embedding
training. Please note that like our v1.5 model, the MRL for this model is
256 dimensions[...]." Die Vergleichstabelle in der Modellkarte misst
ausschließlich 1024d (nativ) und 256d — 384 kommt an keiner Stelle der Karte
vor, weder als Fließtext noch als Tabellenwert. Das bestätigt `config.json`
im Modell-Repo direkt: `"matryoshka_dimensions": [256]` — ein einzelner,
vom Anbieter selbst festgelegter Trunkierungspunkt, keine Bandbreite wie bei
Qwen3 („32 to 1024"). Ein `truncate_dim=384` wäre für dieses Modell also ein
**geratener** Schnitt ohne Zusicherung des Anbieters, exakt die Falle, die
dieser Report und #731 an anderer Stelle bewusst vermeiden (kein geratenes
Prompting-Schema, hier: keine geratene Trunkierungsdimension). Gemessen wurde
deshalb in #801 statt einer 384d-Variante der tatsächlich zugesicherte
256d-Punkt, zusätzlich zur nativen 1024d-Variante (Zahlen in
[#731](2026-08-08-embedding-candidates-731.md)).

Backbone: Die Modellkarte nennt ausdrücklich `BAAI/bge-m3-retromae` als
Basis („arctic-embed-l-v2.0 builds on BAAI/bge-m3-retromae which allows
direct drop-in inference replacement..."). Arctic-Embed L v2.0 teilt sich
damit den Backbone mit dem produktiven Embedder (`BAAI/bge-m3`) sowie mit den
beiden anderen produktiven lokalen Modellen des Plugins — dem NLI-Scorer
(`MoritzLaurer/bge-m3-zeroshot-v2.0`) und dem Reranker
(`BAAI/bge-reranker-v2-m3`). Kein Ausschlussgrund für sich, aber eine
Angabe, die gehört: eine Schwäche im gemeinsamen Backbone träfe alle drei
Stufen der Plugin-Pipeline gleichzeitig, ohne dass eine die andere
korrigieren könnte.

Lizenz: Apache-2.0 (Repo-Tag `license: apache-2.0`, zusätzlich im Fließtext
bestätigt: „Released under the permissive Apache 2.0 license"). Parameter
laut Modellkarten-Vergleichstabelle: 568M gesamt, 303M Nicht-Embedding-
Parameter — **Korrektur zum #801-Issue-Text:** Der dortige Vergleich „303M
Parameter gegen bge-m3s 568M bei derselben Dimension" stellt zwei
unterschiedliche Spalten derselben Tabelle einander gegenüber (Arctics
Nicht-Embedding-Parameter gegen bge-m3s Gesamtparameter). Laut Modellkarte
sind beide Modelle bei **identischer** Parameterzahl gelistet: 568M gesamt
und 303M Nicht-Embedding-Parameter, für Arctic-Embed L v2.0 **und** für
`bge-m3` gleichermaßen. Arctic ist also nicht das kleinere Modell, wie der
Issue-Text nahelegt — die tatsächlich gemessene CPU-Indexierzeit (siehe
#731) liegt entsprechend auch nicht klar unter der von `bge-m3`, sondern in
derselben Größenordnung. Kontextlänge: `config.json`:
`max_position_embeddings: 8194` (RoPE, Modellkarte nennt „context window of
up to 8192"). Download-Größe: aufgelöster Snapshot ≈ 2,29 GB (gemessen wie
in #731, ohne ONNX-Variante) — nahezu identisch mit `bge-m3` (ebenfalls
2,29 GB), konsistent mit der gleichen Parameterzahl.

## Ableitungsfalle explizit ausgeschlossen

Eine Web-Suche außerhalb der Modellkarten liefert Sekundärquellen (Blogs,
Community-Vergleichstabellen), die für BGE-M3 „no Matryoshka support" und für
multilingual-e5-large „doesn't have native Matryoshka support" behaupten,
sowie einen Hinweis auf eine separat nachtrainierte Community-Variante
(`IoannisKat1/multilingual-e5-large-legal-matryoshka`), deren Existenz
impliziert, dass das Basismodell selbst kein MRL mitbringt — sonst wäre ein
eigenes Nachtraining dafür nicht nötig. Diese Quellen sind **nicht** die
Modellkarte des Anbieters und werden hier ausdrücklich nicht als Beleg für
die Tabellenspalte „384d ohne Schema-Migration?" verwendet — sie stützen die
Einschätzung „nicht belegt" nur zusätzlich, ersetzen aber keinen fehlenden
Primärbeleg. Maßgeblich für dieses Issue bleibt ausschließlich, was die
jeweilige Modellkarte selbst zusagt (AC2).

## Fazit

Von den vier geprüften Kandidaten weist **ausschließlich Qwen3-Embedding-0.6B**
eine vom Anbieter selbst zugesicherte 384d-Truncation aus (`MRL Support: Yes`,
Bereich 32–1024) — ein Wechsel auf dieses Modell wäre ohne Schema-Migration
in `chunk_vectors` möglich. Für BGE-M3 und multilingual-e5-large bleibt die
Kürzbarkeit auf 384 Dimensionen **nicht belegt**. **Arctic-Embed L v2.0
(#801) sichert eine Kürzung ausdrücklich zu, aber nicht auf 384 — der vom
Anbieter selbst festgelegte MRL-Punkt ist 256d** (`config.json`:
`matryoshka_dimensions: [256]`); eine 384d-Variante wäre für dieses Modell
ein geratener, nicht belegter Schnitt und wurde deshalb in #801 nicht
gebaut. Ein Einsatz von Arctic in **nativer** Dimension (1024) würde beim
aktuellen Kenntnisstand mit Schema-Migration (`FLOAT[384]` → `FLOAT[1024]`)
plus vollständiger Neuindizierung aller Bestands-Vaults einhergehen — genau
wie bei BGE-M3 und multilingual-e5-large. Das deckt sich mit der in #628
offen gelassenen Einschätzung und bestätigt sie jetzt mit geprüfter
Beleglage statt als Vermutung.

**Nachtrag seit #732 (produktiver Stand `BAAI/bge-m3`, 1024d):** Die 384d-
Fragestellung oben war zum Zeitpunkt von #730 die richtige — produktiv lief
damals `intfloat/multilingual-e5-small` (384d). Seit #732 läuft produktiv
`BAAI/bge-m3` mit 1024d. Ein Wechsel von `bge-m3` auf einen anderen nativ
1024d messenden Kandidaten — wie Arctic-Embed L v2.0 nativ — bräuchte damit
**keine Schema-Migration mehr**, nur einen Reindex (`FLOAT[1024]` bleibt
`FLOAT[1024]`). Die „braucht Migration"-Spalte oben bezieht sich weiterhin
auf den historischen 384d-Ausgangspunkt vor #732, nicht auf den heutigen
Vergleichsmaßstab. Details und die Einordnung, ob das eine Neubewertung von
#732 auslöst, stehen im Fortschreibungsabschnitt von
[`2026-08-08-embedding-model-decision-732.md`](2026-08-08-embedding-model-decision-732.md).

Dieser Report trifft **keine** Empfehlung für oder gegen einen Modellwechsel
— das bleibt Aufgabe eines Folge-Issues, das die tatsächliche Qualität einer
384d-Truncation (sofern für ein Modell möglich) messen müsste.
