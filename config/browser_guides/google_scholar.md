# Google Scholar — Navigation Guide

> **Aufrufform der CLI:** `config/browser_guides/_cli.md` — Heredoc-Aufruf,
> Helfer, Element-Adressierung, Download. Dieser Guide enthält nur Site-Wissen.

**URL:** https://scholar.google.com
**Auth:** keine
**Max. Ergebnisse:** 20 (2 Seiten à 10)
**Anti-Scraping:** **hoch** — Google blockiert Bots aggressiv. 2-3 Sekunden Pause zwischen Aktionen. Bei CAPTCHA: `capture_screenshot(path=…)`, User informieren, Partial Results zurückgeben. Max. ~100 Requests/Tag pro IP.

## Hinweise

- Direkt-URL statt Suchfeld: `https://scholar.google.com/scholar?q=<QUERY>` für
  die Erstsuche, `&start=10` für Seite 2. Das spart einen Klick und damit ein
  Bot-Signal.
- Trefferliste direkt per `js(...)` auslesen — jede Ergebniszeile ist ein
  `.gs_ri`-Block mit `.gs_rt` (Titel + Titel-Link), `.gs_a` (Autorenzeile),
  `.gs_fl` (Fußzeile mit „Cited by"/„Zitiert von"), und der PDF-Link liegt
  daneben in `.gs_or_ggsm`:

  ```
  [...document.querySelectorAll('.gs_ri')].map(r => ({
    title: r.querySelector('.gs_rt')?.innerText,
    link:  r.querySelector('.gs_rt a')?.href,
    meta:  r.querySelector('.gs_a')?.innerText,
    cited: [...r.querySelectorAll('.gs_fl a')]
             .map(a => a.innerText)
             .find(t => /Cited by|Zitiert von/.test(t)),
  }))
  ```

- **Nicht den ersten Link einer Ergebniszeile blind nehmen** — jede Zeile
  enthält Titel-, PDF-, Zitations-, „Speichern"- und „Zitieren"-Links. Immer
  über den Link-Text auswählen (die Zitationszahl steht im „Cited by"-Text).
- Autoren-Zeile folgt dem Format `AUTOR1, AUTOR2 - VENUE, JAHR - PUBLISHER`.
  Das Parsing macht der LLM aus dem `js(...)`-Ergebnis.
- Kein API-Key, keine offizielle API. Scholar sperrt IPs nach Erkennung
  dauerhaft — vorsichtig einsetzen.
