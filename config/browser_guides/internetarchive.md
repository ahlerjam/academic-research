# Internet Archive / Open Library — Browser-Guide (Buch-Download)

**URL:** https://archive.org (Discovery zusätzlich über https://openlibrary.org)
**Auth:** keine für frei herunterladbare Titel; Internet-Archive-Konto
(kostenlos) nur nötig, um kontrolliert verleihbare ("Controlled Digital
Lending", CDL) Titel im Browser-Reader zu **lesen** — diese dürfen NICHT als
PDF exportiert werden.
**Anti-Scraping:** niedrig-mittel — Archive.org ist kooperativ, aber
Massen-Downloads können gedrosselt werden.

## Login-Flow

1. `browser-use open https://archive.org`
2. Für Titel mit direktem Download-Recht (Public Domain / "Borrow"-Badge
   fehlt): kein Login nötig.
3. Für CDL-/Borrow-Titel: Login wird zwar angeboten, aber NICHT verwenden —
   solche Titel sind nicht gemeinfrei und liegen außerhalb des Scopes von
   #450 (kein DRM-Reader-Export). Direkt als eingeschränkte Zugriffsstufe
   melden.

## Discovery-Pfad

1. Bevorzugt über Open Library für saubere Edition-Metadaten:
   `browser-use open "https://openlibrary.org/search?q=<query>"`
   (query = ISBN, Titel oder Autor, URL-encoded)
2. `browser-use state` → Trefferliste lesen, passende Edition wählen
   (Open Library listet mehrere Ausgaben/Editionen desselben Werks getrennt).
3. Alternativ Direktsuche auf Archive.org:
   `browser-use open "https://archive.org/search?query=<query>&sin=TXT"`
4. Auf Treffer klicken → Item-Detailseite (`archive.org/details/<identifier>`).
5. Zugriffsstufe auf der Detailseite prüfen (siehe Access-Level-Matrix).

## Volltext-Lokation

- Auf der Item-Detailseite: rechter "Download Options"-Block.
- Bei frei herunterladbaren Titeln: Link "PDF" direkt anklicken.
  `browser-use download <pdf-link-idx> --to <output_path>`
- Manche Items zeigen den PDF-Download-Link erst nach Klick auf
  "SHOW ALL" / "14 Files" im Download-Block — dort öffnen und den
  `*.pdf`-Eintrag suchen (nicht `_djvu.txt`, nicht `_abbyy.gz`).
- Bei CDL-/Borrow-Items ("Borrow"-Button statt Download-Liste): NICHT den
  In-Browser-Reader öffnen und NICHT versuchen, Seiten zu exportieren —
  sofort als eingeschränkte Zugriffsstufe melden.

## Access-Level-Matrix

| Signal auf Item-Seite | Bedeutung | Aktion |
|---|---|---|
| "Download Options"-Block mit PDF-Link, kein "Borrow"-Button | frei/gemeinfrei | PDF-Download versuchen → `success` |
| "Borrow"-Button, In-Browser-Reader (BookReader) | Controlled Digital Lending — urheberrechtlich geschützt | `metadata_only` mit `reason: "Zugriffsstufe: Borrow/CDL — kein PDF-Export"` |
| Metadatenfeld `access-restricted-item: true` (meist zusammen mit Sammlung `inlibrary`) | Controlled Digital Lending — gilt auch dann, wenn eine PDF-Datei gelistet ist und kein Borrow-Button sichtbar ist | `metadata_only`, gar nicht erst herunterladen |
| Download bricht mit HTTP 401 **oder 403** ab | dasselbe wie oben, nur später bemerkt | `metadata_only` mit `reason: "Zugriffsstufe: Borrow/CDL — HTTP <Code>, kein PDF-Export"`, **kein** Retry |
| Nur Metadaten-Item ohne Datei-Liste | kein Volltext vorhanden | `metadata_only` mit `reason: "Zugriffsstufe: nur Metadaten"` |

## Ausgabe-/Jahresangabe

Jahr, Ausgabe und Verlag stammen aus den **Item-Metadaten der konkret gewählten
Digitalisierung** (Feld "Publication date" / "Publisher" auf der
Archive.org-Detailseite bzw. der Open-Library-Edition-Seite), nicht aus der
Eingabe-ISBN oder dem Eingabe-Titel. Ein Werk kann auf Archive.org mehrfach
digitalisiert vorliegen (verschiedene Bibliotheksscans derselben oder
verschiedener Auflagen) — das Jahr des tatsächlich gewählten Scans übernehmen.

## Pickup-Triggers

- `status: metadata_only` wenn:
  - Item zeigt "Borrow"-Button statt Download-Liste (CDL).
  - Kein PDF in den Download-Optionen (nur `_djvu.txt`, `_abbyy.gz` o. ä.).
- `status: captcha` wenn ein CAPTCHA in `browser-use state` sichtbar ist.
- `status: no_match` wenn Suche 0 Treffer liefert.
- **HTTP 429 / Rate-Limit:** korrekt diagnostizieren (Statuscode +
  Retry-Hinweis im `reason`-Feld), NICHT als `no_match` fehldeuten — siehe
  Issue #450 AC1.

## Bekannte Fallstricke

- Open Library und Archive.org können für dasselbe Werk leicht abweichende
  Editions-Metadaten zeigen — die Angaben von der tatsächlich heruntergeladenen
  Archive.org-Item-Seite sind maßgeblich, nicht die von Open Library.
- CDL-/Borrow-Items NIEMALS über den In-Browser-Reader Seite für Seite
  exportieren oder screenshotten, um daraus ein PDF zu bauen — das umgeht die
  Zugriffsbeschränkung und ist explizit außerhalb des Scopes.
- Manche Items haben mehrere PDF-Varianten (z. B. OCR-Layer vs. Bild-Scan) —
  die größte/vollständigste Datei wählen, nicht die erste im Listing. Eine
  Variante mit Format "ACS Encrypted PDF" (`*_encrypted.pdf`) ist DRM-geschützt
  und kommt nie in Frage; sie tritt typischerweise bei CDL-Items auf.
- Ein CDL-Item kann sein reguläres PDF im Listing zeigen, ohne es
  herauszugeben — der Download endet dann mit HTTP 401 oder 403. Deshalb vor
  dem Download `access-restricted-item` prüfen und nicht auf das Fehlen des
  Borrow-Buttons vertrauen (real gemessen, siehe
  `evals/free-archive-fetchers/live-verification.json`, Lauf `fa-02`,
  `access_control_counter_example`). archive.org hat den Statuscode für
  denselben Fehlerpfad bereits einmal gewechselt (401 → 403, Issue #799) —
  beide zählen als dieselbe Rechteentscheidung, nicht als Störung und nicht
  als Rate-Limit. Den Download deshalb **nicht** wiederholen.
- Rate-Limiting bei vielen Downloads kurz hintereinander — 2-3 Sekunden Pause.
