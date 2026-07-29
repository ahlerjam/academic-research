# Changelog

Alle bemerkenswerten Änderungen an diesem Plugin werden hier dokumentiert.

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

---

## [Unreleased]

### Added

- **Drei neue Fetcher-Agents fuer freie Archive (#450):** `hathitrust-fetcher`,
  `internetarchive-fetcher` (deckt Internet Archive UND Open Library ab) und
  `mdz-fetcher` (Muenchener Digitalisierungszentrum) erweitern die OA-Kette
  des `book-fetcher`-Master-Orchestrators um lizenzfreie Klassiker-/
  Altbestands-Quellen — sie werden in Schritt 3 vor allen Verlags-Subagenten
  abgefragt. Jeder der drei Agents fuehrt die jeweils eigene Zugriffsstufen-
  Matrix des Archivs (z.B. Vollansicht/Suche-im-Buch/nur Metadaten bei
  HathiTrust, Vollansicht/Borrow-only/nur Metadaten bei Internet Archive) und
  meldet eingeschraenkte Sichtbarkeit ueber das `reason`-Feld
  (`"Zugriffsstufe: …"`) statt einen unvollstaendigen Volltext aus
  Suchtreffern/Snippets zusammenzusetzen. Der `success`-Output traegt neu ein
  `edition`-Feld (Jahr/Ausgabe/Verlag aus dem Katalogeintrag des
  Digitalisats selbst, nie aus der Eingabe-ISBN/dem Eingabe-Titel). Das
  gesperrte 5er-Status-Enum bleibt unveraendert. Neue Browser-Guides unter
  `config/browser_guides/{hathitrust,internetarchive,mdz}.md`.

  Die Beschaffung ist ausgefuehrt geprueft, nicht nur beschrieben:
  `tests/helpers/archive_fetcher_nav.py` bildet den Weg jedes Agenten nach,
  holt die Datei ueber einen echten HTTP-Ursprung auf 127.0.0.1, verschiebt sie
  und verifiziert sie von der Platte (`%PDF-`, > 10 KB) — mit Negativkontrollen
  fuer Borrow-only, Suche-im-Buch, Nicht-PDF-Antworten und zu kleine Dateien
  (`tests/test_free_archive_download.py`). Den Stand im echten Netz haelt
  `evals/free-archive-fetchers/live-verification.json` fest: Internet Archive
  (Darwin 1859, 41.339.703 Bytes) und MDZ (Goethes Faust, Cotta 1833,
  35.191.462 Bytes) wurden am 2026-07-29 real geladen und per SHA-256 belegt;
  HathiTrust beantwortet den Gesamtband-Download mit „Page Blocked", weshalb
  dieser Agent dort `pickup_required` meldet statt `success` zu behaupten.
  Nachfahrbar mit
  `RUN_LIVE_ARCHIVE_FETCH=1 uv run pytest tests/test_free_archive_live_fetch.py`.

- **Neuer Skill `parallel-screening` + Agent `screening-judge` (#460):** Die
  gleichförmigen Schritte der Recherche — Titel-/Abstract-Screening vieler
  Treffer und Verzerrungsbewertung vieler Studien — laufen jetzt wellenweise
  über Subagents statt seriell im Dialog. Der neue `screening-judge` urteilt
  über genau einen Treffer und gibt ein festes Ein-Fall-JSON zurück
  (`include`/`exclude`/`unclear` mit Begründung, Kriterium, Beleglage); die
  Verzerrungsbewertung nutzt den bestehenden `risk-of-bias`-Agent unverändert
  weiter. Die deterministische Buchführung liegt in
  `skills/parallel-screening/scripts/screening_ledger.py`: Wellen-Planung
  gegen ein konfigurierbares Limit (Argument > `ACADEMIC_RESEARCH_MAX_PARALLEL`
  > `config/parallel_agents.json` > Default 4, harter Deckel 8), ein
  append-only Ledger `$SESSION_DIR/screening_ledger.jsonl` als Protokoll
  „welche Quelle von welchem Agent" und Resume-Basis, sowie PRISMA-Zähler
  direkt aus dem Ledger. Geschrieben wird ausschließlich in die vorhandenen
  Zielstrukturen: Ausschlüsse nach `excluded_sources` (mit Stufen-Präfix
  `screening: …`), Einschlüsse bleiben in `papers`, RoB-Bewertungen im
  bestehenden Domain-Format. Uneindeutige Fälle erreichen den Vault nie und
  werden gesammelt zur menschlichen Entscheidung vorgelegt. Resume prüft bei
  RoB zusätzlich `vault.list_risk_of_bias()`, weil `add_risk_of_bias` ein
  reines INSERT ohne Idempotenz ist.

- **Neuer Skill `extraction-matrix` für die Synthese-Phase (#463):** Zwischen
  „Quellen gesammelt" und „Kapitel geschrieben" fehlte bisher der Schritt, in
  dem Befunde über mehrere Studien hinweg vergleichbar gemacht werden. Der
  neue Skill leitet die Spalten der Extraktionsmatrix aus den
  Schlüsselkonzepten in `academic_context.md` ab, ergänzt um die
  Standardmerkmale Methode, Stichprobe, Erhebungszeitraum und Kernbefund;
  die Zeilen kommen aus dem Paper-Inventar in `literature_state.md`. Jede
  Zelle wird ausschließlich aus vorhandenen `vault.find_notes()`/
  `vault.find_quotes()`-Belegen befüllt, fehlende Angaben werden explizit als
  `— fehlend —` markiert statt ergänzt zu werden; Quellen ganz ohne Notiz
  oder Zitat bleiben als eigene Zeile mit „Grundlage fehlt"-Hinweis sichtbar
  statt zu verschwinden. Ausgabe als Markdown-Tabelle zur Übernahme in
  `kapitel/literatur.md` sowie als Arbeitsblatt über den externen
  `document-skills:xlsx`-Skill (Verfügbarkeitsprüfung + Fallback-Hinweis,
  gleiches Muster wie `commands/excel.md`). Statistische Auswertung oder
  Interpretation der Matrix bleibt explizit out of scope (Meta-Analyse-Pfad).
  Skill-Zähler 30 → 31 in `docs/reference/skills.md`, `README.md` und
  `.claude-plugin/plugin.json`.

- **SciHub-Tier still ueber das Opt-in-Flag aktiviert, Provenance bleibt aus dem Schreibkontext (#459):**
  `agents/scihub-fetcher.md` hatte bereits Opt-in-Gate und Provenance-Tagging,
  war aber in keinem Orchestrator-Pfad erreichbar — `agents/book-fetcher.md`
  kannte kein `Agent(scihub-fetcher)` (Luecke bestand bereits seit F18/#161).
  Neuer Schritt 6 in `book-fetcher.md` dispatcht `scihub-fetcher` als
  Last-Resort nach `generic-fetcher`, ausschließlich gesteuert durch
  `scihub_optin: true` im aktiven Uni-Profil — kein Laufzeit-Dialog, keine
  Rueckfrage; fehlt das Flag, wird der Agent nie aufgerufen. Der bislang bei
  jedem erfolgreichen Fund ausgegebene Warnhinweis in `scihub-fetcher.md`
  entfaellt; die rechtliche Aufklaerung bleibt einmalig beim Opt-in
  (`commands/setup.md` Schritt 8) bestehen, erfolgreiche Funde setzen nur noch
  das Vault-Tag `provenance:scihub`. `commands/fetch.md` schreibt das
  `Quelle`-Feld nicht mehr in den `literature_state.md`-Block, den
  `chapter-writer` und `citation-extraction` als Kontext lesen duerfen — beide
  Skills erhalten zusaetzlich eine explizite Provenance-Blindheits-Regel
  ("Wichtige Regeln"), damit der Beschaffungskanal Zitierweise und
  Textbehandlung nie beeinflusst. Die Herkunft bleibt vollstaendig im Vault
  nachvollziehbar (`vault.get_paper()`, `vault.list_papers_by_provenance()`,
  Anschluss an #195). Neu: `tests/test_issue_459_scihub_wiring.py`.

- **`/history` verdrahtet den Sitzungs-Index tatsächlich (#466):** Neues Modul
  `scripts/session_index.py` kapselt Lesen/Schreiben/Filtern/Wiederherstellen
  von `~/.academic-research/session_index.json` — bisher schrieb keine Stelle
  im Plugin je in diese Datei, weshalb `/history` trotz durchgeführter Suchen
  immer leer blieb. Der Index liegt bewusst außerhalb von
  `~/.academic-research/sessions/`: `score.md`/`excel.md` wählen die
  "neueste" Session per `ls -t ~/.academic-research/sessions/ | head -1`
  (sortiert nach mtime, ohne zwischen Dateien und Verzeichnissen zu
  unterscheiden); eine Geschwisterdatei dort würde als zuletzt beschriebene
  Datei jeden echten Sitzungsordner dauerhaft überholen und den
  Default-Fluss `/search` -> `/score`/`/excel` brechen (PR #486 Review,
  live reproduziert, vor Merge behoben). `commands/search.md` schreibt am
  Ende jedes Laufs (neuer Schritt 9) per `update_session_index()`/
  `build_session_entry()` einen Eintrag mit Query, Modus, Trefferzahl und
  automatisch gezählter Volltext-Anzahl (`$SESSION_DIR/pdfs/*.pdf`) fort —
  ein Upsert nach `session_path`, atomarer Write (tmp-Datei + rename).
  `commands/history.md` liest/durchsucht diesen Index jetzt über
  `load_session_index()` + `search_session_index()` statt per rohem `cat`;
  ein zwischenzeitlich gelöschter oder verschobener Sitzungsordner wird über
  `annotate_missing_sessions()` als `missing` markiert und mit
  Klartext-Hinweis ausgegeben statt einen Fehler zu werfen. Neuer Flag
  `--restore-session <id>` (bewusst anders benannt als `--restore <ts>`, das
  bereits für Snapshot-Tarballs vergeben ist) macht eine frühere Session über
  `restore_session()` wieder zum Arbeitsstand — analog zur bestehenden
  `ls -t`-Konvention aus `score.md`/`excel.md` wird dafür nur die mtime des
  Sitzungsordners aktualisiert, die Sitzungsablage selbst bleibt unangetastet
  (out of scope). Sessions aus der Zeit vor diesem Fix haben keinen
  Index-Eintrag und bleiben in `/history` unsichtbar — kein Backfill im Scope.
  Neu: `tests/test_session_index.py`.

- **`generic-fetcher` wird universeller Plattform-Navigator (#448):** `agents/generic-fetcher.md` löst die bisherige Einzelseiten-Heuristik durch ein Zustandsmodell mit genau fünf Seitenzuständen ab (`open_access`, `licensed`, `paywalled`, `login_required`, `unavailable`), je Zustand genau eine erlaubte Folgeaktion. Neu sind (a) ein **hartes Schritt-Budget** im Frontmatter (`maxSteps: 12`; jede browser-use-Aktion zählt einen Schritt, bei Erschöpfung Abbruch mit `reason: step_budget_exhausted` — der Abbruch selbst erzeugt bewusst keinen weiteren `tries`-Eintrag, weil keine Aktion mehr stattfand), (b) eine **Viewer-/Embed-Heuristik** für JavaScript-eingebettete PDFs (`Content-Type: application/pdf` nach Weiterleitung, pdf.js-`viewer.html?file=` inklusive URL-Dekodierung, `<embed type="application/pdf">`, `<object type="application/pdf">`, `#viewerContainer` mit `data-pdf-url`), (c) die **profilgesteuerte Lizenzroute**: liegt der Host in `licensed_sites`, wird `proxy_pattern` (bzw. ersatzweise `auth_url`) genutzt und der neue Innen-Status `auth_required` gemeldet, statt nach anonymen Kopien zu suchen, (d) das optionale Input-Feld `session_context` (opaker Bezeichner aus `auth-helper`), mit dem eine bestehende Browser-Session weiterverwendet wird statt eines zweiten Login-Versuchs, und (e) ein **strukturiertes `tries[]`-Protokoll**: statt Freitext-Strings jetzt ein Objekt je Aktion (`step`, `action`, `url`, `observation`, `decision`), das den gegangenen Weg maschinell nachvollziehbar macht. Das Verbots-Kapitel benennt die Scope-Grenzen des Issues ausdrücklich (kein Proxy-Hopping ohne Profil-Eintrag, keine Cookie-/Header-Manipulation, kein SciHub-Umweg — die SciHub-Logik bleibt allein beim `scihub-fetcher` —, keine direkten HTTP-Calls, keine neuen Uni-Profile, keine Credential-Verarbeitung). `agents/book-fetcher.md` reicht in Schritt 5 `session_context` durch und löst `auth_required` nach dem Muster von Schritt 4 auf: `auth-helper` → **genau ein** Retry; nach außen bleibt das Vier-Status-Enum aus `commands/fetch.md` unverändert (`auth_required` leckt nie in den Master-Output). Testbar wird das nach dem etablierten Repo-Muster von `tests/helpers/book_fetcher_router.py` über den neuen Python-Spiegel `tests/helpers/generic_fetcher_nav.py`, der gegen gespeicherte DOM-Fixtures fährt und sein Schritt-Budget aus dem Agent-Frontmatter liest; gegen Spiegel-Drift sichert `TestPromptMirrorCoupling` in beide Richtungen ab (jedes Viewer-Muster, jeder Zustand und jeder `decision`-Wert muss wörtlich im Prompt stehen — und die Zustandstabelle des Prompts darf keinen Zustand jenseits des Spiegels nennen). Vor jedem `success` steht eine **Download-Verifikation**: die Datei unter dem vom Master vorgegebenen `output_path` muss existieren, größer als null Bytes sein und mit `%PDF-` beginnen — sonst wird sie gelöscht und der Agent meldet `pickup_required` mit `decision: download_failed`. Ein Klick, der eine HTML-Fehlerseite oder eine leere Datei speichert, gilt damit als Fehlschlag statt als Volltext; `file_path` ist immer der `output_path` und nie ein selbst gewählter Ort. Die drei Plattform-Cases (Zenodo, MDPI, OpenEdition Books — je per Gegenprobe gegen `agents/` als „ohne dedizierten Agent" belegt) laufen im Test **end-to-end**: `tests/helpers/local_origin.py` serviert Plattform-DOM und PDF-Route auf 127.0.0.1, der Spiegel holt die Datei per HTTP, schreibt sie und verifiziert sie von der Platte, der Test vergleicht die geschriebenen Bytes mit den ausgelieferten. **Ehrlich benannte Grenze:** Die DOM stammt aus Fixtures und das öffentliche Netz der drei Plattformen bleibt ungetestet — der Status in `docs/evals/STRATEGY.md` bleibt deshalb `structural`, ein realer Netz-Lauf bleibt Operator-Sache wie bei `oa-fetchers`/`publisher-fetchers`. Neu: `tests/helpers/generic_fetcher_nav.py`, `tests/helpers/local_origin.py`, sieben DOM-Fixtures unter `tests/fixtures/dom_heuristics/`, zwei Mock-Fixtures unter `tests/fixtures/book_fetcher_mocks/`.

- **Anker-Paper-Survey-Modus als neuer Skill (#394):** Neuer, eigenständiger Skill `skills/anchor-paper-survey/` (30. Skill) ergänzt die themenbasierte Recherche um einen Einstiegspunkt "ich kenne bereits ein Schlüsselpaper": statt eines Themas gibt der User eine arXiv-URL/-ID oder einen lokalen PDF-Pfad an. `scripts/anchor_paper.py` löst arXiv-Eingaben über die arXiv-API auf bzw. extrahiert bei PDFs Titel/Autoren heuristisch (`scripts/pdf.py::extract_text_from_pdf` + `detect_needs_ocr` als Vorab-Guard), legt genau ein Anker-Paper via `vault.add_paper(provenance="anchor-paper")` an und stößt darauf eine Folge-Suche über die bestehenden Fetcher (`scripts/search.py::run_search`) an — Treffer werden nur angezeigt, nicht automatisch importiert (kein neuer externer Dienst, keine Zitations-Graph-DB). Ungültige Eingaben (weder arXiv-URL/-ID noch existierender Pfad) brechen mit `ValueError` ab, ohne den Vault zu verändern. Musterhinweis: Konzept-Idee lose angelehnt an `JeanDiable/academic-research-plugin` (MIT), analog zum Geschwister-Feature `github-repo-research` (#401). Neu: `tests/test_anchor_paper_survey.py`, `evals/anchor-paper-survey/`.
- **Zotero-Annotation-Import (#395):** `zotero_pull.py` importiert jetzt Highlights (Zotero-Item-Typ `annotation`), die am ersten erkannten PDF-Attachment eines Items hängen (`zot.children(att_key)`), als `vault.add_quote(..., extraction_method="manual")`. Der Zitattext stammt **ausschließlich** aus `annotationText`; `annotationComment` wird **nie** zu `quotes.verbatim` — der Kommentar ist eigener Text der forschenden Person, kein Beleg aus der Quelle. `hooks/verbatim-guard.mjs` gibt ein Kapitel-Zitat allein deshalb frei, weil `search_quote_text()` es in `quotes.verbatim` findet (LIKE-Suche ohne weiteren Diskriminator, `extraction_method` wird nicht gelesen); ein Fallback hätte die eigene Notiz damit zum vermeintlich belegten Zitat gemacht und genau die Fehlzuschreibung durchgewinkt, die der Guard verhindern soll. Zotero trennt beides selbst strikt (Note-Templates rendern `{{:highlight}}` in Anführungszeichen bzw. `<blockquote>`, `{{:comment}}` außerhalb des Zitats). Nur-Kommentar-Annotationen (Notiz-, Bild-, Ink-Typ) werden übersprungen, aber in `ImportResult.comments_skipped` gezählt und von der CLI ausgewiesen, statt still zu verschwinden. Die Seitenzahl kommt aus `annotationPageLabel` — geparst wird ausschließlich exakt-numerisch (`_parse_page_label`); römische Ziffern, Bereiche oder leere Labels ergeben bewusst `printed_page = NULL` statt eines Rateversuchs. **Idempotent auch ohne DOI/ISBN:** vor dem Einfügen liest `_existing_quote_keys()` die vorhandenen Quotes des Papers und vergleicht auf `(verbatim, printed_page)`. Nötig, weil `add_quote()` selbst nicht dedupliziert (frische `uuid4()` je Aufruf) und Items ohne Identifikator vom Paper-Dedup nicht erfasst werden — sie durchlaufen bei jedem Lauf den vollen Importpfad, während `paper_id` über den stabilen Zotero-Key konstant bleibt; ohne den Filter wüchse pro Lauf eine weitere Kopie jeder Markierung an dasselbe Paper. Derselbe Wortlaut auf verschiedenen Seiten bleibt bewusst als zwei getrennte Quotes erhalten. Ein Fehler bei einer einzelnen Annotation bricht den Item-Import nicht ab, sondern landet in `result.errors`; neu `ImportResult.quotes_imported`. Die Detaildoku (Textquelle, Seitenlabel-Tabelle, Idempotenz, Grenzen sowie `54yyyu/zotero-mcp` — MIT, ~4,45k Stars, per `gh api` verifiziert, als optionale und **nicht** in `.mcp.json` eingebundene Companion-Integration) liegt nach Progressive-Disclosure-Muster in `skills/zotero-import/references/annotations.md`; `SKILL.md` selbst nennt `54yyyu/zotero-mcp` samt MIT-Lizenzstatus zusätzlich in einer eigenen Kurzzeile (nicht nur per Link auf die Referenzdatei) und wächst dadurch insgesamt um 43 statt 1696 Zeichen. Ein Teil des Budgets kam aus Kürzungen redundanter Bestandsformulierungen; zusätzlich hebt `tests/baselines/skill_sizes.json` die zotero-import-Baseline um den Netto-Zuwachs an (4524 → 4565, Marge 1438 → 1436 Zeichen) — etabliertes, mehrfach genutztes Repo-Muster für legitimes Skill-Wachstum (vgl. 89ca331, d12a976), keine stillschweigende Aufweichung des Guards. `tokens.json` bleibt dagegen unverändert bei 781 (Ist 782, Limit 937). `test_token_reduction`/`test_token_drift_vs_baseline` bleiben damit mit realem, wenn auch knappem Puffer grün. `_parse_page_label()` prüft `str.isdecimal()` statt `str.isdigit()` (Unicode-Ziffern wie Hochstellungen liefern damit korrekt `printed_page = NULL` statt eines `ValueError`, der die ganze Annotation verworfen hätte). Neu: `tests/test_zotero_import.py::TestAnnotationDocsProgressiveDisclosure::test_skill_md_mentions_companion_with_correct_license`, ein Regressionstest für den Unicode-Seitenlabel-Fall sowie `TestAnnotationCommentIsNotVerbatim` (5 Fälle) — inklusive der Gegenprobe über `search_quote_text()`, also genau den Lookup, mit dem der `verbatim-guard` ein Kapitel-Zitat freigibt. Bekannte Grenze (unverändert vom bestehenden Attachment-Design): nur das erste PDF-Attachment pro Item wird betrachtet, Annotationen an weiteren Attachments bleiben unerfasst; bei Dedup-Kurzschluss (Paper per DOI/ISBN bereits im Vault) werden auch neue Annotationen bei Re-Imports nicht nachgezogen.
- **Claim-Drift-Warnung als additiver PreToolUse-Hook (#397):** Neuer Hook `hooks/claim-drift-guard.mjs`, in `hooks/hooks.json` **zusätzlich** zu `verbatim-guard.mjs` an `PreToolUse(Write|Edit|MultiEdit)` gehängt — die bestehende Kernlogik (Quote-/Figure-Block) bleibt unangetastet. Der `verbatim-guard` prüft, ob ein Zitat überhaupt im Vault steht; er sieht aber nicht, wenn eine spätere Überarbeitung die **Aussage um ein bereits belegtes Zitat** verändert und die alte Quellenangabe stehen lässt (aus „moderater Effekt" wird „starker Effekt", Zitat und Beleg bleiben). Verglichen werden dabei **ganze Dateistände**, nicht die Tool-Strings: Ein realistischer `Edit` trägt in `old_string`/`new_string` nur die geänderte Stelle, während Zitat und Quellenangabe ausschließlich in der Datei stehen — ein reiner String-Vergleich sähe im Fenster nie ein Zitat und bliebe stumm. Der Hook liest deshalb den Stand von Platte und rekonstruiert den neuen Stand daraus (`MultiEdit` kumulativ, ein Vergleichspaar je Teil-Edit; `Write` gegen den Dateizustand; ohne lesbaren Vorgängerstand Rückfall auf den reinen String-Vergleich). Er grenzt die Änderung über gemeinsamen Präfix/Suffix ein und warnt nur, wenn im Fenster um diese Region (Default 300 Zeichen, `CLAIM_DRIFT_WINDOW`) ein in Alt **und** Neu wörtlich identischer Zitat-Span liegt, dessen Beleg-Marker (`(Autor Jahr, S. x)`, `\cite{…}`, `[^fussnote]`, `[@citekey]`) im Fenster **um dieses Zitat** ebenfalls unverändert sind und der im Vault belegt ist. Die Beleg-Prüfung hängt bewusst am Zitat und nicht an der Änderungsregion, weil bei einem `MultiEdit` „Aussage ändern" und „Quelle nachziehen" in zwei getrennten Teil-Edits stecken; maßgeblich ist der Stand nach dem kompletten Tool-Aufruf. Der Hook **blockiert nie** (immer Exit 0, Warnung als `systemMessage` + `hookSpecificOutput.additionalContext`, bewusst ohne `permissionDecision` — er informiert, er entscheidet nicht über die Berechtigung). Gegen False Positives: Normalisierung vor dem Vergleich (reine Markdown-/Whitespace-Änderungen zählen nicht), Anker nur an unveränderten Zitaten (ein ausgetauschtes Zitat ist Sache des `verbatim-guard`), Schweigen bei mitgeänderter Quellenangabe. Der Vault-Lookup ist **tri-state** (`found`/`not-found`/`unavailable`) — anders als `lookupInVault()` im `verbatim-guard`, wo eine fehlende DB fail-open zu „gefunden" wird: für einen Warn-Check hieße das, jede Änderung ohne Datenbasis zu bemängeln, deshalb schweigt der Hook bei nicht erreichbarem Vault. Alle Kandidaten laufen in **einem** Python-Subprozess (Budget `CLAIM_DRIFT_MAX_LOOKUPS`, Default 10, Interpreter-Kaskade wie in `mid-session-reinforcement.mjs`, #382), damit das 15-s-Hook-Timeout hält. Die Warnung zitiert `context_before`/`context_after` des Vault-Zitats mit, damit direkt prüfbar ist, ob der Beleg die neue Aussage noch trägt. Konzept-Anleihe: `academic-research-skills` von Imbad0202 (CC-BY-NC-4.0, laut Digest fälschlich als MIT beworben) — übernommen wurde ausschließlich die **Idee**, kein Code von dort gelesen oder kopiert. Neu: `tests/test_issue_397_claim_drift.py` (27 Fälle, Node-Subprocess-Harness — darunter der minimale Edit gegen eine echte Datei auf Platte, sein MultiEdit-Pendant und die Gegenproben gegen False Positives) und ein eigener Abschnitt in `docs/reference/hooks.md`.
- **Optionales `stance`-Feld an Zitaten (#400):** Die `quotes`-Tabelle bekommt die Spalte `stance TEXT CHECK(stance IN ('supports','contrasts','mentions') OR stance IS NULL)`; `vault.add_quote(..., stance=None)` reicht den Wert durch, `vault.get_quote()`/`vault.find_quotes()` liefern ihn per `SELECT *` automatisch mit. Validiert wird in Python (`db.VALID_STANCES`, neue `ValueError`-Meldung mit Wertliste), damit jeder Aufrufweg dieselbe lesbare Fehlermeldung bekommt statt eines rohen `sqlite3.IntegrityError`; der CHECK-Constraint bleibt die zweite Verteidigungslinie für Direkt-Inserts. Bestands-DBs zieht der neue idempotente Helfer `migrate.add_stance_column()` nach — er hängt (anders als frühere Helfer) an einer `quotes`-Spalte, weshalb `db._LEGACY_MIGRATION_COLUMNS` jetzt eine Tabelle→Spalten-Map ist und die Verifikation vor dem `user_version`-Stempel beide Tabellen prüft (`CURRENT_SCHEMA_VERSION` 1 → 2, Muster aus #368/PR #427). **Ausdrücklich nicht enthalten:** die Klassifikation selbst. Das Feld bleibt `null`, solange es nicht manuell gesetzt wird; eine lokale NLI-Klassifikation (Konzept-Anleihe scite Smart Citations / SemanticCite — nur als Idee, keine kostenpflichtige API-Anbindung) ist ein separates Folge-Issue. Kein neues MCP-Tool (weiterhin 34).
- **Seitenbewusstes generisches Chunking-Modul (#374):** Neues Modul `academic_vault/chunking.py`, unabhängig von `scripts/chunk_pdf.py` (bleibt unverändert). `chunk_pages()` nimmt eine Liste seitenweiser Texte (`[(page_number, text), ...]`) entgegen, erkennt Section-Überschriften heuristisch per Regex (Fallback-Label `"Unbenannter Abschnitt"`, falls keine erkannt wird), und baut Sliding-Window-Chunks mit `OVERLAP_RATIO=0.125` (10–15%-Korridor); `page_start`/`page_end` werden aus den Wort→Seiten-Offsets abgeleitet. Die Chunk-Größe wird in **Modell-Tokens** bemessen, nicht in Wörtern: `intfloat/multilingual-e5-small` hat ein hartes Kontextfenster von `max_seq_length=512`, und `SentenceTransformer.encode` kürzt darüber hinausgehende Eingaben stillschweigend (gemessen: 512 Wörter ergeben 858 e5-Tokens bei englischer, 1204 bei deutscher Prosa — der Chunk-Schwanz fiele unbemerkt aus dem Vektor). `TARGET_TOKENS = MODEL_MAX_TOKENS - CONTEXT_TOKEN_RESERVE` (512 − 64 = 448) ist das Budget für den reinen Chunk-Text, sodass der vollständige Embedding-Input inklusive Kontextsatz ins Fenster passt. Gezählt wird über einen austauschbaren `token_counter`: `resolve_token_counter()` nimmt bevorzugt den echten Tokenizer des konfigurierten Embedding-Modells und fällt nur bei nicht ladbarem Tokenizer (offline CI) auf die dokumentierte Zeichen-Näherung `approximate_token_count()` zurück — mit Warnung im Log. Überschreitet ein Chunk das Fenster dennoch (einzelnes überlanges Wort), wird die sonst stille Kürzung geloggt. `chunk_pdf()` liest ein PDF seitenweise via pypdf ein (eigener, minimaler Pfad — dupliziert nicht `academic_vault/fulltext.py` aus #373, das Seiten bewusst zu einem Fließtext zusammenfasst und die Seitenzuordnung dabei aufgibt). Der Kontextsatz kommt über einen austauschbaren `context_provider`: Default ist der deterministische, offline `default_context_sentence()` (kein API-Call), optional andockbar an `academic_vault.embeddings.generate_context_sentence` (#109) via `anthropic_context_provider()`; `embedding_text` wird über das bereits vorhandene `build_contextual_embedding_text()` zusammengesetzt. Neue Fixture `tests/fixtures/chunking/multi_section_paper.pdf` (6 Seiten, 1520 global eindeutige Body-Wörter, 6 Überschriften) plus `tests/test_chunking.py` (Tests je AC, inkl. Randfälle: leerer Text, Dokument unter/exakt an/knapp über der Zielgröße).
- **Recall@k-Goldset DE/EN + Embedding-Modell-A/B (#375):** Neue Fixture `tests/fixtures/retrieval_goldset_de_en.json` (12 DE/EN-Queries, 24 Papers in 6 klar getrennten Themenclustern) plus `tests/test_vault_recall_goldset.py`: der Test baut ein echtes Fixture-Vault via `add_paper()`, injiziert den deterministischen `fake_embedder` und ruft `search_papers(..., rerank=True)` real auf — `compute_recall_at_k()` rechnet damit erstmals gegen echte Hybrid-Suchergebnisse statt synthetischer ID-Listen (Mean-Recall@10 = 0.6875, hermetisch, kein API-Key/Netz nötig). Zusätzlich vergleicht `scripts/eval/recall_at_k_model_ab.py` (manuell/einmalig ausgeführt, nicht Teil der Kernsuite) die drei Modellkandidaten e5-small/MiniLM/Qwen3-Embedding-0.6B (`truncate_dim=384`) per Cosine-Top-k auf demselben Goldset; Ergebnis dokumentiert in `docs/evals/recall-at-k-model-ab-375.md` (alle drei erreichen Recall@10 = 1.0 — Deckeneffekt des bewusst sauber getrennten Goldsets, kein Modellvergleich mit Aussagekraft; e5-small bleibt Default).
- **Crossref-Retraction-Check im Reading-List-Import (#383):** `import_reading_list()` prüft nach jedem erfolgreichen `vault.add_paper()`-Aufruf mit DOI zusätzlich `check_retraction(doi)` gegen `api.crossref.org/works/{doi}` (Feld `message.updated-by`, `type == "retraction"`; seit 09/2023 mit Retraction-Watch-Daten integriert, kostenlos, kein API-Key). Maßgeblich ist `updated-by` — Crossref hängt dieses Feld an den zurückgezogenen Artikel, während das Gegenstück `update-to` zur Retraction-Notiz gehört und von dieser auf den Artikel zeigt. Bei Treffer wird das Paper automatisch über den neuen Wrapper `vault_add_excluded_source()` als `excluded_source` markiert. Fail-safe: Netzwerk-/Parse-Fehler bei `check_retraction()` liefern `False` und blockieren den regulären Paper-Ingest nicht. Aufgezeichnete Crossref-Payloads unter `tests/fixtures/crossref/` halten beide Richtungen fest.
- **Eval-Strategie statt stillschweigender Schema-Checks (#390):** Neues Dokument `docs/evals/STRATEGY.md` benennt für jede der 37 Komponenten unter `evals/` genau einen Zustand — `metric` (Offline-Runner bewertet Inhalt), `structural` (nur Struktur geprüft, inhaltliche Bewertung skippt ohne `ANTHROPIC_API_KEY`, Begründung Pflicht) oder `removed`. Der neue Guard `tests/evals/test_eval_strategy.py` prüft die Tabelle gegen das Dateisystem (Set-Gleichheit in beide Richtungen, geschlossenes Status-Vokabular, Existenz genannter Runner) und erzwingt, dass kein Eval-Runner API-Budget verbraucht. Das Dokument beziffert den Budgetbedarf für reale Läufe (ca. 400 Aufrufe pro Vollauf) ausdrücklich als Operator-Entscheid und hält fest, dass Alt-Issue #55 von #390 absorbiert und geschlossen ist.
- **Die zwei toten Eval-Definitionen haben einen echten Ausführungspfad (#390):** `evals/humanizer-de-pipeline/runner.py` misst die Tell-Dichte (Marker aus `skills/humanizer-de/references/patterns.md` pro 100 Wörter) je Vorher/Nachher-Draft-Paar; `evals/auto-download/runner.py` prüft das Tier-Routing der 20 kuratierten Quellen gegen `resolve_pdf_url()` mit gestubbten Tier-Funktionen. Beide laufen ohne Netz und ohne API-Key, beide sind über `tests/evals/test_humanizer_pipeline_evals.py` bzw. `tests/evals/test_auto_download_routing.py` in jeden `pytest`-Lauf eingebunden. Gegen Placebo-Metriken sichern Negativkontrollen: Detection-Floor und Substanz-Quotient (Humanizer, verhindert „Reduktion durch Kürzen") sowie ein Leerlauf ohne Treffer, der `(None, None)` liefern muss (auto-download).

### Changed

- **`prisma-flow` kennt uneindeutige Fälle (#460):** `render_flow.py` liest
  optional `n_unclear_screening`. Uneindeutige Treffer zählen nicht mehr als
  Volltextkandidaten, sondern bekommen einen eigenen Knoten
  („Unklar — menschliche Entscheidung offen"). Ohne den Zähler ist der Output
  unverändert.

### Fixed

- **Download-Schritt der Archiv-Fetcher rief ein Kommando auf, das es nicht
  gibt (#450):** `hathitrust-fetcher`, `internetarchive-fetcher` und
  `mdz-fetcher` endeten — wie ihre Browser-Guides — mit
  `browser-use download <idx> --to <pfad>`. Dieses Unterkommando existiert in
  browser-use 0.12.6 nicht; der Aufruf bricht mit `invalid choice: 'download'`
  ab, es entsteht nie eine Datei. Damit konnte keiner der drei Agents je einen
  Titel beschaffen. Sie loesen den Download jetzt per `browser-use click` aus,
  holen die Datei aus dem Session-Download-Verzeichnis
  (`<TMPDIR>/browser-use-downloads-<id>/`, angelegt durch `accept_downloads` /
  `auto_download_pdfs`), verschieben sie nach `output_path` und pruefen erst
  danach. Ein Regressionstest sperrt den Fehlaufruf.
  Dieselbe Formulierung steht noch in acht weiteren Fetcher-Agents (`tib`,
  `oapen`, `doabooks`, `degruyter`, `kvk`, `springer-book`, `nationallizenzen`,
  `ebook-central`) — ausserhalb des Scopes von #450 und separat zu beheben.

- **Eval-Cases der freien Archive liessen jeden Ausgang gelten (#450):** alle
  drei Cases akzeptierten `status_in: [success, metadata_only]` und konnten
  damit nicht scheitern. Jeder Case legt sich jetzt auf genau einen Status
  fest, die beiden gemeinfreien Testtitel verlangen ein verifiziertes PDF, und
  zwei neue Gegenproben (`far-04` Borrow-only, `far-05` Suche-im-Buch) halten
  `metadata_only` davon ab, wieder zum Auffangbecken zu werden.

- **HathiTrust: eine Fehldiagnose war zum Sollverhalten geworden (#450):** Die
  vorige Runde beobachtete HTTP 403 von HathiTrust und schloss daraus, „die
  Plattform verweigert den Volltext-Download automatisierten Clients". Die
  Messung stuetzt das nicht. Der 403 trifft die **gesamte** Praesenz — auch
  `babel.hathitrust.org/robots.txt` und `www.hathitrust.org/` — und traegt
  `cf-mitigated: challenge`: es ist eine Cloudflare-Managed-Challenge gegen
  Clients ohne JavaScript, kein Download-Schutz. Ein echter Browser passiert
  sie; die Item-Seite laedt dann vollstaendig („Full View", „Public Domain.",
  630 page scans), und das Download-Formular steht von sich aus auf
  `format=pdf` + `range=volume`. Abgewiesen wird erst der Download selbst, und
  zwar mit **HTTP 429** ueber eine JSONP-Route
  (`/cgi/imgsrv/download/pdf?id=<id>&callback=tunnelCallback&_=<ts>`, als
  `<script>` geladen und deshalb in fetch-/XHR-Mitschnitten unsichtbar).
  HathiTrust beschriftet den Zustand selbst als voruebergehend („IMAGE
  TEMPORARILY UNAVAILABLE / Error code: 429", „Please try again."). Aus dem
  Fehlschluss waren drei falsche Festlegungen geworden: der Eval-Case `far-01`
  erwartete `pickup_required` und verneinte damit AC1 fuer den dritten Agenten,
  der Prompt erklaerte „regelmaessig `pickup_required` statt `success`" zum
  korrekten Ausgang, und der Navigations-Spiegel gab beim ersten Sperrsignal
  auf — bei einem Rate-Limit fuehrt das garantiert nie zu einer Datei. Jetzt:
  `far-01` verlangt `success` mit verifiziertem PDF, der neue Case `far-06`
  beschreibt den 429-Ausgang getrennt davon, und Spiegel wie Prompt fahren bis
  zu drei Versuche mit Wartezeit, bevor `pickup_required` gemeldet wird
  (`HATHITRUST_DOWNLOAD_ATTEMPTS`). Der Live-Beleg fuehrt den Lauf als
  `rate_limited` statt `blocked_by_platform` und traegt eine `mechanism_probe`,
  die 403 und 429 auseinanderhaelt. **Materieller Nebenbefund:** `robots.txt`
  fuehrt fuer `User-agent: *` genau `Crawl-delay: 1` und `Disallow: /cgi/` —
  Viewer und Download-Route liegen beide dort, `Allow` gibt es nur fuer
  benannte Suchmaschinen. Challenge und Rate-Limit sind damit die Durchsetzung
  einer erklaerten Haltung, kein Defekt; Prompt und Browser-Guide halten das
  jetzt fest (nie crawlen, nur der angefragte Titel, Crawl-delay einhalten,
  nach drei Fehlversuchen aufhoeren). AC1 ist fuer `hathitrust-fetcher`
  deshalb weiterhin **nicht live belegt** — es gibt kein PDF und folglich keine
  Pruefsumme; das bleibt eine offene Operator-Entscheidung und wird nicht durch
  einen gruenen Test verdeckt. Nebenbei korrigiert: die Fixture
  `hathitrust_full_view.html` gab sich als Live-Abzug von `hvd.hntupx` aus,
  trug aber „Leipzig : Leopold Voss, 1878", waehrend der Katalogsatz zu genau
  dieser Kennung „Berlin, G. Reimer, 1900" nennt (Bib-API, MARC 260) — der
  AC4-Teil des Spiegels pruefte damit einen erfundenen Wert gegen sich selbst.
  Neu: `tests/test_issue_450_hathitrust_ac1.py` (17 Faelle).

- **Gesamt-Zeitbudget für den Suchlauf (#465):** `run_search()` in `scripts/search.py` wartete bisher unbegrenzt über `concurrent.futures.as_completed()`, bis alle 7 Modul-Futures fertig waren — insbesondere der EconStor-OAI-PMH-Fallback aus #236 (bis zu `OAI_MAX_PAGES=5` × `TIMEOUT=30s` ≈ 150s Worst-Case, laut #456 aktuell der Live-Normalfall, da `econstor.eu`'s REST-Endpunkt durchgehend HTTP 405 liefert) konnte den gesamten Lauf um Minuten verzögern, ohne dass die übrigen, längst fertigen Treffer ausgeliefert wurden. Neuer optionaler Parameter `time_budget: float | None = None` (Default `None` reproduziert exakt das alte, unbegrenzte Verhalten) schaltet auf `concurrent.futures.wait(futures, timeout=time_budget)` um; noch nicht fertige Futures werden **nicht** per `.result()` abgewartet, sondern als „übersprungen" gewertet — getrennt von echten Modulfehlern (`skipped_out`-Ausgabeparameter statt der bestehenden `failed`-Liste, damit die 2-Tuple-Rückgabe von `run_search()` unverändert bleibt und `skills/anchor-paper-survey/scripts/anchor_paper.py`, das `run_search()` ohne `time_budget` aufruft, im alten unbegrenzten Verhalten bleibt). Der Executor wird bei gesetztem Budget per `shutdown(wait=False, cancel_futures=True)` sofort freigegeben, statt am `with`-Block-Exit doch wieder zu blockieren. `search_econstor()` bekommt zusätzlich ein eigenes, engeres `fallback_time_budget` (Default `ECONSTOR_FALLBACK_TIME_BUDGET_S = 20.0`) direkt in der resumptionToken-Schleife (`time.monotonic()`-Vergleich vor jeder weiteren Runde, analog zu den bestehenden Mengenlimits aus #236) — bei Überschreitung bricht die Schleife mit den bis dahin gesammelten Treffern ab, statt weiterzupollen; `run_search()` bindet diesen Wert über `functools.partial()` an `search_econstor()`, ohne die generische `Callable[[str, int], list[dict]]`-Signatur der `MODULES`-Registry zu ändern. Die CLI bekommt zwei neue, optionale Flags `--time-budget` (Default `DEFAULT_TIME_BUDGET_S = 60.0`) und `--fallback-time-budget` (Default `20.0`) — CLI-Läufe sind damit ab sofort standardmäßig budgetiert, programmatische Aufrufer von `run_search()` bleiben unbetroffen, solange sie `time_budget` nicht setzen. Die Sidecar-Statusdatei (`<output-stem>_status.json`, seit #456) bekommt additiv das Feld `skipped_modules`; der Exitcode-1-Fall („alle Quellen ausgefallen") berücksichtigt jetzt `failed` **und** `skipped` gemeinsam, da ein komplett übersprungener Lauf ansonsten fälschlich als Erfolg (Exitcode 0) durchgegangen wäre. Neu: `tests/test_issue_465_time_budget.py` (14 Tests: Konstanten-Existenz, Einhaltung des Gesamtbudgets mit real verzögertem Modul, getrennte Skip-vs-Fail-Kennzeichnung, Vollständigkeit der übrigen Treffer, enges EconStor-Fallback-Budget unabhängig vom Gesamtbudget, CLI-Sidecar-Statusdatei, CLI-Flag-Defaults, sowie 7× Regressionsschutz für `time_budget=None` über alle Module). `commands/search.md` dokumentiert die beiden neuen Flags und das neue Statusfeld.
- **LaTeX-Export: dokumentierte Aufrufparameter existierten nicht im Code (#467):** `commands/latex.md` dokumentierte seit Langem `--kapitel <n>|all --output <datei.tex> [--bib <datei.bib>] [--template <uni>]`, real gab es aber nur die beiden rein positionalen Skripte `render_tex.py <input.md> <output.tex>` (ein File → ein File) und `build_bib.py <vault.db> <output.bib>` (voller Vault-Dump) — keine Kapitel-Auswahl, keine Mehrfach-Kapitel-Verkettung, keine unabhängige `.bib`-Pfadsteuerung, kein Uni-Template-Wrapping. Wer den dokumentierten Aufruf 1:1 nutzte, bekam einen Fehler statt eines Exports. Neuer Orchestrator `skills/latex-export/scripts/export_thesis.py` bündelt eine echte `argparse`-CLI: `resolve_chapters()` löst `--kapitel <n>` robust gegen die im Repo uneinheitliche Namenskonvention auf (`kapitel/3.md`, `kapitel/03-methodik.md` — Matching über die führende Ziffernfolge des Dateinamens-Stamms, numerisch statt alphabetisch sortiert für `all`), mit klarer Fehlermeldung bei fehlendem oder mehrdeutigem Treffer; `apply_template()` ersetzt `%%CONTENT%%` in `~/.academic-research/library-profiles/<uni>.tex.template` und exportiert bei fehlender Vorlage trotzdem — mit erklärender Meldung („Template `<uni>` fehlt.") statt Absturz; `--bib` ist strikt unabhängig von `--output` verkabelt (Default `output/refs.bib`) und nutzt ohne expliziten Pfad den kanonischen `academic_vault.db.default_db_path()` (Issue #190). `commands/latex.md` bekommt dafür ein konkretes Schritt-für-Schritt-Ablauf-Schema (Muster aus `commands/humanize.md`/`commands/excel.md`) statt der bisherigen abstrakten Beschreibung; die für #458 gepinnte `mkdir -p ~/.academic-research/library-profiles/`-Zeile bleibt wörtlich erhalten. Neu: `tests/test_latex_export.py::TestResolveChapters`, `TestApplyTemplate`, `TestExportThesisIntegration`, `TestExportThesisCLI` (22 Fälle, je Akzeptanzkriterium mindestens ein Test). Die neue Workflow-Sektion in `skills/latex-export/SKILL.md` hebt `tests/baselines/skill_sizes.json` (3000 → 3240) und `tests/baselines/tokens.json` (360 → 459) um exakt den Netto-Zuwachs an — etabliertes Repo-Muster für legitimes Skill-Wachstum (vgl. 89ca331, d12a976), keine Aufweichung des Token-Drift-Guards.
- **Suchmodule gegen fehlerhafte Einzeldatensätze abgesichert + Parser-Tests (#456):** `scripts/search.py` fing bisher Fehler nur rund um den *kompletten* Aufruf einer `search_*`-Funktion ab (`_run_module`) — brach die Verarbeitung eines einzelnen Treffers (z. B. `int()` auf ein nicht-numerisches Datumsfeld, `.get()` auf ein Item, das kein Dict ist), verlor die gesamte Quelle alle Treffer, ohne Fehlermeldung und mit Erfolgs-Exitcode. Jede der 7 `search_*`-Funktionen (inkl. beider EconStor-Parsing-Pfade, REST und OAI-PMH-Fallback aus #236) kapselt die Verarbeitung jedes einzelnen Items jetzt in try/except: ein kaputtes Item wird geloggt und übersprungen, die übrigen Treffer bleiben erhalten. `main()` protokolliert einen Quellenausfall jetzt als `WARNING` mit den betroffenen Modulnamen (statt nur einer Zählung) und schreibt bei gesetztem `--output` zusätzlich eine Sidecar-Statusdatei `<output-stem>_status.json` (`requested_modules`, `failed_modules`, `papers_per_module`) — die von `scripts/dedup.py` konsumierte flache `--output`-Liste bleibt unverändert. Nebenbefund beim Einfrieren einer echten EconBiz-Antwort für die Parser-Tests: die API liefert inzwischen ein Elasticsearch-Envelope (`hits.hits`) statt der von `search_econbiz()` erwarteten `results`/`items`-Liste — ohne Fix wären dort dauerhaft 0 Treffer zurückgekommen, ohne jeden Fehlerhinweis (derselbe Symptomkreis wie im Issue beschrieben). `search_econbiz()` erkennt jetzt beide Formen. Zwei weitere Befunde beim Einfrieren einer echten BASE-Antwort: (1) `api.base-search.net` ist registrierungspflichtig („The interface is IP controlled or with an apikey", BASE Interface Guide v1.27) und meldet seine dokumentierten Fehler — darunter das `Access denied` für jede nicht registrierte IP — nicht per HTTP-Status, sondern mit **HTTP 200 + `{"error": ...}`**; `search_base()` fand daraufhin schlicht keine `docs` und meldete 0 Treffer als Erfolg. Das Modul erkennt den Fehler-Envelope jetzt und lässt ihn als Modulausfall sichtbar werden. (2) `search_base()` las den Abstract aus `dcabstract` — ein Feld, das BASE nicht kennt (das Abstract-Feld heißt laut Interface Guide, Appendix 2 „Fields", `dcdescription`); BASE-Treffer hatten dadurch immer `abstract=None`. Neue Fixtures unter `tests/fixtures/search/` (6 echte, per `create_fixtures.py` live abgerufene Kleinantworten; EconStor als OAI-PMH-Antwort, da der REST-Endpunkt aktuell durchgehend HTTP 405 liefert und production Code dadurch immer den Fallback nimmt). Für BASE ist ein Live-Pull mangels Registrierung in keiner unregistrierten Umgebung möglich — eingefroren ist deshalb die vom Betreiber selbst veröffentlichte PerformSearch-Antwort aus dem Interface Guide (`base_documented_response.xml`; der enthaltene Datensatz ist unabhängig gegen `pub.uni-bielefeld.de/record/2710028` gegengeprüft), aus der `create_fixtures.py::solr_xml_to_json` die JSON-Fixture mechanisch ableitet. Neu: `tests/test_search_parsers.py` (7× Positiv-Test gegen die eingefrorene Antwort, 7× Negativ-Test mit einem mutierten Item je Modul, plus Provenienz-Guard, der jede als „echt" bezeichnete Fixture an `create_fixtures.py` bindet) und `tests/test_search_error_handling.py` (Rate-Limit/Serverausfall parametrisiert über alle 7 Module, BASE-Fehler-Envelope, Sichtbarkeits- und Exitcode-Tests für Total- und Teilausfall).
- **`openpyxl` fehlte als Dependency — `/excel` real defekt (#367):** Der vendorierte xlsx-Skill (`skills/xlsx/scripts/recalc.py`, genutzt vom Slash-Command `/excel`) braucht `openpyxl` zwingend, das Paket stand aber weder in `scripts/requirements.txt` noch in `pyproject.toml` — entgegen der Behauptung in `commands/setup.md`/`commands/excel.md`. Ein frisches Setup über den dokumentierten Weg ließ `/excel` mit `ModuleNotFoundError` scheitern. Issue #235 hatte `openpyxl` zuvor bewusst entfernt, weil kein `scripts/*.py`-Modul es importiert — der damalige Scan erfasste den Konsumenten in `skills/xlsx/` nicht; `tests/test_issue_235_unused_deps.py` prüft seither nur noch `pandas`. Neuer Regressionstest `tests/test_issue_367_openpyxl_dependency.py`. Korrektur: Der ursprüngliche Issue-Text (und dieser Eintrag) hatten `/pickup` fälschlich als mitbetroffen genannt — `/pickup` nutzt laut eigener Doku (`commands/pickup.md`) ausschließlich das externe `document-skills:xlsx`-Plugin (kein openpyxl/pandas) und konnte nie durch die fehlende Dependency scheitern; der Regressionstest sichert das jetzt ab.
- **`verbatim-guard.mjs` unterscheidet Fail-open-Fälle und loggt Bypass-Nutzung (#381):** `lookupInVault`/`lookupFigureInVault` behandelten bislang jede Exception aus dem Python-Subprozess identisch zum Fall „Vault-DB fehlt" (fail-open, gleicher Wortlaut) — ein korruptes DB-File wurde damit unsichtbar wie ein frisches Projekt ohne Vault behandelt. Neuer gemeinsamer Helper `warnFailOpen()` formuliert beide Fälle jetzt sichtbar unterschiedlich (`missing-db` vs. `lookup-error`), bleibt aber in beiden Fällen fail-open (kein Regressionsverlust bei fehlender DB). Zusätzlich nannte die Block-Message selbst den Bypass-Marker `<!-- vault-guard: skip -->` im Wortlaut — das lud zur Umgehung ein und ist entfernt (Operator-Doku bleibt einzig in `commands/latex.md`). Jede tatsächliche Nutzung des Markers wird jetzt sichtbar gemacht: stderr-Warnung plus Eintrag in `~/.academic-research/vault-guard-bypass.log` (Override via `VAULT_GUARD_BYPASS_LOG`, 0600-Rechte, best-effort — analog zu `ACADEMIC_DECISIONS_LOG`).

### Changed

- **`skills/xlsx/` entvendoriert — `document-skills` als Plugin-Dependency (#445):** Die 54 Dateien der vendorierten Kopie des Claude-eigenen Excel-Skills sind aus dem Repository entfernt. Grund ist die Lizenz: die mitgelieferte `skills/xlsx/LICENSE.txt` untersagte ausdrücklich abgeleitete Werke und die Weitergabe an Dritte — genau das tat dieses MIT-lizenzierte Marketplace-Plugin, indem es die Dateien versioniert mitverteilte. An ihre Stelle tritt ein `dependencies`-Eintrag in `.claude-plugin/plugin.json` (`{ "name": "document-skills", "marketplace": "anthropic-agent-skills" }`) plus `allowCrossMarketplaceDependenciesOn: ["anthropic-agent-skills"]` in `.claude-plugin/marketplace.json`; ohne diese Allowlist verweigert Claude Code Cross-Marketplace-Dependencies mit einem `cross-marketplace`-Fehler. **Bewusst ohne `version`-Constraint:** Versionsauflösung läuft ausschließlich über Git-Tags nach dem Muster `{plugin-name}--v{version}`, und `anthropics/skills` trägt derzeit keine Tags (`gh api repos/anthropics/skills/tags` → `[]`, Marketplace-Einträge ohne `version`-Feld) — jeder Constraint liefe damit zwingend in `no-matching-tag` und deaktivierte `academic-research` komplett. `commands/excel.md` und `commands/pickup.md` teilen sich jetzt einen wortgleichen, per HTML-Kommentar abgegrenzten Herkunfts-Textbaustein (`<!-- xlsx-backend:start -->`), der Plugin, Marketplace, Upstream-Repo und den Nachinstallations-Weg (`claude plugin marketplace add anthropics/skills` → `claude plugin install document-skills@anthropic-agent-skills`) nennt und die Verfügbarkeitsprüfung **vor** den ersten Skill-Aufruf zieht — fehlt die Dependency, sieht der Nutzer diese Meldung statt eines rohen Tool-Fehlers. `commands/pickup.md` bekommt zusätzlich die bisher fehlende `Skill(document-skills:xlsx)`-Permission (dieselbe Lücke, die #223 für `/excel` schloss). **Faktenkorrektur nebenbei:** `commands/pickup.md` behauptete seit PR #141 wörtlich „kein openpyxl/pandas", und `tests/test_issue_367_openpyxl_dependency.py` zementierte diese Aussage als Guard. Sie war falsch — `/excel` und `/pickup` rufen dasselbe Backend auf, und dessen SKILL.md schreibt „pandas for data, openpyxl for formulas/formatting" und importiert `from openpyxl import Workbook`; der Skill läuft im lokalen Python-Environment des Nutzers. Beide Assertions sind entsprechend umgedreht (`test_pickup_command_doc_names_openpyxl_backed_skill`, `test_openpyxl_dependency_comments_name_the_shared_backend`), die Begründungskommentare über der `openpyxl`-Zeile in `pyproject.toml`/`scripts/requirements.txt` nennen jetzt beide Konsumenten. `openpyxl` bleibt damit unverändert Pflicht-Dependency. Nachzug: Skill-Count 30 → 29 in README-Badge, Architektur-Diagramm, Doku-Karte, beiden Manifest-`description`s, `AGENTS.md` und `docs/reference/skills.md` (Abschnitt „Vendorierte Skills" → „Externe Skills (Plugin-Dependencies)"); Ruff-`extend-exclude` für `skills/xlsx` entfernt; `"xlsx"` aus den acht Vendor-/Exempt-Sets der Testsuite gestrichen, damit dort kein toter Eintrag zurückbleibt. `tests/test_issue_240_xlsx_fourth_edition_typo.py` (prüfte einen Pfad-Tippfehler *innerhalb* der Vendor-Kopie) ist gelöscht — sein Prüfobjekt existiert nicht mehr. **Scope-Korrektur zur Issue-Beschreibung:** `.github/workflows/ci.yml` enthielt entgegen der Annahme im Issue nie einen `skills/xlsx`-Ausschluss; die Vendor-Ausnahmen standen in `pyproject.toml`, dort sind sie entfernt. **Nicht CI-prüfbar und deshalb Operator-Smoke:** dass eine frische Installation die Dependency real mitzieht (`claude plugin list --json` ohne `errors`-Feld) und dass `/academic-research:excel` weiterhin ein Workbook mit allen vier Sheets samt Cluster-Farbcodierung erzeugt — im Runner ist kein Plugin installiert. Neu: `tests/test_issue_445_xlsx_devendored.py` (14 Fälle je Akzeptanzkriterium).

- **README als Schaufenster: Positionierung nach oben, Demo, Voraussetzungstabelle (#451):** Der README-Kopf nennt jetzt innerhalb der ersten Bildschirmseite **was** das Plugin tut, **für wen** es ist und **wodurch** es sich unterscheidet — vor Zitat-Warnung und SciHub-Block. Beide Warnblöcke bleiben wortgleich erhalten (der `SCIHUB-DISCLAIMER-BLOCK` ist unangetastet, es steht nur neuer Text darüber); der bisherige Abschnitt „Für wen ist das?" ist in den Kopf gewandert statt dupliziert zu werden. Neu ist eine visuelle Demonstration: `docs/assets/quickstart.cast` (asciicast v2) trägt die Befehle und Ausgaben der Schritte 1–5 aus `docs/quickstart-protocol.md` im Wortlaut, `scripts/dev/render_quickstart_svg.py` rendert daraus deterministisch `docs/assets/quickstart.svg`. Bewusst statisch statt animiert, weil GitHubs SVG-Sanitizer den Umgang mit SMIL nicht zusichert — der Cast bleibt als abspielbare Quelle im Repo. Zwei Guards halten das Bild ehrlich: jede im Cast getippte Befehlszeile muss im Protokoll belegt sein, und das SVG wird im Test neu gerendert und byteweise verglichen. Der Quickstart bekommt eine Voraussetzungstabelle **vor** dem ersten Befehl, die erstmals **Node.js** nennt (alle Hooks sind `.mjs` und werden in `hooks/hooks.json` als `node …` gestartet — ohne Node greift der Zitat-Guard nicht) und den einmaligen Modell-Download (`intfloat/multilingual-e5-small`, ~470 MB) als eigene Zeile führt, Pflicht sauber von Optional getrennt; die Langform steht in `docs/guide/installation.md`, die README verlinkt nur. Der Suchschritt zeigt jetzt die reale Erfolgsausgabe, damit ein Erstnutzer Erfolg von Fehlschlag unterscheiden kann. Neu: `tests/test_issue_451_readme_showcase.py` — Zahlen-Guards für die bisher ungeprüften Claims (14 Quellen, 7 Browser-Module, 5 Score-Dimensionen, Python-Mindestversion, Modellgröße) hängen an ihrer jeweiligen Code-Quelle (`scripts/search.py::MODULES`, Modul-Reihenfolge in `commands/search.md`, Gewichtstabelle in `commands/score.md`, `pyproject.toml::requires-python`, `academic_vault/embedding_model.py`), nicht an einer zweiten Doku-Stelle; dazu ein Guard, der wörtlich aus `docs/reference/*` kopierte Blöcke und MCP-Toolnamen im README verbietet. Jeder dieser Guards ist per Mutation gegengeprüft. `tests/test_issue_229_arxiv_https.py` erlaubt zusätzlich den SVG-Namespace `http://www.w3.org/2000/svg` — ein Namespace-Bezeichner wie die bereits gelisteten, kein Netzwerk-Endpoint.

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
- **Setup prüft jetzt die Node.js-Laufzeit + drei Zugangsdaten-Wege sind erstmals zusammenhängend dokumentiert (#468):** `scripts/setup.sh` warnt beim Fehlen von `node` deutlich (Installationshinweis `brew install node`) statt die 5 node-abhängigen Hooks (u. a. `verbatim-guard`, `claim-drift-guard`) lautlos ausfallen zu lassen — kein harter Abbruch, da venv/Bootstrap/Uni-Profil/SciHub node-unabhängig sind. Neuer Abschnitt „Zugangsdaten" in `docs/guide/installation.md` erklärt gebündelt alle drei tatsächlich existierenden Wege (Such-API-Umgebungsvariablen, Per-Uni-Profil `credentials_keys` via `auth-helper`, HAN-Zugangsdaten-Datei für `ebscohost`/`proquest`/`opac`) statt sie über drei Dateien verstreut zu lassen, inklusive Hinweis auf die bestehende Doku-Drift bei `credentials_keys` (Schema nennt „OS-Keychain", Code liest den Wert direkt aus der YAML). `uni-profiles.md`, `search.md` und `troubleshooting.md` verlinken jetzt dorthin statt Teil-Erklärungen zu duplizieren.

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
