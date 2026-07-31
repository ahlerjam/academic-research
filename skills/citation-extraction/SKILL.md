---
name: citation-extraction
description: Use this skill when the user needs to extract or format citations. Triggers on "Literaturverzeichnis erstellen / prüfen / generieren", "Zitate finden", "Bibliographie formatieren", "Zitation prüfen / pruefen", "citation extraction", "bibliography generation", or when raw PDFs need citation rendering (not chapter body writing — for that → `chapter-writer`). Extrahiert Zitate aus PDFs und liefert formatierte Bibliographien im Zitationsstil aus `./academic_context.md`.
license: MIT
allowed-tools:
  - Read
  - AskUserQuestion
---

# Zitat-Extraktion

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Extrahiert und formatiert Zitate aus PDFs und Volltexten. Liefert
Literaturverzeichnisse im Zitationsstil aus `./academic_context.md`
(APA7, IEEE, Harvard etc.). Nutzt die Claude-API `documents[] + citations.enabled`.

## Abgrenzung

Extrahiert und formatiert wörtliche Zitate aus PDFs für einzelne Belege.
Für Kapitel-Prosa, die Belege in Argumentation einbaut → `chapter-writer`
(ruft `citation-extraction` bei Bedarf auf).

**BibTeX-Abgrenzung:** „BibTeX aus Vault" / „komplette Bibliographie als .bib"
→ `latex-export --bib`, nicht hierher (Details → `references/output-formats.md`).

## Variant-Selector

Feld `Zitationsstil` aus `./academic_context.md`; leer → `apa.md`, unbekannt →
Rueckfrage. Datei: `${CLAUDE_PLUGIN_ROOT}/skills/citation-extraction/references/<variant>.md`.

| Stil | Datei | Stil | Datei |
|------|-------|------|-------|
| APA7 (Default) | `apa.md` | MLA | `mla.md` |
| Harvard | `harvard.md` | Vancouver | `vancouver.md` |
| Chicago | `chicago.md` | Springer Author-Date | `springer-author-date.md` |
| DIN 1505-2 | `din1505.md` | | |

**Typ-Erweiterung** (Vorrang vor Artikel-Regeln): `type: chapter` →
`book-chapter-de.md`; `type: book` → `din1505.md` (Monografie-Sektion);
`type: article-journal` → keine Zusatz-Referenz.

## Citations-API

Liegt ein Quellen-PDF im Session-Kontext, den `documents`-Parameter der
Claude-API statt Prompt-Zitation nutzen — seitengenau, API erzwingt
Quellenbindung.

**Wann:** ≥1 PDF + Zitierstil-Konversion aus echtem Quelltext. **Wann
nicht:** reiner Metadaten-Workflow → Prompt-Formatierung nach
Variant-References.

**Output:** Seitenangaben aus `citations[].start_page_number` /
`end_page_number` → `references/output-formats.md`.

## Kontext-Dateien

- `./academic_context.md` lesen (Zitationsstil)
- `vault.find_quotes(paper_id, query)` / `vault.get_quote(quote_id)` für Zitate
- `./literature_state.md` nur lesen (read-only Snapshot; nicht schreiben)

## Core-Workflow

### 1. Extraktions-Scope bestimmen

Kläre, was der User braucht:

- **Vollextraktion** — Alle in der Session heruntergeladenen PDFs verarbeiten
- **Kapitelbezogen** — Zitate für ein bestimmtes Kapitel extrahieren
- **Quellenbezogen** — Aus einem oder mehreren bestimmten Papern extrahieren
- **Themenbezogen** — Zitate zu einem Konzept über alle Quellen hinweg suchen

### 2. Relevante Paper aus Vault laden

Rufe `vault.search(query, k=5)` auf, um die relevantesten Paper-IDs zur
Recherche-Query zu ermitteln. Für jeden paper_id:

1. `vault.find_quotes(paper_id, query=research_query, k=10)` aufrufen →
   liefert `[{quote_id, verbatim, pdf_page, section, ...}]`
2. Für detaillierte Zitat-Metadaten: `vault.get_quote(quote_id)`

Sind für ein Paper noch keine Vault-Zitate vorhanden (leere Liste), den
`quote-extractor`-Agent spawnen, um Zitate aus dem PDF zu ziehen und via
`vault.add_quote()` zu persistieren. PDFs werden via `vault.ensure_file(paper_id)`
als `file_id` übergeben — kein direktes `pdf_path` im Context.

### 3. Zitat-Extraktion

Wenn Vault-Zitate für ein Paper vorhanden sind, diese direkt verwenden — kein
Agent-Spawn nötig.

Fehlen Vault-Zitate, den Agent `quote-extractor` spawnen (definiert in
`${CLAUDE_PLUGIN_ROOT}/agents/quote-extractor.md`). Übergebe:

