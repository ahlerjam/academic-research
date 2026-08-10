# HyDE und Multi-Query prototypisch gemessen (#733)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md); die
> Rohdaten dieses Laufs liegen daneben in
> [`2026-08-07-hyde-multiquery-733-live-results.json`](2026-08-07-hyde-multiquery-733-live-results.json)
> und werden im CI-Job `retrieval-goldset` gegen einen frischen Lauf geprüft.
>
> **Datenstand 2026-08-10 (#800).** Das #708-Goldset wurde von 26 auf 60
> Queries (30 auf 61 Chunks) verbreitert; die HyDE-/Multi-Query-Fixture wurde
> daraufhin komplett neu erzeugt (120 echte `claude`-CLI-Aufrufe, 300
> Vektoren). Der Report unten beschreibt durchgehend diesen neuen Lauf auf 60
> Queries — der ursprüngliche 26-Query-Lauf vom 2026-08-07 ist nicht mehr
> Gegenstand dieses Dokuments; seine Zahlen sind vollständig ersetzt, nicht
> nur ergänzt.

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-10 · Fixture neu erzeugt für [#800](2026-08-10-chunk-goldset-widening-800.md)
(ursprünglicher Lauf 2026-08-07 auf dem 26er-Goldset) · **Goldset:**
[#708](retrieval-chunk-goldset-708.md), verbreitert durch #800, 61 Chunks,
60 Queries · **Embedding:** `intfloat/multilingual-e5-small` (384d) ·
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
aktuellen #708-Zahlen exakt (`test_baseline_arm_reproduces_708_numbers`,
Toleranz 1e-9) — ohne diese Kontrolle wäre jeder gemessene Gewinn womöglich
nur ein anderer Suchpfad. **Zweite Kontrolle:** Der `baseline`-Arm liefert
0,8167 / 0,7097 / 0,6764 (Recall@10 / nDCG@10 / MRR) und reproduziert damit
exakt die `e5-small`-Zahlen des #731-Kandidatenlaufs auf demselben, durch
#800 verbreiterten Goldset — es wird dieselbe Strecke gemessen wie dort.

## Die vier Arme

| Arm | Was eingebettet und gesucht wird |
|---|---|
| `baseline` | die unveränderte Query mit `query: `-Präfix — Kontrolle gegen #708/#731 |
| `hyde_query_prefix` | eine hypothetische englische Antwortpassage, eingebettet mit `query: ` |
| `hyde_passage_prefix` | dieselbe Passage, eingebettet mit `passage: ` |
| `multi_query` | Original + drei Umformulierungen, je eigene Suche, Ranglisten per RRF (k=60) fusioniert |

HyDE wird mit **beiden** e5-Präfixen ausgewiesen: für e5 ist nicht dokumentiert,
welches Präfix einer hypothetischen Antwortpassage gebührt. Die Wahl
vorwegzunehmen hieße, womöglich nur eine falsche Präfixwahl zu messen — die
beiden Varianten trennen hier 0,0409 nDCG@10 im Gesamtmittel.

## Gesamtergebnis

| Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| `baseline` | 0,8167 | **0,7097** | **0,6764** |
| `hyde_query_prefix` | 0,7333 | **0,5695** | **0,5231** |
| `hyde_passage_prefix` | 0,7667 | **0,6104** | **0,5678** |
| `multi_query` | **0,8833** | **0,7329** | **0,6968** |

Deltas gegen die Baseline, mit Vorzeichen:

| Arm | Δ Recall@10 | Δ nDCG@10 | Δ MRR |
|---|---:|---:|---:|
| `hyde_query_prefix` | -0,0833 | -0,1402 | -0,1533 |
| `hyde_passage_prefix` | -0,0500 | -0,0994 | -0,1085 |
| `multi_query` | +0,0667 | +0,0232 | +0,0204 |

**Im Gesamtmittel verschlechtert HyDE in beiden Präfixvarianten nDCG@10 und
MRR spürbar** (-0,1402/-0,1533 bzw. -0,0994/-0,1085). **Multi-Query dreht auf
dem breiteren Goldset dagegen das Vorzeichen:** nDCG@10 und MRR liegen jetzt
leicht über der Baseline (+0,0232 bzw. +0,0204), während sie im
ursprünglichen 26-Query-Lauf noch knapp darunter lagen (0,6583 gegen 0,6651
nDCG@10). Der Abstand ist klein — er liegt nur knapp über der Rauschmarge von
0,02, die #708 für sein eigenes CI-Gate ansetzt, und dieser Lauf rechnet
anders als der Kandidatenvergleich in #731 kein Konfidenzintervall. Das ist
kein Nachweis, sondern ein Befund an der Nachweisgrenze.

Der Gesamtwert mischt außerdem drei Fälle, die sich gegenläufig verhalten:
41 der 60 Queries gehören zum Fall `same-language`, den die Baseline ohnehin
fast perfekt löst (nDCG@10 0,9212).

## Sprachlücke: deutsche Umgangssprache auf englischen Fachtext

14 Queries, `case == "language-gap"` — im ursprünglichen 26-Query-Goldset
waren es sechs; #800 hat diese Teilmenge gezielt verbreitert, damit sich eine
Richtung von der Streuung trennen lässt. Getrennt aggregiert, nicht aus dem
Gesamtmittel abgeleitet (`test_language_gap_subset_reported_per_arm` rechnet
die Teilmenge aus den Per-Query-Zeilen nach).

| Arm | Recall@10 | nDCG@10 | MRR | Δ nDCG@10 | Δ MRR |
|---|---:|---:|---:|---:|---:|
| `baseline` | 0,5000 | **0,2725** | **0,1994** | — | — |
| `hyde_query_prefix` | 0,8571 | **0,6763** | **0,6250** | +0,4038 | +0,4256 |
| `hyde_passage_prefix` | **1,0000** | **0,7337** | **0,6579** | +0,4612 | +0,4585 |
| `multi_query` | 0,7857 | **0,5727** | **0,5197** | +0,3002 | +0,3203 |

`hyde_passage_prefix` findet das Ziel in allen 14 Fällen in den Top-10;
`hyde_query_prefix` in 12 von 14 (verfehlt: q-gap-04, q-gap-06); `multi_query`
in 11 von 14 (verfehlt: q-gap-02, q-gap-04, q-gap-05); die Baseline in 7 von
14. Der Unterschied liegt nicht nur im Treffer, sondern auch im Rang. Erster
Treffer je Query (baseline / hyde_passage_prefix / multi_query):

| Query | `baseline` | `hyde_passage_prefix` | `multi_query` |
|---|---:|---:|---:|
| q-gap-01 | nicht in Top-10 | 2 | 3 |
| q-gap-02 | nicht in Top-10 | 2 | nicht in Top-10 |
| q-gap-03 | 4 | 1 | 1 |
| q-gap-04 | nicht in Top-10 | 9 | nicht in Top-10 |
| q-gap-05 | nicht in Top-10 | 1 | nicht in Top-10 |
| q-gap-06 | 8 | 10 | 1 |
| q-gap-07 | 6 | 1 | 1 |
| q-gap-08 | 2 | 1 | 1 |
| q-gap-09 | 1 | 1 | 1 |
| q-gap-10 | 2 | 1 | 1 |
| q-gap-11 | 4 | 3 | 7 |
| q-gap-12 | nicht in Top-10 | 3 | 10 |
| q-gap-13 | nicht in Top-10 | 1 | 5 |
| q-gap-14 | nicht in Top-10 | 3 | 2 |

`hyde_passage_prefix` setzt den Treffer in 12 von 14 Fällen auf Rang 1 bis 3,
verfehlt aber in zwei Fällen (q-gap-04, q-gap-06) deutlich mit Rang 9 bzw. 10.
`multi_query` verfehlt drei Ziele ganz; von den verbleibenden elf Treffern
liegen sechs auf Rang 1, der Rest streut bis Rang 10 (q-gap-12). Der
Mechanismus ist derselbe wie im Ursprungslauf: eine der vier fusionierten
Ranglisten stammt von der unveränderten Query, die in diesem Fall
nachweislich schlecht rankt. RRF mittelt den oft guten Treffer der
Umformulierungen mit dem schlechten Ergebnis des Originals — das begrenzt
meist den Schaden, kostet aber den Rang und in drei von 14 Fällen den Treffer
ganz.

## Die anderen beiden Fälle

| Teilmenge | Queries | Arm | Recall@10 | nDCG@10 | MRR |
|---|---:|---|---:|---:|---:|
| `same-language` | 41 | `baseline` | 1,0000 | 0,9212 | 0,8974 |
| | | `hyde_query_prefix` | 0,7317 | 0,5826 | 0,5409 |
| | | `hyde_passage_prefix` | 0,7317 | 0,6151 | 0,5860 |
| | | `multi_query` | 0,9756 | 0,8456 | 0,8154 |
| `cross-language` | 5 | `baseline` | 0,2000 | 0,2000 | 0,2000 |
| | | `hyde_query_prefix` | 0,4000 | 0,1631 | 0,0917 |
| | | `hyde_passage_prefix` | 0,4000 | 0,2262 | 0,1667 |
| | | `multi_query` | 0,4000 | 0,2578 | 0,2200 |

Hier liegt der Preis von HyDE: **Recall@10 fällt bei 41 von 60 Queries von
1,0000 auf 0,7317.** `hyde_passage_prefix` verfehlt elf der 41
`same-language`-Ziele vollständig; `hyde_query_prefix` verfehlt zehn
vollständig und trifft zwei nur zur Hälfte (Queries mit zwei relevanten
Chunks) — macht denselben Recall-Verlust von 0,2683. Der Prompt schreibt die
hypothetische Passage auf Englisch — für die deutschen `same-language`-Queries
wandert die Suche damit in den englischen Sprachraum und findet dort einen
plausiblen, aber falschen Text. Genau die Asymmetrie, die #708 gemessen hat
(der Sprachraum dominiert die Ähnlichkeit stärker als das Thema), wirkt hier
gegen das Verfahren.

`multi_query` bleibt in `same-language` fast unversehrt (0,9756 gegen
1,0000, Δ -0,0244) — der einzige Rückschritt ist q-de-14: Die Baseline findet
das Ziel dort auf Rang 1, `multi_query` verfehlt es in den Top-10 komplett.
Ein einzelner Treffer, aber real, und relevant für die Empfehlung unten.

`cross-language` bewegt sich jetzt bei allen drei Umform-Armen, anders als im
26er-Lauf: Recall@10 steigt von 0,2000 (1 von 5, `baseline`) auf 0,4000 (2 von
5) bei `hyde_query_prefix`, `hyde_passage_prefix` **und** `multi_query` —
allerdings nicht bei derselben Query. Beide HyDE-Varianten finden zusätzlich
q-cross-04, `multi_query` zusätzlich q-cross-01; q-cross-03 ist der
gemeinsame Treffer aller vier Arme, q-cross-02 und q-cross-05 bleiben bei
allen Armen unauffindbar. Trotz gleichem Recall trennt nDCG@10 die Arme:
`multi_query` liegt mit 0,2578 vorn, vor `hyde_passage_prefix` (0,2262),
`hyde_query_prefix` (0,1631) und der Baseline (0,2000). Fünf Queries bleiben
eine sehr dünne Stichprobe — ein einzelner Treffer verschiebt Recall@10 um
0,2.

## HyDE wirkt gegenläufig je Fall

Das breitere Goldset macht sichtbar, was der 26-Query-Lauf nicht auflösen
konnte: HyDE ist nicht durchweg schlechter, sondern schlägt in
entgegengesetzte Richtungen aus, je nachdem, ob eine Sprachlücke vorliegt.

Bei `language-gap` ist HyDE **deutlich stark**: nDCG@10 0,6763
(`hyde_query_prefix`) bzw. 0,7337 (`hyde_passage_prefix`) gegen 0,2725 der
Baseline — mehr als eine Verdopplung, genau dort, wo das Retrieval am
schwächsten ist. Der Verlust entsteht ausschließlich im gleichsprachigen
Fall: `same-language`-nDCG@10 fällt von 0,9212 (Baseline, nahe am Maximum)
auf 0,5826 bzw. 0,6151, weil die Baseline dort ohnehin fast perfekt arbeitet
und jede Umformung nur stören kann.

Auf 26 Queries stellten `same-language`-Fälle 69 % des Sets (18 von 26); ihr
Verlust überdeckte den Gewinn bei den damals nur sechs `language-gap`-Queries
vollständig, und im Gesamtmittel blieb nur „HyDE schadet". Bei 14
`language-gap`-Queries (23 % der jetzt 60 Queries) wird die Gegenläufigkeit
erkennbar — das Gesamtmittel bleibt für HyDE negativ, ist aber jetzt sichtbar
ein Mittelwert über zwei entgegengesetzte Effekte, kein einheitlicher Befund.

**Daraus folgt eine Hypothese, die dieser Lauf erzeugt, aber nicht belegt:**
bedingter Einsatz von HyDE, ausgelöst durch eine erkannte Sprachlücke
zwischen Anfrage und Bestand. Um das zu belegen, bräuchte es einen eigenen
Aufbau: eine zur Laufzeit belastbare Erkennung der Sprachlücke (nicht die im
Goldset hinterlegte, nachträglich von Hand vergebene `case`-Annotation), eine
Messung, die auch Fehler dieser Erkennung einpreist, und eine
Signifikanzrechnung über beide Teilmengen. Nichts davon ist in diesem Lauf
gemessen.

## Latenz je Verfahren

Drei Posten aus drei verschiedenen Quellen — was wie gemessen wurde, steht in
`tests/fixtures/hyde_multiquery_733/transforms.json` unter `meta` in Klartext.
Werte je Query:

| Arm | Umformung | Embedding | Suche | Summe |
|---|---:|---:|---:|---:|
| `baseline` | 0 ms | 9,45 ms | 1,49 ms | ≈ 11 ms |
| `hyde_query_prefix` | 7810,82 ms | 9,45 ms | 1,52 ms | ≈ 7822 ms |
| `hyde_passage_prefix` | 7810,82 ms | 9,45 ms | 1,47 ms | ≈ 7822 ms |
| `multi_query` | 6290,64 ms | 37,80 ms | 6,08 ms | ≈ 6335 ms |

- **Umformung** — Wanduhrzeit von 60 echten `claude -p`-Aufrufen je Verfahren
  (p50/p95: HyDE 7810,82 / 10731,12 ms, Multi-Query 6290,64 / 8895,15 ms). Das
  ist eine **obere Schranke**: der CLI-Aufruf bezahlt Prozess- und
  Sitzungsaufbau, den eine Umformung innerhalb einer laufenden Sitzung nicht
  bezahlt. Der Posten ist hermetisch nicht messbar, weil der Messlauf selbst
  kein Modell aufruft.
- **Embedding** — Anzahl der Embeddings des Arms mal dem Median einer echten
  e5-Einbettung aus dem Generatorlauf (9,45 ms bei 300 Messungen). Der
  Playback-Embedder des Messlaufs ist ein Dict-Zugriff; seine Zeit als
  Embedding-Latenz auszugeben, wäre eine erfundene Zahl.
- **Suche** — in diesem Lauf gemessen, über den echten `knn_chunks`-Pfad.
  Multi-Query sucht viermal statt einmal.

Beide Verfahren kosten also **drei Größenordnungen** mehr als die Baseline,
und der Posten, der das verursacht, ist in beiden Fällen der Modellaufruf.
Die Embedding- und Suchkosten von Multi-Query (zusammen 43,88 ms gegen
10,94 ms) fallen daneben nicht ins Gewicht.

## Entscheidungsregel

Vorab festgelegt, damit die Empfehlung nicht der Vorliebe folgt:

1. **Ausschluss:** Ein Verfahren, das in irgendeiner Teilmenge (den drei
   Fall-Kategorien `same-language`, `language-gap`, `cross-language`)
   Recall@10 gegen die Baseline verliert, wird nicht empfohlen. Ein nicht
   gefundener Treffer ist im Betrieb nicht durch besseres Ranking heilbar; ein
   schlechter Rang innerhalb der Top-10 ist es. Die Regel kennt keine
   Bagatellgrenze — auch ein Verlust von einer einzigen Query zählt.
2. **Auswahl:** Unter den verbleibenden gewinnt das Verfahren mit dem größten
   Zugewinn bei `language-gap` nDCG@10 — das ist die Lücke, deretwegen dieses
   Issue existiert.
3. Bleibt keines übrig, lautet die Empfehlung „keines".

`test_recommendation_matches_measured_deltas` rechnet diese Regel aus den
eingecheckten Rohdaten nach; eine Empfehlung, die den Zahlen widerspricht,
macht den Test rot.

## Empfehlung

**Keines der beiden Verfahren**

Nach Regel 1 verliert **jeder** der drei geprüften Arme Recall@10 in
mindestens einer Teilmenge gegenüber der Baseline — auch wenn die Ausprägung
sehr unterschiedlich ausfällt:

- `hyde_query_prefix` und `hyde_passage_prefix` verlieren beide massiv
  `same-language`-Recall@10 (1,0000 → 0,7317, betrifft zehn bis zwölf von 41
  Queries).
- `multi_query` verliert ebenfalls `same-language`-Recall@10, aber nur bei
  einer einzigen Query: q-de-14 (Baseline findet das Ziel auf Rang 1,
  Multi-Query verfehlt es ganz — Recall 1,0000 → 0,9756, Δ -0,0244).

Damit bleibt nach der vorab festgelegten Ausschlussregel kein Verfahren
übrig, das ohne Einschränkung empfohlen werden kann — auch Multi-Query nicht,
dessen Verlust so klein ist, dass er im ursprünglichen 26-Query-Lauf gar
nicht auftrat (dort lag `same-language`-Recall bei 1,0000).

Beide Verfahren zeigen aber reale, gemessene Stärken:

- **Multi-Query** dreht auf dem breiteren Goldset das Gesamtvorzeichen bei
  nDCG@10 (+0,0232) und MRR (+0,0204) — beide Werte liegen über der Baseline,
  aber nur knapp über der Rauschmarge von 0,02, die #708 für sein eigenes
  CI-Gate ansetzt, und dieser Lauf rechnet kein Konfidenzintervall (anders als
  der Kandidatenvergleich in #731). Der `language-gap`-Zugewinn ist
  deutlicher: nDCG@10 0,5727 gegen 0,2725 der Baseline (+0,3002), MRR 0,5197
  gegen 0,1994 (+0,3203) — aber mit dem beschriebenen `same-language`-Rückschritt
  bei q-de-14 erkauft.
- **HyDE** liefert bei `language-gap` den mit Abstand größten gemessenen
  Hebel: nDCG@10 0,6763 (`hyde_query_prefix`) bzw. 0,7337
  (`hyde_passage_prefix`) gegen 0,2725 — mehr als eine Verdopplung. Der Preis
  ist der `same-language`-Einbruch, der beide Präfixvarianten disqualifiziert.

Was dieser Lauf nahelegt, aber nicht belegt, ist ein bedingter Einsatz von
HyDE bei erkannter Sprachlücke (siehe „HyDE wirkt gegenläufig je Fall" oben).
Das wäre ein drittes, hier nicht gemessenes Verfahren mit eigenem
Erkennungsbaustein — kein Freibrief für eines der beiden geprüften Verfahren
in seiner hier gemessenen, unbedingten Form. Wer die Sprachlücke wirklich
schließen will, findet in HyDE das stärkere Werkzeug und müsste dessen Preis
anders bezahlen als hier gemessen; wer nur eine geringfügige Verbesserung
sucht und den einzelnen `same-language`-Verlust bei q-de-14 in Kauf nimmt,
findet in Multi-Query das mit Abstand risikoärmere der beiden geprüften
Verfahren — aber die Entscheidungsregel dieses Reports empfiehlt es nicht
vorbehaltlos.

## Aufbau des Laufs

```
scripts/eval/query_expansion_prototypes.py     Prompts, Prompt-IDs, fuse_rankings() (RRF)
scripts/eval/build_hyde_multiquery_fixture.py  Live-Generator (zwei Stufen, beide opt-in)
scripts/eval/run_hyde_multiquery_eval.py       hermetischer Messlauf, vier Arme
tests/fixtures/hyde_multiquery_733/
├── transforms.json   60 Umformungen: HyDE-Passage + 3 Varianten je Query, Latenz, Manifest
└── vectors.json      300 base64-kodierte float32-Vektoren (384d)
```

**Umformungen erzeugen** (dauert rund 15 Minuten — Hochrechnung aus den
gemessenen Mittelwerten: 60 × 8060,29 ms HyDE + 60 × 6582,83 ms Multi-Query ≈
878.587 ms —, 120 CLI-Aufrufe):

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

- **Die Stichprobe ist größer, aber für die kleineren Teilmengen weiterhin
  klein.** `language-gap` hat jetzt 14 Queries (vorher sechs); `cross-language`
  weiterhin nur fünf (vorher zwei). Ein einzelner Treffer verschiebt
  `cross-language`-Recall@10 um 0,2. Die eigentliche Evidenz sind deshalb die
  Per-Query-Tabellen und die Rohdaten, nicht nur der Mittelwert.
- **Kein Konfidenzintervall.** Die Deltas sind Punktschätzungen; der
  Multi-Query-Gewinn im Gesamtmittel (+0,0232 nDCG@10, +0,0204 MRR) liegt nur
  knapp über der Rauschmarge von 0,02, die #708 für sein CI-Gate ansetzt. Der
  Kandidatenvergleich in #731 rechnet dafür ein Intervall, dieser Lauf nicht.
- **Gemessen wird eine eingefrorene Stichprobe von Umformungen, keine
  Verteilung.** Jede Query hat genau eine HyDE-Passage und drei Varianten, aus
  einem Lauf. Ein zweiter Lauf desselben Prompts liefert andere Texte und damit
  andere Zahlen; wie groß diese Streuung ist, ist hier nicht gemessen.
- **Der HyDE-Prompt legt die Sprache fest.** Er verlangt eine englische
  Passage. Das ist eine Designentscheidung, kein Naturgesetz — und sie erklärt
  den `same-language`-Verlust vollständig, während sie den `language-gap`-Gewinn
  erst ermöglicht (siehe „HyDE wirkt gegenläufig je Fall"). Ein Prompt, der die
  Sprache der Anfrage übernimmt, wäre ein anderes Verfahren mit anderen Zahlen.
- **Die Sprachlücken-Erkennung, die eine bedingte HyDE-Anbindung bräuchte, ist
  hier nicht gemessen.** Die `case`-Annotation im Goldset ist eine
  nachträgliche, von Hand vergebene Kategorisierung, keine
  Laufzeit-Erkennung. Ob sich eine Sprachlücke zuverlässig genug erkennen
  lässt, um HyDE bedingt zuzuschalten, ist eine offene Frage.
- **Die beiden Verfahren bekommen ungleich viele Freiheitsgrade.** HyDE erzeugt
  einen Text und muss sich für eine Sprache entscheiden; Multi-Query erzeugt drei
  und deckt zwei Sprachen plus eine Präzisierung ab. Diese Asymmetrie steckt in
  der Natur der Verfahren, verschiebt aber den Vergleich zugunsten von
  Multi-Query.
- **Leckage ist ausgeschlossen, nicht nur zugesichert.** Das Modell sah beim
  Umformen ausschließlich den Query-Text. `test_transforms_carry_no_goldset_leakage`
  prüft, dass kein Anker des Goldsets wörtlich in einer Umformung steht.
- **Die Latenz der Umformung ist eine obere Schranke** (siehe oben) und stammt
  von einer einzelnen Maschine, gemessen über 60 Aufrufe je Verfahren. Sie
  taugt zum Größenordnungsvergleich, nicht als Betriebskennzahl.
- **Das Ergebnis entscheidet nichts über die produktive Anbindung.** Die folgt
  laut Issue im Nachfolge-Issue und nur für ein Verfahren, das die
  Entscheidungsregel ohne Einschränkung besteht — was auf diesem Goldset für
  keines der beiden geprüften Verfahren zutrifft. Weder `academic_vault/**`
  noch `commands/search.md` sind in diesem Lauf angefasst worden.
