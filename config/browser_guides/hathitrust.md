# HathiTrust — Browser-Guide (babel.hathitrust.org)

**URL:** https://babel.hathitrust.org (Viewer/Download), https://catalog.hathitrust.org (Katalog-Suche)
**Auth:** kein Login fuer Full-View-Titel noetig; manche sehr umfangreichen Baende
verlangen fuer den Ganzbuch-PDF-Download einen (kostenlosen) HathiTrust-Account.
**Anti-Scraping:** mittel — Bulk-Download-Schutz und gelegentliche CAPTCHAs bei
verdaechtig schnellen/vielen Seitenabrufen.

## Zugriffsstufen-Matrix

HathiTrust fuehrt pro digitalisiertem Band eine von drei Stufen. Die Stufe steht
als Badge auf der Trefferliste UND auf der Item-Seite:

| Stufe | Bedeutung | Kennzeichen |
| --- | --- | --- |
| **Vollansicht** ("Full view") | Ganzes Werk frei einsehbar, i.d.R. gemeinfrei | Badge "Full view" |
| **Suche-im-Buch** ("Limited, search-only") | Nur Volltextsuche im Buch, keine Seiten-Ansicht am Stueck | Badge "Limited (search-only)" |
| **nur Metadaten** ("No preview") | Reiner Katalogeintrag ohne Leseansicht | kein Viewer-Link auf der Detailseite |

Nur bei **Vollansicht** ist ein PDF-Download realistisch. Bei den anderen beiden
Stufen: sofort `metadata_only` mit der Stufe im `reason`-Feld, KEIN Versuch,
Seiten einzeln zusammenzusetzen.

## Login-Flow

Kein Login fuer den Standard-Fall (Vollansicht, kleinere Werke).

1. `browser-use open https://babel.hathitrust.org`
2. Direkt zur Discovery fortfahren.

## Discovery-Pfad

1. `browser-use open https://catalog.hathitrust.org/Search/Home?lookfor=<query>&type=all`
   (`query` = ISBN, Titel oder Autor, URL-encoded)
2. `browser-use state` → Trefferliste lesen, Zugriffsstufen-Badge je Treffer pruefen.
3. Plausibelsten Treffer waehlen (Titel/Autor/Jahr matcht Eingabe).
4. Bei 0 Treffern: `{"status": "no_match", "source_subagent": "hathitrust-fetcher", "reason": "0 Treffer im HathiTrust-Katalog"}`
5. Auf Treffer klicken → Katalog-Datensatz → "View full text at Hathitrust"-Link → Item-Viewer.

## Volltext-Lokation

1. Auf der Item-Viewer-Seite: Zugriffsstufe im UI erneut bestaetigen ("Full view"
   sichtbar? sonst siehe Zugriffsstufen-Matrix).
2. Bei Vollansicht: Menue "Download" → "PDF (whole book)" waehlen.
3. Bei sehr grossen Werken kann ein Bestaetigungsdialog erscheinen (Seitenzahl-
   Limit, ggf. Hinweis auf laengere Generierungszeit). Bestaetigen, sofern kein
   zusaetzliches Login verlangt wird.
4. Verlangt der Download-Dialog ein Login, das nicht konfiguriert ist: KEIN
   Umgehungsversuch → `metadata_only` mit `reason: "Zugriffsstufe: Vollansicht
   (Download erfordert HathiTrust-Login)"`.
5. `browser-use click <pdf-link-idx>` — es gibt **kein**
   `browser-use download`-Unterkommando (verifiziert gegen browser-use 0.12.6).
   Chromium nimmt den Download selbst an und legt die Datei unter
   `<TMPDIR>/browser-use-downloads-<id>/` ab; von dort nach `<output_path>`
   verschieben.
6. Antwortet die Download-Route mit "Error code: 429", "IMAGE TEMPORARILY
   UNAVAILABLE" oder "Please try again.", greift das Rate-Limit. Das ist ein
   voruebergehender Zustand: kurz warten und erneut versuchen, insgesamt bis zu
   drei Versuche. Erst danach `pickup_required` mit
   `reason: "Zugriffsstufe: Vollansicht, Download vom Rate-Limit abgewiesen (HTTP 429)"`.
7. Validation von der Platte: erste 5 Bytes = `%PDF-`, Groesse > 10 KB.

## robots.txt (Stand 2026-07-29)

`https://babel.hathitrust.org/robots.txt` fuehrt fuer `User-agent: *` nur
`Crawl-delay: 1` und `Disallow: /cgi/`. Viewer (`/cgi/pt`) und Download-Route
(`/cgi/imgsrv/...`) liegen beide dort; `Allow`-Eintraege dafuer gibt es nur fuer
benannte Suchmaschinen. Cloudflare-Challenge (403) und Rate-Limit (429) setzen
das durch. Praktisch: nie crawlen, immer nur den einen angefragten Titel,
mindestens eine Sekunde zwischen Abrufen, nach drei Fehlversuchen aufhoeren.

## Ausgabe-Metadaten (Edition)

Auf der Katalog-Detailseite ("Catalog Record" / MARC-Ansicht) stehen Jahr,
Auflage/Ausgabe und Verlag DES DIGITALISIERTEN EXEMPLARS — diese koennen vom
Erscheinungsjahr des Originalwerks abweichen (z.B. spaeterer Nachdruck). Immer
von dort uebernehmen, nie aus der Eingabe-ISBN/dem Eingabe-Titel raten.

## Pickup-Triggers

- `status: metadata_only` wenn:
  - Zugriffsstufe ist "Suche-im-Buch" oder "nur Metadaten".
  - Vollansicht vorhanden, aber Download erfordert nicht-konfiguriertes Login.
- `status: no_match` wenn Katalogsuche 0 Treffer liefert.
- `status: captcha` wenn ein CAPTCHA/Bot-Check-Screen erscheint.

## Bekannte Fallstricke

- "Suche-im-Buch" liefert bei einer Textsuche einzelne Snippet-Treffer — diese
  NIE zu einem Pseudo-Volltext zusammensetzen (siehe Verbote im Agent-Prompt).
- Mehrbaendige Werke: jeder Band hat einen eigenen Katalog-/Item-Eintrag —
  richtigen Band anhand Titel/Bandzaehlung waehlen.
- Rate-Limiting bei vielen Seitenabrufen kurz hintereinander → CAPTCHA moeglich.
- Digitalisat-Jahr (Scan/Katalogisierung) ist nicht das Erscheinungsjahr des
  digitalisierten Exemplars — Ausgabejahr immer aus dem Katalogdatensatz lesen.
