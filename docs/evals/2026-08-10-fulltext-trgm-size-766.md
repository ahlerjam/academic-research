# Lohnt ein Trigram-Index über PDF-Volltext und Notizen? (#766)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Messlaufs, keine laufend
> gepflegte Zahl.

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-10 · **Folge-Issue aus:** #703 (Trigram-Index für Titel/Abstract,
PR #767) · **Generator:** [`scripts/eval/measure_fulltext_trgm_size_766.py`](../../scripts/eval/measure_fulltext_trgm_size_766.py)
· **Rohdaten:** [`2026-08-10-fulltext-trgm-size-766.json`](2026-08-10-fulltext-trgm-size-766.json)

## Entscheidungsregel (Issue-Kommentar vom 2026-08-10)

Ein Trigram-Index über `paper_fulltext.text` bzw. `notes.text` kommt nur, wenn **beide**
Bedingungen erfüllt sind:

1. **Größe:** die Vault-Datei wächst durch den Index um weniger als 100 % (höchstens
   Verdopplung), gemessen an einem realistischen Bestand.
2. **Nutzen:** ein Nachweis, dass die Teilwortsuche im Volltext bzw. in Notizen Treffer
   erzeugt, die die bestehende Wortsuche (`papers_fts`/`notes_fts`) nicht schon liefert.

Reißt Bedingung 1, fällt die Entscheidung negativ — unabhängig von Bedingung 2.

## Ergebnis

| Tabelle | Zeilen | Baseline (Bytes) | mit Trigram-Index (Bytes) | Zuwachs |
|---|---:|---:|---:|---:|
| `paper_fulltext` | 40 Paper | 16.547.840 | 32.112.640 | **+94,06 %** |
| `notes` | 80 Notizen | 5.267.456 | 6.262.784 | **+18,90 %** |

**Entscheidung: kein Index — für beide Tabellen.**

## Bedingung 1 (Größe) — Methode und Einordnung

Gemessen an einer synthetischen Vault-DB (aktuelles Schema, `VaultDB.init_schema()`),
befüllt über die echten Schreibpfade (`server.add_paper`, `server.add_note`,
`VaultDB.set_fulltext`) — **nicht** simuliert. Der Textkorpus ist bewusst
nicht-repetitiv (kombinatorischer Aufbau aus ~40 deutschen Wortstämmen × 14 Endungen
plus Funktionswörtern statt Lorem-Ipsum-Wiederholung, siehe
`scripts/eval/measure_fulltext_trgm_size_766.py::_sentence`) — ein sich wiederholender
Text würde den Trigram-Zuwachs künstlich niedrig ausfallen lassen, weil SQLite-FTS5 stark
von Textredundanz profitiert.

- **`paper_fulltext`:** 40 synthetische Paper, Volltextgröße pro Paper deterministisch
  zwischen 50–200 KB (Issue-Body-Schätzung), je Paper über den echten `add_paper()`-Weg
  eingefügt (löst damit auch den produktiven Embedding-Ingest aus — die Baseline ist
  folglich eine **realistische** Vault-Größe inklusive Chunk-Vektoren, nicht nur
  Rohtext). Die Trigram-Variante hängt eine eigene `fts5(tokenize='trigram')`-Tabelle
  über `paper_fulltext.text` an derselben DB an (Kopie, kein Rebuild) und misst erneut
  nach `VACUUM`.
- **`notes`:** 80 synthetische Notizen (0,5–5 KB, eigene Schätzung — deutlich kleiner als
  Volltexte), analog gemessen über eine `notes_trgm`-Tabelle.

**Bedingung 1 ist für beide Tabellen rechnerisch erfüllt** (94,06 % bzw. 18,90 % <
100 %) — der Volltext-Wert liegt allerdings **knapp** unter der Schwelle, nicht
„deutlich darunter". Der Kommentar vom 2026-08-10 nennt „deutlich unter 100 %
Zuwachs" als Auslöser, die Nutzenfrage neu zu stellen — 94 % erfüllt dieses Kriterium
nicht. Zwei Gründe, warum der Wert nicht 1:1 mit dem reinen Text-Overhead des
Trigram-Tokenizers vergleichbar ist:

