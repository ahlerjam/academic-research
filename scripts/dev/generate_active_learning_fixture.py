#!/usr/bin/env python3
"""Erzeugt die Gold-Trefferliste für den Active-Learning-Validierungslauf (#602).

Der Validierungslauf aus AC6 braucht eine Trefferliste mit **bekanntem**
Ergebnis. Sie wird hier deterministisch erzeugt statt von Hand geschrieben,
damit die Konstruktionsregel nachprüfbar ist und niemand die Datei
stillschweigend auf den Klassifikator hin frisiert.

Konstruktionsregel (Kern der Aussagekraft):

1. **Das Thema trägt kein Signal.** Alle Datensätze — relevante wie
   irrelevante — ziehen ihren Gegenstand aus demselben Pool
   (``TOPICS``: Lernvideos, Online-Kurse, …). Ein Klassifikator, der nur
   Themenwörter lernt, kann die beiden Klassen nicht trennen.
2. **Das Signal liegt im Studiendesign**, nicht im Vokabular an sich: relevante
   Datensätze sind Wirksamkeitsstudien (Kontrollgruppe, Prä-/Posttest),
   irrelevante sind Essays, Erfahrungsberichte aus der Schule oder
   Überblicksartikel.
3. **Harte Negative** (``_hard_negative``): irrelevante Datensätze, die die
   Methodenwörter der relevanten Klasse ausdrücklich verwenden (ein Aufsatz
   *über* randomisierte Zuweisung). Sie sind der Grund, warum die Aufgabe
   nicht trivial ist.
4. **Harte Positive** (``_sparse_positive``): relevante Datensätze mit
   auffällig wenigen Methodenwörtern (quasi-experimenteller Kohortenvergleich).
5. Die Ausgangsreihenfolge ist mit festem Seed gemischt — sie ist damit weder
   nach Relevanz sortiert noch von Hand gelegt.

Aufruf:

    uv run python scripts/dev/generate_active_learning_fixture.py

Schreibt ``tests/fixtures/active_learning/gold_screening.jsonl``. Die Datei ist
im Repository eingecheckt; das Skript ist die Herkunftsdokumentation, nicht
Teil der Testausführung.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "tests" / "fixtures" / "active_learning" / "gold_screening.jsonl"

SEED = 602
N_RELEVANT = 15
N_IRRELEVANT = 135

#: Gegenstandsbereich — identisch für beide Klassen, trägt darum kein Signal.
TOPICS = [
    "Lernvideos",
    "Online-Kursen",
    "digitalen Uebungsaufgaben",
    "adaptiven Lernumgebungen",
    "E-Learning-Modulen",
    "Vorlesungsaufzeichnungen",
    "digitalen Quizformaten",
    "Lernplattformen",
    "Webinaren",
    "digitalen Lerntagebuechern",
]

MEASURES = [
    "Klausurergebnis",
    "Wissenszuwachs",
    "Lernerfolg",
    "Aufgabenloesequote",
    "Behaltensleistung",
]

FIELDS = [
    "der Hochschullehre",
    "der universitaeren Lehre",
    "des Grundstudiums",
    "der Lehrerbildung",
    "der Weiterbildung",
]


def _relevant(rng: random.Random, topic: str, index: int) -> dict[str, object]:
    measure = rng.choice(MEASURES)
    field = rng.choice(FIELDS)
    n = rng.choice([64, 88, 112, 140, 176, 208])
    return {
        "paper_id": f"gold{index:03d}",
        "title": f"Wirksamkeit von {topic} in {field}: eine randomisierte Studie",
        "abstract": (
            f"Die Studie prueft die Wirkung von {topic} auf den {measure} von Studierenden "
            f"in {field}. {n} Studierende wurden randomisiert einer Interventionsgruppe und "
            f"einer Kontrollgruppe zugewiesen. Der {measure} wurde im Praetest und im Posttest "
            "erhoben. Die Effektstaerke der Intervention war statistisch signifikant."
        ),
        "relevant": True,
    }


def _sparse_positive(rng: random.Random, topic: str, index: int) -> dict[str, object]:
    """Relevant, aber mit wenigen Methodenwoertern — harter Fall fuer den Ranker."""
    measure = rng.choice(MEASURES)
    field = rng.choice(FIELDS)
    return {
        "paper_id": f"gold{index:03d}",
        "title": f"{topic} im Vergleich zweier Kohorten in {field}",
        "abstract": (
            f"Eine quasi-experimentelle Untersuchung zum Einsatz von {topic} in {field}. "
            f"Zwei aufeinanderfolgende Kohorten wurden verglichen; berichtet werden die "
            f"Unterschiede im {measure}."
        ),
        "relevant": True,
    }


def _essay(rng: random.Random, topic: str, index: int) -> dict[str, object]:
    field = rng.choice(FIELDS)
    return {
        "paper_id": f"gold{index:03d}",
        "title": f"Zum Stellenwert von {topic} in {field}",
        "abstract": (
            f"Der Beitrag diskutiert {topic} in {field} aus theoretischer Sicht. "
            "Es handelt sich um ein Positionspapier ohne eigene Datenerhebung. "
            "Argumentiert wird entlang bildungstheoretischer Konzepte."
        ),
        "relevant": False,
    }


def _school_report(rng: random.Random, topic: str, index: int) -> dict[str, object]:
    return {
        "paper_id": f"gold{index:03d}",
        "title": f"Erfahrungsbericht: {topic} im Schulunterricht",
        "abstract": (
            f"Der Erfahrungsbericht schildert den Einsatz von {topic} in der Grundschule. "
            "Beschrieben werden Curriculum, Ablauf und organisatorische Huerden. "
            "Eine systematische Erhebung fand nicht statt."
        ),
        "relevant": False,
    }


def _overview(rng: random.Random, topic: str, index: int) -> dict[str, object]:
    field = rng.choice(FIELDS)
    return {
        "paper_id": f"gold{index:03d}",
        "title": f"Ueberblick: Forschungsstand zu {topic}",
        "abstract": (
            f"Der Ueberblicksartikel fasst die Literatur zu {topic} in {field} zusammen. "
            "Berichtet wird der Stand der Diskussion; eigene Daten werden nicht erhoben. "
            "Abschliessend werden Forschungsluecken benannt."
        ),
        "relevant": False,
    }


def _tool_description(rng: random.Random, topic: str, index: int) -> dict[str, object]:
    field = rng.choice(FIELDS)
    return {
        "paper_id": f"gold{index:03d}",
        "title": f"Konzeption und technische Umsetzung von {topic}",
        "abstract": (
            f"Vorgestellt wird die technische Umsetzung von {topic} fuer {field}. "
            "Der Beitrag beschreibt Architektur, Schnittstellen und Betrieb der Plattform. "
            "Eine Wirkungsmessung ist nicht Gegenstand des Beitrags."
        ),
        "relevant": False,
    }


def _hard_negative(rng: random.Random, topic: str, index: int) -> dict[str, object]:
    """Irrelevant, verwendet aber die Methodenwoerter der relevanten Klasse."""
    field = rng.choice(FIELDS)
    return {
        "paper_id": f"gold{index:03d}",
        "title": f"Methodische Anforderungen an Wirksamkeitsstudien zu {topic}",
        "abstract": (
            f"Der Beitrag diskutiert, wie Kontrollgruppe, randomisierte Zuweisung und "
            f"Praetest-Posttest-Design in der Forschung zu {topic} in {field} einzusetzen "
            "waeren. Effektstaerke und Signifikanz werden methodisch eroertert. "
            "Eigene Daten wurden nicht erhoben."
        ),
        "relevant": False,
    }


IRRELEVANT_KINDS = (_essay, _school_report, _overview, _tool_description)


def build_records() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    records: list[dict[str, object]] = []
    index = 1

    for i in range(N_RELEVANT):
        topic = TOPICS[i % len(TOPICS)]
        # Jeder fuenfte relevante Datensatz ist ein harter Positivfall.
        maker = _sparse_positive if i % 5 == 4 else _relevant
        records.append(maker(rng, topic, index))
        index += 1

    for i in range(N_IRRELEVANT):
        topic = TOPICS[i % len(TOPICS)]
        # Jeder zwoelfte irrelevante Datensatz ist ein hartes Negativ.
        if i % 12 == 11:
            records.append(_hard_negative(rng, topic, index))
        else:
            records.append(IRRELEVANT_KINDS[i % len(IRRELEVANT_KINDS)](rng, topic, index))
        index += 1

    rng.shuffle(records)
    return records


def main() -> int:
    records = build_records()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    n_relevant = sum(1 for r in records if r["relevant"])
    print(f"{OUTPUT_PATH}: {len(records)} Datensaetze, davon {n_relevant} relevant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
