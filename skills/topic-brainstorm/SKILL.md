---
name: topic-brainstorm
description: Use this skill when the user needs help finding or evaluating a thesis topic. Triggers on "welches Thema?", "Themenfindung", "Idee evaluieren", "Thema gesucht", "ich brauche ein Thema", "welches Thema lohnt", "Thema für Bachelorarbeit / Thema fuer Bachelorarbeit", "Thema für Masterarbeit", or when academic-context is missing a topic. Fokus auf strategische Themensuche und Bewertung; Schärfung einer bestehenden Forschungsfrage übernimmt `research-question-refiner`.
license: MIT
allowed-tools:
  - Bash
  - Read
  - Write
---

# Topic-Brainstorm Skill

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

> **Override Vorbedingungen:** Kein bestehendes `./academic_context.md` erforderlich —
> dieser Skill hilft dabei, das Thema erst zu finden.

## Übersicht

Unterstützt den User bei der strategischen Themenfindung: 3-5 Topic-Kandidaten
mit Feasibility-, Novelty- und Career-Fit-Scores, 2-3 Forschungsfragen pro
Kandidat und ein Pilot-Paper-Set. Übergang zu `research-question-refiner` nahtlos.

## Abgrenzung

Hilft beim Finden eines Themas (Erstanlage/Bewertung).
Für Schärfung einer bestehenden Forschungsfrage → `research-question-refiner`.
Für Gliederung und Methodik → `advisor` / `methodology-advisor`.

## Kontext-Dateien

- Lesen: `./academic_context.md` (falls vorhanden — Studiengang, Präferenzen)
- Schreiben: `./academic_context.md` — Thema des gewählten Top-Topics eintragen

## Core-Workflow

### Schritt 1: Eingaben sammeln

Stelle dem User sechs strukturierte Fragen via `AskUserQuestion`. Fach,
Arbeitstyp, Umfang und Interessen sind Pflichtangaben — ohne sie darf kein
Kandidat entworfen werden (Schritt 2):

```
Für eine gute Themenempfehlung brauche ich sechs Angaben:

1. Studienrichtung? (Pflicht)
   - Wirtschaftsinformatik (Bachelor/Master)
   - BWL / Betriebswirtschaft
   - Informatik
   - Maschinenbau
   - Andere → freitext

2. Arbeitstyp? (Pflicht, konsistent zu academic-context "### Arbeit"-Feld "Typ")
   - Bachelorarbeit
   - Masterarbeit
   - Hausarbeit
   - Seminararbeit
   - Facharbeit
   - Andere → freitext

3. Umfang? (Pflicht, z.B. Seiten- oder Wortzahl, freitext — z.B. "60 Seiten", "12000 Wörter")

4. Interessensgebiete (Pflicht, frei, z.B. "Cyber Security, KI, Nachhaltigkeit")

5. Zeitbudget?
   - 3 Monate
   - 6 Monate
   - 12 Monate

6. Datenzugang?
   - Public Datasets (Kaggle, STATISTA, Eurostat usw.)
   - Literatur-Only (kein eigener Datensatz)
   - Interview-fähig (Zugang zu Experten/Unternehmen)
   - Unternehmensdaten (NDA-Umgebung)
```

### Schritt 2: Themenkandidaten entwerfen und scoren

**Es gibt keine feste Themenliste.** Du (das Modell) entwirfst selbst 3-5
Kandidaten, die zu Studienrichtung, Arbeitstyp, Umfang, Interessensgebieten,
Zeitbudget und Datenzugang des Users passen — die Urteilsarbeit liegt hier,
nicht in `scorer.py`. Zwei Anfragen aus unterschiedlichen Fächern (oder mit
unterschiedlichem Arbeitstyp/Umfang) müssen zu erkennbar unterschiedlichen,
fachlich passenden Kandidaten führen — niemals dieselben Titel unabhängig
vom Fach.

Für jeden Kandidaten legst du fest:

