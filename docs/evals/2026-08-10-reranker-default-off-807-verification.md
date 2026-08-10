# Nachmessung: Reranker-Default-Aus im Produktivpfad verifiziert (Issue #807)

> **Historisches Dokument.** Momentaufnahme der Nachmessung vom 2026-08-10,
> unmittelbar nach dem Vollzug von Beschluss #806. Der Sollzustand steht im
> Code (`DEFAULT_RERANKER_ENABLED` in `academic_vault/retrieval.py`) und in
> [`docs/reference/vault.md`](../reference/vault.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-10
**Vorgänger-Issues:** [#806](2026-08-10-reranker-decision-806.md) (Beschluss),
[#804](2026-08-10-reranker-ablation-804.md) (Baseline-Zahlen, VOR dem Vollzug)
**Umsetzung:** #807 (`DEFAULT_RERANKER_ENABLED = False`,
`config/parallel_agents.json`: `"reranker_enabled": false`)
**Rohdaten:** [`2026-08-10-reranker-ablation-807-postchange-live-results.json`](2026-08-10-reranker-ablation-807-postchange-live-results.json)

## Frage

Landet der Produktivpfad (`server.search_papers(rerank=True)`, **ohne** einen
Schalter zu setzen) nach dem Vollzug von #806 tatsächlich bei den
"aus"-Kennzahlen aus #804 — mit Zahlen belegt, nicht nur behauptet?

## Methode

Derselbe Live-Generator wie #804
(`scripts/eval/build_reranker_ablation_804.py --write-live-results`), erneut
gefahren auf demselben Goldset (#708-Chunk-Goldset, 60 Queries) und derselben
Maschine (Apple M4 Pro, CPU). Die Kostenmessung läuft weiterhin in zwei
getrennten Subprozessen (RSS-Isolation); die "aus"-Bedingung setzt dabei
**keinen** Schalter — sie verlässt sich ausschließlich auf den neuen
Code-/Config-Default. (Die "an"-Bedingung und der Qualitäts-Fixture-Teil
setzen `ACADEMIC_RESEARCH_RERANKER_ENABLED=1` explizit, weil sie den
Reranker-Beitrag unabhängig vom jeweils aktuellen Produktivdefault messen
sollen — Anpassung an `_CloudKeyGuard`/`run_cost_condition` im selben PR.)

## Ergebnis: Produktivpfad landet auf "aus"-Niveau

| Bedingung | Suchlatenz p50 | Suchlatenz p95 | Peak-RSS |
|---|---|---|---|
| #804 "aus" (Schalter explizit gesetzt, VOR #807) | 17,2 ms | 35,2 ms | 74,3 MB |
| #807 Produktivpfad (kein Schalter gesetzt, NACH #807) | 7,3 ms | 9,4 ms | 71,2 MB |
| Referenz #804 "an" (Reranker aktiv) | 3057,5 ms | 3542,7 ms | 900,7 MB |

Die Nachmessung liegt im selben Größenbereich wie die #804-"aus"-Zahlen
(niedriger, im Rahmen normaler Lauf-zu-Lauf-Varianz auf derselben Maschine —
kein Modell wird geladen, die absoluten Millisekunden hängen an
Systemauslastung) und weit unterhalb der "an"-Bedingung. Der Qualitäts-Teil
desselben Laufs bestätigt zusätzlich den bereits aus #804 bekannten
Nullbefund (kein 95-%-Intervall schließt die Null aus) — erwartungsgemäß
unverändert, da an der Reranker-Logik selbst nichts geändert wurde.

**Beleg:** Eine Suche ohne gesetzten Schalter lädt kein Reranker-Modell und
liegt bei Latenz/Peak-RSS auf dem Niveau der "aus"-Bedingung aus #804 — der
Beschluss aus #806 ist im Produktivpfad angekommen.
