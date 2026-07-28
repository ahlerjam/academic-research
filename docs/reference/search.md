# Suchquellen, Scoring und Cluster

[← zurück zur README](../../README.md)

## Suchquellen (15)

Das Plugin sucht in 15 Quellen: **8 API-Quellen** laufen immer und parallel, 7 weitere
Module steuert die `browser-use`-CLI an (nur im `--mode deep`).

### API-Module (automatisch, parallel)

Registriert im `MODULES`-Dispatch von `scripts/search.py` — das ist die maßgebliche Liste.

| Modul | Quelle | Disziplin |
|-------|--------|-----------|
| `crossref` | DOI-Registry | Alle |
| `openalex` | OpenAlex-Katalog | Alle |
| `semantic_scholar` | Semantic Scholar | Alle |
| `base` | Bielefeld Academic Search Engine | Alle |
| `econbiz` | ZBW Suchportal | Wirtschaft |
| `econstor` | OA-Wirtschafts-Repository | Wirtschaft |
| `arxiv` | arXiv Preprints | CS, ML, Physik, Mathe |
| `dblp` | DBLP Computer Science Bibliography | Informatik |

### Browser-Module (`browser-use`-CLI)

Reihenfolge und Auth-Anforderungen stehen in `commands/search.md`. No-Auth-Module zuerst,
Auth-Module danach.

| Modul | Quelle | Auth |
|-------|--------|------|
| `google_scholar` | Google Scholar | keine |
| `springer` | Springer Nature | HAN optional |
| `oecd` | OECD.org | keine |
| `repec` | IDEAS/RePEc | keine |
| `ebscohost` | EBSCO Publication Finder | HAN |
| `proquest` | ProQuest Dissertationen | HAN |
| `opac` | Hochschul-OPAC | Login |

> Ohne installierte `browser-use`-CLI werden die Browser-Module übersprungen; die
> API-Suche funktioniert unverändert weiter. Das Setup meldet das explizit.

## 5D-Scoring

Jedes Paper wird nach 5 Dimensionen bewertet (0–1):

| Dimension | Gewicht | Berechnung |
|-----------|---------|------------|
| **Relevanz** | 35 % | Keyword-Match Titel (70 %) + Abstract (30 %) + Phrasen-Bonus |
| **Aktualität** | 20 % | Exponentieller Verfall, 5-Jahre-Halbwertzeit |
| **Qualität** | 15 % | Zitationen/Jahr, Log-Skalierung |
| **Autorität** | 15 % | Venue-Reputation (IEEE = 1.0, Mid = 0.7, Other = 0.4) |
| **Zugang** | 15 % | Open Access = 1.0, Institutional = 0.8, DOI = 0.5, URL = 0.2 |

Nur die Relevanz-Dimension nutzt einen LLM-Agent (`relevance-scorer`); die übrigen vier
berechnet die Command-Logik deterministisch.

## Cluster

| Cluster | Kriterien | Rolle |
|---------|-----------|-------|
| **Kernliteratur** | Score ≥ 0.75, Relevanz ≥ 0.80 | Muss zitiert werden |
| **Ergänzungsliteratur** | Score ≥ 0.50, Relevanz ≥ 0.50 | Vertiefung |
| **Hintergrundliteratur** | Score ≥ 0.30 | Grundlagen, Standards |
| **Methodenliteratur** | Methodik-Keywords erkannt | Methodik-Begründung |

Der `cluster-visualizer`-Skill rendert die Zuordnung als Mermaid-Diagramm.
