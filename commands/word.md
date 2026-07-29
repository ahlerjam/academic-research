---
description: Exportiert Kapitel des aktuellen Projekts als .docx (echte Formatvorlagen) und optional als PDF, inklusive Titelblatt, Verzeichnissen und eidesstattlicher Erklärung.
disable-model-invocation: true
allowed-tools: Read, Write, Bash(python3 *), Bash(soffice *), Skill(document-skills:docx)
argument-hint: --kapitel <n>|all --output <datei.docx> [--format docx|pdf] [--template <uni>]
---

# /academic-research:word — Word-Export

## Beschreibung

Exportiert Kapitel des aktuellen Projekts als `.docx` mit echten Formatvorlagen
für Überschriftenebenen (statt manuellem Fett/Größe), Titelblatt, automatischem
Inhaltsverzeichnis und eidesstattlicher Erklärung. Optional als PDF (reine
Konvertierung derselben `.docx`, kein eigener PDF-Renderer).

## Syntax

```
/academic-research:word --kapitel <n>|all --output <datei.docx> [--format docx|pdf] [--template <uni>]
```

## Parameter

| Parameter | Typ | Standard | Beschreibung |
|-----------|-----|---------|--------------|
| `--kapitel` | `<n>` oder `all` | — (Pflicht) | Kapitel-Nummer oder `all` für alle |
| `--output` | Dateipfad | — (Pflicht) | Ausgabedatei (`.docx`) |
| `--format` | `docx` oder `pdf` | `docx` | `pdf` erzeugt zusätzlich eine PDF-Konvertierung derselben `.docx` |
| `--template` | Uni-Kürzel | — | Titelblatt-Vorlage aus `~/.academic-research/library-profiles/<uni>.tex.template` (geteilter Slot mit `latex-export`) |

## Beispiele

```bash
# Alle Kapitel als Word-Dokument
/academic-research:word --kapitel all --output output/thesis.docx

# Einzelnes Kapitel, zusätzlich als PDF
/academic-research:word --kapitel 3 --output output/kap3.docx --format pdf
```

## Word-Backend

<!-- docx-backend:start -->
Die docx-Erzeugung übernimmt der externe Skill `document-skills:docx` aus dem
Marketplace `anthropic-agent-skills` (Repository `anthropics/skills`). Das Plugin
`academic-research` deklariert ihn als Abhängigkeit in `.claude-plugin/plugin.json`
— eine frische Installation zieht ihn automatisch mit, sofern der Marketplace
bereits hinzugefügt ist.

**Vor dem ersten Skill-Aufruf prüfen:** Ist der Skill `document-skills:docx` aufrufbar?
Falls nicht, brich mit dieser Meldung ab, statt einen rohen Tool-Fehler durchzureichen:

> Das Word-Backend `document-skills:docx` ist nicht installiert — es wird
> deshalb keine Word-Datei erzeugt. So installierst du es nach:
>
> ```bash
> claude plugin marketplace add anthropics/skills
> claude plugin install document-skills@anthropic-agent-skills
> ```
>
> Danach `/reload-plugins` ausführen und den Command erneut aufrufen.
<!-- docx-backend:end -->

## Ablauf

### Schritt 1 — Argumente parsen

- `KAPITEL` = Wert von `--kapitel` (Pflicht: Zahl oder `all`)
- `OUTPUT` = Wert von `--output` (Pflicht: Zielpfad der `.docx`-Datei)
- `FORMAT` = Wert von `--format` (optional, Default `docx`)
- `TEMPLATE` = Wert von `--template` (optional, Uni-Kürzel)

### Schritt 2 — Skill laden

Skill `skills/word-export/SKILL.md` wird geladen (Backend-Präflight,
Fehlerpfade, Abgrenzung zu `latex-export`/`citation-extraction`/`submission-checker`).

### Schritt 3 — Kapitel + Bibliografie vorbereiten

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/latex-export/scripts")
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/word-export/scripts")
from export_thesis import resolve_chapters
from collect_references import collect_references, resolve_cite_markers

chapters = resolve_chapters("kapitel", "$KAPITEL")
academic_context = open("academic_context.md", encoding="utf-8").read() if __import__("os").path.exists("academic_context.md") else ""
refs = collect_references(
    "$VAULT_DB_PATH",
    academic_context,
    "${CLAUDE_PLUGIN_ROOT}/skills/citation-extraction/references",
)
bodies = [resolve_cite_markers(p.read_text(encoding="utf-8"), refs["papers"]) for p in chapters]
# bodies + refs an document-skills:docx uebergeben (Schritt 4)
PY
```

### Schritt 4 — `document-skills:docx` aufrufen

Formatvorlagen (`HeadingLevel.*`), Titelblatt, Inhaltsverzeichnis,
Literaturverzeichnis (Papers + `style_rules` aus Schritt 3, im Stil aus
`academic_context.md` gerendert) und eidesstattliche Erklärung gemäß
`skills/word-export/SKILL.md` erzeugen.

### Schritt 5 — Optional PDF

Bei `--format pdf`: `soffice --headless --convert-to pdf --outdir <dir> <OUTPUT>`
auf die erzeugte `.docx` anwenden. Fehlt `soffice`, `.docx` bleibt gültiges
Ergebnis + Meldung (kein Abbruch).

### Schritt 6 — Ergebnis zeigen

Pfad(e) der erzeugten Datei(en), Kapitelanzahl, Anzahl Literatureinträge.

## Abhängigkeiten

- `document-skills:docx` (siehe „Word-Backend" oben)
- LibreOffice (`soffice`, optional, für `--format pdf`)
