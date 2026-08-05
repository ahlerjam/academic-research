---
name: extraction-matrix
description: >
  Verwende diesen Skill, wenn der User aus den Vault-Quellen eine
  Extraktionsmatrix erstellen oder mehrere Studien tabellarisch vergleichen
  möchte. Trigger-Phrasen: "Extraktionsmatrix erstellen", "Studien
  vergleichen", "Quellen tabellarisch gegenüberstellen / Quellen
  tabellarisch gegenueberstellen", "Datenextraktion für die Synthese-Phase /
  Datenextraktion fuer die Synthese-Phase", "Merkmalstabelle aus meinen
  Quellen". Leitet Spalten aus den Schlüsselkonzepten in
  `academic_context.md` ab, ergänzt um die Standardmerkmale Methode,
  Stichprobe, Erhebungszeitraum und Kernbefund; befüllt jede Zelle
  ausschließlich aus vorhandenen `vault.find_notes()`/`vault.find_quotes()`-
  Belegen und markiert Fehlendes explizit statt zu raten. Statistische
  Auswertung oder Interpretation der Matrix ist nicht Teil dieses Skills. Für
  Einzel-Exzerpte pro Quelle → `reading-notes`. Für wörtliche Zitate →
  `citation-extraction`.
license: MIT
allowed-tools: [Read, Skill(document-skills:xlsx)]
---

# Extraktionsmatrix

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Sitzt zwischen „Quellen gesammelt" und „Kapitel geschrieben": erzeugt aus
den im Vault vorhandenen Quellen eine tabellarische Extraktionsmatrix
(Zeilen = Quellen, Spalten = für die Fragestellung relevante Merkmale). Macht
Befunde über mehrere Studien hinweg vergleichbar, ohne sie zu interpretieren
oder statistisch auszuwerten (Meta-Analyse-Pfad).

## Abgrenzung

Aggregiert ausschließlich **vorhandene** Vault-Inhalte zu einer
Vergleichstabelle:
- Legt selbst keine Notizen an (`vault.add_note()`) → `reading-notes`
- Extrahiert selbst keine wörtlichen Zitate (`vault.add_quote()`) →
  `citation-extraction`
- Sucht keine neuen Quellen und bewertet keine Korpus-Lücken →
  `literature-gap-analysis`
- Keine statistische Auswertung oder Interpretation der Matrix (Effektgrößen,
  Heterogenität) — das ist der Meta-Analyse-Pfad, out of scope laut Issue
- Keine Fabrikation: fehlt ein Beleg in Notiz oder Zitat, wird die Zelle als
  fehlend markiert, niemals ergänzt oder geschätzt

## Kontext-Dateien

- Lesen: `./academic_context.md` (Schlüsselkonzepte für die Spaltenableitung),
  `./literature_state.md` (read-only Paper-Inventar für die Zeilenableitung)
- Vault-Queries: `vault.find_notes(paper_id, query=None, k=10)` für
  strukturierte Exzerpte (Kernbefund/Methode/Verwendbarkeit aus
  `reading-notes`), `vault.find_quotes(paper_id, query, k=3)` für wörtliche
  Belege je Spaltenthema, `vault.list_tables(paper_id)` und
  `vault.get_table_cell(paper_id, page, table_index, row, col)` für
  Zahlen-Spalten aus Ergebnistabellen (Schritt 4a)
- Extern: `document-skills:xlsx` für den Arbeitsblatt-Export (Schritt 7)

## Core-Workflow

### 1. Staleness-Check

Ist `./literature_state.md` älter als der letzte `vault.add_paper()`-Aufruf
oder fehlt sie ganz, ist die Zeilen-Basis unvollständig (verletzt AC1/AC4).
Schlage `node scripts/export-literature-state.mjs` zur Regenerierung vor und
warte auf Bestätigung, statt mit veraltetem Stand fortzufahren.

### 2. Spalten ableiten

Lies `./academic_context.md`, Abschnitt „Schlüsselkonzepte". Jedes Konzept
wird eine Spalte. Ergänze vier feste Standardspalten: **Methode**,
**Stichprobe**, **Erhebungszeitraum**, **Kernbefund**. Frag den User nicht
nach der Spaltenliste — sie ergibt sich aus der eigenen Fragestellung.

### 3. Zeilen ableiten

Enumeriere die Paper-IDs aus `./literature_state.md` (ein `###`-Abschnitt
pro Quelle). Jede Quelle wird eine Zeile, unabhängig davon, ob später Belege
gefunden werden — AC4 verbietet das stille Weglassen.

### 4. Zellen befüllen

Pro Zeile (Quelle) und Konzept-Spalte:

1. `vault.find_quotes(paper_id, query=<Konzeptbegriff>)` — wörtlicher Beleg,
   bevorzugt für Konzept-Spalten
2. Kein Zitat gefunden: `vault.find_notes(paper_id, query=<Konzeptbegriff>)`
   durchsuchen

