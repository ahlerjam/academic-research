# 0002 — OpenAlex: Filter-Syntax, Semantic Search, Usage-based Pricing

[← Doku-Übersicht](../README.md) · [Entscheidungsvermerke](README.md)

Entwurf zu Issue #850. Beantwortet drei Fragen aus der [OpenAlex-API-Ankündigung](
https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/)
(24.02.2026): Ist die Filter-Suchsyntax im Plugin noch im Einsatz? Lohnt sich
Semantic Search für systematische Reviews? Was bedeutet das Usage-based Pricing
für den keylosen Betrieb (#632)?

## 1. Filter-Suchsyntax — Audit, kein Umbau nötig

`scripts/search.py::search_openalex` (Zeile 223–261) ruft die Works-API bereits
seit dem v4-Rewrite (985263a) über `params={"search": query, "per-page": limit}`
auf — den heute empfohlenen Weg. Ein Repo-weiter Grep über `scripts/`, `skills/`,
`academic_vault/`, `tests/` nach `filter=` in Verbindung mit einer OpenAlex-URL
findet **keinen** Treffer, der die zur Suche gehörende, jetzt deprecated
`filter=default.search:`/`filter=title.search:`-Syntax verwendet.

Ein zweiter OpenAlex-Aufruf existiert in `scripts/known_item_search.py:127-129`
(`fetch_reference_tally_candidates`): `params={"filter": f"openalex_id:{ids}"}`.
Das ist eine **ID-Exact-Match-Filterung**, kein Volltext-/Titelsuchfilter — dieser
Filtertyp ist von der Deprecation nicht betroffen (Beleg unten) und bleibt
unverändert.

**Beleg (live gegengeprüft am 2026-08-13/14 gegen zwei unabhängige aktuelle
Quellen):**

- [OpenAlex-Blog, „New Features and Usage-Based Pricing"](https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/):
  „the old filter syntax for search is now deprecated; the `?search=` parameter
  approach remains […] Filter searches will redirect to the `?search` param."
- [OpenAlex-Hilfe, „Searching"](https://help.openalex.org/guides/searching):
  „Deprecated. The `filter=field.search:` syntax still works but is no longer
  recommended. Use the `search` query parameter instead." — Ausnahme:
  `raw_author_name.search` bleibt der einzige Weg für Autorennamen-Suche in der
  Rohform, weil `search=` dafür kein Pendant hat (im Plugin nicht genutzt).

**Ergebnis:** AC1 ist erfüllt, ohne Code zu ändern — die Umstellung war bereits
vor der Ankündigung erfolgt. Ergänzt wurde ein Regressions-Guard-Test
(`test_openalex_uses_search_query_param_not_deprecated_filter_syntax`,
`tests/test_search_parsers.py`), der die tatsächlich an `httpx` übergebenen
Query-Parameter prüft, damit eine künftige stille Rückkehr zu `filter=` auffällt.

## 2. Semantic Search — abwarten

Laut Hilfe-Doku ist Semantic Search **Beta**: „we don't recommend using it for
sensitive production workflows yet." Für systematische Reviews ist Präzision und
Nachvollziehbarkeit der Trefferauswahl zentral (Vault-Provenienz, Snowballing,
Duplikatabgleich über DOI/OpenAlex-ID) — ein Beta-Feature ohne dokumentierte
Stabilitätsgarantie ist dafür ungeeignet.

**Einstufung: abwarten.** Kein Einbau jetzt. Re-Evaluierung, sobald OpenAlex
Semantic Search als produktionsreif einstuft (Beobachtungspunkt: Statuswechsel
im Blog/Hilfe-Doku, kein fester Termin).

## 3. Usage-based Pricing — abwarten, mit Monitoring-Hinweis

Die Ankündigung führt kostenpflichtige Nutzung ein: API-Keys sind laut Blog jetzt
**Pflicht für Produktionsbetrieb** („You can still make a few calls without an
API key for demo purposes, but it's not suitable for any kind of production
use."). Mit Key gibt es ein kostenloses Tageskontingent von 1 USD, darin u. a.
bis zu 1.000 Such-Calls/Tag. Live-Gegenprobe am 2026-08-13
(`curl api.openalex.org/works?search=...` ohne Key) zeigt: Der keylose Zugriff
funktioniert **aktuell noch** und liefert denselben `x_query.oql` wie zuvor;
die Antwort trägt bereits `cost_usd: 0.001` pro Aufruf im Meta-Block, auch ohne
Key.

Das Plugin darf laut #632 keinen Anthropic- oder Fremd-API-Schlüssel voraussetzen
— diese Linie gilt unverändert für OpenAlex. Ein erzwungener Key-Einbau ist damit
**keine zulässige Option**, unabhängig davon, wie sich der keylose Zugang künftig
entwickelt (siehe Scope „Out" in Issue #850).

**Einstufung: abwarten, mit Monitoring-Hinweis.** Keylose Nutzung bleibt der
Default. Konkretes Risiko: Der Blog-Wortlaut „nicht für Produktionsbetrieb
geeignet" ist eine Empfehlung, keine technische Sperre — sollte OpenAlex den
keylosen Pfad in Zukunft hart abschalten oder auf ein Limit drosseln, das unter
dem Bedarf einer typischen 8-Quellen-Parallelsuche liegt, degradiert das Modul
still (leere Trefferlisten oder HTTP 429/403) statt laut zu scheitern —
`search_openalex()` propagiert `resp.raise_for_status()` bereits als Exception,
die vom Aufrufer als „Modul fehlgeschlagen" behandelt wird (kein stiller
Datenverlust, aber ohne gezielte Fehlermeldung „Key jetzt Pflicht"). Empfehlung
für ein Folge-Issue, sobald das eintritt: eine klare Fehlermeldung im Log statt
der generischen HTTP-Ausnahme, keine Änderung an der No-Key-Linie selbst.

## Zusammenfassung

| Thema | Einstufung | Begründung |
|---|---|---|
| Filter-Suchsyntax | Bereits erledigt | `search=` seit v4-Rewrite im Einsatz, Audit ohne Treffer, Guard-Test ergänzt |
| Semantic Search | Abwarten | Beta, vom Betreiber selbst nicht für produktive Workflows empfohlen |
| Usage-based Pricing | Abwarten, mit Monitoring-Hinweis | Keylos aktuell noch funktionsfähig; #632 verbietet Key-Zwang; Risiko ist ein stiller Verlust der Quelle, nicht ein Compliance-Bruch |
