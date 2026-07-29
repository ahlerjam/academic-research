---
description: Generate or update a literature Excel spreadsheet via the document-skills:xlsx skill
disable-model-invocation: true
allowed-tools: Read, Write, Bash(ls ~/.academic-research/sessions/*), Skill(document-skills:xlsx)
argument-hint: [--papers papers.json] [--output literature.xlsx] [--context]
---

# Literatur-Excel-Generator

Erstellt ein formatiertes Excel-Workbook aus gescorten Papers.

## Excel-Backend

<!-- xlsx-backend:start -->
Die Excel-Erzeugung übernimmt der externe Skill `document-skills:xlsx` aus dem
Marketplace `anthropic-agent-skills` (Repository `anthropics/skills`). Das Plugin
`academic-research` deklariert ihn als Abhängigkeit in `.claude-plugin/plugin.json`
— eine frische Installation zieht ihn automatisch mit, sofern der Marketplace
bereits hinzugefügt ist. Der Skill führt Python mit `openpyxl` und `pandas` im
lokalen Environment aus; beide Pakete installiert `/academic-research:setup` mit.

**Vor dem ersten Skill-Aufruf prüfen:** Ist der Skill `document-skills:xlsx` aufrufbar?
Falls nicht, brich mit dieser Meldung ab, statt einen rohen Tool-Fehler durchzureichen:

> Das Excel-Backend `document-skills:xlsx` ist nicht installiert — es wird
> deshalb keine Excel-Datei erzeugt. So installierst du es nach:
>
> ```bash
> claude plugin marketplace add anthropics/skills
> claude plugin install document-skills@anthropic-agent-skills
> ```
>
> Danach `/reload-plugins` ausführen und den Command erneut aufrufen.
<!-- xlsx-backend:end -->

## Verwendung

- `/academic-research:excel` — Aus letzter Session generieren
- `/academic-research:excel --papers papers.json --output my_literature.xlsx`
- `/academic-research:excel --context` — Kapitel-Zuordnung aus akademischem Kontext mitnehmen

## Erwartete Sheets

1. **Literaturübersicht** — Vollständige Paperliste mit 5D-Scores, Clustern, farbcodiert
2. **Cluster-Analyse** — Statistik pro Cluster mit Balkendiagramm
3. **Kapitel-Zuordnung** — Papers den Gliederungskapiteln zugeordnet (benötigt `--context`)
4. **Datenblatt** — Rohdaten für programmatischen Zugriff

## Umsetzung

### Schritt 1: Papers lokalisieren

```bash
if [ -z "$PAPERS" ]; then
  LATEST=$(ls -t ~/.academic-research/sessions/ | head -1)
  PAPERS=~/.academic-research/sessions/$LATEST/ranked.json
fi
```

### Schritt 2: Input strukturieren

Lies die Paper-Daten aus `$PAPERS` (JSON-Array mit Feldern `title`, `authors`, `year`, `doi`, `total_score`, `cluster`, `relevance_score`, `recency_score`, `quality_score`, `authority_score`, `access_score`, `venue`, `source_module`).

Wenn `--context` gesetzt:
- Lies `./academic_context.md` aus dem Projekt-Ordner; extrahiere die `Gliederung`
- Berechne pro Paper die zugeordneten Kapitel (Keyword-Match zwischen `title`/`abstract` und Kapitelüberschriften)

### Schritt 3: xlsx-Skill aktivieren

Führe zuerst die Verfügbarkeitsprüfung aus dem Abschnitt „Excel-Backend" durch. Wende dann `document-skills:xlsx` auf die strukturierten Paper-Daten an.

**Input:** Strukturierte Paper-Daten (siehe Schritt 2) plus Sheet-Spezifikation (welche Sheets, welche Spalten, welche Farbcodierung).

**Output:** `$OUTPUT` (Default: `~/.academic-research/sessions/$LATEST/literature.xlsx`).

**Sheet-Spezifikation:**

- **Literaturübersicht**: Spalten `Titel | Autoren | Jahr | Venue | DOI | Gesamt | Relevanz | Aktualität | Qualität | Autorität | Zugang | Cluster`. Farbcodierung je Cluster (Kern = grün, Ergänzung = blau, Hintergrund = grau, Methoden = gelb).
- **Cluster-Analyse**: Aggregatstatistik pro Cluster (Anzahl, Durchschnittsscore, Jahresverteilung) + eingebettetes Balkendiagramm.
- **Kapitel-Zuordnung** (nur bei `--context`): Mapping Kapitel → Papers.
- **Datenblatt**: Alle Rohdatenfelder in flachem Tabellenformat.

### Schritt 4: Ergebnis präsentieren

Ausgabepfad und Zusammenfassung anzeigen (Anzahl Papers, Cluster-Verteilung, Dateigröße).
