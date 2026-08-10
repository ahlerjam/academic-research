#!/usr/bin/env python3
"""Groessenmessung: lohnt ein Trigram-Index ueber ``paper_fulltext.text`` bzw.
``notes.text``? (Folge-Issue aus #703, Issue #766)

#703 hat ``papers_trgm`` bewusst auf Titel/Abstract begrenzt (1-2 KB je
Paper). Offen blieb, ob dieselbe Teilwortsuche auch fuer den PDF-Volltext
(50-200 KB je Paper) und fuer Notizen gerechtfertigt ist. Die
Entscheidungsregel (Issue-Kommentar vom 2026-08-10) verlangt dafuer BEIDE
Bedingungen:

  1. **Groesse:** die Vault-Datei waechst durch den Index um weniger als
     100 % -- gemessen an einem realistischen Bestand, nicht an einem
     Einzeldokument. Reisst diese Bedingung, faellt die Entscheidung negativ,
     unabhaengig vom Nutzen.
  2. **Nutzen:** ein Nachweis, dass die Teilwortsuche im Volltext Treffer
     erzeugt, die die bestehende Wortsuche nicht schon liefert. #789 zeigt,
     dass das #708-Goldset dafuer strukturell tot ist (1/60 ``papers_fts``-,
     0/60 ``papers_trgm``-Treffer) -- diese Bedingung ist mit der heutigen
     Datenlage nicht neu zu erheben, sondern nur zu referenzieren.

Dieses Skript liefert AUSSCHLIESSLICH die Groessenmessung (Bedingung 1), je
Tabelle unabhaengig, vorher/nachher in Bytes nach ``VACUUM``. Der
generierte Korpus ist bewusst NICHT repetitiv (kein Lorem-Ipsum) -- ein
Text, der sich staendig wiederholt, wuerde den Trigram-Zuwachs kuenstlich
niedrig ausfallen lassen (SQLite-FTS5-Groesse haengt stark von der
Textredundanz ab).

Nutzung::

    uv run python scripts/eval/measure_fulltext_trgm_size_766.py

Schreibt ``docs/evals/2026-08-10-fulltext-trgm-size-766.json``
(``--out`` zum Ueberschreiben des Pfads).
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUT_PATH = REPO_ROOT / "docs" / "evals" / "2026-08-10-fulltext-trgm-size-766.json"

#: Entscheidungsschwelle aus dem Issue-Kommentar vom 2026-08-10 (Bedingung 1):
#: der Index darf die Vault-Datei hoechstens verdoppeln. Bei >= 100 % Zuwachs
#: faellt die Entscheidung negativ, unabhaengig von Bedingung 2 (Nutzen).
GROWTH_THRESHOLD_PCT = 100.0

#: Realistische Groessenordnungen aus dem Issue-Body: PDF-Volltexte 50-200 KB
#: je Paper, Notizen deutlich kleiner (0.5-5 KB, eigene Schaetzung).
FULLTEXT_MIN_KB = 50
FULLTEXT_MAX_KB = 200
NOTE_MIN_KB = 0.5
NOTE_MAX_KB = 5.0

#: Realistischer synthetischer Bestand fuer den dokumentierten Messlauf
#: (docs/evals/2026-08-10-fulltext-trgm-size-766.md). Tests verwenden
#: deutlich kleinere Zahlen fuer Laufzeit.
DEFAULT_N_PAPERS = 40
DEFAULT_N_NOTES = 80

# ---------------------------------------------------------------------------
# Nicht-repetitiver Korpusgenerator
# ---------------------------------------------------------------------------

# Deutsche Wortstamm-Bausteine + Endungen: Kombinatorik statt Wiederholung.
# Ueber die Kreuzung von ~40 Staemmen mit ~14 Endungen entstehen > 500
# unterschiedliche Woerter, dazu Funktionswoerter fuer fliessenden Satzbau --
# bewusst KEIN Lorem-Ipsum-Wiederholungsmuster (siehe Plan-Risiko).
_STAEMME = [
    "Mittelstand",
    "Digitalisier",
    "Governance",
    "Organisation",
    "Transformation",
    "Wertschoepf",
    "Prozess",
    "Struktur",
    "Kompetenz",
    "Innovation",
    "Nachhaltig",
    "Regulier",
    "Kooperation",
    "Ressourc",
    "Strateg",
    "Fuehrung",
    "Investition",
    "Qualifizier",
    "Digitalkompetenz",
    "Betrieb",
    "Wettbewerb",
    "Marktanteil",
    "Kundenbeziehung",
    "Lieferkette",
    "Produktion",
    "Automatisier",
    "Datenschutz",
    "Compliance",
    "Effizienz",
    "Skalier",
    "Personal",
    "Fachkraeft",
    "Standort",
    "Region",
    "Netzwerk",
    "Plattform",
    "Schnittstelle",
    "Systemintegr",
    "Cloudmigration",
    "Cybersicherheit",
]
_ENDUNGEN = [
    "ung",
    "ungen",
    "ierung",
    "sansatz",
    "sstrategie",
    "smodell",
    "sprozess",
    "sfaktor",
    "spotenzial",
    "sgrenze",
    "smassnahme",
    "sniveau",
    "sbedarf",
    "skonzept",
]
_FUNKTIONSWOERTER = [
    "im",
    "der",
    "die",
    "das",
    "und",
    "fuer",
    "bei",
    "durch",
    "ueber",
    "zwischen",
    "innerhalb",
    "insbesondere",
    "vor allem",
    "dabei",
    "zunehmend",
    "bereits",
    "haeufig",
    "entlang",
    "im Rahmen von",
    "gegenueber",
]


def _word(rng: random.Random) -> str:
    """Ein deterministisches, kombiniertes Wort (Stamm + Endung)."""
    return rng.choice(_STAEMME) + rng.choice(_ENDUNGEN)


def _sentence(rng: random.Random) -> str:
    """Ein Satz aus 8-16 Woertern, Mix aus Komposita und Funktionswoertern."""
    length = rng.randint(8, 16)
    parts: list[str] = []
    for i in range(length):
        if i % 3 == 1:
            parts.append(rng.choice(_FUNKTIONSWOERTER))
        else:
            parts.append(_word(rng))
    sentence = " ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def _generate_text(seed: int, target_bytes: int) -> str:
    """Erzeugt deterministischen, nicht-repetitiven Fliesstext bis zur Zielgroesse."""
    rng = random.Random(seed)
    sentences: list[str] = []
    size = 0
    while size < target_bytes:
        sentence = _sentence(rng)
        sentences.append(sentence)
        size += len(sentence.encode("utf-8")) + 1
    return " ".join(sentences)


def generate_fulltext(seed: int, target_bytes: int) -> str:
    """Synthetischer PDF-Volltext (deterministisch ueber ``seed``)."""
    return _generate_text(seed, target_bytes)


def generate_note(seed: int, target_bytes: int) -> str:
    """Synthetische Notiz (deterministisch ueber ``seed``, deutlich kuerzer)."""
    return _generate_text(seed, target_bytes)


# ---------------------------------------------------------------------------
# Messung: Vorher/Nachher-Bytes je Tabelle, unabhaengig
# ---------------------------------------------------------------------------


def _vacuum_size(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    return db_path.stat().st_size


def measure_fulltext_variant(tmp_dir: Path, n_papers: int, seed: int) -> dict[str, Any]:
    """Vorher/Nachher-Groesse: Trigram-Index ueber ``paper_fulltext.text``.

    Baut eine Baseline-Vault (aktuelles Schema inkl. ``papers_trgm`` fuer
    Titel/Abstract, aber ohne Volltext-Trigram), fuellt sie mit
    ``n_papers`` synthetischen Papern samt PDF-Volltext, misst die
    Dateigroesse nach ``VACUUM``. Kopiert die DB, haengt eine eigene
    ``fts5(tokenize='trigram')``-Tabelle ueber ``paper_fulltext.text`` an und
    misst erneut -- unabhaengig vom Schema-Weg aus #703 (dort wird
    ``papers_trgm`` nicht angefasst).
    """
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper

    tmp_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = tmp_dir / "fulltext_baseline.db"
    db = VaultDB(str(baseline_path))
    db.init_schema()

    for i in range(n_papers):
        paper_seed = seed + i
        target_bytes = random.Random(paper_seed).randint(FULLTEXT_MIN_KB, FULLTEXT_MAX_KB) * 1024
        text = generate_fulltext(paper_seed, target_bytes)
        paper_id = f"p{i:04d}"
        csl_json = json.dumps({"type": "article-journal", "title": f"Synthetisches Paper {i}"})
        add_paper(str(baseline_path), paper_id, csl_json)
        db.set_fulltext(paper_id, text)

    baseline_bytes = _vacuum_size(baseline_path)

    trgm_path = tmp_dir / "fulltext_trgm.db"
    shutil.copy(baseline_path, trgm_path)
    conn = sqlite3.connect(str(trgm_path))
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE paper_fulltext_trgm "
            "USING fts5(paper_id UNINDEXED, text, tokenize='trigram')"
        )
        conn.execute(
            "INSERT INTO paper_fulltext_trgm(paper_id, text) "
            "SELECT paper_id, text FROM paper_fulltext"
        )
        conn.commit()
    finally:
        conn.close()

    with_trgm_bytes = _vacuum_size(trgm_path)
    growth_pct = round((with_trgm_bytes - baseline_bytes) / baseline_bytes * 100.0, 2)

    return {
        "table": "paper_fulltext",
        "n_rows": n_papers,
        "baseline_bytes": baseline_bytes,
        "with_trgm_bytes": with_trgm_bytes,
        "growth_pct": growth_pct,
    }


def measure_notes_variant(tmp_dir: Path, n_notes: int, seed: int) -> dict[str, Any]:
    """Vorher/Nachher-Groesse: Trigram-Index ueber ``notes.text``.

    Analog zu :func:`measure_fulltext_variant`, aber fuer Notizen -- eigener
    Lauf, eigenes Ergebnis (AC3 verlangt eine GETRENNTE Entscheidung).
    """
    from academic_vault.db import VaultDB
    from academic_vault.server import add_note, add_paper

    tmp_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = tmp_dir / "notes_baseline.db"
    db = VaultDB(str(baseline_path))
    db.init_schema()

    paper_id = "p_notes_host"
    add_paper(
        str(baseline_path),
        paper_id,
        json.dumps({"type": "article-journal", "title": "Notiz-Traeger-Paper"}),
    )

    for i in range(n_notes):
        note_seed = seed + i
        target_bytes = int(random.Random(note_seed).uniform(NOTE_MIN_KB, NOTE_MAX_KB) * 1024)
        text = generate_note(note_seed, target_bytes)
        add_note(str(baseline_path), paper_id, text, tags="synthetic-766")

    baseline_bytes = _vacuum_size(baseline_path)

    trgm_path = tmp_dir / "notes_trgm.db"
    shutil.copy(baseline_path, trgm_path)
    conn = sqlite3.connect(str(trgm_path))
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE notes_trgm "
            "USING fts5(note_id UNINDEXED, text, tokenize='trigram')"
        )
        conn.execute("INSERT INTO notes_trgm(note_id, text) SELECT note_id, text FROM notes")
        conn.commit()
    finally:
        conn.close()

    with_trgm_bytes = _vacuum_size(trgm_path)
    growth_pct = round((with_trgm_bytes - baseline_bytes) / baseline_bytes * 100.0, 2)

    return {
        "table": "notes",
        "n_rows": n_notes,
        "baseline_bytes": baseline_bytes,
        "with_trgm_bytes": with_trgm_bytes,
        "growth_pct": growth_pct,
    }


# ---------------------------------------------------------------------------
# Entscheidungsregel
# ---------------------------------------------------------------------------


def decide(growth_pct: float, threshold_pct: float = GROWTH_THRESHOLD_PCT) -> bool:
    """Bedingung 1 (Groesse) der Entscheidungsregel aus dem Issue-Kommentar.

    ``True`` heisst: der Zuwachs liegt unter der Schwelle, Bedingung 1 ist
    erfuellt (das entscheidet noch NICHT ueber den Index -- Bedingung 2,
    der Nutzen, muss zusaetzlich belegt sein). ``False`` heisst: die
    Entscheidung faellt negativ, unabhaengig vom Nutzen -- bei genau
    ``threshold_pct`` (Verdopplung) gilt das bereits als Ueberschreitung.
    """
    return growth_pct < threshold_pct


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-papers", type=int, default=DEFAULT_N_PAPERS)
    parser.add_argument("--n-notes", type=int, default=DEFAULT_N_NOTES)
    parser.add_argument("--seed", type=int, default=766)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    args = parser.parse_args(argv)

    import tempfile

    with tempfile.TemporaryDirectory(prefix="vault-fulltext-trgm-766-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        print(f"Messe paper_fulltext ({args.n_papers} Paper) ...", file=sys.stderr)
        fulltext_result = measure_fulltext_variant(tmp_dir / "fulltext", args.n_papers, args.seed)
        print(f"Messe notes ({args.n_notes} Notizen) ...", file=sys.stderr)
        notes_result = measure_notes_variant(tmp_dir / "notes", args.n_notes, args.seed + 10_000)

    report = {
        "meta": {
            "issue": 766,
            "generator": "scripts/eval/measure_fulltext_trgm_size_766.py",
            "growth_threshold_pct": GROWTH_THRESHOLD_PCT,
            "note": (
                "Bedingung 1 (Groesse) wird hier gemessen. Bedingung 2 (Nutzen) "
                "ist mit dem heutigen #708-Goldset laut #789 strukturell nicht "
                "pruefbar (1/60 papers_fts-, 0/60 papers_trgm-Treffer) -- siehe "
                "docs/evals/2026-08-10-fulltext-trgm-size-766.md."
            ),
        },
        "paper_fulltext": {
            **fulltext_result,
            "condition_1_size_ok": decide(fulltext_result["growth_pct"]),
        },
        "notes": {
            **notes_result,
            "condition_1_size_ok": decide(notes_result["growth_pct"]),
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Rohdaten geschrieben: {args.out}", file=sys.stderr)
    print(
        f"paper_fulltext: {fulltext_result['baseline_bytes']} -> "
        f"{fulltext_result['with_trgm_bytes']} Bytes "
        f"({fulltext_result['growth_pct']:+.2f} %), "
        f"Bedingung 1 {'erfuellt' if report['paper_fulltext']['condition_1_size_ok'] else 'gerissen'}",
        file=sys.stderr,
    )
    print(
        f"notes: {notes_result['baseline_bytes']} -> {notes_result['with_trgm_bytes']} Bytes "
        f"({notes_result['growth_pct']:+.2f} %), "
        f"Bedingung 1 {'erfuellt' if report['notes']['condition_1_size_ok'] else 'gerissen'}",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
