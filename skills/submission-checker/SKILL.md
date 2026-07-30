---
name: submission-checker
description: Use this skill when the user prepares final submission (formalia check). Triggers on "Abgabe prüfen / Abgabe pruefen", "abgabefertig", "Formalia prüfen / Formalia pruefen", "FH-Leibniz-Formalia", "Formatierung", "Seitenränder / Seitenraender", "Zeilenabstand", "Schriftart", "submission check", or when the user nears deadline. Prüft institutsspezifische Formalia; Default-Profil FH Leibniz, weitere via `references/<variant>.md`.
license: MIT
allowed-tools:
  - Read
---

# Abgabe-Prüfer

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Prüft Formalia vor Abgabe: Pflichtabschnitte, Seitenumfang, Formatierung,
Quellenzahl, Abbildungen/Tabellen, eidesstattliche Erklärung. Verwendet
hochschulspezifische Regeln aus `references/<variant>.md` (Default:
FH Leibniz). Seitenumfang und Formatierung entstehen als Layout erst beim
Export -- am reinen Markdown-Material sind sie nicht belegbar und werden
ohne explizite User-Angabe als „Nicht geprüft" ausgewiesen statt geraten.

## Abgrenzung

Prüft Formalia gegen Hochschul-Regeln. Abstract/Keywords → `abstract-generator`.
Titel → `title-generator`. Kontextdaten → `academic-context`.
`.docx`/PDF-Export → `word-export`.

## Variant-Selector

Lies `./academic_context.md`, Feld `Universitaet` und/oder `Arbeitstyp`:

| Kontext | Referenz-Datei |
|---------|----------------|
| FH Leibniz (Default) | `references/fh-leibniz.md` |
| Andere deutsche Uni | `references/uni-general.md` |
| IEEE-Konferenz/-Journal | `references/journal-ieee.md` |
| ACM-Konferenz/-Journal | `references/journal-acm.md` |

Fehlt das Feld → `fh-leibniz.md` als Default (Plugin-Default ist FH Leibniz). Unbekannt → Rueckfrage.

## Kontext- und Referenzdateien

- `./academic_context.md` — Arbeitstyp, Universität, Zitationsstil
- `${CLAUDE_PLUGIN_ROOT}/skills/submission-checker/references/fh-leibniz.md` — hochschulspezifische Formalia
- `./writing_state.md` — Wortzahlen, Kapitelstatus

## Checklisten-Dimensionen

Am reinen Markdown-Material (`kapitel/*.md`, `writing_state.md`) sind nur
Text-Eigenschaften belegbar. Layout entsteht erst beim Export
(`word-export`/`latex-export`). Dimensionen 1, 4 und 6 sind deshalb am
Material selbst prüfbar; Dimensionen 2 und 3 sind es **nicht**, außer der
User nennt die tatsächlichen Werte explizit (z. B. aus dem fertigen
Word-Dokument abgelesen) -- dann gegen `references/fh-leibniz.md` abgleichen
statt selbst zu schätzen. Dimension 5 ist nur auf Text-Ebene prüfbar (siehe
dort). Nicht geprüfte Dimensionen gehören verpflichtend in die
„Nicht geprüft"-Sektion des Outputs (siehe unten) -- niemals stillschweigend
als PASS ausgeben.

### 1. Pflichtabschnitte

Präsenz aller verpflichtenden Abschnitte in der korrekten Reihenfolge prüfen:

**Front Matter:**
- [ ] Deckblatt -- Titel, Autor:in, Matrikelnummer, Betreuer:in, Abgabedatum, Hochschullogo
- [ ] Abstract (falls für den Arbeitstyp erforderlich)
- [ ] Inhaltsverzeichnis -- mit Seitenzahlen
- [ ] Abbildungsverzeichnis -- falls Abbildungen enthalten sind
- [ ] Tabellenverzeichnis -- falls Tabellen enthalten sind
- [ ] Abkürzungsverzeichnis -- falls Abkürzungen verwendet werden

**Hauptteil:**
- [ ] Einleitung -- mit Forschungsfrage, Methodik-Überblick, Strukturvorschau
- [ ] Hauptkapitel -- laut Gliederung
- [ ] Fazit/Schluss -- mit Zusammenfassung, Limitationen, Ausblick

**Back Matter:**
- [ ] Literaturverzeichnis -- alle zitierten Quellen, korrekt formatiert
- [ ] Anhang -- falls im Text referenziert
- [ ] Eidesstattliche Erklärung -- unterzeichnete Erklärung eigenständiger Arbeit

### 2. Seitenzahl und Umfang -- NICHT am Material prüfbar

