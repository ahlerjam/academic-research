# DOAB — Directory of Open Access Books — Browser-Guide

**URL:** https://www.doabooks.org
**Auth:** keine (Verzeichnis-Service, kein eigener Volltext)
**Anti-Scraping:** niedrig — DOAB ist öffentlich.

## Login-Flow

Kein Login erforderlich. DOAB ist ein Metadaten-Aggregator ohne eigenen Volltext.

1. `browser-use open https://www.doabooks.org`
2. Direkt zur Discovery fortfahren.

## Discovery-Pfad

1. Suchfeld auf der Startseite: Titel, Autor, ISBN oder DOI eingeben.
2. `browser-use state` → Suchergebnisse prüfen.
3. Filter "Publisher", "Language", "Subject" im linken Panel optional setzen.
4. Auf Treffer klicken → Metadaten-Detailseite öffnet.
5. Volltext-Link auf Detailseite suchen (Feld "PDF" oder "Download" oder
   "Publisher URL").

## Volltext-Lokation

- DOAB hostet **keinen** Volltext direkt — alle Download-Links zeigen auf externe
  Repositorien (OAPEN, Verlagsseite, Zenodo, etc.).
- `browser-use state` → "Download"-Link-Index identifizieren, klicken.
- Weiterleitung zu externem Provider → dortigen Browser-Guide verwenden:
  - OAPEN-Link → `oapen.md`
  - Springer-Link → `springer.md` (Buch-Download-Abschnitt)
  - De Gruyter-Link → `degruyter.md`
  - Unbekannter Provider → `generic-fetcher`-Subagent

## OA-Invariante

DOAB listet ausschließlich OA-Bücher — jeder Treffer ist per Definition Open
Access. Das heißt aber **nicht**, dass jeder Eintrag einen Volltext-Link hat:
manche Einträge tragen nur Metadaten, weil der Verlag noch nicht geliefert hat.
Volltext-Verfügbarkeit deshalb pro Treffer prüfen, nicht aus der OA-Invariante
folgern.

## Status-Vokabular

| Beobachtung | Status | Feld |
|---|---|---|
| Volltext-Link vorhanden, Download geglückt und verifiziert | `success` | `file_path` |
| Volltext-Link zeigt auf eine Paywall oder eine lizenzierte Seite | `metadata_only` | `url` = DOAB-Detailseite |
| Kein Volltext-Link auf der Detailseite (nur Metadaten) | `metadata_only` | `reason: "Zugriffsstufe: nur Metadaten — kein Volltext-Link"` |
| Externer Provider gibt 404 / Access-Denied (Link-Rot) | `metadata_only` | `url` = DOAB-Detailseite |
| Suche liefert 0 Treffer | `no_match` | `reason: "0 Treffer auf DOAB"` |

Ein Paywall-Treffer über DOAB ist **`metadata_only`, nicht `pickup_required`**:
der Master braucht die Unterscheidung, um seine Verlags-Stufe zu aktivieren.

## Verbote (site-spezifisch)

- **Kein direkter DOAB-REST-API-Aufruf.** `directory.doabooks.org/rest/search`
  existiert, wird aber nicht verwendet — die Site wird wie von einem Menschen
  über browser-use bedient.
- Keine automatische Fernleihe, keine Bestellformulare ausfüllen.

## Bekannte Fallstricke

- DOAB ist Aggregator, nicht Repositorium — immer Weiterleitung zum Volltext.
- Manche Einträge haben nur Metadaten ohne Volltext-Link (Verlag hat noch nicht
  geliefert).
- Link-Rot: Einige ältere Einträge verweisen auf inzwischen umgezogene oder
  gelöschte URLs.
- DOAB-Suche ist weniger präzise als direktes ISBN-/DOI-Lookup — DOI-Direktsuche
  bevorzugen wenn möglich.
