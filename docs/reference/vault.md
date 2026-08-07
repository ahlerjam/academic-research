# Vault-MCP-Server

[← Doku-Übersicht](../README.md)

Der **Vault** (`academic_vault/`) ist die Kernkomponente seit v6.0. Er ersetzt die
flachen Markdown-Dateien durch eine SQLite-Datenbank mit FTS5-Volltext-Index und
sqlite-vec für semantische Suche.

**Datenbank:** `~/.academic-research/projects/<slug>/vault.db`

## Halluzinationsschutz

Das ist der Grund, warum es den Vault gibt: Zitate stammen nicht aus dem Modellgedächtnis,
sondern aus einer Datenbank, in der jedes Zitat mit Herkunft und Seitenzahl liegt.

Der `verbatim-guard`-Hook prüft jeden `Write`-Aufruf auf `kapitel/**/*.md` (Unterordner
eingeschlossen) und `*.tex`: enthaltene Zitate
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
| `VAULT_EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | Alternatives Modell, beliebige Dimension. Auf einem bereits befüllten Vault braucht ein Wechsel der Dimension einen Re-Index (siehe unten). |
| `VAULT_EMBEDDING_CACHE` | `~/.academic-research/models` | Ablageort der Modellgewichte. |
| `VAULT_MAX_CHUNKS` | `64` | Obergrenze der Chunks pro Ingest (Latenzschutz). |

Bestands-Datenbanken bekommen den vec0-Spiegel per
`python -c "from academic_vault.migrate import add_chunk_vectors_table; add_chunk_vectors_table('<pfad>/vault.db')"`.

### Modellwechsel und Re-Index

Welches Modell einen Vault gefüllt hat und in welcher Breite, steht in der Tabelle
`embedding_meta` und ist über `vault.stats()` ablesbar (`embedding_model`,
`embedding_dim`). Beide Felder sind `null`, solange noch nie ein Embedding geschrieben
wurde — das ist eine Aussage über den Bestand, nicht über die Konfiguration, und es wird
dafür kein Modell geladen.

Vektoren zweier Modelle liegen nicht im selben Raum. Ein Modell mit abweichender Dimension
schreibt deshalb **nicht** in einen befüllten Vault, sondern scheitert mit
`EmbeddingDimensionMismatchError` und dem Hinweis auf den Re-Index (vorher lief so ein
Wechsel still durch, und jede Suche sah danach nur den zufällig passenden Teilbestand,
Issue #629). Ein **leerer** Vault übernimmt die Dimension des ersten Modells ohne
Zwischenschritt.

```bash
python -m academic_vault.migrate --db ~/.academic-research/projects/<slug>/vault.db --reindex-embeddings
```

Der Lauf berechnet alle Chunk- und Zitat-Vektoren mit dem aktuell konfigurierten Modell neu
(Quelle: `chunk_embeddings.embedding_text` bzw. `quotes.verbatim` samt Kontext), legt die
vec0-Tabellen in der neuen Breite an und schreibt `embedding_meta` fort. Anders als die
Backfills füllt er keine Lücken, sondern **ersetzt den gesamten Bestand** — nur so
verschwindet ein Mischbestand aus zwei Modellen. Ein gesperrter Vault (Material-Passport)
wird vor der ersten Änderung abgewiesen. Nicht im Scope des Wechsels: die Chunk-Größen in
`chunking.py` bleiben unverändert, ein Modell mit anderem Kontextfenster braucht dafür
eine eigene Entscheidung.

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

## Tabellenextraktion

Die Meta-Analyse (`agents/meta-analysis.md`), die Extraktionsmatrix
(`skills/extraction-matrix/SKILL.md`) und die Verzerrungsbewertung (`agents/risk-of-bias.md`) stehen
und fallen mit Zahlen aus den Primärstudien — und diese Zahlen stehen in Tabellen. Der
Volltextpfad oben kann sie nicht liefern: `normalize_whitespace()` kollabiert jede
Whitespace-Folge zu einem Leerzeichen, was für den FTS5-Index richtig ist und die letzte
Strukturinformation einer Tabelle vernichtet. Seit Issue #630 gibt es deshalb einen
**zweiten, danebenliegenden Pfad** (`academic_vault/tables.py` → Tabelle `paper_tables`).
Er fasst `paper_fulltext`, `papers_fts` und die FTS5-Trigger nicht an; der Volltext bleibt
byteweise unverändert (Regressionstest: `test_fts5_fulltext_is_byte_identical_after_table_extraction`).

```
vault.extract_tables("smith2020")            # PDF -> paper_tables
vault.list_tables("smith2020")               # Zeilen-/Spaltenmatrix je Tabelle
vault.get_table_cell("smith2020", 1, 0, 1, 1)  # eine Zelle mit Beleg
```

`vault.get_table_cell()` liefert neben `value` und `bbox` das Feld `evidence` — einen
fertigen Beleg der Form `smith2020, S. 1, Tabelle 1, Zeile 2, Spalte 2`. `page` ist die
PDF-Seite (1-basiert), `table_index`, `row` und `col` sind 0-basiert; im Beleg stehen sie
1-basiert, weil ihn ein Mensch gegen das PDF hält.

**Backend: pdfplumber, Pflicht-Dependency**

Seit Issue #723 läuft `pdfplumber` als Teil von `[project.dependencies]` bei jedem `uv sync`
automatisch mit (Endnutzer-Installation: `scripts/requirements.txt`). Fehlt das Paket in
einer realen Installation dennoch, läuft der bestehende Volltextpfad unverändert weiter und
`vault.extract_tables()` meldet `status="backend-missing"` mit Installationsanweisung
(`pip install 'pdfplumber>=0.11'`) — keine Exception, kein stilles Nichts.

| Kandidat | Bewertung |
|---|---|
| **pdfplumber** (gewählt) | Reines Python (pdfminer.six, Pillow, pypdfium2), keine Systembinaries. `Page.find_tables()` gibt Zellen als Bounding-Boxen zurück — genau die Adressierbarkeit, die der Zellbeleg braucht. Drei zusätzliche Pakete im Lock. |
| camelot | Setzt Ghostscript und OpenCV als Systembinaries voraus. Eine Installationsanleitung, die am Betriebssystem hängt, ist für ein Claude-Code-Plugin die falsche Grundlage. |
| Docling | Layout-Modelle im GB-Bereich landen in `uv.lock` und in jedem CI-Job — dieselbe Falle, die in `pyproject.toml` bereits für FlagEmbedding dokumentiert ist. Bessere Erkennung, unverhältnismäßiger Preis. |
| Marker | Wie Docling modellgestützt, zusätzlich auf GPU ausgelegt. Für den Offline-Anspruch des Vaults zu schwer. |

**Statusmodell** — „nichts gefunden" ist nie eine leere Liste ohne Begründung:

| `status` | Bedeutung |
|---|---|
| `ok` | Mindestens eine Tabelle erkannt und in `paper_tables` abgelegt. |
| `no-tables` | Text-Layer vorhanden, aber kein auswertbares Tabellengitter. |
| `no-textlayer` | Keine Zeichen im PDF (Scan) — erst OCR, dann erneut extrahieren. |
| `backend-missing` | pdfplumber nicht installiert; `message` nennt die Nachinstallation. |

**Bekannte Grenzen**

Beide Fälle sind als Fixture abgedeckt (`tests/fixtures/tables/`) und ihr tatsächlicher
Ist-Zustand ist in `tests/test_issue_630_table_extraction.py` festgeschrieben — nicht
schöngefärbt:

- **Verbundene Kopfzellen** (`merged_header.pdf`): Eine über zwei Spalten laufende
  Kopfzelle wird als *eine* breite Zelle geliefert; die von ihr geschluckte Position
  erscheint in `rows` als `null` und taucht in `cells` gar nicht auf (eine Zelle ohne
  eigene Bounding-Box wäre kein Beleg). Die Datenzeilen darunter bleiben davon unberührt
  und korrekt zugeordnet. Wer die Spaltenüberschrift braucht, liest sie aus der zweiten
  Kopfzeile.
- **Zweispaltiges Layout** (`two_column_layout.pdf`): Eine Tabelle in der linken Spalte
  wird korrekt erkannt und der Fließtext der rechten Spalte gerät nicht hinein — weil
  pdfplumber per Default über *gezeichnete Linien* erkennt und nicht über Textausrichtung.
  Die Kehrseite derselben Voreinstellung: eine Tabelle **ohne** Gitterlinien (reine
  Whitespace-Ausrichtung, in Preprints verbreitet) wird nicht gefunden und meldet
  `no-tables`.

Eine extrahierte Zahl ist ein **Vorschlag mit Beleg**, keine übernommene Tatsache:
`scripts/meta_analysis.py` bekommt `yi`/`vi` weiterhin nur nach ausdrücklicher Bestätigung,
und `extraction-matrix` markiert eine Zelle ohne Tabellenbeleg unverändert als `— fehlend —`.

Bestands-Datenbanken bekommen `paper_tables` idempotent nachgezogen:

```bash
python -c "from academic_vault.migrate import add_paper_tables_table as m; m('<pfad>/vault.db')"
```

## MCP-Tools (alle 49)

Der Server registriert **49 MCP-Tools** (`@mcp.tool`). Maßgebliche Code-Referenz:
[`academic_vault/server.py`](../../academic_vault/server.py) (Funktion
`_build_mcp_server`). Die folgenden Tabellen sind nach Kategorie geordnet; Signatur mit
Default-Werten, Beschreibung und Beispiel-Call.

**Suche & Papers**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.search(query, type=None, k=5, rerank=False)` | Hybrid-Suche (BM25 + vec0-KNN + RRF); `rerank=True` aktiviert zusätzlich Voyage/Cohere | `vault.search("transformer attention", k=10)` | Vault mit indizierten Papers; die Vektor-Hälfte braucht ein geladenes Embedding-Modell | `list[dict]` der Treffer, nach Rang zusammengeführt | Leere Liste trotz passender Papers — dann fehlt der Index; `vault.component_status()` nennt die Ursache |
| `vault.get_paper(paper_id)` | Paper-Metadaten + `pdf_status` | `vault.get_paper("vaswani2017")` | Bekannte `paper_id` | `dict` mit Metadaten und `pdf_status`, sonst `None` | Rückgabe `None` — die `paper_id` steht nicht im Vault |
| `vault.add_paper(paper_id, csl_json, pdf_path=None, doi=None, isbn=None, page_offset=0, editor=None, chapter=None, page_first=None, page_last=None, container_title=None, parent_paper_id=None)` | Upsert eines Papers; `type` aus `csl_json` | `vault.add_paper("vaswani2017", csl_json, doi="10.5555/...")` | Gültiges CSL-JSON (`type` ∈ `book`/`chapter`/`article-journal`), Vault nicht gesperrt | Kein Rückgabewert; das Paper steht danach im Vault, Volltext und Embeddings laufen mit | `ValueError` („csl_json ist kein valides JSON", „verletzt Schema"); bei gesperrtem Vault `VaultLockedError` |
| `vault.add_chapter(parent_paper_id, chapter_number, csl_json, paper_id=None, pdf_path=None, page_first=None, page_last=None)` | Legt Kapitel als Kind-Paper an; gibt `paper_id` zurück | `vault.add_chapter("book2020", 3, csl_json, page_first=45)` | Vorhandenes Eltern-Paper und gültiges Kapitel-CSL-JSON | `paper_id` des angelegten Kind-Papers | `ValueError` „add_chapter: Ungueltiges csl_json" |
| `vault.stats()` | DB-Counts (`paper_count`, `quote_count`) plus Embedding-Bestand (`embedding_model`, `embedding_dim`) | `vault.stats()` | Erreichbare Vault-DB | `dict` mit `paper_count`, `quote_count`, `embedding_model`, `embedding_dim` | `embedding_model` und `embedding_dim` sind `null` — es wurde nie ein Embedding geschrieben |
| `vault.component_status()` | Zustand der optionalen Bestandteile (Embedding-Modell, `sqlite-vec`, FTS5): je `loaded`, laienverständlicher `impact`-Text bei Fehlen, `reason` sofern ermittelbar, plus `python_executable` und `db_path` (#624) | `vault.component_status()` | Keine — der Aufruf lädt bewusst kein Modell | `dict` je Bestandteil mit `loaded`, `impact` und `reason`, dazu `python_executable` und `db_path` | `loaded: false` bei Embedding-Modell oder `sqlite-vec`; `impact` sagt, was dadurch fehlt |

**Zitate (Quotes)**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.add_quote(paper_id, verbatim, extraction_method, api_response_id=None, pdf_page=None, printed_page=None, section=None, context_before=None, context_after=None, stance=None)` | Fügt Verbatim-Zitat mit Provenance ein. `extraction_method` ist `"local-verbatim"` (**fail-closed**, s. u., der einzige Weg für neue Zitate seit #632), `"manual"` (ungeprüft) oder `"citations-api"` (erfordert `api_response_id`; nur noch für Bestandszitate aus älteren Läufen gültig); `stance` ist optional (`"supports"`/`"contrasts"`/`"mentions"`, sonst `None`) | `vault.add_quote("vaswani2017", "Attention is all you need", "local-verbatim")` | Paper mit lesbarem lokalem PDF (für `local-verbatim`), Vault nicht gesperrt | `quote_id`; gespeichert werden der Wortlaut aus der Quelle und die verifizierte Seite | `ValueError` mit Prüfstatus `no-match` oder `no-textlayer` — es wird nichts gespeichert |
| `vault.search_quote_text(verbatim, k=5)` | LIKE-Volltextsuche in `quotes.verbatim` (prüft, ob ein Zitat existiert) | `vault.search_quote_text("Attention is all", k=3)` | Vault mit mindestens einem Zitat | `list[dict]` der Treffer aus `quotes.verbatim` | Leere Liste — dieser Wortlaut liegt nicht im Vault |
| `vault.find_quotes(paper_id, query=None, k=10)` | Gibt Quotes für ein Paper zurück (optional Ähnlichkeitssuche) | `vault.find_quotes("vaswani2017", query="self-attention")` | Bekannte `paper_id` | `list[dict]` der Zitate des Papers | Leere Liste — zu diesem Paper wurde nie ein Zitat gezogen |
| `vault.get_quote(quote_id)` | Vollständiger Quote-Record (inkl. Feld `stance`, standardmäßig `null`) | `vault.get_quote("q_42")` | Bekannte `quote_id` | `dict` mit dem vollständigen Record inklusive `stance`, sonst `None` | Rückgabe `None` — die `quote_id` existiert nicht |
| `vault.verify_verbatim(paper_id, candidate)` | Read-only-Vorschau des Verbatim-Prüfpfads: liefert **immer** `{status, verbatim, pdf_page, ratio}` zurück (`status` ∈ `"exact"`/`"snapped"`/`"no-match"`/`"no-textlayer"`, kein `ValueError` bei Nicht-Treffer). Paper unbekannt oder kein/kein lesbarer `pdf_path` wirft weiterhin `ValueError`. Schreibt nichts (s. u.) | `vault.verify_verbatim("vaswani2017", "Attention is all you need")` | Paper im Vault mit lesbarem `pdf_path` | Immer `{status, verbatim, pdf_page, ratio}` — auch bei Nicht-Treffer | `status` ist `no-match` oder `no-textlayer`; `ValueError` nur bei unbekanntem Paper oder fehlendem PDF |
| `vault.set_quote_stance(quote_id, stance)` | Setzt `stance` eines **bestehenden** Zitats nachträglich (Audit-Schreibpfad, u. a. für `quote-fidelity-auditor`). `stance` ist Pflicht (`"supports"`/`"contrasts"`/`"mentions"`, kein `None`); `ValueError` bei ungültigem Wert oder unbekannter `quote_id` | `vault.set_quote_stance("q_42", "contrasts")` | Bestehende `quote_id` und ein gültiger `stance` | Kein Rückgabewert; `quotes.stance` ist danach gesetzt | `ValueError` „Ungueltiger stance" oder „Quote '<id>' nicht gefunden" |
| `vault.record_quote_audit(quote_id, verdict, severity=None)` | Protokolliert ein Audit-Urteil eines **bestehenden** Zitats (Issue #737), additiv zu `vault.set_quote_stance` — beide werden vom `quote-fidelity-auditor` nach jedem Urteil aufgerufen, auch bei `verdict="unsupported"` (dort bleibt `set_quote_stance` aus). `verdict` ∈ `"faithful"`/`"overstated"`/`"context-stripped"`/`"polarity-flip"`/`"unsupported"`; `severity` ∈ `"kritisch"`/`"hoch"`/`"mittel"` ist Pflicht außer bei `verdict="faithful"` (dort zwingend `None`, kein Befund) | `vault.record_quote_audit("q_42", "polarity-flip", "kritisch")` | Bestehende `quote_id`, gültige Verdict/Severity-Kombination | Kein Rückgabewert; `quotes.audited_at`/`audit_verdict`/`audit_severity` sind danach gesetzt | `ValueError` bei ungültiger Kombination oder unbekannter `quote_id` |
| `vault.chapter_quote_balance(chapter_path)` | Prüfbilanz für ein Kapitel: bucketet alle im Kapiteltext belegten Vault-Zitate nach Audit-Historie (siehe Abschnitt „Prüfbilanz je Kapitel" unten) | `vault.chapter_quote_balance("kapitel/03-methodik.md")` | Lesbare Kapiteldatei; Zitate müssen im Vault stehen, um erfasst zu werden | `dict` mit `total_quotes`, den drei Zählern (`geprueft_unauffaellig`/`befund_offen`/`nicht_geprueft`), `not_audited` (je Eintrag mit `reason`) und `findings` (offene Befunde, schwerste zuerst) | `FileNotFoundError`, wenn `chapter_path` nicht existiert |

**`extraction_method="local-verbatim"` — fail-closed** (Issue #512)

`vault.add_quote` prüft den Wortlaut selbst gegen den lokalen PDF-Volltext des
Papers, **bevor** irgendetwas geschrieben wird. Das Enforcement sitzt im Vault
und nicht in einem Hook — es lässt sich nicht per Marker abschalten.

| Situation | Verhalten |
|---|---|
| Paper unbekannt, kein `pdf_path`, Datei nicht vorhanden | `ValueError`, nichts gespeichert |
| Prüfstatus `no-match` oder `no-textlayer` | `ValueError` inkl. Status und bester Ähnlichkeit, nichts gespeichert |
| Prüfstatus `exact` oder `snapped` | gespeichert wird der **Wortlaut aus der Quelle** (nicht der übergebene Kandidat) und die **verifizierte Seite**; ein abweichendes `pdf_page` wird verworfen und geloggt |

Grenzen der Prüfung: seitenübergreifende Zitate und ausgelassene Wörter können
falsch-negativ als `no-match` gelten. Dann ist `extraction_method="manual"` mit
eigenem Beleg der richtige Weg — nicht das Aufweichen der Prüfung.

**`vault.verify_verbatim` — read-only Vorschau** (Issue #513)

Nutzt denselben Prüfpfad wie das `local-verbatim`-Gate von `vault.add_quote`
(gemeinsame Paper-/`pdf_path`-Auflösung), aber ohne Schreibzugriff und ohne
`ValueError` bei Nicht-Treffer: `status="no-match"`/`"no-textlayer"` kommen
als reguläres Ergebnis zurück. Damit können Agenten einen Kandidaten
iterativ prüfen und korrigieren, bevor `vault.add_quote` endgültig ablehnt.
Paper unbekannt oder kein/kein lesbarer `pdf_path` bleiben `ValueError` —
das sind Bedienfehler des Aufrufers, keine Zitat-Prüfergebnisse.

**Echter Quellkontext — `resolve_quote_context`** (Issue #520)

Nach `vault.add_quote(..., extraction_method="local-verbatim")` wird —
non-fatal, im Hintergrund — versucht, `context_before`/`context_after` aus
dem echten `paper_fulltext` des Papers zu befüllen (nicht mehr vom Modell
„erinnert"). Erst exakter Substring-Treffer, sonst Fuzzy-Fallback via
`rapidfuzz` (der Volltext-Extraktor kann vom Seiten-Extraktor der
Verbatim-Prüfung abweichen — Ligaturen, Trennstriche). Bei Erfolg steht
`quotes.context_source == "fulltext"`; ohne `paper_fulltext`-Eintrag oder
ohne Fundstelle bleibt alles unverändert (`None`) — geraten wird nie.

Die Funktion ist auch direkt aufrufbar:

| Funktion (Signatur mit Defaults) | Beschreibung |
|---|---|
| `resolve_quote_context(db_path, quote_id, window=600)` | Sucht die Fundstelle von `quotes.verbatim` im `paper_fulltext` des zugehörigen Papers und schneidet ±`window` Zeichen als Kontext heraus. Persistiert nur bei nachgewiesener Fundstelle (`context_source="fulltext"`), gibt `True`/`False` zurück (`False` = No-Op). Wirft `ValueError` bei unbekannter `quote_id`. |

**Prüfbilanz je Kapitel — `chapter_quote_balance`** (Issue #737)

Ein Abgabe-Check, kein Nebenprodukt eines Schreibvorgangs: `vault.chapter_quote_balance`
liest die Kapiteldatei von der Platte, findet ALLE darin belegten Vault-Zitate (über
denselben `nli_prefilter.scan_chapter_quotes`-Mechanismus wie der lokale
NLI-Vorfilter, Issue #592 — deckt das **gesamte** Kapitel ab, nicht nur die letzte
Sitzung) und bucketet jedes Zitat anhand seiner Audit-Historie:

- **geprüft & unauffällig** — `quotes.audited_at` gesetzt, letztes Urteil `faithful`.
- **Befund offen** — `audited_at` gesetzt, letztes Urteil ≠ `faithful`; erscheint mit
  Zitat, Paper und betroffener Kapitelstelle in `findings`, nach Schwere sortiert
  (`kritisch` → `hoch` → `mittel`).
- **nicht geprüft** — `audited_at` ist `NULL`. Jeder Eintrag in `not_audited` trägt
  einen `reason`; aktuell der einzige unterscheidbare Grund ist „kein
  Audit-Datensatz vorhanden" (auch für Altbestand, der vor Issue #737 bereits einen
  `stance`-Wert trug — `stance` und die Audit-Historie sind bewusst getrennte Felder,
  siehe unten).

Die drei Zähler ergeben zusammen `total_quotes`. Ein Kapitel ohne ein einziges
belegtes Zitat liefert alle Zähler als `0`, kein Fehler.

Audit-Urteile schreibt der `quote-fidelity-auditor`-Agent über das neue Tool
`vault.record_quote_audit(quote_id, verdict, severity=None)` — **additiv** zu
`vault.set_quote_stance`, nicht als dessen Ersatz: `stance` ist lossy (bei
`verdict="unsupported"` wird laut Mapping-Tabelle des Agenten gar nichts in
`stance` persistiert, und `add_quote(stance=...)` kann `stance` schon ohne jedes
Audit gesetzt sein) und kann „geprüft & unauffällig" nicht von „nie geprüft"
unterscheiden. `audited_at` ist die einzige verlässliche Grundlage dafür — der
Agent ruft beide Tools nach jedem Urteil auf, auch wenn `set_quote_stance` dabei
bewusst ausbleibt.

**Was die Bilanz nicht belegt:** Ein Verdikt `faithful` bedeutet „vom
`quote-fidelity-auditor` als unauffällig eingestuft", nicht „mit letzter
Sicherheit korrekt verwendet" — die Prüfkette selbst kann irren, und ein Zitat
ohne Audit-Datensatz ist nicht automatisch problematisch, nur ungeprüft. Die
Bilanz **priorisiert** die Prüfkette vor der Abgabe, sie **beweist nicht**, dass
geprüfte Zitate korrekt verwendet sind. Ebenfalls außerhalb ihres Umfangs: kein
automatisches Nachprüfen ungeprüfter Zitate, keine Blockade auf Basis der Zahlen
— sie stellt fest, sie handelt nicht.

**Zitat-Embeddings — `embed_quote`** (Issue #521)

Nach jedem `vault.add_quote(...)` wird — non-fatal, im Hintergrund, für ALLE
drei gültigen `extraction_method`-Werte (`citations-api`/`manual`/
`local-verbatim` gelten laut CHECK-Constraint als "bestandene Prüfung") —
versucht, ein lokales e5-Embedding aus `context_before + verbatim +
context_after` (Fallback: nur `verbatim` ohne Kontext) zu erzeugen und in die
vec0-Tabelle `quote_embeddings` zu schreiben. Billiger lokaler Vorfilter für
einen künftigen Kontexttreue-Hook — Prinzip „erst prüfen, dann vektorn":
ungeprüfte Zustände gibt es in `quotes` nicht, daher bekommt jedes gespeicherte
Zitat einen Embedding-Versuch.

Anders als `chunk_embeddings` hat `quote_embeddings` **keine
BLOB-Basistabelle**: fehlt das lokale Embedding-Backend ODER ist die
sqlite-vec-Extension in diesem Prozess nicht ladbar (z. B. macOS-System-Python
ohne `--enable-loadable-sqlite-extensions`), ist Embedding für Zitate ein
vollständiges No-Op — geloggt, kein Absturz (bewusste Scope-Entscheidung, kein
Schema-Umbau).

| Funktion (Signatur mit Defaults) | Beschreibung |
|---|---|
| `embed_quote(db_path, quote_id, embedder=None)` | Erzeugt und speichert das Embedding eines Zitats. Prüft Backend UND Extension VOR dem teuren Modell-Load. Gibt `True`/`False` zurück (`False` = Degradationspfad, geloggt). Wirft `ValueError` bei unbekannter `quote_id`. |

Bestands-Quotes ohne `quote_embeddings`-Eintrag lassen sich per Backfill
nachrüsten (idempotent — ein zweiter Lauf findet keine Kandidaten mehr):

```bash
python -m academic_vault.migrate --db ~/.academic-research/projects/<slug>/vault.db --backfill-quote-embeddings
```

**Notizen & Exzerpte** (Issue #462)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.add_note(paper_id, text, tags=None, page=None)` | Fügt ein Exzerpt zu einer Quelle hinzu; `page` optional; gibt `note_id` zurück | `vault.add_note("vaswani2017", "Kernbefund: ...", page=5)` | Bekannte `paper_id` | `note_id` der angelegten Notiz | `vault.find_notes()` gibt die Notiz nicht zurück |
| `vault.find_notes(paper_id, query=None, k=10)` | Gibt Notizen für ein Paper zurück, optional per Text-Filter (LIKE) | `vault.find_notes("vaswani2017", query="Methode")` | Bekannte `paper_id` | `list[dict]` der Notizen, optional per Text-Filter | Leere Liste — zu diesem Paper gibt es keine Notiz |
| `vault.search_notes(query, k=5)` | FTS5-Volltextsuche über alle Notizen — macht Exzerpte beim Kapitelschreiben themenbezogen auffindbar | `vault.search_notes("Reliabilität", k=5)` | Mindestens eine Notiz im Vault | `list[dict]` der FTS5-Treffer über alle Notizen | Leere Liste trotz vorhandener Notizen — der Suchbegriff steht so nicht im Notiztext |

**Eigenes Erhebungsmaterial** (Issue #473)

Transkripte liegen als `papers`-Zeile mit `source_kind='primary'` im Vault — nur so
greift dieselbe Belegkette wie bei Literaturzitaten (`quotes.paper_id`, `verbatim-guard`).
`scripts/export-literature-state.mjs` lässt Primärmaterial im Literatur-Snapshot aus.

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.add_transcript_segment(paper_id, seq, text, speaker=None, timecode=None)` | Nimmt einen Transkript-Absatz belegfähig auf; `seq` ist die zitierfähige Stellenangabe („Abs. 5"), Upsert über `UNIQUE(paper_id, seq)`; gibt `segment_id` zurück | `vault.add_transcript_segment("interview-01", 5, "Die Abstimmung ist hilfreich …", speaker="B1", timecode="00:02:41")` | Paper mit `source_kind='primary'`; `seq` ist mindestens 1 | `segment_id`; erneutes Schreiben derselben `seq` ist ein Upsert | `ValueError` „seq muss >= 1 sein" |
| `vault.list_transcript_segments(paper_id)` | Gibt alle Segmente eines Transkripts in `seq`-Reihenfolge zurück | `vault.list_transcript_segments("interview-01")` | Aufgenommenes Transkript | `list[dict]` aller Segmente in `seq`-Reihenfolge | Leere Liste — für dieses Paper wurde kein Segment aufgenommen |
| `vault.add_coding(paper_id, category, category_origin, segment_id=None, quote_id=None, memo=None)` | Ordnet einer Stelle eine Kategorie zu; `category_origin` ist Pflicht (`induktiv`/`deduktiv`); gibt `coding_id` zurück | `vault.add_coding("interview-01", "Teamabstimmung", "induktiv", quote_id="q-5")` | Nicht-leere `category`, `category_origin` ist `induktiv` oder `deduktiv` | `coding_id` der angelegten Kodierung | `ValueError` „category darf nicht leer sein" oder bei ungültiger Herkunft |
| `vault.list_codings(paper_id=None, category=None)` | Gibt Kodierungen zurück, optional nach Paper und/oder Kategorie gefiltert | `vault.list_codings(paper_id="interview-01")` | Keine; Paper und Kategorie sind optionale Filter | `list[dict]` der Kodierungen | Leere Liste — der Filter trifft keine Kodierung |

**Figures & Tabellen** (v6.1 Figure-Verifier)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.add_figure(paper_id, page=None, caption=None, vlm_description=None, data_extracted_json=None)` | Fügt Figure/Tabelle ein; gibt `figure_id` zurück | `vault.add_figure("vaswani2017", page=3, caption="Fig. 1: Architecture")` | Bekannte `paper_id` | `figure_id` der angelegten Figure | `vault.list_figures()` führt die Figure nicht auf |
| `vault.get_figure(figure_id)` | Gibt Figure-Record zurück oder `None` | `vault.get_figure("fig_7")` | Bekannte `figure_id` | `dict` mit dem Figure-Record, sonst `None` | Rückgabe `None` — die `figure_id` existiert nicht |
| `vault.list_figures(paper_id)` | Alle Figures eines Papers, nach `page` sortiert | `vault.list_figures("vaswani2017")` | Bekannte `paper_id` | `list[dict]` aller Figures, nach `page` sortiert | Leere Liste — zu diesem Paper wurde keine Figure angelegt |

**OCR-Pipeline & Seitenzählung** (v6.1)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.set_ocr_done(paper_id, value=1)` | Setzt `ocr_done`-Flag (`1`=OCR durchgeführt) | `vault.set_ocr_done("scan2019")` | Bekannte `paper_id` | Kein Rückgabewert; `ocr_done` ist danach gesetzt | `vault.get_paper()` zeigt `ocr_done` unverändert |
| `vault.update_pdf_path(paper_id, new_path)` | Aktualisiert den PDF-Pfad nach OCR | `vault.update_pdf_path("scan2019", "/data/scan2019_ocr.pdf")` | Bekannte `paper_id` und eine tatsächlich vorhandene Datei | Kein Rückgabewert; der neue Pfad gilt ab sofort für Verbatim-Prüfung und Volltext | Die nächste Verbatim-Prüfung meldet „kein lesbarer pdf_path" |
| `vault.set_page_offset(paper_id, offset)` | Setzt `page_offset` (Bücher mit Vorseiten/Vorwort) | `vault.set_page_offset("book2020", 12)` | Bekannte `paper_id` und der Versatz zwischen PDF- und Druckseite | Kein Rückgabewert; `page_offset` ist danach gesetzt | `vault.get_printed_page()` liefert weiterhin die PDF-Seite |
| `vault.get_printed_page(paper_id, pdf_page)` | Berechnet gedruckte Seite: `pdf_page - page_offset` | `vault.get_printed_page("book2020", 25)` | Gesetzter `page_offset` am Paper | `int` mit der gedruckten Seite, sonst `None` | Rückgabe `None` — das Paper ist unbekannt |
| `vault.extract_fulltext(paper_id, backend="auto")` | Extrahiert den PDF-Volltext und indiziert ihn in `papers_fts.fulltext` (#373) | `vault.extract_fulltext("vaswani2017")` | Paper mit `pdf_path`; für `backend="grobid"` zusätzlich `GROBID_URL` | `dict` mit dem Ergebnis; der Text steht danach in `paper_fulltext` und `papers_fts` | `ValueError` „Paper unbekannt" oder „hat keinen pdf_path"; ein Scan ohne Textlayer speichert bewusst nichts |
| `vault.extract_tables(paper_id, backend="auto")` | Extrahiert Tabellen strukturerhaltend nach `paper_tables`; `papers_fts` bleibt unverändert (#630). `status` ∈ `ok`/`no-tables`/`no-textlayer`/`backend-missing` | `vault.extract_tables("smith2020")` | pdfplumber installiert (Pflicht-Dependency seit #723), Paper mit `pdf_path` | `dict` mit `status` und den erkannten Tabellen in `paper_tables` | `status` ist nicht `ok`; `backend-missing` nennt im `message` die Nachinstallation |
| `vault.list_tables(paper_id, page=None)` | Gespeicherte Tabellenstrukturen eines Papers (`rows` = Textmatrix, `cells` = Zellen mit Bounding-Box) (#630) | `vault.list_tables("smith2020")` | Vorher gelaufene Tabellenextraktion | `list[dict]` mit `rows` (Textmatrix) und `cells` (Bounding-Boxen) | Leere Liste — für dieses Paper wurde keine Tabelle gespeichert |
| `vault.get_table_cell(paper_id, page, table_index, row, col)` | Eine Zelle mit `value`, `bbox` und fertigem `evidence`-Beleg; `None` statt Näherungstreffer (#630). `table_index`/`row`/`col` 0-basiert | `vault.get_table_cell("smith2020", 1, 0, 1, 1)` | Extrahierte Tabelle; `table_index`, `row` und `col` sind 0-basiert | `dict` mit `value`, `bbox` und fertigem `evidence`-Beleg | Rückgabe `None` — die Zelle gibt es nicht, ein Näherungstreffer kommt bewusst nicht |

**Decision-Log & Ausschlüsse**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.add_decision(category=None, text="", rationale=None)` | Fügt Entscheidung ins Decision-Log ein; gibt `decision_id` zurück | `vault.add_decision(category="scope", text="Nur Studien ab 2015", rationale="Aktualität")` | Vault nicht gesperrt | `decision_id` der angelegten Entscheidung | `VaultLockedError` bei gesperrtem Vault; sonst fehlt der Eintrag in `vault.list_decisions()` |
| `vault.list_decisions(category=None, active_only=True)` | Gibt Decisions zurück (optionaler `category`-Filter) | `vault.list_decisions(category="scope")` | Keine; `category` und `active_only` sind Filter | `list[dict]` der Entscheidungen | Leere Liste — der Filter trifft keine Entscheidung |
| `vault.supersede_decision(decision_id, superseded_by)` | Markiert eine Decision als abgelöst durch eine neuere (`superseded_by`) | `vault.supersede_decision("dec_3", "dec_7")` | Beide `decision_id` existieren | Kein Rückgabewert; die alte Entscheidung gilt danach als abgelöst | `vault.list_decisions()` führt sie weiterhin als aktiv |
| `vault.add_excluded_source(paper_id, reason=None)` | Fügt `paper_id` zu `excluded_sources` (verhindert Re-Vorschlag) | `vault.add_excluded_source("smith2010", reason="off-topic")` | Eine `paper_id`, die künftig nicht mehr vorgeschlagen werden soll | Kein Rückgabewert; das Paper steht danach in `excluded_sources` | `vault.is_excluded()` gibt weiterhin `False` zurück |
| `vault.is_excluded(paper_id)` | Prüft, ob `paper_id` ausgeschlossen ist | `vault.is_excluded("smith2010")` | Eine `paper_id` | `bool` — `True`, wenn das Paper ausgeschlossen ist | `False` trotz Ausschluss — der Ausschluss wurde nie geschrieben |
| `vault.list_excluded_sources()` | Gibt alle ausgeschlossenen Quellen zurück | `vault.list_excluded_sources()` | Keine — der Aufruf liest nur den Bestand | `list[dict]` aller ausgeschlossenen Quellen | Leere Liste — es wurde noch nichts ausgeschlossen |
| `vault.list_papers_by_provenance(provenance)` | Provenance-Audit: alle Papers mit gegebenem Herkunfts-Tag (z.B. `"scihub"`) | `vault.list_papers_by_provenance("scihub")` | Ein Herkunfts-Tag, etwa `"scihub"` | `list[dict]` aller Papers mit diesem Tag | Leere Liste — kein Paper trägt dieses Herkunfts-Tag |
| `vault.check_retractions(max_age_days=90, force=False, project_dir=".")` | Vault-weite Crossref-Retraction-Pruefung über alle Papers mit `source_kind='literature'` und DOI (#604); prüft nur seit `max_age_days` nicht (oder noch nie) geprüfte Papers, `force=True` erzwingt eine erneute Prüfung. Legt Treffer nur **vor** (`retracted`-Liste mit Fundstelle `source` und heuristischem `cited_in_chapter`-Flag) — schreibt **nie** automatisch nach `excluded_sources`. Papers ohne DOI landen unter `no_doi`, ein Crossref-Ausfall unter `error` (`error_count` macht einen Teilausfall sichtbar) | `vault.check_retractions(max_age_days=30)` | Papers mit DOI und `source_kind='literature'`; Crossref erreichbar | `dict` mit `retracted`, `no_doi`, `error` und `error_count` — geschrieben wird nichts | `error_count` ist größer als 0 — Crossref war ganz oder teilweise nicht erreichbar |

**Risk-of-Bias & Score-Historie** (v6.4)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.add_risk_of_bias(paper_id, study_type, domain_scores)` | Fügt RoB-Assessment ein (`domain_scores` als JSON-String); gibt `assessment_id` zurück | `vault.add_risk_of_bias("rct2018", "RCT", '{"randomization":"low"}')` | Bekannte `paper_id` und `domain_scores` als JSON-String | `assessment_id` des angelegten Assessments | `vault.list_risk_of_bias()` führt das Assessment nicht auf |
| `vault.list_risk_of_bias(paper_id=None)` | Gibt RoB-Assessments zurück (optional nach `paper_id` gefiltert) | `vault.list_risk_of_bias("rct2018")` | Keine; `paper_id` ist ein Filter | `list[dict]` der Assessments | Leere Liste — für dieses Paper wurde nie bewertet |
| `vault.add_score_snapshot(paper_id, session_id, scores)` | Fügt Score-Snapshot ein (`scores` als JSON-String); gibt `snapshot_id` zurück | `vault.add_score_snapshot("rct2018", "sess_1", '{"relevance":0.8}')` | Bekannte `paper_id`, `scores` als JSON-String | `snapshot_id` des angelegten Snapshots | `vault.get_score_history()` bleibt leer |
| `vault.get_score_history(paper_id, k=None)` | Score-History eines Papers (neueste zuerst) | `vault.get_score_history("rct2018", k=5)` | Mindestens ein Score-Snapshot zum Paper | `list[dict]`, neueste Snapshots zuerst | Leere Liste — es wurde nie ein Snapshot geschrieben |

**Material-Passport & Lock** (v6.4)

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.export_material_passport(slug, output_dir=".", score_algo_version="1.0", plugin_version="6.4")` | Exportiert `material-passport.json`; gibt Dateipfad zurück | `vault.export_material_passport("mein-projekt")` | Projekt-Slug und ein beschreibbares `output_dir` | Pfad der geschriebenen `material-passport.json` | `FEHLER:`-Meldung bei gesperrtem Vault oder nicht gefundener DB — keine Datei |
| `vault.lock_passport(slug)` | Setzt Vault-Lock für `slug` (macht Vault read-only) | `vault.lock_passport("mein-projekt")` | Zuvor exportierter Material-Passport | Kein Rückgabewert; der Vault ist danach read-only | Spätere Schreibzugriffe laufen weiter durch — der Lock wurde nicht gesetzt |
| `vault.is_locked(slug)` | Prüft, ob der Vault für `slug` gelockt ist | `vault.is_locked("mein-projekt")` | Ein Projekt-Slug | `bool` — `True`, wenn der Vault gesperrt ist | `False` trotz gesetztem Lock — dann zeigt der Aufruf auf einen anderen Slug |

**Snapshots & Backup**

| Tool (Signatur mit Defaults) | Beschreibung | Beispiel-Call | Voraussetzung | Rückgabe | Fehlschlag erkennbar an |
|------|-------------|------|---------------|----------|-------------------------|
| `vault.export_snapshot(slug, project_dir=".", snapshots_dir=None)` | Exportiert State-Dateien + Vault-DB als `.tgz`-Snapshot; gibt Pfad zurück (`snapshots_dir` default `~/.academic-research/snapshots`) | `vault.export_snapshot("mein-projekt")` | Projektverzeichnis mit State-Dateien, beschreibbares Snapshot-Verzeichnis | Pfad der `.tgz`-Datei, sonst `None` | Rückgabe `None` — es wurde kein Snapshot geschrieben |
| `vault.restore_snapshot(slug, ts, snapshots_dir=None, target_dir=".")` | Stellt Snapshot `<slug>/<ts>.tgz` wieder her; gibt `True`/`False` zurück | `vault.restore_snapshot("mein-projekt", "20260604-0930")` | Vorhandene Datei `<slug>/<ts>.tgz` | `True` bei erfolgreicher Wiederherstellung, sonst `False` | `False`, oder `ValueError` bei Symlink, absolutem Pfad oder Path-Traversal im Archiv |