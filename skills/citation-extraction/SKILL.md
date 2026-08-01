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
(APA7, IEEE, Harvard etc.). Standard: lokale Extraktion + serverseitige
`local-verbatim`-Verifikation (kein API-Key nötig); Citations-API nur
optional (siehe unten).

## Abgrenzung

Extrahiert und formatiert wörtliche Zitate aus PDFs für einzelne Belege.
Für Kapitel-Prosa, die Belege in Argumentation einbaut → `chapter-writer`
(ruft `citation-extraction` bei Bedarf auf).

**BibTeX-Abgrenzung:** „BibTeX aus Vault" / „komplette Bibliographie als .bib"
→ `latex-export --bib`, nicht hierher (Details → `references/output-formats.md`).

## Variant-Selector

Lies `./academic_context.md`, Feld `Zitationsstil`. Lade die entsprechende Variant-Datei:

| Zitationsstil | Referenz-Datei |
|---------------|----------------|
| APA7 (Default) | `references/apa.md` |
| Harvard | `references/harvard.md` |
| Chicago | `references/chicago.md` |
| DIN 1505-2 | `references/din1505.md` |
| MLA | `references/mla.md` |
| Vancouver | `references/vancouver.md` |
| Springer Author-Date | `references/springer-author-date.md` |

Ist `Zitationsstil` leer → `apa.md`. Unbekannt → Rueckfrage. Lies `${CLAUDE_PLUGIN_ROOT}/skills/citation-extraction/references/<variant>.md`.

**Typ-basierte Erweiterung:** Je nach Quellen-`type` zusaetzliche Referenz laden;
deren Regeln haben Vorrang vor den generischen Artikel-Regeln.

| Quellen-Typ | Zusaetzliche Referenz |
|-------------|----------------------|
| `type: chapter` | `references/book-chapter-de.md` |
| `type: book` | `references/din1505.md` (Monografie-Sektion) |
| `type: article-journal` | (keine Zusatz-Referenz) |

## Zitat-Extraktion (Standard: lokal, kein API-Key)

Standard: `vault.add_quote(..., extraction_method="local-verbatim")` — der
`quote-extractor`-Agent liest das PDF lokal (`Read`), der Vault-Server prüft
den Wortlaut fail-closed gegen den PDF-Volltext. Kein `ANTHROPIC_API_KEY` nötig.

**Citations-API (optional):** Liegen PDFs im Session-Kontext, alternativ der
`documents`-Parameter der Claude-API (seitengenau, erzwingt Quellenbindung).
Braucht einen eigenen `ANTHROPIC_API_KEY` außerhalb der Subscription-Session
(Anthropic Beta-API) — nur bei explizitem Bedarf, nicht der Standardweg.

**Output:** `pdf_page` aus `vault.find_quotes`/`vault.get_quote` (Standard),
sonst `citations[].start_page_number`/`end_page_number` (optionale
Citations-API) → `references/output-formats.md`.

## Kontext-Dateien

- Lesen: `./academic_context.md` (Zitationsstil)
- Vault-Queries: `vault.find_quotes(paper_id, query)`, `vault.get_quote(quote_id)`
- `./literature_state.md`: read-only Snapshot, nicht schreiben

## Core-Workflow

### 1. Extraktions-Scope bestimmen

Kläre, was der User braucht:

- **Vollextraktion** — Alle in der Session heruntergeladenen PDFs verarbeiten
- **Kapitelbezogen** — Zitate für ein bestimmtes Kapitel extrahieren
- **Quellenbezogen** — Aus einem oder mehreren bestimmten Papern extrahieren
- **Themenbezogen** — Zitate zu einem Konzept über alle Quellen hinweg suchen

### 2. Relevante Paper aus Vault laden

Rufe `vault.search(query, k=5)` auf für die relevantesten Paper-IDs. Für jeden paper_id:

1. `vault.find_quotes(paper_id, query=research_query, k=10)` →
   `[{quote_id, verbatim, pdf_page, section, ...}]`
2. Details: `vault.get_quote(quote_id)`

Fehlen Vault-Zitate (leere Liste): `quote-extractor`-Agent spawnen (Ablauf →
Schritt 3).

### 3. Zitat-Extraktion

Wenn Vault-Zitate für ein Paper vorhanden sind, diese direkt verwenden — kein
Agent-Spawn nötig.

