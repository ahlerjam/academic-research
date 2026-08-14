---
name: latex-export
description: Use this skill for LaTeX-Output / .tex-Export. Triggers on "Kapitel exportieren / übersetzen / uebersetzen", "Thesis als .tex", "BibTeX aus Vault", "/academic-research:latex". Markdown → .tex plus .bib aus dem Vault (biblatex, DIN-1505).
license: MIT
allowed-tools:
  - Bash
  - Read
  - Write
---

# LaTeX-Export

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du fortfährst.

## Trigger-Wrapper

Dieser Skill fängt natürlichsprachige LaTeX-Export-Anfragen ab und leitet an
den Command weiter: Lies `commands/latex.md` vollständig und führe dessen
Schritte 1–4 aus, so als wäre `/academic-research:latex` mit den erkannten
Argumenten aufgerufen worden. `commands/latex.md` ist die einzige Quelle für
Ablauflogik, Fehlerpfade und Renderer-Details — sie wird hier nicht dupliziert.

## Abgrenzung

`latex-export` erzeugt `.tex`/`.bib` aus dem Vault. Für Word/PDF siehe
`word-export`, für ein Einzelzitat aus einer PDF (one-shot, keine
Vault-weite Bibliography) siehe `citation-extraction`.

## Verbatim-Guard

Hook `hooks/verbatim-guard.mjs` schützt `*.tex`-Writes (wie `kapitel/*.md`).
