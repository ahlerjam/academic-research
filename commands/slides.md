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
- `RAHMEN` = `kolloquium` | `konferenz` | leer (Flags)
- `PAYLOAD` = Ablagepfad der JSON-Zwischenrepräsentation aus Schritt 3
  (z. B. `${OUTPUT%.pptx}.payload.json`)

### Schritt 2 — Skill laden

Skill `skills/slide-export/SKILL.md` wird geladen (nur Trigger-Wrapper,
prüft Vorbedingungen über `skills/_common/preamble.md`). Ablauflogik,
Fehlerpfade und Abgrenzung zu `word-export`/`latex-export` stehen
ausschließlich in diesem Command (siehe unten).

### Schritt 3 — Folien-Zwischenrepräsentation bauen

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slide-export/scripts/build_slide_deck.py" \
  --kapitel "$KAPITEL" --payload "$PAYLOAD" --rahmen "$RAHMEN"
```

Ergebnis ist die JSON-Datei unter `PAYLOAD` mit
`slides[]` (`title`, `core_statement`, `source`) und `rahmen`. Die
Kapitel-Auflösung ist `export_thesis.resolve_chapters()` — dieselbe wie bei
`latex-export`/`word-export`, kein zweiter Nachbau.

Bei Exit-Code ≠ 0 die vom Skript ausgegebene `FEHLER:`-Meldung (z. B. unbekanntes
Kapitel) unverändert weitergeben — kein Stacktrace. Fehlt bei einem Kapitel die
Kernaussage (`core_statement == ""`, das Skript meldet das auf stderr), den User
um eine Kernaussage bitten statt eine zu erfinden.

### Schritt 4 — Foliensatz rendern

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slide-export/scripts/render_pptx.py" \
  --payload "$PAYLOAD" --output "$OUTPUT"
```

Ein Slide je Eintrag aus `slides` in Schritt 3: `title` als Folientitel,
`core_statement` als zentrale Aussage. Bei `rahmen` = `kolloquium`/`konferenz`
stellt das Skript Deckblatt- und Agenda-Folie voran. Kapitel ohne Kernaussage
ergeben eine Folie mit leerem Rumpf + Meldung auf stderr — nachfragen statt
eine Kernaussage erfinden.

Bei Exit-Code ≠ 0 die `FEHLER:`-Meldung unverändert weitergeben.

### Schritt 5 — Optionale Layout-Verfeinerung

Bei Bedarf `document-skills:pptx` auf das **erzeugte** Deck anwenden
(Designvorlage, Bildfolien). Optional — das Ergebnis aus Schritt 4 ist bereits
ein vollständiger, in PowerPoint öffenbarer Foliensatz.

### Schritt 6 — Ergebnis zeigen

Pfad der erzeugten `.pptx`, Anzahl Folien.

## Abgrenzung

- **`word-export`**: gleiche Kapitel-Quelle, aber Fließtext-Renderer (`.docx`/PDF)
  statt Folien. Beide teilen die Kapitel-Auflösung aus `latex-export`, nicht
  die Rendering-Logik — docx-Fließtext und pptx-Folien sind strukturell zu
  verschieden für einen gemeinsamen Renderer.
- **`latex-export`**: kein Bezug zu Folien; nur Kapitel-Quelle ist geteilt.
- Kein eigenes Literaturverzeichnis auf Folien — Zitate/Quellen bleiben in den
  Kapiteln, `slide-export` reduziert auf die Kernaussage.

## Fehlerpfade

- **Backend fehlt:** Siehe „Slide-Backend" oben — Abbruch mit Installationshinweis,
  kein roher Tool-Fehler.
- **Kapitel ohne Kernaussage:** `core_statement` ist leer (kein Fließtext-Absatz
  gefunden) — Rückfrage an den User statt Platzhalter-Fabrikation.
- **Unbekanntes `--kapitel`:** `resolve_chapters()` wirft `ChapterResolutionError`
  mit den verfügbaren Kapiteln in der Meldung (identisch zu `latex-export`).
- **Kein Kapitel in `kapitel/`:** `ChapterResolutionError` mit „Kein Kapitel in
  '<dir>' gefunden" statt Stacktrace.
- **`python-pptx` fehlt:** `render_pptx.py` meldet „FEHLER: Das Python-Paket
  'python-pptx' ist nicht installiert …" mit Nachinstallations-Hinweis statt
  eines `ImportError`-Tracebacks (AC6).

## Abhängigkeiten

- `python-pptx` (Renderer aus Schritt 4, Teil der Plugin-Installation)
- `document-skills:pptx` (siehe „Slide-Backend" oben)
