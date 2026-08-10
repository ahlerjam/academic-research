# Reranker-Ablation auf dem Chunk-Goldset (Issue #804)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-10
**Komponente:** `academic_vault` (Retrieval-Pfad; **kein** Eingriff im
produktiven Code — aller Code dieses Laufs liegt unter `scripts/eval/`)
**Goldset:** Chunk-Goldset aus [#708](retrieval-chunk-goldset-708.md), 60 Queries seit [#800](2026-08-10-chunk-goldset-widening-800.md)
**Rohdaten:** [`2026-08-10-reranker-ablation-804-live-results.json`](2026-08-10-reranker-ablation-804-live-results.json)

## Fragestellung

#722 hat den Reranker-Beitrag per Leave-one-out mit +0,0000 Recall@10,
+0,0107 nDCG@10 und +0,0144 MRR beziffert. Das Rauschband des Repos liegt bei
0,02 (#708) — beide Werte liegen darunter, ohne dass eine Signifikanzaussage
dazu existierte. Seit #729 laufen zudem alle Retrieval-Messungen mit
abgeschaltetem Reranker, weil er die Zahlen sonst verwischt — der
Produktivpfad läuft damit in einer Konfiguration, die keine Messung erfasst,
obwohl die Komponente rund 1 s je Suche und 2120 MB Peak-RSS kostet (#714).

Dieser Report liefert die Signifikanzaussage: gepaarter Bootstrap über genau
die Kandidaten, die der Produktionscode fusioniert — einmal in
RRF-Reihenfolge ("aus"), einmal nach `rerank_score` sortiert ("an").

## Messaufbau

| | |
|---|---|
| Fusion | echte Produktionsfunktionen: `server._vec0_search`, `server._attach_chunk_to_fts_hit` (chunk-level `chunk_fts`, #726/#727), `retrieval.reciprocal_rank_fusion`, `top_n=k*4` (#727-Konstante) |
| Reranker | echter lokaler `BAAI/bge-reranker-v2-m3` (`sentence_transformers.CrossEncoder`, #714) |
| Generator (live) | `scripts/eval/build_reranker_ablation_804.py` (env-gated `VAULT_RERANK_LIVE_TEST=1`) |
| Auswertung (hermetisch) | `scripts/eval/run_reranker_ablation_804.py` — kein Netz, kein Modell |
| Signifikanz | gepaarter Bootstrap über die 60 Queries, 10 000 Resamples, Seed 804, 95-%-Perzentilintervall |
| Regel | Ein Abstand zwischen 'an' und 'aus' traegt genau dann, wenn das 95-%-Intervall der gepaarten Bootstrap-Differenz (10 000 Resamples, Seed 804, ueber die Queries gepaart) die Null nicht enthaelt. |

"aus" und "an" sortieren **dieselben** fusionierten Kandidaten nur
unterschiedlich um (nach `rrf_score` bzw. nach `rerank_score`) — kein
zweiter Suchlauf, keine unterschiedliche Kandidatenmenge. Der CI-Job
`retrieval-goldset` fährt den hermetischen Lauf gegen die Rohdaten unten;
weicht eine Zahl ab, wird die Pipeline rot, statt dass der Report unbemerkt
altert.

## Ergebnis

Zahlen über alle 60 Queries, `k = 10` — Qualitätsmetriken und Kosten (Suchlatenz,
Peak-RSS) in derselben Tabelle, weil beide Seiten zusammen gelesen werden müssen:
ein Reranker, der Latenz/RSS kostet, aber keinen belegbaren Qualitätsgewinn bringt,
ist nur im direkten Nebeneinander beider Werte erkennbar. Messhardware: Apple M4
Pro, 12 Kerne, 25,8 GB RAM, macOS-26.5.2-arm64, Python 3.12.13.

| Bedingung | Recall@10 | nDCG@10 | MRR | Suchlatenz p50 | Suchlatenz p95 | Peak-RSS |
|---|---|---|---|---|---|---|
| `aus` (RRF-Reihenfolge, aktueller Betriebszustand seit #729) | 0,8167 | 0,7097 | 0,6764 | 17,2 ms | 35,2 ms | 74,3 MB |
| `an` (nach `rerank_score` sortiert) | 0,7917 | 0,7190 | 0,6970 | 3057,5 ms | 3542,7 ms | 900,7 MB |

Gepaarter Bootstrap, Delta = `an` minus `aus`:

| Metrik | Delta | 95-%-CI | trägt? |
|---|---|---|---|
| Recall@10 | −0,0250 | [−0,1000; 0,0500] | nein |
| nDCG@10 | +0,0093 | [−0,0452; 0,0704] | nein |
| MRR | +0,0206 | [−0,0400; 0,0872] | nein |

**Fazit: Der aktive Reranker hat im heutigen Zustand keinen vom Rauschen
trennbaren Effekt auf Recall@10, nDCG@10 oder MRR — für keine der drei
Metriken schließt das 95-%-Intervall der gepaarten Bootstrap-Differenz die
Null aus.**

Die Punktschätzung deckt sich mit der Größenordnung aus #722 (positive, aber
kleine Verschiebung bei nDCG@10/MRR, hier zusätzlich ein kleiner negativer
Ausschlag bei Recall@10) — neu ist hier ausschließlich die
Konfidenzaussage: keiner der drei Abstände ist von Null zu unterscheiden.

## Kosten

Der aktive Reranker kostet auf diesem Goldset rund **3 s zusätzliche
Suchlatenz** und **rund 826 MB zusätzliches Peak-RSS** je Suche (Zahlen in
der Tabelle unter „Ergebnis" oben) — bei einem Effekt, der sich laut obigem
Bootstrap nicht vom Rauschen trennen lässt.

Gemessen über den echten Suchpfad `server.search_papers(rerank=True)`, je
Bedingung in einem **eigenen Subprozess** (RSS-Isolation — `ru_maxrss` ist
pro Prozess monoton steigend, sonst kontaminiert das Laden des
CrossEncoder-Modells für "an" die "aus"-Messung). Latenz und Peak-RSS sind
NICHT Teil des `--check-against`-Gatters (Muster #731): sie hängen an der
Maschine und wären als Gatter nur eine Quelle roter CI-Läufe ohne Aussage.

## Grenzen dieses Laufs

1. **Lexikalische Seite strukturell schwach.** #789 hat gezeigt, dass die
   Kandidatenquelle `papers_fts`/`papers_trgm` auf diesem synthetischen
   Goldset fast nie trifft — der Reranker sortiert damit überwiegend
   vektorielle Kandidaten um. Ob sich das Bild bei einem Korpus mit stärkerem
   lexikalischem Signal ändert, ist offen.
2. **Kleines Goldset.** 60 Queries ergeben eine Auflösungsgrenze von rund
   0,0167 Recall-Punkten je Query — ein Nullbefund bei einem Effekt dieser
   Größenordnung ist erwartbar, auch wenn ein wirklicher (aber kleiner)
   Effekt existiert.
3. **Ein Reranker-Modell.** Gemessen ist ausschließlich der heutige
   Produktivstand `BAAI/bge-reranker-v2-m3`. Alternative Reranker-Modelle
   sind ausdrücklich Scope eines Folge-Issues.
4. **Keine Aussage zum Produktivpfad.** Dieses Issue misst; es ändert nichts
   am Schalter `ACADEMIC_RESEARCH_RERANKER_ENABLED`. Der Beschluss fällt
   später und an anderer Stelle.

## Reproduktion

```bash
# hermetisch (kein Netz, kein Modell) — das ist auch, was CI fährt
uv run python scripts/eval/run_reranker_ablation_804.py \
  --check-against docs/evals/2026-08-10-reranker-ablation-804-live-results.json

# Rohdaten neu erzeugen (lädt den lokalen Reranker, CPU-Inferenz)
VAULT_RERANK_LIVE_TEST=1 uv run python scripts/eval/build_reranker_ablation_804.py \
  --write-live-results docs/evals/2026-08-10-reranker-ablation-804-live-results.json
```

Je Query liegen die fusionierten Kandidaten samt echten `rerank_score`-Werten
unter `tests/fixtures/reranker_ablation_804/candidates.json`. Ein
`fixture_sha256` über die Kandidaten und ein `goldset_manifest_sha256` gegen
das #708-Goldset brechen den Lauf ab, sobald Fixture und Texte
auseinanderlaufen.

## Was dieser Report nicht leistet

Keine Wechselempfehlung zu alternativen Rerankern, keine Änderung am
produktiven Pfad. "Kein nachweisbarer Effekt" ist laut Issue ein zulässiges
Ergebnis — dieses Issue misst, es rettet den Reranker nicht.
