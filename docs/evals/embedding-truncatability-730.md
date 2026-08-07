# Truncatierbarkeit der Embedding-Kandidaten (Issue #730)

> **Historisches Dokument.** Momentaufnahme des Abrufstands unten, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-07
**Komponente:** keine (reine Recherche-/Doku-Aufgabe, kein Code) — Vorarbeit für
eine mögliche Modellwahl-Entscheidung im Anschluss an
[`recall-at-k-model-ab-hard-628.md`](recall-at-k-model-ab-hard-628.md)
**Abrufstand:** 2026-08-07 (alle drei Quellen an diesem Tag abgerufen)

## Fragestellung

`chunk_vectors` wird in `academic_vault/db.py` mit fester Dimension (384)
angelegt. Ein Kandidat mit nativ höherer Dimension bedeutet deshalb nicht nur
andere Vektoren, sondern eine Schema-Migration (`FLOAT[384]` → `FLOAT[1024]`)
plus vollständige Neuindizierung aller Bestands-Vaults. Dieser Report prüft
für die drei in #628 als aussichtsreich benannten Kandidaten, ob der Anbieter
selbst eine verlustarme Kürzung auf 384 Dimensionen zulässt (Matryoshka
Representation Learning / MRL bzw. eine vergleichbare Trunkierungsgarantie) —
**ohne** zu messen und **ohne** eine Wechsel-Empfehlung auszusprechen (beides
Out-of-Scope für #730, siehe Issue-Body).

## Ergebnis je Kandidat

| Modell | Model-ID | Truncation lt. Anbieter (Zitat + Fundstelle) | 384d ohne Schema-Migration? | Download-Größe | Lizenz |
|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B | `Qwen/Qwen3-Embedding-0.6B` | „MRL Support: Yes" und „Up to 1024, supports user-defined output dimensions ranging from 32 to 1024" — [Modellkarte](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), abgerufen 2026-08-07 | **Ja** — 384 liegt innerhalb des vom Anbieter selbst genannten Bereichs 32–1024 | `model.safetensors` ≈ 1,19 GB (Gesamtrepo inkl. Tokenizer-Dateien ≈ 1,21 GB) — [HF-API `siblings`](https://huggingface.co/api/models/Qwen/Qwen3-Embedding-0.6B?blobs=true), abgerufen 2026-08-07 | Apache-2.0 — [Modellkarte](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), abgerufen 2026-08-07 |
| BGE-M3 | `BAAI/bge-m3` | Modellkarte enthält **keine** Aussage zu „Matryoshka", „MRL" oder „truncat*" (Volltextsuche im README negativ) — [Modellkarte](https://huggingface.co/BAAI/bge-m3), abgerufen 2026-08-07 | **nicht belegt** | `pytorch_model.bin` ≈ 2,27 GB (zusätzlich `onnx/model.onnx_data` ≈ 2,27 GB als optionale ONNX-Variante) — [HF-API `siblings`](https://huggingface.co/api/models/BAAI/bge-m3?blobs=true), abgerufen 2026-08-07 | MIT — [Modellkarte](https://huggingface.co/BAAI/bge-m3), abgerufen 2026-08-07 |
| multilingual-e5-large | `intfloat/multilingual-e5-large` | Modellkarte enthält **keine** Aussage zu „Matryoshka", „MRL" oder „truncat*" (Volltextsuche im README negativ) — [Modellkarte](https://huggingface.co/intfloat/multilingual-e5-large), abgerufen 2026-08-07 | **nicht belegt** | `pytorch_model.bin` / `model.safetensors` ≈ 2,24 GB — [HF-API `siblings`](https://huggingface.co/api/models/intfloat/multilingual-e5-large?blobs=true), abgerufen 2026-08-07 | MIT — [Modellkarte](https://huggingface.co/intfloat/multilingual-e5-large), abgerufen 2026-08-07 |

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

Von den drei Kandidaten weist **ausschließlich Qwen3-Embedding-0.6B** eine
vom Anbieter selbst zugesicherte 384d-Truncation aus (`MRL Support: Yes`,
Bereich 32–1024) — ein Wechsel auf dieses Modell wäre ohne Schema-Migration
in `chunk_vectors` möglich. Für BGE-M3 und multilingual-e5-large bleibt die
Kürzbarkeit auf 384 Dimensionen **nicht belegt**; ein Einsatz dieser beiden
Modelle würde beim aktuellen Kenntnisstand nur mit nativer Dimension (1024)
und damit mit Schema-Migration (`FLOAT[384]` → `FLOAT[1024]`) plus
vollständiger Neuindizierung aller Bestands-Vaults in Frage kommen. Das
deckt sich mit der in #628 offen gelassenen Einschätzung und bestätigt sie
jetzt mit geprüfter Beleglage statt als Vermutung.

Dieser Report trifft **keine** Empfehlung für oder gegen einen Modellwechsel
— das bleibt Aufgabe eines Folge-Issues, das die tatsächliche Qualität einer
384d-Truncation (sofern für ein Modell möglich) messen müsste.
