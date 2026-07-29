---
name: slide-export
description: Use this skill for Folien-/Slide-Output / .pptx-Export. Triggers on "Foliensatz erstellen / erzeugen", "Präsentation / Praesentation fürs Kolloquium", "Konferenz-Slides", "/academic-research:slides". Markdown-Kapitel → .pptx mit einer Kernaussage pro Folie, als Ausgangspunkt für Kolloquium-Präsentation und Konferenz-Vortrag.
license: MIT
allowed-tools:
  - Bash
  - Read
  - Write
  - Skill(document-skills:pptx)
---

# Slide-Export

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du fortfährst.

## Workflow

`/academic-research:slides --kapitel <n>|all --output <datei.pptx> [--kolloquium|--konferenz]`:

1. Backend-Verfügbarkeit prüfen (Abschnitt „Slide-Backend" unten) — vor dem
   ersten `document-skills:pptx`-Aufruf.
2. Folien-Zwischenrepräsentation bauen — **eine echte CLI, kein Inline-Python**:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/slide-export/scripts/build_slide_deck.py" \
     --kapitel "$KAPITEL" --payload "$PAYLOAD" --rahmen "$RAHMEN"
   ```

   Exit-Code ≠ 0 → die `FEHLER:`-Meldung des Skripts unverändert weitergeben
   (kein Stacktrace). Kapitel-Auflösung ist `export_thesis.resolve_chapters()` —
   dieselbe `--kapitel <n>|all`-Semantik wie `latex-export`/`word-export`, kein
   zweiter Nachbau.
3. Die Payload enthält `slides[]` mit
   pro Kapitel-Datei genau einem Eintrag `{title, core_statement, source}` —
   `title` aus der ersten H1-Überschrift (Fallback: Dateiname), `core_statement`
   aus dem ersten Fließtext-Satz nach der Überschrift. Kapitel ohne Fließtext
   (nur Überschrift/Liste) liefern einen leeren `core_statement` — das Skript
   meldet das auf stderr; in dem Fall den User um eine Kernaussage bitten statt
   eine zu erfinden (Preamble „Keine Fabrikation").
4. `document-skills:pptx` aufrufen: ein Slide je Eintrag, Titel als Folientitel,
   `core_statement` als einzige zentrale Aussage (kein Fließtext-Absatz auf der
   Folie — Design-Leitplanken für Kernaussage-Folien kommen aus
   `document-skills:pptx` selbst, hier nicht dupliziert).
5. `--kolloquium`/`--konferenz` steuern nur den Foliensatz-Rahmen (Deckblatt,
   Agenda-Folie, Backup-Slot); die Kern-Extraktion aus Schritt 3 bleibt gleich.

## Slide-Backend

<!-- pptx-backend:start -->
Die pptx-Erzeugung übernimmt der externe Skill `document-skills:pptx` aus dem
Marketplace `anthropic-agent-skills` (Repository `anthropics/skills`). Das Plugin
`academic-research` deklariert ihn als Abhängigkeit in `.claude-plugin/plugin.json`
— eine frische Installation zieht ihn automatisch mit, sofern der Marketplace
bereits hinzugefügt ist.

**Vor dem ersten Skill-Aufruf prüfen:** Ist der Skill `document-skills:pptx` aufrufbar?
Falls nicht, brich mit dieser Meldung ab, statt einen rohen Tool-Fehler durchzureichen:

> Das Folien-Backend `document-skills:pptx` ist nicht installiert — es wird
> deshalb kein Foliensatz erzeugt. So installierst du es nach:
>
> ```bash
> claude plugin marketplace add anthropics/skills
> claude plugin install document-skills@anthropic-agent-skills
> ```
>
> Danach `/reload-plugins` ausführen und den Command erneut aufrufen.
<!-- pptx-backend:end -->

## Abgrenzung

- **`word-export`**: gleiche Kapitel-Quelle, aber Fließtext-Renderer (`.docx`/PDF)
  statt Folien. Beide teilen die Kapitel-Auflösung aus `latex-export`, nicht
  die Rendering-Logik — docx-Fließtext und pptx-Folien sind strukturell zu
  verschieden für einen gemeinsamen Renderer.
- **`latex-export`**: kein Bezug zu Folien; nur Kapitel-Quelle ist geteilt.
- Kein eigenes Literaturverzeichnis auf Folien — Zitate/Quellen bleiben in den
  Kapiteln, `slide-export` reduziert auf die Kernaussage.

## Fehlerpfade

- **Backend fehlt:** Siehe „Slide-Backend" oben — Abbruch mit Installationshinweis,
  kein roher Tool-Fehler.
- **Kapitel ohne Kernaussage:** `core_statement` ist leer (kein Fließtext-Absatz
  gefunden) — Rückfrage an den User statt Platzhalter-Fabrikation.
- **Unbekanntes `--kapitel`:** `resolve_chapters()` wirft `ChapterResolutionError`
  mit den verfügbaren Kapiteln in der Meldung (identisch zu `latex-export`).
- **Kein Kapitel in `kapitel/`:** `ChapterResolutionError` mit „Kein Kapitel in
  '<dir>' gefunden" statt Stacktrace.
