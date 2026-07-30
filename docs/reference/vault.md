# Vault-MCP-Server

[← Doku-Übersicht](../README.md)

Der **Vault** (`academic_vault/`) ist die Kernkomponente seit v6.0. Er ersetzt die
flachen Markdown-Dateien durch eine SQLite-Datenbank mit FTS5-Volltext-Index und
sqlite-vec für semantische Suche.

**Datenbank:** `~/.academic-research/projects/<slug>/vault.db`

## Halluzinationsschutz

Das ist der Grund, warum es den Vault gibt: Zitate stammen nicht aus dem Modellgedächtnis,
sondern aus einer Datenbank, in der jedes Zitat mit Herkunft und Seitenzahl liegt.

Der `verbatim-guard`-Hook prüft jeden `Write`-Aufruf auf `kapitel/*.md`: enthaltene Zitate
werden gegen den Vault geprüft. Unbekannte Zitate werden geblockt mit dem Hinweis
*„Zitat nicht im Vault — bitte über `quote-extractor` ziehen"*. Ein real durchgespielter
Beleg für beide Fälle (erfundenes Zitat blockiert, verifiziertes Zitat durchgelassen) steht
im [Quickstart-Protokoll](../quickstart-protocol.md#5-halluzinationsschutz-verbatim-guard).

> Der Guard ist eine Absicherung, kein Freibrief. Prüfe Seitenzahlen, Autorennamen und
> Jahreszahlen weiterhin am Original, bevor du ein Zitat abgibst.

## Vektor-Suche (Embedding-Pipeline)

`vault.add_paper()` erzeugt seit v6.6 automatisch Chunk-Embeddings (`chunk_embeddings` +
vec0-Spiegel `chunk_vectors`); `vault.search(..., rerank=True)` führt die KNN-Treffer per
Reciprocal-Rank-Fusion mit dem BM25-Ranking zusammen.

Das Embedding-Backend (`sentence-transformers`) ist eine **reguläre Abhängigkeit** und wird
von `scripts/setup.sh` bzw. `uv sync` mitinstalliert — ohne es bliebe `chunk_embeddings`
leer und die Vektor-Suche wäre wirkungslos. Die Modellgewichte (~470 MB) lädt das Plugin
beim ersten `vault.add_paper()` nach `VAULT_EMBEDDING_CACHE` herunter; danach läuft alles
lokal und offline.

Für die Dev-Umgebung bezieht `uv` Torch aus dem CPU-Index von PyTorch
(`[tool.uv.sources]` in `pyproject.toml`), damit nicht der komplette CUDA-Stack im
Lockfile landet. Wer den pip-Weg nutzt und auf Linux kein CUDA-Wheel möchte, installiert
Torch vorab separat:

```bash
pip install --index-url https://download.pytorch.org/whl/cpu torch
```

Lässt sich das Backend nicht laden (Modell-Download nicht möglich, inkompatible
Torch-Version), fällt der Vault mit einer Log-Warnung auf FTS5-only zurück statt zu
scheitern. Genauso verhält er sich, wenn die `sqlite-vec`-Extension nicht ladbar ist
(z. B. Python-Builds ohne `--enable-loadable-sqlite-extensions` auf macOS): die KNN-Suche
rechnet dann in reinem Python über dieselben Vektoren, nur langsamer.

| Env-Variable | Default | Wirkung |
|---|---|---|
| `VAULT_AUTO_EMBED` | `1` | `0` schaltet den Embedding-Ingest in `vault.add_paper()` ab. |
| `VAULT_EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | Alternatives Modell (muss 384 Dimensionen liefern). |
| `VAULT_EMBEDDING_CACHE` | `~/.academic-research/models` | Ablageort der Modellgewichte. |
| `VAULT_MAX_CHUNKS` | `64` | Obergrenze der Chunks pro Ingest (Latenzschutz). |
| `VAULT_CONTEXTUAL_EMBEDDING` | *(aus)* | `1` + `ANTHROPIC_API_KEY` erzeugt pro Chunk einen 1-Satz-Kontext. |

Bestands-Datenbanken bekommen den vec0-Spiegel per
`python -c "from academic_vault.migrate import add_chunk_vectors_table; add_chunk_vectors_table('<pfad>/vault.db')"`.

## PDF-Volltext-Index

`papers_fts.fulltext` wird seit v6.6 real befüllt (zuvor schrieben die FTS5-Trigger die
Spalte hart auf `NULL`, die Suche sah faktisch nur Titel und Abstract). Kanonischer
Speicher ist die Tabelle `paper_fulltext`; die Trigger `papers_ai`/`papers_au` ziehen den
Text von dort in den Index, damit er ein `vault.set_ocr_done()` oder
`vault.update_pdf_path()` überlebt.

`vault.add_paper()` extrahiert den Volltext direkt beim Upsert (abschaltbar via
`VAULT_AUTO_FULLTEXT=0`); bereits extrahierte Paper werden übersprungen. Nachträglich oder
gezielt geht es per `vault.extract_fulltext(paper_id)`. Beide Wege nutzen dasselbe Backend:

- **pypdf** (Default) — offline, ohne Zusatzinfrastruktur. Reine Scan-PDFs ohne Text-Layer
  liefern leeren Text; der wird bewusst **nicht** gespeichert, damit der Lauf nach einem
  OCR-Durchgang nachgeholt werden kann.
- **GROBID** (opt-in) — `GROBID_URL` auf einen laufenden Server setzen (Apache-2.0,
  `docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.1`). Der Vault ruft
  `POST {GROBID_URL}/api/processFulltextDocument` mit abgeschalteter Consolidation auf und
  indiziert den TEI-`<text>`-Baum. Jeder Fehler (kein Server, Timeout, kaputtes XML) fällt
  still auf pypdf zurück.

| Env-Variable | Default | Wirkung |
|---|---|---|
| `VAULT_AUTO_FULLTEXT` | `1` | `0` schaltet die Volltext-Extraktion in `vault.add_paper()` ab. |
| `GROBID_URL` | *(aus)* | Aktiviert den GROBID-Pfad, z. B. `http://localhost:8070`. |
| `GROBID_TIMEOUT` | `60` | Timeout des GROBID-Requests in Sekunden. |

Bestands-Datenbanken tragen den Volltext per Backfill nach (idempotent, `papers` und
`quotes` bleiben unangetastet):

```bash
python -m academic_vault.migrate --db ~/.academic-research/projects/<slug>/vault.db --backfill-fulltext
```

## MCP-Tools (alle 41)

Der Server registriert **41 MCP-Tools** (`@mcp.tool`). Maßgebliche Code-Referenz:
[`academic_vault/server.py`](../../academic_vault/server.py) (Funktion
`_build_mcp_server`). Die folgenden Tabellen sind nach Kategorie geordnet; Signatur mit
Default-Werten, Beschreibung und Beispiel-Call.

**Suche & Papers**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.search(query, type=None, k=5, rerank=False)` | Hybrid-Suche (BM25 + vec0-KNN + RRF); `rerank=True` aktiviert zusätzlich Voyage/Cohere | `vault.search("transformer attention", k=10)` |
| `vault.get_paper(paper_id)` | Paper-Metadaten + `pdf_status` | `vault.get_paper("vaswani2017")` |
| `vault.add_paper(paper_id, csl_json, pdf_path=None, doi=None, isbn=None, page_offset=0, editor=None, chapter=None, page_first=None, page_last=None, container_title=None, parent_paper_id=None)` | Upsert eines Papers; `type` aus `csl_json` | `vault.add_paper("vaswani2017", csl_json, doi="10.5555/...")` |
| `vault.add_chapter(parent_paper_id, chapter_number, csl_json, paper_id=None, pdf_path=None, page_first=None, page_last=None)` | Legt Kapitel als Kind-Paper an; gibt `paper_id` zurück | `vault.add_chapter("book2020", 3, csl_json, page_first=45)` |
| `vault.ensure_file(paper_id)` | PDF → Anthropic Files-API; gibt gecachte `file_id` zurück | `vault.ensure_file("vaswani2017")` |
| `vault.stats()` | DB-Counts + Token-Ersparnis-Schätzung | `vault.stats()` |

**Zitate (Quotes)**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.add_quote(paper_id, verbatim, extraction_method, api_response_id=None, pdf_page=None, printed_page=None, section=None, context_before=None, context_after=None, stance=None)` | Fügt Verbatim-Zitat mit Provenance ein; `extraction_method="citations-api"` erfordert `api_response_id`; `stance` ist optional (`"supports"`/`"contrasts"`/`"mentions"`, sonst `None`) | `vault.add_quote("vaswani2017", "Attention is all you need", "citations-api", api_response_id="resp_1")` |
| `vault.search_quote_text(verbatim, k=5)` | LIKE-Volltextsuche in `quotes.verbatim` (prüft, ob ein Zitat existiert) | `vault.search_quote_text("Attention is all", k=3)` |
| `vault.find_quotes(paper_id, query=None, k=10)` | Gibt Quotes für ein Paper zurück (optional Ähnlichkeitssuche) | `vault.find_quotes("vaswani2017", query="self-attention")` |
| `vault.get_quote(quote_id)` | Vollständiger Quote-Record (inkl. Feld `stance`, standardmäßig `null`) | `vault.get_quote("q_42")` |

**Notizen & Exzerpte** (Issue #462)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.add_note(paper_id, text, tags=None, page=None)` | Fügt ein Exzerpt zu einer Quelle hinzu; `page` optional; gibt `note_id` zurück | `vault.add_note("vaswani2017", "Kernbefund: ...", page=5)` |
| `vault.find_notes(paper_id, query=None, k=10)` | Gibt Notizen für ein Paper zurück, optional per Text-Filter (LIKE) | `vault.find_notes("vaswani2017", query="Methode")` |
| `vault.search_notes(query, k=5)` | FTS5-Volltextsuche über alle Notizen — macht Exzerpte beim Kapitelschreiben themenbezogen auffindbar | `vault.search_notes("Reliabilität", k=5)` |

**Eigenes Erhebungsmaterial** (Issue #473)

Transkripte liegen als `papers`-Zeile mit `source_kind='primary'` im Vault — nur so
greift dieselbe Belegkette wie bei Literaturzitaten (`quotes.paper_id`, `verbatim-guard`).
`scripts/export-literature-state.mjs` lässt Primärmaterial im Literatur-Snapshot aus.

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.add_transcript_segment(paper_id, seq, text, speaker=None, timecode=None)` | Nimmt einen Transkript-Absatz belegfähig auf; `seq` ist die zitierfähige Stellenangabe („Abs. 5"), Upsert über `UNIQUE(paper_id, seq)`; gibt `segment_id` zurück | `vault.add_transcript_segment("interview-01", 5, "Die Abstimmung ist hilfreich …", speaker="B1", timecode="00:02:41")` |
| `vault.list_transcript_segments(paper_id)` | Gibt alle Segmente eines Transkripts in `seq`-Reihenfolge zurück | `vault.list_transcript_segments("interview-01")` |
| `vault.add_coding(paper_id, category, category_origin, segment_id=None, quote_id=None, memo=None)` | Ordnet einer Stelle eine Kategorie zu; `category_origin` ist Pflicht (`induktiv`/`deduktiv`); gibt `coding_id` zurück | `vault.add_coding("interview-01", "Teamabstimmung", "induktiv", quote_id="q-5")` |
| `vault.list_codings(paper_id=None, category=None)` | Gibt Kodierungen zurück, optional nach Paper und/oder Kategorie gefiltert | `vault.list_codings(paper_id="interview-01")` |

**Figures & Tabellen** (v6.1 Figure-Verifier)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.add_figure(paper_id, page=None, caption=None, vlm_description=None, data_extracted_json=None)` | Fügt Figure/Tabelle ein; gibt `figure_id` zurück | `vault.add_figure("vaswani2017", page=3, caption="Fig. 1: Architecture")` |
| `vault.get_figure(figure_id)` | Gibt Figure-Record zurück oder `None` | `vault.get_figure("fig_7")` |
| `vault.list_figures(paper_id)` | Alle Figures eines Papers, nach `page` sortiert | `vault.list_figures("vaswani2017")` |

**OCR-Pipeline & Seitenzählung** (v6.1)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.set_ocr_done(paper_id, value=1)` | Setzt `ocr_done`-Flag (`1`=OCR durchgeführt) | `vault.set_ocr_done("scan2019")` |
| `vault.update_pdf_path(paper_id, new_path)` | Aktualisiert den PDF-Pfad nach OCR | `vault.update_pdf_path("scan2019", "/data/scan2019_ocr.pdf")` |
| `vault.set_page_offset(paper_id, offset)` | Setzt `page_offset` (Bücher mit Vorseiten/Vorwort) | `vault.set_page_offset("book2020", 12)` |
| `vault.get_printed_page(paper_id, pdf_page)` | Berechnet gedruckte Seite: `pdf_page - page_offset` | `vault.get_printed_page("book2020", 25)` |
| `vault.extract_fulltext(paper_id, backend="auto")` | Extrahiert den PDF-Volltext und indiziert ihn in `papers_fts.fulltext` (#373) | `vault.extract_fulltext("vaswani2017")` |

**Decision-Log & Ausschlüsse**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.add_decision(category=None, text="", rationale=None)` | Fügt Entscheidung ins Decision-Log ein; gibt `decision_id` zurück | `vault.add_decision(category="scope", text="Nur Studien ab 2015", rationale="Aktualität")` |
| `vault.list_decisions(category=None, active_only=True)` | Gibt Decisions zurück (optionaler `category`-Filter) | `vault.list_decisions(category="scope")` |
| `vault.supersede_decision(decision_id, superseded_by)` | Markiert eine Decision als abgelöst durch eine neuere (`superseded_by`) | `vault.supersede_decision("dec_3", "dec_7")` |
| `vault.add_excluded_source(paper_id, reason=None)` | Fügt `paper_id` zu `excluded_sources` (verhindert Re-Vorschlag) | `vault.add_excluded_source("smith2010", reason="off-topic")` |
| `vault.is_excluded(paper_id)` | Prüft, ob `paper_id` ausgeschlossen ist | `vault.is_excluded("smith2010")` |
| `vault.list_excluded_sources()` | Gibt alle ausgeschlossenen Quellen zurück | `vault.list_excluded_sources()` |
| `vault.list_papers_by_provenance(provenance)` | Provenance-Audit: alle Papers mit gegebenem Herkunfts-Tag (z.B. `"scihub"`) | `vault.list_papers_by_provenance("scihub")` |

**Risk-of-Bias & Score-Historie** (v6.4)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.add_risk_of_bias(paper_id, study_type, domain_scores)` | Fügt RoB-Assessment ein (`domain_scores` als JSON-String); gibt `assessment_id` zurück | `vault.add_risk_of_bias("rct2018", "RCT", '{"randomization":"low"}')` |
| `vault.list_risk_of_bias(paper_id=None)` | Gibt RoB-Assessments zurück (optional nach `paper_id` gefiltert) | `vault.list_risk_of_bias("rct2018")` |
| `vault.add_score_snapshot(paper_id, session_id, scores)` | Fügt Score-Snapshot ein (`scores` als JSON-String); gibt `snapshot_id` zurück | `vault.add_score_snapshot("rct2018", "sess_1", '{"relevance":0.8}')` |
| `vault.get_score_history(paper_id, k=None)` | Score-History eines Papers (neueste zuerst) | `vault.get_score_history("rct2018", k=5)` |

**Material-Passport & Lock** (v6.4)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.export_material_passport(slug, output_dir=".", score_algo_version="1.0", plugin_version="6.4")` | Exportiert `material-passport.json`; gibt Dateipfad zurück | `vault.export_material_passport("mein-projekt")` |
| `vault.lock_passport(slug)` | Setzt Vault-Lock für `slug` (macht Vault read-only) | `vault.lock_passport("mein-projekt")` |
| `vault.is_locked(slug)` | Prüft, ob der Vault für `slug` gelockt ist | `vault.is_locked("mein-projekt")` |

**Snapshots & Backup**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call |
|------|-------------|------|
| `vault.export_snapshot(slug, project_dir=".", snapshots_dir=None)` | Exportiert State-Dateien + Vault-DB als `.tgz`-Snapshot; gibt Pfad zurück (`snapshots_dir` default `~/.academic-research/snapshots`) | `vault.export_snapshot("mein-projekt")` |
| `vault.restore_snapshot(slug, ts, snapshots_dir=None, target_dir=".")` | Stellt Snapshot `<slug>/<ts>.tgz` wieder her; gibt `True`/`False` zurück | `vault.restore_snapshot("mein-projekt", "20260604-0930")` |
