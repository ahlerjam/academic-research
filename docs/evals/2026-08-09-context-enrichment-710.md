# Was kostet die inhaltliche Kontextsatz-Anreicherung real? (#784, Epic #710-B)

> **Historisches Dokument.** Momentaufnahme eines einzelnen Laufs, nicht der
> aktuelle Stand. Rohdaten liegen daneben in
> [`2026-08-09-context-enrichment-710-live-results.json`](2026-08-09-context-enrichment-710-live-results.json).

[← Doku-Übersicht](../README.md) · [← Evals-Übersicht](README.md)

**Stand:** 2026-08-09 · **Agent:** `agents/chunk-context-writer.md` (Sonnet) ·
**Aufrufweg:** `claude -p --model sonnet --output-format json`, echter
`academic-vault`-MCP-Server (echter stdio-Subprozess, echte SQLite-Vault,
echtes `BAAI/bge-m3`-Embedding) · **Rohdaten:**
[`2026-08-09-context-enrichment-710-live-results.json`](2026-08-09-context-enrichment-710-live-results.json)
· **Generator:** `scripts/eval/measure_context_enrichment_710.py`
(`VAULT_CONTEXT_LIVE_TRANSFORM=1`)

## Fragestellung

#785 (#710-C) hat bereits gezeigt, dass ein inhaltlicher Kontextsatz dem
Retrieval nützt. Offen war, was der produktive Schreibweg aus #783/#784
**real kostet** — Sitzungstokens, Zeit, Re-Embedding-Latenz — an genau dem
Pfad, der auch aus `/academic-research:fetch` aufgerufen wird: der echte
`chunk-context-writer`-Agent, gegen den echten MCP-Server, nicht eine
Simulation davon (der Unterschied zu #785: dort schrieb ein roher
`claude -p`-Prompt Sätze in eine Fixture, hier läuft der Agent selbst mit
echtem Tool-Zugriff).

## Aufbau

Zwölf `claude -p`-Sitzungen, eine je Paper, seriell:

