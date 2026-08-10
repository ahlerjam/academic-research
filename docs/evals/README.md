# Evals-Reports

[← Doku-Übersicht](../README.md)

Dieses Verzeichnis enthaelt die Eval-Reports der Release-Kandidaten. Die Reports sind
**Momentaufnahmen** eines einzelnen Laufs und altern; der Sollzustand steht in der
Eval-Strategie. Wer wissen will, was heute gemessen wird, liest zuerst die Strategie und
danach höchstens den passenden Report.

> **Zuerst lesen:** [`STRATEGY.md`](STRATEGY.md) legt fuer jede Komponente unter
> `evals/` offen, ob sie real gemessen (`metric`), nur strukturell geprueft
> (`structural`) oder entfernt (`removed`) ist — plus die Bezifferung des
> API-Budgets, das echte Laeufe kosten wuerden. Die Strategie ist der Sollzustand
> und wird von `tests/evals/test_eval_strategy.py` erzwungen.

## Inhalt dieses Verzeichnisses

| Datei | Was drinsteht |
|-------|---------------|
| [`STRATEGY.md`](STRATEGY.md) | Sollzustand: Status je Eval-Komponente, Budgetbedarf (aktuell) |
| [`TEMPLATE.md`](TEMPLATE.md) | Leere Vorlage fuer einen neuen Report |
| [`2026-04-23-summary.md`](2026-04-23-summary.md) | Momentaufnahme: Eval-Infrastruktur zu v5.2.0 |
| [`recall-at-k-model-ab-375.md`](recall-at-k-model-ab-375.md) | Momentaufnahme: Recall@10-Goldset + Embedding-Modell-A/B (#375) |
| [`recall-at-k-model-ab-hard-628.md`](recall-at-k-model-ab-hard-628.md) | Momentaufnahme: hartes Recall@10-Goldset mit Themen-Overlap + BGE-M3/e5-large-A/B (#628) |
| [`recall-at-k-model-ab-hard-628-live-results.json`](recall-at-k-model-ab-hard-628-live-results.json) | Rohdaten des manuellen Live-Laufs zu obigem Report (Per-Query-Aufschlüsselung aller fünf Kandidaten) |
| [`v6.2-tier-eval.md`](v6.2-tier-eval.md) | Momentaufnahme: Auto-Download-Tier-Pipeline v6.2 |
| [`2026-08-03-live-fetch-weekly-first-runs.md`](2026-08-03-live-fetch-weekly-first-runs.md) | Momentaufnahme: erste beiden echten `live-fetch-weekly`-Läufe, Auswertung je Fetcher (#612) |
| [`2026-08-04-trigger-baseline-614.md`](2026-08-04-trigger-baseline-614.md) | Momentaufnahme: erster echter Lauf der Trigger-Evals, Recall/FPR je Skill (#614) |
| [`2026-08-04-trigger-baseline-614-live-results.json`](2026-08-04-trigger-baseline-614-live-results.json) | Rohdaten des Trigger-Baseline-Laufs (Per-Skill-Aufschlüsselung, Fehlklassifikationen, Tokens) |
| [`2026-08-05-disable-model-invocation-622.md`](2026-08-05-disable-model-invocation-622.md) | Prüfung je Kandidat (#622): warum 0 Skills mit `disable-model-invocation` markiert werden, Listing-Größe vorher/nachher |
| [`embedding-truncatability-730.md`](embedding-truncatability-730.md) | Belegte Truncatierbarkeit der drei #628-Kandidaten sowie (seit #801) Arctic-Embed L v2.0 auf 384d je Modellkarte — nur Qwen3-Embedding-0.6B ohne Schema-Migration einsetzbar, BGE-M3/e5-large „nicht belegt", Arctic sichert nur 256d zu, nicht 384d (#730, #801) |
| [`2026-08-06-extended-nli-goldset-721.md`](2026-08-06-extended-nli-goldset-721.md) | Momentaufnahme: erweitertes NLI-Goldset (186 Fälle, 30 echte Paper, acht Fächer) ins Repo aufgenommen, Reproduktion der #720-Schwellenkurve (#721) |
| [`retrieval-chunk-goldset-708.md`](retrieval-chunk-goldset-708.md) | Chunk-Goldset (61 Chunks, 60 Queries seit [#800](2026-08-10-chunk-goldset-widening-800.md), ursprünglich 30/26) mit Recall@10/nDCG@10/MRR, hermetisch in CI dank eingecheckter Vektoren — inkl. gemessener Sprachlücke DE→EN (#708) |
| [`2026-08-07-hyde-multiquery-733.md`](2026-08-07-hyde-multiquery-733.md) | HyDE und Multi-Query prototypisch gegen das Chunk-Goldset aus #708 gemessen: nDCG@10/MRR je Arm, Sprachlücke getrennt ausgewiesen, Latenz je Verfahren, Empfehlung aus den Zahlen (#733) |
| [`2026-08-07-hyde-multiquery-733-live-results.json`](2026-08-07-hyde-multiquery-733-live-results.json) | Rohdaten des Messlaufs (alle vier Arme, per Query, inklusive Deltas und Latenzblock) — vom CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft |
| [`2026-08-07-bge-m3-nli-scorer-720.md`](2026-08-07-bge-m3-nli-scorer-720.md) | Momentaufnahme: NLI-Scorer-Wechsel auf `bge-m3-zeroshot-v2.0` @ Schwelle 0,95, A/B über 278 Fälle, `condition-stripped`-Grenze, zwei verworfene Zusatzansätze (#720) |
| [`retrieval-ablation-722.md`](retrieval-ablation-722.md) | Ablation der vier Retrieval-Änderungen #701/#702/#703/#714 gegen die volle Hybrid-Pipeline (FTS5+Vektor+RRF+Reranker), Paper-Ebene-Aggregation aus #708, Leave-one-out je Änderung, aufgedeckter FTS5-Sanitize-Defekt außerhalb des Scopes (#722) |
| [`retrieval-ablation-722-live-results.json`](retrieval-ablation-722-live-results.json) | Rohdaten des Ablationslaufs (alle 6 Kombinationen, per Query, inklusive `fts5_syntax_errors`) |
| [`2026-08-08-embedding-candidates-731.md`](2026-08-08-embedding-candidates-731.md) | Sieben Embedding-Kandidaten auf dem Chunk-Goldset aus #708 gemessen (fünf ursprünglich, plus Snowflake Arctic-Embed L v2.0 nativ/256d seit #801): nDCG@10/MRR/Recall@10, CPU-Indexierungszeit und Download-Größe gleichrangig, Preis der Schema-Migration je Kandidat, gepaarter Bootstrap samt Auflösungsgrenze (#731, #801) |
| [`2026-08-08-embedding-candidates-731-live-results.json`](2026-08-08-embedding-candidates-731-live-results.json) | Rohdaten des Kandidatenlaufs (alle sieben Kandidaten, per Query, inklusive Zeit-, Hardware- und Signifikanzblock) — vom CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft |
| [`2026-08-08-embedding-model-decision-732.md`](2026-08-08-embedding-model-decision-732.md) | Entscheidung auf Basis der #731-Zahlen: Wechsel auf `BAAI/bge-m3` (1024d) statt `qwen3-384` (migrationsfrei, aber ~80x CPU-Indexierungszeit) oder „bleiben" bei `e5-small`, Hardwarekosten auf GPU-losem Laptop explizit gewichtet, Migrationsprobe mit dem echten Modell (#732); Fortschreibung: Arctic-Embed L v2.0 bestätigt die Entscheidung, statistisch nicht von `bge-m3` unterscheidbar (#801) |
| [`2026-08-08-chunk-fusion-ablation-729.md`](2026-08-08-chunk-fusion-ablation-729.md) | Trägt der Umbau auf Chunk-Ebene (#726 Chunk-FTS-Index, #727 Chunk-Fusion)? Drei Zustände (vorher/Zwischenzustand A/nachher) gegen das #708-Goldset, Index- und Fusionsbeitrag getrennt ausgewiesen, Index-Zuwachs und Suchlatenz an einem 60-Paper-Vault, vollständig hermetisch (#729) |
| [`2026-08-08-chunk-fusion-ablation-729-live-results.json`](2026-08-08-chunk-fusion-ablation-729-live-results.json) | Rohdaten des Ablationslaufs (alle drei Zustände, per Query, inklusive Kosten-Block) |
| [`2026-08-09-chunk-fusion-goldset-790.md`](2026-08-09-chunk-fusion-goldset-790.md) | Gezielt konstruiertes Probe-Goldset (31 Paper / 102 Chunks / 72 Queries seit [#800](2026-08-10-chunk-goldset-widening-800.md), ursprünglich 21/71/38), das den Nullbefund aus #729 auflöst: Signal-Split als dominanter Mechanismus belegt, Gewinn- und Schadensrichtung betragsgleich (±0,3691 nDCG@10), Crowding als messbar zu schwach ausgewiesen, Kontrollen bei exakt 0 — Vorbedingungen maschinell geprüft statt zugesichert; Betriebshäufigkeit ausdrücklich offen (#790, Epic #711) |
| [`2026-08-09-chunk-fusion-goldset-790-live-results.json`](2026-08-09-chunk-fusion-goldset-790-live-results.json) | Rohdaten des Probe-Laufs in zwei Blöcken: Probe-Set als Hauptmessung, #708-Set als Regressionsanker (`baseline`) — vom CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft |
| [`2026-08-10-chunk-goldset-widening-800.md`](2026-08-10-chunk-goldset-widening-800.md) | Verbreiterung des #708-Chunk-Goldsets von 26 auf 60 Queries / 11 auf 21 Dokumente bei gleicher Konstruktionsdisziplin: neue Auflösung je Query (0,038 → 0,0167 Recall-Punkte), neu abgeleitete Schwellen, nachgezogene #729/#731-Gatter (#800) |
| [`2026-08-08-context-ablation-710.md`](2026-08-08-context-ablation-710.md) | Vier-Arme-Vergleich auf der bge-m3-Fassung des #708-Goldsets: hilft ein echter, modellgeschriebener Kontextsatz gegenüber dem deterministischen Metadaten-Satz? Sprach-Confound über einen vierten Arm (`model_context_de`) isoliert, Teilmengen getrennt ausgewiesen, `metadata_context`-Arm reproduziert die #731-Zahlen exakt (#785, Epic #710) |
| [`2026-08-08-context-ablation-710-live-results.json`](2026-08-08-context-ablation-710-live-results.json) | Rohdaten des Vier-Arme-Laufs (alle Arme, per Query, inklusive Deltas und Kontrolltest-Block) |
| [`2026-08-09-context-enrichment-710.md`](2026-08-09-context-enrichment-710.md) | Reale Kostenmessung des Kontextsatz-Schreibwegs (#783/#784): der echte `chunk-context-writer`-Agent über `claude -p`, gegen den echten MCP-Server, 11 Goldset-Dokumente plus ein reales Paper mit 27 Chunks — Tokens/Kosten/Latenz aus echten `usage`-Feldern, Re-Embedding-Latenz je Einzeltext, Beobachtung zum Batch-/Turn-Verhalten bei großen Papers (#784, Epic #710) |
| [`2026-08-09-context-enrichment-710-live-results.json`](2026-08-09-context-enrichment-710-live-results.json) | Rohdaten des Kostenlaufs (alle 12 Sitzungen, Tokens/Kosten/Dauer je Paper, Post-Zustand je Chunk, Re-Embedding-Latenzblock) |
| [`2026-08-10-reranker-ablation-804.md`](2026-08-10-reranker-ablation-804.md) | Trägt der aktive `BAAI/bge-reranker-v2-m3`? Echte Produktionsfusion (RRF über `chunk_fts`+Vektor) auf dem #708-Chunk-Goldset, "aus" (RRF-Reihenfolge) gegen "an" (`rerank_score`-Reihenfolge) auf denselben fusionierten Kandidaten, gepaarter Bootstrap, Latenz/Peak-RSS je Bedingung in getrenntem Subprozess — Nullbefund als explizit zulässiges Ergebnis (#804) |
| [`2026-08-10-reranker-ablation-804-live-results.json`](2026-08-10-reranker-ablation-804-live-results.json) | Rohdaten des Ablationslaufs (beide Bedingungen, per Query, inklusive Kosten-Block) — vom CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft |
| [`reranker-candidates-803.md`](reranker-candidates-803.md) | Belegte Reranker-Kandidaten als Alternativen zu `bge-reranker-v2-m3`: Lizenz, Parameterzahl, Downloadgröße, Sprachabdeckung, Eingabeschema und Backbone je Kandidat, `sentence_transformers.CrossEncoder`-Ladbarkeit mit dem gepinnten `transformers==5.14.1` geprüft, `jina-reranker-v2-base-multilingual` an CC-BY-NC-4.0-Lizenz ausgeschlossen (#803) |
| [`2026-08-10-reranker-decision-806.md`](2026-08-10-reranker-decision-806.md) | Entscheidung aus den #804-Zahlen: Reranker per Default abschalten (`DEFAULT_RERANKER_ENABLED = False`), Latenz/Peak-RSS als dauerhafte Kosten gegen den Nullbefund gewichtet, „bleiben" und „wechseln" (#803, keine Messung) verworfen, konkrete Revisionsauslöser inkl. lexikalischer Flanke aus #789 (#806) |
| [`2026-08-10-reranker-default-off-807-verification.md`](2026-08-10-reranker-default-off-807-verification.md) | Nachmessung nach dem Vollzug von #806: Produktivpfad ohne gesetzten Schalter liegt bei Latenz/Peak-RSS auf dem Niveau der #804-„aus"-Bedingung — Beleg statt Zusicherung (#807) |
| [`2026-08-10-reranker-ablation-807-postchange-live-results.json`](2026-08-10-reranker-ablation-807-postchange-live-results.json) | Rohdaten der Nachmessung (beide Bedingungen, per Query, inklusive Kosten-Block) |

## Konvention

- `<datum>-<component>.md` — Report fuer eine einzelne Komponente, geschrieben vor einem Release
- `TEMPLATE.md` — leeres Report-Template zum Kopieren

## Ausfuehrung

```
claude auth login   # einmalig, falls noch keine eingeloggte Session existiert
pytest tests/evals/ -v
```

Reports entstehen manuell auf Basis der pytest-Ausgabe. Kein automatischer
Report-Generator (YAGNI — Reports werden nur ein paar Mal pro Release geschrieben).
