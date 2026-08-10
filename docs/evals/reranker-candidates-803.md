# Reranker-Kandidaten: Lizenz, Größe, Sprachabdeckung, Eingabeschema (Issue #803)

> **Historisches Dokument.** Momentaufnahme des Rechercheergebnisses unten, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-10
**Komponente:** keine (reine Recherche-/Doku-Aufgabe, kein Code) — Vorarbeit für einen
möglichen späteren Reranker-Vergleichslauf, analog zur Embedding-Vorarbeit in
[`embedding-truncatability-730.md`](embedding-truncatability-730.md) (#730)
**Abrufstand:** 2026-08-10 (alle Quellen an diesem Tag abgerufen)
**Gepinnte Versionen im Repo (`uv.lock`):** `transformers==5.14.1`,
`sentence-transformers==5.6.1`

## Fragestellung

Der Repo-Reranker `BAAI/bge-reranker-v2-m3` läuft seit #714 über
`sentence_transformers.CrossEncoder` statt `FlagEmbedding`, weil letzteres
`transformers<5.0` erzwingt und damit jede Installation im Repo auf einen Downgrade
zieht (`academic_vault/retrieval.py:133`). Dieser Report belegt für mindestens drei
ernsthafte, offen gewichtete, multilinguale Cross-Encoder-Alternativen — je aus der
eigenen Modellkarte, nicht aus dem Gedächtnis oder von einem anderen Modell
übernommen —: Lizenz, Parameterzahl, Downloadgröße, Sprachabdeckung, maximale
Eingabelänge, Eingabeschema und Backbone. Zusätzlich wird geprüft, ob der Kandidat über
`sentence_transformers.CrossEncoder` mit dem im Repo gepinnten `transformers==5.14.1`
ladbar ist. **Keine Messung, keine Empfehlung** (beides Out-of-Scope für #803, siehe
Issue-Body).

## Kandidatenauswahl

Geprüft wurden vier offene, multilinguale Cross-Encoder-Reranker, die aktuell als
Alternativen zu `bge-reranker-v2-m3` gehandelt werden: `mixedbread-ai/mxbai-rerank-large-v2`,
`Alibaba-NLP/gte-multilingual-reranker-base`, `BAAI/bge-reranker-v2-gemma` und
`jinaai/jina-reranker-v2-base-multilingual`. Drei bestehen die Lizenzprüfung und werden
unten tabellarisch geführt; der vierte scheidet aus Lizenzgründen aus (siehe
[Ausgeschlossene Kandidaten](#ausgeschlossene-kandidaten)).

## Ergebnis je Kandidat

| Modell | Model-ID | Lizenz | Parameter | Downloadgröße | Sprachabdeckung | Max. Eingabelänge | Backbone |
|---|---|---|---|---|---|---|---|
| mxbai-rerank-large-v2 | `mixedbread-ai/mxbai-rerank-large-v2` | Apache-2.0 — [Modellkarte](https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v2), abgerufen 2026-08-10 | „2B params" — [Modellkarte](https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v2), abgerufen 2026-08-10 | `model.safetensors` 3.087.466.808 Byte (≈ 2,88 GiB) — [HF-API `siblings`](https://huggingface.co/api/models/mixedbread-ai/mxbai-rerank-large-v2?blobs=true), abgerufen 2026-08-10 | „multilingual support (100+ languages, outstanding English and Chinese performance)" — [Modellkarte](https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v2), abgerufen 2026-08-10 | Nicht explizit in der Modellkarte als Zahl genannt; `config.json` trägt `max_position_embeddings: 32768` — [`config.json`](https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v2/raw/main/config.json), abgerufen 2026-08-10 | `Qwen2ForCausalLM` (`model_type: qwen2`) laut `config.json` — [`config.json`](https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v2/raw/main/config.json), abgerufen 2026-08-10 — kein BGE-M3-Derivat |
| gte-multilingual-reranker-base | `Alibaba-NLP/gte-multilingual-reranker-base` | Apache-2.0 — [Modellkarte](https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base), abgerufen 2026-08-10 | „306M" — [Modellkarte](https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base), abgerufen 2026-08-10 | `model.safetensors` 611.934.706 Byte (≈ 0,57 GiB) — [HF-API `siblings`](https://huggingface.co/api/models/Alibaba-NLP/gte-multilingual-reranker-base?blobs=true), abgerufen 2026-08-10 | „Supports over 70 languages" — [Modellkarte](https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base), abgerufen 2026-08-10 | „Max Input Tokens: 8192" — [Modellkarte](https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base), abgerufen 2026-08-10 | „Trained using an encoder-only transformers architecture" — [Modellkarte](https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base), abgerufen 2026-08-10 — kein Basismodell namentlich genannt, **nicht belegt** ob BGE-M3-Derivat |
| bge-reranker-v2-gemma | `BAAI/bge-reranker-v2-gemma` | Apache-2.0 — [Modellkarte](https://huggingface.co/BAAI/bge-reranker-v2-gemma), abgerufen 2026-08-10 | „3B params" — [Modellkarte](https://huggingface.co/BAAI/bge-reranker-v2-gemma), abgerufen 2026-08-10 | Drei Gewichts-Shards `model-0000{1,2,3}-of-00003.safetensors` = 4.911.635.192 + 4.978.830.584 + 134.242.760 = 10.024.708.536 Byte (≈ 9,33 GiB) — [HF-API `siblings`](https://huggingface.co/api/models/BAAI/bge-reranker-v2-gemma?blobs=true), abgerufen 2026-08-10 | „Suitable for multilingual contexts, performs well in both English proficiency and multilingual capabilities" — [Modellkarte](https://huggingface.co/BAAI/bge-reranker-v2-gemma), abgerufen 2026-08-10 | Kein expliziter Zahlenwert in der Modellkarte; Beispielcode nutzt `max_length=512`/`max_length=1024`, **nicht belegt** als harte Modellgrenze | „Built on `gemma-2b` from Google" — [Modellkarte](https://huggingface.co/BAAI/bge-reranker-v2-gemma), abgerufen 2026-08-10 — kein BGE-M3-Derivat |

## Details je Kandidat

### mixedbread-ai/mxbai-rerank-large-v2

Lizenz laut Modellkarten-Tag: `apache-2.0`. Das HF-Repo führt zusätzlich eine eigene
`LICENSE`-Datei (10.763 Byte), die diesen Tag bestätigt.

Die Modellkarte selbst nennt keine Zahl für die maximale Eingabelänge; belegt ist der
Wert `max_position_embeddings: 32768` aus der eigenen `config.json` — das ist eine
Primärquelle des Modells selbst (keine Ableitung von einem anderen Modell), auch wenn
sie nicht im README-Fließtext steht.

Backbone laut `config.json`: `architectures: ["Qwen2ForCausalLM"]`,
`model_type: "qwen2"` — ein Qwen2-basiertes Causal-LM, kein BGE-M3-Derivat.

Eingabeschema laut Modellkarte (Beispielcode):

```python
pairs = [(query, doc) for doc in documents]
scores = model.predict(pairs)
```

sowie alternativ `model.rank(query, documents)`. Das ist dasselbe Query/Passage-Paar-
Schema wie beim aktuellen `bge-reranker-v2-m3`, aber ohne Präfix- oder Prompt-Template.

**`sentence_transformers.CrossEncoder`-Ladbarkeit:** explizit in der Modellkarte
demonstriert — `from sentence_transformers import CrossEncoder` gefolgt von
`model = CrossEncoder("mixedbread-ai/mxbai-rerank-large-v2")`. Die Karte nennt keine
Ober- oder Untergrenze für `transformers`, sodass kein Konflikt mit dem gepinnten
`transformers==5.14.1` aus der Modellkarte selbst ableitbar ist — die Karte bestätigt
die Ladbarkeit aber nicht aktiv gegen genau diese Version, das bleibt ungetestet.

### Alibaba-NLP/gte-multilingual-reranker-base

Lizenz laut Modellkarten-Tag: `apache-2.0`.

Parameterzahl „306M" und Sprachabdeckung „Supports over 70 languages" (an anderer
Stelle der Karte auch „75 languages") direkt aus der Modellkarte. Maximale
Eingabelänge explizit als „Max Input Tokens: 8192" benannt.

Backbone: Die Karte beschreibt nur den Architekturtyp — „Trained using an
encoder-only transformers architecture, resulting in a smaller model size" — und
positioniert das Modell als „first reranker model in the GTE family", nennt aber
kein konkretes Basismodell. Ob es auf einem vortrainierten GTE-Embedding-Modell oder
auf BGE-M3 aufbaut, bleibt **nicht belegt**.

Eingabeschema laut Modellkarte (Beispielcode, mit chinesisch/englischem Beispielpaar):

```python
pairs = [["中国的首都在哪儿", "北京"], ["what is the capital of China?", "北京"]]
inputs = tokenizer(pairs, padding=True, truncation=True, return_tensors="pt", max_length=512)
scores = model(**inputs, return_dict=True).logits
```

**`sentence_transformers.CrossEncoder`-Ladbarkeit:** explizit in der Modellkarte
demonstriert, aber mit einer Zusatzbedingung:

```python
from sentence_transformers import CrossEncoder

model = CrossEncoder("Alibaba-NLP/gte-multilingual-reranker-base", trust_remote_code=True)
```

Die Karte nennt als Mindestversion `transformers>=4.36.0` (keine Obergrenze
angegeben), rechnerisch also kompatibel mit dem gepinnten `transformers==5.14.1` —
aber `trust_remote_code=True` bedeutet, dass Custom-Modelling-Code aus dem HF-Repo
nachgeladen wird, dessen Kompatibilität mit `transformers==5.14.1` die Karte selbst
nicht bestätigt. Damit: **ja, mit Einschränkung** — Ladbarkeit demonstriert, aber
`trust_remote_code`-Pfad gegen die konkrete gepinnte Version nicht von der Karte
getestet ausgewiesen.

### BAAI/bge-reranker-v2-gemma

Lizenz laut Modellkarten-Tag: `apache-2.0`.

Parameterzahl „3B params" direkt aus der Modellkarte übernommen (wörtlich zitiert,
auch wenn das Basismodell `gemma-2b` heißt — die Karte selbst benennt keine
Diskrepanz und wird hier nicht durch eine eigene Schätzung ersetzt).

Backbone laut Modellkarte: „Built on `gemma-2b` from Google" — kein BGE-M3-Derivat.

Downloadgröße: drei Gewichts-Shards laut HF-API `siblings`
(`model-00001-of-00003.safetensors` 4.911.635.192 Byte,
`model-00002-of-00003.safetensors` 4.978.830.584 Byte,
`model-00003-of-00003.safetensors` 134.242.760 Byte), Summe 10.024.708.536 Byte
(≈ 9,33 GiB).

Eingabeschema laut Modellkarte: für den empfohlenen Weg über `FlagEmbedding` ein
einfaches Query/Passage-Paar —

```python
from FlagEmbedding import FlagLLMReranker

reranker = FlagLLMReranker("BAAI/bge-reranker-v2-gemma", use_fp16=True)
score = reranker.compute_score(["query", "passage"])
```

— alternativ über reinen `transformers`-Code mit Tokenizer-Paaren
(`pairs = [['query_text', 'passage_text']]`, `max_length=512`) und einem
Yes/No-Prompt-Template für die LLM-Variante („Given a query A and a passage B,
determine whether the passage contains an answer to the query by providing a
prediction of either 'Yes' or 'No'.", Query mit „A: ", Passage mit „B: " vorangestellt).

**`sentence_transformers.CrossEncoder`-Ladbarkeit: nicht belegt.** Die Modellkarte
demonstriert ausschließlich zwei Lade-Wege — `FlagEmbedding.FlagLLMReranker` und
rohes `transformers` (`AutoModelForCausalLM`) — aber an keiner Stelle
`sentence_transformers.CrossEncoder`. Der von der Karte empfohlene
`FlagEmbedding`-Weg ist genau der Weg, den #714 bereits für `bge-reranker-v2-m3`
verworfen hat, weil `FlagEmbedding` `transformers<5.0` erzwingt und damit einen
Downgrade des im Repo gepinnten `transformers==5.14.1` nötig macht. Ein CrossEncoder-
Einsatz dieses Kandidaten wäre damit — falls überhaupt möglich — ein selbst gebauter
Wrapper um das Causal-LM, den die Modellkarte nicht zeigt.

## Ausgeschlossene Kandidaten

| Modell | Grund | Beleg |
|---|---|---|
| `jinaai/jina-reranker-v2-base-multilingual` | Lizenz **CC-BY-NC-4.0** (nicht-kommerziell) — inkompatibel mit der MIT-lizenzierten Codebasis dieses Plugins ([`LICENSE`](../../LICENSE)), exakt dasselbe Ausschlussmuster wie `jina-embeddings-v3` in #801 | Modellkarten-Tag `cc-by-nc-4.0` sowie wörtlicher Hinweis „licenced for research and evaluation purposes under CC-BY-NC-4.0. For commercial usage, please refer to Jina AI's APIs, AWS Sagemaker or Azure Marketplace offerings." — [Modellkarte](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual), abgerufen 2026-08-10 |

Ergänzend zur Vollständigkeit, ohne Wertung: `jina-reranker-v2-base-multilingual`
wäre mit 278M Parametern (0,3B) und max. 1024 Token Eingabelänge (mit
Sliding-Window-Option für längere Texte) sowie einem eigenständig trainierten
Backbone (kein in der Karte genanntes Basismodell) ein architektonisch interessanter
Kandidat gewesen — die Lizenz allein schließt ihn aber aus, unabhängig von jeder
technischen Eigenschaft.

## Backbone-Übersicht (reine Angabe, keine Wertung)

Alle drei heute produktiven Repo-Modelle (`BAAI/bge-m3` als Embedding-Backbone,
`BAAI/bge-reranker-v2-m3` als Reranker) bauen auf `bge-m3` auf. Von den drei
gelisteten Kandidaten baut **keiner belegbar auf `bge-m3` auf**:

- `mxbai-rerank-large-v2`: Qwen2-Causal-LM (`config.json`), kein BGE-M3-Derivat.
- `gte-multilingual-reranker-base`: eigenständige GTE-Familie, Basismodell in der
  Karte nicht benannt — **nicht belegt**, ob BGE-M3-Bezug besteht, aber die Karte
  positioniert es ausdrücklich als „first reranker model in the GTE family", nicht
  der BGE-Familie.
- `bge-reranker-v2-gemma`: baut auf `gemma-2b` (Google) — trotz „bge"-Namenspräfix
  kein BGE-M3-Derivat, sondern derselbe BAAI-Publisher mit anderem Backbone.

Alle drei Kandidaten würden die aktuelle BGE-M3-Monokultur der Repo-Pipeline
durchbrechen. Das ist hier ausschließlich als Information für eine spätere
Entscheidung festgehalten, nicht als Auswahlkriterium (Out-of-Scope für #803).

## Fazit

Drei Kandidaten bestehen die Lizenzprüfung und werden mit vollständig belegten
Feldern geführt: `mxbai-rerank-large-v2` (Apache-2.0, 2B Parameter, CrossEncoder-
Ladbarkeit ohne Einschränkung in der eigenen Karte demonstriert), `gte-multilingual-
reranker-base` (Apache-2.0, 306M Parameter, CrossEncoder-Ladbarkeit demonstriert,
aber mit `trust_remote_code=True`) und `bge-reranker-v2-gemma` (Apache-2.0, 3B
Parameter, CrossEncoder-Ladbarkeit **nicht belegt** — die Karte zeigt nur
`FlagEmbedding`- und rohe `transformers`-Wege, wobei der `FlagEmbedding`-Weg dasselbe
`transformers<5.0`-Downgrade-Problem hätte, das #714 bereits für `bge-reranker-v2-m3`
verworfen hat). Ein vierter geprüfter Kandidat, `jina-reranker-v2-base-multilingual`,
scheidet ausschließlich an der Lizenz (CC-BY-NC-4.0) aus.

Dieser Report trifft **keine** Empfehlung und liefert **keine** Messung — beides
bleibt einem Folge-Issue vorbehalten, das die tatsächliche Reranking-Qualität der
gelisteten Kandidaten (soweit ladbar) gegen ein Goldset misst.