Für die vier Standardspalten: `vault.find_notes(paper_id)` liefert den
`reading-notes`-Freitext (`"Kernbefund: ...\nMethode: ...\nVerwendbarkeit:
..."`). **Kernbefund** und **Methode** direkt aus den gleichnamigen Feldern
übernehmen. **Stichprobe** und **Erhebungszeitraum** stehen dort nicht als
eigenes Feld — nur übernehmen, wenn sie explizit im Methode-Text auftauchen
(z. B. „N=42", „Erhebung 2021–2022"); sonst als fehlend markieren, auch wenn
der Methode-Text sonst vorhanden ist. Nie aus dem Kernbefund oder aus
Weltwissen ergänzen.

### 4a. Zahlen-Spalten aus Tabellen (Stichprobe, Effektstärke, CI)

Zahlen stehen in Tabellen, der Volltextindex kollabiert dort jede Struktur.
Für **Stichprobe**, Effektstärke und CI zuerst die Tabellenquelle prüfen:

1. `vault.list_tables(paper_id)` — je Tabelle `page`, `table_index` und `rows`
   (Zeile → Spalte → Wert); Zeile 0 ist meist die Kopfzeile.
2. Spalte in der Kopfzeile suchen (`N`, `d`, `95%-CI`), dann die Studienzeile.
3. `vault.get_table_cell(paper_id, page, table_index, row, col)` → `value`,
   `bbox` und ein fertiges `evidence`-Feld.
4. Matrixzelle: `<value> (<evidence>)`, z. B.
   `120 (smith2020, S. 1, Tabelle 1, Zeile 2, Spalte 2)`.

Kein Ergebnis heißt nicht „still leer": `status` nennt den Grund (`no-tables`,
`no-textlayer` → erst OCR, `backend-missing` → `uv sync --extra tables`). In
allen Fällen bleibt die Zelle `— fehlend —`; ein `None` von
`vault.get_table_cell()` wird nie durch einen Nachbarwert ersetzt.

**Fehlend-Markierung:** Jede Zelle ohne Beleg erhält den Text `— fehlend —`
(nicht leer lassen, nicht raten). Der Preamble-Block „Keine Fabrikation" gilt
hier als harte Regel: eine erfundene Stichprobengröße ist eine erfundene
Zahl.

### 5. Quellen ohne Grundlage (AC4)

Liefert weder `vault.find_notes()` noch `vault.find_quotes()` einen Treffer
für eine Quelle, erscheint sie trotzdem als eigene Zeile — alle Zellen
`— fehlend —`, zusätzlich eine Anmerkung unter der Tabelle: „*Grundlage
fehlt: keine Notiz oder kein Zitat im Vault — zuerst `reading-notes` oder
`citation-extraction` nutzen.*"

### 6. Ausgabe als Kapitel-Tabelle

Markdown-Tabelle direkt im Chat ausgeben, zur Übernahme in
`kapitel/literatur.md` (gleiches Einbettungsmuster wie bei
`cluster-visualizer`):

```markdown
| Quelle | <Konzept 1> | <Konzept 2> | Methode | Stichprobe | Erhebungszeitraum | Kernbefund |
|---|---|---|---|---|---|---|
| Autor (Jahr) | Beleg oder `— fehlend —` | ... | ... | ... | ... | ... |
```

### 7. Ausgabe als Arbeitsblatt

Vor dem Aufruf prüfen, ob `document-skills:xlsx` verfügbar ist. Falls nicht,
abbrechen mit:

> Das Excel-Backend `document-skills:xlsx` ist nicht installiert — es wird
> deshalb kein Arbeitsblatt erzeugt. Nachinstallation:
> `claude plugin marketplace add anthropics/skills` gefolgt von
> `claude plugin install document-skills@anthropic-agent-skills`, danach
> `/reload-plugins`.

Ist der Skill verfügbar: dieselbe Matrix (Schritt 4-5) als Sheet
„Extraktionsmatrix" übergeben, eine Spalte pro Merkmal, `— fehlend —`-Zellen
unverändert übernehmen (keine Farbcodierung nötig, anders als beim
5D-Scoring-Export in `commands/excel.md`).

## Wichtige Regeln

- **Spalten aus der eigenen Fragestellung** — nie eine generische
  Merkmalsliste ohne Bezug zu `academic_context.md` verwenden
- **Jede Zelle belegt oder fehlend** — kein Ausfüllen aus Vermutung,
  Weltwissen oder Analogie zu anderen Quellen
- **Keine Quelle verschwindet** — auch ohne Notiz/Zitat bleibt sie eine
  Zeile mit explizitem Hinweis
- **Kein Statistik-Pfad** — Effektgrößen, Signifikanzen, Heterogenitätsmaße
  gehören nicht in diesen Skill
- **Externer Export bleibt extern** — kein eigener xlsx-Code, ausschließlich
  `document-skills:xlsx` mit Verfügbarkeitscheck