1. Die Baseline enthält bereits Chunk-Embeddings (der produktive `add_paper()`-Pfad
   embedded automatisch), die einen erheblichen, vom Trigram-Index unabhängigen Anteil
   der Baseline-Größe stellen. Das drückt den *relativen* Zuwachs nach unten, verglichen
   mit einer Text-only-Baseline — macht die Zahl aber realistischer für einen echten
   Vault, in dem Embeddings ohnehin vorhanden sind.
2. Bei kleineren/frischeren Vaults (wenige Paper, noch keine Embeddings) wäre der
   relative Zuwachs deutlich höher, da der Trigram-Index dann einen größeren Anteil der
   Gesamtgröße ausmacht.

## Bedingung 2 (Nutzen) — nicht neu erhoben, sondern referenziert

Der Issue-Kommentar verlangt hier ausdrücklich **keine neue Messung**: „Miss die Größe,
dokumentiere sie, und halte fest, dass Bedingung 2 mit dem heutigen Goldset nicht
prüfbar ist."

- **#722** hat den bestehenden Trigram-Index (Titel/Abstract, #703) gegen das
  #708-Goldset gemessen: Δ = ±0,0000 in allen drei Metriken (Recall@10/nDCG@10/MRR).
- Der #722-Report erklärt die Null als **Messgrenze**, nicht als Befund: die
  synthetischen #708-Dokumente haben Titel, aber keine Abstracts — `papers_trgm`
  deckt nur diese beiden Felder ab und kann den Effekt gar nicht auslösen.
- **#789** verschärft das: `test_708_goldset_lexical_side_is_structurally_dead` belegt,
  dass **1 von 60** Queries überhaupt einen `papers_fts`-Treffer erzielt, **0 von 60**
  einen `papers_trgm`-Treffer.

Die lexikalische Seite des Goldsets ist strukturell tot — ein Nutzennachweis für einen
Volltext- oder Notiz-Trigram-Index ist auf dieser Datenbasis **nicht zu führen**, weder
positiv noch negativ. Das gilt für `paper_fulltext` ebenso wie für `notes` (kein
lexikalisch lebendiges Notizen-Goldset existiert überhaupt).

## Gesamtentscheidung

| Tabelle | Bedingung 1 (Größe < 100 %) | Bedingung 2 (Nutzen belegt) | Entscheidung |
|---|---|---|---|
| `paper_fulltext` | erfüllt, aber knapp (94,06 %) | nicht prüfbar (#789) | **kein Index** |
| `notes` | erfüllt (18,90 %) | nicht prüfbar (kein Goldset) | **kein Index** |

Beide Tabellen erfüllen Bedingung 1 formal, aber die Entscheidungsregel verlangt
**beide** Bedingungen — Bedingung 2 ist nach heutiger Datenlage für keine der beiden
Tabellen zu erbringen. Das ist laut Issue-Kommentar ein **vollständiges Ergebnis**, keine
Lücke: „nicht auf dieser Datenlage entscheidbar, und der Preis allein trägt ihn nicht"
(zutreffend für `notes`, wo der Preis niedrig ist, ohne dass das etwas am fehlenden
Nutzenbeleg ändert).

**Konsequenz für AC4** (Migration/Backfill/`_REQUIRED_MIGRATION_TABLES`): **nicht
ausgelöst**. Schema, `migrate.py` und `db.py` bleiben unverändert — eine
Schema-Migration ohne erfüllte Bedingung 2 ist laut Issue-Kommentar ausdrücklich nicht
gedeckt.

## Wann diese Entscheidung neu zu stellen wäre

- Ein lexikalisch lebendiges Goldset entsteht (im Raum für den Reranker-Nachlauf,
  #802-Entscheidungsdokument) — dann lässt sich Bedingung 2 tatsächlich prüfen.
- Der Volltext-Zuwachs müsste bei einer erneuten Messung **deutlich** unter 100 % fallen
  (nicht nur knapp wie hier), um die Nutzenfrage von sich aus dringlicher zu machen.

Beides ist ausdrücklich **nicht** Teil dieses Issues.

## Reproduktion

```
uv run python scripts/eval/measure_fulltext_trgm_size_766.py
```

Deterministisch über `--seed` (Default 766); die Zahlen oben stammen aus einem
Standardlauf (`--n-papers 40 --n-notes 80`).
