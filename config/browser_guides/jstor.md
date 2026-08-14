# JSTOR — Browser-Guide (Buch-Download)

> **Aufrufform der CLI:** `config/browser_guides/_cli.md` — Heredoc-Aufruf,
> Helfer, Element-Adressierung, Download. Dieser Guide enthält nur Site-Wissen.

**URL:** https://www.jstor.org
**Auth:** Shibboleth/OpenAthens (Institutionszugang) ODER kein Login für
OA-Titel
**Anti-Scraping:** HOCH — JSTORs Nutzungsbedingungen (`about.jstor.org/terms`)
untersagen ausdrücklich automatisiertes/systematisches Herunterladen,
Web-Scraping und Bulk-Extraktion. Nur menschliches Tempo über die CLI,
niemals Skript-Schleifen über mehrere Titel.

## Login-Flow

**Für OA-Titel:** kein Login erforderlich — direkt zu Discovery-Pfad. JSTOR
führt eine große Open-Access-Ebook-Sammlung (u. a. UC Press, University of
Michigan Press, RAND Corporation — 13.000+ Titel) ohne Registrierung und ohne
DRM.

**Für lizenzierte Titel (Institutionszugang):**

1. `new_tab("https://www.jstor.org")`
2. "Log In"-Button oben rechts klicken.
3. "Access through your institution" über den AX-Baum finden und klicken
   (führt zu `jstor.org/institutionSearch`).
4. Institution im Suchfeld eingeben und auswählen.
5. Hochschul-Login-Formular ausfüllen (Credentials aus Uni-Profil,
   Shibboleth/OpenAthens-Redirect).
6. Auf Weiterleitung zurück zu JSTOR warten — angemeldeten Status prüfen.

**Achtung:** Persönliche JSTOR-Accounts (E-Mail/Passwort, Google/Microsoft-SSO)
sind KEIN institutioneller Zugang und schalten keine lizenzierten Volltexte
frei — nur der Institution-Pfad tut das.

## Discovery-Pfad

1. Suchfeld im Header: Titel, ISBN oder DOI eingeben.
2. Filter "Item Type: Book" setzen.
3. "Open Access"-Badge in Ergebniszeile prüfen.
4. Auf Treffer klicken → Buchdetailseite öffnet (`/stable/<id>` oder
   `/book/<id>`).
5. Alternativ per DOI-Direktlink: `https://doi.org/10.2307/...` →
   JSTOR-Detailseite.

## Volltext-Lokation

- Auf der Buchdetailseite bzw. im Inhaltsverzeichnis: "Download PDF" pro
  Kapitel suchen.
- **JSTOR liefert Bücher überwiegend kapitelweise** — ein einzelner
  "Gesamtbuch-Download"-Button ist der Ausnahmefall, nicht die Regel. Jedes
  heruntergeladene Kapitel zählt als Erfolg mit `chapter_only: true`.
- Button über den AX-Baum finden.

## Tempo und Anti-Scraping

- Mindestens 3–5 Sekunden Pause zwischen Klicks/Downloads einhalten.
- Bei wiederholtem CAPTCHA nicht erneut versuchen oder Tempo erhöhen —
  ehrlich `status: captcha` melden.
- Keine Batch-/Bulk-Downloads mehrerer Titel in einem Aufruf.

## Pickup-Triggers

- `status: pickup_required` wenn:
  - Auth-Wall / "Access options" statt Download-Button sichtbar.
  - Institutionszugang nicht konfiguriert oder Shibboleth fehlgeschlagen.
  - Nur Online-Lese-Option vorhanden (kein PDF-Download).
- `status: captcha` wenn CAPTCHA in `page_info()` erkennbar →
  Screenshot sichern, User informieren.
- `status: no_match` wenn Suche 0 Treffer liefert.

## Bekannte Fallstricke

- Kein einzelner Gesamtbuch-Download-Button auf den meisten Buchseiten —
  Kapitel-für-Kapitel ist der Normalfall.
- "Open Access"-Badge auf der Trefferliste kann sich auf einzelne Kapitel statt
  das gesamte Buch beziehen — Buchseite vor jedem Download prüfen.
- Persönlicher Account-Login ersetzt NICHT den institutionellen Zugang.
- Historisch aggressives Anti-Scraping (Rate-Limiting, CAPTCHA, IP-Sperren) —
  konservatives Tempo ist Pflicht, nicht Kür.
