# Reranker-Entscheidung: per Default abschalten (Issue #806)

> **Historisches Dokument.** Momentaufnahme der Entscheidung vom 2026-08-10 auf
> Basis der zu diesem Zeitpunkt vorliegenden Zahlen. Der Sollzustand — ob der
> Reranker produktiv aktiv ist — steht im Code (`DEFAULT_RERANKER_ENABLED`)
> und in [`docs/reference/vault.md`](../reference/vault.md).

[← Doku-Übersicht](../README.md)

**Datum:** 2026-08-10
**Vorgänger-Issues:** [#804](2026-08-10-reranker-ablation-804.md) (Signifikanzlauf,
**die Datenbasis dieser Entscheidung**), [#803](reranker-candidates-803.md)
(Kandidatenrecherche, keine Messung), [#789](../../tests/test_issue_789_fts_diagnosis.py)
(FTS-Trefferdiagnose auf dem #708-Goldset)
**Umgesetzt in:** #807 (Code-Schalter `DEFAULT_RERANKER_ENABLED`, nicht Teil
dieses Issues)

## Die Entscheidung

**Reranker per Default abschalten.** `DEFAULT_RERANKER_ENABLED` wird auf
`False` gesetzt. Der lokale Reranker `BAAI/bge-reranker-v2-m3` bleibt
vollständig funktionsfähig und über `ACADEMIC_RESEARCH_RERANKER_ENABLED` bzw.
den Config-Schlüssel `reranker_enabled` einschaltbar — er wird nur nicht mehr
ungefragt bei jeder Suche geladen.

Begründet ausschließlich aus den gemessenen Zahlen aus
[#804](2026-08-10-reranker-ablation-804.md) (60 Queries, gepaarter Bootstrap,
10 000 Resamples), nicht aus Modellgröße oder Literatur.

## Grundlage: Qualität und Kosten in einer Tabelle

Zahlen aus #804, Suchpfad `server.search_papers(rerank=True)`, 60 Queries,
`k = 10`, Apple M4 Pro, CPU. Qualitätsmetriken und Suchlatenz/Peak-RSS stehen
absichtlich gleichrangig in derselben Tabelle: die Latenz ist keine Fußnote,
sondern fällt **bei jeder einzelnen Suchanfrage an, dauerhaft** — anders als
ein einmaliger Migrationsaufwand (Muster aus #732: Indexierungszeit als
dauerhafte Steuer gegen einmalige Migration; hier ist das Äquivalent die
Suchlatenz je Anfrage gegen einen einmaligen Umsetzungsaufwand).

| Bedingung | Recall@10 | nDCG@10 | MRR | Suchlatenz p50 | Suchlatenz p95 | Peak-RSS |
|---|---|---|---|---|---|---|
| `aus` (RRF-Reihenfolge, Betriebszustand seit #729) | 0,8167 | 0,7097 | 0,6764 | 17,2 ms | 35,2 ms | 74,3 MB |
| `an` (nach `rerank_score` sortiert) | 0,7917 | 0,7190 | 0,6970 | 3057,5 ms | 3542,7 ms | 900,7 MB |

Gepaarter Bootstrap, Delta = `an` minus `aus`:

| Metrik | Delta (an − aus) | 95-%-CI | trägt? |
|---|---:|---|---|
| Recall@10 | −0,0250 | [−0,1000; 0,0500] | nein |
| nDCG@10 | +0,0093 | [−0,0452; 0,0704] | nein |
| MRR | +0,0206 | [−0,0400; 0,0872] | nein |

Kosten je Suche, dauerhaft: **3058 ms statt 17 ms** Suchlatenz (p50),
**901 MB statt 74 MB** Peak-RSS. Kein einziger der drei
Qualitätsabstände schließt die Null aus — der Reranker kauft die 180-fache
Latenz und das 12-fache Peak-RSS gegen einen Qualitätseffekt, der sich vom
Rauschen nicht trennen lässt.

## Verworfen: bleiben

„Bleiben" heißt: der Reranker bleibt per Default aktiv, wie er es seit
Einführung war (der Zustand `an` in der Tabelle oben ist exakt dieser
Status quo). Verworfen, weil genau dieser Zustand der gemessene ist und
keinen belegten Zusatznutzen zeigt: keine der drei Metriken trägt gegen
`aus`, während die Kosten (3 s zusätzliche Latenz, 826 MB zusätzliches
Peak-RSS je Suche) real und unbestritten sind. Eine per Default aktive
Komponente ohne nachweisbaren Gegenwert bei jeder Suche zu belassen, ist
keine neutrale Wahl — sie ist eine implizite Entscheidung für die Kosten
ohne die Gegenleistung.

## Verworfen: wechseln

#803 hat drei Reranker-Kandidaten identifiziert, die die Lizenzprüfung
bestehen und mit vollständig belegten technischen Feldern geführt werden
(`mxbai-rerank-large-v2`, `gte-multilingual-reranker-base`,
`bge-reranker-v2-gemma`, letzterer mit ungeklärter
`CrossEncoder`-Ladbarkeit). #803 liefert dazu **ausdrücklich keine
Messung** — das Issue selbst benennt das als Aufgabe eines Folge-Issues.

Das ist selbst der Grund, warum „wechseln" hier nicht auf gemessenen
Zahlen basieren kann: ohne einen Lauf dieser Kandidaten gegen das
#708-Goldset gibt es keine Datenbasis, aus der sich eine Entscheidung für
oder gegen einen Wechsel ziehen ließe. „Wechseln" scheidet damit nicht aus,
weil ein Kandidat schlechter gemessen wurde, sondern weil **keine Messung
vorliegt** — eine Empfehlung für einen ungemessenen Kandidaten wäre eine
Entscheidung aus Modellgröße oder Literatur, genau das, was AC1 dieses
Issues ausschließt.

## Warum nicht einfach genauer messen

Eine Fallzahlrechnung auf den Per-Query-Deltas der #804-Rohdaten ergibt rund
**1100 Queries** (Recall/MRR) bzw. **4500–4800 Queries** (nDCG) für einen
belastbaren Nachweis — das 18- bis 80-fache des heutigen Goldsets, mit
geschätzt ~300 handgeschriebenen Quelldokumenten und über 2000 zusätzlichen
CLI-Aufrufen für die abhängigen Fixtures (#733, #710, #804).

Zwei Befunde wiegen schwerer als die Fallzahl selbst:

1. **Die Rechnung gilt nicht einmal.** Die #800-Konstruktionsregel verlangt,
   dass der Korpus mit den Queries mitwächst. Bei 1100 Queries hätte er
   ~1100 Chunks statt 61 — Recall@10 auf einem 18-mal größeren Korpus ist
   eine andere Aufgabe, die heutigen Deltas übertragen sich nicht.
2. **Der Effekt ist teilmengen-heterogen.** Der Reranker hilft
   `cross-language` (Recall 0,2 → 0,4), schadet aber `language-gap` deutlich
   (Recall 0,50 → 0,32, MRR 0,199 → 0,084). Ein größeres Set desselben
   Zuschnitts vermisst nur den Durchschnitt zweier gegenläufiger Effekte
   präziser um die Null herum — bei Recall@10 würde es am ehesten zuerst
   belegen, dass der Reranker **schadet**.

Und selbst im günstigsten Fall stünde am Ende: „+0,02 MRR, gesichert, für
3 Sekunden und 826 MB je Suche". Das trägt „Default an" genauso wenig wie
der heutige Nullbefund. Die Frage ist eine Kosten-Nutzen-Entscheidung, keine
Schätzgenauigkeitsfrage.

## Offene lexikalische Flanke (#789)

`tests/test_issue_789_fts_diagnosis.py::test_708_goldset_lexical_side_is_structurally_dead`
belegt: **1 von 60** Queries erzielt einen `papers_fts`-Treffer, **0 von 60**
einen `papers_trgm`-Treffer. Der Reranker bekommt auf diesem Goldset fast
ausschließlich vektorielle Kandidaten, die bereits semantisch sortiert sind —
er tauscht eine semantische Rangfolge gegen eine andere. Das ist genau die
Konfiguration, in der ein Cross-Encoder am wenigsten beitragen *kann*.

**Ob der Reranker auf einem lexikalisch lebendigen Korpus hilft, ist damit
nicht beantwortet.** Diese Flanke ist bewusst offen gelassen statt
geschlossen und ist der erste konkrete Auslöser im Abschnitt unten.

## Konsequenz für den Produktivpfad

`DEFAULT_RERANKER_ENABLED = False`. `ACADEMIC_RESEARCH_RERANKER_ENABLED`
(Env-Var) und der Config-Schlüssel `reranker_enabled` bleiben als
Einschalt-Weg vollständig erhalten — der lokale `BAAI/bge-reranker-v2-m3`
wird nicht entfernt, nur nicht mehr per Default geladen. Die Umsetzung
dieses Schalters im Code ist [#807](https://github.com/ahlerjam/academic-research/issues/807)
und explizit nicht Teil dieses Issues.

## Wann diese Entscheidung erneut zu prüfen ist

Nicht ohne neue Daten, aber konkret:

- **Ein lexikalisch lebendiger Korpus wird verfügbar.** Konkreter Weg: ein
  kompaktes Zusatz-Goldset von 20–30 bewusst stichwortlastigen Queries
  (Fachtermini, Eigennamen, Abkürzungen statt ausgeschriebener Sätze), das
  gemischte Kandidatenlisten (FTS + Vektor, nicht nur Vektor) in die Fusion
  bringt — dann lässt sich der Reranker in genau der Konfiguration messen,
  für die er entworfen ist, statt in der #789-Konfiguration, in der die
  lexikalische Seite strukturell tot ist.
- **Ein neues Reranker-Modell mit belegter Messung** gegen das #708-Goldset
  (einer der #803-Kandidaten oder ein neuer) zeigt einen Qualitätsabstand,
  dessen 95-%-Bootstrap-Intervall die Null ausschließt, bei vertretbarer
  Latenz — dann ist die Kosten-Nutzen-Abwägung neu zu führen, nicht nur für
  `bge-reranker-v2-m3`.
- **GPU wird zur angenommenen Zielhardware.** Diese Entscheidung gewichtet
  die CPU-Suchlatenz explizit hoch (3058 ms p50 auf Apple M4 Pro, CPU). Auf
  GPU-Zielhardware fiele dieser Kostenposten voraussichtlich deutlich
  kleiner aus — dann wäre die Abwägung zwischen Latenz und dem (weiterhin zu
  belegenden) Qualitätsgewinn neu zu führen.
- **Ein größeres Goldset** löst die Auflösungsgrenze aus #804 auf (die
  Fallzahlrechnung oben nennt die Größenordnung) — dann ließe sich der
  heutige Nullbefund entweder erhärten oder auflösen, ohne dass dafür ein
  eigenes Issue die Fallzahl neu herleiten muss.

Ohne eines dieser Signale bleibt die Frage geschlossen — das ist der Zweck
dieses Vermerks.