Markdown-Kapiteltext hat kein Seitenlayout; die tatsächliche Seitenzahl
entsteht erst beim Export (`word-export`/`latex-export`). Ohne eine echte
Seitenzahl-Angabe des Users diese Dimension als „Nicht geprüft" ausweisen,
nie eine Wortzahl-Schätzung als geprüfte Seitenzahl ausgeben.

Nennt der User die tatsächliche (z. B. aus dem Export abgelesene) Seitenzahl,
gegen die Richtwerte aus `${CLAUDE_PLUGIN_ROOT}/skills/submission-checker/references/fh-leibniz.md` prüfen:

| Arbeitstyp       | Typischer Umfang (Seiten) |
|------------------|---------------------------|
| Bachelorarbeit   | 30-50                     |
| Masterarbeit     | 60-80                     |
| Hausarbeit       | 12-20                     |
| Seminararbeit    | 15-25                     |
| Facharbeit       | 8-15                      |

Zusätzlich (nur mit User-Angabe) verifizieren:
- Gesamtseitenzahl im zulässigen Rahmen
- Front Matter und Back Matter nicht mitgezählt (falls die Hochschule das verlangt)

Am Material selbst bleibt nur die relative Kapitelbalance (aus `writing_state.md`-Wortzahlen)
prüfbar -- kein Kapitel überproportional lang oder kurz im Vergleich zu den anderen. Das
ist eine Wortzahl-Heuristik, keine Seitenzahl-Prüfung, und entsprechend zu benennen.

### 3. Formatierung -- NICHT am Material prüfbar

**Typografie, Ränder, Zeilenabstand:** Schriftart, Punktgröße, Zeilenabstand, Randmaße und
Blocksatz sind Eigenschaften eines Layout-Dokuments (`.docx`/`.tex`/PDF) und lassen sich aus
reinem Markdown-Text nicht ableiten. Diese Dimension immer als „Nicht geprüft" ausweisen,
außer der User nennt die tatsächlichen Werte explizit im Gespräch (z. B. aus der geöffneten
Word-Datei abgelesen) -- dann gegen die Vorgaben aus
`${CLAUDE_PLUGIN_ROOT}/skills/submission-checker/references/fh-leibniz.md` prüfen
(Referenzwerte: Times New Roman 12pt/Arial 11pt, Zeilenabstand 1.5, Ränder links 3cm/rechts
2.5cm/oben+unten 2.5cm/2cm, Blocksatz, Seitenzahlen arabisch ab Einleitung).

**Überschriften und Absätze (am Material prüfbar):** Konsistente Überschriften-Hierarchie,
nummeriert (max. 3 Ebenen), keine Schuster-Überschriften, keine Einzelsatz-Absätze -- das
sind Text-Eigenschaften und bleiben unabhängig vom Layout prüfbar.

### 4. Quellenzahl und Zitationsqualität

Ausreichende Quellennutzung prüfen:

| Arbeitstyp       | Minimum Quellen |
|------------------|-----------------|
| Bachelorarbeit   | 25-40           |
| Masterarbeit     | 40-60           |
| Hausarbeit       | 10-20           |
| Seminararbeit    | 15-25           |

Prüfen: Quellenzahl, In-Text↔Bibliographie-Abgleich, Zitierformat (aus `./academic_context.md`), kein zitatfreies Kapitel (außer Intro-Vorschau + Ausblick).

### 5. Abbildungen und Tabellen -- nur auf Text-Ebene prüfbar

Falls Abbildungen oder Tabellen vorhanden, am Markdown-Text prüfbar:
- Jede hat eine nummerierte Beschriftung ("Abbildung 1:", "Tabelle 1:")
- Jede wird im Text referenziert
- Nummerierung sequenziell und konsistent
- Quellenangabe unter jeder Abbildung/Tabelle
- Abbildungs-/Tabellenverzeichnis im Front Matter stimmt mit dem Inhalt überein

**Nicht prüfbar:** ob eine referenzierte Bilddatei tatsächlich existiert/lädt,
und die visuelle Platzierung im Layout -- das entsteht erst im Export.

### 6. Eidesstattliche Erklärung -- Text-Präsenz prüfbar

Verifizieren:
- Vorhanden als letzte Seite (oder gemäß hochschulspezifischer Platzierungsregel)
- Enthält den geforderten Wortlaut gemäß `${CLAUDE_PLUGIN_ROOT}/skills/submission-checker/references/fh-leibniz.md`
- Enthält Ort-/Datum-Feld
- Enthält ein Unterschriftenfeld (Textmarker/Platzhalter)

**Nicht prüfbar:** ob das Feld tatsächlich handschriftlich unterzeichnet ist --
das lässt sich am Markdown-Text nie feststellen, auch nicht nach Export.

