---
name: defense-prep
description: Use this skill when the user prepares for the oral thesis defense / Kolloquium. Triggers on "Verteidigung vorbereiten", "Kolloquium vorbereiten", "für die Verteidigung / fuer die Verteidigung", "Fragenkatalog Kolloquium", "Prüfungsgespräch / Pruefungsgespraech", "defense prep", or when submission is done and the oral exam is next. Leitet aus den fertigen Kapiteln eine Vortragsgliederung mit Zeitrahmen und Kernaussage je Kapitel sowie einen an Methodik und Limitationen gebundenen Fragenkatalog ab; für den Foliensatz selbst → `slide-export`.
license: MIT
allowed-tools:
  - Read
---

# Verteidigungsvorbereitung

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Bereitet die mündliche Verteidigung (Kolloquium/Disputation) vor: leitet aus
den fertigen Kapiteln eine Vortragsgliederung mit Zeitbudget und Kernaussage
pro Kapitel ab, dazu einen Fragenkatalog, der an die tatsächlich gewählte
Methodik und die im Fazit benannten Limitationen gebunden ist -- keine
generischen Prüfungsfragen aus dem Gedächtnis.

## Abgrenzung

Liefert Vortragsgliederung, Kernaussagen und Fragenkatalog als **Text-Output**.
Für den Foliensatz selbst → `slide-export`. Liefert **keine**
Bewertungsprognose (Notenschätzung) -- dafür gibt es am Textmaterial keine
belastbare Grundlage.

## Kontext-Dateien

- `./academic_context.md` -- Arbeitstyp, Forschungsfrage, Methodik-Feld
  (Pflichtquelle für den Methodik-Teil des Fragenkatalogs)
- `kapitel/*.md` -- alle vorhandenen Kapitel, numerisch sortiert (dieselbe
  Auflösung wie `latex-export`/`word-export`/`slide-export`)
- `./writing_state.md` -- Wortzahlen je Kapitel, falls vorhanden, für die
  proportionale Zeitbudget-Verteilung in Schritt 3
- Fazit-Kapitel (letztes Kapitel der Gliederung) -- Quelle für die
  Limitationen-Fragen

## Core-Workflow

### 1. Kontext und Kapitel laden

Lies `./academic_context.md`. Fehlt sie: `academic-context`-Skill triggern.
Lies alle `kapitel/*.md`, numerisch sortiert. Ist kein Kapitel vorhanden,
abbrechen und auf `chapter-writer` verweisen -- ohne Kapiteltext keine
Kernaussagen ableitbar.

### 2. Zeitrahmen klären

Frage den User via `AskUserQuestion` nach der verfügbaren Vortragszeit.
Fehlt eine Angabe, Default nach Arbeitstyp: Bachelorarbeit 15-20 Min.,
Masterarbeit 20-30 Min., Hausarbeit/Seminararbeit 10-15 Min. Der Zeitrahmen
bestimmt das Budget pro Gliederungspunkt in Schritt 3.

### 3. Vortragsgliederung mit Zeitbudget

Verteile die genannte Gesamtzeit proportional zur Kapitelgewichtung
(Wortzahl aus `./writing_state.md`, ersatzweise Kapitelanzahl):

| Abschnitt | Richtwert am Gesamtbudget |
|-----------|---------------------------|
| Einleitung/Motivation | 15 % |
| Theorie/Stand der Forschung | 15 % |
| Methodik | 20 % |
| Ergebnisse/Diskussion | 35 % |
| Fazit/Ausblick | 15 % |

Richtwerte an die tatsächliche Kapitelstruktur anpassen, nicht stur
übernehmen -- Arbeiten ohne empirischen Teil verschieben Gewicht zu
Theorie/Diskussion. Die Minutensumme muss der genannten Gesamtzeit
entsprechen.

### 4. Kernaussage je Kapitel

Pro Kapitel genau eine Kernaussage (ein Satz) aus dem tatsächlichen
Kapiteltext ableiten -- der zentrale Befund oder die zentrale These, nicht
die Kapitelüberschrift. Kapitel ohne extrahierbaren Fließtext (nur
Gliederungspunkte/Platzhalter): keine Kernaussage erfinden, im Output als
„noch kein Fließtext" kennzeichnen und den User um den Stand bitten
(Preamble „Keine Fabrikation").

### 5. Fragenkatalog

Zwei Pflichtkategorien, beide an das tatsächliche Material gebunden:

- **Methodik-Fragen** -- abgeleitet aus dem Methodik-Feld in
  `./academic_context.md` (z. B. bei „12 Interviews, Inhaltsanalyse nach
  Mayring": Fragen zu Stichprobenziehung, Sättigung, Kategorienbildung,
  Intercoder-Reliabilität).
- **Limitationen-Fragen** -- abgeleitet aus der Limitationen-Sektion des
  Fazit-Kapitels. **Fehlt diese Sektion**, keine generischen Limitationen
  erfinden: den User explizit darauf hinweisen, dass das Fazit keine
  Limitationen benennt, und nachfragen, ob er sie ergänzen möchte oder der
  Fragenkatalog ohne diese Kategorie ausgegeben werden soll.

Optionale dritte Kategorie **Erwartbare Nachfragen** zu Forschungsfrage und
Abgrenzung, wenn der User danach fragt.

## Output-Format

```
## Verteidigungsvorbereitung: [Arbeitstitel]

**Zeitrahmen:** [N] Minuten | **Arbeitstyp:** [Typ]

### Vortragsgliederung
| Abschnitt | Zeit (Min.) | Kernaussage |
|-----------|-------------|-------------|
| ...       | ...         | ...         |

### Fragenkatalog

**Methodik**
1. [Frage]

**Limitationen**
1. [Frage]
(oder: „Fazit-Kapitel benennt keine Limitationen -- Rückfrage an den User
ausstehend.")
```

## Wichtige Regeln

- Zeitbudget-Summe muss exakt der vom User genannten Gesamtzeit entsprechen
- Keine Kernaussage ohne Beleg im Kapiteltext -- bei Zweifel nachfragen statt erfinden
- Fragenkatalog nie mit generischen Prüfungsfragen aus dem Gedächtnis auffüllen -- nur was Methodik-Feld und Fazit-Kapitel tatsächlich hergeben
- Fehlt `./academic_context.md` oder sind keine Kapitel vorhanden, Voraussetzung klar benennen statt mit Platzhaltern zu arbeiten
- Ergebnisse auf Deutsch präsentieren, wenn `./academic_context.md` Deutsch als Sprache angibt

## Few-Shot-Beispiele

### Stil: Kernaussage

**Schlecht** (Grund: Kapitelüberschrift statt Befund):

> "Kapitel 4: Ergebnisse der Befragung"

**Gut** (Grund: konkreter Befund mit Zahl):

> "87 von 142 Befragten nutzen KI regelmäßig und erreichen dabei im
> Schnitt 0,4 Notenstufen bessere Prüfungsergebnisse."

### Stil: Methodik-Frage

**Schlecht** (Grund: generische Frage, nicht an gewählte Methodik gebunden):

> "Warum haben Sie diese Methode gewählt?"

**Gut** (Grund: bezieht sich auf konkrete Angabe aus academic_context.md):

> "Die Stichprobe umfasst 12 Interviews an drei FH-Standorten -- wie wurde
> Sättigung festgestellt, und warum nicht mehr Standorte einbezogen?"
