# Gold-Trefferliste für den Active-Learning-Validierungslauf (#602)

`gold_screening.jsonl` ist eine **synthetische** Trefferliste mit bekanntem
Ergebnis: 150 Datensätze, davon 15 relevant. Sie belegt, dass die Umsortierung
greift und nichts verliert — sie ist keine Aussage über die Ausbeute an einem
echten Korpus.

Erzeugt von `scripts/dev/generate_active_learning_fixture.py` (fester Seed
`602`). Das Skript ist die Herkunftsdokumentation; es läuft nicht als Teil der
Tests. Neu erzeugen:

```bash
uv run python scripts/dev/generate_active_learning_fixture.py
```

## Konstruktionsregel (gegen Test-Gaming)

Die Liste darf nicht auf den Klassifikator hin gebaut sein, sonst misst der
Validierungslauf sich selbst. Darum:

1. **Das Thema trägt kein Signal.** Relevante und irrelevante Datensätze ziehen
   ihren Gegenstand aus demselben Pool (Lernvideos, Online-Kurse,
   Lernplattformen …). Wer nur Themenwörter lernt, trennt die Klassen nicht.
2. **Das Signal liegt im Studiendesign.** Relevant sind Wirksamkeitsstudien
   (Kontrollgruppe, Prä-/Posttest); irrelevant sind Essays,
   Erfahrungsberichte aus der Schule, Überblicksartikel und
   Werkzeugbeschreibungen.
3. **Harte Negative** — irrelevante Datensätze, die die Methodenwörter der
   relevanten Klasse ausdrücklich verwenden (ein Aufsatz *über* randomisierte
   Zuweisung). Ohne sie wäre die Aufgabe trivial.
4. **Harte Positive** — relevante Datensätze mit auffällig wenigen
   Methodenwörtern (quasi-experimenteller Kohortenvergleich).
5. **Die Ausgangsreihenfolge ist gemischt** (fester Seed), also weder nach
   Relevanz sortiert noch von Hand gelegt.

`tests/test_issue_602_active_learning.py::test_gold_fixture_is_not_built_around_the_classifier`
prüft die Punkte 1, 3 und 4 am Dateiinhalt nach.

## Format

Eine JSON-Zeile je Datensatz:

```json
{"abstract": "…", "paper_id": "gold042", "relevant": true, "title": "…"}
```
