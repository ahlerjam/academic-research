# Academic-Writing-Prinzipien (Auszug: Figures/Tables, Bibliography, Struktur)

Quelle: andrehuang/academic-writing-agents, `principles/academic-writing.md`
(MIT-Lizenz), abgerufen 2026-07-30 via GitHub-API.
https://github.com/andrehuang/academic-writing-agents

Der Originalkatalog umfasst 30 Prinzipien in 6 Kategorien (A–F). Dieser
Auszug enthält nur die für `latex-layout-auditor` relevanten Prinzipien aus
Kategorie D (Figures & Tables), plus A3 (Struktur/Reihenfolge im Quelltext)
und E3 (Bibliography Hygiene). Das Original nennt in Kategorie D explizit
`latex-layout-auditor` als einen der primär zuständigen Agenten.

## A3. Figure/Table Definition Order

> Ensure that figure/table definition order in the source matches the order
> they are first mentioned and discussed in the text. Teaser figures may
> appear early but must still be discussed promptly.

**Common violations**: LaTeX source defines Figure 5 before Figure 3; a
figure is `\input`'d early but not referenced until much later.

Übertragen auf Kapitel-Nummerierung (Dimension 4 dieses Skills): dieselbe
Logik gilt für `\chapter{}`/`\section{}`-Reihenfolge im Quelltext.

## D1. Active Figure Use

> Use figures to explain or illustrate complicated concepts. If a concept is
> hard to convey in text alone, create a figure.

**Common violations**: long stretches of dense text with no visual support;
figures that decorate rather than explain.

## D2. Cross-Reference All Floats

> Never let any figure or table "just be there." Every float must be
> explicitly referenced and discussed in the surrounding text.

**Common violations**: figures placed in the document but never mentioned
with `\ref`; tables referenced once without discussion of their content.

Grundlage für Dimension 6 dieses Skills (unbenutzte `\label{}`-Definitionen).

## D3. Figure-Text-Caption Consistency

> Always match what the figure shows, what the caption says, and what the
> body text says. If they describe the same concept differently, reconcile
> them.

**Common violations**: caption describes elements not visible in the
figure; body text says "top-left" when the item is bottom-right.

## D4. One Figure, One Message

> Do not layer multiple stories onto one visualization. If a figure answers
> two questions, consider splitting.

## D6. Figure Row Alignment

> Use `[t]` alignment on subfigures in multi-row grids to ensure rows align
> at their tops. `[b]` alignment causes visual misalignment when subfigures
> in a row have different heights. Add explicit height constraints
> (`\includegraphics[height=X]`) when images within a row have different
> aspect ratios.

**Common violations**: using `[b]` alignment in subfigure grids (the
default in many templates); mixing raster and vector formats without
height normalization.

## D7. Figure Caption Self-Sufficiency

> A caption should be understandable without reading the body text. It
> should state what the figure shows, define any abbreviations or symbols
> used in the figure, and highlight the key takeaway.

**Common violations**: captions that reference terms defined only in the
body text; captions missing units on reported quantities.

Grundlage für Dimension 5 dieses Skills (Bildunterschriften-Format).

## E3. Bibliography Hygiene

> Bibliography entries should be complete, consistent, and up-to-date.
> Check: (1) every entry has the required fields for its type, (2) title
> capitalization is protected with braces for proper nouns and acronyms
> (e.g., `{ImageNet}`, `{BERT}`), (3) arXiv-only citations are updated to
> their published versions when available, (4) author names are consistent
> across entries, (5) venue names are consistent, (6) no "?" markers appear
> in the compiled PDF (indicating unresolved references).

**Common violations**: inconsistent venue abbreviations; title-cased
titles without brace protection causing lowercase output; duplicate bib
entries under different keys.

Grundlage für die Zitierstil-Konsistenz-Prüfung dieses Skills (ergänzend zu
Dimension 2, die nur die Kommando-Korruption selbst prüft).
