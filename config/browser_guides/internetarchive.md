# Internet Archive / Open Library — Browser-Guide (archive.org, openlibrary.org)

**URL:** https://archive.org (Volltext-Host + Suche), https://openlibrary.org
(Metadaten-Ebene, verlinkt auf archive.org-Editionen)
**Auth:** kein Login fuer frei ladbare (gemeinfreie) Titel; Controlled-Digital-
Lending-Titel (CDL, "Borrow") verlangen Login + zeitlich begrenzte Ausleihe im
DRM-geschuetzten BookReader — kein PDF-Export moeglich.
**Anti-Scraping:** niedrig fuer freie Items; der CDL-BookReader ist technisch
DRM-geschuetzt (Lesen ausschliesslich im Browser-Viewer).

## Zugriffsstufen-Matrix

| Stufe | Bedeutung | Kennzeichen |
| --- | --- | --- |
| **Vollansicht** ("Free to download") | Datei direkt ladbar, gemeinfrei | "DOWNLOAD OPTIONS"-Panel mit PDF-Link |
| **Borrow-only** (Controlled Digital Lending) | Nur Lesen nach Ausleihe im Wasserzeichen-Reader, kein Download | Button "Borrow" statt Download-Panel |
| **nur Metadaten** | Reiner Katalogeintrag (haeufig bei Open-Library-only-Treffern) ohne verknuepftes Digitalisat | kein "Read"/"Borrow"-Button auf der Edition-Seite |

Nur bei **Vollansicht** wird heruntergeladen. Bei **Borrow-only**: NIEMALS
ausleihen, NIEMALS den Reader oeffnen und Seiten zu einem Pseudo-PDF
zusammensetzen — das ist der Kernfall aus Issue #450/AC2.

## Login-Flow

Kein Login fuer den Standard-Fall (freie Downloads).

1. `browser-use open https://archive.org`
2. Direkt zur Discovery fortfahren.

## Discovery-Pfad

1. `browser-use open https://archive.org/search?query=<query>` (ISBN, DOI oder
   Titel, URL-encoded). Alternativ ueber Open Library:
   `https://openlibrary.org/search?q=<query>`.
2. `browser-use state` → Trefferliste lesen.
3. Bei 0 Treffern auf archive.org: Open-Library-Suche versuchen (verlinkt ggf.
   auf ein archive.org-Item, das die direkte Suche nicht fand).
4. Bei 0 Treffern in beiden: `{"status": "no_match", "source_subagent": "internetarchive-fetcher", "reason": "0 Treffer auf archive.org/openlibrary.org"}`
5. Auf Treffer klicken → Item-Seite (archive.org) bzw. Edition-Seite
   (openlibrary.org → "Read"-Link fuehrt zum archive.org-Item).

## Volltext-Lokation

1. Auf der archive.org-Item-Seite: `browser-use state` → "DOWNLOAD OPTIONS"-
   Panel suchen.
2. Vorhanden → den Farb-Eintrag "PDF download" waehlen (`_bw.pdf` ist die
   Graustufen-Zweitausgabe), dann `browser-use click <pdf-link-idx>` — es gibt **kein**
   `browser-use download`-Unterkommando (verifiziert gegen browser-use 0.12.6).
   Chromium nimmt den Download selbst an und legt die Datei unter
   `<TMPDIR>/browser-use-downloads-<id>/` ab; von dort nach `<output_path>`
   verschieben.
3. Kein Download-Panel, aber Button "Borrow" sichtbar → CDL-Fall →
   `metadata_only` mit `reason: "Zugriffsstufe: Borrow-only (Controlled Digital Lending)"`.
4. Open-Library-Eintrag ohne verlinktes archive.org-Item (nur Katalogdaten) →
   `metadata_only` mit `reason: "Zugriffsstufe: nur Metadaten"`.
5. Validation: erste 4 Bytes = `%PDF`, Groesse > 10 KB.

## Ausgabe-Metadaten (Edition)

Der Reiter "About This Book" / die Metadaten-Tabelle auf der Item-Seite (bzw.
die Edition-Seite auf openlibrary.org) nennt Jahr, Auflage und Verlag DES
DIGITALISIERTEN EXEMPLARS — oft ein spezifischer, spaeterer Druck. Immer von
dort uebernehmen, nie aus der Eingabe-ISBN/dem Eingabe-Titel raten.

## Pickup-Triggers

- `status: metadata_only` wenn:
  - Zugriffsstufe ist "Borrow-only" oder "nur Metadaten".
- `status: no_match` wenn beide Suchen 0 Treffer liefern.
- `status: captcha` wenn ein CAPTCHA/Bot-Check-Screen erscheint.

## Bekannte Fallstricke

- Open Library ist reine Metadaten-Ebene: mehrere Editionen desselben Werks
  koennen auf unterschiedliche archive.org-Items zeigen (manche frei, manche
  Borrow-only) — Edition mit "Vollansicht" bevorzugen, wenn vorhanden.
- CDL-Titel zeigen im Suchresultat oft ein Uhr-Icon oder "Borrow" statt
  "Download" — vor dem Klicken auf der Trefferliste bereits erkennbar.
- Manche gemeinfreien Werke sind dennoch als "Borrow" markiert (Rechte-Review
  des Archivs noch nicht abgeschlossen) — dann gilt trotzdem Borrow-only, kein
  Sonderfall.
- Der digitalisierte Druck kann Jahrzehnte nach dem Erstdruck erschienen sein
  (Bibliotheksexemplar) — Ausgabejahr immer aus den Item-Metadaten lesen.
