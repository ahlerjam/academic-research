# Changelog

Alle bemerkenswerten Änderungen an diesem Plugin werden hier dokumentiert.

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

---

## [Unreleased]

### Added

- **Zotero-Annotation-Import (#395):** `zotero_pull.py` importiert jetzt Highlights/Notizen (Zotero-Item-Typ `annotation`), die am ersten erkannten PDF-Attachment eines Items haengen (`zot.children(att_key)`), als `vault.add_quote(..., extraction_method="manual")`. Text kommt aus `annotationText` (Fallback `annotationComment` fuer reine Notiz-Annotationen ohne markierten Text), die Seitenzahl aus `annotationPageLabel` — geparst wird ausschliesslich exakt-numerisch (`_parse_page_label`); roemische Ziffern, Bereiche oder leere Labels ergeben bewusst `printed_page = NULL` statt eines Rateversuchs. Ein Fehler bei einer einzelnen Annotation bricht den Item-Import nicht ab, sondern landet in `result.errors`; neu `ImportResult.quotes_imported`. `SKILL.md` nennt `54yyyu/zotero-mcp` (MIT, ~4,45k Stars, per `gh api` verifiziert) als optionale, nicht in `.mcp.json` eingebundene Companion-Integration. Bekannte Grenze (unveraendert vom bestehenden Attachment-Design): nur das erste PDF-Attachment pro Item wird betrachtet, Annotationen an weiteren Attachments bleiben unerfasst; bei Dedup-Kurzschluss (Paper per DOI/ISBN bereits im Vault) werden auch neue Annotationen bei Re-Imports nicht nachgezogen.

- **Claim-Drift-Warnung als additiver PreToolUse-Hook (#397):** Neuer Hook `hooks/claim-drift-guard.mjs`, in `hooks/hooks.json` **zusätzlich** zu `verbatim-guard.mjs` an `PreToolUse(Write|Edit|MultiEdit)` gehängt — die bestehende Kernlogik (Quote-/Figure-Block) bleibt unangetastet. Der `verbatim-guard` prüft, ob ein Zitat überhaupt im Vault steht; er sieht aber nicht, wenn eine spätere Überarbeitung die **Aussage um ein bereits belegtes Zitat** verändert und die alte Quellenangabe stehen lässt (aus „moderater Effekt" wird „starker Effekt", Zitat und Beleg bleiben). Verglichen werden dabei **ganze Dateistände**, nicht die Tool-Strings: Ein realistischer `Edit` trägt in `old_string`/`new_string` nur die geänderte Stelle, während Zitat und Quellenangabe ausschließlich in der Datei stehen — ein reiner String-Vergleich sähe im Fenster nie ein Zitat und bliebe stumm. Der Hook liest deshalb den Stand von Platte und rekonstruiert den neuen Stand daraus (`MultiEdit` kumulativ, ein Vergleichspaar je Teil-Edit; `Write` gegen den Dateizustand; ohne lesbaren Vorgängerstand Rückfall auf den reinen String-Vergleich). Er grenzt die Änderung über gemeinsamen Präfix/Suffix ein und warnt nur, wenn im Fenster um diese Region (Default 300 Zeichen, `CLAIM_DRIFT_WINDOW`) ein in Alt **und** Neu wörtlich identischer Zitat-Span liegt, dessen Beleg-Marker (`(Autor Jahr, S. x)`, `\cite{…}`, `[^fussnote]`, `[@citekey]`) im Fenster **um dieses Zitat** ebenfalls unverändert sind und der im Vault belegt ist. Die Beleg-Prüfung hängt bewusst am Zitat und nicht an der Änderungsregion, weil bei einem `MultiEdit` „Aussage ändern" und „Quelle nachziehen" in zwei getrennten Teil-Edits stecken; maßgeblich ist der Stand nach dem kompletten Tool-Aufruf. Der Hook **blockiert nie** (immer Exit 0, Warnung als `systemMessage` + `hookSpecificOutput.additionalContext`, bewusst ohne `permissionDecision` — er informiert, er entscheidet nicht über die Berechtigung). Gegen False Positives: Normalisierung vor dem Vergleich (reine Markdown-/Whitespace-Änderungen zählen nicht), Anker nur an unveränderten Zitaten (ein ausgetauschtes Zitat ist Sache des `verbatim-guard`), Schweigen bei mitgeänderter Quellenangabe. Der Vault-Lookup ist **tri-state** (`found`/`not-found`/`unavailable`) — anders als `lookupInVault()` im `verbatim-guard`, wo eine fehlende DB fail-open zu „gefunden" wird: für einen Warn-Check hieße das, jede Änderung ohne Datenbasis zu bemängeln, deshalb schweigt der Hook bei nicht erreichbarem Vault. Alle Kandidaten laufen in **einem** Python-Subprozess (Budget `CLAIM_DRIFT_MAX_LOOKUPS`, Default 10, Interpreter-Kaskade wie in `mid-session-reinforcement.mjs`, #382), damit das 15-s-Hook-Timeout hält. Die Warnung zitiert `context_before`/`context_after` des Vault-Zitats mit, damit direkt prüfbar ist, ob der Beleg die neue Aussage noch trägt. Konzept-Anleihe: `academic-research-skills` von Imbad0202 (CC-BY-NC-4.0, laut Digest fälschlich als MIT beworben) — übernommen wurde ausschließlich die **Idee**, kein Code von dort gelesen oder kopiert. Neu: `tests/test_issue_397_claim_drift.py` (27 Fälle, Node-Subprocess-Harness — darunter der minimale Edit gegen eine echte Datei auf Platte, sein MultiEdit-Pendant und die Gegenproben gegen False Positives) und ein eigener Abschnitt in `docs/reference/hooks.md`.
- **Optionales `stance`-Feld an Zitaten (#400):** Die `quotes`-Tabelle bekommt die Spalte `stance TEXT CHECK(stance IN ('supports','contrasts','mentions') OR stance IS NULL)`; `vault.add_quote(..., stance=None)` reicht den Wert durch, `vault.get_quote()`/`vault.find_quotes()` liefern ihn per `SELECT *` automatisch mit. Validiert wird in Python (`db.VALID_STANCES`, neue `ValueError`-Meldung mit Wertliste), damit jeder Aufrufweg dieselbe lesbare Fehlermeldung bekommt statt eines rohen `sqlite3.IntegrityError`; der CHECK-Constraint bleibt die zweite Verteidigungslinie für Direkt-Inserts. Bestands-DBs zieht der neue idempotente Helfer `migrate.add_stance_column()` nach — er hängt (anders als frühere Helfer) an einer `quotes`-Spalte, weshalb `db._LEGACY_MIGRATION_COLUMNS` jetzt eine Tabelle→Spalten-Map ist und die Verifikation vor dem `user_version`-Stempel beide Tabellen prüft (`CURRENT_SCHEMA_VERSION` 1 → 2, Muster aus #368/PR #427). **Ausdrücklich nicht enthalten:** die Klassifikation selbst. Das Feld bleibt `null`, solange es nicht manuell gesetzt wird; eine lokale NLI-Klassifikation (Konzept-Anleihe scite Smart Citations / SemanticCite — nur als Idee, keine kostenpflichtige API-Anbindung) ist ein separates Folge-Issue. Kein neues MCP-Tool (weiterhin 34).
- **Seitenbewusstes generisches Chunking-Modul (#374):** Neues Modul `academic_vault/chunking.py`, unabhängig von `scripts/chunk_pdf.py` (bleibt unverändert). `chunk_pages()` nimmt eine Liste seitenweiser Texte (`[(page_number, text), ...]`) entgegen, erkennt Section-Überschriften heuristisch per Regex (Fallback-Label `"Unbenannter Abschnitt"`, falls keine erkannt wird), und baut Sliding-Window-Chunks mit `OVERLAP_RATIO=0.125` (10–15%-Korridor); `page_start`/`page_end` werden aus den Wort→Seiten-Offsets abgeleitet. Die Chunk-Größe wird in **Modell-Tokens** bemessen, nicht in Wörtern: `intfloat/multilingual-e5-small` hat ein hartes Kontextfenster von `max_seq_length=512`, und `SentenceTransformer.encode` kürzt darüber hinausgehende Eingaben stillschweigend (gemessen: 512 Wörter ergeben 858 e5-Tokens bei englischer, 1204 bei deutscher Prosa — der Chunk-Schwanz fiele unbemerkt aus dem Vektor). `TARGET_TOKENS = MODEL_MAX_TOKENS - CONTEXT_TOKEN_RESERVE` (512 − 64 = 448) ist das Budget für den reinen Chunk-Text, sodass der vollständige Embedding-Input inklusive Kontextsatz ins Fenster passt. Gezählt wird über einen austauschbaren `token_counter`: `resolve_token_counter()` nimmt bevorzugt den echten Tokenizer des konfigurierten Embedding-Modells und fällt nur bei nicht ladbarem Tokenizer (offline CI) auf die dokumentierte Zeichen-Näherung `approximate_token_count()` zurück — mit Warnung im Log. Überschreitet ein Chunk das Fenster dennoch (einzelnes überlanges Wort), wird die sonst stille Kürzung geloggt. `chunk_pdf()` liest ein PDF seitenweise via pypdf ein (eigener, minimaler Pfad — dupliziert nicht `academic_vault/fulltext.py` aus #373, das Seiten bewusst zu einem Fließtext zusammenfasst und die Seitenzuordnung dabei aufgibt). Der Kontextsatz kommt über einen austauschbaren `context_provider`: Default ist der deterministische, offline `default_context_sentence()` (kein API-Call), optional andockbar an `academic_vault.embeddings.generate_context_sentence` (#109) via `anthropic_context_provider()`; `embedding_text` wird über das bereits vorhandene `build_contextual_embedding_text()` zusammengesetzt. Neue Fixture `tests/fixtures/chunking/multi_section_paper.pdf` (6 Seiten, 1520 global eindeutige Body-Wörter, 6 Überschriften) plus `tests/test_chunking.py` (Tests je AC, inkl. Randfälle: leerer Text, Dokument unter/exakt an/knapp über der Zielgröße).
- **Recall@k-Goldset DE/EN + Embedding-Modell-A/B (#375):** Neue Fixture `tests/fixtures/retrieval_goldset_de_en.json` (12 DE/EN-Queries, 24 Papers in 6 klar getrennten Themenclustern) plus `tests/test_vault_recall_goldset.py`: der Test baut ein echtes Fixture-Vault via `add_paper()`, injiziert den deterministischen `fake_embedder` und ruft `search_papers(..., rerank=True)` real auf — `compute_recall_at_k()` rechnet damit erstmals gegen echte Hybrid-Suchergebnisse statt synthetischer ID-Listen (Mean-Recall@10 = 0.6875, hermetisch, kein API-Key/Netz nötig). Zusätzlich vergleicht `scripts/eval/recall_at_k_model_ab.py` (manuell/einmalig ausgeführt, nicht Teil der Kernsuite) die drei Modellkandidaten e5-small/MiniLM/Qwen3-Embedding-0.6B (`truncate_dim=384`) per Cosine-Top-k auf demselben Goldset; Ergebnis dokumentiert in `docs/evals/recall-at-k-model-ab-375.md` (alle drei erreichen Recall@10 = 1.0 — Deckeneffekt des bewusst sauber getrennten Goldsets, kein Modellvergleich mit Aussagekraft; e5-small bleibt Default).
- **Crossref-Retraction-Check im Reading-List-Import (#383):** `import_reading_list()` prüft nach jedem erfolgreichen `vault.add_paper()`-Aufruf mit DOI zusätzlich `check_retraction(doi)` gegen `api.crossref.org/works/{doi}` (Feld `message.updated-by`, `type == "retraction"`; seit 09/2023 mit Retraction-Watch-Daten integriert, kostenlos, kein API-Key). Maßgeblich ist `updated-by` — Crossref hängt dieses Feld an den zurückgezogenen Artikel, während das Gegenstück `update-to` zur Retraction-Notiz gehört und von dieser auf den Artikel zeigt. Bei Treffer wird das Paper automatisch über den neuen Wrapper `vault_add_excluded_source()` als `excluded_source` markiert. Fail-safe: Netzwerk-/Parse-Fehler bei `check_retraction()` liefern `False` und blockieren den regulären Paper-Ingest nicht. Aufgezeichnete Crossref-Payloads unter `tests/fixtures/crossref/` halten beide Richtungen fest.
- **Eval-Strategie statt stillschweigender Schema-Checks (#390):** Neues Dokument `docs/evals/STRATEGY.md` benennt für jede der 37 Komponenten unter `evals/` genau einen Zustand — `metric` (Offline-Runner bewertet Inhalt), `structural` (nur Struktur geprüft, inhaltliche Bewertung skippt ohne `ANTHROPIC_API_KEY`, Begründung Pflicht) oder `removed`. Der neue Guard `tests/evals/test_eval_strategy.py` prüft die Tabelle gegen das Dateisystem (Set-Gleichheit in beide Richtungen, geschlossenes Status-Vokabular, Existenz genannter Runner) und erzwingt, dass kein Eval-Runner API-Budget verbraucht. Das Dokument beziffert den Budgetbedarf für reale Läufe (ca. 400 Aufrufe pro Vollauf) ausdrücklich als Operator-Entscheid und hält fest, dass Alt-Issue #55 von #390 absorbiert und geschlossen ist.
- **Die zwei toten Eval-Definitionen haben einen echten Ausführungspfad (#390):** `evals/humanizer-de-pipeline/runner.py` misst die Tell-Dichte (Marker aus `skills/humanizer-de/references/patterns.md` pro 100 Wörter) je Vorher/Nachher-Draft-Paar; `evals/auto-download/runner.py` prüft das Tier-Routing der 20 kuratierten Quellen gegen `resolve_pdf_url()` mit gestubbten Tier-Funktionen. Beide laufen ohne Netz und ohne API-Key, beide sind über `tests/evals/test_humanizer_pipeline_evals.py` bzw. `tests/evals/test_auto_download_routing.py` in jeden `pytest`-Lauf eingebunden. Gegen Placebo-Metriken sichern Negativkontrollen: Detection-Floor und Substanz-Quotient (Humanizer, verhindert „Reduktion durch Kürzen") sowie ein Leerlauf ohne Treffer, der `(None, None)` liefern muss (auto-download).

### Fixed

- **`openpyxl` fehlte als Dependency — `/excel` real defekt (#367):** Der vendorierte xlsx-Skill (`skills/xlsx/scripts/recalc.py`, genutzt vom Slash-Command `/excel`) braucht `openpyxl` zwingend, das Paket stand aber weder in `scripts/requirements.txt` noch in `pyproject.toml` — entgegen der Behauptung in `commands/setup.md`/`commands/excel.md`. Ein frisches Setup über den dokumentierten Weg ließ `/excel` mit `ModuleNotFoundError` scheitern. Issue #235 hatte `openpyxl` zuvor bewusst entfernt, weil kein `scripts/*.py`-Modul es importiert — der damalige Scan erfasste den Konsumenten in `skills/xlsx/` nicht; `tests/test_issue_235_unused_deps.py` prüft seither nur noch `pandas`. Neuer Regressionstest `tests/test_issue_367_openpyxl_dependency.py`. Korrektur: Der ursprüngliche Issue-Text (und dieser Eintrag) hatten `/pickup` fälschlich als mitbetroffen genannt — `/pickup` nutzt laut eigener Doku (`commands/pickup.md`) ausschließlich das externe `document-skills:xlsx`-Plugin (kein openpyxl/pandas) und konnte nie durch die fehlende Dependency scheitern; der Regressionstest sichert das jetzt ab.
- **`verbatim-guard.mjs` unterscheidet Fail-open-Fälle und loggt Bypass-Nutzung (#381):** `lookupInVault`/`lookupFigureInVault` behandelten bislang jede Exception aus dem Python-Subprozess identisch zum Fall „Vault-DB fehlt" (fail-open, gleicher Wortlaut) — ein korruptes DB-File wurde damit unsichtbar wie ein frisches Projekt ohne Vault behandelt. Neuer gemeinsamer Helper `warnFailOpen()` formuliert beide Fälle jetzt sichtbar unterschiedlich (`missing-db` vs. `lookup-error`), bleibt aber in beiden Fällen fail-open (kein Regressionsverlust bei fehlender DB). Zusätzlich nannte die Block-Message selbst den Bypass-Marker `<!-- vault-guard: skip -->` im Wortlaut — das lud zur Umgehung ein und ist entfernt (Operator-Doku bleibt einzig in `commands/latex.md`). Jede tatsächliche Nutzung des Markers wird jetzt sichtbar gemacht: stderr-Warnung plus Eintrag in `~/.academic-research/vault-guard-bypass.log` (Override via `VAULT_GUARD_BYPASS_LOG`, 0600-Rechte, best-effort — analog zu `ACADEMIC_DECISIONS_LOG`).

### Changed

- **`evals/SCHEMA.md` dokumentiert das zweite, `cases[]`-basierte Format (#390)** — `fetch`, `publisher-fetchers` (Objekt mit `cases[]`) sowie `figure-verifier` und `oa-fetchers` (Top-Level-Array ohne `component`-Feld) folgten nie dem dokumentierten `prompts[]`-Schema. Bewusst dokumentiert statt normalisiert; ein Umbau würde `tests/test_figure_verifier.py`, `tests/test_oa_fetchers.py` und `tests/test_publisher_fetchers.py` brechen, ohne die Messqualität zu erhöhen. Neu ist außerdem die `runner.py`-Konvention für `metric`-Komponenten.
- **README und `docs/evals/` sagen den Ist-Zustand offen (#390):** Der Abschnitt „Evals" nennt jetzt die tatsächliche Bilanz ohne API-Key (184 bestanden / 148 übersprungen, davon 147 API-gated; vor #390: 112 / 147) und die 3-von-37-Quote echter Offline-Metriken statt einer pauschalen Eval-Zusage. `docs/evals/v6.2-tier-eval.md` ist als historischer Report gekennzeichnet — der dort beschriebene „Eval-Lauf" war ein YAML-Dump ohne jede Prüfung.

- **PDF-Volltext im Suchindex (#373):** Neues Modul `academic_vault/fulltext.py` extrahiert den PDF-Text — pypdf als Default (offline), GROBID opt-in über `GROBID_URL` (`POST /api/processFulltextDocument`, TEI-`<text>`-Baum, Consolidation abgeschaltet) mit stillem Fallback auf pypdf. Neues MCP-Tool `vault.extract_fulltext(paper_id, backend="auto")` (jetzt 34 Tools), neue `VaultDB`-Methoden `set_fulltext()`/`get_fulltext()`/`papers_missing_fulltext()` und die idempotente Backfill-Migration `migrate.add_fulltext_support()` + `migrate.backfill_fulltext()` (CLI: `python -m academic_vault.migrate --db <pfad> --backfill-fulltext`). `vault.add_paper()` extrahiert den Volltext direkt beim Upsert (best effort, abschaltbar via `VAULT_AUTO_FULLTEXT=0`), sodass der Embedding-Ingest aus #372 den PDF-Text statt nur Titel+Abstract einbettet.
- **Lokale Embedding-Pipeline (#372):** Neues Modul `academic_vault/embedding_model.py` kapselt `intfloat/multilingual-e5-small` (MIT, 384d) inkl. der e5-Pflichtpräfixe `passage: `/`query: `, L2-Normalisierung und float32-Serialisierung. Neues Modul `academic_vault/ingest.py` verdrahtet Textquelle → Chunks → Embedding → `chunk_embeddings`; `vault.add_paper()` triggert den Ingest best effort (abschaltbar via `VAULT_AUTO_EMBED=0`).

### Dependencies

- **`voyageai`/`cohere` als optionales Extra `rerank-cloud` (#376):** `pyproject.toml` deklariert `[project.optional-dependencies].rerank-cloud` (`voyageai`, `cohere`; `uv sync --extra rerank-cloud`), bewusst getrennt von `dev`, damit die Default-CI-Installation schlank bleibt. Der lokale Reranker-Fallback (`FlagEmbedding`, `BAAI/bge-reranker-v2-m3`) ist dagegen **bewusst KEIN uv-verwaltetes Extra** (P1-Fix aus der Fixrunde zu PR #422, nach zwei gescheiterten Zwischenständen: erst als `rerank-local`-Extra, dann als globale `transformers<5.0`-Ceiling in `[project.dependencies]`) — uv löst ohne `tool.uv.conflicts` alle Extras/Gruppen GEMEINSAM zu einer universellen Version je Paket auf, ein Cap für `FlagEmbedding` (das `transformers<5.0` braucht, da `FlagEmbedding==1.4.0` intern `Tokenizer.prepare_for_model()` aufruft, entfernt in `transformers>=5.x`, verifiziert per Live-Modell-Download `AttributeError`) hätte an JEDER Stelle deklariert jede Installation heruntergezogen, auch `uv sync --extra dev` ohne den lokalen Reranker (real beobachtet: `transformers` 5.14.1→4.57.6, `huggingface-hub` 1.24.0→0.36.2 im Default-Lock). `tool.uv.conflicts` (die uv-eigene Lösung für inkompatible Extra-Versionen) verbietet dafür die gleichzeitige Installation der konfliktären Extras — genau das braucht aber der AC2-Live-Test (`dev` + lokaler Reranker zusammen). Opt-in daher nur manuell, außerhalb von uv.lock: `uv sync --extra dev && uv pip install 'FlagEmbedding>=1.3,<2.0' 'transformers<5.0'`, danach `uv run --no-sync ...` (sonst syncet uv den manuellen Downgrade weg).
- **`sentence-transformers>=3.0` ist neue Laufzeit-Abhängigkeit (#372)** — in `pyproject.toml` und `scripts/requirements.txt`. Ohne das Backend bliebe `chunk_embeddings` in jeder realen Installation leer und die Vektor-Suche wäre eine Attrappe. Torch bezieht `uv` über `[tool.uv.sources]` aus dem CPU-Index von PyTorch, damit der CUDA-Stack (mehrere GB) nicht in `uv.lock` und in jeden CI-Job wandert. Die Modellgewichte (~470 MB) werden beim ersten `add_paper()` nach `VAULT_EMBEDDING_CACHE` geladen; scheitert das, warnt der Vault im Log und läuft FTS5-only weiter.

### Changed

- **FTS5-Trigger schreiben `fulltext` nicht mehr hart auf `NULL` (#373):** `papers_ai`/`papers_au` ziehen den Volltext per Subselect aus der neuen Tabelle `paper_fulltext`, sodass er den Trigger-Rebuild bei jedem `UPDATE papers` (`set_ocr_done`, `update_pdf_path`, …) überlebt. Die Trigger werden in `schema.sql` per `DROP` + `CREATE` neu angelegt, damit `init_schema()` auch Bestands-DBs umstellt. `vault.search` nutzt `snippet(papers_fts, -1, …)` und zeigt damit die tatsächliche Fundstelle statt immer den Titel.
- **`_vec0_search` ist keine Attrappe mehr (#372):** echte KNN-Suche über die vec0-Tabelle `chunk_vectors` mit reinem Python-Fallback für Umgebungen ohne ladbare `sqlite-vec`-Extension (macOS-Matrix). Treffer werden auf Paper-Ebene aggregiert und mit Snippet an die Reciprocal-Rank-Fusion übergeben, sodass `vault.search(rerank=True)` reale Vektortreffer verarbeitet statt FTS5-Ergebnisse umzusortieren. Der Vektorpfad erhält die unsanitierte Query (FTS5-Sanitizing verfälscht die Semantik).
- `VaultDB.add_chunk_embedding()` respektiert jetzt den Material-Passport-Lock (analog #407) und spiegelt Vektoren nach `chunk_vectors`; neu sind `VaultDB.knn_chunks()`, `VaultDB.delete_chunk_embeddings()`, `VaultDB.sync_chunk_vectors()` und die idempotente Migration `migrate.add_chunk_vectors_table()` für Bestands-DBs.

### Fixed

- **Reranking war nie funktionsfähig (#376):** `apply_reranker` fing bei gesetztem `VOYAGE_API_KEY`/`COHERE_API_KEY` jede Exception mit einem stillen `except Exception: pass` — verifiziert schlug `rerank_with_voyage`/`rerank_with_cohere` sofort mit `ImportError` fehl, weil `voyageai`/`cohere` in keiner Dependency-Datei standen, ohne dass der Nutzer davon erfuhr. Behoben: benanntes Exception-Handling (`ImportError` separat + die jeweilige SDK-Fehlerbasis `voyageai.error.VoyageError`/`cohere.core.api_error.ApiError`) mit `logger.warning(...)` auf jeder Fallback-Stufe; jedes Ergebnis-Dict trägt jetzt `reranked` (bool) + `reranker` (`"voyage"`/`"cohere"`/`"local-bge"`/`"none"`). Neuer kostenfreier lokaler Fallback über `BAAI/bge-reranker-v2-m3` (Apache-2.0, FlagEmbedding), der **nur** greift, wenn beide Cloud-Keys fehlen — ein fehlgeschlagener Voyage/Cohere-Aufruf wird nicht still durch den lokalen Reranker ersetzt. `academic_vault/server.py::search_papers` ruft `apply_reranker` jetzt immer auf (statt nur bei gesetztem Cloud-Key), damit der lokale Fallback überhaupt erreichbar ist.
- **`mid-session-reinforcement.mjs` lief ins Leere (#382):** Der Hook war auf `Notification` und `PostCompact` verdrahtet — laut offizieller Claude-Code-Doku injizieren nur `UserPromptSubmit`, `UserPromptExpansion` und `SessionStart` ihr stdout tatsächlich als Modell-Kontext. Umgestellt auf `UserPromptSubmit` (Intervall-Trigger, alle ~20 Nachrichten) und `SessionStart` mit `matcher: "compact"` (Compaction-Trigger); `hooks/hooks.json` enthält damit 6 statt 7 Top-Level-Events.
- **`mid-session-reinforcement.mjs`: Intervall-Trigger feuerte auch nach dem `UserPromptSubmit`-Umbau nie (#382-Review-Nachbesserung):** Die Trigger-Bedingung hing an `input.message_count` — ein Feld, das der reale `UserPromptSubmit`-Payload von Claude Code laut Doku nicht enthält (nur `session_id`, `prompt_id`, `transcript_path`, `cwd`, `permission_mode`, `effort`, `hook_event_name`). `messageCount` blieb dadurch immer `0`, der Intervall-Pfad exitete stets ohne Ausgabe; nur der `SessionStart`/`compact`-Pfad funktionierte. Der Hook zählt jetzt seine eigenen `UserPromptSubmit`-Aufrufe persistent in der State-Datei (`prompt_count`) statt sich auf das nicht existente Feld zu verlassen — jeder Aufruf entspricht einer realen User-Message.
- **`mid-session-reinforcement.mjs`: ein Hook-Timeout fror den Intervall-Zähler dauerhaft ein (#382-Review-Nachbesserung):** Auf dem Trigger-Pfad wurde der bereits erhöhte `prompt_count` erst **nach** dem Vault-Lookup persistiert. Der Lookup blockiert pro Interpreter-Kandidat bis zu 10 s (bis zu vier Kandidaten), das `UserPromptSubmit`-Timeout in `hooks/hooks.json` beträgt 15 s — wird der Hook dabei abgeschossen, stand in der State-Datei weiterhin `TRIGGER_N-1`. Der nächste Prompt traf damit wieder den Trigger-Pfad, hing wieder, wurde wieder gekillt: der Zähler kam nie über `TRIGGER_N-1` hinaus und der teure Lookup lief ab da bei *jeder* Nachricht statt bei jeder N-ten. Der Zähler wird jetzt auf beiden Pfaden unmittelbar nach dem Inkrement gespeichert, vor dem Lookup. Preis: stirbt der Hook während des Lookups, entfällt die Erinnerung dieser Runde.
- **`mid-session-reinforcement.mjs` injizierte in echten Sessions einen leeren Hinweis (#382-Review-Nachbesserung):** Der Vault-Lookup lief über `python3` aus der `PATH`. In einer echten Session erbt der Hook die Shell-`PATH` des Nutzers, dort steht meist das System-Python (macOS: `/usr/bin/python3` == 3.9), das `academic_vault` mangels PEP-604-Syntax nicht einmal importieren kann — der Hook injizierte dann zwar Text, aber nur die leere Hülle `(keine aktiven Decisions)` trotz gefülltem Vault. In der Testsuite fiel das nie auf, weil `uv run pytest` das venv-Python an den `PATH`-Anfang stellt. Der Hook probiert jetzt der Reihe nach `$ACADEMIC_PYTHON`, `$VIRTUAL_ENV/bin/python`, `~/.academic-research/venv/bin/python` (Setup-venv) und zuletzt `python3`; scheitert alles, bleibt er fail-open.
- **AC1 von #382 ist jetzt direkt belegt statt nur aus der Doku abgeleitet:** Neues Skript `scripts/dev/verify_reinforcement_context.py` führt einen Nonce-Round-Trip gegen eine echte headless `claude -p`-Session (temporärer Vault mit gewürfeltem Marker → Hook → Modell-Antwort) und leitet die `settings.json` aus der deployten `hooks/hooks.json` ab, statt eine Attrappe zu bauen. Zusätzlich prüft es das Session-Transcript auf den `hook_success`-Eintrag. `tests/test_hook_midsession_live_context.py` prüft die Verdrahtung offline in jedem Lauf (nur Events mit echter Context-Injection, `SessionStart` nur mit `compact`-Matcher); der Live-Round-Trip ist per `ACADEMIC_LIVE_CONTEXT_TEST=1` gegated (Muster analog `VAULT_E5_LIVE_TEST`).
- **`pre-compact.mjs`: `SLUG`-Default vermischte Snapshots verschiedener Projekte (#382):** `SLUG` fiel ohne `ACADEMIC_PROJECT_SLUG` hartkodiert auf `'default'` zurück, während `DB_SLUG` bereits `basename(CLAUDE_PROJECT_DIR)` nutzte — Snapshots unterschiedlicher Projekte landeten dadurch im selben `~/.academic-research/snapshots/default/`-Ordner. `SLUG` nutzt jetzt denselben Default wie `DB_SLUG`.

---

## [6.5.1] — 2026-06-03

### Fixed

- **Vault-MCP-Server startet wieder (#217):** Drei sich gegenseitig blockierende Start-Ursachen behoben: (1) `.mcp.json` startet den Server jetzt mit der Projekt-venv (`${HOME}/.academic-research/venv/bin/python`) und setzt `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}`; (2) `mcp>=1.0` + `sqlite-vec>=0.1.0` werden über `scripts/requirements.txt` ins venv installiert; (3) Namespace-Kollision mit dem `mcp`-SDK aufgelöst — lokales Paket `mcp/academic_vault/` → `academic_vault/` (Top-Level) verschoben, alle Referenzen (`.mcp.json`, Hooks, Skills, Tests) angepasst.
- **`/history --restore` repariert (#219):** Literal-Platzhalter `<PLUGIN_ROOT>` in `commands/history.md` durch `${CLAUDE_PLUGIN_ROOT}` ersetzt — der Pfad wird nun zur Laufzeit expandiert, `import academic_vault.server` schlägt nicht mehr fehl.

## [6.5.0] — 2026-05-18

### Added

- **Contextual Retrieval (#109):** Hybrid BM25 + vec0 mit Reciprocal-Rank-Fusion (RRF). 1-Satz-Kontext-Embedding vor jedem Chunk via Anthropic Prompt-Caching (1h-TTL). `vault.search(query, rerank=true)` für optionales Reranking.
- **Reading-List-Import (#95):** Neuer Skill `reading-list-import`. Input: PDF, Markdown oder Plaintext mit Quellenliste. LLM-Parser (Sonnet) → DOI/ISBN-Resolution → Vault. AskUserQuestion bei Mehrdeutigkeit. Anystyle (Ruby) als optionales Backend.
- **LaTeX-Export (#96):** Neuer Skill `latex-export`. Markdown-Kapitel → `.tex` (Pandoc optional, fallback custom Renderer). Bibliographie → `.bib` (biblatex, DIN-1505). Per-Uni-Template-Slot: `~/.academic-research/library-profiles/<uni>.tex.template`. Neuer Command `/academic-research:latex --kapitel <n>|all --output thesis.tex`. Verbatim-Validation auch auf `*.tex`-Outputs.
- **Topic-Brainstorm (#107):** Neuer Skill `topic-brainstorm`. Trigger: *„welches Thema?"*, *„Themenfindung"*. 3–5 Kandidaten mit Feasibility/Novelty/Career-Fit-Scores, je 2–3 Forschungsfragen + 1 Pilot-Paper-Set. Übergang zu `research-question-refiner`.
- **Grant / Poster / Response (#108):** Drei neue Output-Skills (Default-Off, Opt-in via `output_targets` in `academic_context.md`):
  - `grant-proposal`: DFG/BMBF/EU-Antragsstruktur mit Vault-Quellen
  - `conference-poster`: A0-Poster (LaTeX tikzposter / PowerPoint)
  - `reviewer-response`: Point-by-point Response-Letter
- **SciHub-Tier Opt-in (#97):** Optionaler Last-Resort-Fetcher. Default DEAKTIVIERT. Aktivierung via `/academic-research:setup` → explizite Opt-in-Frage. Provenance-Tag `provenance:scihub` im Vault. Output-Hinweis *„Quelle via SciHub bezogen — bitte zusätzlich legalen Zugriff klären."*
- **README + Docs Rewrite (#98):** Kompletter README-Rewrite für v6.x (Vault, Universal Book Fetcher, humanizer-de, Per-Uni-Profile, alle v6.x-Features). Neues `CHANGELOG.md` (alle v6.x-Releases). Neues `docs/MIGRATION-v5-to-v6.md`. Glossar-Erweiterung (Vault, Subagent, Site-Profile, Material-Passport, Contextual Retrieval, RRF, CSL, humanizer-de).

### Changed

- `vault.search()` unterstützt jetzt `rerank=true` für Cohere/Voyage-Reranking.
- `skills/style-evaluator/SKILL.md`: triggert `humanizer-de` als Subagent bei `output_target ∈ {Bachelor, Master, Diplom, Dissertation}`.

---

## [6.4.0] — 2026-05-17

### Added

- **Vault-Foundation (#148):** `vault.add_decision` / `vault.list_decisions`, `vault.add_score_snapshot` / `vault.get_score_history`, `vault.add_risk_of_bias` / `vault.list_risk_of_bias`, `vault.export_snapshot` / `vault.restore_snapshot`.
- **Material-Passport (#104):** `vault.export_material_passport` / `vault.lock_passport` / `vault.is_locked`. Neuer Skill `material-passport`. Repro-Lock verhindert nachträgliche Änderungen an gesperrten Artefakten.
- **PRISMA-Flow (#92):** Neuer Skill `prisma-flow`. Mermaid-Diagramm + 27-Punkte-PRISMA-2020-Checkliste. Integration in `/search` (schreibt `n_identified`, `n_after_dedup`) und `relevance-scorer` (`excluded_screening`).
- **Meta-Analysis (#150):** Neuer Agent `meta-analysis`. DerSimonian-Laird Random-Effects-Modell. Mermaid-Forest-Plot. Output via `scripts/meta_analysis.py`.
- **Risk-of-Bias (#100):** Neuer Agent `risk-of-bias`. Cochrane RoB 2, ROBINS-I, CASP Assessment. Ergebnisse in `vault.add_risk_of_bias()`.
- **Hooks-Stack (#91, #103):** 7 Hook-Events (5 Skript-Dateien + 1 Inline-Bash):
  - `pre-compact.mjs` (`PreCompact`): Snapshot-Backup vor Claude-Compaction nach `~/.academic-research/snapshots/`.
  - `post-tool-use-decisions.mjs` (`PostToolUse(Write)`): Decision-Log für alle `*.md`-Schreiboperationen.
  - `mid-session-reinforcement.mjs` (`Notification` + `PostCompact`): Anti-Fabrikations-Erinnerung nach ~20 Nachrichten bzw. nach Compaction.
  - `verbatim-guard.mjs` (`PreToolUse(Write)`): Blockt Kapitel-Writes mit nicht-verifizierten Zitaten.
  - `onboard-project-uni-prompt.sh` (`SessionStart`): Prüft Python-venv-Bereitschaft.
  - Inline-Bash (`Stop`): Hinweis bei ungesicherten `academic_context.md`-Änderungen.
  - `/academic-research:history --restore <ts>`: Snapshot-Restore.
- **Citation-Styles MLA/Vancouver/Springer-AD (#106):** Drei neue Varianten in `citation-extraction/references/`.
- **CSL-JSON Import (#93):** Neuer Skill `citation-style-import`. Lädt beliebige `.csl`-Datei aus CSL-Repository, parst zu promptfähigen Regeln, speichert als `references/custom-<style>.md`.
- **Batch-API für Bulk-Scoring (#94):** `--batch`-Flag für `/search` und `/score`. Job-ID in `$SESSION_DIR/batch.json`. 50 % Kostenreduktion bei > 50 Papers. Pickup via `/academic-research:history --batch <id>`.
- **Interactive Search Mode (#105):** Interaktiver Modus bei `/search --interactive`: schrittweise Filter, Query-Verfeinerung, Cluster-Vorschau.
- **Cluster-Visualisierung (#132):** Mermaid-Diagramm aus 5D-Scoring-Output. Einbettbar in `kapitel/literatur.md`.

### Changed

- `tests/baselines/skill_sizes.json`: aktualisiert für neue Skills.
- `scripts/requirements.txt`: `meta_analysis`-Dependencies ergänzt (scipy, numpy).

---

## [6.3.0] — 2026-05-16

### Added

- **Zotero-Import (#143):** Neuer Skill `zotero-import`. pyzotero-Pull-only (kein Push). DOI/ISBN-basierte Dedup gegen Vault. Konfiguration via `~/.academic-research/config.yaml` (Zotero API-Key, Library-ID).
- **NotebookLM-Bundle (#144):** Neuer Skill `notebook-bundle`. Packt PDF-Bundle aus Top-N-Papers + Bibliographie als ein PDF. Unterstützt Split-Modus für einzelne Dokumente. Für Bücher > 600 Seiten als Triage-Tool. Output-Pfad-Fix: Split-Modus respektiert `output_path`-Verzeichnis.

### Notes

- NotebookLM-Bundle ist kein Zitationsweg — kein Verbatim-Garantiepfad. Nur als Exploration-Tool gedacht.

---

## [6.2.0] — 2026-05-14

Wave 1: Universal Book Fetcher — 11 PRs (Tickets #131–#141).

### Added

- **Universal Book Fetcher — Site-Subagenten (#138):** 9 Browser-Subagenten für Buch-Download:
  - `tib-fetcher`, `springer-book`, `oapen-fetcher`, `doabooks-fetcher`, `degruyter`, `nationallizenzen`, `ebook-central`, `kvk-fetcher`, `generic-fetcher`
  - Jeder Subagent kennt nur seine Site. Nur `browser-use` CLI — kein curl/wget/direktes HTTP.
- **book-fetcher Master-Agent (#137):** Orchestriert Site-Subagenten. Strategie basiert auf Input-Typ (OA, Verlags, unbekannt) und Per-Uni-Profil. Strikt sequentiell (single Browser-Session).
- **auth-helper Subagent (#136):** Gemeinsamer Auth-Agent für alle Site-Subagenten. Unterstützt HAN, Shibboleth-WAYF, EZproxy, DFN-AAI.
- **Per-Uni-Profile (#133):** `library-profiles/<uni>.yaml`. Mitgelieferte Profile: Leibniz FH, TU München, RWTH Aachen, FAU Erlangen-Nürnberg. Templates: HAN, Shibboleth, EZproxy, OA-only. Setup fragt beim Erstaufruf nach Uni.
  > Anmerkung (#387, nachträglich): Das damalige Profil-Set wurde seither ersetzt. Unter `config/library-profiles/` liegen heute `eth-zurich`, `fu-berlin`, `tum`, `uni-hamburg`, `uni-wien` — dieser historische Log-Eintrag bleibt unverändert stehen, beschreibt aber nicht mehr den aktuellen Bestand.
- **`/academic-research:fetch` Command (#140):** Parst ISBN/DOI/URL/Freitext, startet `book-fetcher`, schreibt Ergebnis in Vault. Bei `captcha`: Screenshot + User-Handoff. Bei `pickup_required`: Eintrag in Pickup-Liste.
- **`/academic-research:pickup` Command (#141):** Erzeugt Bibliotheks-Pickup-Excel aus nicht-OA-Quellen. 4 Sheets: Vor-Ort / Fernleihe / OA / Lizenz. OPAC-Standort + Code128-Barcode.
- **OA-Site-Subagenten (#134):** TIB, OAPEN, DOAB, KVK mit Tests und Evals.
- **Auto-Download-Pipeline 8-Tier (#135):** OpenAccessButton, DOAB, EuropePMC als Tiers 6–8. Ergänzt bestehende 5-Tier-Pipeline.
- **Browser-Guides (#131):** Neue Guides für TIB, OAPEN, DOAB, De Gruyter, Nationallizenzen, Ebook Central, KVK. Springer-Guide überarbeitet (Buch-Download-Block).
- **Cluster-Mermaid (#132):** Cluster-Visualisierung als Mermaid-Diagramm.

### Changed

- `config/browser_guides/springer.md`: Buch-Download-Flow ergänzt.

---

## [6.1.0] — 2026-05-13

Wave 1: Bücher, OCR, Seitenmapping, VLM, Evals — viele Features.

### Added

- **Eval-Coverage Bücher (#130):** 5 Test-Cases (1 OA, 2 ISBN-only, 1 Scan-PDF, 1 Sammelband). Token-Regression-Baseline unter `tests/evals/book-handler/`.
- **VLM Figure/Table Verification (#129):** Neuer Agent `figure-verifier`. Vault-Tools: `add_figure`, `get_figure`, `list_figures`. Verbatim-Guard prüft Abbildungsreferenzen. Eval-Skeleton mit 5 Cases.
- **Page-Mapping pdf_page → printed_page (#128):** `page_offset` in Vault. Sanity-Check über 2 Stichproben-Seiten. Unterstützung für Bücher mit Doppelpaginierung / römischen Vorseiten.
- **OCR-Detection + Trigger-Workflow (#127):** Detektion bei < 100 extrahierbaren Zeichen. `ocrmypdf`-Integration (optional). AskUserQuestion vor OCR-Start.

### Changed

- Vault: `set_ocr_done`, `update_pdf_path`, `set_page_offset`, `get_printed_page`, `add_figure`, `get_figure`, `list_figures` ergänzt.
- `skills/book-handler/SKILL.md`: Kapitel-Schnitt + Seitenmapping + OCR-Pfad integriert.

---

## [6.0.0] — 2026-05-09

Foundation-Release: Vault, Buch-Pfad, humanizer-de, Files-API.

### Added

- **Vault-MCP-Server (initial):** `mcp/academic_vault/` — SQLite mit FTS5 + sqlite-vec. Tools: `vault.search`, `vault.get_paper`, `vault.add_paper`, `vault.add_chapter`, `vault.add_quote`, `vault.find_quotes`, `vault.search_quote_text`, `vault.ensure_file`, `vault.stats`. Datenbank unter `~/.academic-research/projects/<slug>/vault.db`.
- **`book-handler` Skill:** ISBN/Titel → DNB SRU + OpenLibrary + GoogleBooks → Metadaten → OPAC-Suche → DOAB/OAPEN → Kapitel-Schnitt + OCR-Check. CSL-Felder `type: book | chapter`, `container-title`, `editor[]`, `chapter`, `page-first`, `page-last`.
- **`/academic-research:humanize` Command:** Anti-KI-Audit-Pass für Kapitel. Aktiviert `humanizer-de`-Skill im gewünschten Modus. Output: `<basename>.humanized.md` + `<basename>.diff.md`.
- **`humanizer-de`-Integration in `chapter-writer`:** Draft → `humanizer-de(audit)` → `quality-reviewer` → final.
- **`style-evaluator`-Integration:** Triggert `humanizer-de` als Subagent bei Bachelor/Master/Diplom/Dissertation.
- **Files-API für PDFs:** `vault.ensure_file()` lädt PDF zu Anthropic Files-API hoch, cached `file_id` mit TTL. `quote-extractor` nutzt `file_id` statt base64. Feature-Flag in `~/.academic-research/config.yaml`.
- **1h-TTL-Prompt-Caching:** `relevance-scorer`, `quote-extractor`, `chapter-writer`, `quality-reviewer`: `cache_control: {type: "ephemeral", ttl: "1h"}` auf System-Prompt (nach Anthropic-Default-Änderung März 2026).
- **`git init` Auto-Setup:** `/academic-research:setup` bietet optionalen `git init` + Initial-Commit der Bootstrap-Files.

### Changed

- `quote-extractor`: schreibt via `vault.add_quote()` statt JSON-Datei.
- `chapter-writer`: liest via `vault.find_quotes()` + `vault.search()`.
- `literature_state.md`: read-only Snapshot-Export aus Vault (nicht mehr Primary Source).

### Migration

- Bestehende `literature_state.md` kann via `/academic-research:setup --migrate-v5` in den Vault migriert werden.
- Vollständiger Guide: `docs/MIGRATION-v5-to-v6.md`.

---

## [5.4.0] — 2026-04-24

Finale Review-Runde gegen anthropics/skills Cookbook (Commit `5128e186`).

### Changed

- Skill-Namen auf kebab-case (alle 13 Skills): `Abstract Generator` → `abstract-generator` usw.
- `./`-Prefix für Kontext-Datei-Referenzen durchgängig.
- `## Übersicht` als erste H2 in allen 13 Skills (Cookbook-Pattern).
- Few-Shot-Beispiele (Schlecht/Gut mit Grund-Annotation) in 10 bisher few-shot-losen Skills.
- Skill-Cross-Referenzen in Prosa: Title Case → `` `kebab-case` ``.
- `chapter-writer`, `citation-extraction` Trigger erweitert.

### Fixed

- `submission-checker`: Legacy-Datei entfernt, Variant-Selector aktiviert.
- `methodology-advisor`: fehlender `## Abgrenzung`-Block ergänzt.
- `agents/query-generator.md`, `agents/relevance-scorer.md`: `tools: []` Allowlist ergänzt.
- `commands/history.md`: `disable-model-invocation: true` ergänzt.
- `agents/quality-reviewer.md`: ASCII-Umlaute → echte Umlaute.

### Removed

- `settings.json` (Root), `.mcp.json` (Root), `templates/` (Root), `config/scoring.yaml` (obsolet).

### Internal

- 2 neue Regression-Guards: `tests/test_skill_naming.py`, `tests/test_cross_references.py`.

---

## [5.3.0] — 2026-04-24

### ⚠️ BREAKING — Kontext-Ablage geändert

Der akademische Kontext wandert von Claude-Memory (`~/.claude/projects/<hash>/memory/`) in projekt-lokale Dateien (`./academic_context.md`).

### Added

- `/academic-research:setup` erweitert um Projekt-Bootstrap: leere Ordner → Facharbeit-Init; existierende Ordner → idempotent nachrüsten; Code-Repos → nur Environment-Setup.
- Generierte `CLAUDE.md` mit Skill-Delegations-Tabelle und Anti-Fabrikations-Regel.
- Migrations-Helper: `/setup` erkennt Memory-basierten Kontext, bietet Copy an.
- `scripts/project_bootstrap.py` (12 Tests in `tests/test_project_bootstrap.py`).

### Changed

- Alle 13 Skills + `query-generator`: lesen `./academic_context.md` statt Memory.

---

## [5.2.0] — 2026-04-23

### Added

- Native Citations-API in `quote-extractor`, `citation-extraction`, `chapter-writer`.
- Evals-Suite (`tests/evals/`) mit Quality-Evals und Trigger-Evals.
- `quality-reviewer`-Agent (Evaluator-Optimizer-Pattern).
- Domain-organized References in 3 Skills.
- Prompt-Caching in `relevance-scorer` + `quote-extractor`.

---

## [5.1.1] — 2026-04-23

### Fixed

- Abgrenzungs-Klauseln in 8 weiteren Skills.
- Duplikat-Precondition in `literature-gap-analysis` entfernt.
- Trigger-Überschneidung `"Forschungsfrage"` aufgelöst.

---

## [5.1.0] — 2026-04-23

### Added

- Anti-Fabrikations-Klauseln in allen 13 Skills.
- Memory-Precondition-Checks in 12 Skills.
- Few-Shot-Paare in 4 Skills.
- Skill-Abgrenzung zwischen `literature-gap-analysis` und `source-quality-audit`.
- Smoke-Test `tests/test_skills_manifest.py` (51 parametrisierte Tests).

### Changed

- Numerische Schwellen in 5 Skills (advisor, methodology-advisor, submission-checker, style-evaluator, literature-gap-analysis).
- Sprache einheitlich Deutsch in allen Skills/Commands/Agents.
- Umlaut-Varianten in allen 13 Skill-Trigger-Descriptions.

---

## [5.0.1] — 2026-04-23

### Changed

- `scripts/setup.sh` zu vollständigem One-Click-Installer ausgebaut. `browser-use` CLI Auto-Install via `uv`/`pipx`.

---

## [5.0.0] — 2026-04-23

> **⚠️ BREAKING:** Playwright → `browser-use`, Excel → `document-skills:xlsx`.

### Changed

- Browser-Automation von Playwright-MCP auf `browser-use`-CLI umgestellt.
- Excel-Generierung an externes `document-skills:xlsx`-Plugin delegiert (ab v5.5 plugin-intern vendoriert).

### Removed

- `scripts/citations.py`, `scripts/style_analysis.py`, `scripts/ranking.py`, `scripts/excel.py` gelöscht.
- Playwright-Konfiguration entfernt.

---

## [4.0.0] — vor 2026-04-23

Erstes getracktes Release. Monolithische 7-Phasen-Pipeline → 13 modulare Skills. Siehe Git-Historie für frühere Änderungen.

[6.5.0]: https://github.com/ahlerjam/academic-research/compare/v6.4.0...v6.5.0
[6.4.0]: https://github.com/ahlerjam/academic-research/compare/v6.3.0...v6.4.0
[6.3.0]: https://github.com/ahlerjam/academic-research/compare/v6.2.0...v6.3.0
[6.2.0]: https://github.com/ahlerjam/academic-research/compare/v6.1.0...v6.2.0
[6.1.0]: https://github.com/ahlerjam/academic-research/compare/v6.0.0...v6.1.0
[6.0.0]: https://github.com/ahlerjam/academic-research/compare/v5.4.0...v6.0.0
[5.4.0]: https://github.com/ahlerjam/academic-research/compare/v5.3.0...v5.4.0
[5.3.0]: https://github.com/ahlerjam/academic-research/compare/v5.2.0...v5.3.0
[5.2.0]: https://github.com/ahlerjam/academic-research/compare/v5.1.1...v5.2.0
[5.1.1]: https://github.com/ahlerjam/academic-research/compare/v5.1.0...v5.1.1
[5.1.0]: https://github.com/ahlerjam/academic-research/compare/v5.0.1...v5.1.0
[5.0.1]: https://github.com/ahlerjam/academic-research/compare/v5.0.0...v5.0.1
[5.0.0]: https://github.com/ahlerjam/academic-research/compare/v4.0.0...v5.0.0
