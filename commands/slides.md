---
description: Erzeugt einen Foliensatz (.pptx) aus vorhandenen Kapiteln mit je einer Kernaussage pro Folie, als Ausgangspunkt für Kolloquium oder Konferenz.
disable-model-invocation: true
allowed-tools: Read, Write, Bash(python3 *), Skill(document-skills:pptx)
argument-hint: --kapitel <n>|all --output <datei.pptx> [--kolloquium|--konferenz]
---

# /academic-research:slides — Slide-Export

## Beschreibung

Erzeugt einen Foliensatz (`.pptx`) aus vorhandenen Kapiteln — eine Kernaussage
pro Folie, als Ausgangspunkt für Kolloquium und Konferenz.

## Syntax

```
/academic-research:slides --kapitel <n>|all --output <datei.pptx> [--kolloquium|--konferenz]
```

## Parameter

| Parameter | Typ | Standard | Beschreibung |
|-----------|-----|---------|--------------|
| `--kapitel` | `<n>` oder `all` | — (Pflicht) | Kapitel-Nummer oder `all` für alle |
| `--output` | Dateipfad | — (Pflicht) | Ausgabedatei (`.pptx`) |
| `--kolloquium` | Flag | aus | Foliensatz-Rahmen für Kolloquium (Deckblatt, Agenda, Backup-Slot) |
| `--konferenz` | Flag | aus | Foliensatz-Rahmen für Konferenz-Vortrag |

## Beispiele

```bash
# Foliensatz aus allen Kapiteln fuer das Kolloquium
/academic-research:slides --kapitel all --output output/kolloquium.pptx --kolloquium

# Foliensatz aus einem Kapitel fuer eine Konferenz
/academic-research:slides --kapitel 4 --output output/konferenz.pptx --konferenz
```

## Slide-Backend

<!-- pptx-backend:start -->
Die pptx-Erzeugung übernimmt der externe Skill `document-skills:pptx` aus dem
Marketplace `anthropic-agent-skills` (Repository `anthropics/skills`). Das Plugin
`academic-research` deklariert ihn als Abhängigkeit in `.claude-plugin/plugin.json`
— eine frische Installation zieht ihn automatisch mit, sofern der Marketplace
bereits hinzugefügt ist.

**Vor dem ersten Skill-Aufruf prüfen:** Ist der Skill `document-skills:pptx` aufrufbar?
Falls nicht, brich mit dieser Meldung ab, statt einen rohen Tool-Fehler durchzureichen:

> Das Folien-Backend `document-skills:pptx` ist nicht installiert — es wird
> deshalb kein Foliensatz erzeugt. So installierst du es nach:
>
> ```bash
> claude plugin marketplace add anthropics/skills
> claude plugin install document-skills@anthropic-agent-skills
> ```
>
> Danach `/reload-plugins` ausführen und den Command erneut aufrufen.
<!-- pptx-backend:end -->

## Ablauf

### Schritt 1 — Argumente parsen

- `KAPITEL` = Wert von `--kapitel` (Pflicht: Zahl oder `all`)
- `OUTPUT` = Wert von `--output` (Pflicht: Zielpfad der `.pptx`-Datei)
- `RAHMEN` = `kolloquium` | `konferenz` | keiner (Flags)

### Schritt 2 — Skill laden

Skill `skills/slide-export/SKILL.md` wird geladen (Backend-Präflight,
Fehlerpfade, Abgrenzung zu `word-export`/`latex-export`).

### Schritt 3 — Folien-Zwischenrepräsentation bauen

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/slide-export/scripts")
from build_slide_deck import resolve_chapters, extract_slide_data

chapters = resolve_chapters("kapitel", "$KAPITEL")
slides = extract_slide_data(chapters)
# slides = [{"title": ..., "core_statement": ..., "source": ...}, ...]
PY
```

Fehlt bei einem Kapitel die Kernaussage (`core_statement == ""`), den User um
eine Kernaussage bitten statt eine zu erfinden.

### Schritt 4 — `document-skills:pptx` aufrufen

Ein Slide je Eintrag aus Schritt 3: `title` als Folientitel, `core_statement`
als zentrale Aussage. Bei `--kolloquium`/`--konferenz` zusätzlich Deckblatt-
und Agenda-Folie voranstellen.

### Schritt 5 — Ergebnis zeigen

Pfad der erzeugten `.pptx`, Anzahl Folien.

## Abhängigkeiten

- `document-skills:pptx` (siehe „Slide-Backend" oben)
