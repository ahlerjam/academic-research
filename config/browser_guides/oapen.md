# OAPEN — Browser-Guide (Buch-Download)

**URL:** https://www.oapen.org
**Auth:** keine (Open-Access-Repositorium)
**Anti-Scraping:** niedrig — OAPEN ist öffentlich zugänglich.

## Login-Flow

Kein Login erforderlich. Alle Inhalte sind Open Access.

1. `browser-use open https://www.oapen.org`
2. Direkt zur Discovery fortfahren.

## Discovery-Pfad

1. Suchfeld im Header: Titel, Autor oder ISBN eingeben.
2. `browser-use state` → Suchergebnisse prüfen.
3. Alternativ per DOI-Direktlink: `https://doi.org/10.xxxx/...` → OAPEN-Detailseite.
4. Alternativ per Handle: `https://library.oapen.org/handle/<handle>`.
5. Auf Treffer klicken → Detailseite mit Metadaten und Download-Button.

## Volltext-Lokation

- Auf der Detailseite: Button "Download PDF" suchen.
- `browser-use state` → Button-Index identifizieren, klicken.
- PDF liegt direkt auf OAPEN-Servern — keine Weiterleitung zu externen Seiten.
- Dateiname: meist `<handle>.pdf` oder titelbasiert.

## OA-Invariante

oapen.org hostet ausschließlich Open-Access-Bücher. Jeder gefundene Treffer ist
per Definition OA — kein separater OA-Filter nötig, kein Login (OAPEN kennt für
den Volltextzugriff kein Auth-Konzept).

## Status-Vokabular

| Beobachtung | Status | Feld |
|---|---|---|
| "Download PDF" vorhanden, Download geglückt und verifiziert | `success` | `file_path` |
| Detailseite ohne Download-Button (seltener Fehlerfall) | `metadata_only` | `url` = Detailseite |
| Server-Fehler 5xx oder leere Download-Antwort | `metadata_only` | `url` = Detailseite |
| Handle-URL gibt 404 (Buch entfernt/umgezogen), auch nach DOI-Zweitversuch | `no_match` | `reason` |
| Suche liefert 0 Treffer | `no_match` | `reason: "0 Treffer auf oapen.org"` |

## Verbote (site-spezifisch)

- Keine OAPEN-API-Endpunkte direkt aufrufen — nur der Browser-Weg.
- Kein Login-Versuch: OAPEN benötigt keine Authentifizierung.

## Bekannte Fallstricke

- Handle-URLs und DOI-URLs können auf unterschiedliche Seiten zeigen — beide
  versuchen falls eine 404 liefert.
- Verwaiste Handles (Buch nachträglich entfernt) geben 404 ohne Redirect.
- OAPEN enthält nur OA-Bücher — wenn Titel nicht gefunden, ist er vermutlich nicht OA.
- Große PDFs (>50 MB) können Timeout auslösen — Download-Fortschritt überwachen.
