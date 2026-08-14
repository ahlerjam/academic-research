# Cambridge Core — Browser-Guide (Buch-Download)

> **Aufrufform der CLI:** `config/browser_guides/_cli.md` — Heredoc-Aufruf,
> Helfer, Element-Adressierung, Download. Dieser Guide enthält nur Site-Wissen.

**URL:** https://www.cambridge.org/core
**Auth:** Shibboleth/OpenAthens (Institutionszugang) ODER kein Login für OA-Titel
**Anti-Scraping:** mittel — CAPTCHA bei schnellen Requests möglich.

## Login-Flow

**Für OA-Titel:** kein Login erforderlich — direkt zu Discovery-Pfad.

**Für lizenzierte Titel (Institutionszugang):**

1. `new_tab("https://www.cambridge.org/core")`
2. "Log In"-Button oben rechts klicken.
3. "Access through your institution" über den AX-Baum finden und klicken.
4. Seamless Access / Shibboleth: Hochschule im Dropdown/Suchfeld wählen.
5. Hochschul-Login-Formular ausfüllen (Credentials aus Uni-Profil).
6. Auf Weiterleitung zurück zu Cambridge Core warten — angemeldeten Status
   prüfen (Institutionsname erscheint im Header).

## Discovery-Pfad

1. Suchfeld im Header: Titel, ISBN oder DOI eingeben.
2. Filter "Book" (Content Type) im linken Panel setzen.
3. OA-Badge ("Open Access") in Ergebniszeile prüfen.
4. Auf Treffer klicken → Buchdetailseite öffnet (`/core/books/<slug>`).
5. Alternativ per DOI-Direktlink: `https://doi.org/10.1017/...` →
   Cambridge-Core-Detailseite.

## Volltext-Lokation

- Auf der Buchdetailseite: Button "Download book PDF" suchen.
  - OA-Titel: Button direkt verfügbar ohne Login.
  - Lizenzierte Titel: Button nur nach erfolgreichem Institutionszugang.
- Button über den AX-Baum finden.
- Achtung: Buchseite (`/core/books/<slug>`) vs. Kapitelseite
  (`/core/books/<slug>/<chapter-slug>`):
  - Buchseite → Gesamtbuch-Download, falls verfügbar.
  - Kapitelseite → "Download PDF" für einzelnes Kapitel (linkes
    Inhaltsverzeichnis, jedes Kapitel hat eigenen Download-Link).
- Vollbuch-Download bevorzugen wenn vorhanden.

## Pickup-Triggers

- `status: pickup_required` wenn:
  - Auth-Wall / "Access options" statt Download-Button sichtbar.
  - Institutionszugang nicht konfiguriert oder Shibboleth fehlgeschlagen.
  - Nur Online-Lese-Option vorhanden (kein PDF-Download).
- `status: captcha` wenn CAPTCHA in `page_info()` erkennbar →
  Screenshot sichern, User informieren.
- `status: no_match` wenn Suche 0 Treffer liefert.

## Bekannte Fallstricke

- Buch-DOI und Kapitel-DOI sind verschieden — Buchseite ist der
  Buchkanon-Einstiegspunkt, Kapitelseiten für einzelne Kapitel.
- Einzelne Kapitel können lizenziert sein, obwohl das Buch selbst OA ist —
  immer Buchseite prüfen, nicht nur Kapitelseite.
- Seamless Access erkennt oft eine bestehende Institution-Session automatisch —
  vor manuellem Login-Formular prüfen, ob bereits angemeldet.
- CAPTCHA erscheint bei schnellen Request-Folgen — mind. 3 Sekunden Pause.
- Nicht jedes Buch bietet einen Gesamtbuch-Download; einige nur kapitelweise.
