# 0002 — OpenAlex: Filter-Syntax, Semantic Search, Usage-based Pricing

[← Doku-Übersicht](../README.md) · [Entscheidungsvermerke](README.md)

Entwurf zu Issue #850. Quelle:
[OpenAlex-Blogpost „OpenAlex API: New Features and Usage-based Pricing"](https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/).
Bewertet drei Fragen, die der Blogpost aufwirft: die deprecated Filter-Suchsyntax, die
neuen Semantic-/Advanced-Search-Features, und die Auswirkung des angekündigten
Usage-based Pricing auf den keylosen Betrieb des Plugins.

## 1. Deprecated Filter-Suchsyntax — bereits erledigt

Audit über `scripts/`, `skills/`, `academic_vault/`, `tests/` (Grep nach `filter=` in
Verbindung mit `openalex`): kein Code-Pfad ruft OpenAlex über
`filter=default.search:` oder `filter=title.search:` auf.
`scripts/search.py::search_openalex` (Zeile 223–229) übergibt bereits
`params={"search": query, "per-page": limit}` an `GET /works` — den vom Blogpost als
zukunftsfest bezeichneten Top-Level-Parameter `search`, seit dem v4-Rewrite
(985263a). `scoring.py` und `dedup.py` rufen die OpenAlex-API nicht selbst auf, sie
verarbeiten nur bereits normalisierte Felder. `skills/anchor-paper-survey/scripts/anchor_paper.py`
ruft `search_openalex` über die gemeinsame Modul-Fassade auf, ohne eigene Parameter.

Live-Gegenprobe (2026-08-13, `curl "https://api.openalex.org/works?search=climate%20change&per-page=1"`):
`search=` liefert eine Antwort mit `meta.x_query.url` `/works?filter=fulltext.search:climate change&per_page=1`
— OpenAlex übersetzt den `search`-Parameter intern selbst auf die (weiterhin
funktionierende, aber laut Blogpost deprecated) Filter-Repräsentation und meldet das
zu Diagnosezwecken zurück; das ist keine Rückkehr des Codes zur alten Syntax, sondern
OpenAlex' eigene interne Query-Übersetzung. Der alte `filter=default.search:`-Weg
funktioniert derzeit noch parallel (Redirect/Kompatibilitätsmodus), ist aber laut
Blogpost der abzulösende Pfad.

**Einstufung: erledigt, kein Umsetzungsbedarf.** Ein Guard-Test
(`test_openalex_uses_search_param_not_deprecated_filter`,
`tests/test_search_parsers.py`) verhindert eine künftige stille Rückkehr zu
`filter=`.

## 2. Semantic Search (Beta)

Der Blogpost kündigt experimentelle Semantic-/Advanced-Search-Endpunkte an
(Embedding-basierte Ähnlichkeitssuche zusätzlich zur klassischen Volltext-/
Feldsuche).

- **Nutzen für systematische Reviews:** potenziell hoch — Ähnlichkeitssuche über
  Anker-Papiere passt zum bestehenden Anchor-Paper-Survey-Skill
  (`skills/anchor-paper-survey/`) und zur 8-Quellen-Parallelsuche.
- **Reifegrad:** Beta/experimentell zum Zeitpunkt dieses Vermerks — kein SLA, keine
  Versionsgarantie, laut OpenAlex-Doku Verhalten und Antwortschema noch in Bewegung.
- **Risiko einer Vorab-Integration:** ein Beta-Endpunkt, der sich ändert, bricht
  denselben Parser-Pfad, den AC2 dieses Issues gerade gegen Strukturbrüche absichert
  — Integration jetzt würde eine ungetestete Abhängigkeit auf einen instabilen
  Vertrag schaffen.

**Einstufung: abwarten.** Kein Einbau jetzt (ohnehin Out-of-Scope für #850). Sobald
OpenAlex Semantic Search als stabil markiert (nicht mehr Beta) oder ein
Versionsvertrag dokumentiert ist, eigenes Folge-Issue zur Bewertung als
9. Suchmodul bzw. Ergänzung zu `search_openalex` — siehe Ausgangs-Issue-Body,
„Out"-Abschnitt.

## 3. Usage-based Pricing — Auswirkung auf keylosen Betrieb

Live-Gegenprobe (2026-08-13, derselbe `curl`-Aufruf wie oben) bestätigt: Usage-based
Pricing ist bereits scharf, nicht nur angekündigt.

Response-Header:

```
x-ratelimit-cost-usd: 0.001
x-ratelimit-limit-usd: 0.1
x-ratelimit-remaining-usd: 0.096
x-ratelimit-limit: 1000
x-ratelimit-remaining: 960
```

- **Kosten pro Aufruf:** 0,001 USD je `works`-Suche (der von `search_openalex`
  genutzte Endpunkt).
- **Tagesbudget ohne Schlüssel:** 0,10 USD/Tag — rechnerisch rund 100
  `works`-Aufrufe/Tag über alle Nutzungen des Plugins auf derselben IP hinweg (ein
  Aufruf pro `search_openalex`-Invocation innerhalb der 8-Quellen-Parallelsuche
  entspricht einer Recherche-Anfrage im Plugin, nicht einer Ergebniszeile).
- **Aktuelle Reserve:** für den typischen Anwendungsfall — punktuelle
  Recherchesitzungen eines einzelnen Nutzers, nicht Dauerbetrieb mit hoher Frequenz —
  ausreichend; ein Recherchelauf verbraucht einen kleinen Bruchteil des
  Tagesbudgets.
- **Risiko:** Das Tagesbudget ist IP- oder Fingerprint-gebunden (Details nicht
  öffentlich dokumentiert) und kann sich mit wachsender OpenAlex-Nutzerbasis
  verschärfen, ohne dass das Plugin davon vorab erfährt — ein `429`/Budget-Fehler
  von OpenAlex würde dann `search_openalex` scheitern lassen, während die übrigen
  Module der Parallelsuche unberührt blieben (bestehendes
  Fehlerisolationsverhalten der Parallelsuche, kein neuer Code nötig).

**Einstufung: abwarten, kein Key-Zwang.** Ein eigener API-Schlüssel würde die
No-API-Key-Linie des Plugins verletzen (#632) und ist damit keine zulässige
Option, selbst bei einer künftigen Budgetverschärfung — „abwarten" bzw.
„degradiert weiterlaufen lassen" (OpenAlex fällt in der Fehlerisolation der
Parallelsuche einfach als eines von mehreren Modulen aus) sind die einzig
zulässigen Reaktionen. Keine Code-Änderung jetzt nötig; Monitoring-Hinweis: sollte
`x-ratelimit-remaining-usd` in der Praxis wiederholt bei 0 beobachtet werden
(z. B. über Bug-Reports oder Live-Fetch-Weekly-Läufe), ist eine erneute Bewertung
angezeigt — dann ggf. mit reduzierter `per-page`/Ergebnisanzahl als
kostenneutraler Abmilderung, nicht mit einem Schlüssel.

## Zusammenfassung

| Thema | Einstufung | Begründung |
|---|---|---|
| Deprecated Filter-Syntax | Erledigt | Code nutzt bereits `search=`; Guard-Test ergänzt |
| Semantic Search (Beta) | Abwarten | Instabiler Beta-Vertrag, Out-of-Scope für #850 |
| Usage-based Pricing | Abwarten, kein Key-Zwang | Aktuelles Tagesbudget ausreichend für typische Nutzung; #632 schließt Schlüssel-Einführung aus |
