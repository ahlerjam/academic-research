---
name: latex-layout-auditor
description: >
  Verwende diesen Skill, um einen `latex-export`-Output auf LaTeX-spezifische
  Layout-Fehler zu prüfen / pruefen: Package-Konflikte, unvollständige
  Listen-Strukturen (fehlendes `\tightlist`), korrumpierte Zitationskommandos,
  Kapitel-Nummerierungssprünge, Bildunterschriften-Format,
  Cross-Referenzierung. Trigger-Phrasen: "LaTeX-Layout prüfen / pruefen",
  ".tex auditieren", "Listen-Struktur prüfen / pruefen", "tightlist Fehler",
  "Kapitel-Nummerierung prüfen / pruefen", "Package-Konflikte prüfen /
  pruefen", "Layout-Check vor Abgabe". Read-only: liest die .tex-Datei(en)
  und meldet konkrete Fundorte (Zeile + Snippet), ändert nichts.
license: MIT
allowed-tools:
  - Read
---

# LaTeX-Layout-Auditor

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Prüft eine oder mehrere `.tex`-Dateien (typischerweise der `latex-export`-Output)
auf typografische LaTeX-Layout-Regeln, die beim Export selbst entstehen können —
nicht auf Hochschul-Formalia (dafür `submission-checker`). Liest ausschließlich
(`allowed-tools: [Read]`), führt keine Skripte aus und schreibt nichts.

## Abgrenzung

- **`submission-checker`** prüft institutsspezifische Formalia auf
  Enddatei-Ebene: Seitenumfang, Pflichtabschnitte, Zeilenabstand,
  eidesstattliche Erklärung — hochschulspezifisch (`references/<variant>.md`).
  **`latex-layout-auditor`** prüft LaTeX-Layout-Regeln, die unabhängig von der
  Hochschule beim `.tex`-Export selbst entstehen: Listen-Strukturen,
  Zitationskommandos, Kapitel-Nummerierung, Package-Konflikte,
  Bildunterschriften-Format. Beide ergänzen sich; keiner ersetzt den anderen.
- **`latex-export`** erzeugt die `.tex`-Datei. **`latex-layout-auditor`**
  prüft sie danach, rein lesend. Bugs im Renderpfad selbst
  (`${CLAUDE_PLUGIN_ROOT}/skills/latex-export/scripts/render_tex.py`) werden hier nur als Finding
  erkannt und gemeldet, nicht behoben (Scope-Abgrenzung laut Issue #392) —
  ein Fix gehört in `latex-export`.

## Quelle

Die Checklisten-Dimensionen orientieren sich am 30-Prinzipien-Katalog aus
[andrehuang/academic-writing-agents](https://github.com/andrehuang/academic-writing-agents)
(MIT-Lizenz; Wortlaut-Übernahme mit Quellenhinweis laut Issue #392 erlaubt).
Auszug (Kategorie D „Figures & Tables“ + E3 „Bibliography Hygiene“ + A3
„Figure/Table Definition Order“): `references/academic-writing-agents-principles.md`.

## Checklisten-Dimensionen

Dimensionen 1–2 sind deterministisch per Musterabgleich prüfbar (Referenz-
implementierung: `scripts/check_layout.py`, `audit_tex(text) -> list[Finding]`,
separat pytest-getestet — der Skill selbst wendet dieselben Muster beim Lesen
an, statt das Skript zur Laufzeit auszuführen). Dimensionen 3–6 verlangen
Lesen + Bewertung anhand des Katalogs.

1. **Listen-Strukturen** — `\tightlist` ohne vorangehende
   `\providecommand{\tightlist}`- oder `\newcommand{\tightlist}`-Definition
   irgendwo im Dokument. Ohne Definition bricht `pdflatex` mit "Undefined
   control sequence \tightlist" ab (Digest-Befund #1, vgl. Issue #386, das
   den Renderpfad selbst gefixt hat — dieser Auditor erkennt dasselbe Muster
   auch in manuell editierten oder anders erzeugten `.tex`-Dateien).
2. **Zitationskommandos** — korrumpierte Kommandos wie
   `\textbackslash{}cite{key}` statt `\cite{key}` (Digest-Befund #2):
   entsteht, wenn ein bereits vorhandenes LaTeX-Kommando ein zweites Mal
   escaped wird. Gilt für `\cite`, `\citep`, `\citet`, `\parencite`,
   `\footcite`.
3. **Package-Konflikte** — `\usepackage`-Zeilen auf bekannte
   Inkompatibilitäten prüfen: `hyperref` muss vor `cleveref` geladen werden;
   `biblatex` und `natbib` nicht gleichzeitig; Encoding-Pakete (`inputenc`,
   `fontenc`) auf Konsistenz mit dem Dateiencoding.
4. **Kapitel-Nummerierungssprünge** (Prinzip A3) — Reihenfolge der
   `\chapter{}`/`\section{}`-Definitionen im Quelltext muss lückenlos sein
   und mit der im Fließtext diskutierten Reihenfolge übereinstimmen; keine
   Sprünge wie Kapitel 3 direkt nach Kapitel 1.
5. **Bildunterschriften-Format** (Prinzip D7, Caption Self-Sufficiency) —
   jede `\caption{}` muss eigenständig verständlich sein: keine Verweise auf
   nur im Fließtext definierte Abkürzungen, Einheiten bei Zahlenangaben.
6. **Cross-Referenzierung** (Prinzip D2) — jedes `\label{}` sollte
   mindestens einmal per `\ref{}`/`\autoref{}`/`\eqref{}` referenziert
   werden; unbenutzte Labels deuten auf verwaiste Floats hin.

## Workflow

1. `.tex`-Datei(en) per Read einlesen (Pfad vom User oder `latex-export`-Output).
2. Dimensionen 1–2 per Musterabgleich prüfen (siehe oben); Fundort = Zeile +
   Snippet.
3. Dimensionen 3–6 per Lesen + Bewertung gegen den Katalog-Auszug in
   `references/academic-writing-agents-principles.md` prüfen.
4. Output als Tabelle `Zeile | Regel | Fundort-Snippet | Kurzbeschreibung`,
   aufsteigend nach Zeile sortiert. Keine Funde → "Keine Layout-Verstöße
   gefunden".

## Nicht geprüft

Hochschul-Formalia (Seitenränder als Institutsvorgabe, Zeilenabstand,
Pflichtabschnitte, eidesstattliche Erklärung) → `submission-checker`. Echte
Kompilierbarkeit (ein tatsächlicher `pdflatex`-Lauf) → außerhalb des Scopes;
dieser Skill leistet nur statische Musteranalyse ohne Compiler-Aufruf. Beide
Lücken gehören verpflichtend in eine „Nicht geprüft"-Sektion des Outputs,
falls der User danach fragt — niemals stillschweigend als geprüft ausweisen.
