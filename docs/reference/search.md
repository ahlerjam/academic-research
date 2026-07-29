# Suchquellen, Scoring und Cluster

[← zurück zur README](../../README.md)

## Suchquellen (14)

Das Plugin sucht in 14 Quellen: **7 API-Quellen** laufen immer und parallel, 7 weitere
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

Woher die Auth-Module (`ebscohost`, `proquest`, `opac`) ihre HAN-Zugangsdaten nehmen und
wie sich das vom Per-Uni-Profil unterscheidet, steht gesammelt unter
[Zugangsdaten](../guide/installation.md#zugangsdaten).

### Zustimmung für Hochschul-Zugangsdaten (Auth-Module)

`ebscohost`, `proquest` und `opac` verwenden per HAN-Login
(`config/browser_guides/han_login.md`) Hochschul-Zugangsdaten in
Browser-Sessions. Dabei gelten unverändert die Nutzungsbedingungen der
jeweiligen Plattform — **EBSCOhost**, **ProQuest** und der **HAN**-Proxy der
Hochschule.

Vor dem allerersten Zugriff auf eines dieser drei Module im `--mode deep`
holt `commands/search.md` eine einmalige, erklärte Zustimmung ein
(`scripts/deep_search_consent.py`, `AskUserQuestion`-Gate). Die Zustimmung
wird in `~/.academic-research/consent.json` gespeichert und danach **nicht
erneut abgefragt**. Bei Ablehnung werden nur die drei Auth-Module für den
aktuellen Lauf übersprungen — No-Auth-Module und alle 7 API-Module laufen
unverändert weiter.

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
