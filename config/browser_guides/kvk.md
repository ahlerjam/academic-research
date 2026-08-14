# KVK — Karlsruher Virtueller Katalog — Browser-Guide

> **Aufrufform der CLI:** `config/browser_guides/_cli.md` — Heredoc-Aufruf,
> Helfer, Element-Adressierung, Download. Dieser Guide enthält nur Site-Wissen.

**URL:** https://kvk.bibliothek.kit.edu
**Auth:** keine für Metadaten-Abfrage; Fernleihe/Bestellung verlangen Bibliothekskonto
**Anti-Scraping:** niedrig — KVK ist öffentlicher Dienst.

## Login-Flow

Für reine Standort-/Verfügbarkeitsabfragen kein Login erforderlich.

Für Fernleihe / Direktbestellung (nicht automatisiert):
1. Bibliotheks-OPAC der gewählten Bibliothek aufrufen.
2. Dort mit Bibliothekskonto anmelden.
3. Fernleihe-Formular ausfüllen — **nicht automatisch auslösen**,
   nur Standort-Info für Pickup-Liste zurückgeben.

## Discovery-Pfad

1. `new_tab("https://kvk.bibliothek.kit.edu")`
2. Suchformular ausfüllen: ISBN (bevorzugt), Titel oder Autor.
3. Datenbanken auswählen (Standard: HEIDI, BVB, GBV, SWB — alle aktivieren).
4. "Suchen"-Button klicken.
5. Ergebnisliste mit Bibliotheksbeständen per `js(...)` prüfen.
6. Für jeden Treffer: Bibliotheks-Name, Standort, Signatur notieren.

## Volltext-Lokation

KVK ist ein **Meta-Katalog über 80+ Bibliotheken und kein Volltext-Host**: er
weist Bestände nach, hostet aber selbst nichts. Ein `success` ist hier die
Ausnahme und entsteht nur über einen externen Volltext-Link aus der Trefferliste.

### OA-/Volltext-Filter

KVK zeigt physische UND digitale Bestände gemischt. Priorisierung:

1. "Volltext"-Links oder "Online-Zugriff"-Buttons zuerst suchen.
2. Explizit als "Open Access" markierte Treffer bevorzugen.
3. "Online-Ressource" ohne Preisangabe = OA-Kandidat.
4. Nur Print-Nachweis → Standort-Info sammeln.

Bei gefundenem Volltext-Link: Link öffnen, auf der Zielseite herunterladen,
Download nach `<output_path>` (Rezept in `_cli.md`), Datei verifizieren.

### Standort-Info

Ohne Volltext-Link werden die Standorte gesammelt (Bibliotheksname, Ort,
Signatur, Ausleihtyp) und als kompakter String im `reason`-Feld zurückgegeben.
Der Master entscheidet, ob und wie sie in die Pickup-Liste wandern.

```
"Standorte: BSB München (4 Ph.pr. 123, Lesesaal), UB Berlin (Ausleihe), HU Berlin (Fernleihe)"
```

## Status-Vokabular

| Beobachtung | Status | Feld |
|---|---|---|
| Externer Volltext-Link gefunden, Download geglückt und verifiziert | `success` | `file_path` |
| Nur Bibliotheks-/Print-Nachweis (Regelfall) | `metadata_only` | `url` = KVK-Ergebnisseite, `reason: "Standorte: ..."` |
| 0 Treffer in allen Datenbanken | `no_match` | `reason: "0 Treffer in KVK für <query>"` |

Der Regelfall ist `metadata_only`, **nicht** `pickup_required`: KVK ist
Standort-Finder, und der Master braucht den Unterschied für seine Verlags-Stufe.

## Verbote (site-spezifisch)

- **Kein automatisches Auslösen von Fernleihe oder Bestellformularen.** Das
  Fernleihe-Formular wird nie abgeschickt — nur die Standort-Info wird gemeldet.
- Kein Login in Bibliotheks-Portale (nur Metadaten, kein Bestellen).
- Keine erfundenen Standorte oder Signaturen.

## Bekannte Fallstricke

- KVK zeigt physische UND digitale Bestände gemischt — "Online-Ressource"-Treffer
  verweisen auf Volltext-URLs (können als sekundäre Discovery genutzt werden).
- Nicht jede Bibliothek hat Online-Bestellung aktiviert — Fernleihe manuell.
- Signatur-Format variiert stark je Bibliothek — nur als Referenz zurückgeben,
  nicht parsen.
- Einige Datenbanken haben Ladezeiten >5 Sekunden — KVK wartet auf alle
  Teilbibliotheken, bevor Ergebnisse angezeigt werden.
- Timeout bei sehr breiten Suchen (viele Datenbanken aktiv) — ggf. Suche
  auf GBV + BVB einschränken.
