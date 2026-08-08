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
| [`embedding-truncatability-730.md`](embedding-truncatability-730.md) | Belegte Truncatierbarkeit der drei #628-Kandidaten auf 384d je Modellkarte — nur Qwen3-Embedding-0.6B ohne Schema-Migration einsetzbar, BGE-M3/e5-large „nicht belegt" (#730) |
| [`2026-08-06-extended-nli-goldset-721.md`](2026-08-06-extended-nli-goldset-721.md) | Momentaufnahme: erweitertes NLI-Goldset (186 Fälle, 30 echte Paper, acht Fächer) ins Repo aufgenommen, Reproduktion der #720-Schwellenkurve (#721) |
| [`retrieval-chunk-goldset-708.md`](retrieval-chunk-goldset-708.md) | Chunk-Goldset (30 Chunks, 26 Queries) mit Recall@10/nDCG@10/MRR, hermetisch in CI dank eingecheckter Vektoren — inkl. gemessener Sprachlücke DE→EN (#708) |
| [`2026-08-07-hyde-multiquery-733.md`](2026-08-07-hyde-multiquery-733.md) | HyDE und Multi-Query prototypisch gegen das Chunk-Goldset aus #708 gemessen: nDCG@10/MRR je Arm, Sprachlücke getrennt ausgewiesen, Latenz je Verfahren, Empfehlung aus den Zahlen (#733) |
| [`2026-08-07-hyde-multiquery-733-live-results.json`](2026-08-07-hyde-multiquery-733-live-results.json) | Rohdaten des Messlaufs (alle vier Arme, per Query, inklusive Deltas und Latenzblock) — vom CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft |
| [`2026-08-07-bge-m3-nli-scorer-720.md`](2026-08-07-bge-m3-nli-scorer-720.md) | Momentaufnahme: NLI-Scorer-Wechsel auf `bge-m3-zeroshot-v2.0` @ Schwelle 0,95, A/B über 278 Fälle, `condition-stripped`-Grenze, zwei verworfene Zusatzansätze (#720) |
| [`retrieval-ablation-722.md`](retrieval-ablation-722.md) | Ablation der vier Retrieval-Änderungen #701/#702/#703/#714 gegen die volle Hybrid-Pipeline (FTS5+Vektor+RRF+Reranker), Paper-Ebene-Aggregation aus #708, Leave-one-out je Änderung, aufgedeckter FTS5-Sanitize-Defekt außerhalb des Scopes (#722) |
| [`retrieval-ablation-722-live-results.json`](retrieval-ablation-722-live-results.json) | Rohdaten des Ablationslaufs (alle 6 Kombinationen, per Query, inklusive `fts5_syntax_errors`) |
| [`2026-08-08-embedding-candidates-731.md`](2026-08-08-embedding-candidates-731.md) | Fünf Embedding-Kandidaten auf dem Chunk-Goldset aus #708 gemessen: nDCG@10/MRR/Recall@10, CPU-Indexierungszeit und Download-Größe gleichrangig, Preis der Schema-Migration je Kandidat, gepaarter Bootstrap samt Auflösungsgrenze (#731) |
| [`2026-08-08-embedding-candidates-731-live-results.json`](2026-08-08-embedding-candidates-731-live-results.json) | Rohdaten des Kandidatenlaufs (alle fünf Kandidaten, per Query, inklusive Zeit-, Hardware- und Signifikanzblock) — vom CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft |
| [`2026-08-08-embedding-model-decision-732.md`](2026-08-08-embedding-model-decision-732.md) | Entscheidung auf Basis der #731-Zahlen: Wechsel auf `BAAI/bge-m3` (1024d) statt `qwen3-384` (migrationsfrei, aber ~80x CPU-Indexierungszeit) oder „bleiben" bei `e5-small`, Hardwarekosten auf GPU-losem Laptop explizit gewichtet, Migrationsprobe mit dem echten Modell (#732) |

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
