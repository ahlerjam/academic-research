# EBSCOhost — Navigation Guide

> **Aufrufform der CLI:** `config/browser_guides/_cli.md` — Heredoc-Aufruf,
> Helfer, Element-Adressierung, Download. Dieser Guide enthält nur Site-Wissen.

**URL (über HAN):** https://han.leibniz-fh.de → EBSCOhost
**Auth:** HAN-Login (siehe `han_login.md`)
**Max. Ergebnisse:** 30
**Anti-Scraping:** niedrig (lizenzierter Zugriff), aber Timeout nach ~20 min Inaktivität.

## Hinweise

- Nach HAN-Login auf der Portal-Seite den Link "EBSCOhost" klicken.
- Suchoberfläche bietet "Advanced Search" im Hauptmenü — für strukturierte Suche meist besser als die Basissuche.
- Jede Ergebnisseite zeigt Badges: "Peer Reviewed", "Full Text", "Scholarly (Peer Reviewed) Journal". Per `js(...)` als Text auslesbar.
- Volltext-PDF via Button "PDF Full Text" (wenn verfügbar) oder "HTML Full Text".
- Filter im linken Panel: "Source Types", "Publication Date", "Subject: Thesaurus Term".

## Datenbanken innerhalb EBSCOhost

- Business Source Premier (Wirtschaft)
- Academic Search Complete (interdisziplinär)
- ERIC (Pädagogik)
- APA PsycInfo (Psychologie)

Auswahl im Dropdown "Choose Databases" oben rechts vor der Suche.

## Fehlerbehandlung

- "Service unavailable"-Meldung → später retry, einzelne Datenbanken manchmal offline.
- Session-Timeout → HAN-Login erneut durchführen, Command fortsetzen.
