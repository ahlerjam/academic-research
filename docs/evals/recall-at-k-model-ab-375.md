# Eval-Report — Recall@10-Goldset DE/EN + Embedding-Modell-A/B (Issue #375)

**Datum:** 2026-07-27
**Komponente:** `compute_recall_at_k()` (`academic_vault/retrieval.py`) + drei
Embedding-Modellkandidaten (`sentence-transformers`)
**Modell:** n/a fuer den hermetischen Kernteil (kein LLM); die drei
A/B-Kandidaten sind selbst der Untersuchungsgegenstand
**Goldset:** `tests/fixtures/retrieval_goldset_de_en.json` — 12 Queries
(6 DE, 6 EN), 24 Fixture-Papers in 6 klar getrennten Themenclustern
(Transformer/Attention, Klimawandel, Hybrid-Retrieval, Computer Vision,
Quantencomputing, Bibliometrie)

## Zwei unterschiedliche Messungen — nicht verwechseln

Dieses Issue erzeugt zwei separate, methodisch unterschiedliche Ergebnisse
auf demselben Goldset:

1. **Hermetischer Kern-Test** (`tests/test_vault_recall_goldset.py`, laeuft
   in jedem `uv run pytest tests/`): echter `search_papers(..., rerank=True)`
   -Aufruf gegen ein reales Fixture-Vault — FTS5 + vec0-KNN via RRF fusioniert
   — mit dem deterministischen `fake_embedder` (Hashing-Bag-of-Words,
   `tests/conftest.py`) statt eines echten Modells. Mean-Recall@10 = **0.6875**
   (Range 0.5–1.0 je Query). Dieser Wert ist **kein** Modellvergleich, sondern
   ein Sanity-Check, dass der Hybrid-Suchpfad echte, nicht-triviale Treffer
   liefert und via `compute_recall_at_k` korrekt bewertet.
2. **Modell-A/B** (dieses Kapitel, `scripts/eval/recall_at_k_model_ab.py`,
   manuell/einmalig ausgefuehrt): reine Cosine-Similarity-Rangfolge ueber
   Title+Abstract-Embeddings der drei echten Kandidatenmodelle, ohne FTS5/RRF.
   Ergebnisse unten.

## A/B-Ergebnisse (reale Modelle, Cosine-Top-k, k=10)

| Modell | Model-ID | Dim | Mean Recall@10 | Query-Range |
|---|---|---|---|---|
| e5-small (Default) | `intfloat/multilingual-e5-small` | 384 (nativ) | **1.0000** | 1.0–1.0 |
| MiniLM | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 (nativ) | **1.0000** | 1.0–1.0 |
| Qwen3-Embedding-0.6B | `Qwen/Qwen3-Embedding-0.6B` | 384 (`truncate_dim=384`, nativ 1024) | **1.0000** | 1.0–1.0 |

Alle drei Kandidaten erreichen auf allen 12 Goldset-Queries (DE und EN,
breite Cluster-Queries wie auch enge 1-2-Paper-Queries) perfekten
Recall@10 = 1.0 — pro Query nachvollziehbar in der Skript-Ausgabe
(`--model <key>` liefert die per-Query-Aufschluesselung als JSON).

### Ehrliche Einordnung: Deckeneffekt, kein Differenzierungs-Ergebnis

