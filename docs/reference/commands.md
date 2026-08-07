# Commands / Slash-Commands

[← Doku-Übersicht](../README.md)

Commands werden explizit per `/academic-research:<name>` aufgerufen. Das Plugin bringt
**12 Slash-Commands** mit (`commands/*.md`).

| Command | Beschreibung |
|---------|-------------|
| `/academic-research:search` | Literatursuche über 7 APIs (+ `dblp` optional) + optional 7 Browser-Module |
| `/academic-research:score` | Re-Scoring und Cluster-Zuweisung |
| `/academic-research:excel` | Professionelle Excel-Datei (4 Sheets) |
| `/academic-research:setup` | Installer: venv, Browser, Vault, Hooks, Per-Uni-Profil |
| `/academic-research:history` | Recherche-Sessions einsehen |
| `/academic-research:fetch` | Buch/Paper via Site-Subagenten beschaffen |
| `/academic-research:pickup` | Bibliotheks-Pickup-Excel für nicht-OA-Quellen |
| `/academic-research:humanize` | Anti-KI-Audit-Pass via humanizer-de |
| `/academic-research:latex` | LaTeX-Export (`*.tex` + `*.bib`) |
| `/academic-research:word` | Word-Export (`*.docx`, optional PDF) mit echten Formatvorlagen |
| `/academic-research:slides` | Foliensatz (`*.pptx`) aus Kapiteln, eine Kernaussage pro Folie |
| `/academic-research:pruefbilanz` | Prüfbilanz eines Kapitels: geprüft/Befund offen/nicht geprüft |

Jede Sektion folgt demselben Schema: **Syntax** (mit `argument-hint`), **Beispiel(e)**,
**Skills/Agents** (was unter der Haube läuft), **Voraussetzungen**, **Rückgabe** und
**Fehlschlag**. Die letzten drei Felder sind dieselbe Feldmenge, die auch die
[Skills-](skills.md) und die [Agent-Referenz](agents.md) je Eintrag führen — hier als
Marker-Zeilen statt als Tabellenspalten, weil ein Command mehr Platz braucht als eine
Tabellenzeile hergibt.

## Command-Referenz

### `/academic-research:setup`

**Syntax:** `/academic-research:setup`

**Beispiele:**

```bash
# Vollständiges Setup (venv, browser-use, Vault, Hooks, Per-Uni-Profil)
/academic-research:setup
```

**Skills/Agents:** Ruft `scripts/setup.sh` auf — kein Agent. Prüft u.a. den globalen
`browser-use`-Skill und den vendorierten `humanizer-de`-Skill und schreibt
Claude-Code-Permissions.

**Voraussetzungen:** Python 3.11+, Node.js und Git auf dem Rechner; Schreibrecht in
`~/.academic-research/`. Der Lauf ist idempotent — ein zweiter Aufruf zerstört nichts.

**Rückgabe:** Eingerichtete Umgebung: virtuelle Umgebung, geprüfter `browser-use`-Skill,
registrierte Hooks und ein ausgewähltes Per-Uni-Profil.

**Fehlschlag:** `scripts/setup.sh` bricht mit einer Meldung ab, die den fehlenden
Bestandteil nennt (etwa Python-Version oder `browser-use`). Danach fehlen die
Claude-Code-Permissions, und die übrigen Commands melden fehlende Werkzeuge.

### `/academic-research:search`

**Syntax:** `/academic-research:search "<query>" [--mode quick|standard|deep|metadata] [--modules LIST] [--limit N] [--no-expand] [--no-browser] [--interactive=off]`

Das Approval-Gate nach Phase 1 (Query-Expansion + Treffer-Preview) läuft seit
#537 standardmäßig; `--interactive=off` ist das Opt-out, nicht-interaktive
Läufe bleiben gate-frei.

| Mode | Module | Top-N | Beschreibung |
|------|--------|-------|-------------|
| `quick` | 4 APIs | 15 | Schnelle Suche |
| `standard` | 7 APIs | 25 | Empfohlen |
| `deep` | 7 APIs + 7 Browser-Module | 40 | Systematisch |
| `metadata` | 7 APIs | 25 | Ohne PDFs |

**Beispiele:**

```bash
# Standard-Suche
/academic-research:search "DevOps Governance" --mode standard

# Tiefe Suche, nur CrossRef + OpenAlex, max. 40 Treffer
/academic-research:search "AI ethics" --mode deep --modules crossref,openalex --limit 40
```

**Skills/Agents:** Startet die Agents `query-generator` (Query-Expansion),
`relevance-scorer` (5D-Relevanz) und `quote-extractor` (Verbatim-Zitate).

**Voraussetzungen:** Netzzugang zu den API-Quellen; für `--mode deep` zusätzlich ein
eingerichteter `browser-use`-Skill.

