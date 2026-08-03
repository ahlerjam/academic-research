# Eval-Report — hartes Recall@10-Goldset mit Themen-Overlap + Embedding-Modell-A/B (Issue #628)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-03
**Komponente:** `compute_recall_at_k()` (`academic_vault/retrieval.py`) + fünf
Embedding-Modellkandidaten (`sentence-transformers`)
**Modell:** n/a für den hermetischen Kernteil (kein LLM); die fünf
A/B-Kandidaten sind selbst der Untersuchungsgegenstand
**Goldset:** `tests/fixtures/retrieval_goldset_hard_overlap_628.json` — 8
Queries, 24 Fixture-Papers in 2 Themen (`transformer-efficiency`,
`retrieval-augmented-generation`) mit je 3 eng verwandten Subtopics

## Vorgeschichte: der Deckeneffekt aus #375

Das bestehende Goldset (`retrieval_goldset_de_en.json`, #375) besteht aus 24
Papers in 6 thematisch scharf getrennten Clustern (Transformer/Attention,
Klimawandel, Hybrid-Retrieval, Computer Vision, Quantencomputing,
Bibliometrie). Auf diesem Set erreichten alle drei damaligen Kandidaten
(e5-small, MiniLM, Qwen3-Embedding-0.6B) Recall@10 = 1.0 auf allen 12
Queries — ein Deckeneffekt, keine belegte Rangfolge. Dieses Issue baut das
im damaligen Report explizit empfohlene härtere Set.

## Wie das neue Goldset überlappt

Statt 6 klar getrennter Cluster besteht das neue Set aus nur **2 Themen**,
die jeweils in **3 eng verwandte Subtopics** zerfallen:

- **`transformer-efficiency`** (12 Papers): `sparse-attention`,
  `linear-attention`, `quantized-inference`. Alle drei Subtopics teilen das
  Kernvokabular "Transformer", "Attention", "effiziente Inferenz" — sie
  unterscheiden sich nur im konkreten Mechanismus (feste/gelernte
  Sparsity-Muster vs. Kernel-Linearisierung vs. Quantisierung der Gewichte).
- **`retrieval-augmented-generation`** (12 Papers): `dense-retrieval`,
  `hybrid-fusion`, `long-context-rag`. Alle drei Subtopics teilen
  "Retrieval", "Generation", "Sprachmodell" — Unterschied ist der
  Retrieval-Mechanismus (dichte Embeddings vs. Sparse+Dense-Fusion vs.
  längere Kontextfenster).

Jedes Subtopic hat 4 Papers (2 EN, 2 DE) mit nahezu identischer
Formulierungsebene innerhalb des Subtopics, um Cosine-Rangfolge auf
Title+Abstract-Ebene tatsächlich schwer zu machen — ein Modell, das nur grob
auf Themenebene trennt, verwechselt Papers benachbarter Subtopics leicht.

**Zusätzlich strukturell erzwungen:** Jedes Thema hat eine themenweite Query
(`hq07`, `hq08`), deren `relevant_paper_ids` **alle 12 Papers** des Themas
umfasst. Da `k=10`, kann Recall@10 für diese beiden Queries per
Schubfachprinzip **niemals** 1.0 erreichen (maximal 10/12 = 0.8333) — das
stellt AC2 unabhängig von der tatsächlichen Modellqualität sicher und macht
das Goldset robust gegen einen erneuten Deckeneffekt. Die übrigen 6 Queries
zielen je auf ein einzelnes Subtopic (4 relevante Papers) und prüfen die
tatsächliche semantische Trennschärfe innerhalb eines Themas.

## A/B-Ergebnisse (reale Modelle, Cosine-Top-k, k=10, hartes Goldset)

| Modell | Model-ID | Dim | Mean Recall@10 | Query-Range |
|---|---|---|---|---|
| e5-small (Default) | `intfloat/multilingual-e5-small` | 384 (nativ) | **0.8958** | 0.6667–1.0 |
| MiniLM | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 (nativ) | **0.9271** | 0.75–1.0 |
| Qwen3-Embedding-0.6B | `Qwen/Qwen3-Embedding-0.6B` | 384 (`truncate_dim=384`, nativ 1024) | **0.9583** | 0.8333–1.0 |
| BGE-M3 | `BAAI/bge-m3` | 1024 (nativ) | **0.9375** | 0.75–1.0 |
| multilingual-e5-large | `intfloat/multilingual-e5-large` | 1024 (nativ) | **0.9583** | 0.8333–1.0 |

Rohdaten (per-Query-Aufschlüsselung aller fünf Kandidaten):
[`recall-at-k-model-ab-hard-628-live-results.json`](recall-at-k-model-ab-hard-628-live-results.json).

### Differenzierung erreicht — kein Deckeneffekt mehr

Anders als auf dem #375-Set erreicht **kein** Kandidat Recall@10 = 1.0 über
alle 8 Queries: Bereits die beiden themenweiten Queries (`hq07`, `hq08`)
deckeln jeden Kandidaten strukturell auf maximal 0.8333. Auf den reinen
Subtopic-Queries (`hq01`–`hq06`) zeigt sich eine stärker differenzierte Lage:
Qwen3-Embedding-0.6B, BGE-M3 und multilingual-e5-large erhalten auf allen
Subtopic-Queries exakt 1.0 (vollständige Treffer), während e5-small und MiniLM
mit Einzelwerten von 0.75 auf `hq04` ein schwaches Differenzierungssignal
liefern. Der häufig zitierte Tiefstwert 0.6667 (e5-small) stammt dagegen
ausschließlich von den themenweiten Queries (`hq08`), nicht von den
Subtopic-Queries selbst. Die gesamte Rangfolge zwischen den drei besten
Kandidaten wird daher allein durch die strukturell auf 0.8333 gedeckelten
themenweiten Queries bestimmt; ohne diese beiden Queries läge die komplette
Spitzengruppe erneut bei 1.0.

**e5-small (aktueller Default) ist auf diesem härteren Set der schwächste der
fünf Kandidaten** — sowohl im Mittel (0.8958, niedrigster Wert aller fünf)
als auch im schlechtesten Einzelquery-Wert (0.6667). Qwen3-Embedding-0.6B und
multilingual-e5-large teilen sich mit 0.9583 den besten Mittelwert, BGE-M3
liegt mit 0.9375 dazwischen; MiniLM (0.9271) liegt vor e5-small. Die Spanne
zwischen bestem und schlechtestem Kandidat beträgt 6,25 Prozentpunkte
(0.8958–0.9583) — ein sichtbares, aber auf nur 8 Queries kein statistisch
robustes Signal.

## Methodik / Prompting je Modell

- **e5-small, e5-large:** asymmetrisches Retrieval-Präfix-Schema (Teil des
  Trainings-Setups): Queries mit `"query: "`, Dokumente mit `"passage: "`
  präfigiert. Für e5-large auf der Modellkarte verifiziert ("Each input text
  should start with 'query: ' or 'passage: ', even for non-English texts").
- **MiniLM (`paraphrase-multilingual-MiniLM-L12-v2`):** symmetrisches
  Paraphrase-Modell, kein Präfix/Prompt.
- **Qwen3-Embedding-0.6B:** `prompt_name="query"` für Queries (im Modell
  hinterlegter Prompt), Dokumente ohne Prompt; `truncate_dim=384` beim Laden
  gesetzt (natives Modell liefert 1024 Dimensionen).
- **BGE-M3:** kein Präfix/Prompt nötig — auf der Modellkarte verifiziert
  ("the BGE-M3 model no longer requires adding instructions to the
  queries"), anders als frühere BGE-Generationen. Natives 1024d,
  8192-Token-Fenster (hier ungenutzt, da Title+Abstract kurz bleiben).

Alle fünf Läufe embedden denselben Dokumenttext (`"{title}. {abstract}"`)
und dieselben 8 Queries; Ähnlichkeit ist Cosine-Similarity auf
L2-normalisierten Vektoren.

## Eval-Ausführung (Reproduktion)

```bash
# Hermetische Struktur-/Config-Tests (Teil von `uv run pytest tests/`,
# kein Netzwerk/API-Key):
uv run pytest tests/test_recall_goldset_hard_overlap_628.py -v
uv run pytest tests/test_recall_ab_config.py -v

# Modell-A/B (NICHT hermetisch: fünf echte HuggingFace-Downloads, mehrere
# 100 MB bis ~2.3 GB; CPU-Inferenz auf 24 Dokumenten + 8 Queries):
uv run python scripts/eval/recall_at_k_model_ab.py --goldset hard                        # alle fuenf
uv run python scripts/eval/recall_at_k_model_ab.py --goldset hard --model bge-m3
uv run python scripts/eval/recall_at_k_model_ab.py --goldset hard --model e5-large
```

Modellgewichte landen im üblichen `sentence-transformers`/HuggingFace-Cache
(`~/.cache/huggingface/hub`).

## Momentaufnahme, kein MTEB-Ersatz

Diese Zahlen sind auf einer Maschine/Modellversion am 2026-08-03
(`sentence-transformers` 5.6.1) erzeugt und bilden **keinen** konsolidierten,
offiziell benchmarkten MTEB-Vergleich ab (laut #375-Recherche für DE ohnehin
nicht konsolidiert auffindbar, explizit Out-of-Scope für #628). Das Set ist
synthetisch (Fixture-Papers, keine echten Abstracts kopiert) und mit den in
diesem Report dokumentierten Subtopic-Paaren bewusst so konstruiert, dass es
nicht trivial lösbar ist — es bleibt aber ein kleines, gezielt konstruiertes
Diagnose-Set, kein umfassender Benchmark.

## Empfehlung

**Nein, kein Modellwechsel allein auf Basis dieser Messung.** Die Messung
zeigt zum ersten Mal ein echtes Differenzierungssignal (e5-small ist
durchgängig der schwächste Kandidat, Qwen3-Embedding-0.6B und
multilingual-e5-large durchgängig die stärksten) — das ist genau der
Fortschritt, den dieses Issue liefern sollte. Für eine tatsächliche
Wechsel-Entscheidung reicht das aber nicht:

- 8 Queries auf 24 synthetischen Papers sind ein Diagnose-Set, kein
  Benchmark; die 6,25-Prozentpunkte-Spanne zwischen bestem und
  schlechtestem Kandidaten ist auf dieser Stichprobengröße nicht robust
  gegen Zufallsrauschen in der Fixture-Formulierung.
- Ein Wechsel auf BGE-M3 oder multilingual-e5-large ist keine reine
  Modell-Config-Änderung: beide liefern nativ 1024 statt 384 Dimensionen,
  was eine Schema-Migration von `FLOAT[384]` auf `FLOAT[1024]` in der
  vec0-Tabelle und eine Neuindizierung des gesamten Vaults erzwingen würde
  (bewusst Out-of-Scope für #628, siehe Issue-Scope).
- BGE-M3s 8192-Token-Fenster würde zusätzlich Teile der
  Chunking-Mechanik (`TARGET_TOKENS = 448` in `chunking.py`) obsolet
  machen — auch das eine Folgeentscheidung, kein Nebeneffekt dieses Reports.

**Empfehlung für das Folge-Issue (Modellwahl):** Qwen3-Embedding-0.6B,
multilingual-e5-large und BGE-M3 sind auf Basis dieser beiden Läufe
(#375 + #628) die aussichtsreichsten Kandidaten für eine vertiefte Prüfung.
Qwen3-Embedding-0.6B bleibt dabei als einziger der drei ohne Schema-Bruch
einsetzbar (`truncate_dim=384`, per Modellkarte für Matryoshka-Truncation
ausgelegt); ob eine 384d-Truncation von BGE-M3/e5-large ohne nennenswerten
Recall-Verlust möglich wäre, ist unverifiziert (unklar, ob diese Modelle für
Matryoshka-Truncation trainiert wurden) und müsste vor einer Empfehlung
gegen die jeweilige Modellkarte geprüft werden, nicht angenommen — sonst
bliebe der 1024d-Weg mit Schema-Migration die einzige Option für diese
beiden. e5-small bleibt bis zu einer solchen vertieften Prüfung Default
(Issue-Vorgabe, #628 trifft explizit keine Wechsel-Entscheidung).
