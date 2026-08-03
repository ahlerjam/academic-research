# Active Learning im Titel-/Abstract-Screening (#602)

Vollständiges Vorgehen für die lernende Umsortierung der Restliste. Ergänzt
`SKILL.md`, das nur den Einstieg trägt.

## Wozu

Bei 800 Abstracts sind typischerweise 30 relevant. Wer die Liste in
Datenbankreihenfolge durchgeht, liest 770 Absagen — und weiß bis zum letzten
Abstract nicht, ob noch etwas kommt.

Ein Klassifikator, der laufend aus den bereits gefällten Urteilen nachtrainiert,
dreht das um: die wahrscheinlich relevanten Arbeiten wandern nach vorn. Das
Verfahren stammt aus ASReview. Übernommen ist die Idee, nicht das Paket — die
Lizenz- und Installationsfrage lohnt den Aufwand hier nicht.

## Was Active Learning **nicht** tut

Diese drei Grenzen sind der eigentliche Inhalt des Features:

1. **Es entscheidet nichts.** Kein Ein- oder Ausschluss geht auf den
   Klassifikator zurück. Er ordnet nur, wer wann drankommt.
2. **Es kürzt nichts.** Jede Rückgabe ist eine Permutation der Eingabe: gleiche
   Menge, gleiche Länge, keine Duplikate. Umsortiert, nicht gefiltert.
3. **Kein automatischer Abbruch.** Das Modul hat keine Funktion, die ein Stop-Signal
   gibt. Wann genug gescreent ist, entscheidet ein Mensch am
   Fortschrittsbericht. Eine Arbeit, die ausgeschlossen wurde, weil ein Modell
   sie für unwichtig hielt und niemand hinsah, ist ein methodischer Schaden, den
   keine Zeitersparnis aufwiegt.

## Blindheit bleibt gewahrt (#598)

Die Sortierung verändert **nur die Reihenfolge der Task-Aufrufe, nie deren
Inhalt**. In den `screening-judge`-Aufruf gehört kein Relevanzwert, kein Rang
und kein Runde-1-Urteil — sonst wäre das blinde Doppel-Screening aufgehoben und
das Modell würde seine eigene Vorhersage bestätigt bekommen. Diese Regel ist
eine Ausführungsvorschrift; das Modul kann sie nicht erzwingen, weil es die
Prompts nicht sieht.

## Schalter

| Schalter | Vorrang | Default |
|----------|---------|---------|
| `resolve_active_learning()` | Argument > `ACADEMIC_RESEARCH_ACTIVE_LEARNING` > `config/parallel_agents.json` → `active_learning` > Default | `False` |
| `resolve_retrain_interval()` | Argument > `ACADEMIC_RESEARCH_ACTIVE_LEARNING_INTERVAL` > `active_learning_retrain_interval` > Default | `10` |
| `resolve_block_size()` | Argument > `ACADEMIC_RESEARCH_ACTIVE_LEARNING_BLOCK` > `active_learning_block_size` > Default | `25` |

**Opt-in, anders als das Doppel-Screening.** Doppel-Screening folgt einer
methodischen Pflicht und ist darum Default. Active Learning hilft erst ab einer
gewissen Listenlänge; ein Default-on würde jeden bestehenden Screening-Lauf
still umsortieren. Bei `False` schreibt das Modul nichts, sortiert nichts und
ist von einem Lauf ohne dieses Feature nicht unterscheidbar.

## Funktionen

Alle in `scripts/active_learning.py`, Import wie im Haupt-`SKILL.md`.

| Funktion | Aufgabe |
|----------|---------|
| `reorder_pending(ids, papers, session_dir, …)` | Der Weg im Ablauf: Schalter prüfen, umsortieren, protokollieren |
| `rank_pending(ids, papers, session_dir, …)` | Nur die Reihenfolge, ohne Protokoll und ohne Schalterprüfung |
| `training_labels(session_dir, …)` | Die bisherigen Urteile als `{paper_id: include\|exclude}` |
| `progress(ids, session_dir, …)` | Bearbeiteter Anteil + Trefferausbeute je Abschnitt |
| `progress_report(…)` | Derselbe Stand als Markdown |
| `validate_ranking(records, …)` | Recall-Kurve gegen eine Liste mit bekanntem Ergebnis |
| `read_log(session_dir)` | Das Umsortierungs-Protokoll |
| `NaiveBayesRanker` | Der Klassifikator selbst |

CLI-Unterbefehle: `rank`, `progress`, `validate`.

## Der Klassifikator

Multinomiale Naive Bayes mit Laplace-Glättung über Titel + Abstract, reine
Standardbibliothek. Bewertet wird das Log-Wahrscheinlichkeitsverhältnis
`include` gegen `exclude`; höher heißt „wahrscheinlicher relevant".

