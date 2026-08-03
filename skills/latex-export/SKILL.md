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

## Workflow

`/academic-research:latex --kapitel <n>|all --output <datei.tex> [--bib <datei.bib>] [--template <uni>]`
ruft `${CLAUDE_PLUGIN_ROOT}/skills/latex-export/scripts/export_thesis.py` auf:

1. Kapitel aus `kapitel/` auflösen (`<n>` oder `all`, numerisch sortiert)
2. `render_tex.py` je Kapitel → `.tex` (Pandoc bevorzugt, Custom-Fallback), verkettet
3. Optional: Uni-Template `~/.academic-research/library-profiles/<uni>.tex.template`
   (`%%CONTENT%%`-Platzhalter; fehlt sie, Export ohne Vorlage)
4. `build_bib.py` → `.bib` aus Vault, Pfad unabhängig von `--output`

## Abgrenzung zu citation-extraction und word-export

`latex-export` = vollständiger `.bib`-Dump aller Vault-Papers + `.tex`-Konvertierung.
`citation-extraction` = Einzelzitat aus PDF (one-shot), keine Vault-weite Bibliography.
`word-export` = Word/PDF statt `.tex`/`.bib`, siehe dort.

## Fehlerpfade

- **Pandoc fehlt:** Custom-Renderer-Fallback (kein Absturz). Pandoc installieren empfehlen.
- **Vault leer:** Leere `.bib` + Meldung „Vault leer – Papers via `add` hinzufügen."
- **Template nicht gefunden:** Ausgabe ohne Vorlage + Meldung „Template `<uni>` fehlt."

## Verbatim-Guard

Hook `hooks/verbatim-guard.mjs` schützt `*.tex`-Writes (wie `kapitel/*.md`).
