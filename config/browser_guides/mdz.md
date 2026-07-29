# MDZ — Münchener Digitalisierungszentrum — Browser-Guide (digitale-sammlungen.de)

**URL:** https://www.digitale-sammlungen.de (Bayerische Staatsbibliothek)
**Auth:** keine — alle dort gefuehrten Digitalisate sind frei zugaengliche,
gemeinfreie Bestaende.
**Anti-Scraping:** niedrig — oeffentlicher Bibliotheksdienst.

## Zugriffsstufen-Matrix

| Stufe | Bedeutung | Kennzeichen |
| --- | --- | --- |
| **Vollansicht** | Digitalisat online, Viewer + Download vorhanden | Viewer-Link auf der Trefferseite fuehrt zu einer bsb-URN-Seite mit Download-Icon |
| **nur Metadaten** | Werk noch nicht digitalisiert, nur OPAC-Katalogeintrag | kein Viewer-Link, nur Bestandsnachweis |

MDZ kennt keine Zwischenstufe wie Suche-im-Buch — entweder ist der komplette
Band online oder es existiert (noch) kein Digitalisat.

## Login-Flow

Kein Login erforderlich.

1. `browser-use open https://www.digitale-sammlungen.de`
2. Direkt zur Discovery fortfahren.

## Discovery-Pfad

1. `browser-use open https://www.digitale-sammlungen.de/de/search?query=<query>`
   (`query` = ISBN, Titel oder Autor, URL-encoded)
2. `browser-use state` → Trefferliste lesen.
3. Bei 0 Treffern: `{"status": "no_match", "source_subagent": "mdz-fetcher", "reason": "0 Treffer auf digitale-sammlungen.de"}`
4. Auf Treffer klicken → Werk-Detailseite (bsb-URN).
5. Bei mehrbaendigen Werken: richtigen Band anhand Titelblatt/Bandzaehlung
   waehlen, nicht automatisch den ersten Treffer nehmen.

## Volltext-Lokation

1. Auf der Detail-/Viewer-Seite: `browser-use state` → Download-Icon/-Menue
   suchen ("PDF-Download", teils mit Seitenbereichs-Auswahl "gesamtes Werk").
2. Vorhanden → "gesamtes Werk" bzw. Default-Bereich waehlen,
   `browser-use download <pdf-link-idx> --to <output_path>`.
3. Kein Viewer/kein Digitalisat verlinkt (nur OPAC-Metadaten) →
   `{"status": "metadata_only", "source_subagent": "mdz-fetcher", "url": "<detailseite-url>", "reason": "Zugriffsstufe: nur Metadaten"}`
4. Validation: erste 4 Bytes = `%PDF`, Groesse > 10 KB.

## Ausgabe-Metadaten (Edition)

Die Titelaufnahme auf der Werk-Detailseite (Strukturdaten-/Metadaten-Panel)
nennt Jahr, Auflage und Verlag DES DIGITALISIERTEN EXEMPLARS. Historische
Bestaende sind haeufig spaetere Nachdrucke oder eine bestimmte, konkrete
Auflage — immer von dort uebernehmen, nie aus der Eingabe-ISBN/dem
Eingabe-Titel raten.

## Pickup-Triggers

- `status: metadata_only` wenn kein Viewer-/Download-Link auf der
  Detailseite vorhanden ist (Werk noch nicht digitalisiert).
- `status: no_match` wenn Suche 0 Treffer liefert.
- `status: captcha` wenn ein CAPTCHA/Bot-Check-Screen erscheint (selten).

## Bekannte Fallstricke

- Der OCR-Volltext-Tab im Viewer ist Rohtext ohne Nachbearbeitung — das faellt
  unter `scripts/ocr.py` (Out-of-Scope fuer diesen Agent, niemals als Ersatz
  fuer den PDF-Download zusammensetzen).
- Mehrbaendige Werke/Zeitschriften-Jahrgaenge: ein Suchtreffer kann auf die
  Gesamtaufnahme statt auf einen konkreten Band zeigen — pruefen, ob der
  Download tatsaechlich den gesuchten Band enthaelt.
- Manche Titel sind nur als Mikrofilm-Digitalisat mit schlechter OCR-Qualitaet
  vorhanden — das aendert nichts an der Zugriffsstufe "Vollansicht" (PDF ist
  trotzdem ladbar).