**Rückgabe:** Trefferliste mit Score je Dimension, dazu die Session-Datei mit den
Treffern und die Papers im Vault.

**Fehlschlag:** Die Ausgabe meldet `Found 0 papers`, oder ein Modul läuft in einen
Timeout und taucht in der Quellenliste des Berichts nicht auf.

### `/academic-research:score`

**Syntax:** `/academic-research:score [papers.json] [--query "..."] [--mode standard]`

**Beispiele:**

```bash
# Papers der letzten Session neu scoren
/academic-research:score

# Bestimmte Datei gegen Query scoren
/academic-research:score papers.json --query "DevOps"
```

**Skills/Agents:** Startet den `relevance-scorer`-Agent für die Relevanz-Dimension; die
vier übrigen 5D-Dimensionen (Aktualität, Qualität, Autorität, Zugang) berechnet die
Command-Logik direkt.

**Voraussetzungen:** Eine Trefferdatei (`papers.json`) oder eine gelaufene Session, deren
Treffer neu bewertet werden sollen.

**Rückgabe:** Aktualisierte Scores je Dimension und die Cluster-Zuweisung; je Paper ein
Score-Snapshot, der über `vault.get_score_history()` abrufbar bleibt.

**Fehlschlag:** Der Command findet weder Datei noch Session und meldet das; die
bestehenden Scores bleiben dann unverändert.

### `/academic-research:excel`

**Syntax:** `/academic-research:excel [--papers papers.json] [--output literature.xlsx] [--context]`

**Beispiele:**

```bash
# Aus letzter Session generieren
/academic-research:excel

# Mit Kapitel-Zuordnung aus dem akademischen Kontext
/academic-research:excel --context --output my_literature.xlsx
```

