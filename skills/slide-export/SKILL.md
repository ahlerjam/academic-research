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

## Trigger-Wrapper

Dieser Skill fängt natürlichsprachige Foliensatz-Anfragen ab und leitet an den
Command weiter: Lies `commands/slides.md` vollständig und führe dessen
Schritte 1–6 aus, so als wäre `/academic-research:slides` mit den erkannten
Argumenten aufgerufen worden. `commands/slides.md` ist die einzige Quelle für
Ablauflogik, Fehlerpfade und Abgrenzung (u. a. eine Kernaussage pro Folie) —
sie wird hier nicht dupliziert.

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

`slide-export` erzeugt einen Foliensatz mit einer Kernaussage pro Folie aus
denselben Kapiteln wie `word-export` (Fließtext-Renderer, `.docx`/PDF) und
`latex-export` (kein Bezug zu Folien, nur Kapitel-Quelle geteilt). Kein
eigenes Literaturverzeichnis auf Folien.
