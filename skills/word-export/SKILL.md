---
name: word-export
description: Use this skill for Word-/PDF-Output / .docx-Export. Triggers on "Kapitel als Word exportieren / übersetzen / uebersetzen", "Thesis als .docx", "Abgabe als PDF", "/academic-research:word". Markdown-Kapitel + Vault-Bibliografie → .docx mit echten Formatvorlagen (Überschriften, Titelblatt, Verzeichnisse, eidesstattliche Erklärung), optional PDF-Konvertierung.
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
2. Kapitel aus `kapitel/` auflösen: `${CLAUDE_PLUGIN_ROOT}/skills/latex-export/scripts/export_thesis.py`
   exportiert `resolve_chapters()` — dieselbe `--kapitel <n>|all`-Auflösung
   wie `latex-export`, kein zweiter Nachbau.
3. `\cite{key}`-Marker je Kapitel auflösen: `${CLAUDE_PLUGIN_ROOT}/skills/word-export/scripts/collect_references.py`
   Funktion `resolve_cite_markers(text, papers)` — LaTeX-Zitationsmarker
   (Issue #386) sind für Word bedeutungslos und werden zu Klartext-Kurzzitaten
   `(Nachname Jahr)`; unbekannte Keys werden sichtbar als `(? key)` markiert,
   nie stillschweigend fallengelassen.
4. Bibliografie sammeln: `collect_references(db_path, academic_context_text, references_dir)`
   liefert `{papers, style_file, style_rules}`. `papers` kommt aus
   `latex-export/scripts/build_bib.get_all_papers()` (geteilte Vault-Query,
   **Import, keine Kopie** — sonst bricht AC „gleiche Entrymenge docx↔LaTeX"
   lautlos bei künftigen Vault-Änderungen). `style_rules` ist der **unveränderte**
   Inhalt der passenden `citation-extraction/references/<style>.md`-Datei
   (Zuordnung über `Zitationsstil` in `./academic_context.md`, Default `apa.md`).
5. `document-skills:docx` aufrufen und rendern:
   - **Überschriftenebenen als echte Formatvorlagen** — `HeadingLevel.HEADING_1`
     bis `HEADING_6` (bzw. das äquivalente Styles-API des Backends), niemals
     manuelles Fett/Größe. Das ist Voraussetzung dafür, dass Word ein
     automatisches Inhaltsverzeichnis erzeugen kann und die Datei ohne
     Reparaturhinweis öffnet.
   - **Titelblatt**: Titel, Autor:in, Betreuer:in, Hochschule aus
     `./academic_context.md`; ohne Hochschulvorlage (`--template` nicht
     gesetzt oder nicht gefunden) ein generischer Platzhalter-Aufbau — keine
     erfundene FH-spezifische Wortlaut-Fabrikation (siehe Fehlerpfade).
   - **Verzeichnisse**: Inhaltsverzeichnis über die Formatvorlagen-Struktur
     (Word-native Feldfunktion, kein statischer Text).
   - **Literaturverzeichnis**: `papers` + `style_rules` aus Schritt 4 als
     Word-Absätze rendern — der Agent wendet die geladenen Stilregeln beim
     Rendern an, `collect_references.py` liefert keine fertig formatierten
     Strings (keine zweite Stilregel-Implementierung neben
     `citation-extraction`).
   - **Eidesstattliche Erklärung**: letzte Seite, generischer Wortlaut +
     Ort-/Datum-/Unterschriftsfeld (hochschulspezifischer Wortlaut ist
     eigenes Issue, siehe Abgrenzung).
6. `--format pdf`: dieselbe erzeugte `.docx` per `soffice --headless --convert-to pdf`
   konvertieren (kein eigener PDF-Renderer). Fehlt LibreOffice/`soffice`,
   Meldung statt Absturz (siehe Fehlerpfade).

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

- **`latex-export`**: paralleler Renderer für `.tex`/`.bib`. Beide teilen sich
  die Vault-Bibliografie-Auswahl (`build_bib.get_all_papers()`), unterscheiden
  sich nur in der Ausgabeform. Für LaTeX/biblatex → `latex-export`.
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

## Verbatim-Guard

Kapitel-Quelltext (`kapitel/*.md`) ist bereits durch `hooks/verbatim-guard.mjs`
geschützt (siehe `latex-export`). `word-export` liest nur bereits verifizierte
Kapitel, schreibt keine neuen Zitate.