- `title`: konkreter, spezifischer Arbeitstitel (kein Gattungsbegriff)
- `keywords`: 3-6 Schlagworte
- `reason`: 1-2 Sätze, **warum** das Thema zur genannten Studienrichtung,
  dem Arbeitstyp, den Interessen und dem Zuschnitt (Budget/Datenzugang)
  passt — Pflichtfeld, nicht leer lassen
- `feasibility_note`: 1 Satz Machbarkeitshinweis — passt der Umfang
  (Seiten-/Wortzahl) und das Zeitbudget realistisch zum Methodenaufwand?
  Pflichtfeld
- `source_note`: 1 Satz Hinweis zur Quellenlage — grobe Einschätzung, ob
  ausreichend Literatur/Daten zu erwarten ist (keine echte Recherche, nur
  Heuristik). Pflichtfeld
- `base_feasibility` (0-10): deine Einschätzung nach Datenverfügbarkeit +
  Methoden-Match, siehe Orientierungswerte in
  [`references/scoring-criteria.md`](references/scoring-criteria.md)
- `base_novelty` (0-10): deine Einschätzung der Forschungslücke
- `base_career_fit` (0-10): deine Einschätzung der Passung zu Studienrichtung
  und Berufsbild, siehe Orientierungswerte in
  [`references/scoring-criteria.md`](references/scoring-criteria.md)
- `research_questions`: 2-3 Forschungsfragen
- `pilot_papers`: 1-3 plausible Referenzen (Autor, Jahr, Titel/Venue) — als
  Hinweis, keine Gewissheit für reale Existenz

Beispiel-Snippet (gekürzt, ein Kandidat):

```json
[
  {
    "title": "Preisstrategien im stationären Einzelhandel unter Inflationsdruck",
    "keywords": ["pricing", "einzelhandel", "inflation"],
    "reason": "Passt zur BWL, da Preistheorie und Marktbeobachtung Kernkompetenzen sind, und zum Interesse 'Handel'.",
    "feasibility_note": "Mit 6 Monaten und Public Datasets (Statista, Eurostat) im Umfang einer 60-seitigen Bachelorarbeit realistisch bearbeitbar.",
    "source_note": "Preistheorie ist breit erforscht — genug Sekundärliteratur, aktuelle Inflationsdaten aber noch dünn.",
    "base_feasibility": 7.0,
    "base_novelty": 6.0,
    "base_career_fit": 8.5,
    "research_questions": [
      "Wie reagieren Einzelhändler auf anhaltende Inflation bei der Preissetzung?",
      "Welche Preisstrategien wirken sich am stärksten auf die Kundenbindung aus?"
    ],
    "pilot_papers": ["Simon & Fassnacht (2019): Preismanagement, Springer Gabler"]
  }
]
```

Schreibe das Array in eine temporäre JSON-Datei und rufe den Scorer auf (er
normalisiert Feasibility über Budget-/Datenzugang-Modifikatoren und Novelty
über den Interessens-Overlap; Career-Fit, `reason`, `feasibility_note` und
`source_note` reicht er unverändert durch; Fach/Arbeitstyp/Umfang/Interessen
landen unverändert im `context`-Objekt der Ausgabe):

```bash
python ${CLAUDE_PLUGIN_ROOT}/skills/topic-brainstorm/scripts/scorer.py \
  --topics-json <pfad-zur-json-datei> \
  --interests "<INTERESSEN>" \
  --field "<STUDIENRICHTUNG>" \
  --work-type "<ARBEITSTYP>" \
  --scope "<UMFANG>" \
  --budget "<ZEITBUDGET>" \
  --data-access "<DATENZUGANG>" \
  --output-mode full
```

### Schritt 3: Ergebnisse präsentieren

Präsentiere die 3-5 Kandidaten in dieser Tabellenform:

