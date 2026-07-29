---
name: literature-excel
description: >
  Verwende diesen Skill für natürlichsprachige Excel-/Tabellen-Wünsche mit
  klarem Literaturbezug. Trigger-Phrasen: "Excel-Übersicht meiner Literatur",
  "Literaturübersicht / Literaturuebersicht als Excel", "Excel aus meinen
  Papers", "Literaturliste als Excel exportieren", "Paper-Liste als
  Excel-Tabelle".
  Fängt genau diese Anfragen vor dem generischen `document-skills:xlsx`-Skill
  ab und leitet sie zur Literatur-Sheet-Spezifikation in
  `/academic-research:excel` (`commands/excel.md`) weiter — vier Sheets
  (Literaturübersicht, Cluster-Analyse, Kapitel-Zuordnung, Datenblatt) mit
  5D-Scores und Cluster-Farbcodierung, die dieser Skill nicht dupliziert.
  NICHT für literaturfremde Excel-Wünsche (z. B. Haushaltsbudget, generische
  Kalkulationstabelle) — dort greift `document-skills:xlsx` direkt.
license: MIT
allowed-tools:
  - Read
  - Bash(ls ~/.academic-research/sessions/*)
  - Skill(document-skills:xlsx)
---

# Literatur-Excel-Router

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Löst die Trigger-Kollision zwischen `/academic-research:excel` und dem
generischen `document-skills:xlsx`-Skill (Issue #447): Der Command trägt
`disable-model-invocation: true` und ist damit nur per explizitem Slash-Aufruf
erreichbar, während der externe xlsx-Skill sich selbst über eine sehr breite
Beschreibung aktiviert und deshalb jede natürlichsprachige Excel-Anfrage
gewinnt — auch literaturbezogene. Dieser Skill fängt genau die
literaturbezogenen Anfragen vorher ab, mit eng gefassten Trigger-Phrasen
(siehe Frontmatter).

## Spezifikation vs. Engine

`commands/excel.md` ist die Spezifikation (welche Sheets, welche Spalten,
welche Farbcodierung); `document-skills:xlsx` ist die Engine, die das
Workbook tatsächlich schreibt. Dieser Skill dupliziert die Spezifikation
nicht, sondern verweist ausschließlich auf sie.

## Umsetzung

1. Lies `commands/excel.md` vollständig (Abschnitte „Erwartete Sheets" und
   „Umsetzung").
2. Führe dessen Schritte 1–4 wörtlich aus, so als wäre
   `/academic-research:excel` ohne Argumente aufgerufen worden — inklusive
   der Verfügbarkeitsprüfung aus dessen Abschnitt „Excel-Backend" vor dem
   ersten `document-skills:xlsx`-Aufruf.
3. Erkennt der User-Auftrag zusätzlich `--context`-Bedarf (explizite
   Kapitel-Zuordnung gewünscht), wende Schritt 2 aus `commands/excel.md`
   entsprechend an.
4. Ergebnis wie in `commands/excel.md` Schritt 4 präsentieren.

## Abgrenzung

- Nur bei erkennbarem Literaturbezug aktivieren (siehe Trigger-Phrasen im
  Frontmatter). Excel-/Tabellen-Wünsche ohne Literaturbezug (Budget,
  generische Kalkulationstabelle) bleiben beim generischen
  `document-skills:xlsx`-Skill.
- Definiert keine eigene, abweichende Sheet-Struktur — Single Source of
  Truth bleibt `commands/excel.md`.
- Kein Ersatz für `/academic-research:pickup` (Bibliotheks-Pickup-Liste,
  eigene 4-Sheet-Struktur nach Verfügbarkeitsstatus): dessen Trigger-Phrasen
  sind bereits eng genug (z. B. „Pickup-Liste"), um nicht mit dem
  generischen xlsx-Skill zu kollidieren — ein eigener Router-Skill ist dafür
  nicht nötig (Abgleich siehe `commands/pickup.md`).