## Evaluations-Workflow

1. Kontext-Dateien lesen (academic_context → Arbeitstyp/Hochschule, fh-leibniz.md → Anforderungen, writing_state → Fertigstellung)
2. Arbeit gegen Checkliste prüfen, Dimensionen PASS/PARTIAL/FAIL scoren
3. Strukturiert ausgeben, Fixes nach Schweregrad priorisieren

## Output-Format

```
## Abgabe-Check: [Arbeitstitel]

**Typ:** [Arbeitstyp] | **Uni:** [Hochschule] | **Datum:** [Prüfdatum]

### Ergebnis-Übersicht

| Prüfbereich           | Status                          | Details           |
|-----------------------|----------------------------------|-------------------|
| Pflichtabschnitte     | PASS/PARTIAL/FAIL                | [X/Y vorhanden]   |
| Seitenumfang          | PASS/PARTIAL/FAIL/NICHT GEPRÜFT  | [N Seiten oder Grund] |
| Formatierung          | PASS/PARTIAL/FAIL/NICHT GEPRÜFT  | [Issues count oder Grund] |
| Quellenanzahl         | PASS/PARTIAL/FAIL                | [N Quellen]       |
| Abbildungen/Tabellen  | PASS/PARTIAL/FAIL                | [Issues count]    |
| Eidesstattl. Erkl.    | PASS/PARTIAL/FAIL                | [vorhanden/fehlt] |

### Kritische Mängel (sofort beheben)
[FAIL-Punkte mit konkreten Fix-Anweisungen auflisten]

### Empfehlungen (sollte behoben werden)
[PARTIAL-Punkte mit Verbesserungsvorschlägen auflisten]

### Bestanden
[PASS-Punkte zur Bestätigung auflisten]

### Nicht geprüft
[Pflicht-Sektion, immer ausgeben -- auch wenn leer: „keine" explizit vermerken.
Jede Dimension, die am Markdown-Material nicht belegbar war (typischerweise
Seitenzahl/Umfang, Formatierung/Typografie, Bilddatei-Existenz, tatsächliche
Unterschrift), mit kurzer Begründung, warum sie nicht geprüft werden konnte
und wie der User sie prüfen lassen kann (Werte nennen oder Export abwarten).]
```

## Wichtige Regeln

- Immer zuerst `${CLAUDE_PLUGIN_ROOT}/skills/submission-checker/references/fh-leibniz.md` prüfen -- hochschulspezifische Regeln überschreiben allgemeine Konventionen
- Ist die Datei nicht verfügbar, deutsche Standard-Konventionen nutzen und vermerken, dass hochschulspezifische Prüfung nicht möglich war
- Formatierung und Seitenzahl nie als PASS/FAIL ausgeben, wenn die Werte nur aus dem Markdown-Text geschätzt statt vom User genannt wurden -- Formatfehler sind zwar der häufigste Grund für Abgabeverzögerungen, aber ein erfundenes PASS ist schlimmer als ein ehrliches „Nicht geprüft"
- Zwischen harten Anforderungen (FAIL = keine Abgabe möglich) und weichen Empfehlungen (PARTIAL = sollte behoben werden) unterscheiden
- Ist die Arbeit noch nicht fertig, Check auf vorhandene Abschnitte laufen lassen und offene Prüfpunkte benennen
- Ergebnisse auf Deutsch präsentieren, wenn `./academic_context.md` Deutsch als Sprache angibt
- Die „Nicht geprüft"-Sektion im Output ist Pflicht, nicht optional -- sie fehlt nie, auch wenn sie leer ist

## Few-Shot-Beispiele

### Stil: Formalia-Bewertung

**Schlecht** (Grund: PASS ohne dokumentierte Prüfung):

> "Formatierung ist OK."

**Schlecht** (Grund: erfundener Layout-Befund -- Zeilenabstand und Seiten
stehen im Markdown-Material nicht):

> "Formatierung: PARTIAL. Zeilenabstand 1.0 statt geforderten 1.5
> (Seiten 12-18)."

**Gut** (Grund: ehrliche Nicht-Prüfung plus Weg zur Prüfbarkeit):

> "Formatierung: NICHT GEPRÜFT. Zeilenabstand und Ränder entstehen erst
> beim Export. Nenne mir die Werte aus dem Word-Dokument, dann gleiche ich
> sie gegen die FH-Vorgaben ab."

**Gut** (Grund: dimensionaler Score, weil der User die Werte selbst genannt hat):

> "Formatierung: PARTIAL. Dein genannter Zeilenabstand 1.0 verfehlt die
> geforderten 1.5. Fix: Formatvorlage 'Standard' auf 1.5 setzen."
