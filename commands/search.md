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
3. Steuere den Browser mit dem globalen `browser-use`-Skill (CLI-basiert, index-orientiert, keine CSS-Selektoren):
   - `browser-use open <URL>` — Seite laden
   - `browser-use state` — klickbare Elemente mit Index abrufen
   - Query-Feld per Index identifizieren: `browser-use input <idx> "<QUERY>"`
   - Suche auslösen (Enter oder Submit-Button per Index klicken): `browser-use click <idx>`
   - Nach Warten auf Laden: `browser-use state` erneut, um Ergebnislisten auszulesen
   - Bei Bedarf paginieren — maximal 2 Seiten pro Modul
4. Ergebnisse ins `api_results.json`-Schema normalisieren (`title`, `authors`, `year`, `venue`, `doi`, `url`, `source_module`, `snippet`) und an die bestehende Ergebnisliste anhängen.
5. Fehlerbehandlung:
   - CAPTCHA erkannt → `browser-use screenshot` machen, User informieren, Teilergebnisse behalten.
   - Login schlägt fehl → Modul überspringen, Warnung loggen, mit nächstem Modul weitermachen.
   - Rate-Limit → 30s Pause, einmal wiederholen, dann Modul überspringen.

Ergebnisse an `$SESSION_DIR/api_results.json` anhängen.

### Schritt 5: Deduplikation

```bash
~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/dedup.py \
  --papers "$SESSION_DIR/api_results.json" \
  --output "$SESSION_DIR/deduped.json"
```

### Schritt 6: Ranking (5D-Scoring + Cluster)

Die Heuristik-Dimensionen (Aktualität, Qualität, Autorität, Zugang) werden direkt in diesem Command berechnet — siehe Formeln in `commands/score.md` → „4 weitere Dimensionen berechnen". Gesamtscore wie dort, Clusterzuweisung ebenfalls. Das Resultat in `$SESSION_DIR/ranked.json` schreiben.

### Schritt 7: Interactive Mode — Phase 1 (Approval-Gate, Default)

Dieses Gate läuft **standardmäßig** — es steht bewusst vor Schritt 9, damit der
User Query-Expansion und Trefferlage sieht, bevor das teure LLM-Relevanz-Scoring
startet.

Gate-freie Pfade (Schritt komplett überspringen, direkt weiter mit Schritt 8):

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
2. Die Top-5-10-Treffer aus dem Preview als formatierte Tabelle.

Dann **Approval-Gate via `AskUserQuestion`**:

Optionen:
1. **Weiter** — Phase 2 starten (Deep-Investigation)
2. **Anders formulieren** — neue Query eingeben und ab Schritt 2 wiederholen
3. **Mehr Quellen** — zusätzliche Module hinzufügen und ab Schritt 3 wiederholen
4. **Modul-Wahl ändern** — andere API-Module wählen und ab Schritt 3 wiederholen

Bei "Weiter": Phase 2 (Deep-Investigation) starten = vollständiges Scoring + Kapitelplanung.

### Schritt 8: PRISMA-Zähler speichern

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

Die Zähler werden in `$SESSION_DIR/prisma_counters.json` gespeichert.

Lief das Screening über den `parallel-screening`-Skill, sind die Zähler bereits
im Ledger protokolliert — dann statt der Handzählung:

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/screening_ledger.py \
  counters --session-dir "$SESSION_DIR" --n-identified "${N_IDENTIFIED}" \
  > "$SESSION_DIR/prisma_counters.json"
```

### Schritt 9: Relevanz-Scoring

Den `relevance-scorer`-Agent in Batches von 10 Papers starten. Das gilt
unabhängig von der Treffermenge: auch 50, 100 oder mehr Paper laufen über
denselben Weg, nur mit mehr Agent-Läufen — es gibt keinen Sonderpfad. LLM-Scores ins Ranking einmischen. Top-N nach
Modus wählen (quick=15, standard=25, deep=40). Als `$SESSION_DIR/papers.json`
speichern.

Das Scoring läuft vollständig in der Sitzung, ohne eigenen Modellzugang und
ohne asynchrone Abholung (#632).

### Schritt 10: Session-Index aktualisieren

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

### Schritt 11: Ergebnisse anzeigen

Eine formatierte Tabelle mit Rang, Titel, Jahr, Score, Cluster und Quellmodul ausgeben.
Pfad des Session-Verzeichnisses melden.

Die Kontext-Datei `./literature_state.md` im Projekt-Ordner mit neuen Statistiken aktualisieren, falls akademischer Kontext vorliegt.
