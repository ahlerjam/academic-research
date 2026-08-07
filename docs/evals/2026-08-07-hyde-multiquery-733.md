# HyDE und Multi-Query prototypisch gemessen (#733)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md); die
> Rohdaten dieses Laufs liegen daneben in
> [`2026-08-07-hyde-multiquery-733-live-results.json`](2026-08-07-hyde-multiquery-733-live-results.json)
> und werden im CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft.

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-07 · **Goldset:** [#708](retrieval-chunk-goldset-708.md), 30 Chunks,
26 Queries, unverändert · **Embedding:** `intfloat/multilingual-e5-small` (384d) ·
**Umformung:** `claude -p --model sonnet`, eingeloggte OAuth-Sitzung, kein API-Schlüssel

Gemessen wird eine Frage, die die Literatur für andere Korpora und andere
Sprachen beantwortet: Schließt HyDE oder Multi-Query-Expansion die Lücke
zwischen einer umgangssprachlichen deutschen Frage („woran merke ich, dass
jemand nachts von Hand am laufenden Rechner etwas umgestellt hat") und dem
englischen Fachtext, der sie beantwortet („configuration drift … declared state
versus observed state")?

Beide Verfahren liegen als Prototyp unter `scripts/eval/` und laufen über
denselben Suchpfad wie #708: die Vektoren gehen über
`VaultDB.add_chunk_embedding()` in eine Wegwerf-DB und werden mit
`VaultDB.knn_chunks(k=10)` gerankt. Der `baseline`-Arm reproduziert die
#708-Zahlen exakt (`test_baseline_arm_reproduces_708_numbers`, Toleranz 1e-9) —
ohne diese Kontrolle wäre jeder gemessene Gewinn womöglich nur ein anderer
Suchpfad.

## Die vier Arme

| Arm | Was eingebettet und gesucht wird |
|---|---|
| `baseline` | die unveränderte Query mit `query: `-Präfix — Kontrolle gegen #708 |
| `hyde_query_prefix` | eine hypothetische englische Antwortpassage, eingebettet mit `query: ` |
| `hyde_passage_prefix` | dieselbe Passage, eingebettet mit `passage: ` |
| `multi_query` | Original + drei Umformulierungen, je eigene Suche, Ranglisten per RRF (k=60) fusioniert |

HyDE wird mit **beiden** e5-Präfixen ausgewiesen: für e5 ist nicht dokumentiert,
welches Präfix einer hypothetischen Antwortpassage gebührt. Die Wahl
vorwegzunehmen hieße, womöglich nur eine falsche Präfixwahl zu messen — die
beiden Varianten trennen hier 0,0418 nDCG@10 im Gesamtmittel.

## Gesamtergebnis

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `baseline` | 0,7692 | **0,6651** | **0,6314** |
| `hyde_query_prefix` | 0,7692 | **0,5696** | **0,5135** |
| `hyde_passage_prefix` | 0,7500 | **0,6088** | **0,5702** |
| `multi_query` | **0,9615** | **0,6583** | **0,5648** |

Deltas gegen die Baseline, mit Vorzeichen:

| Arm | Δ Recall@10 | Δ nDCG@10 | Δ MRR |
|---|---:|---:|---:|
| `hyde_query_prefix` | +0,0000 | -0,0955 | -0,1179 |
| `hyde_passage_prefix` | -0,0192 | -0,0563 | -0,0612 |
| `multi_query` | +0,1923 | -0,0068 | -0,0666 |

**Im Gesamtmittel verschlechtert jedes der beiden Verfahren nDCG@10 und MRR.**
Das ist ein gültiges Ergebnis und wird hier nicht weggemittelt. Es ist aber
nicht das ganze Ergebnis — der Gesamtwert mischt drei Fälle, die sich
gegenläufig verhalten, und 18 der 26 Queries gehören zum Fall, den die Baseline
ohnehin fast perfekt löst.

## Sprachlücke: deutsche Umgangssprache auf englischen Fachtext

Sechs Queries, `case == "language-gap"`. Getrennt aggregiert, nicht aus dem
Gesamtmittel abgeleitet (`test_language_gap_subset_reported_per_arm` rechnet die
Teilmenge aus den Per-Query-Zeilen nach).

| Arm | Recall@10 | nDCG@10 | MRR | Δ nDCG@10 | Δ MRR |
|---|---:|---:|---:|---:|---:|
| `baseline` | 0,3333 | **0,1311** | **0,0694** | — | — |
| `hyde_query_prefix` | 1,0000 | **0,7718** | **0,6944** | +0,6407 | +0,6250 |
| `hyde_passage_prefix` | 1,0000 | **0,7936** | **0,7222** | +0,6625 | +0,6528 |
| `multi_query` | 1,0000 | **0,3927** | **0,2129** | +0,2615 | +0,1435 |

Alle drei Umform-Arme finden das Ziel in **allen sechs** Fällen in den Top-10;
die Baseline findet es in zwei. Der Unterschied liegt im Rang. Erster Treffer je
Query:

| Query | `baseline` | `hyde_passage_prefix` | `multi_query` |
|---|---:|---:|---:|
| q-gap-01 | nicht in Top-10 | 1 | 7 |
| q-gap-02 | nicht in Top-10 | 2 | 7 |
| q-gap-03 | 4 | 1 | 2 |
| q-gap-04 | nicht in Top-10 | 2 | 8 |
| q-gap-05 | nicht in Top-10 | 1 | 6 |
| q-gap-06 | 6 | 3 | 5 |

HyDE setzt den Treffer auf Rang 1 bis 3, Multi-Query auf Rang 2 bis 8. Der Grund
ist die Fusion selbst: eine der vier fusionierten Ranglisten stammt von der
unveränderten Query, und die rankt in diesem Fall nachweislich schlecht. RRF
mittelt den guten Treffer der englischen Umformulierung mit dem schlechten
Ergebnis des Originals — das rettet den Recall und kostet den Rang.

## Die anderen beiden Fälle

| Teilmenge | Queries | Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---|---:|---:|---:|
| `same-language` | 18 | `baseline` | 1,0000 | 0,9170 | 0,8889 |
| | | `hyde_query_prefix` | 0,7778 | 0,5655 | 0,5102 |
| | | `hyde_passage_prefix` | 0,7500 | 0,6149 | 0,5829 |
| | | `multi_query` | 1,0000 | 0,7961 | 0,7310 |
| `cross-language` | 2 | `baseline` | 0,0000 | 0,0000 | 0,0000 |
| | | `hyde_query_prefix` | 0,0000 | 0,0000 | 0,0000 |
| | | `hyde_passage_prefix` | 0,0000 | 0,0000 | 0,0000 |
| | | `multi_query` | 0,5000 | 0,2153 | 0,1250 |

Hier liegt der Preis von HyDE: **Recall@10 fällt bei 18 von 26 Queries von 1,0
auf 0,75.** In vier bis fünf Fällen findet der Lauf den Zielchunk überhaupt nicht
mehr. Der Prompt schreibt die hypothetische Passage auf Englisch — für die
deutschen `same-language`-Queries wandert die Suche damit in den englischen
Sprachraum und findet dort einen plausiblen, aber falschen Text. Genau die
Asymmetrie, die #708 gemessen hat (der Sprachraum dominiert die Ähnlichkeit
stärker als das Thema), wirkt hier gegen das Verfahren.

`cross-language` (englische Frage auf deutschen Text) bewegt sich bei HyDE
nicht — die englische Passage bleibt englisch. Multi-Query erreicht dort als
einziger Arm überhaupt einen Treffer, weil eine seiner drei Umformulierungen
verpflichtend deutsch ist. Zwei Queries sind allerdings keine Stichprobe,
sondern eine Beobachtung.

## Latenz je Verfahren

Drei Posten aus drei verschiedenen Quellen — was wie gemessen wurde, steht in
`tests/fixtures/hyde_multiquery_733/transforms.json` unter `meta` in Klartext.
Werte je Query, Mediane:

| Arm | Umformung | Embedding | Suche | Summe |
|---|---:|---:|---:|---:|
| `baseline` | 0 ms | 16,9 ms | 1,7 ms | ≈ 19 ms |
| `hyde_*` | 8022,8 ms | 16,9 ms | 1,6 ms | ≈ 8041 ms |
| `multi_query` | 6762,0 ms | 67,0 ms | 6,5 ms | ≈ 6835 ms |

- **Umformung** — Wanduhrzeit von 26 echten `claude -p`-Aufrufen je Verfahren
  (p50/p95: HyDE 8022,8 / 11727,3 ms, Multi-Query 6762,0 / 7906,1 ms). Das ist
  eine **obere Schranke**: der CLI-Aufruf bezahlt Prozess- und Sitzungsaufbau,
  den eine Umformung innerhalb einer laufenden Sitzung nicht bezahlt. Der Posten
  ist hermetisch nicht messbar, weil der Messlauf selbst kein Modell aufruft.
- **Embedding** — Anzahl der Embeddings des Arms mal dem Median einer echten
  e5-Einbettung aus dem Generatorlauf (16,9 ms bei 129 Messungen). Der
  Playback-Embedder des Messlaufs ist ein Dict-Zugriff; seine Zeit als
  Embedding-Latenz auszugeben, wäre eine erfundene Zahl.
- **Suche** — in diesem Lauf gemessen, über den echten `knn_chunks`-Pfad.
  Multi-Query sucht viermal statt einmal.

Beide Verfahren kosten also **drei Größenordnungen** mehr als die Baseline, und
der Posten, der das verursacht, ist in beiden Fällen der Modellaufruf. Die
Embedding- und Suchkosten von Multi-Query (zusammen 73 ms gegen 19 ms) fallen
daneben nicht ins Gewicht.

## Entscheidungsregel

Vorab festgelegt, damit die Empfehlung nicht der Vorliebe folgt:

1. **Ausschluss:** Ein Verfahren, das in irgendeiner Teilmenge Recall@10 gegen
   die Baseline verliert, wird nicht empfohlen. Ein nicht gefundener Treffer ist
   im Betrieb nicht durch besseres Ranking heilbar; ein schlechter Rang innerhalb
   der Top-10 ist es.
2. **Auswahl:** Unter den verbleibenden gewinnt das Verfahren mit dem größten
   Zugewinn bei `language-gap` nDCG@10 — das ist die Lücke, deretwegen dieses
   Issue existiert.
3. Bleibt keines übrig, lautet die Empfehlung „keines".

`test_recommendation_matches_measured_deltas` rechnet diese Regel aus den
eingecheckten Rohdaten nach; eine Empfehlung, die den Zahlen widerspricht, macht
den Test rot.

## Empfehlung

**Multi-Query**

HyDE scheidet nach Regel 1 aus: beide Präfixvarianten verlieren `same-language`
Recall@10 (1,0000 → 0,7778 bzw. 0,7500), und das betrifft 18 der 26 Queries.
Multi-Query verliert in keiner Teilmenge Recall und gewinnt in zweien:
`language-gap` 0,3333 → 1,0000, `cross-language` 0,0000 → 0,5000.

Der Zugewinn bei der Sprachlücke beträgt **+0,2615 nDCG@10** (0,1311 → 0,3927)
und **+0,1435 MRR** (0,0694 → 0,2129), bei einem Gesamtmittel, das um -0,0068
nDCG@10 praktisch unverändert bleibt und um -0,0666 MRR nachgibt. Der MRR-Verlust
ist real und stammt aus `same-language`, wo die Fusion den bereits perfekten
ersten Rang gelegentlich verschiebt.

Diese Empfehlung ist ausdrücklich **kein** Freibrief für die produktive
Anbindung. Sie sagt: von den beiden geprüften Verfahren ist Multi-Query das
einzige, dessen Nachteil ein Rangnachteil und kein Trefferverlust ist. Wer die
Sprachlücke wirklich schließen will, findet in HyDE das stärkere Werkzeug
(+0,6625 nDCG@10) und müsste dessen Preis anders bezahlen als hier gemessen —
etwa mit einer sprachbedingten Fallunterscheidung oder einer Passage in der
Sprache der Anfrage. Beides ist in diesem Issue nicht gemessen und deshalb hier
auch keine Empfehlung.

## Aufbau des Laufs

```
scripts/eval/query_expansion_prototypes.py     Prompts, Prompt-IDs, fuse_rankings() (RRF)
scripts/eval/build_hyde_multiquery_fixture.py  Live-Generator (zwei Stufen, beide opt-in)
scripts/eval/run_hyde_multiquery_eval.py       hermetischer Messlauf, vier Arme
tests/fixtures/hyde_multiquery_733/
├── transforms.json   26 Umformungen: HyDE-Passage + 3 Varianten je Query, Latenz, Manifest
└── vectors.json      129 base64-kodierte float32-Vektoren (384d)
```

**Umformungen erzeugen** (dauert rund zehn Minuten, 52 CLI-Aufrufe):

```bash
VAULT_HYDE_LIVE_TRANSFORM=1 uv run python \
    scripts/eval/build_hyde_multiquery_fixture.py --stage transforms
VAULT_E5_LIVE_TEST=1 uv run python \
    scripts/eval/build_hyde_multiquery_fixture.py --stage vectors
```

Die erste Stufe schreibt jede fertige Query sofort in einen Cache neben der
Ausgabedatei; ein Abbruch mitten im Lauf kostet deshalb nicht die schon bezahlten
Aufrufe. Die zweite Stufe embeddet alle Umformtexte, misst die Embedding-Latenz
und schreibt `manifest_sha256` über alle Texte, Modell-ID und Dimension. Wird ein
Text später editiert, ohne die Vektoren neu zu rechnen, bricht der Messlauf mit
Exit 2 ab, statt eine still verschobene Metrik zu melden.

**Messlauf** (hermetisch, kein Netz, kein Modell):

```bash
uv run python scripts/eval/run_hyde_multiquery_eval.py
uv run python scripts/eval/run_hyde_multiquery_eval.py \
    --check-against docs/evals/2026-08-07-hyde-multiquery-733-live-results.json
```

## Grenzen

- **Die Stichprobe ist klein.** `language-gap` hat sechs Queries, eine einzige
  verschiebt Recall@10 um 0,1667; `cross-language` hat zwei. Die eigentliche
  Evidenz sind deshalb die Per-Query-Tabellen und die Rohdaten, nicht der
  Mittelwert. Die Richtung des HyDE-Effekts (sechs von sechs Treffern statt zwei,
  Ränge 1 bis 3) ist deutlich genug, um die Streuung zu überstehen; der
  MRR-Unterschied zwischen den beiden HyDE-Präfixen (0,6944 gegen 0,7222) ist es
  nicht.
- **Gemessen wird eine eingefrorene Stichprobe von Umformungen, keine
  Verteilung.** Jede Query hat genau eine HyDE-Passage und drei Varianten, aus
  einem Lauf. Ein zweiter Lauf desselben Prompts liefert andere Texte und damit
  andere Zahlen; wie groß diese Streuung ist, ist hier nicht gemessen.
- **Der HyDE-Prompt legt die Sprache fest.** Er verlangt eine englische Passage.
  Das ist eine Designentscheidung, kein Naturgesetz — und sie erklärt den
  `same-language`-Verlust vollständig. Ein Prompt, der die Sprache der Anfrage
  übernimmt, wäre ein anderes Verfahren mit anderen Zahlen, und er stünde dann
  bei der Sprachlücke schlechter da.
- **Die beiden Verfahren bekommen ungleich viele Freiheitsgrade.** HyDE erzeugt
  einen Text und muss sich für eine Sprache entscheiden; Multi-Query erzeugt drei
  und deckt zwei Sprachen plus eine Präzisierung ab. Diese Asymmetrie steckt in
  der Natur der Verfahren, verschiebt aber den Vergleich zugunsten von
  Multi-Query.
- **Leckage ist ausgeschlossen, nicht nur zugesichert.** Das Modell sah beim
  Umformen ausschließlich den Query-Text. `test_transforms_carry_no_goldset_leakage`
  prüft, dass kein Anker des Goldsets wörtlich in einer Umformung steht.
- **Die Latenz der Umformung ist eine obere Schranke** (siehe oben) und stammt
  von einer einzelnen Maschine. Sie taugt zum Größenordnungsvergleich, nicht als
  Betriebskennzahl.
- **Das Ergebnis entscheidet nichts über die produktive Anbindung.** Die folgt
  laut Issue im Nachfolge-Issue und nur für das Verfahren, das gewinnt. Weder
  `academic_vault/**` noch `commands/search.md` sind in diesem Lauf angefasst
  worden.
