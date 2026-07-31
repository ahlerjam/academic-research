# Lückenerkennung — Zitat-Extraktion

Vom Skill `citation-extraction` bei Bedarf geladen (Progressive Disclosure).

Während der Extraktion auf diese Muster achten:

- **Kapitel ohne Zitate** — Als literaturbedürftig flaggen
- **Kapitel mit nur einer Quelle** — Als potenziell unzureichend flaggen
- **Fehlende Gegenargumente** — Wenn alle Zitate dieselbe Position stützen, nach Gegenpositionen suchen
- **Veraltete Quellen** — Zitate aus Quellen älter als 10 Jahre flaggen, außer es sind Standardwerke

Bei erkannten Lücken `/search` mit gezielten Queries anbieten oder den Skill `literature-gap-analysis` für ein umfassendes Review triggern.
