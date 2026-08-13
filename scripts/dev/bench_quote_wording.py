#!/usr/bin/env python3
"""Latenz-Messung des Wortlaut-Abgleichs im Guard-Pfad (Issue #846).

Vergleicht die beiden Vault-Aufrufe, die `hooks/verbatim-guard.mjs` fuer die
Zitat-Spans eines Writes machen kann:

* ALT: ein ``search_quote_text()`` je Span (LIKE-Substring, Boolean).
* NEU: ein ``match_quote_wording()`` fuer ALLE Spans (ein Quotes-Snapshot,
  Normalisierung, Fuzzy-Zuordnung).

Gemessen wird nur die Python-Seite; der Interpreterstart (~0,3 s) und der
Node-Overhead kommen in beiden Faellen einmal je Write hinzu und sind fuer den
Vergleich irrelevant.

Aufruf::

    uv run python scripts/dev/bench_quote_wording.py [--quotes 2000] [--spans 8]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from academic_vault.db import VaultDB  # noqa: E402
from academic_vault.server import match_quote_wording, search_quote_text  # noqa: E402

SENTENCE = (
    "Governance ist ein Prozess der Aushandlung zwischen mehreren Akteuren und "
    "keine einmalige Entscheidung, sondern eine fortlaufende Aufgabe der Nummer {n}."
)


def build_vault(db_path: str, quote_count: int) -> None:
    """Legt eine Vault-DB mit ``quote_count`` verschiedenen Zitaten an."""
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(
        paper_id="bench-paper",
        csl_json=json.dumps({"title": "Bench", "type": "article-journal"}),
    )
    for index in range(quote_count):
        db.add_quote(
            quote_id=f"q-{index:06d}",
            paper_id="bench-paper",
            verbatim=SENTENCE.format(n=index),
            extraction_method="manual",
        )


def median_ms(durations: list[float]) -> float:
    ordered = sorted(durations)
    return ordered[len(ordered) // 2] * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quotes", type=int, default=2000, help="Zitate im Vault")
    parser.add_argument("--spans", type=int, default=8, help="Zitat-Spans je Write")
    parser.add_argument("--runs", type=int, default=5, help="Wiederholungen")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "bench_vault.db")
        build_vault(db_path, args.quotes)

        # Haelfte exakt, Haelfte mit einem ausgetauschten Wort (Worst Case:
        # der Fuzzy-Pfad laeuft nur fuer die abweichenden).
        candidates = [
            SENTENCE.format(n=i)
            if i % 2 == 0
            else SENTENCE.format(n=i).replace("Prozess", "Vorgang")
            for i in range(args.spans)
        ]

        old: list[float] = []
        new: list[float] = []
        for _ in range(args.runs):
            start = time.perf_counter()
            for candidate in candidates:
                search_quote_text(db_path, candidate)
            old.append(time.perf_counter() - start)

            start = time.perf_counter()
            match_quote_wording(db_path, candidates)
            new.append(time.perf_counter() - start)

    print(f"Vault-Zitate: {args.quotes}, Spans je Write: {args.spans}, Laeufe: {args.runs}")
    print(f"ALT  search_quote_text (je Span):      Median {median_ms(old):7.1f} ms")
    print(f"NEU  match_quote_wording (ein Batch):  Median {median_ms(new):7.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
