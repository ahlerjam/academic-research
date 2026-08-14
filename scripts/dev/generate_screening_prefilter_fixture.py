#!/usr/bin/env python3
"""Erzeugt die Messfixture fuer den Screening-Vorfilter (Issue #892).

Schreibt ``tests/fixtures/screening_prefilter_892/corpus.jsonl``: 1000
synthetische Treffer, wie sie eine thematische Suche ueber sieben Module
liefert. Fester Seed (892), damit zwei Laeufe byte-identisch sind.

Das Skript ist die Herkunftsdokumentation der Fixture; es laeuft nicht als
Teil der Tests. Neu erzeugen:

    uv run python scripts/dev/generate_screening_prefilter_fixture.py

Die Konstruktionsregel (gegen Test-Gaming) steht in der README.md neben der
Datei und wird von ``tests/test_issue_892_screening_prefilter.py`` am
Dateiinhalt nachgeprueft.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "screening_prefilter_892"
OUT_PATH = OUT_DIR / "corpus.jsonl"

SEED = 892

#: Gegenstaende der Arbeiten. Bewusst ueber ALLE Gruppen hinweg derselbe Pool:
#: kein Wort im Titel trennt die mechanisch ausschliessbaren von den anderen.
TOPICS = [
    "DevOps governance in regulated industries",
    "continuous delivery and internal control",
    "platform teams and change approval",
    "infrastructure as code compliance",
    "release management maturity",
    "audit trails in deployment pipelines",
    "segregation of duties in CI/CD",
    "cloud operating models",
    "site reliability engineering practices",
    "toolchain consolidation in large enterprises",
]

VENUES = [
    "Journal of Systems and Software",
    "IEEE Software",
    "Information and Software Technology",
    "ACM Computing Surveys",
    "Business & Information Systems Engineering",
    "Proceedings of ICSE",
]

#: Gruppengroessen. Summe 1000.
N_OUT_OF_WINDOW = 480
N_WRONG_LANGUAGE = 250
N_WRONG_TYPE = 130
N_MISSING_METADATA = 60
N_COMPLIANT = 80


def _record(rng: random.Random, index: int, **overrides: object) -> dict[str, object]:
    topic = TOPICS[index % len(TOPICS)]
    record: dict[str, object] = {
        "paper_id": f"p{index:04d}",
        "doi": f"10.9999/ar892.{index:04d}",
        "title": f"{topic} ({index})",
        "venue": rng.choice(VENUES),
        "year": rng.randint(2015, 2025),
        "language": "en",
        "publication_type": "journal-article",
    }
    record.update(overrides)
    return record


def build_corpus() -> list[dict[str, object]]:
    rng = random.Random(SEED)
    records: list[dict[str, object]] = []
    index = 0

    for _ in range(N_OUT_OF_WINDOW):
        records.append(_record(rng, index, year=rng.randint(1988, 2014)))
        index += 1

    for _ in range(N_WRONG_LANGUAGE):
        records.append(_record(rng, index, language=rng.choice(["fr", "es", "zh", "pt", "ru"])))
        index += 1

    for _ in range(N_WRONG_TYPE):
        records.append(
            _record(
                rng,
                index,
                publication_type=rng.choice(["editorial", "book-review", "dataset", "erratum"]),
            )
        )
        index += 1

    # Fehlende Metadaten: der Vorfilter darf daran NICHT ausschliessen.
    for slot in range(N_MISSING_METADATA):
        missing = ["year", "language", "publication_type"][slot % 3]
        records.append(_record(rng, index, **{missing: None}))
        index += 1

    for _ in range(N_COMPLIANT):
        records.append(_record(rng, index))
        index += 1

    rng.shuffle(records)
    return records


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in build_corpus()]
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUT_PATH}: {len(lines)} Datensaetze")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
