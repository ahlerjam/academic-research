---
description: Search academic papers across multiple APIs (Semantic Scholar, CrossRef, OpenAlex, BASE, EconBiz, EconStor, arXiv)
disable-model-invocation: true
allowed-tools: Read, Write, Bash(~/.academic-research/venv/bin/python *), Bash(browser-use:*), Bash(browser-use *), Bash(SESSION_DIR=~/.academic-research/sessions/*), Bash(mkdir -p "$SESSION_DIR/pdfs"), Agent(query-generator, relevance-scorer), AskUserQuestion
argument-hint: "<query>" [--mode quick|standard|deep|metadata] [--modules crossref,openalex,...] [--limit N] [--interactive=off]
---

# Akademische Paper-Suche

Parallele Suche über bis zu 8 API-Quellen (7 laufen automatisch je Modus, `dblp` optional per `--modules dblp`). Optional werden Queries mit dem `query-generator`-Agent erweitert.

## Verwendung

- `/academic-research:search "DevOps Governance"` — Standardsuche über alle API-Module
- `/academic-research:search "Machine Learning" --mode quick` — Schnelle Suche (4 Module)
- `/academic-research:search "IT Compliance" --mode deep` — Tiefensuche (alle Module + Portfolio-Anpassungen)
- `/academic-research:search "Cloud Computing" --modules crossref,semantic_scholar --limit 30`

## Argumente

| Argument | Default | Beschreibung |
|----------|---------|--------------|
| `query` | (erforderlich) | Suchanfrage |
| `--mode` | `standard` | quick (4 APIs), standard (7 APIs), deep (7 APIs + Portfolio), metadata (keine PDFs) |
| `--modules` | (aus Modus) | Override: kommagetrennte Modulnamen |
| `--limit` | `50` | Maximale Treffer pro Modul |
| `--no-expand` | false | `query-generator`-Agent überspringen, rohe Query nutzen |
| `--no-browser` | false | Browser-Module überspringen (nur APIs) |
| `--interactive` | `on` | Two-Phase Research Mode: Phase 1 zeigt Query-Expansion + Top-5-10-Treffer-Preview, dann Approval-Gate vor dem teuren Relevanz-Scoring. Opt-out: `--interactive=off` überspringt das Gate und liefert wie vor #537 direkt das Endergebnis. |

## Modul-Auswahl nach Modus

- **quick**: crossref, openalex, semantic_scholar, arxiv
- **standard**: crossref, openalex, semantic_scholar, base, econbiz, econstor, arxiv
- **deep**: Alle 7 API-Module + Browser-Module (Google Scholar, Springer, OECD, RePEc, OPAC)
- **metadata**: Wie standard

## Umsetzung

### Schritt 1: Session-Verzeichnis anlegen

```bash
SESSION_DIR=~/.academic-research/sessions/$(date -u +%Y-%m-%dT%H-%M-%SZ)
mkdir -p "$SESSION_DIR/pdfs"
```

Metadaten sichern:
```json
{"query": "$QUERY", "mode": "$MODE", "timestamp": "$TIMESTAMP", "modules": [...]}
```

### Schritt 2: Query-Erweiterung (falls nicht `--no-expand`)

Den `query-generator`-Agent mit der User-Query und den Ziel-Modulen starten.
Ausgabe nach `$SESSION_DIR/queries.json` speichern.

### Schritt 3: API-Suche

```bash
~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/search.py \
  --query "$QUERY" \
  --modules "$MODULES" \
  --limit $LIMIT \
  --queries-file "$SESSION_DIR/queries.json" \
  --output "$SESSION_DIR/api_results.json"
```

Neben `api_results.json` schreibt `search.py` seit #456 zusätzlich eine Sidecar-Statusdatei
`$SESSION_DIR/api_results_status.json` (`requested_modules`, `failed_modules`,
`skipped_modules`, `papers_per_module`). Fällt eine Quelle ganz oder teilweise aus, steht sie
dort explizit in `failed_modules` — bei Bedarf im Ergebnis-Digest erwähnen, statt eine
leere/kleinere Trefferzahl kommentarlos hinzunehmen.

Seit #465 hat der Gesamtlauf zusätzlich ein Zeitbudget: `--time-budget SEKUNDEN` (Default 60s)
begrenzt die Wartezeit über alle Module hinweg — eine Quelle, die das Budget überschreitet, wird
abgebrochen, ihre bis dahin gefundenen Treffer bleiben verloren (nicht: der ganze Lauf), und sie
erscheint in `skipped_modules` statt in `failed_modules` (getrennte Kennzeichnung: Zeitüberschreitung
ist kein Fehler der Quelle). `--fallback-time-budget SEKUNDEN` (Default 20s) begrenzt zusätzlich enger
den EconStor-OAI-PMH-Fallback (der REST-Endpunkt liefert aktuell durchgehend HTTP 405, der Fallback
läuft also praktisch bei jedem EconStor-Aufruf). Beide Flags sind optional; ohne sie greifen die
Default-Werte automatisch.

### Schritt 4: Browser-Suche (standard-/deep-Modus, falls nicht `--no-browser`)

Für jedes Browser-Modul in fester Reihenfolge:

1. **No-Auth zuerst:** `google_scholar` → `springer` → `oecd` → `repec`
2. **Auth danach:** `ebscohost` → `proquest` → `opac`

#### Consent-Gate vor den Auth-Modulen (Hochschul-Zugangsdaten)

Bevor das erste Auth-Modul (`ebscohost`, `proquest`, `opac`) startet, muss eine
einmalige, erklärte Zustimmung vorliegen — diese Module verwenden per
HAN-Login (`config/browser_guides/han_login.md`) Hochschul-Zugangsdaten in
Browser-Sessions gegen externe Plattformen. Es gelten dabei unverändert die
Nutzungsbedingungen von **EBSCOhost**, **ProQuest** und dem **HAN**-Proxy
deiner Hochschule.

```bash
~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/deep_search_consent.py --check
```

Gibt das Skript `no` aus (noch keine gespeicherte Zustimmung): **AskUserQuestion**-Gate mit Erklärungstext:

> Die Tiefensuche greift für EBSCOhost, ProQuest und den Hochschul-OPAC auf
> Browser-Sessions zu, die deine Hochschul-Zugangsdaten (HAN-Login) verwenden.
> Dabei gelten unverändert die Nutzungsbedingungen von EBSCOhost, ProQuest und
> dem HAN-Proxy deiner Hochschule. Zugangsdaten werden nie im Klartext an das
> LLM übergeben (siehe `auth-helper`) — sie laufen ausschließlich über lokale
> Shell-Umgebungsvariablen direkt in die Login-Formulare. Jetzt zustimmen?

Optionen:
1. **Zustimmen** — Zustimmung wird gespeichert, alle drei Auth-Module laufen wie geplant.
2. **Ablehnen** — nur `ebscohost`, `proquest` und `opac` werden für diesen Lauf übersprungen; No-Auth-Module und alle 7 API-Module laufen unverändert weiter. Keine Zustimmung wird gespeichert — die Frage erscheint beim nächsten Tiefensuche-Lauf erneut.

Bei "Zustimmen":

```bash
~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/deep_search_consent.py --record
```

Gibt der erste Check bereits `yes` aus, liegt die Zustimmung schon aus einem
früheren Lauf vor — kein erneutes Fragen, direkt weiter mit den Auth-Modulen.

Pro Modul:

1. Lies den Guide aus `${CLAUDE_PLUGIN_ROOT}/config/browser_guides/<modul>.md` (URL, Auth-Typ, Anti-Scraping-Hinweise, datenbankspezifische Fallen).
2. Bei Auth-Modulen (`ebscohost`, `proquest`, `opac`): folge zuerst `${CLAUDE_PLUGIN_ROOT}/config/browser_guides/han_login.md`.
3. Steuere den Browser über die `browser-use`-CLI. **Aufrufform, Helfer,
   Element-Adressierung und Download stehen in
   `${CLAUDE_PLUGIN_ROOT}/config/browser_guides/_cli.md`** — dort nachlesen
   statt raten. Kurz: `new_tab(<URL>)` → `wait_for_load()` → Suchfeld per
   `fill_input(<selector>, <QUERY>)` + `press_key("Enter")` → Trefferliste per
   `js(...)` auslesen. Buttons ohne stabilen Selektor über den AX-Baum
   (`Accessibility.getFullAXTree` → `DOM.getBoxModel` → `click_at_xy`).
   - Bei Bedarf paginieren — maximal 2 Seiten pro Modul
4. Ergebnisse ins `api_results.json`-Schema normalisieren (`title`, `authors`, `year`, `venue`, `doi`, `url`, `source_module`, `snippet`) und an die bestehende Ergebnisliste anhängen.
5. Fehlerbehandlung:
   - CAPTCHA erkannt → `capture_screenshot(path=…)`, User informieren, Teilergebnisse behalten.
   - Login schlägt fehl → Modul überspringen, Warnung loggen, mit nächstem Modul weitermachen.
   - Rate-Limit → 30s Pause, einmal wiederholen, dann Modul überspringen.

Ergebnisse an `$SESSION_DIR/api_results.json` anhängen.

### Schritt 5: Deduplikation

```bash
~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/dedup.py \
  --papers "$SESSION_DIR/api_results.json" \
  --output "$SESSION_DIR/deduped.json"
```

### Schritt 6: Known-Item-Suche (#886)

Die thematischen Queries treffen strukturbedingt oft nicht die benannten
Grundlagenarbeiten eines Feldes — wer nach „multi-agent coordination failure
modes" sucht, findet nicht „MetaGPT". Dieser Schritt sucht deshalb gezielt
nach benannten Werken, statt sich auf die thematische Suche zu verlassen.

```bash
~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/known_item_search.py \
  --deduped "$SESSION_DIR/deduped.json" \
  --queries-file "$SESSION_DIR/queries.json" \
  --modules crossref,openalex \
  --report-output "$SESSION_DIR/known_item_report.json"
```

Kandidaten kommen aus zwei Quellen:

1. **`known_works_queries`** aus `$SESSION_DIR/queries.json` (vom
   `query-generator`, Schritt 2) — Titelsuchen nach seminalen Werken mit
   Begründung.
2. **Zitationsheuristik** — die meistzitierten Treffer der bisherigen
   thematischen Suche als Titel-Query, plus deren häufigste gemeinsame
   OpenAlex-`referenced_works` (eng begrenzter Lookup auf wenige Top-Treffer,
   **kein** vollständiges Snowballing über die ganze Menge — das ist ein
   eigener Arbeitsschritt und bewusst Out-of-Scope).

Fällt die Query-Erweiterung aus (#881: `queries.json` fehlt oder
`known_works_queries` ist leer), läuft der Schritt trotzdem — nur eben
ausschließlich mit der Zitationsheuristik. `known_item_report.json` nennt in
diesem Fall den Grund explizit im Feld `fallback_reason`.

Treffer werden mit `found_via_known_item: true` markiert, an
`$SESSION_DIR/deduped.json` angehängt und `dedup.py` erneut darüber laufen
gelassen (idempotent) — die Markierung übersteht dabei auch einen Merge mit
einem unmarkierten thematischen Duplikat (Konsolidierungsregel analog
`is_retracted`, #618).

Der Schritt meldet immer, wonach er gesucht hat (`searched_for` in
`known_item_report.json`) und was er gefunden hat (`found` je Kandidat) —
**auch ein Nulltreffer ist ein valides, gemeldetes Ergebnis**: er sagt etwas
über das Feld aus (z. B. weil eine Titel-Query gegen die Volltextsuche der
Module nicht exakt genug matcht) und darf nicht als „Werk existiert nicht"
fehlinterpretiert werden.

Im Report/Digest ausweisen:

1. Wonach gesucht wurde (Kandidaten-Queries + Quelle: `known_works_queries`
   vs. Zitationsheuristik).
2. Was gefunden wurde, inkl. expliziter Nulltreffer.
3. Bei Fallback: den Grund aus `fallback_reason`.

### Schritt 7: Vorranking (4D `prescore` + Cluster)

An dieser Stelle gibt es noch **keine** Relevanzbewertung — die entsteht erst in
Schritt 11. Ein Ranking, das sie hier schon bräuchte, würde mit einer Zahl
rechnen, die es noch nicht gibt (#892). Darum rechnet dieser Schritt ein
Vorranking aus den vier *gerechneten* Dimensionen (Aktualität, Qualität,
Autorität, Zugang), deren Gewichte auf 1.0 renormiert sind:

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/scripts/scoring.py prescore '<paper-json>' [current_year]
```

`scripts/scoring.py` → `prescore()` / `prescore_paper()`. Der Wert wird je
Treffer als Feld `prescore` in `$SESSION_DIR/ranked.json` geschrieben,
Clusterzuweisung wie in `commands/score.md`. Alles Weitere bis Schritt 11
sortiert nach `prescore`.

Der gewichtete Gesamtscore über alle fünf Dimensionen (`scoring.total_score()`,
siehe `commands/score.md`) entsteht erst in Schritt 10, sobald die Relevanz
tatsächlich vorliegt.

### Schritt 8: Interactive Mode — Phase 1 (Approval-Gate, Default)

Dieses Gate läuft **standardmäßig** — es steht bewusst vor Schritt 10, damit der
User Query-Expansion und Trefferlage sieht, bevor das teure LLM-Relevanz-Scoring
startet. Die Vorschau ordnet nach `prescore` aus Schritt 7 (`run_interactive_phase1`
fällt auf ein altes `score`-Feld zurück, falls die `ranked.json` aus einem Lauf vor
#892 stammt).

Gate-freie Pfade (Schritt komplett überspringen, direkt weiter mit Schritt 9):

- `--interactive=off` — das dokumentierte Opt-out, stellt das Verhalten vor #537 her.
- Nicht-interaktive bzw. headless Läufe (kein `AskUserQuestion`-Kanal verfügbar,
  z. B. CI oder Automatisierung): kein Gate, sonst würde der Lauf blockieren.

Sonst Preview aufbauen:

```bash
~/.academic-research/venv/bin/python -c "
import json, sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from search import run_interactive_phase1
papers = json.load(open('$SESSION_DIR/ranked.json'))
preview = run_interactive_phase1(papers, query='$QUERY', n_preview=5)
print(json.dumps(preview, ensure_ascii=False, indent=2))
"
```

Anzeigen:

1. Die in Schritt 2 expandierten Queries aus `$SESSION_DIR/queries.json`
   (bei `--no-expand`: die rohe User-Query) — damit sichtbar ist, wonach
   tatsächlich gesucht wurde.
2. Die Top-5-10-Treffer aus dem Preview als formatierte Tabelle. Treffer mit
   `is_retracted: true` erhalten eine sichtbare Markierung (z. B. Spalte/Badge
   „⚠ Retracted") — **vor** dem Screening, damit niemand eine zurückgezogene
   Arbeit unwissentlich mitscreent (#618). `is_retracted: false` bleibt
   unmarkiert, `is_retracted` fehlend/`null` ebenfalls unmarkiert und darf
   NICHT wie „nicht zurückgezogen" dargestellt werden — die Drei-Werte-Semantik
   (zurückgezogen / nicht zurückgezogen / unbekannt) muss in der Tabelle
   erkennbar bleiben. Treffer mit `found_via_known_item: true` (Schritt 6)
   erhalten ein sichtbares Badge „🎯 Known-Item" in derselben Tabelle, damit
   erkennbar bleibt, welche Treffer aus der gezielten Suche nach
   Grundlagenarbeiten stammen statt aus der thematischen Suche.

Dann **Approval-Gate via `AskUserQuestion`**:

Optionen:
1. **Weiter** — Phase 2 starten (Deep-Investigation)
2. **Anders formulieren** — neue Query eingeben und ab Schritt 2 wiederholen
3. **Mehr Quellen** — zusätzliche Module hinzufügen und ab Schritt 3 wiederholen
4. **Modul-Wahl ändern** — andere API-Module wählen und ab Schritt 3 wiederholen

Bei "Weiter": Phase 2 (Deep-Investigation) starten = vollständiges Scoring + Kapitelplanung.

### Schritt 9: Mechanischer Vorfilter

Was die Ein-/Ausschlusskriterien **eindeutig** entscheiden, entscheidet ein
Kriterienabgleich — nicht das Modell. Eine Arbeit, die den Zeitraum, die
Sprache oder den Publikationstyp verfehlt, kostet damit keinen Modellaufruf
(#892):

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/screening_prefilter.py \
  prefilter --session-dir "$SESSION_DIR" \
  --papers "$SESSION_DIR/ranked.json" \
  --context ./academic_context.md \
  --db-path "$VAULT_DB"
```

Der Schritt liest den eingezäunten `screening_filters`-Block aus der Section
`### Ein-/Ausschlusskriterien` von `./academic_context.md` (geschrieben vom
`preregistration`-Skill) und schreibt zwei Dateien:

- `$SESSION_DIR/to_screen.json` — die verbleibende Menge, absteigend nach
  `prescore` sortiert. Bei knappem Budget wird damit das Aussichtsreichste
  zuerst bewertet.
- `$SESSION_DIR/prefilter_report.json` — Trefferzahl und Batchzahl **vor und
  nach** dem Filter plus die Aufschlüsselung je Kriterium. Diese Zahlen gehören
  in den Ergebnis-Digest.

Jeder mechanische Ausschluss steht danach mit Kriteriumsnamen im Grund im
Ledger (`decided_by: "rule"`) und in `excluded_sources` — mechanische und
Modell-Ausschlüsse liegen im selben Protokoll, aus dem Schritt 11 die
PRISMA-Zähler zieht.

Fail-open, in beide Richtungen:

- **Kein Filterblock in `./academic_context.md`** → No-Op, der Lauf verhält sich
  exakt wie vor #892. Nichts wird erfunden: der Vorfilter schließt nur an
  Grenzen aus, die ausdrücklich in den Kriterien stehen.
- **Fehlt einem Treffer das geprüfte Metadatum** (kein `year`, keine `language`,
  kein `publication_type`) → er wird **nicht** ausgeschlossen, sondern dem
  Modell vorgelegt. Unwissen ist kein Ausschlussgrund.

Abschaltbar per `--no-prefilter` bzw. `screening_prefilter: false` in
`config/parallel_agents.json`.

### Schritt 10: Relevanz-Scoring

Den `relevance-scorer`-Agent in Batches von 10 Papers starten. Grundlage ist die
Restmenge aus `$SESSION_DIR/to_screen.json`, in deren `prescore`-Reihenfolge:
Was der Vorfilter in Schritt 9 bereits entschieden hat, taucht hier nicht mehr
auf (`screening_ledger.pending()` überspringt protokollierte IDs). Läuft das
Screening über den `parallel-screening`-Skill, kommt die Wellenplanung von dort.

Erst hier existiert die Relevanz — und erst hier entsteht der gewichtete
Gesamtscore über alle fünf Dimensionen (`scoring.total_score()`), der das
Vorranking aus Schritt 7 ablöst. Top-N nach Modus wählen (quick=15,
standard=25, deep=40). Als `$SESSION_DIR/papers.json` speichern.

Das Scoring läuft vollständig in der Sitzung, ohne eigenen Modellzugang und
ohne asynchrone Abholung (#632).

### Schritt 11: PRISMA-Zähler speichern

Die Zähler kommen aus dem Ausschlussprotokoll, nicht aus einer getrennt
geführten Zählung — mechanische Ausschlüsse aus Schritt 9 und Modell-Urteile
aus Schritt 10 stehen beide im selben Ledger (#892):

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/screening_ledger.py \
  counters --session-dir "$SESSION_DIR" --n-identified "${N_IDENTIFIED}" \
  > "$SESSION_DIR/prisma_counters.json"
```

**Fallback** — nur wenn gar kein Ledger existiert (das Screening lief weder über
den Vorfilter noch über `parallel-screening`), die Handzählung:

```bash
~/.academic-research/venv/bin/python -c "
import json, sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from search import build_prisma_counters, save_prisma_counters
counters = build_prisma_counters(
    n_identified=${N_IDENTIFIED},
    n_after_dedup=${N_AFTER_DEDUP},
    n_excluded_screening=${N_EXCLUDED_SCREENING},
    n_excluded_eligibility=${N_EXCLUDED_ELIGIBILITY},
    n_included=${N_INCLUDED},
)
save_prisma_counters('$SESSION_DIR', counters)
"
```

Die Zähler werden in beiden Fällen in `$SESSION_DIR/prisma_counters.json`
gespeichert.

### Schritt 12: Session-Index aktualisieren

Damit `/history` diesen Lauf findet, wird die Session am Ende jedes Suchlaufs
im Index unter `~/.academic-research/session_index.json` fortgeschrieben
(Upsert per Session-Pfad). Der Index liegt bewusst **nicht** unter
`~/.academic-research/sessions/` — dieses Verzeichnis lesen `score.md`/
`excel.md` per `ls -t ... | head -1`, und eine Geschwisterdatei dort würde
als jeweils zuletzt beschriebene Datei jeden echten Sitzungsordner dauerhaft
überholen (PR #486 Review, #466):

```bash
~/.academic-research/venv/bin/python -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from session_index import DEFAULT_INDEX_PATH, build_session_entry, update_session_index
entry = build_session_entry(
    '$SESSION_DIR',
    query='$QUERY',
    mode='$MODE',
    n_hits=${N_HITS},
)
update_session_index(DEFAULT_INDEX_PATH, entry)
"
```

`N_HITS` ist die Anzahl der final in `$SESSION_DIR/papers.json` enthaltenen
Paper (fällt das Scoring aus, ersatzweise `$SESSION_DIR/ranked.json`). Die
Anzahl beschaffter Volltexte wird automatisch aus `$SESSION_DIR/pdfs/*.pdf`
gezählt.

### Schritt 13: Ergebnisse anzeigen

Eine formatierte Tabelle mit Rang, Titel, Jahr, Score, Cluster und Quellmodul ausgeben.
Treffer mit `is_retracted: true` wie in Schritt 8 sichtbar markieren („⚠ Retracted");
`is_retracted: false` unmarkiert, fehlend/`null` ebenfalls unmarkiert und nicht als
„nicht zurückgezogen" ausweisen (#618). Der Hinweis führt zu keinem automatischen
Ausschluss — die Entscheidung trifft der Mensch. Treffer mit
`found_via_known_item: true` erhalten dasselbe „🎯 Known-Item"-Badge wie in
Schritt 8 (#886).
Pfad des Session-Verzeichnisses melden.

Die Kontext-Datei `./literature_state.md` im Projekt-Ordner mit neuen Statistiken aktualisieren, falls akademischer Kontext vorliegt.
