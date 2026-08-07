---
description: Score and rank literature with 5D scoring system (Relevance, Recency, Quality, Authority, Accessibility)
disable-model-invocation: true
allowed-tools: Read, Agent(relevance-scorer), Bash(~/.academic-research/venv/bin/python *)
argument-hint: [papers.json] [--query "..."] [--mode standard]
---

# Literatur-Scoring

Papers mithilfe des `relevance-scorer`-Agents neu scoren und ranken. Der Agent bewertet Titel + Abstract gegen die Query auf einer 0.0–1.0-Skala und liefert Reasoning und Confidence je Paper.

## Verwendung

- `/academic-research:score` — Papers aus der letzten Session scoren
- `/academic-research:score papers.json --query "DevOps"` — Bestimmte Datei scoren
- `/academic-research:score --mode deep` — Scoring mit zusätzlichem Confidence-Durchlauf

## 5D-Dimensionen (Referenz, Agent übernimmt 1D-Relevanz)

| Dimension | Gewicht (Default) | Quelle |
|-----------|---------|--------|
| Relevanz | 0.35 | `relevance-scorer`-Agent (Titel + Abstract-Match) |
| Aktualität | 0.20 | Exponentieller Decay, Halbwertszeit profilabhängig (Default 5 Jahre), berechnet aus `year`-Feld |
| Qualität | 0.15 | OpenAlex `fwci` (feldnormalisierter Zitationsimpact, Weltdurchschnitt = 1.0), sonst Rückfall auf Zitationen pro Jahr mit Log-Skalierung aus `citations` |
| Autorität | 0.15 | Venue-Heuristik aus `venue`/`source`-Feld |
| Zugang | 0.15 | Open Access > Institutional > DOI > URL > Nichts |

Die vier Nicht-Relevanz-Dimensionen werden von `scripts/scoring.py` berechnet (reproduzierbar, mit Tests in `tests/test_scoring.py`), nicht vom Modell im Kopf ausgerechnet.

Halbwertszeit und alle fünf Gewichte kommen seit #705 aus dem aktiven
Bibliotheksprofil (`~/.academic-research/library-profiles/active.yaml`,
Abschnitt `scoring:`); fehlt der Abschnitt oder einzelne Felder darin, gelten
die Default-Werte aus der Tabelle oben. Presets: `library-profiles/profiles/systematic-review.yaml`
(lange Halbwertszeit, favorisiert Grundlagenliteratur) und
`library-profiles/profiles/fachhausarbeit.yaml` (kurze Halbwertszeit, favorisiert
aktuelle Literatur) — Details und ein Vorher/Nachher-Beispiel in
`docs/reference/scoring.md`.

## Cluster

- **Kernliteratur** (grün): Total ≥ 0.75, Relevanz ≥ 0.80
- **Ergänzungsliteratur** (blau): Total ≥ 0.50, Relevanz ≥ 0.50
- **Hintergrundliteratur** (grau): Total ≥ 0.30
- **Methodenliteratur** (gelb): Methodologie-Schlüsselwörter in Titel/Abstract

## Umsetzung

### Schritt 1: Paper-Quelle finden

```bash
LATEST=$(ls -t ~/.academic-research/sessions/ | head -1)
PAPERS=~/.academic-research/sessions/$LATEST/deduped.json
```

Bei explizitem Argument: diesen Pfad verwenden.

### Schritt 2: Relevanz-Scoring via Agent

Papers in Batches à 10 an den `relevance-scorer`-Agent schicken. Input pro Batch:

```json
{
  "user_query": "<QUERY>",
  "papers": [
    {"doi": "...", "title": "...", "abstract": "...", "year": 2023}
  ]
}
```

Output-Feld `relevance_score` je Paper als 0.0–1.0-Float einsammeln.

### Schritt 3+4: 4 weitere Dimensionen berechnen und Gesamtscore bilden

Je Paper `scripts/scoring.py` aufrufen — das Skript berechnet Aktualität,
Qualität, Autorität und Zugang (siehe Tabelle oben für die Formeln) und
summiert sie gewichtet mit der vom Agenten gelieferten Relevanz zum
Gesamtscore. Optionales 4. Argument: Pfad zu einem Profil-YAML (Default:
`~/.academic-research/library-profiles/active.yaml`, falls vorhanden, sonst
die Default-Werte):

```bash
~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/scoring.py \
  '{"year": 2023, "citations": 50, "citations_normalized": 1.4, "venue": "IEEE Transactions on Software Engineering", "oa_url": "https://arxiv.org/..."}' \
  0.9
```

Ausgabe (stdout): ein JSON-Objekt, z. B.

```json
{"total": 0.8404873871933739, "quality_source": "fwci", "recency_half_life_years": 5.0}
```

`total` ist der Gesamtscore für die Cluster-Zuordnung; `quality_source` zeigt,
ob der feldnormalisierte OpenAlex-Wert (`"fwci"`) oder der rohe Zitationswert
(`"raw"`) verwendet wurde; `recency_half_life_years` die tatsächlich
angewandte Halbwertszeit.

Cluster gemäß Threshold-Tabelle oben anhand von `total` zuordnen.

### Schritt 5: Ausgabe

Papers nach Cluster sortiert als formatierte Markdown-Tabelle ausgeben. Als JSON in `ranked.json` im Session-Verzeichnis speichern.
