# Messfixture fuer den Screening-Vorfilter (#892)

`corpus.jsonl` ist eine **synthetische** Trefferliste mit 1000 Datensaetzen in
der Groessenordnung des Befundes aus dem Issue (1095 bzw. 1672 Treffer eines
echten Laufs). Sie belegt, um welchen Faktor der mechanische Vorfilter die
Zahl der Modelldurchlaeufe senkt — sie ist **keine** Aussage darueber, wie
viele Treffer eines beliebigen echten Korpus die Kriterien verfehlen.

Erzeugt von `scripts/dev/generate_screening_prefilter_fixture.py` (fester Seed
`892`). Das Skript ist die Herkunftsdokumentation; es laeuft nicht als Teil der
Tests. Neu erzeugen:

```bash
uv run python scripts/dev/generate_screening_prefilter_fixture.py
```

## Zusammensetzung

| Gruppe | n | erwartet |
|--------|---|----------|
| Publikationsjahr vor dem Reviewfenster (< 2015) | 480 | mechanisch ausgeschlossen (Kriterium `Zeitraum`) |
| Sprache ausserhalb der Allowlist (`fr`/`es`/`zh`/`pt`/`ru`) | 250 | mechanisch ausgeschlossen (Kriterium `Sprache`) |
| Publikationstyp ausserhalb der Allowlist (`editorial`, `book-review`, `dataset`, `erratum`) | 130 | mechanisch ausgeschlossen (Kriterium `Publikationstyp`) |
| genau ein Metadatum fehlt (`year`/`language`/`publication_type` = `null`) | 60 | **bleibt** in der Modellmenge (fail-open) |
| alle drei Kriterien erfuellt | 80 | bleibt in der Modellmenge |

Damit gehen 140 der 1000 Treffer ins Modell: `ceil(1000/10) = 100` Batches
vorher gegen `ceil(140/10) = 14` Batches nachher.

## Konstruktionsregel (gegen Test-Gaming)

Der Vorfilter darf nicht an einer Liste gemessen werden, die auf ihn hin
gebaut ist. Darum:

1. **Der Gegenstand traegt kein Signal.** Alle fuenf Gruppen ziehen ihren
   Titel aus demselben Themenpool. Ein Filter, der am Titel entscheidet,
   trennt hier nichts — nur die drei Metadatenfelder tun es.
2. **Fehlende Metadaten sind eine eigene Gruppe.** 60 Datensaetzen fehlt genau
   ein Feld. Sie sind der Gegenbeweis gegen einen Filter, der bei Unwissen
   ausschliesst: sie muessen samt und sonders im Modelldurchlauf landen.
3. **Jedes Ausschlusskriterium greift nur an einem Feld.** Kein Datensatz
   verletzt zwei Kriterien gleichzeitig; die Aufschluesselung im
   Vorfilter-Report ist damit nachrechenbar und nicht von der Prueffolge
   abhaengig.
4. **Die Ueberlebenden sind nicht die relevanten.** Die 140 Ueberlebenden
   ziehen ihre Themen aus demselben Pool wie die Ausgeschlossenen. Der
   Vorfilter entscheidet ausdruecklich nicht ueber Relevanz — das bleibt dem
   Modell.
5. **Die Ausgangsreihenfolge ist gemischt** (fester Seed), also weder nach
   Gruppen sortiert noch von Hand gelegt.

`tests/test_issue_892_screening_prefilter.py` prueft die Punkte 1, 2 und 3 am
Dateiinhalt nach.

## Format

Eine JSON-Zeile je Datensatz, Schluessel alphabetisch sortiert:

```json
{"doi": "10.9999/ar892.0000", "language": "en", "paper_id": "p0000",
 "publication_type": "journal-article", "title": "…", "venue": "…", "year": 2019}
```
