"""Tests fuer scripts/audit_author_names.py (Issue #908 AC5).

Read-only Bestandscheck: liest papers.csl_json aus dem Vault, wendet
denselben Plausibilitaetscheck an wie parse_author_names()/
csl_authors_to_parsed(), gibt eine Liste betroffener paper_ids zurueck.
Mutiert nichts am Vault-Inhalt.
"""

from __future__ import annotations

import json

from academic_vault.db import VaultDB

import audit_author_names


def _add_paper(db_path: str, paper_id: str, authors: list[dict]) -> None:
    csl = {
        "type": "article-journal",
        "title": f"Titel von {paper_id}",
        "author": authors,
    }
    with VaultDB(db_path) as db:
        db.add_paper(paper_id=paper_id, csl_json=json.dumps(csl))


def test_audit_flags_known_bad_entry(temp_vault_db) -> None:
    """Ein praeparierter Fehleintrag (Nachname == Vorname eines Co-Autors)
    taucht in der Audit-Ausgabe auf; ein unauffaelliger Eintrag nicht."""
    _add_paper(
        temp_vault_db,
        "bad-entry-1",
        [{"family": "Miller", "given": "Peter"}, {"family": "Peter", "given": "Someone"}],
    )
    _add_paper(
        temp_vault_db,
        "good-entry-1",
        [{"family": "Snell", "given": "Charlie"}, {"family": "Huang", "given": "Dong"}],
    )

    flagged = audit_author_names.audit(temp_vault_db)

    flagged_ids = {entry["paper_id"] for entry in flagged}
    assert "bad-entry-1" in flagged_ids
    assert "good-entry-1" not in flagged_ids


def test_audit_does_not_mutate_vault(temp_vault_db) -> None:
    """Read-only: der Aufruf veraendert weder csl_json noch die Zeilenzahl."""
    _add_paper(
        temp_vault_db,
        "bad-entry-2",
        [{"family": "Miller", "given": "Peter"}, {"family": "Peter", "given": "Someone"}],
    )
    with VaultDB(temp_vault_db) as db:
        before = db._papers_snapshot()

    audit_author_names.audit(temp_vault_db)

    with VaultDB(temp_vault_db) as db:
        after = db._papers_snapshot()
    assert before == after


def test_audit_returns_empty_list_for_clean_vault(temp_vault_db) -> None:
    _add_paper(
        temp_vault_db,
        "clean-1",
        [{"family": "Snell", "given": "Charlie"}],
    )

    assert audit_author_names.audit(temp_vault_db) == []
