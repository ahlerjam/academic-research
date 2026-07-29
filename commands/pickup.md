---
name: academic-research:pickup
description: Erzeugt eine Bibliotheks-Pickup-Liste als Excel-Datei (4 Sheets nach Verfügbarkeitsstatus) aus Vault-Einträgen. Code128-Barcodes für ISBNs werden als Zellbild eingebettet.
allowed-tools: Read, Write, Bash(python3 *), Skill(document-skills:xlsx)
argument-hint: [--filter <verfuegbar|fernleihe|oa|lizenz>] [--output <file.xlsx>]
---

# /academic-research:pickup

Erstellt `pickup-list.xlsx` mit 4 Sheets aus den übergebenen Vault-Einträgen.

## Sheets (nach Verfügbarkeitsstatus)

| Sheet | `availability_status` |
|-------|-----------------------|
| Vor Ort verfügbar | `vor_ort_verfuegbar` |
| Fernleihe | `fernleihe` |
| Online OA | `online_oa` |
| Lizenz nötig | `lizenz_noetig` oder nicht gesetzt |

## Verwendung

```
/academic-research:pickup
```

Führe diesen Command aus, wenn du aus deiner Vault-Auswahl eine druckfertige
Pickup-Liste für die Bibliothek brauchst. Der Command:

1. Liest alle markierten Vault-Einträge mit `availability_status`-Feld.
2. Erzeugt Code128-Barcode-PNGs für ISBNs via `scripts/barcode_utils.py`.
3. Baut die 4-Sheet-Struktur:
   - **Vor Ort verfügbar:** Titel, Autor, ISBN, Barcode (Bild), Signatur, Standort
   - **Fernleihe:** Titel, Autor, ISBN, Barcode (Bild), Verlag, Erscheinungsjahr
   - **Online OA:** Titel, Autor, URL, Zugriffsdatum
   - **Lizenz nötig:** Titel, Autor, ISBN/DOI, Verlag, Preis-Schätzung
4. Ruft `document-skills:xlsx` auf, um die Excel-Datei zu erzeugen:
   - `create_workbook` mit 4 Sheets
   - `write_rows` pro Sheet
   - `insert_image` für Barcode-PNGs (Bücher mit ISBN)
   - `save_workbook` → `pickup-list.xlsx`

## Excel-Backend

<!-- xlsx-backend:start -->
Die Excel-Erzeugung übernimmt der externe Skill `document-skills:xlsx` aus dem
Marketplace `anthropic-agent-skills` (Repository `anthropics/skills`). Das Plugin
`academic-research` deklariert ihn als Abhängigkeit in `.claude-plugin/plugin.json`
— eine frische Installation zieht ihn automatisch mit, sofern der Marketplace
bereits hinzugefügt ist. Der Skill führt Python mit `openpyxl` und `pandas` im
lokalen Environment aus; beide Pakete installiert `/academic-research:setup` mit.

**Vor dem ersten Skill-Aufruf prüfen:** Ist der Skill `document-skills:xlsx` aufrufbar?
Falls nicht, brich mit dieser Meldung ab, statt einen rohen Tool-Fehler durchzureichen:

> Das Excel-Backend `document-skills:xlsx` ist nicht installiert — es wird
> deshalb keine Excel-Datei erzeugt. So installierst du es nach:
>
> ```bash
> claude plugin marketplace add anthropics/skills
> claude plugin install document-skills@anthropic-agent-skills
> ```
>
> Danach `/reload-plugins` ausführen und den Command erneut aufrufen.
<!-- xlsx-backend:end -->

## Weitere Abhängigkeiten

### Optional (für Barcode-PNGs)

- **`python-barcode[images]`** — Code128-PNG-Generierung
  - Installation: `pip install "python-barcode[images]"` im Projekt-Venv
  - Fallback: Wenn nicht installiert, wird die Barcode-Spalte leer gelassen
    (kein Crash, nur Hinweis im Output)

## Fehlerbehandlung

- **`document-skills:xlsx` nicht verfügbar:**
  Meldung aus dem Abschnitt „Excel-Backend" ausgeben und abbrechen.

- **`python-barcode` nicht installiert:**
  Warnung im Output; Excel-Datei wird ohne Barcode-Bilder erzeugt.

- **Kein `availability_status` im Eintrag:**
  Eintrag landet automatisch im Sheet „Lizenz nötig".

## Workflow-Schritte (für den ausführenden Agenten)

```python
# 1. Vault-Einträge laden (aus Vault-Auswahl oder Argument)
entries = load_vault_selection()

# 2. Barcode-PNGs erzeugen
from scripts.barcode_utils import generate_isbn_barcode, build_pickup_sheets

barcode_paths = {}
for entry in entries:
    isbn = entry.get("isbn")
    if isbn:
        path = generate_isbn_barcode(isbn)
        if path:
            barcode_paths[entry["citekey"]] = path

# 3. Einträge auf Sheets verteilen
sheets = build_pickup_sheets(entries)

# 4. Excel via document-skills:xlsx erzeugen
# Skill-Aufruf (document-skills:xlsx):
#   create_workbook(sheets=["Vor Ort verfügbar", "Fernleihe", "Online OA", "Lizenz nötig"])
#   write_rows(sheet="Vor Ort verfügbar", rows=[...])
#   insert_image(sheet="Vor Ort verfügbar", row=i, col="Barcode", path=barcode_paths[citekey])
#   save_workbook(path="pickup-list.xlsx")
```

## Hinweise

- Alle Vault-Einträge der Auswahl werden aufgenommen — kein OA-Filter.
- Sheet-Zuordnung basiert ausschließlich auf `availability_status`.
- `pickup_required`-Einträge aus `/academic-research:fetch` haben typisch
  `availability_status: fernleihe` oder `availability_status: lizenz_noetig`.
- Spec: `specs/v6.2/I.md`
