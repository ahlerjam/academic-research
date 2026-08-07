# Suchquellen, Scoring und Cluster

[← Doku-Übersicht](../README.md)

Woher die Literatur kommt, wie Treffer bewertet werden und wie daraus Themencluster
entstehen. Maßgeblich für die Modulliste ist immer der `MODULES`-Dispatch in
`scripts/search.py` — diese Seite gibt ihn wieder.

## Suchquellen (15)

Das Plugin sucht in bis zu 15 Quellen: **8 API-Quellen** sind registriert, davon laufen
7 in jedem Modus immer automatisch und parallel; das achte Modul (`dblp`) ist optional
per `--modules dblp` wählbar (kein automatisches Umschalten je nach Themengebiet). 7
weitere Module steuert die `browser-use`-CLI an (nur im `--mode deep`).

### API-Module

Registriert im `MODULES`-Dispatch von `scripts/search.py` — das ist die maßgebliche
Liste. `dblp` läuft nur, wenn es explizit per `--modules dblp` ausgewählt wird (siehe
`commands/search.md`); die übrigen sieben laufen automatisch in jedem Modus.

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

| Dimension | Gewicht (Default) | Berechnung |
|-----------|---------|------------|
| **Relevanz** | 35 % | Keyword-Match Titel (70 %) + Abstract (30 %) + Phrasen-Bonus |
| **Aktualität** | 20 % | Exponentieller Verfall, Halbwertszeit profilabhängig (Default 5 Jahre) |
| **Qualität** | 15 % | OpenAlex `fwci` (feldnormalisierter Zitationsimpact, Weltdurchschnitt = 1.0), sonst Rückfall auf Zitationen/Jahr mit Log-Skalierung |
| **Autorität** | 15 % | Venue-Reputation (IEEE = 1.0, Mid = 0.7, Other = 0.4) |
| **Zugang** | 15 % | Open Access = 1.0, Institutional = 0.8, DOI = 0.5, URL = 0.2 |

Nur die Relevanz-Dimension nutzt einen LLM-Agent (`relevance-scorer`); die übrigen vier
berechnet `scripts/scoring.py` deterministisch (`tests/test_scoring.py`).

### Feldnormalisierte Qualität (fwci)

Rohe Zitationszahlen vergleichen Felder mit sehr unterschiedlichen
Zitiergewohnheiten (Medizin vs. Germanistik) auf einer Skala. OpenAlex liefert
dafür `fwci` (Field-Weighted Citation Impact) bereits im Work-Objekt — ein
Wert von 1.0 entspricht dem Weltdurchschnitt für Feld/Jahr/Typ. `scripts/scoring.py`
verwendet `fwci`, wenn die Suche es geliefert hat (`min(fwci / 2, 1.0)`,
nach oben geklemmt, da `fwci` unbeschränkt ist), sonst den bisherigen
Rohwert. Die Herkunft steht im Ergebnis (`quality_source: "fwci"|"raw"`).

### Profilabhängige Halbwertszeit und Gewichte (#705)

Der pauschale 5-Jahre-Verfall bestraft Grundlagenliteratur systematisch — bei
einer Literaturarbeit ist das rückwärts. Halbwertszeit und alle fünf Gewichte
lassen sich daher pro Bibliotheksprofil überschreiben
(`~/.academic-research/library-profiles/active.yaml`, Abschnitt `scoring:`);
fehlt der Abschnitt oder ein einzelnes Feld darin, gelten die Default-Werte
aus der Tabelle oben (`scripts/scoring.py`, `load_profile()`).

Zwei Presets liegen unter `library-profiles/profiles/` bereit und lassen sich
in die eigene `active.yaml` übernehmen:

| Preset | Halbwertszeit | Schwerpunkt |
|--------|---------------|-------------|
| `systematic-review.yaml` | 15 Jahre | Grundlagenliteratur bleibt sichtbar (mehr Gewicht auf Qualität/Autorität, weniger auf Aktualität) |
| `fachhausarbeit.yaml` | 3 Jahre | Aktueller Forschungsstand (mehr Gewicht auf Aktualität) |

**Beispiel** — ein hoch zitiertes 1998er-Grundlagenwerk
(`fwci: 3.0`, Journal-Venue, Open Access, Relevanz 0.8, aktuelles Jahr 2026):

| Profil | Halbwertszeit | Gesamtscore | Cluster |
|--------|---------------|-------------|---------|
| Default (5 Jahre) | 5 Jahre | ≈ 0.69 | Ergänzungsliteratur (< 0.75) |
| `systematic-review` | 15 Jahre | ≈ 0.81 | **Kernliteratur** (≥ 0.75) |

Unter dem heutigen Default fällt das Paper allein durch sein Alter aus der
Kernliteratur; unter dem Review-Profil bleibt es dank geringerem
Aktualitätsgewicht und längerer Halbwertszeit oben (siehe
`tests/test_scoring.py::test_review_profile_keeps_landmark_1998_paper_in_top_cluster`
für die exakte Rechnung).

## Cluster

| Cluster | Kriterien | Rolle |
|---------|-----------|-------|
| **Kernliteratur** | Score ≥ 0.75, Relevanz ≥ 0.80 | Muss zitiert werden |
| **Ergänzungsliteratur** | Score ≥ 0.50, Relevanz ≥ 0.50 | Vertiefung |
| **Hintergrundliteratur** | Score ≥ 0.30 | Grundlagen, Standards |
| **Methodenliteratur** | Methodik-Keywords erkannt | Methodik-Begründung |

Der `cluster-visualizer`-Skill rendert die Zuordnung als Mermaid-Diagramm.
