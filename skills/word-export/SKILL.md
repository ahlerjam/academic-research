---
name: word-export
description: Use this skill for Word-/PDF-Output / .docx-Export. Triggers on "Kapitel als Word exportieren / Word übersetzen / Word uebersetzen", "Thesis als .docx", "Abgabe als PDF", "/academic-research:word". Markdown-Kapitel + Vault-Bibliografie → .docx mit echten Formatvorlagen (Überschriften, Titelblatt, Verzeichnisse, eidesstattliche Erklärung), optional PDF-Konvertierung.
license: MIT
allowed-tools:
  - Bash
  - Read
  - Write
  - Skill(document-skills:docx)
---

# Word-Export

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du fortfährst.

## Trigger-Wrapper

Dieser Skill fängt natürlichsprachige Word-/PDF-Export-Anfragen ab und leitet
an den Command weiter: Lies `commands/word.md` vollständig und führe dessen
Schritte 1–6 aus, so als wäre `/academic-research:word` mit den erkannten
Argumenten aufgerufen worden. `commands/word.md` ist die einzige Quelle für
Ablauflogik, Fehlerpfade und Abgrenzung — sie wird hier nicht dupliziert.

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

## Abgrenzung

`word-export` erzeugt `.docx`/PDF mit echten Formatvorlagen. Für `.tex`/`.bib`
siehe `latex-export` (paralleler Renderer, teilt sich die
Vault-Bibliografie-Auswahl); Zitierstil-Regeln kommen unverändert aus
`citation-extraction`; Foliensätze aus denselben Kapiteln macht `slide-export`;
die fertige Datei gegen Hochschul-Formalia prüft `submission-checker`.

## Verbatim-Guard

Kapitel-Quelltext (`kapitel/*.md`) ist bereits durch `hooks/verbatim-guard.mjs`
geschützt (siehe `latex-export`). `word-export` liest nur bereits verifizierte
Kapitel, schreibt keine neuen Zitate.
