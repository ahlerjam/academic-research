"""Tests fuer die Kapitel-Pruefbilanz (Issue #737).

Deckt:
  AC1  Drei Buckets (geprueft & unauffaellig / Befund offen / nicht geprueft),
       deren Summe die Gesamtzahl ergibt. Plus: VaultDB.record_quote_audit
       als neuer, additiver Audit-Schreibpfad (nicht dasselbe wie `stance`).
  AC2  Jedes nicht gepruefte Zitat traegt einen konkreten `reason`.
  AC3  Offene Befunde nach Schwere aufgeschluesselt, einzeln benannt
       (quote_id, paper_id, verbatim, chapter_claim), schwerste zuerst.
  AC4  Kapitel ohne belegte Zitate liefert eine leere, fehlerfreie Bilanz.
  AC5  Ohne vorherigen Write abrufbar, deckt Zitate aus mehreren Sitzungen
       im selben Kapiteltext ab.
  AC6  Doku benennt den Nicht-Beweis-Charakter der Bilanz explizit.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def paper_id(temp_vault_db):
    from academic_vault.server import add_paper

    pid = "test-paper-737"
    add_paper(
        db_path=temp_vault_db,
        paper_id=pid,
        csl_json=json.dumps({"title": "Test Paper 737", "type": "article-journal"}),
    )
    return pid


@pytest.fixture
def quote_id(temp_vault_db, paper_id):
    from academic_vault.server import add_quote

    return add_quote(
        db_path=temp_vault_db,
        paper_id=paper_id,
        verbatim="Der Effekt war in allen Kohorten nachweisbar und robust.",
        extraction_method="manual",
    )


# ---------------------------------------------------------------------------
# AC1 -- VaultDB.record_quote_audit (Vault-Layer)
# ---------------------------------------------------------------------------


def test_record_quote_audit_persists_faithful_without_severity(temp_vault_db, quote_id):
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    db.record_quote_audit(quote_id, "faithful")

    record = db.get_quote(quote_id)
    assert record["audited_at"] is not None
    assert record["audit_verdict"] == "faithful"
    assert record["audit_severity"] is None


def test_record_quote_audit_persists_negative_verdict_with_severity(temp_vault_db, quote_id):
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    db.record_quote_audit(quote_id, "polarity-flip", "kritisch")

    record = db.get_quote(quote_id)
    assert record["audit_verdict"] == "polarity-flip"
    assert record["audit_severity"] == "kritisch"


def test_record_quote_audit_rejects_faithful_with_severity(temp_vault_db, quote_id):
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    with pytest.raises(ValueError):
        db.record_quote_audit(quote_id, "faithful", "mittel")

    assert db.get_quote(quote_id)["audited_at"] is None


def test_record_quote_audit_rejects_negative_verdict_without_severity(temp_vault_db, quote_id):
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    with pytest.raises(ValueError):
        db.record_quote_audit(quote_id, "overstated")

    assert db.get_quote(quote_id)["audited_at"] is None


def test_record_quote_audit_rejects_invalid_verdict(temp_vault_db, quote_id):
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    with pytest.raises(ValueError):
        db.record_quote_audit(quote_id, "not-a-real-verdict")


def test_record_quote_audit_rejects_unknown_quote_id(temp_vault_db):
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    with pytest.raises(ValueError):
        db.record_quote_audit("does-not-exist", "faithful")


def test_record_quote_audit_is_additive_to_stance_not_a_replacement(temp_vault_db, quote_id):
    """unsupported bekommt keinen stance-Wert (Mapping-Tabelle des Agenten),
    aber SEHR WOHL einen Audit-Datensatz -- die beiden Felder sind getrennt."""
    from academic_vault.db import VaultDB

    db = VaultDB(temp_vault_db)
    db.record_quote_audit(quote_id, "unsupported", "hoch")

    record = db.get_quote(quote_id)
    assert record["stance"] is None
    assert record["audited_at"] is not None
    assert record["audit_verdict"] == "unsupported"


def test_record_quote_audit_refuses_write_on_locked_passport(temp_vault_db, quote_id):
    """Issue #380/#523-Lernpunkt: Lock-Guard muss auch fuer den neuen
    Audit-Schreibpfad greifen (Mutationstest gegen `_raise_if_locked`)."""
    from academic_vault.db import VaultDB, VaultLockedError

    db = VaultDB(temp_vault_db)
    db.lock_vault("proj")

    with pytest.raises(VaultLockedError):
        db.record_quote_audit(quote_id, "faithful")

    assert db.get_quote(quote_id)["audited_at"] is None


def test_server_record_quote_audit_updates_record(temp_vault_db, quote_id):
    from academic_vault import server

    server.record_quote_audit(
        db_path=temp_vault_db, quote_id=quote_id, verdict="faithful", severity=None
    )

    record = server.get_quote(db_path=temp_vault_db, quote_id=quote_id)
    assert record["audit_verdict"] == "faithful"


def test_mcp_tools_are_registered():
    content = (REPO_ROOT / "academic_vault" / "server.py").read_text(encoding="utf-8")
    assert '@mcp.tool(name="vault.record_quote_audit")' in content
    assert '@mcp.tool(name="vault.chapter_quote_balance")' in content


# ---------------------------------------------------------------------------
# AC1/AC2/AC3 -- chapter_quote_balance: drei Buckets, Summe = Gesamtzahl,
# Gruende je nicht geprueftem Zitat, offene Befunde nach Schwere sortiert
# ---------------------------------------------------------------------------


def _make_chapter(verbatims: list[str]) -> str:
    parts = ["Einleitung ohne Zitat."]
    for i, v in enumerate(verbatims):
        parts.append(f'Beleg {i + 1}: "{v}" -- so die Quelle.')
    return " ".join(parts)


def test_chapter_quote_balance_splits_into_three_buckets_summing_to_total(temp_vault_db, tmp_path):
    from academic_vault.server import (
        add_paper,
        add_quote,
        chapter_quote_balance,
        record_quote_audit,
    )

    add_paper(
        db_path=temp_vault_db,
        paper_id="paper-balance",
        csl_json=json.dumps({"title": "Balance Paper", "type": "article-journal"}),
    )
    verbatims = [
        "Erstes belegtes Zitat mit ausreichender Laenge fuer den Scan.",
        "Zweites belegtes Zitat mit ausreichender Laenge fuer den Scan.",
        "Drittes belegtes Zitat mit ausreichender Laenge fuer den Scan.",
        "Viertes belegtes Zitat mit ausreichender Laenge fuer den Scan.",
        "Fuenftes belegtes Zitat mit ausreichender Laenge fuer den Scan.",
    ]
    quote_ids = [
        add_quote(
            db_path=temp_vault_db,
            paper_id="paper-balance",
            verbatim=v,
            extraction_method="manual",
        )
        for v in verbatims
    ]

    # 2x auditiert+faithful, 1x auditiert+overstated, 2x nie auditiert.
    record_quote_audit(db_path=temp_vault_db, quote_id=quote_ids[0], verdict="faithful")
    record_quote_audit(db_path=temp_vault_db, quote_id=quote_ids[1], verdict="faithful")
    record_quote_audit(
        db_path=temp_vault_db, quote_id=quote_ids[2], verdict="overstated", severity="mittel"
    )

    chapter_file = tmp_path / "kapitel3.md"
    chapter_file.write_text(_make_chapter(verbatims), encoding="utf-8")

    balance = chapter_quote_balance(db_path=temp_vault_db, chapter_path=str(chapter_file))

    assert balance["total_quotes"] == 5
    assert balance["geprueft_unauffaellig"] == 2
    assert balance["befund_offen"] == 1
    assert balance["nicht_geprueft"] == 2
    assert (
        balance["geprueft_unauffaellig"] + balance["befund_offen"] + balance["nicht_geprueft"]
        == balance["total_quotes"]
    )

    # AC2: jedes nicht gepruefte Zitat traegt einen konkreten Grund.
    assert len(balance["not_audited"]) == 2
    for entry in balance["not_audited"]:
        assert entry["reason"]
        assert entry["reason"] != "nicht geprueft"

    # AC3: der offene Befund ist einzeln benannt.
    assert len(balance["findings"]) == 1
    finding = balance["findings"][0]
    assert finding["quote_id"] == quote_ids[2]
    assert finding["paper_id"] == "paper-balance"
    assert finding["verbatim"] == verbatims[2]
    assert finding["chapter_claim"].strip()
    assert finding["verdict"] == "overstated"
    assert finding["severity"] == "mittel"


def test_chapter_quote_balance_sorts_findings_by_severity_worst_first(temp_vault_db, tmp_path):
    from academic_vault.server import (
        add_paper,
        add_quote,
        chapter_quote_balance,
        record_quote_audit,
    )

    add_paper(
        db_path=temp_vault_db,
        paper_id="paper-sev",
        csl_json=json.dumps({"title": "Severity Paper", "type": "article-journal"}),
    )
    verbatims = [
        "Zitat mit mittlerer Schwere und ausreichender Laenge im Text.",
        "Zitat mit kritischer Schwere und ausreichender Laenge im Text.",
        "Zitat mit hoher Schwere und ausreichender Laenge im Text.",
    ]
    quote_ids = [
        add_quote(
            db_path=temp_vault_db, paper_id="paper-sev", verbatim=v, extraction_method="manual"
        )
        for v in verbatims
    ]
    record_quote_audit(
        db_path=temp_vault_db, quote_id=quote_ids[0], verdict="overstated", severity="mittel"
    )
    record_quote_audit(
        db_path=temp_vault_db, quote_id=quote_ids[1], verdict="polarity-flip", severity="kritisch"
    )
    record_quote_audit(
        db_path=temp_vault_db, quote_id=quote_ids[2], verdict="unsupported", severity="hoch"
    )

    chapter_file = tmp_path / "kapitel-sev.md"
    chapter_file.write_text(_make_chapter(verbatims), encoding="utf-8")

    balance = chapter_quote_balance(db_path=temp_vault_db, chapter_path=str(chapter_file))

    severities = [f["severity"] for f in balance["findings"]]
    assert severities == ["kritisch", "hoch", "mittel"]


# ---------------------------------------------------------------------------
# AC4 -- Kapitel ohne belegte Zitate
# ---------------------------------------------------------------------------


def test_chapter_quote_balance_empty_chapter_returns_all_zero_no_error(temp_vault_db, tmp_path):
    from academic_vault.server import chapter_quote_balance

    chapter_file = tmp_path / "leeres-kapitel.md"
    chapter_file.write_text(
        "Reine Prosa ohne jedes Anfuehrungszeichen und ohne belegte Aussage.",
        encoding="utf-8",
    )

    balance = chapter_quote_balance(db_path=temp_vault_db, chapter_path=str(chapter_file))

    assert balance["total_quotes"] == 0
    assert balance["geprueft_unauffaellig"] == 0
    assert balance["befund_offen"] == 0
    assert balance["nicht_geprueft"] == 0
    assert balance["not_audited"] == []
    assert balance["findings"] == []


# ---------------------------------------------------------------------------
# AC5 -- ohne vorherigen Write abrufbar, deckt mehrere Sitzungen ab
# ---------------------------------------------------------------------------


def test_chapter_quote_balance_covers_whole_chapter_across_sessions(temp_vault_db, tmp_path):
    """Zitate aus 'Sitzung 1' und 'Sitzung 2' im selben Kapiteltext muessen
    beide erscheinen -- die Bilanz ist kein Nebenprodukt des letzten Writes."""
    from academic_vault.server import add_paper, add_quote, chapter_quote_balance

    add_paper(
        db_path=temp_vault_db,
        paper_id="paper-sessions",
        csl_json=json.dumps({"title": "Sessions Paper", "type": "article-journal"}),
    )
    v1 = "Zitat aus der ersten Sitzung mit ausreichender Textlaenge hier."
    v2 = "Zitat aus der zweiten Sitzung mit ausreichender Textlaenge hier."
    q1 = add_quote(
        db_path=temp_vault_db, paper_id="paper-sessions", verbatim=v1, extraction_method="manual"
    )
    q2 = add_quote(
        db_path=temp_vault_db, paper_id="paper-sessions", verbatim=v2, extraction_method="manual"
    )

    chapter = (
        f'## Sitzung 1\nErster Abschnitt: "{v1}" -- Beleg A.\n\n'
        f'## Sitzung 2\nZweiter Abschnitt, spaeter ergaenzt: "{v2}" -- Beleg B.\n'
    )
    chapter_file = tmp_path / "mehrsitzungen.md"
    chapter_file.write_text(chapter, encoding="utf-8")

    # Kein vorheriger Write/Audit -- direkter Abruf nach Vault-Setup.
    balance = chapter_quote_balance(db_path=temp_vault_db, chapter_path=str(chapter_file))

    found_ids = {e["quote_id"] for e in balance["not_audited"]}
    assert found_ids == {q1, q2}
    assert balance["total_quotes"] == 2


# ---------------------------------------------------------------------------
# AC6 -- Doku benennt den Nicht-Beweis explizit
# ---------------------------------------------------------------------------


def test_docstring_states_balance_is_not_a_proof_of_correct_usage():
    content = (REPO_ROOT / "academic_vault" / "server.py").read_text(encoding="utf-8")
    # chapter_quote_balance-Docstring extrahieren.
    start = content.index("def chapter_quote_balance")
    end = content.index("def search_papers", start)
    docstring = content[start:end].lower()
    assert "nicht" in docstring
    assert "beweis" in docstring or "beweist" in docstring
