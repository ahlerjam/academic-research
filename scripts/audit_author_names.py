#!/usr/bin/env python3
"""audit_author_names.py -- Bestandscheck fuer vertauschte Autorennamen (Issue #908 AC5).

Liest ``papers.csl_json`` aus dem Vault (read-only, keine Mutation) und
wendet denselben Plausibilitaetscheck an, den ``parse_author_names()``/
``csl_authors_to_parsed()`` bereits im Ingest-Pfad nutzen: landet der
Nachname eines Autors auch als Vorname eines Co-Autors desselben Papers,
deutet das auf eine vertauschte "Nachname, Vorname"-Zerlegung hin.

Das Ergebnis ist eine Liste betroffener Eintraege -- keine stille
Massenaenderung an bereits zitierten Arbeiten (Issue-Scope, AC5).

CLI:
    uv run python scripts/audit_author_names.py [--db-path PFAD] [--json]

Ohne ``--db-path`` gilt derselbe Default wie der academic-vault-MCP-Server
(``academic_vault.db.default_db_path()``).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from academic_vault.db import default_db_path  # noqa: E402

from text_utils import csl_authors_to_parsed  # noqa: E402


def audit(db_path: str) -> list[dict[str, Any]]:
    """Scannt alle Papers im Vault auf implausible Autoren-Splits.

    Read-only: oeffnet die SQLite-Datei direkt im URI-Modus ``mode=ro``
    (kein ``academic_vault.db.VaultDB``-Schreibpfad involviert), damit ein
    Bug im Audit-Skript strukturell keine Mutation am Vault-Inhalt ausloesen
    kann -- unabhaengig davon, ob spaeter jemand Schreiblogik ergaenzt.

    Returns:
        Liste von Dicts ``{"paper_id", "title", "warnings"}`` fuer jedes
        Paper mit mindestens einer Plausibilitaets-Warnung. Leere Liste bei
        sauberem Bestand.
    """
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT paper_id, csl_json FROM papers").fetchall()
    finally:
        conn.close()

    flagged: list[dict[str, Any]] = []
    for row in rows:
        try:
            csl = json.loads(row["csl_json"])
        except (TypeError, ValueError):
            continue
        if not isinstance(csl, dict):
            continue
        authors = csl.get("author")
        if not isinstance(authors, list) or not authors:
            continue
        parsed = csl_authors_to_parsed(authors)
        warnings = [p.warning for p in parsed if p.warning]
        if warnings:
            flagged.append(
                {
                    "paper_id": row["paper_id"],
                    "title": csl.get("title"),
                    "warnings": warnings,
                }
            )
    return flagged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Bestandscheck auf implausible Autoren-Splits (Issue #908 AC5)"
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Pfad zur vault.db (Default: academic_vault.db.default_db_path())",
    )
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON statt Klartext")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.db_path or default_db_path()
    if not Path(db_path).exists():
        print(f"[ERROR] Vault-DB nicht gefunden: {db_path}", file=sys.stderr)
        return 1

    flagged = audit(db_path)

    if args.json:
        print(json.dumps(flagged, ensure_ascii=False, indent=2))
    elif not flagged:
        print("Keine implausiblen Autoren-Zerlegungen gefunden.")
    else:
        print(f"{len(flagged)} Paper(s) mit implausibler Autoren-Zerlegung:")
        for entry in flagged:
            print(f"  {entry['paper_id']}: {entry['title']}")
            for warning in entry["warnings"]:
                print(f"    - {warning}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