```
## Topic-Kandidaten

| # | Thema | Feasibility | Novelty | Career-Fit | Gesamt |
|---|-------|-------------|---------|------------|--------|
| 1 | [Titel] | X/10 | X/10 | X/10 | XX/30 |
...

**Empfehlung: [Top-Topic-Titel]** (Score: XX/30)
```

Zeige pro Topic:
- Den `reason` — warum das Thema zum Zuschnitt (Fach/Arbeitstyp/Umfang) passt
- Den `feasibility_note` — Machbarkeitshinweis
- Den `source_note` — Hinweis zur Quellenlage
- Die 2-3 Forschungsfragen
- Das Pilot-Paper-Set (1-3 Referenzen)

Score-Legende (aus `${CLAUDE_PLUGIN_ROOT}/skills/topic-brainstorm/references/scoring-criteria.md`):
- **Feasibility**: Datenverfügbarkeit + Zeitaufwand + Methoden-Match
- **Novelty**: Lücken-Indikator (Anzahl recent vs. older papers in area)
- **Career-Fit**: Deine Einschätzung der Passung zu Studienrichtung + Berufsbild (aus Schritt 2)

### Schritt 4: User-Auswahl und Context-Update

Frage den User, welches Thema er wählt:

```
Welches Thema möchtest du weiterverfolgen?
(1) [Titel 1] — Empfehlung
(2) [Titel 2]
...
Oder: Eigene Variante (freitext)
```

Nach Auswahl:
1. Rufe den Scorer erneut mit derselben `--topics-json`-Datei aus Schritt 2
   plus `--write-context ./academic_context.md` auf (oder schreibe das Thema
   direkt in die Datei)
2. Bestätige die Speicherung: "Das Thema wurde in `academic_context.md` eingetragen."

### Schritt 5: Handover zu research-question-refiner

Beende mit einem Soft-Handover-Hinweis:

```
Das Thema ist jetzt in deinem akademischen Kontext gespeichert.

Nächster Schritt: Forschungsfrage präzisieren
→ Sag "Forschungsfrage formulieren" oder "Fragestellung schärfen",
  um den `research-question-refiner` zu starten und aus den
  vorgeschlagenen Forschungsfragen eine präzise Hauptfrage zu entwickeln.
```

## Scoring-Dimensionen

Drei Scores (je 0-10), Summe ergibt den Gesamtscore (0-30).
Details: `${CLAUDE_PLUGIN_ROOT}/skills/topic-brainstorm/references/scoring-criteria.md`

- **Feasibility**: Datenverfügbarkeit + Zeitaufwand + Methoden-Match
- **Novelty**: Forschungslücken-Heuristik (Stichwort-Überschneidung mit Interessensgebieten)
- **Career-Fit**: Deine (Modell-)Einschätzung der Schlagwort-/Themen-Passung zur
  Studienrichtung — als `base_career_fit` je Kandidat in Schritt 2 festgelegt

Scoring-Kriterien (Orientierungswerte für Datenverfügbarkeit, Zeitbudget
und Studienrichtung) siehe `${CLAUDE_PLUGIN_ROOT}/skills/topic-brainstorm/references/scoring-criteria.md`.

## Wichtige Regeln

- **Keine feste Themenliste** — Kandidaten fach-, arbeitstyp-, umfangs- und
  interessenspassend selbst entwerfen (Schritt 2), nie aus einer
  vordefinierten Liste kopieren
- **Keine Themen aufdrängen** — 3-5 Optionen zeigen, User entscheidet
- **Scores transparent erklären** — Immer die Scoring-Kriterien kurz erläutern
- **Pilot-Papers sind Hinweise, keine Gewissheiten** — Darauf hinweisen, dass reale Literaturrecherche folgen muss
- **Vor dem Schreiben bestätigen** — Explizit fragen, ob das Thema in `academic_context.md` gespeichert werden soll
- **Handover sanft** — Nicht erzwingen; research-question-refiner als Hinweis, nicht als Pflicht
- **Deutsche Ausgabe** — Alle User-facing Texte auf Deutsch
