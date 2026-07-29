# Commands / Slash-Commands

[← Doku-Übersicht](../README.md)

Commands werden explizit per `/academic-research:<name>` aufgerufen. Das Plugin bringt
**9 Slash-Commands** mit (`commands/*.md`).

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

Jede Sektion folgt demselben Schema: **Syntax** (mit `argument-hint`), **Beispiel(e)** und
**Skills/Agents** (was unter der Haube läuft).

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

### `/academic-research:search`

**Syntax:** `/academic-research:search "<query>" [--mode quick|standard|deep|metadata] [--modules LIST] [--limit N] [--no-expand] [--no-browser]`

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
