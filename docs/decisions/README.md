# Entscheidungsvermerke

[← Doku-Übersicht](../README.md)

Hier liegen Entwürfe, die eine projektweite Architekturfrage beantworten, bevor sie
als Umsetzungs-Issue spec-scharf geschrieben werden kann — nicht einzelne
Recherche-Entscheidungen innerhalb einer Sitzung (dafür ist `vault.add_decision`
zuständig, siehe [Vault-MCP-Server](../reference/vault.md)). Jeder Vermerk bewertet
mehrere Wege gegeneinander, spricht eine begründete Empfehlung aus und benennt, was
ein daraus folgendes Umsetzungs-Issue leisten müsste.

Nummerierung fortlaufend, ein Vermerk pro Datei, Dateiname `NNNN-kurzer-slug.md`.

## Bestand

- [0001 — Modellzugang beim Ingest ohne eigenen Schlüssel](0001-modellzugang-ingest.md)
  — welcher Weg dem Vault-Ingest ein Modell für inhaltliche Kontextsätze verschafft,
  ohne die No-Key-Randbedingung aus #632 zu verletzen.
- [0002 — OpenAlex: Filter-Syntax, Semantic Search, Usage-based Pricing](0002-openalex-search-syntax-semantic-pricing.md)
  — Filter-Syntax-Umstellung ist bereits erledigt, Semantic Search (Beta) und
  Usage-based Pricing werden abgewartet, keylose Nutzung bleibt Default.