- **11 Goldset-Dokumente** aus
  [`tests/fixtures/embedding_candidates_731/bge-m3/goldset.json`](../../tests/fixtures/embedding_candidates_731/bge-m3/goldset.json)
  (dieselben 30 Chunks wie in [#731](2026-08-08-embedding-candidates-731.md)/[#785](2026-08-08-context-ablation-710.md)),
  direkt über `VaultDB.add_chunk_embedding()` mit dem Metadaten-Kontextsatz
  aus dem Fixture gesät (`context_source="metadata"`, pending).
- **Ein reales Paper mit ≥ 20 Chunks:** kein Fixture im Repo erreicht das
  (größtes textführendes PDF-Fixture: 13 Chunks,
  `tests/fixtures/chunking/multi_section_paper.pdf`). Stattdessen
  [„Attention Is All You Need"](https://arxiv.org/abs/1706.03762)
  (Vaswani et al. 2017, arXiv:1706.03762, frei zugänglich) — nur für diesen
  Live-Lauf heruntergeladen, **nicht im Repo enthalten**. Gesät über den
  echten Produktionspfad `academic_vault.server.add_paper(pdf_path=...)`
  (Volltextextraktion + Embedding-Ingest, derselbe Aufruf wie
  `vault_add_paper` in `commands/fetch.md` Schritt 2) — ergab 27 Chunks.

Jede Sitzung: frischer `claude -p`-Prozess, `--system-prompt` = exakt der
Body von `agents/chunk-context-writer.md` (kein Duplikat), `--mcp-config`
mit ausschließlich dem `academic-vault`-Server (`--strict-mcp-config`),
`--allowedTools` beschränkt auf die zwei deklarierten Tools,
`--tools ""` (keine eingebauten Tools). Das ist der engste Zugriff, den ein
echter `Task()`-Dispatch dem Subagenten auch gewähren würde.

## Ergebnis: 57/57 Chunks angereichert, keine Skips

| | Wert |
|---|---:|
| Sitzungen | 12 |
| Chunks gesamt | 57 (30 Goldset + 27 real) |
| Erfolgreich angereichert (`context_source='model'`) | 57 (100 %) |
| `skipped`-Einträge über alle Batches | 0 |
| Gesamtkosten (`total_cost_usd`, summiert) | **1,51 USD** |

Kein einziger Chunk landete in `skipped` — die 25-Wörter-Grenze und die
Sprachregel wurden in diesem Lauf durchgehend beim ersten Versuch
eingehalten, kein Korrekturdurchgang war nötig (bei keinem der zwölf
Papers). Das ist eine Beobachtung dieses einen Laufs, keine Garantie — die
Skip-Pfade selbst sind unabhängig davon durch die #783-Vault-Layer-Tests
abgedeckt (leerer/zu langer Satz, unbekannte `chunk_id`).

## Kosten pro Paper

| | Kosten gesamt | Chunks | Kosten/Chunk |
|---|---:|---:|---:|
| 11 Goldset-Dokumente (2–3 Chunks/Paper) | 1,05 USD | 30 | 0,0351 USD |
| 1 reales Paper (27 Chunks) | 0,45 USD | 27 | 0,0169 USD |
| **Gesamt** | **1,51 USD** | **57** | **0,0265 USD** |

**Kosten/Chunk sinkt mit der Papergröße.** Jede Sitzung trägt einen fixen
Sockelbetrag (System-Prompt + zwei MCP-Tool-Schemas, `pending_context_chunks`-
Aufruf), der sich bei einem 2-Chunk-Paper auf wenige Sätze verteilt, bei
einem 27-Chunk-Paper auf entsprechend mehr. Für ein typisches Paper mit
10–20 Chunks liegt der reale Wert zwischen den beiden Polen dieser Tabelle,
nicht linear interpolierbar (siehe Turn-Verhalten unten).

**Token-Summe über alle 12 Sitzungen** (`usage`-Felder, `total_cost_usd`
je Sitzung aufsummiert):

| Feld | Summe |
|---|---:|
| `input_tokens` | 88 |
| `cache_creation_input_tokens` | 141.406 |
| `cache_read_input_tokens` | 1.029.006 |
| `output_tokens` | 23.379 |

`cache_read_input_tokens` dominiert bei Weitem — der System-Prompt (Agent-
Body + zwei Tool-Schemas) ist über die 1-Stunden-Ephemeral-Cache-TTL hinweg
mehrfach wiederverwendet worden, weil alle zwölf Sitzungen seriell und
innerhalb einer Stunde liefen. **Das ist repräsentativ für den
Produktivfall:** wer in einer Sitzung mehrere Papers nacheinander per
`/academic-research:fetch` lädt, zahlt den vollen Cache-Erstellungspreis nur
einmal, danach überwiegend den deutlich günstigeren Cache-Read-Preis. Der
erste Aufruf **des Tages** (kalter Cache, keine Vorlaufsitzung) liegt näher
an den rund 0,15 USD, die ein isolierter Vorabtest mit zwei Chunks in
diesem Lauf kostete (nicht Teil der obigen Summe) — die Sockelkosten sind
dort nicht amortisiert.

## Latenz

Zwei getrennt gemessene Posten, wie im #785-Vorbild:

| Posten | n | p50 | p95 | Mittelwert | Max |
|---|---:|---:|---:|---:|---:|
| Sitzung, reine Modellzeit (`duration_api_ms`) | 12 | 14.428 ms | 28.967 ms | 22.407 ms | 95.119 ms |
| Sitzung, Wanduhrzeit (`duration_ms`, inkl. MCP-Kaltstart) | 12 | 27.951 ms | 55.666 ms | 36.496 ms | 108.683 ms |
| Re-Embedding je Einzeltext (`BAAI/bge-m3`, CPU) | 57 | 83,0 ms | 91,5 ms | 80,8 ms | 147,2 ms |

**`duration_ms` (Wanduhrzeit) ist pessimistisch für wiederholte Aufrufe.**
Jede der zwölf Sitzungen startete einen FRISCHEN
`academic-vault`-MCP-Serverprozess, der das bge-m3-Modell (≈ 2,3 GB) beim
ersten Tool-Aufruf lädt — der Median-Abstand zwischen Wanduhrzeit und
`duration_api_ms` (≈ 13,5 s) ist größtenteils dieser Kaltstart, nicht
Modellzeit. In einer echten interaktiven Sitzung läuft der MCP-Server
bereits (ein Ladevorgang pro Sitzung, nicht pro Paper) — `duration_api_ms`
ist deshalb der tragfähigere Vergleichswert für wiederholte Aufrufe in
derselben warmen Sitzung.

## Beobachtung: das reale Paper hielt die Ein-Batch-Regel nicht ein

Der Agentenprompt verlangt EINEN `enrich_chunk_contexts`-Aufruf mit allen
Items. Bei den elf Goldset-Papers (2–3 Chunks) hielt sich der Agent daran
(`num_turns` 3–4, ein Batch-Call). Beim realen Paper mit 27 Chunks
splittete er den Schreibvorgang in **drei** Aufrufe (10, 10, 7 Items,
`num_turns=10`) — laut `result_text`: *"verteilt auf drei Batch-Aufrufe (10,
10, 7 Items)"*. Alle 27 Chunks wurden am Ende trotzdem vollständig und
korrekt angereichert (0 `skipped`), das Ergebnis ist nicht falsch — aber
die Vorgabe "ein Batch-Aufruf" wurde bei einem größeren Paper real nicht
eingehalten.

**Relevanz für `maxTurns: 6`:** Der Agent im Frontmatter trägt `maxTurns: 6`
(Vorgabe aus dem #710-Plan-Kommentar). Dieser Live-Lauf ruft `claude -p`
direkt auf (kein `Task()`-Dispatch, der `maxTurns` durchsetzen würde) — das
reale Paper brauchte **10 Turns**, mehr als das im Frontmatter deklarierte
Budget. Ein echter `Task()`-Dispatch mit durchgesetztem `maxTurns: 6` hätte
diesen Lauf möglicherweise vor Abschluss beendet. Das ist **kein
Datenrisiko**: bricht der Agent vorzeitig ab, bleiben die noch nicht
erreichten Chunks einfach bei `context_source='metadata'` stehen — derselbe
Normalzustand wie "Anreicherung nie aufgerufen" (Fallback-Fall 1,
`docs/reference/vault.md`). Es ist aber ein **Vollständigkeitsrisiko** bei
sehr großen Papers (deutlich über 27 Chunks, bis zur `VAULT_MAX_CHUNKS`-
Obergrenze von 64): ein Teil der Chunks bliebe dauerhaft beim
Metadaten-Kontextsatz, bis ein weiterer Lauf sie erneut aufgreift. Nicht
behoben in diesem Issue (Scope: Agent + Einbindung + Messung, keine
Prompt-Nachjustierung aufgrund einer Einzelbeobachtung) — festgehalten als
Beobachtung für ein mögliches Folge-Issue, falls sich das Muster in
weiteren Läufen bestätigt.

## Grenzen

- **Ein Lauf, seriell, warmer Cache.** Alle zwölf Sitzungen liefen
  hintereinander innerhalb einer Stunde — die hohen `cache_read`-Werte
  spiegeln das. Ein isolierter Einzelaufruf (kalter Cache, z. B. der erste
  `/academic-research:fetch`-Aufruf eines Tages) kostet mehr als der
  Durchschnitt dieser Tabelle.
  - **Kein Wiederholungslauf.** Wie in #785/#733 vermerkt: ein zweiter Lauf
  mit denselben Prompts liefert andere Sätze, andere Tokenzahlen und damit
  andere Kosten/Latenzen in ähnlicher Größenordnung, nicht identisch.
- **Nur EIN reales Paper.** 27 Chunks ist ein Datenpunkt, kein Mittelwert
  über Papergrößen. Das Batch-Split-Verhalten (siehe oben) ist an genau
  diesem einen Paper beobachtet, nicht an einer Stichprobe großer Papers.
- **Wanduhrzeit ist durch den Messaufbau verzerrt** (siehe Latenz-Abschnitt)
  — jede Sitzung zahlt einen MCP-Server-Kaltstart, den eine warme
  interaktive Sitzung nicht zahlt. `duration_api_ms` ist dafür korrigiert,
  bleibt aber ebenfalls ein Einzellauf.
- **Keine Aussage zur Retrieval-Qualität.** Das ist #785s Aufgabe, nicht
  diese. Dieser Report misst ausschließlich Kosten/Latenz des Schreibwegs.

## Aufbau des Laufs

```
scripts/eval/measure_context_enrichment_710.py   Live-Runner (ein Skript, ein Gate)
docs/evals/2026-08-09-context-enrichment-710-live-results.json   Rohdaten
```

```bash
VAULT_CONTEXT_LIVE_TRANSFORM=1 uv run python \
    scripts/eval/measure_context_enrichment_710.py
```

Lädt das reale Paper bei jedem Lauf neu von arXiv (kein lokaler Cache) und
startet zwölf echte `claude -p`-Subprozesse — echte API-Kosten in der
Größenordnung von 1,50 USD je Lauf, kein hermetischer Test.