- **Lokal.** Kein Netzzugriff, kein Schlüssel, kein zusätzliches Paket. Das
  Screening von 800 Abstracts darf keine Cloud-Abhängigkeit einführen.
- **Bewusst einfach.** Keine Embeddings, kein neuronales Modell in dieser
  Fassung. Erst belegen, dass das einfache Verfahren nicht reicht — der
  Validierungslauf unten ist das Instrument dafür.
- **Deterministisch.** Sortierschlüssel ist `(-Bewertung, Ursprungsindex)`,
  keine Zufallsquelle. Gleiche Eingabe, gleiche Reihenfolge.

### Wann *nicht* umsortiert wird

| Lage | Verhalten |
|------|-----------|
| Weniger Urteile als `interval` (Kaltstart) | Ursprungsreihenfolge, keine Protokollzeile |
| Nur eine Klasse geurteilt (0 `include` **oder** 0 `exclude`) | Ursprungsreihenfolge, keine Protokollzeile |
| Zu keinem offenen Fall liegt Text vor | Ursprungsreihenfolge, keine Protokollzeile |
| Einzelne Fälle ohne Titel/Abstract | Diese behalten ihre **Ursprungsposition**; fehlender Text ist kein Argument gegen eine Quelle |

### Trainingsgrundlage

`unclear` und `dissent` sind keine Trainingsbeispiele — sie sind offene Fragen,
keine Entscheidungen. Läuft Doppel-Screening (#598), trainiert das Modell auf
den **konsolidierten** Urteilen aus `merge_double()` (inklusive der
menschlichen Auflösungen), sonst auf `merge()`.

## Protokoll

`$SESSION_DIR/active_learning_log.jsonl`, append-only, eine Zeile je
tatsächlicher Umsortierung:

```json
{"n_labels": 30, "n_include": 4, "n_exclude": 26, "n_pending": 770,
 "n_scored": 768, "vocabulary_size": 4211, "model": "multinomial-nb/laplace/1",
 "stage": "screening", "ts": 1750000000, "order": ["…", "…"]}
```

Damit ist beantwortbar: welche Reihenfolge galt ab wann, auf welcher
Trainingsgrundlage. Ohne dieses Protokoll wäre die Reihenfolge eines
abgeschlossenen Screenings nicht mehr rekonstruierbar.

## Ablauf

### Schritt 1 — Restliste vor jeder Welle umsortieren

```python
todo = pending(paper_ids, session_dir)
todo = reorder_pending(todo, papers, session_dir)  # papers: {id: {"title":…, "abstract":…}}
waves = plan_waves(todo, max_parallel)
```

`plan_waves` ist reihenfolgetreu — die Umsortierung wird also allein durch die
neue Liste wirksam, ohne Eingriff in die Wellenlogik. `papers` kommt aus
`$SESSION_DIR/ranked.json` bzw. `papers.json`; beide führen Titel und Abstract
bereits.

### Schritt 2 — Urteilen wie bisher

Unverändert: ein `Task`-Aufruf je Fall, `record_decision` je Urteil. Weder
`screening-judge` noch die Ledger-Buchführung wissen von diesem Modul.

### Schritt 3 — Fortschritt vorlegen

```python
print(progress_report(paper_ids, session_dir))
```

Die Abschnitte folgen der **Urteilsreihenfolge** aus dem Ledger, nicht der
Listenreihenfolge. Genau darum ist an den letzten Abschnitten ablesbar, ob die
Ausbeute versiegt — die Datengrundlage der Abbruchentscheidung, und nur die
Grundlage.

## Validierungslauf

`validate_ranking(records)` spielt ein vollständiges Screening gegen eine Liste
mit **bekanntem** Ergebnis durch (`records` mit `paper_id`, `title`,
`abstract`, `relevant`) und weist aus, nach welchem Anteil der Liste welcher
Anteil der relevanten Arbeiten gefunden war. Zufallsbaseline ist die Diagonale:
ohne Umsortierung wären nach x % der Liste im Mittel x % der Treffer gefunden.

```bash
~/.academic-research/venv/bin/python \
  ${CLAUDE_PLUGIN_ROOT}/skills/parallel-screening/scripts/active_learning.py \
  validate --gold gold_screening.jsonl
```

Die im Repository mitgelieferte Liste
(`tests/fixtures/active_learning/gold_screening.jsonl`, erzeugt von
`scripts/dev/generate_active_learning_fixture.py`) ist **synthetisch**. Sie
belegt, dass das Verfahren greift und die Umsortierung nichts verliert — sie
ist keine Aussage über die Ausbeute an einem echten Korpus. Wer eine Zahl für
die eigene Arbeit braucht, lässt den Befehl gegen ein abgeschlossenes eigenes
Screening laufen.
