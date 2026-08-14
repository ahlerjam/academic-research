---
description: Exportiert Kapitel des aktuellen Projekts als .tex-Dateien und generiert eine biblatex-konforme .bib-Datei aus dem Vault.
disable-model-invocation: true
allowed-tools: Read, Write, Bash(pandoc *), Bash(python3 *), Agent(quality-reviewer)
argument-hint: --kapitel <n>|all --output <datei.tex> [--bib <datei.bib>] [--template <uni>]
---

# /academic-research:latex — LaTeX-Export

## Beschreibung

Exportiert Kapitel des aktuellen Projekts als `.tex`-Dateien und generiert eine biblatex-konforme `.bib`-Datei aus dem Vault.

## Syntax

```
/academic-research:latex --kapitel <n>|all --output <datei.tex> [--bib <datei.bib>] [--template <uni>]
```

## Parameter

| Parameter | Typ | Standard | Beschreibung |
|-----------|-----|---------|--------------|
| `--kapitel` | `<n>` oder `all` | — (Pflicht) | Kapitel-Nummer oder `all` für alle |
| `--output` | Dateipfad | — (Pflicht) | Ausgabedatei |
| `--bib` | Dateipfad | `output/refs.bib` | BibTeX-Ausgabe, unabhängig vom `--output`-Pfad |
| `--template` | Uni-Kürzel | — | Template aus `~/.academic-research/library-profiles/<uni>.tex.template` |

## Beispiele

```bash
# Einzelnes Kapitel exportieren
/academic-research:latex --kapitel 3 --output output/kap3.tex

# Alle Kapitel + BibTeX
/academic-research:latex --kapitel all --output output/thesis.tex --bib output/refs.bib

# Mit Uni-Template (LMU München)
/academic-research:latex --kapitel all --output output/thesis.tex --template lmu
```

## Ablauf

### Schritt 1 — Argumente parsen

- `KAPITEL` = Wert von `--kapitel` (Pflicht: Zahl oder `all`)
- `OUTPUT` = Wert von `--output` (Pflicht: Zielpfad der `.tex`-Datei)
- `BIB` = Wert von `--bib` (optional, Default `output/refs.bib`,
  unabhängig von `OUTPUT`)
- `TEMPLATE` = Wert von `--template` (optional, Uni-Kürzel)

### Schritt 2 — Skill laden

Skill `skills/latex-export/SKILL.md` wird geladen (nur Trigger-Wrapper,
prüft Vorbedingungen über `skills/_common/preamble.md`). Ablauflogik,
Fehlerpfade und Abgrenzung stehen ausschließlich in diesem Command
(siehe unten).

### Schritt 3 — Export ausführen

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/latex-export/scripts/export_thesis.py" \
  --kapitel "$KAPITEL" --output "$OUTPUT" \
  ${BIB:+--bib "$BIB"} ${TEMPLATE:+--template "$TEMPLATE"}
```

Das Skript bündelt intern:
1. Kapitel-Resolution aus `kapitel/` (Einzelkapitel oder alle, numerisch
   sortiert)
2. `render_tex.render_markdown_to_tex()` je Kapitel (Pandoc oder
   Custom-Renderer) + Verkettung in Datei-Reihenfolge
3. Optional: Uni-Template-Wrapping (`%%CONTENT%%`-Ersetzung); fehlt das
   Template, wird ohne Vorlage exportiert und eine Meldung auf stderr
   ausgegeben (kein Abbruch)
4. `build_bib.build_bib_from_vault()` → `.bib` nach `BIB` (unabhängig von
   `OUTPUT`)

### Schritt 4 — Ergebnis zeigen

Bei Erfolg (Exit-Code 0): Pfade von `.tex` und `.bib` sowie Kapitelanzahl
ausgeben. Erschien eine Template-Fallback-Meldung auf stderr, diese
zusätzlich anzeigen. Bei Exit-Code ≠ 0: die vom Skript ausgegebene
`FEHLER:`-Meldung (z. B. unbekanntes Kapitel) unverändert weitergeben.

## Abgrenzung zu citation-extraction und word-export

`latex-export` = vollständiger `.bib`-Dump aller Vault-Papers + `.tex`-Konvertierung.
`citation-extraction` = Einzelzitat aus PDF (one-shot), keine Vault-weite Bibliography.
`word-export` = Word/PDF statt `.tex`/`.bib`, siehe dort.

## Fehlerpfade

- **Pandoc fehlt:** Custom-Renderer-Fallback (kein Absturz). Pandoc installieren empfehlen.
- **Vault leer:** Leere `.bib` + Meldung „Vault leer – Papers via `add` hinzufügen."
- **Template nicht gefunden:** Ausgabe ohne Vorlage + Meldung „Template `<uni>` fehlt."

## Renderer

- **Pandoc** (bevorzugt): Wird automatisch genutzt wenn `pandoc -v` erfolgreich
- **Custom-Renderer** (Fallback): Eigener Renderer ohne externe Abhängigkeiten

Pandoc manuell überspringen: `force_custom=True` in `render_tex.py`

## Verbatim-Guard

Der `verbatim-guard`-Hook blockiert `.tex`-Writes wenn Zitate nicht im Vault verifiziert sind.

Bypass (nur für Ausnahmefälle): `<!-- vault-guard: skip -->` im Content. Jede Nutzung
wird geloggt (stderr-Warnung + Eintrag in `~/.academic-research/vault-guard-bypass.log`,
Override via `VAULT_GUARD_BYPASS_LOG`).

## Per-Uni-Template-Slot

Template-Datei: `~/.academic-research/library-profiles/<uni>.tex.template`

Platzhalter `%%CONTENT%%` wird durch den generierten LaTeX-Body ersetzt.

Beispiel Template erstellen:
```bash
mkdir -p ~/.academic-research/library-profiles/
cp skills/latex-export/references/biblatex-din-1505.md ~/.academic-research/library-profiles/
# Template-Datei anlegen: <uni>.tex.template
```

## Abhängigkeiten

- Python 3.10+ (für `render_tex.py`, `build_bib.py`)
- Pandoc (optional, für bessere Konvertierung): `brew install pandoc`
- biblatex + biber (für LaTeX-Kompilierung): Enthalten in TeX Live / MikTeX