Das ist ein **Deckeneffekt (ceiling effect)**, kein Qualitaetsunterschied
zwischen den Modellen: Mit nur 24 Papers in 6 thematisch stark
distinkten Clustern (bewusst so entworfen, damit der hermetische Kern-Test
mit dem simplen Hashing-Bag-of-Words-Embedder ueberhaupt sauber trennbare
Cluster hat, siehe Plan-Risiko 2) ist reine Cosine-Top-10-Rangfolge fuer
jedes der drei modernen multilingualen Embedding-Modelle trivial loesbar.
Dieses Goldset kann auf Basis der aktuellen Messung **keine** Rangfolge
zwischen e5-small/MiniLM/Qwen3-Embedding-0.6B belegen — dafuer waere ein
groesseres, weniger sauber separiertes Set noetig (laut Issue #375 explizit
Out-of-Scope: "Aufbau eines vollwertigen, offiziell benchmarkten
MTEB-Vergleichs"). Der Wert dieses A/B-Laufs liegt darin, zu belegen, dass
**alle drei Kandidaten** auf realen Text-Embeddings fuer diese Aufgabenklasse
grundsaetzlich funktionieren (kein Kandidat faellt durch/degeneriert) —
nicht darin, einen Sieger zu kueren. Die Modellwahl bleibt e5-small als
Default (Issue-Vorgabe), Qwen3-Embedding-0.6B bleibt dokumentierter,
groesserer Upgrade-Pfad (0.6B Parameter vs. e5-small ~118M).

## Methodik / Prompting je Modell

- **e5-small:** asymmetrisches Retrieval-Praefix-Schema (Teil des
  Trainings-Setups): Queries mit `"query: "`, Dokumente mit `"passage: "`
  praefigiert (siehe `academic_vault/embedding_model.py`).
- **MiniLM (`paraphrase-multilingual-MiniLM-L12-v2`):** symmetrisches
  Paraphrase-Modell, kein Praefix/Prompt.
- **Qwen3-Embedding-0.6B:** `prompt_name="query"` fuer Queries (im Modell
  hinterlegter Prompt, ueber `sentence-transformers.encode(..., prompt_name=
  "query")`), Dokumente ohne Prompt; `truncate_dim=384` beim Laden gesetzt
  (natives Modell liefert 1024 Dimensionen), damit die Vergleichbarkeit zur
  vec0-Spaltenbreite (`FLOAT[384]`) gegeben ist. API-Details verifiziert via
  Context7 (`sentence-transformers`-Doku, `docs/sentence_transformer/usage/
  usage.rst` + Migration-Guide zu `truncate_dim`).

Alle drei Laeufe embedden denselben Dokumenttext (`"{title}. {abstract}"`)
und dieselben 12 Queries; Aehnlichkeit ist Cosine-Similarity auf
L2-normalisierten Vektoren.

## Eval-Ausfuehrung (Reproduktion)

```bash
# Hermetischer Kern-Test (Teil von `uv run pytest tests/`, kein Netzwerk/API-Key):
uv run pytest tests/test_vault_recall_goldset.py -v

# Modell-A/B (NICHT hermetisch: 3 echte HuggingFace-Downloads, mehrere
# 100 MB bis ~2.4 GB; CPU-Inferenz auf 24 Dokumenten + 12 Queries):
uv run python scripts/eval/recall_at_k_model_ab.py                 # alle drei
uv run python scripts/eval/recall_at_k_model_ab.py --model e5-small
uv run python scripts/eval/recall_at_k_model_ab.py --model minilm
uv run python scripts/eval/recall_at_k_model_ab.py --model qwen3-embedding-0.6b
```

Modellgewichte landen im ueblichen `sentence-transformers`/HuggingFace-Cache
(`~/.cache/huggingface/hub` bzw. `default_cache_dir()` fuer e5-small).

## Momentaufnahme, kein MTEB-Ersatz

Diese Zahlen sind auf einer Maschine/Modellversion am 2026-07-27 erzeugt
(`sentence-transformers` 5.6.1) und bilden **keinen** konsolidierten,
offiziell benchmarkten MTEB-Vergleich fuer Deutsch ab — laut Recherche in
Issue #375 fuer DE ohnehin nicht konsolidiert auffindbar und explizit
Out-of-Scope. Fuer eine echte Modellwahl-Entscheidung braeuchte es ein
groesseres, haerteres Goldset mit ueberlappenden/aehnlichen Themen statt
sauber getrennter Cluster.

## Empfehlungen

- e5-small bleibt Default (Issue-Vorgabe, keine Aenderung angezeigt durch
  diese Messung).
- Fuer eine tatsaechlich differenzierende Modellwahl: ein zweites, haerteres
  Goldset mit thematisch ueberlappenden Papers (z. B. mehrere
  Transformer-Subtopics, die sich nur in Details unterscheiden) waere noetig
  — bewusst nicht Teil dieses Issues.
- Qwen3-Embedding-0.6B ist ~5x groesser als e5-small (0.6B vs. ~118M
  Parameter) bei hier identischem Recall@10 auf diesem Goldset; ein
  Upgrade waere nur bei nachgewiesenem Recall-Gewinn auf einem haerteren Set
  gerechtfertigt (Rechenkosten/Latenz steigen sonst ohne Mehrwert).