```json
{
  "paper": {
    "paper_id": "mueller2023",
    "title": "Paper Title",
    "doi": "10.xxxx/xxxxx"
  },
  "research_query": "derived from chapter title or user query",
  "max_quotes": 3,
  "max_words_per_quote": 25
}
```

Der Agent liefert `possible_pdf_mismatch` + `extraction_quality` im
Output-JSON. Persistenz via `vault.add_quote()`: automatisch bei
`possible_pdf_mismatch: false`; bei `true` NICHT, außer im Re-Invoke steht
`mismatch_override: true` — siehe PDF-Mismatch-Gate.

#### PDF-Mismatch-Gate

Bei `possible_pdf_mismatch: true` vor jeder weiteren Persistenz
`AskUserQuestion` stellen — kein reines Flaggen für späteres Review:

- **"Fortfahren — Zitate trotz Mismatch übernehmen"** → Agent-Re-Invoke mit
  `mismatch_override: true`, dann `vault.add_quote()`
- **"Paper überspringen"** → `vault.add_excluded_source(paper_id,
  reason="possible_pdf_mismatch")`, kein Persist, Paper gilt als ausgelassen
- **"PDF-Zuordnung prüfen"** → pausieren, kein Persist, User klärt die
  Zuordnung (z. B. `vault.update_pdf_path`)

Ohne Freigabe aus diesem Gate wird kein Zitat des Papers persistiert.

Bei kapitelbezogener Extraktion den `research_query` aus Kapiteltitel und
Schlüsselkonzepten der Gliederung ableiten. Die Gliederungs-Struktur aus
`./academic_context.md` nutzen, um Paper zu Kapiteln zu matchen.

### 4. Qualitätsprüfung

Nach der Extraktion die Ergebnisse prüfen:

- Zitate mit `extraction_quality: "failed"` verwerfen
- `possible_pdf_mismatch: true` → PDF-Mismatch-Gate aus Schritt 3, kein
  eigenständiges Flaggen mehr an dieser Stelle
- Prüfen, ob Zitate tatsächlich für das Zielkapitel/-thema relevant sind
- Duplikate über Paper hinweg entfernen (gleiche Idee, andere Formulierung)

Ergebnispräsentation getrennt nach Ausgang:

- **Erfolgreich** — Paper mit persistierten Zitaten, gruppiert nach Quelle:
  Zitattext, Seitenzahl (falls verfügbar), Abschnitt, Relevanz-Score,
  Paper-Titel und Autoren.
- **Ausgelassen** — im Gate übersprungene oder zur PDF-Zuordnungsprüfung
  pausierte Paper; zählen nicht als erfolgreich, eigene Gruppe im Report.

### 5. Zitat-Formatierung

Formatiere Zitate inline nach dem in `./academic_context.md` konfigurierten Stil. Keine externe Skript-Pipeline — Claude generiert die Formate direkt aus den strukturierten Paper-Daten. Output-Formate → `references/output-formats.md`.

### 6. Kapitelzuordnung

Wenn Zitate für ein bestimmtes Kapitel extrahiert werden:

1. Zitate nach Relevanz für die Unterabschnitte gruppieren
2. Platzierung innerhalb der Kapitelstruktur vorschlagen
3. Unterabschnitte identifizieren, in denen noch stützende Evidenz fehlt
4. Bei Lücken weitere Literatursuche anbieten

### 7. Literaturstatus

Der Vault ist die Quelle der Wahrheit; `./literature_state.md` ist ein
read-only Snapshot — nicht beschreiben. Snapshot regenerieren:
```bash
node scripts/export-literature-state.mjs
```
Zitatanzahlen und Coverage über `vault.stats()` abfragen.

## Lückenerkennung

Muster (fehlende Zitate, Einzelquellen, fehlende Gegenargumente, veraltete
Quellen) und Handlungsempfehlungen → `references/gap-detection.md`.

## Export-Formate

Unterstützte Output-Formate (BibTeX, Markdown, JSON; inline generiert, kein
externes Skript). Details und Ziel-Pfade → `references/output-formats.md`.

## Few-Shot-Beispiele

Gut/Schlecht-Beispiele zur Qualitätskalibrierung (APA7-Zitation,
Bibliography-Vollständigkeit) → `references/citation-examples.md`.

## Wichtige Regeln

- **Nie fabrizieren** — nur Text direkt aus PDFs
- **Exakter Wortlaut** — wörtlich zur Quelle
- **Seitenzahlen** — wenn verfügbar immer mitführen
- **Zitationsstil respektieren** — durchgehend den konfigurierten Stil
- **Mismatches gaten** — `possible_pdf_mismatch: true` löst vor jeder Persistenz das Gate aus Schritt 3 aus (kein reines Flaggen)
- **User bestätigt Zuordnungen** — Kapitel-Zitat-Zuordnung vor dem Speichern freigeben
