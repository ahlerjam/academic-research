# Einstieg nach Vorhaben — welche Skills wann

[← Doku-Übersicht](../README.md)

Die übrige Doku ist nach Komponenten geordnet: Skills, Agents, Commands, jedes für sich
beschrieben. Wer neu ist, hat aber kein Komponentenproblem, sondern ein Vorhaben — eine
systematische Übersichtsarbeit, eine empirische Qualifikationsarbeit mit eigener
Erhebung, eine Literaturarbeit, einen Zeitschriftenbeitrag. Diese Seite sortiert genau
danach: vier Wege, je Weg die real existierenden Skills in der Reihenfolge, in der sie
gebraucht werden, mit den Abhängigkeiten dazwischen. Was ein einzelner Skill tut, steht
nicht hier noch einmal — dafür verweist jeder Abschnitt auf die
[Skills-Übersicht](../reference/skills.md).

## Kürzester Weg: Installation bis zum ersten Ergebnis

Unabhängig vom Vorhaben ist der kürzeste Weg vom leeren Ordner bis zum ersten
verifizierten Zitat immer derselbe: [Erste Schritte](getting-started.md) — ein
durchgehender Ablauf, rund 20 Minuten, ohne Sprung auf eine andere Seite. Alle vier Wege
unten setzen dort auf; wiederholt wird das hier nicht.

## Systematische Übersichtsarbeit

**Annahme:** Diese Einteilung folgt der Themenbeschreibung in Issue #611 ("typische
Wege"), nicht einer Nutzerbefragung — die vier Vorhaben sind benannt, nicht belegt.

Davor steht [Erste Schritte](getting-started.md): Ohne gefülltes `academic_context.md`
haben die folgenden Skills nichts zu lesen.

Reihenfolge: `academic-context` → `preregistration` → `parallel-screening` →
`source-quality-audit` → `prisma-flow` → `citation-extraction` → `chapter-writer`.

Abhängigkeit: `preregistration` muss vor der ersten Suche stehen, nicht danach — das
Protokoll legt Suchstrategie und Ein-/Ausschlusskriterien fest, die `parallel-screening`
erst danach anwenden kann. `prisma-flow` wiederum liest die Zähler, die das Screening
hinterlässt, und ergibt vor dessen Abschluss kein vollständiges Bild.

## Empirische Qualifikationsarbeit mit eigener Erhebung

**Annahme:** Wie beim vorigen Weg — aus der Themenbeschreibung in Issue #611 abgeleitet,
nicht aus einer Nutzerbefragung.

Setzt voraus, dass [Erste Schritte](getting-started.md) gelaufen ist und die Methodik
grob feststeht (Schritt 5 im [Walkthrough](walkthrough.md)).

Reihenfolge: `academic-context` → `research-question-refiner` → `methodology-advisor` →
`instrument-design` → `data-management-plan` → `qualitative-coding` (bei qualitativem
Design) beziehungsweise `quantitative-analysis` (bei quantitativem Design) →
`chapter-writer`.

Abhängigkeit: `instrument-design` braucht eine gewählte Methodik als Eingabe — ohne
`methodology-advisor` fehlt die Grundlage, gegen die der Interviewleitfaden oder
Fragebogen rückverweist. `data-management-plan` gehört vor die Erhebung, nicht danach,
weil er auch Speicherung und rechtliche Aspekte der noch zu sammelnden Daten plant.

## Literaturarbeit

**Annahme:** Wie bei den anderen drei Wegen — aus Issue #611 übernommen, nicht separat
belegt.

Davor steht [Erste Schritte](getting-started.md); ein eigenes Erhebungsinstrument
entfällt hier, anders als beim vorigen Weg.

Reihenfolge: `academic-context` → `research-question-refiner` → `citation-extraction` →
`reading-notes` → `literature-gap-analysis` → `extraction-matrix` → `chapter-writer`.

Abhängigkeit: `literature-gap-analysis` setzt einen aufgebauten Quellenbestand
(`literature_state.md` via `/search`) und die Gliederung in `academic_context.md`
voraus. Damit ist die zweite Suchrunde nach `reading-notes` möglich, ohne erst
`chapter-writer` aufzurufen — der Skill analysiert Abdeckung pro Kapitelthema, nicht
pro geschriebenem Entwurf.

## Zeitschriftenbeitrag

**Annahme:** Ebenfalls aus der Themenbeschreibung in Issue #611, nicht durch eine eigene
Erhebung unter Autor:innen belegt.

Setzt voraus, dass [Erste Schritte](getting-started.md) gelaufen ist; Literaturarbeit
oder empirische Erhebung sind hier als vorgelagerter Weg gedacht, nicht Teil dieser
Sequenz.

Reihenfolge: `academic-context` → `chapter-writer` → `abstract-generator` →
`reviewer-response`.

Abhängigkeit: `reviewer-response` setzt eine bereits eingereichte und begutachtete
Fassung voraus — der Skill schreibt einen Point-by-Point-Response auf vorhandene
Reviewer-Kommentare, nicht das Manuskript selbst.

## Wie diese Seite zu docs/README.md steht

Die [Doku-Übersicht](../README.md) gliedert nach Publikum (Einsteiger, Praktiker,
Beitragende); diese Seite gliedert quer dazu nach Vorhaben. Beide führen zu denselben
Zielseiten — welcher Einstieg passt, hängt davon ab, ob du weißt, was du schreibst, oder
erst wissen willst, wo du in der Doku stehst.
