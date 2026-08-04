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

## Workflow

`/academic-research:word --kapitel <n>|all --output <datei.docx> [--format docx|pdf] [--template <uni>]`:

1. Backend-Verfügbarkeit prüfen (Abschnitt „Word-Backend" unten) — vor dem
   ersten `document-skills:docx`-Aufruf.
2. Kapitel + Bibliografie in einem Schritt vorbereiten — **eine echte CLI, kein
   Inline-Python**:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/word-export/scripts/collect_references.py" \
     --kapitel "$KAPITEL" --payload "$PAYLOAD"
   ```

   Ergebnis ist eine JSON-Datei mit `chapters[]` (`source`, `path`, `body`),
   `papers`, `style_file`, `style_rules`, `vault_db_path`, `messages`.
   Exit-Code ≠ 0 → die `FEHLER:`-Meldung des Skripts unverändert weitergeben
   (kein Stacktrace); `messages` anzeigen und weitermachen.
3. Was das Skript intern garantiert:
   - Kapitel-Auflösung über `export_thesis.resolve_chapters()` — dieselbe
     `--kapitel <n>|all`-Semantik wie `latex-export`, kein zweiter Nachbau.
   - `\cite{key}`-Marker (Issue #386) → Klartext-Kurzzitate `(Nachname Jahr)`;
     Mehrfachzitate `\cite{a,b}` → `(Alpha 2020; Beta 2021)`, unbekannte Keys
     sichtbar als `? key`, nie stillschweigend fallengelassen.
   - `papers` aus `latex-export/scripts/build_bib.get_all_papers()` gegen
     `academic_vault.db.default_db_path()` (geteilte Vault-Query **und**
     geteilter Pfad-Auflöser, **Import statt Kopie** — sonst bricht AC „gleiche
     Entrymenge docx↔LaTeX" lautlos bei künftigen Vault-Änderungen). Override
     nur für Tests: `--vault-db <pfad>`.
   - `style_rules` = **unveränderter** Inhalt der passenden
     `citation-extraction/references/<style>.md`-Datei (Zuordnung über
     `Zitationsstil` in `./academic_context.md`, Default `apa.md`).
4. **Stilstufe — der einzige Agentenschritt:** `papers` + `style_rules` zu
   fertigen Literatureinträgen formatieren und als String-Liste unter
   `bibliography` **in dieselbe Payload-Datei zurückschreiben**. `style_rules`
   ist der unveränderte Inhalt der `citation-extraction`-Referenzdatei — keine
   zweite Stilregel-Implementierung, weder hier noch in Python.
5. Datei rendern — **wieder eine echte CLI, kein Freihand-Rendern**:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/word-export/scripts/render_docx.py" \
     --payload "$PAYLOAD" --output "$OUTPUT" --format "$FORMAT" --template "$TEMPLATE"
   ```

   `render_docx.py` ist hier, was `render_tex.py` für `latex-export` ist:
   Repo-Code erzeugt die Zieldatei deterministisch — nur deshalb ist sie prüfbar
   (`tests/test_issue_446_render_pipeline.py` öffnet sie wieder). Garantiert:
   - **Überschriftenebenen als echte Formatvorlagen** — Markdown `#`…`######`
     wird zu `HeadingLevel.HEADING_1`…`HEADING_6`, niemals manuelles
     Fett/Größe. Voraussetzung dafür, dass Word ein automatisches
     Inhaltsverzeichnis erzeugt und die Datei ohne Reparaturhinweis öffnet.
   - **Titelblatt** aus `context` (ausgefüllte Felder von
     `./academic_context.md`); fehlende Felder erscheinen als sichtbare
     Leerstelle `[bitte ergänzen]` statt erfunden. Ohne Hochschulvorlage
     generischer Aufbau + Meldung (siehe Fehlerpfade).
   - **Verzeichnisse**: Inhaltsverzeichnis als Word-native Feldfunktion über
     die Formatvorlagen-Struktur, kein statischer Text.
   - **Literaturverzeichnis**: die `bibliography`-Einträge aus Schritt 4
     **zeichengenau und in unveränderter Reihenfolge**. Fehlen sie, obwohl der
     Vault Papers liefert, bricht das Skript mit `FEHLER:` ab.
   - **Eidesstattliche Erklärung**: letzte Seite, generischer Wortlaut +
     Ort-/Datum-/Unterschriftsfeld (hochschulspezifischer Wortlaut ist
     eigenes Issue, siehe Abgrenzung).
   - `--format pdf`: dieselbe `.docx` per `soffice --headless --convert-to pdf`
     (kein eigener PDF-Renderer); fehlt LibreOffice, Meldung statt Absturz.
6. Optional: `document-skills:docx` auf die **erzeugte** Datei anwenden, wenn
   Layout über den Basisaufbau hinaus gewünscht ist. Ohne diesen Schritt ist das
   Ergebnis aus Schritt 5 bereits vollständig und in Word öffenbar.

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

- **`latex-export`**: paralleler Renderer für `.tex`/`.bib`, teilt sich die
  Vault-Bibliografie-Auswahl. Für LaTeX/biblatex → `latex-export`.
- **`citation-extraction`**: definiert die Zitierstil-Regeln (`references/*.md`).
  `word-export` lädt diese Regeln, definiert keine eigenen.
- **`slide-export`**: Foliensatz aus denselben Kapiteln, eigener Skill (siehe dort).
- **`submission-checker`**: prüft die fertige Abgabedatei gegen Hochschul-Formalia
  (Seitenränder, Pflichtabschnitte). `word-export` erzeugt die Formatvorlagen-
  Struktur, die `submission-checker` danach prüft — keine doppelte
  Formalia-Logik.

## Fehlerpfade

- **Backend fehlt:** Siehe „Word-Backend" oben — Abbruch mit Installationshinweis,
  kein roher Tool-Fehler.
- **Vault leer:** Leeres Literaturverzeichnis + Meldung „Vault leer – Papers via
  `add` hinzufügen." (kein Abbruch, Kapitel werden trotzdem exportiert).
- **Template nicht gefunden:** Titelblatt ohne Hochschulvorlage (generischer
  Platzhalter) + Meldung „Template `<uni>` fehlt.“ — kein Absturz.
- **`soffice`/LibreOffice fehlt (`--format pdf`):** `.docx` wird trotzdem
  geschrieben, PDF-Konvertierung übersprungen + Meldung „LibreOffice (`soffice`)
  nicht gefunden — PDF-Konvertierung übersprungen, `.docx` verfügbar."
- **Zitierstil-Referenzdatei fehlt:** `collect_references.load_style_rules()`
  wirft `StyleRulesNotFoundError` mit lesbarer Meldung statt Stacktrace.
- **`python-docx` fehlt:** `render_docx.py` meldet „FEHLER: Das Python-Paket
  'python-docx' ist nicht installiert …" mit Nachinstallations-Hinweis statt
  eines `ImportError`-Tracebacks (AC6).
- **`bibliography` fehlt trotz gefüllten Vaults:** `render_docx.py` bricht mit
  `FEHLER:` ab und nennt den fehlenden Schritt. Bewusst kein Fallback: ein
  Literaturverzeichnis in einem nicht belegten Format wäre Fabrikation.

## Verbatim-Guard

Kapitel-Quelltext (`kapitel/*.md`) ist bereits durch `hooks/verbatim-guard.mjs`
geschützt (siehe `latex-export`). `word-export` liest nur bereits verifizierte
Kapitel, schreibt keine neuen Zitate.
