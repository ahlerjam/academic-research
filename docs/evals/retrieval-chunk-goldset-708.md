# Retrieval-Goldset auf Chunk-Ebene (#708)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Der Sollzustand steht in [`STRATEGY.md`](STRATEGY.md); die
> laufend geprüfte Fassung der Zahlen ist `thresholds.json` neben dem Goldset.
>
> **Datenstand 2026-08-10 (#800).** Das Goldset wurde von 26 auf 60 Queries
> (30 auf 61 Chunks) verbreitert; `thresholds.json` und `goldset.json` tragen
> seither die neuen Zahlen. Der Report unten beschreibt weiterhin
> ausschließlich den ursprünglichen 26-Query/30-Chunk-Lauf vom 2026-08-07 — er
> ist nicht auf den breiteren Stand nachgezogen. Die aktuellen Zahlen (60
> Queries, 61 Chunks) stehen in
> [`2026-08-10-chunk-goldset-widening-800.md`](2026-08-10-chunk-goldset-widening-800.md).

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-07 (historischer Referenzlauf, siehe Datenstands-Hinweis
oben) · **Modell:** `intfloat/multilingual-e5-small` (384d) ·
**Korpus:** 30 Chunks aus 11 synthetischen Volltexten · **Queries:** 26

Dieses Set misst die Retrieval-Strecke, die tatsächlich betrieben wird:
448-Token-Chunks aus seitenweisem Volltext, mit vorangestelltem Kontextsatz und
`passage: `-Präfix eingebettet, gesucht über `VaultDB.knn_chunks()`. Das
Vorgängerset aus [#628](recall-at-k-model-ab-hard-628.md) embeddet
`"{title}. {abstract}"` und misst damit etwas anderes als das, was läuft.

Anders als #375/#628 ist dieser Lauf **hermetisch**: die Vektoren liegen
vorberechnet im Repo, es gibt keinen Modell-Download und keinen Netzzugriff.
Deshalb läuft er bei jedem PR im CI-Job `retrieval-goldset` und wird rot, sobald
eine Metrik unter ihre hinterlegte Schwelle fällt.

## Ergebnis des Referenzlaufs

| Teilmenge | Queries | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|---:|
| **gesamt** | 26 | **0,7692** | **0,6651** | **0,6314** |
| `same-language` | 18 | 1,0000 | 0,9170 | 0,8889 |
| `language-gap` (DE-Frage → EN-Text) | 6 | 0,3333 | 0,1311 | 0,0694 |
| `cross-language` (EN-Frage → DE-Text) | 2 | 0,0000 | 0,0000 | 0,0000 |

Drei Befunde, die die Zahlen tragen:

1. **Innerhalb einer Sprache ist das Set fast gesättigt.** Recall@10 liegt bei
   1,0; nur nDCG und MRR trennen noch, weil in fünf Fällen der Zieltreffer auf
   Rang 2 statt Rang 1 steht. Für ein Regressionsgatter reicht das — eine
   Verschlechterung senkt nDCG sofort —, für einen Modellvergleich nicht.
2. **Die Sprachlücke ist groß und real.** Vier von sechs deutschen Fragen auf
   englische Fachtexte finden ihr Ziel in den Top-10 überhaupt nicht, obwohl der
   Text die Frage wörtlich beantwortet. Der Deckeneffekt aus #375 tritt hier
   ausdrücklich **nicht** ein: die Fragen sind umgangssprachlich formuliert und
   teilen kein Wort ab fünf Zeichen mit dem Zielchunk (hart geprüft in
   `test_language_gap_pair_exists_and_is_measured`).
3. **Die Asymmetrie ist stärker als erwartet.** Beide englischen Fragen auf
   deutsche Texte liefern ausschließlich englische Chunks in den Top-10 — der
   Sprachraum dominiert die Ähnlichkeit deutlicher als das Thema. Die Teilmenge
   `cross-language` hat deshalb heute die Schwelle 0,0: sie ist als **Messung**
   im Report sichtbar, taugt aber vorerst nicht als Gatter. Das ehrlich
   auszuweisen ist der Punkt; eine geschönte Schwelle wäre wertlos.

Rohdaten je Query stehen in der JSON-Ausgabe des Runners (`per_query`, inklusive
`first_hit_rank` und der vollständigen Trefferliste).

## Aufbau des Sets

```
tests/fixtures/retrieval_goldset_chunks_708/
├── sources.json      11 synthetische Volltexte (seitenweise) + 26 Queries mit Ankern
├── goldset.json      30 Chunks aus chunk_pages() + Queries mit aufgelösten IDs
├── vectors.json      base64-kodierte float32-Vektoren (384d) für Chunks und Queries
└── thresholds.json   Schwellen je Metrik, gesamt und je Teilmenge
```

**Quelltexte.** Elf Dokumente à drei bis vier Seiten, vollständig selbst
geschrieben — es liegt bewusst kein fremdes Paper unter Copyright im Repo. Acht
tragen Zielchunks, drei sind reine Distraktoren (`"_role": "distractor"`), die
Vokabular mit den Zieldokumenten teilen (Freigabe, Nachweis, Aufbewahrung,
Zugriff) und Rangdruck erzeugen. Sieben Dokumente sind englisch, vier deutsch.

**Chunks.** `chunking.chunk_pages()` mit den Produktionsdefaults
(`TARGET_TOKENS = 448`, `OVERLAP_RATIO = 0.125`, `default_context_sentence`).
Ergebnis: 30 Chunks, 19 englisch, 11 deutsch, im Mittel 261 Wörter. Jeder
`embedding_text` ist exakt `default_context_sentence(...) + " " + chunk_text`;
das Embedding entsteht über `E5SmallEmbedder.embed_documents`, das den
`passage: `-Präfix ergänzt.

**Relevanzurteile.** Queries verweisen in `sources.json` nicht auf Chunk-Indizes,
sondern auf **Anker** — wörtliche Textstellen. Der Generator löst sie auf die
Chunks auf, die sie enthalten. Verschieben sich die Chunkgrenzen (anderer
Tokenizer, anderes Tokenbudget), bleiben die Urteile gültig; ein Anker, der in
keinem Chunk mehr vorkommt, bricht den Generator ab, statt still eine
Fehlmessung zu erzeugen. Wegen der Fensterüberlappung liegen vier Anker in je
zwei benachbarten Chunks — beide gelten dann als relevant.

**Queries.** 26 Stück in drei Fällen: 18 `same-language` (11 EN, 7 DE),
6 `language-gap` (deutsche Umgangssprache auf englischen Fachtext),
2 `cross-language` (englische Frage auf deutschen Text).

**Der Lauf.** Der Runner schreibt die Vektoren über
`VaultDB.add_chunk_embedding()` in eine Wegwerf-DB und rankt mit
`VaultDB.knn_chunks(k=10)` — also über den echten Speicher- und KNN-Pfad
inklusive vec0-Spiegel, sofern die Extension ladbar ist. Beide `knn_chunks`-Pfade
(vec0 und Python-Fallback) liefern bei L2-normalisierten Vektoren dieselbe
Reihenfolge, das Ergebnis ist damit plattformunabhängig.

## Wie die Schwellen zustande kamen

`thresholds.json` entsteht nicht aus einem Zielwert, sondern aus dem oben
tabellierten Referenzlauf **minus einer Marge von 0,02**
(`build_retrieval_chunk_goldset.py --write-thresholds --margin 0.02`).

Die Marge darf klein sein, weil der Lauf bei fixen Vektoren deterministisch ist:
gemessen wird kein Modell, sondern nur noch die Rangfolge über eingecheckte
Zahlen. Die 0,02 fangen Rundungsunterschiede zwischen Plattformen ab, keine
Qualitätsschwankung. Eine großzügigere Marge wäre hier kein Sicherheitspuffer,
sondern eine Lücke: sie würde genau die Verschlechterung durchlassen, deretwegen
das Gatter existiert.

`tests/test_issue_708_retrieval_chunk_goldset.py::test_thresholds_stay_below_measured_values`
hält beide Richtungen fest: keine Schwelle darf über dem Messwert liegen (sonst
ist die CI dauerhaft rot), und keine mehr als 0,15 darunter (sonst gattert sie
nichts mehr).

Dass die Schwelle greift, ist nicht behauptet, sondern geprüft:
`test_runner_exits_nonzero_below_threshold` rotiert die Query-Vektoren
gegeneinander — jede Query zieht dann die Antwort einer anderen — und verlangt
Exit ≠ 0 samt Nennung der unterschrittenen Metrik.

## Vektoren nach einem Modellwechsel neu erzeugen

Ein Wechsel des Embedding-Modells (`VAULT_EMBEDDING_MODEL`, siehe #629) entwertet
die Fixture vollständig: die Vektoren liegen dann in einem anderen Raum. Neu
erzeugen:

```bash
VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/build_retrieval_chunk_goldset.py --write-thresholds
```

Was dabei passiert:

1. `VAULT_E5_LIVE_TEST=1` hebt den Backend-Guard aus `tests/conftest.py` auf —
   ohne die Variable bricht das Skript mit Exit 2 ab. Der echte e5-Tokenizer
   wird geladen (exakte Chunkgrenzen), danach das Modell (~470 MB beim ersten
   Mal, danach aus `~/.academic-research/models`).
2. `goldset.json` und `vectors.json` werden neu geschrieben, samt
   `manifest_sha256` über alle `embedding_text`e, alle Query-Texte, Modell-ID und
   Dimension.
3. Mit `--write-thresholds` werden die Schwellen aus dem frisch gemessenen Lauf
   abgeleitet. **Ohne** das Flag bleiben die alten Schwellen stehen — sinnvoll,
   wenn ein Modellwechsel die alten Werte halten *soll*.
4. Danach diesen Report von Hand nachziehen: Tabelle, Modellname, Datum. Der
   Report ist eine Momentaufnahme und altert (Konvention aus `README.md`).

Der Drift-Schutz greift, falls jemand `goldset.json` editiert, ohne neu zu
rechnen: `manifest_sha256` passt dann nicht mehr, der Runner endet mit Exit 2 und
nennt den Generator-Befehl. Ein `chunk_text`, dessen Vektor zu einem anderen
Textstand gehört, käme sonst als stille Metrikverschiebung durch.

Ändern sich nur die Quelltexte in `sources.json`, gilt derselbe Weg — zusätzlich
müssen die Anker weiter im Text vorkommen, sonst bricht der Generator ab.

## Grenzen

- **Der Ingest sieht genau eine Seite.** `ingest_paper_embeddings()` chunkt seit
  #708 über dasselbe `chunking.chunk_pages()` mit denselben Defaults wie dieses
  Set — vorher lief dort `split_text()` (Zeichenfenster, `context_sentence=""`),
  und das Set hätte etwas gemessen, das nirgends läuft. Der Ingest-Text kommt
  aus `papers_fts.fulltext`, und der trägt seit #373 bewusst keine Seitengrenzen
  mehr; er geht deshalb als **eine** Seite hinein, die Seitenangabe im
  Kontextsatz lautet dort immer „Seite 1-1". Die Quelldokumente hier sind
  mehrseitig, also steht in ihren Kontextsätzen ein echter Seitenbereich. Das
  ist die einzige verbliebene Abweichung, und sie ist vermessen statt behauptet:
  `test_flat_text_changes_only_the_page_range_in_the_context_sentence`
  (in `tests/test_issue_708_ingest_uses_chunk_pages.py`) belegt, dass
  Chunkgrenzen, Section-Titel und Chunk-Index dabei identisch bleiben.
  `page_start`/`page_end` haben ohnehin keine Spalte in `chunk_embeddings`.
- **Die Chunks sind Datenlage, nicht hermetisch reproduzierbar.** Hermetisch
  fällt `chunk_pages()` auf `approximate_token_count` zurück und setzt die
  Grenzen anders als der echte e5-Tokenizer. Die Identität beweist der
  Live-Test `test_live_rechunk_matches_fixture` (Gate `VAULT_E5_LIVE_TEST=1`);
  hermetisch geprüft werden nur die Invarianten (Kontextsatz-Vertrag,
  Monotonie von Index und Seitenzahlen, Manifest-Hash).
- **Der Korpus ist klein.** 30 Chunks bei k=10 heißt: ein Drittel des Bestands
  passt in die Trefferliste. Recall@10 ist deshalb innerhalb einer Sprache
  gesättigt und trennt dort nicht mehr; die Aussagekraft liegt bei nDCG@10, MRR
  und der Sprachlücke. Für einen Modellvergleich braucht es ein größeres Set.
- **Die lexikalische Seite dieses Sets ist praktisch tot.** Die Queries sind
  ausgeschriebene Sätze; FTS5-`MATCH` verknüpft ohne `OR` implizit mit UND, und
  ein einziges Token, das nirgends wörtlich vorkommt, lässt den gesamten
  Treffer scheitern. Gemessen: 1 von 26 Queries erzielt überhaupt einen
  `papers_fts`-Treffer, 0 bei `papers_trgm`
  ([#789](2026-08-08-chunk-fusion-ablation-729.md#nachtrag-2026-08-09-789-die-korpus-zu-klein-diagnose-war-unvollständig)).
  Für die Vektorstrecke, die dieses Set messen soll, ist das folgenlos; für
  jede Frage nach der **Hybrid**-Fusion ist es der entscheidende Vorbehalt.
  Dafür gibt es seit [#790](2026-08-09-chunk-fusion-goldset-790.md) ein
  ergänzendes Probe-Goldset, das dieselben elf Dokumente und 26 Queries
  wortgleich enthält und um lexikalisch treffende Probe-Queries erweitert.
- **Die Texte sind synthetisch.** Sie imitieren Fachprosa in Aufbau und
  Registerhöhe, aber sie enthalten weder Formeln, noch Tabellenreste, noch die
  Umbruchartefakte einer PDF-Extraktion — genau die Textsorten also, bei denen
  die Tokenschätzung laut Modul-Docstring von `chunking.py` am weitesten
  danebenliegt.
- **Das Set entscheidet nichts über einen Modellwechsel.** Es schafft die
  Grundlage dafür (Metriken, hermetischer Lauf, Schwellen); der Vergleich
  mehrerer Kandidaten bleibt bei #628/#730.
