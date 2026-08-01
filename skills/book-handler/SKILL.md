---
name: book-handler
description: 'Verwende diesen Skill wenn der User ein Buch / eine Monografie / einen Sammelband verarbeiten möchte. Trigger: "Buch", "Monografie", "Sammelband", "Bücher verarbeiten", "Sammelband prüfen / pruefen", "Kapitel von ...", ISBN-Pattern (\d{3}-\d{1,5}-\d{1,7}-\d{1,7}-\d), Springer-DOI (10.1007/978-). Löst ISBN/Titel/DOI via DNB + OpenLibrary + DOAB auf und legt CSL-JSON im Vault an. Unterstützt "Monografie / Sammelband" als gleichwertige Buchtypen.'
license: MIT
allowed-tools: [Read, Bash, AskUserQuestion]
---

# Buch-Handler

> **Gemeinsames Preamble laden:** Lies `skills/_common/preamble.md`
> und befolge alle dort definierten Blöcke (Vorbedingungen, Keine Fabrikation,
> Aktivierung, Abgrenzung), bevor du mit diesem Skill-spezifischen Inhalt
> fortfährst.

## Übersicht

Indexiert Bücher und Kapitel analog zu Artikeln. Liefert CSL-JSON mit
`type: book | chapter`, Herausgeber-Array und Seitenangaben. Prüft
DOAB/OAPEN auf Open-Access-Verfügbarkeit.

## Abgrenzung

Schneidet keine Kapitel aus PDFs (F2.2), berechnet kein Seitenmapping
(F2.3), führt keine OCR durch (F2.4).
Zitationsformatierung: `citation-extraction`.

## Trigger-Erkennung

Aktiviert sich bei:
- Direkten Begriffen: "Buch", "Monografie", "Sammelband", "Kapitel von ..."
- ISBN-Pattern: `\d{3}-\d{1,5}-\d{1,7}-\d{1,7}-\d`
- Springer-Buch-DOI: `10.1007/978-`

## Workflow

### 1. Metadaten auflösen

```bash
python scripts/book_resolve.py --isbn {isbn}
python scripts/book_resolve.py --title "{titel}"
python scripts/book_resolve.py --doi {doi}
```

Output: CSL-JSON (type=book|chapter). API-Quellen: `${CLAUDE_PLUGIN_ROOT}/skills/book-handler/references/sources.md`.

### 2. Vault-Eintrag anlegen

```
vault.add_paper(
  paper_id        = "{citekey}",
  csl_json        = "{csl_json_string}",
  isbn            = "{isbn}",
  editor          = "{editor_json}",
  chapter         = "{kapitel_nr}",
  page_first      = {seite_von},
  page_last       = {seite_bis},
  container_title = "{sammelband_titel}"
)
```

Ist der Sammelband selbst schon indexiert, hängen weitere Kapitel per
`vault.add_chapter(parent_paper_id, chapter_number, csl_json, paper_id, page_first,
page_last)` daran — erbt Herausgeber und `container_title` vom Eltern-Eintrag und
gibt die Kapitel-`paper_id` für alle Folgeschritte zurück.

### 2.5. page_offset berechnen und bestätigen

Falls `pdf_path` gesetzt:

```bash
python scripts/page_offset.py {pdf_path}
```

**Gate (Pflicht):** Ein falscher Offset verschiebt alle Seitenzahlen des Buchs.
Lass den Wert daher per `AskUserQuestion` bestätigen, Optionen:

- „Offset {offset} übernehmen — PDF-Seite {offset+1} = gedruckte Seite 1"
- „Offset manuell setzen — Mapping stimmt nicht"

Erst nach der ersten Option `vault.set_page_offset({citekey}, {offset})`
aufrufen. Bei der zweiten Option den Offset vom User erfragen und diesen Wert
speichern; der berechnete Offset wird nie ungefragt übernommen.

### 3. OA-Check

Falls `book_resolve.py` ein `URL`-Feld liefert (DOAB/OAPEN):
- Setze `pdf_path` im Vault-Eintrag
- Informiere User: "OA-PDF verfügbar unter {url}"

### 4. Nachfolge-Hinweise

Nach erfolgreichem Vault-Eintrag dem User anbieten:
- Kapitel extrahieren? -> F2.2: `chunk_pdf.py`
- Scan-PDF (kein Text)? -> Schritt 5 ausführen

### 5. OCR-Prüfung (bei pdf_path vorhanden)

```python
from pdf import detect_needs_ocr

if detect_needs_ocr(pdf_path):
    # User fragen:
    # "Scan-PDF erkannt: wenig Text auf Stichproben-Seiten.
    #  OCR ausführen? (~30 s/Seite, lokal via ocrmypdf) [j/n]"
    # Bei Zustimmung:
    from ocr import run_ocrmypdf

    run_ocrmypdf(pdf_path, pdf_path_ocr)
    vault.set_ocr_done(paper_id)
    vault.update_pdf_path(paper_id, pdf_path_ocr)
    vault.extract_fulltext(paper_id)
```

`vault.extract_fulltext` ist nach jedem `vault.update_pdf_path` Pflicht: Der
Volltext-Index entsteht sonst nur beim Anlegen, und `vault.search` sucht weiter
im leeren Text des Scans.

## Ausgabe

```
Buch indexiert: {titel} ({year})
- paper_id: {citekey}
- type: {type}
- ISBN: {isbn}
- Vault: vault.get_paper("{citekey}")
[- OA-PDF: {url}]
```

## Beispiel

**Gut:** User gibt ISBN 978-3-446-46103-1 an.
book-handler führt `book_resolve.py --isbn 9783446461031` aus,
erhält CSL-JSON (type=book, title, author, publisher, year),
legt Vault-Eintrag an, bestätigt dem User.

**Schlecht:** Metadaten ohne API-Aufruf erfinden -- VERBOTEN.
