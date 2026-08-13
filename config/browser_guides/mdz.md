# MDZ — Münchener Digitalisierungszentrum — Browser-Guide (Buch-Download)

> **Aufrufform der CLI:** `config/browser_guides/_cli.md` — Heredoc-Aufruf,
> Helfer, Element-Adressierung, Download. Dieser Guide enthält nur Site-Wissen.

**URL:** https://www.digitale-sammlungen.de (Bayerische Staatsbibliothek)
**Auth:** keine — MDZ digitalisiert ausschließlich gemeinfreie/rechtefreie
Bestände, kein Login-Konzept für den Volltextzugriff.
**Anti-Scraping:** niedrig — öffentlicher Kulturerbe-Dienst, kooperativ.

## Login-Flow

Kein Login erforderlich. MDZ ist ein Digitalisierungsportal der Bayerischen
Staatsbibliothek für gemeinfreie Werke.

1. `new_tab("https://www.digitale-sammlungen.de")`
2. Direkt zur Discovery fortfahren.

## Discovery-Pfad

1. Suchfeld auf der Startseite: Titel, Autor, ISBN (bei neueren Digitalisaten)
   oder Erscheinungsjahr eingeben.
2. Trefferliste per `js(...)` lesen.
3. Filter "Digitalisat verfügbar" links setzen, falls vorhanden — MDZ listet
   auch rein bibliografische Katalogisate ohne Scan.
4. Auf Treffer klicken → Werkansicht/Viewer öffnet
   (`daten.digitale-sammlungen.de/~db/...` oder `mdz-nbn-resolving.de/...`).

## Volltext-Lokation

- Im Viewer: Download-Icon (Pfeil nach unten) oben rechts → Eintrag
  **"PDF/DaFo"**. Der Eintrag führt auf ein Formular auf
  `download.digitale-sammlungen.de`, nicht auf eine PDF-Datei.
- Dort **PDF** wählen, nicht DaFo: DaFo (Daten für die Forschung) ist eine
  Bestellung hochauflösender Bilder mit Mailadresse und Bereitstellung binnen
  bis zu vier Wochen. Für diesen Agenten ist nur der Sofort-Download als PDF
  relevant.
- Seitenbereich ("Erstes Bild"/"Letztes Bild") steht auf dem Gesamtwerk
  vorbelegt — so belassen.
- **Rechtehinweis bestätigen — Pflichtschritt, sonst kein PDF.** Die Frage
  "Ich versichere, den Rechtehinweis gelesen zu haben und bin damit
  einverstanden" steht auf **Nein** vorbelegt. Wer sie überspringt, bekommt
  HTTP 200 und wieder das Formular, diesmal mit "Bitte akzeptieren Sie den
  Rechtehinweis" — der Schritt scheitert also lautlos, ohne Fehlerseite. Auf
  **Ja** stellen, dann absenden. Real gemessen, siehe
  `evals/free-archive-fetchers/live-verification.json`, Lauf `fa-03`
  (`rights_gate`).
- MDZ stellt das PDF danach serverseitig zusammen; erst dann erscheint der Link
  "PDF-Datei öffnen oder herunterladen (\<Größe\>)". Auf ihn warten — bei
  großen Werken dauert die Zusammenstellung spürbar.
- Bei mehrbändigen Werken: sicherstellen, dass der passende Band ausgewählt
  ist, bevor der PDF-Download gestartet wird (MDZ listet Bände oft als
  separate Digitalisate mit eigener Werk-ID).
- PDF-Link klicken, Download nach `<output_path>` (Rezept in `_cli.md`).

## Access-Level-Matrix

| Signal auf Werkseite | Bedeutung | Aktion |
|---|---|---|
| Viewer mit Download-Icon und Eintrag "PDF/DaFo" | Digitalisat vollständig verfügbar | Formular ausfüllen, Rechtehinweis auf "Ja" stellen, PDF-Download → `success` |
| Katalogeintrag ohne Viewer-Link ("kein Digitalisat") | nur bibliografischer Nachweis, (noch) nicht digitalisiert | `metadata_only` mit `reason: "Zugriffsstufe: nur Metadaten — kein Digitalisat"` |
| Viewer vorhanden, aber PDF-Option fehlt (reiner Bildbetrachter) | Digitalisat nur seitenweise einsehbar, kein Gesamt-PDF-Export vorgesehen | `metadata_only` mit `reason: "Zugriffsstufe: nur Seitenansicht, kein PDF-Export"` |

## Ausgabe-/Jahresangabe

Jahr, Ausgabe und Verlag stammen aus den **bibliografischen Metadaten der
konkret gewählten Werkseite** (Block "Bibliografische Angaben" / bib.
Metadaten neben dem Viewer), nicht aus der Eingabe-ISBN oder dem
Eingabe-Titel. MDZ-Digitalisate sind i. d. R. historische Erstausgaben oder
spezifische Exemplare einer Bibliothek — das dort angegebene Erscheinungsjahr
des Digitalisats übernehmen, nicht das einer moderneren Neuauflage.

## Pickup-Triggers

- `status: metadata_only` wenn:
  - Katalogeintrag ohne Viewer-Link (kein Digitalisat vorhanden).
  - Viewer vorhanden, aber keine PDF-Download-Option (reiner Seitenbetrachter).
- `status: captcha` wenn ein CAPTCHA in `page_info()` sichtbar ist
  (selten bei MDZ).
- `status: no_match` wenn Suche 0 Treffer liefert.
- **HTTP 429 / Rate-Limit:** korrekt diagnostizieren (Statuscode +
  Retry-Hinweis im `reason`-Feld), NICHT als `no_match` fehldeuten — siehe
  Issue #450 AC1.

## Bekannte Fallstricke

- Mehrbändige Werke sind auf MDZ oft als eigenständige Digitalisate pro Band
  katalogisiert — nicht automatisch den ersten Treffer nehmen, sondern den
  Band prüfen, der zur Anfrage passt.
- Manche Werke sind mehrfach digitalisiert (verschiedene Exemplare/Auflagen
  derselben Bibliothek) — Erscheinungsjahr des tatsächlich gewählten
  Digitalisats übernehmen.
- Alte Frakturschrift-Digitalisate können OCR-Fehltreffer in der internen
  Volltextsuche erzeugen — das betrifft nur die MDZ-eigene Suche, nicht den
  PDF-Download selbst.
- Der Viewer läuft in einigen Fällen über `mdz-nbn-resolving.de`-Weiterleitung
  — Zielseite nach Redirect erneut mit `page_info()` prüfen.
- Der Rechtehinweis ist keine Formalie: MDZ stellt seine Digitalisate unter
  wechselnde Rights Statements (das geprüfte Beispiel unter NoC-NC, also ohne
  kommerzielle Nutzung). Das Statement der konkreten Werkseite gehört zur
  Zugriffsstufe und wird nicht pauschal als "gemeinfrei" gemeldet.
- Ein abgesendetes Formular ohne bestätigten Rechtehinweis sieht wie ein
  normal geladenes Formular aus — kein Fehlerstatus, kein sichtbarer Hinweis
  außer der Zeile "Bitte akzeptieren Sie den Rechtehinweis". Nicht als
  "PDF-Option fehlt" fehldeuten.
