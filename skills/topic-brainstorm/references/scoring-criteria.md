# Scoring-Kriterien — Topic-Brainstorm

## Übersicht

Der Scorer (`scripts/scorer.py`) normalisiert für jeden vom Modell entworfenen
Topic-Kandidaten drei Scores im Bereich 0-10. Die Summe aller drei Scores
ergibt den Gesamtscore (0-30), nach dem das Top-Topic bestimmt wird.

**Wer berechnet was:** Feasibility und Novelty sind Scorer-Arithmetik
(Basiswert des Kandidaten + Modifikator aus Budget/Datenzugang bzw.
Interessens-Overlap). Career-Fit ist reine Modell-Einschätzung (`base_career_fit`
im Topic-Kandidaten) — der Scorer reicht ihn unverändert durch. Die Tabellen
in diesem Dokument sind für Career-Fit deshalb **Orientierungshilfe fürs
Modell**, kein interner Scorer-Lookup.

---

## Feasibility-Score (0-10)

**Fragestellung:** Ist das Thema im gegebenen Zeitrahmen mit dem verfügbaren
Datenzugang bearbeitbar?

**Zusammensetzung:**
- Datenverfügbarkeit (3 Punkte max)
- Zeitaufwand (3 Punkte max)
- Methoden-Match (4 Punkte max)

### Datenverfügbarkeit-Modifikatoren

| Datenzugang | Modifikator | Begründung |
|-------------|-------------|------------|
| Public Datasets | +1.0 | Kaggle, Eurostat, Statista, GitHub — sofort verfügbar |
| Literatur-Only | +0.5 | Kein eigener Datensatz nötig — Fokus auf Analyse |
| Interview-fähig | 0.0 | Aufwand für Rekrutierung und Durchführung realistisch |
| Unternehmensdaten | -1.0 | NDA, Verfügbarkeit, Freigabe unsicher |

### Zeitbudget-Modifikatoren

| Zeitbudget | Modifikator | Begründung |
|------------|-------------|------------|
| 3 Monate | -1.0 | Wenig Puffer für Datenbeschaffung und Analyse |
| 6 Monate | 0.0 | Standard Bachelor-/Masterarbeitszeit |
| 12 Monate | +1.0 | Genug Zeit für komplexe Methoden und Iterationen |

### Methoden-Match

Fließt in den `base_feasibility`-Wert ein, den das Modell pro Kandidat
schätzt (Schritt 2 in `SKILL.md`). Typische Orientierungswerte:

| Methodik | Basiswert |
|----------|-----------|
| Literaturreview + Inhaltsanalyse | 8-9 |
| Fragebogen / Online-Survey | 7-8 |
| Semi-strukturierte Interviews | 6-7 |
| Datenbankanalyse / Data Mining | 7-8 |
| Experiment / Labor | 5-6 |

---

## Novelty-Score (0-10)

**Fragestellung:** Wie groß ist die Forschungslücke — gibt es noch offene Fragen?

**Berechnung:**
- Basiswert pro Topic (heuristisch)
- +0.5 pro Stichwort-Überschneidung zwischen Interessensgebieten und Topic-Keywords
- Maximum: +2.0 Bonus durch Interessens-Overlap

### Interpretation

| Score | Bedeutung |
|-------|-----------|
| 8-10 | Wenig Forschung, viel Lücke — hohes Neuheitspotenzial |
| 5-7 | Moderater Forschungsstand — Differenzierung nötig |
| 0-4 | Gut erforscht — klare Differenzierung zwingend |

**Hinweis:** Der Novelty-Score ist ein Heuristik-Indikator. Für eine präzise
Lückenanalyse bitte den `literature-gap-analysis`-Skill nach der Themenauswahl
verwenden.

---

## Career-Fit-Score (0-10)

**Fragestellung:** Passt das Thema zur Studienrichtung und zum Berufsbild?

**Berechnung:** Wird vom Modell als `base_career_fit` pro Kandidat geschätzt
(Schlagwort-/Themen-Passung zwischen Studienrichtung und Topic) und vom
Scorer unverändert übernommen — kein interner Scorer-Lookup.

### Referenzwerte nach Studienrichtung (Orientierung fürs Modell)

Kein interner Scorer-Lookup — dient dem Modell in Schritt 2 von `SKILL.md`
als Anhaltspunkt beim Schätzen von `base_career_fit`. Andere Studienrichtungen
(z. B. Maschinenbau) sind ausdrücklich zulässig; das Modell schätzt dafür
einen plausiblen Wert nach demselben Muster, statt auf eine der drei Zeilen
zurückzufallen.

| Studienrichtung | Wirtschafts-IT-Themen | Reine IT-Themen | BWL-Themen |
|-----------------|----------------------|-----------------|------------|
| Wirtschaftsinformatik | 8.5-9.5 | 7.0-8.0 | 6.0-7.0 |
| BWL | 6.0-7.5 | 3.5-5.0 | 7.5-9.0 |
| Informatik | 7.0-8.5 | 8.5-9.5 | 3.0-4.5 |

---

## Top-Topic-Ermittlung

```
Top-Topic = argmax( feasibility + novelty + career_fit )
```

Bei Gleichstand wird der erste Kandidat in der Liste gewählt.

---

## Weiterentwicklung

Dieser Scorer ist bewusst deterministisch und heuristisch gehalten.
Für eine datengetriebene Novelty-Berechnung kann die `vault.search()`-API
genutzt werden, um die Anzahl verfügbarer Papers pro Topic-Bereich zu zählen
und den Novelty-Score entsprechend anzupassen.

Beispiel (optional, für zukünftige Erweiterung):
```python
recent = vault.search(topic_keywords, date_filter="2020-2024")
older = vault.search(topic_keywords, date_filter="2000-2019")
gap_ratio = max(0, 1 - len(recent) / max(1, len(older)))
novelty = base_novelty + gap_ratio * 2.0
```
