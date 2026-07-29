# Oxford Academic — Browser-Guide (Buch-Download)

**URL:** https://academic.oup.com
**Auth:** Shibboleth/OpenAthens (SeamlessAccess) ODER EZproxy/WAM ODER kein
Login für OA-Titel
**Anti-Scraping:** mittel — CAPTCHA bei schnellen Requests möglich.

## Login-Flow

**Für OA-Titel:** kein Login erforderlich — direkt zu Discovery-Pfad.

**Für lizenzierte Titel (Institutionszugang):**

1. `browser-use open https://academic.oup.com`
2. "Sign In"-Button oben rechts klicken.
3. `browser-use state` → "Sign in via your institution" suchen, klicken.
4. SeamlessAccess/Institution-Finder: Hochschule wählen.
5. Hochschul-Login-Formular ausfüllen (Credentials aus Uni-Profil).
6. Auf Weiterleitung zurück zu Oxford Academic warten — angemeldeten Status
   prüfen.
7. Alternative: Falls `proxy_pattern` im Uni-Profil gesetzt ist (EZproxy/WAM),
   URL über den Proxy-Präfix öffnen statt Shibboleth-Flow.

## Discovery-Pfad

1. Suchfeld im Header: Titel, ISBN oder DOI eingeben.
2. `browser-use state` → Filter "Books" (Content Type) im linken Panel setzen.
3. Badge in Ergebniszeile prüfen: "Open Access", "Free" oder "Unlocked".
4. Auf Treffer klicken → Buchdetailseite öffnet (Oxford Scholarship Online,
   `/oso/...`).
5. Alternativ per DOI-Direktlink: `https://doi.org/10.1093/oso/...` →
   Oxford-Academic-Detailseite.

## Volltext-Lokation

- Auf der Buchdetailseite: Button "PDF" unterhalb des Buchtitels suchen.
  - OA-Titel: Button direkt verfügbar ohne Login, meist DRM-frei.
  - Lizenzierte Titel: Button nur nach erfolgreichem Institutionszugang.
- `browser-use state` → Button-Index identifizieren.
- Manche Titel bieten nur "Download Chapter" statt Gesamtbuch — kapitelweiser
  Fallback über die Inhaltsverzeichnis-Navigation.
- Vollbuch-Download bevorzugen wenn vorhanden.

## Pickup-Triggers

- `status: pickup_required` wenn:
  - Auth-Wall / "Get access" oder "Buy This Book" statt Download-Button sichtbar.
  - Institutionszugang nicht konfiguriert oder Shibboleth/EZproxy fehlgeschlagen.
  - Nur Online-Lese-Option vorhanden (kein PDF-Button).
- `status: captcha` wenn CAPTCHA in `browser-use state` erkennbar →
  Screenshot sichern, User informieren.
- `status: no_match` wenn Suche 0 Treffer liefert.

## Bekannte Fallstricke

- Oxford Scholarship Online (`/oso/...`) ist der Buch-Namensraum; nicht mit
  Journal-Artikel-Pfaden auf derselben Domain verwechseln.
- "Free"/"Unlocked" auf der Trefferliste ist kein Lizenzbeleg — nur ein
  Download-Signal.
- SeamlessAccess erkennt oft eine bestehende Institution-Session automatisch —
  vor manuellem Login-Formular prüfen.
- CAPTCHA erscheint bei schnellen Request-Folgen — mind. 3 Sekunden Pause.
- Nicht jedes Buch bietet einen Gesamtbuch-Download; einige nur kapitelweise.
