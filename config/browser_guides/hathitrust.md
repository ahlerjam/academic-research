# HathiTrust — Browser-Guide (Buch-Download)

**URL:** https://babel.hathitrust.org (Katalog: https://catalog.hathitrust.org)
**Auth:** keine für gemeinfreie Volltexte; HathiTrust-Konto (kostenlos, i.d.R.
institutionell via Shibboleth) nur für "Search-only"-Titel mit eingeschränktem
Textabruf (Full-Text-Search innerhalb des Buchs), nicht für Full-View-Download.
**Anti-Scraping:** mittel — HathiTrust begrenzt Massen-Downloads (Rate-Limits,
gelegentlich temporäre 429-Sperren bei zu vielen Seitenabrufen kurz hintereinander).

## Login-Flow

1. `browser-use open https://catalog.hathitrust.org`
2. Für **Full-View**-Titel (gemeinfrei, "Full view"-Badge): kein Login nötig.
3. Für **Search-only**-Titel: Login nur relevant, wenn eine Institution mit
   Shibboleth-Föderation konfiguriert ist — hier NICHT versuchen, da
   Search-only-Titel ohnehin nicht als Volltext-PDF exportiert werden dürfen
   (siehe Access-Level-Matrix).

## Discovery-Pfad

1. Katalogsuche: `browser-use open "https://catalog.hathitrust.org/Search/Home?lookfor=<query>&type=all"`
   (query = ISBN, Titel oder Autor, URL-encoded)
2. `browser-use state` → Trefferliste lesen.
3. Access-Badge pro Treffer prüfen: **"Full view"** vs. **"Limited (search-only)"**
   vs. **"Full view (original from ...)"**.
4. Auf Treffer klicken → Katalog-Detailseite mit Digitalisat-Liste (mehrere
   Bibliotheken können dasselbe Werk digitalisiert haben — mehrere Exemplare
   möglich, jedes mit eigenem Erscheinungsjahr/Ausgabe des jeweiligen
   physischen Scans).
5. Digitalisat mit "Full view"-Badge auswählen → öffnet den Reader
   (`babel.hathitrust.org/cgi/pt?id=<hathi-id>`).

## Volltext-Lokation (nur Full-View)

- Im Reader: Menü "Download this book" (meist über ein Zahnrad-/Download-Icon
  oder im Seitenmenü "Downloads").
- Optionen dort: "PDF" (ganzes Buch, evtl. mit Bestätigungsdialog wegen
  Bulk-Download-Schutz) oder "PDF (this page)" — für den vollständigen Download
  die Ganzbuch-Option wählen.
- Bestätigungsdialog ("Are you a human?" / Download-Größe-Warnung) bestätigen,
  falls vorhanden — kein CAPTCHA-Umgehen, nur normaler Klick-Dialog.
- `browser-use download <link-idx> --to <output_path>`
- Große Werke (>500 Seiten) können HathiTrust serverseitig als Hintergrundjob
  zusammenstellen ("Your PDF is being prepared") — auf Fertigstellung warten
  und danach erneut versuchen.

## Access-Level-Matrix

| Badge im Katalog | Bedeutung | Aktion |
|---|---|---|
| "Full view" | gemeinfrei, komplett einsehbar | Full-PDF-Download versuchen → `success` |
| "Limited (search-only)" | urheberrechtlich geschützt, nur Volltextsuche INNERHALB des Buchs möglich, keine Seiten-/Buchansicht | NIEMALS Suchtreffer-Snippets zu einem Text zusammensetzen → `metadata_only` mit `reason: "Zugriffsstufe: search-only"` |
| "Limited (no full-text search)" | nur bibliografische Metadaten | `metadata_only` mit `reason: "Zugriffsstufe: nur Metadaten"` |

## Ausgabe-/Jahresangabe

Jahr, Ausgabe und Verlag stammen aus dem **Katalogeintrag des konkret gewählten
Digitalisats** (Feld "Published" auf der Detailseite des jeweiligen Exemplars),
nicht aus der Eingabe-ISBN oder dem Eingabe-Titel. Verschiedene Bibliotheken
können unterschiedliche Auflagen desselben Werks digitalisiert haben — das Jahr
des tatsächlich heruntergeladenen Scans übernehmen.

## Pickup-Triggers

- `status: metadata_only` wenn:
  - Badge ist "Limited (search-only)" oder "Limited (no full-text search)".
  - "Full view"-Digitalisat vorhanden, aber Download-Menü liefert keinen
    PDF-Link (seltener Rand-Fall).
- `status: captcha` wenn ein echtes CAPTCHA (nicht der normale
  Bestätigungsdialog) in `browser-use state` sichtbar ist.
- `status: no_match` wenn Katalogsuche 0 Treffer liefert.
- **HTTP 429 / Rate-Limit:** Kein Fehldiagnose als `no_match` oder `captcha`.
  Statuscode und Retry-Hinweis explizit im `reason`-Feld nennen, z. B.
  `"HTTP 429 — Rate-Limit, Retry empfohlen nach Wartezeit"`. Dies gilt gemäß
  Issue #450 AC1 als erfülltes Kriterium, sofern korrekt diagnostiziert.

## Bekannte Fallstricke

- Ein Katalogeintrag kann mehrere Digitalisate (verschiedene Bibliotheken,
  verschiedene Auflagen) bündeln — das mit "Full view" auswählen, nicht
  automatisch das erste.
- Bulk-Download-Schutz kann bei großen Werken einen serverseitigen
  Vorbereitungsschritt auslösen — kein Fehler, nur Wartezeit.
- Rate-Limit (HTTP 429) bei zu vielen Seitenabrufen/Downloads kurz
  hintereinander — 2-3 Sekunden Pause zwischen Aktionen, bei 429 nicht
  wiederholt sofort erneut versuchen.
- "Search-only"-Snippets NIEMALS zu einem Volltext zusammensetzen — das ist
  ein Verstoß gegen die Zugriffsstufe der Quelle.
