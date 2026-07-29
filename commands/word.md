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
| `--template` | Uni-Kürzel | — | Word-Basisvorlage aus `~/.academic-research/library-profiles/<uni>.docx` (geteilter Profil-Slot mit `latex-export`, dort die `.tex`-Variante). Fehlt sie: generisches Titelblatt + Meldung |

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
- `PAYLOAD` = Ablagepfad der JSON-Zwischenrepräsentation aus Schritt 3
  (z. B. `${OUTPUT%.docx}.payload.json`)

### Schritt 2 — Skill laden

Skill `skills/word-export/SKILL.md` wird geladen (Backend-Präflight,
Fehlerpfade, Abgrenzung zu `latex-export`/`citation-extraction`/`submission-checker`).

### Schritt 3 — Kapitel + Bibliografie vorbereiten

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/word-export/scripts/collect_references.py" \
  --kapitel "$KAPITEL" --payload "$PAYLOAD"
```

Das Skript bündelt intern:
1. Kapitel-Resolution aus `kapitel/` über `export_thesis.resolve_chapters()` —
   dieselbe `--kapitel <n>|all`-Auflösung wie `latex-export`, kein zweiter Nachbau
2. Zitationsstil aus `./academic_context.md` → unveränderte Regeln aus
   `citation-extraction/references/<style>.md`
3. Vault-Bibliografie über `build_bib.get_all_papers()` gegen
   `academic_vault.db.default_db_path()` — **exakt dieselbe Vault-Quelle wie der
   `.bib`-Pfad von `latex-export`**, damit die Literatureintrag-Menge
   docx ↔ LaTeX per Konstruktion identisch ist. Override nur für Tests:
   `--vault-db <pfad>`
4. `\cite{key}`-Marker je Kapitel → Klartext-Kurzzitate (Mehrfachzitate
   `\cite{a,b}` werden zu `(Alpha 2020; Beta 2021)`, unbekannte Keys sichtbar
   als `? key`)

Ergebnis ist die JSON-Datei unter `PAYLOAD` mit `chapters[]` (`source`, `path`,
`body`), `papers`, `style_file`, `style_rules`, `vault_db_path` und `messages`.
Bei Exit-Code ≠ 0 die vom Skript ausgegebene `FEHLER:`-Meldung (z. B. unbekanntes
Kapitel, fehlende Zitierstil-Referenzdatei) unverändert weitergeben — kein
Stacktrace. Meldungen aus `messages` (leerer Vault, fehlende
`academic_context.md`) anzeigen und trotzdem weitermachen.

### Schritt 4 — Dokument rendern

Vorher: `papers` + `style_rules` aus der Payload zu fertigen
Literatureinträgen im Stil aus `academic_context.md` formatieren und als
String-Liste unter dem Schlüssel `bibliography` **in dieselbe Payload-Datei
zurückschreiben**. Die Regeln stehen unverändert in `style_rules` (Quelle:
`citation-extraction/references/<style>.md`) — kein eigener Stil.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/word-export/scripts/render_docx.py" \
  --payload "$PAYLOAD" --output "$OUTPUT" --format "$FORMAT" --template "$TEMPLATE"
```

Das Skript erzeugt die Datei deterministisch (kein Freihand-Rendern): echte
Formatvorlagen `Heading 1`…`Heading 6` aus den Markdown-Ebenen `#`…`######`,
Word-native Inhaltsverzeichnis-Feldfunktion, Titelblatt aus `context`,
Literaturverzeichnis **zeichengenau** aus `bibliography` und eidesstattliche
Erklärung. Bei `--format pdf` konvertiert es dieselbe `.docx` per
`soffice --headless --convert-to pdf`; fehlt LibreOffice, bleibt die `.docx`
das gültige Ergebnis + Meldung (kein Abbruch).

Bei Exit-Code ≠ 0 die `FEHLER:`-Meldung unverändert weitergeben. Fehlt
`bibliography`, obwohl der Vault Einträge liefert, bricht das Skript bewusst ab
— ein Literaturverzeichnis in einem nicht belegten Format wäre Fabrikation.

### Schritt 5 — Optionale Layout-Verfeinerung

Bei Bedarf `document-skills:docx` auf die **erzeugte** Datei anwenden
(Hochschul-Layout, Kopf-/Fußzeilen). Optional — das Ergebnis aus Schritt 4 ist
bereits eine vollständige, in Word öffenbare Datei.

### Schritt 6 — Ergebnis zeigen

Pfad(e) der erzeugten Datei(en), Kapitelanzahl, Anzahl Literatureinträge.

## Abhängigkeiten

- `python-docx` (Renderer aus Schritt 4, Teil der Plugin-Installation)
- `document-skills:docx` (siehe „Word-Backend" oben)
- LibreOffice (`soffice`, optional, für `--format pdf`)
