# Abschlussmessung: wirken die Retrieval-Änderungen tatsächlich? (#722)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand.

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-08 · **Korpus:** 11 Dokumente / 30 Chunks (#708-Fixture) ·
**Queries:** 26, davon 19 auswertbar (siehe [Grenzen](#grenzen)) ·
**Reranker:** `BAAI/bge-reranker-v2-m3` (lokal, `sentence_transformers.CrossEncoder`)

Vier Issues verbessern das Retrieval unabhängig voneinander — #701
(Kontextsatz mit echten Paper-Metadaten, PR #771), #702 (Reranker bekommt
Chunk-/Abstract-Text statt Snippet-Markup, PR #768), #703 (FTS5-Komposita via
Trigram-Index, PR #767), #714 (lokaler Reranker läuft per Default, PR #772).
Jedes für sich plausibel begründet, keines gegen den Endzustand gemessen.
Dieser Lauf misst alle vier gemeinsam und einzeln (Leave-one-out ab dem
aktuellen Stand) gegen das Chunk-Goldset aus [#708](retrieval-chunk-goldset-708.md),
aggregiert auf **Paper-Ebene**: ein Paper gilt als relevant, wenn es
mindestens einen relevanten Chunk der Query enthält.

## Ergebnis

| Zustand | Recall@10 | nDCG@10 | MRR |
|---|---:|---:|---:|
| **vor** (alle vier Änderungen zurückgeschaltet) | 0,7308 | 0,6619 | 0,6394 |
| **nach** (aktueller Stand, alle vier aktiv) | 0,7308 | 0,6868 | 0,6731 |
| Δ gesamt | ±0,0000 | **+0,0249** | **+0,0337** |

Recall@10 ist über **alle** sechs gemessenen Kombinationen identisch
(0,7308) — bei 11 Papers und k=10 passt praktisch der ganze Bestand in die
Trefferliste, das Maß sättigt strukturell (siehe [Grenzen](#grenzen)). Die
gesamte Aussage dieses Laufs steckt in nDCG@10 und MRR.

### Beitrag je Änderung (Leave-one-out ab dem aktuellen Stand)

Δ = Metrik mit Änderung **minus** Metrik ohne diese eine Änderung (bei sonst
aktuellem Stand). Positiv heißt: die Änderung hilft.

| Änderung | Issue/PR | Recall@10 | nDCG@10 | MRR |
|---|---|---:|---:|---:|
| Kontextsatz mit Paper-Titel | #701 / #771 | +0,0000 | **−0,0050** | **−0,0064** |
| Reranker bekommt echten Text | #702 / #768 | +0,0000 | +0,0000 | +0,0000 |
| Trigram-Komposita | #703 / #767 | +0,0000 | +0,0000 | +0,0000 |
| Lokaler Reranker per Default | #714 / #772 | +0,0000 | **+0,0107** | **+0,0144** |

Die Summe der vier Einzeldeltas (−0,0050 + 0 + 0 + 0,0107 = +0,0057 nDCG)
liegt **unter** dem Gesamtdelta (+0,0249 nDCG) — die vier Änderungen wirken
nicht rein additiv, es gibt einen Interaktionseffekt zwischen ihnen (am
plausibelsten: der veränderte Kontextsatz verschiebt, welche Chunks der
Reranker überhaupt zu Gesicht bekommt). Das ist eine Beobachtung, keine
Erklärung, die dieser Lauf beweisen könnte — dafür wäre der volle
Faktorenplan nötig (16 statt 6 Kombinationen), den dieses Chore-Issue bewusst
nicht fährt (siehe Plan-Kommentar).

## Drei Änderungen ohne messbaren Effekt — und warum das plausibel ist

**#702 (Reranker-Text) und #703 (Trigram) liegen bei exakt 0,0000 in allen
drei Metriken.** Das ist kein Rundungsartefakt, sondern strukturell erklärbar:

- **#702** wirkt nur auf Kandidaten, die *ausschließlich* über FTS5 gefunden
  wurden (kein vec0-Treffer, also kein echter Chunk-Text verfügbar). Der
  #708-Korpus hat für alle 11 Papers vollständige Chunk-Embeddings — jedes
  Paper, das FTS5 überhaupt findet, hat also auch einen vec0-Kandidaten mit
  echtem Chunk-Text, und `_fill_missing_reranker_text` hat nichts zu tun. Der
  Fix ist real (behebt einen gemeldeten Bug, siehe #702-Issue-Text), aber
  dieses Goldset kann ihn nicht auslösen.
- **#703** indiziert `papers_trgm` ausschließlich über `title`/`abstract`
  (siehe `academic_vault/schema.sql`), **nicht** über den Chunk-Volltext. Die
  synthetischen #708-Papers haben Titel, aber keine Abstracts, und die
  Test-Queries zielen auf Inhalte im Fließtext, nicht auf Komposita in
  Titeln. Damit trifft der Teilwort-Zweig hier strukturell nie — unabhängig
  davon, ob die Migration gelaufen ist oder nicht.

Beide Nullen sind also **Aussagen über die Reichweite dieses Goldsets**, keine
Aussagen darüber, ob #702/#703 im Betrieb wirken.

## Regression: #701 (Kontextsatz mit Paper-Titel)

nDCG@10 sinkt um 0,0050, MRR um 0,0064, wenn der Kontextsatz den Paper-Titel
trägt (Recall@10 unverändert). Die Größenordnung ist klein — kleiner als die
0,02-Marge, die [#708](retrieval-chunk-goldset-708.md) für sein eigenes
CI-Gate als Rauschband ansetzt — und bei 19 auswertbaren Queries kippt sie
durch einzelne Rangverschiebungen um eine Position.

**Empfehlung: nicht zurücknehmen.** Drei Gründe:

1. Die Regression liegt unterhalb dessen, was dieses kleine, synthetische
   Set zuverlässig von Rauschen unterscheiden kann (vgl. die 0,02-Marge in
   #708).
2. #701 hat einen eigenständigen Nutzen, den dieses Set nicht prüft: Chunks
   aus unterschiedlichen Papers mit ähnlichem Fließtext (z. B. die
   Distraktor-Dokumente) werden über den Titel im Embedding-Raum trennbarer
   — ein Effekt, der bei 11 Papers mit klar unterschiedlichen Themen kaum
   zum Tragen kommt, in einem großen Korpus mit vielen ähnlichen Papers aber
   der eigentliche Zweck der Änderung ist.
3. Ein Revert von #701 wäre selbst eine "neue Retrieval-Verbesserung" im
   Sinne des Out-of-Scope dieses Issues — dieser Lauf schafft die
   Entscheidungsgrundlage, trifft aber keine Änderungsentscheidung.

Sollte ein künftiger, größerer Lauf (siehe [Grenzen](#grenzen)) dieselbe
Richtung mit größerer Marge bestätigen, ist das ein Fall für ein eigenes
Issue — nicht für eine stille Rücknahme hier.

## Grenzen

- **Ein vorbestehender FTS5-Sanitize-Defekt entfernt 7 von 26 Queries aus der
  Messung**, unabhängig von #722: `academic_vault.db._sanitize_fts5_query`
  entschärft `- ^ / * ( ) " :`, aber **kein Komma**. Jede Query mit Komma
  (`"wie erkennt man früh, dass ..."`) lässt `papers_fts`/`papers_trgm` MATCH
  mit `sqlite3.OperationalError: fts5: syntax error near ","` abbrechen.
  Betroffen: `q-de-05`, `q-gap-01`, `q-gap-03`, `q-gap-04`, `q-gap-05`,
  `q-gap-06`, `q-cross-02` — **6 von 6** `language-gap`-Queries und 1 von 2
  `cross-language`-Queries. Der Harness fängt das ab (leere Trefferliste
  statt Laufabbruch, siehe `fts5_syntax_errors` im
  [Rohdaten-Anhang](retrieval-ablation-722-live-results.json)), aber die
  Aussagekraft für genau die Teilmenge, die im #708-Report als "größte
  Sprachlücke" beschrieben ist, ist damit für 2026-08-08 **nicht vorhanden**.
  Dieser Defekt liegt in `academic_vault/db.py` (`area/vault`, geschützt) —
  außerhalb des Scopes dieses Chore-Issues zu fixen; er gehört als eigenes
  Issue gemeldet.
- **Recall@10 ist bei 11 Papers und k=10 strukturell gesättigt** (siehe
  Ergebnis-Tabelle oben) — es trennt nichts zwischen "vor" und "nach". Die
  Aussagekraft liegt vollständig bei nDCG@10 und MRR.
- **#702 und #703 sind auf diesem Korpus strukturell unsichtbar** (siehe
  oben) — die gemessenen Nullen bestätigen NICHT, dass die Änderungen wirkungslos
  sind, sondern dass dieses Set sie nicht prüfen kann.
- **Kein voller Faktorenplan.** 4 Binärschalter ergeben 16 Kombinationen;
  gemessen wurden 6 (die beiden Randpunkte plus Leave-one-out ab "nach"). Ein
  gefundener Interaktionseffekt (siehe oben) ist damit benannt, aber nicht
  zerlegt.
- **Der Korpus ist klein und synthetisch** — dieselbe Einschränkung wie im
  [#708-Report](retrieval-chunk-goldset-708.md#grenzen): keine Formeln,
  Tabellenreste oder PDF-Umbruchartefakte, keine echten Abstracts.
- **#701 "vor" nutzt die eingecheckte #708-Fixture direkt** (deren Chunks
  wurden 2026-08-07 gebaut, vor #701) — **#701 "nach"** baut den Kontextsatz
  live neu (`chunking.PaperMeta(title=...)`, echter e5-Tokenizer) und
  embeddet live neu. Beide Zustände laufen über denselben Produktionscode
  (`chunking.default_context_sentence`), keine Nachbildung.
- **#702 ist der einzige Shim in diesem Lauf** (`scripts/eval/run_retrieval_ablation_722.py::search_papers_pre_702`)
  — die anderen drei "vor"-Zustände sind reale Produktions-Stellschrauben
  (`paper_meta=None`, fehlende `papers_trgm`-Tabelle,
  `VAULT_RERANK_LOCAL_DISABLE`). Der Shim ist gegen das reale Verhalten des
  #702-Diffs (Commit `68f2ed8`) differenziell geprüft in
  `tests/test_issue_722_retrieval_ablation.py`, nicht durch Wiederausführung
  des historischen Codes.

## Grundlage für #712

Dieser Lauf liefert die Zahlen, auf denen die Modellentscheidung in #712
aufbauen kann — er trifft selbst **keine** Modellentscheidung und empfiehlt
keinen Modellwechsel. #712 bleibt offen.

## Reproduktion

```bash
VAULT_E5_LIVE_TEST=1 uv run python scripts/eval/run_retrieval_ablation_722.py \
  --out docs/evals/retrieval-ablation-722-live-results.json
```

Lädt den echten e5-Tokenizer/-Embedder und (für die `local_rerank`-Kombinationen)
`BAAI/bge-reranker-v2-m3` über `sentence_transformers.CrossEncoder` — beide
aus dem lokalen HuggingFace-Cache, sofern vorhanden, sonst per Download. Nicht
hermetisch, nicht CI-pflichtig (analog `scripts/eval/recall_at_k_model_ab.py`,
#375/#628, und `scripts/eval/build_retrieval_chunk_goldset.py`, #708). Die
vollständigen Rohdaten (alle 6 Kombinationen, `per_query`, `fts5_syntax_errors`)
liegen unter `docs/evals/retrieval-ablation-722-live-results.json`.