Fehlen Vault-Zitate, den Agent `quote-extractor` spawnen (definiert in
`${CLAUDE_PLUGIN_ROOT}/agents/quote-extractor.md`). Übergebe:

```json
{
  "paper": { "paper_id": "mueller2023", "title": "Paper Title" },
  "research_query": "derived from chapter title or user query",
  "max_quotes": 3,
  "max_words_per_quote": 25
}
```

Der Agent liest das PDF lokal via `vault.get_paper(paper_id)` → `pdf_path` →
`Read`, persistiert via `vault.add_quote(..., extraction_method="local-verbatim")`
und gibt `vault_quote_id` zurück.

Bei kapitelbezogener Extraktion den `research_query` aus Kapiteltitel und
Schlüsselkonzepten der Gliederung ableiten. Die Gliederungs-Struktur aus
`./academic_context.md` nutzen, um Paper zu Kapiteln zu matchen.

### 4. Qualitätsprüfung

Nach der Extraktion die Ergebnisse prüfen:

- Zitate mit `extraction_quality: "failed"` verwerfen
- Paper mit `possible_pdf_mismatch: true` für Review flaggen
- Relevanz für Zielkapitel/-thema prüfen
- Duplikate über Paper hinweg entfernen (gleiche Idee, andere Formulierung)

Extrahierte Zitate gruppiert nach Quelle präsentieren: Zitattext, Seitenzahl
(falls verfügbar), Ursprungs-Abschnitt, Relevanz-Score, Paper-Titel, Autoren.

### 5. Zitat-Formatierung

Formatiere Zitate inline nach dem in `./academic_context.md` konfigurierten
Stil — keine externe Skript-Pipeline, Claude generiert direkt aus den
strukturierten Paper-Daten. Output-Formate → `references/output-formats.md`.

### 6. Kapitelzuordnung

Wenn Zitate für ein bestimmtes Kapitel extrahiert werden:

1. Zitate nach Relevanz für die Unterabschnitte gruppieren
2. Platzierung innerhalb der Kapitelstruktur vorschlagen
3. Unterabschnitte identifizieren, in denen noch stützende Evidenz fehlt
4. Bei Lücken weitere Literatursuche anbieten

**Gate:** Vorschlag 1.–4. gilt erst nach `AskUserQuestion`-Bestätigung als
angenommen — vor Export/Weiterverwendung:

- „Übernehmen" — Vorschlag weiterverwenden
- „Ablehnen" — verworfen, kein Vault-Schreibzugriff, keine Weiterverwendung;
  zurück zu Schritt 5 oder erneuter Vorschlag

Ablehnung ist Default-Pfad, kein Fehler.

### 7. Literaturstatus

Der Vault ist die Quelle der Wahrheit; `./literature_state.md` ist ein
read-only Snapshot — nicht beschreiben. Snapshot regenerieren:
```bash
node scripts/export-literature-state.mjs
```
Zitatanzahlen und Coverage über `vault.stats()` abfragen.

## Lückenerkennung

Während der Extraktion auf diese Muster achten:

- **Kapitel ohne Zitate** — literaturbedürftig flaggen
- **Kapitel mit nur einer Quelle** — potenziell unzureichend flaggen
- **Fehlende Gegenargumente** — bei Einseitigkeit nach Gegenpositionen suchen
- **Veraltete Quellen** — >10 Jahre alt flaggen, außer Standardwerke

Bei Lücken `/search` gezielt anbieten oder `literature-gap-analysis` triggern.

## Export-Formate

Unterstützte Output-Formate (BibTeX, Markdown, JSON; inline generiert, kein
externes Skript). Details und Ziel-Pfade → `references/output-formats.md`.

## Few-Shot-Beispiele

Gut/Schlecht-Beispiele zur Qualitätskalibrierung (APA7-Zitation,
Bibliography-Vollständigkeit) → `references/citation-examples.md`.

## Wichtige Regeln

- **Nie Zitate fabrizieren** — nur Text, der direkt aus PDFs extrahiert wurde
- **Exakten Wortlaut bewahren** — Zitate müssen wörtlich der Quelle entsprechen
- **Seitenzahlen angeben** — wenn verfügbar, immer mitführen
- **Zitationsstil respektieren** — durchgehend den konfigurierten Stil nutzen
- **Mismatches flaggen** — Abweichung PDF-Inhalt vs. erwartetes Paper melden
- **User bestätigt Zuordnungen** — Gate in Schritt 6 (`AskUserQuestion`)
