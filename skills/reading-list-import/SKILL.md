---
name: reading-list-import
description: >
  Verwende diesen Skill wenn der User eine Leseliste, Bibliographie oder
  Quellenliste (PDF, Markdown, Plaintext) in den Vault importieren möchte.
  Trigger-Phrasen: "Importiere Reading List", "Prof-Liste einlesen",
  "Bibliographie importieren", "Literaturliste einlesen",
  "Literaturliste importieren", "Reading List importieren",
  "Quellenliste / Quellenliste importieren",
  "Leseliste einlesen / Leseliste prüfen / pruefen".
  Parst Referenzen in der Sitzung, resolvet DOI/ISBN ("Auflösung / Resolution"
  via Crossref + DNB), und schreibt alles in den Vault (vault.add_paper).
  Optional: anystyle (Ruby) als Backend, falls installiert.
  Deckt auch die vault-weite Retraction-Prüfung ab (#604, Trigger u.a.
  "Rückzüge im Vault prüfen / pruefen"): `vault.check_retractions()`.
license: MIT
allowed-tools:
  - Bash
  - Read
security:
  - network_allowlist:
      - "api.crossref.org"
      - "services.dnb.de"
      - "openlibrary.org"
      - "www.googleapis.com"
---

# Reading-List-Import Skill

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Zweck

Importiert eine Referenzliste (Literaturliste, Reading List, Bibliographie)
eines Professors oder aus einem Paper in den academic-research Vault.
Unterstützt PDF, Markdown und Plaintext. Dedupliziert via DOI/ISBN.

## Voraussetzungen

### 1. Abhängigkeiten

```bash
pip install requests lxml
# Optional für PDF:
pip install pypdf
# Optional: anystyle (Ruby-Gem) für strukturiertes Parsen
gem install anystyle-cli
```

Kein API-Key nötig: das Parsen macht der Skill in der Sitzung.

### 2. Vault-Datenbank vorhanden

Der Vault muss initialisiert sein (z.B. via `vault.init_schema()`).

## Verwendung

### Automatisch (Skill-Trigger)

Claude erkennt folgende Phrasen:
- "Importiere Reading List"
- "Prof-Liste einlesen"
- "Bibliographie importieren"
- "Literaturliste einlesen"

### Manuell

Zweistufig: Stufe 1 gibt den Rohtext aus, du parst ihn, Stufe 2 importiert.

```bash
P=${CLAUDE_PLUGIN_ROOT}/skills/reading-list-import/scripts/parse_list.py
python $P --extract --file /Pfad/zur/Literaturliste.pdf
python $P --entries entries.json --db ~/.academic-research/.../vault.db
```

`entries.json` ist ein JSON-Array mit `author`, `title`, `year`, `doi`, `isbn`
und optional `_ambiguous`/`_candidates`. Feldtabelle, Beispiel und die Regel
„nichts erfinden": `references/entry-schema.md`

### Unterstützte Formate

- `.pdf` — Text wird via pypdf oder pdfminer.six extrahiert
- `.md` / `.markdown` — direkt eingelesen
- `.txt` — direkt eingelesen

Erwartete Inhalts-Formate: APA, BibTeX-Snippets, Plain-Stil.
Detaillierte Format-Hinweise: `references/format-hints.md`

## Pipeline

```
Datei-Eingabe
    ↓
Text-Extraktion (`--extract`: pypdf für PDF, direkt für md/txt)
    ↓
Parsen in der Sitzung: Text → [{author, title, year, doi, isbn, ...}]
    ↓  (optional: anystyle-Fallback)
`--entries`: JSON entgegennehmen und validieren
    ↓
DOI-Resolution: Crossref-API → CSL-JSON
    ↓
ISBN-Resolution: DNB SRU + OpenLibrary + GoogleBooks → CSL-JSON
    ↓
Fallback: minimales CSL-JSON aus geparsten Daten
    ↓
Vault.is_excluded() je Eintrag → Treffer: überspringen
    ↓
Vault.add_paper() für jeden Eintrag (Dedup via DOI/ISBN)
    ↓
Retraction-Check (nur bei DOI): Crossref update-type:retraction
    ↓ (Treffer)
Vault.add_excluded_source() markiert das Paper automatisch
    ↓
Ergebnis: N importiert, M übersprungen, Fehler
```

### Anystyle (optional)

Falls `anystyle` installiert ist, dient es als vorgelagerter Parser.
Claude prüft die Verfügbarkeit automatisch:

```bash
# Prüfe ob anystyle verfügbar
anystyle --version 2>/dev/null && echo "verfügbar" || echo "nicht installiert"
```

Bei Verfügbarkeit parst anystyle initial; der Skill prüft und ergänzt.

## Verhalten

1. Datei-Pfad entgegennehmen (Argument oder via User-Frage)
2. Rohtext holen: `parse_list.py --extract --file <liste>`
3. Rohtext selbst ins Eintrags-Schema überführen, als `entries.json` ablegen,
   dann `parse_list.py --entries entries.json --db <vault>`
4. Für jeden Eintrag: DOI/ISBN resolven → CSL-JSON
5. `vault.is_excluded(citekey)` vorab prüfen: Treffer → überspringen und als
   „ausgeschlossen" zählen, sonst holt der Re-Import aussortierte Quellen zurück
6. `vault.add_paper()` aufrufen (idempotent: Dedup via DOI/ISBN)
7. Bei vorhandenem DOI: Retraction-Status via Crossref prüfen (`updated-by`-Feld,
   `type: retraction`) — Treffer → `vault.add_excluded_source()`, Ausfall
   blockiert den Ingest nicht (fail-safe)
8. Bei Mehrdeutigkeit (_ambiguous: true): AskUserQuestion-Tool nutzen
9. Ergebnis melden: N importiert, M übersprungen

## Mehrdeutigkeiten

Kommen beim Parsen mehrere Quellen für einen Eintrag in Frage (z.B.
gleichnamige Arbeiten verschiedener Autoren), gehört er mit `_ambiguous: true`
und `_candidates` ins JSON — der Import fragt den User dann via
`AskUserQuestion` nach der gemeinten Quelle. Beispiel:
`references/entry-schema.md`.

## Vault-weite Retraction-Prüfung (Issue #604)

Wiederholbarer Check über den gesamten Vault statt nur beim Import: MCP-Tool
`vault.check_retractions(max_age_days=90, force=False, project_dir=".")`.
Ablauf, Fundstelle-Semantik und `cited_in_chapter`-Heuristik:
`references/vault-wide-retraction-check.md`.

## Sicherheitshinweise

- **Read-only Netz**: Nur lesende API-Zugriffe (Crossref, DNB, OpenLibrary)
- **Kein Schreiben in externe Systeme**: Nur Vault lokal
- **Kein API-Key**: das Skript braucht keinen eigenen Modellzugang (#632)
- **Keine PDFs heruntergeladen**: Nur Metadaten werden im Vault gespeichert
- **Retraction-Check**: kostenloser Crossref-Call bei DOI (`network_allowlist`
  bereits vorhanden); Treffer → automatisch `excluded_source`, kein Hard-Fail

## Bekannte Einschränkungen

- Einträge ohne DOI und ISBN können nicht dedupliziert werden;
  sie werden bei erneutem Import neu angelegt
- PDF-Extraktion erfordert pypdf oder pdfminer.six
- Scan-PDFs (keine Textschicht) können nicht verarbeitet werden;
  OCR muss vorgelagert werden
- anystyle erfordert Ruby-Umgebung (optional, kein Pflicht-Dep)
- Netz-Ausfälle führen zu minimalem CSL-JSON aus den geparsten Daten