**Skills/Agents:** Nutzt den `document-skills:xlsx`-Skill (Plugin-Dependency, siehe
[Externe Skills](skills.md#externe-skills-plugin-dependencies)).

**Voraussetzungen:** Das Plugin `document-skills` ist installiert, und es liegen Treffer
aus einer Session oder Papers im Vault vor. Für `--context` zusätzlich eine Gliederung in
`academic_context.md`.

**Rückgabe:** Eine `.xlsx`-Datei mit den vier Sheets der Literaturübersicht.

**Fehlschlag:** Statt einer Datei kommt der Nachinstallations-Weg für `document-skills`
zurück, oder die Kapitel-Spalte bleibt leer, weil keine Gliederung vorliegt.

### `/academic-research:pickup`

**Syntax:** `/academic-research:pickup`

**Beispiele:**

```bash
# Bibliotheks-Pickup-Liste (4 Sheets) aus markierten Vault-Einträgen
/academic-research:pickup
```

**Skills/Agents:** Nutzt den `document-skills:xlsx`-Skill (Plugin-Dependency, siehe
[Externe Skills](skills.md#externe-skills-plugin-dependencies)) für die
4-Sheet-Excel-Datei sowie `scripts/barcode_utils.py` für Code128-Barcodes (optional via
`python-barcode[images]`).

**Voraussetzungen:** Vault-Einträge ohne frei zugänglichen Volltext (etwa aus einem
`metadata_only`-Lauf von `/fetch`) und das Plugin `document-skills`.

**Rückgabe:** Eine `.xlsx`-Datei mit der Pickup-Liste, auf Wunsch mit Code128-Barcodes
für die Ausleihtheke.

**Fehlschlag:** Ohne `python-barcode[images]` entstehen keine Barcodes — die Liste selbst
bleibt nutzbar. Ohne `document-skills` kommt gar keine Datei.

### `/academic-research:fetch`

**Syntax:** `/academic-research:fetch <isbn|doi|titel|url> [--uni <profil>]`

**Beispiele:**

```bash
# Per ISBN
/academic-research:fetch 978-3-16-148410-0

# Per DOI mit Uni-Profil
/academic-research:fetch 10.1007/978-3-658-12345-6 --uni tum
```

**Skills/Agents:** Startet den `book-fetcher`-Agent (Master-Orchestrator) mit
konfigurierbarer Fallback-Kette über die Site-Agents (OAPEN → DOAB → TIB → KVK;
Springer → De Gruyter → Ebook Central → Nationallizenzen) und `auth-helper` für
HAN/Shibboleth.

**Voraussetzungen:** Eingerichteter `browser-use`-Skill; für lizenzpflichtige Wege ein
Uni-Profil unter `~/.academic-research/library-profiles/` mit Dateirechten `0600`.

**Rückgabe:** Das JSON des `book-fetcher` mit `status`, bei Erfolg `file_path` und
immer der `tries`-Kette der versuchten Subagenten.

**Fehlschlag:** `status` ist nicht `success` — `pickup_required` (Ausleihe nötig),
`captcha` (Zugriff blockiert) oder `no_match` (kein Treffer). Die `tries`-Kette zeigt,
welcher Subagent woran gescheitert ist.

### `/academic-research:humanize`

**Syntax:** `/academic-research:humanize <kapitel-pfad> [--mode normal|deep]`

**Beispiele:**

```bash
# Normal-Modus (Default)
/academic-research:humanize kapitel/3.md

# Deep-Modus (zweiter Anti-KI-Pass)
/academic-research:humanize kapitel/3.md --mode deep
```

**Skills/Agents:** Nutzt den vendorierten `humanizer-de`-Skill (`skills/humanizer-de/`)
und erzeugt `<basename>.humanized.md` plus ein Severity-gegliedertes
`<basename>.diff.md`.

**Voraussetzungen:** Eine lesbare deutschsprachige Markdown-Datei; das Zielverzeichnis
muss beschreibbar sein.

**Rückgabe:** `<basename>.humanized.md` mit dem überarbeiteten Text und
`<basename>.diff.md` mit den Änderungen nach Severity.

**Fehlschlag:** Eine der beiden Dateien fehlt danach, oder der Diff ist leer, obwohl der
Audit Muster gemeldet hat.

### `/academic-research:latex`

Neu in v6.5: exportiert Markdown-Kapitel nach LaTeX.

**Syntax:** `/academic-research:latex --kapitel <n>|all --output <datei.tex> [--bib <datei.bib>] [--template <uni>]`

**Beispiele:**

```bash
# Einzelnes Kapitel exportieren
/academic-research:latex --kapitel 3 --output output/kap3.tex

# Alle Kapitel + biblatex-konforme .bib
/academic-research:latex --kapitel all --output output/thesis.tex --bib output/refs.bib

# Mit Uni-Template
/academic-research:latex --kapitel all --output output/thesis.tex --template tum
```

**Skills/Agents:** Lädt den `latex-export`-Skill (`skills/latex-export/`):
`export_thesis.py` orchestriert Kapitel-Auswahl, `render_tex.py`
(Markdown → `.tex`, Pandoc oder Custom-Renderer), optionales
Uni-Template-Wrapping und `build_bib.py` (`.bib` aus dem Vault, Pfad
unabhängig von `--output`). Der `verbatim-guard`-Hook blockiert `.tex`-Writes
mit nicht-verifizierten Zitaten.

**Voraussetzungen:** Kapitel-Dateien unter `kapitel/`; für die `.bib` ein gefüllter
Vault. Pandoc ist optional — ohne Pandoc greift der Custom-Renderer.

**Rückgabe:** Die `.tex`-Datei und, bei gesetztem `--bib`, die biblatex-konforme
`.bib`-Datei.

**Fehlschlag:** Der `verbatim-guard` blockt den `.tex`-Write, weil ein Zitat nicht im
Vault steht. Weitere Signale: „Template `<uni>` fehlt" oder eine leere `.bib` mit der
Meldung „Vault leer".

### `/academic-research:word`

Neu in Issue #446: exportiert Markdown-Kapitel nach Word (`.docx`) mit echten
Formatvorlagen für Überschriftenebenen, Titelblatt, Inhaltsverzeichnis und
eidesstattlicher Erklärung; optional zusätzlich als PDF.

**Syntax:** `/academic-research:word --kapitel <n>|all --output <datei.docx> [--format docx|pdf] [--template <uni>]`

**Beispiele:**

```bash
# Alle Kapitel als Word-Dokument
/academic-research:word --kapitel all --output output/thesis.docx

# Einzelnes Kapitel, zusaetzlich als PDF
/academic-research:word --kapitel 3 --output output/kap3.docx --format pdf
```

**Skills/Agents:** Lädt den `word-export`-Skill (`skills/word-export/`).
`collect_references.py` importiert `build_bib.get_all_papers()` aus
`latex-export` (geteilte Vault-Query, keine zweite Implementierung) und lädt die
Zitierstil-Regeln unverändert aus `citation-extraction/references/<style>.md`.
`\cite{key}`-Marker aus `kapitel/*.md` werden vor dem Rendern zu Klartext-
Kurzzitaten aufgelöst. Die `.docx` selbst erzeugt `render_docx.py`
deterministisch (echte `Heading 1`…`Heading 6`-Formatvorlagen, Word-native
Inhaltsverzeichnis-Feldfunktion, Titelblatt, Literaturverzeichnis,
eidesstattliche Erklärung) — der externe `document-skills:docx`-Skill bleibt für
optionale Layout-Verfeinerung auf der erzeugten Datei.

**Voraussetzungen:** Kapitel-Dateien unter `kapitel/` und das Paket `python-docx`. Für
`--format pdf` zusätzlich LibreOffice (`soffice`) auf dem Rechner.

**Rückgabe:** Die `.docx` mit Titelblatt, Verzeichnissen und eidesstattlicher Erklärung;
mit `--format pdf` zusätzlich die PDF-Fassung.

**Fehlschlag:** `render_docx.py` meldet `FEHLER:` mit Nachinstallations-Hinweis (etwa
fehlendes `python-docx`). Fehlt nur `soffice`, entsteht die `.docx` trotzdem und die
PDF-Konvertierung wird mit Hinweis übersprungen.

### `/academic-research:slides`

Neu in Issue #446: erzeugt einen Foliensatz (`.pptx`) aus vorhandenen Kapiteln
— eine Kernaussage pro Folie, als Ausgangspunkt für Kolloquium und Konferenz.

**Syntax:** `/academic-research:slides --kapitel <n>|all --output <datei.pptx> [--kolloquium|--konferenz]`

**Beispiele:**

```bash
# Foliensatz aus allen Kapiteln fuer das Kolloquium
/academic-research:slides --kapitel all --output output/kolloquium.pptx --kolloquium
```

**Skills/Agents:** Lädt den `slide-export`-Skill (`skills/slide-export/`).
`build_slide_deck.py` importiert `resolve_chapters()` aus
`latex-export/export_thesis.py` und extrahiert je Kapitel Titel + ersten
Kernsatz als Folien-Zwischenrepräsentation; `render_pptx.py` rendert daraus das
`.pptx` deterministisch (eine Folie je Kapitel, mit `--kolloquium`/`--konferenz`
zusätzlich Deckblatt und Agenda). Der externe `document-skills:pptx`-Skill
bleibt für optionale Designvorlagen auf dem erzeugten Deck.

**Voraussetzungen:** Kapitel-Dateien unter `kapitel/` und das Paket `python-pptx`.

**Rückgabe:** Die `.pptx` mit einer Folie je Kapitel, bei `--kolloquium`/`--konferenz`
zusätzlich Deckblatt und Agenda.

**Fehlschlag:** `resolve_chapters()` wirft `ChapterResolutionError` und nennt die
verfügbaren Kapitel. Findet der Skill in einem Kapitel keine Kernaussage, kommt eine
Rückfrage statt einer Platzhalter-Folie.

### `/academic-research:history`

**Syntax:** `/academic-research:history [<query>|<datum>|stats|--snapshots|--restore <ts>]`

**Beispiele:**

```bash
# Alle Sessions auflisten
/academic-research:history

# Sessions per Query durchsuchen
/academic-research:history "DevOps"

# Snapshot wiederherstellen
/academic-research:history --restore 20260507-1430
```

**Skills/Agents:** Reine Command-Logik (kein Agent/Skill) — liest den Session-Index
unter `~/.academic-research/sessions/` und verwaltet `.tgz`-Snapshots.

**Voraussetzungen:** Mindestens eine gelaufene Recherche-Session; für `--restore` ein
vorhandener Snapshot unter `<slug>/<ts>.tgz`.

**Rückgabe:** Die Session-Liste (oder die Treffer der Suche), die Snapshot-Übersicht
und bei `--restore` der wiederhergestellte Projektstand.

**Fehlschlag:** Die Liste bleibt leer, obwohl Suchen gelaufen sind — dann fehlt der
Session-Index. Bei `--restore` meldet der Command den unbekannten Zeitstempel.

### `/academic-research:pruefbilanz`

**Syntax:** `/academic-research:pruefbilanz <kapitel-datei.md>`

**Beispiele:**

```bash
/academic-research:pruefbilanz kapitel/03-methodik.md
```

**Skills/Agents:** Reine Command-Logik (kein Agent/Skill) — ruft
`vault.chapter_quote_balance(chapter_path)` direkt auf und formatiert die Rückgabe.

**Voraussetzungen:** Lesbare Kapiteldatei; Zitate müssen im Vault stehen, um erfasst
zu werden (nicht im Vault belegte Passagen tauchen in keiner Bucket-Zahl auf).

**Rückgabe:** `total_quotes`, die drei Zähler (`geprueft_unauffaellig`/`befund_offen`/
`nicht_geprueft`), `not_audited` (je Eintrag mit `reason`) und `findings` (offene
Befunde, schwerste zuerst) als formatierte Ausgabe.

**Fehlschlag:** `FileNotFoundError`, wenn die Kapiteldatei nicht existiert. Ein Kapitel
ohne belegte Zitate ist **kein** Fehlschlag — alle Zähler stehen dann auf `0`.
