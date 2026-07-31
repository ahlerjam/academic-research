"""Tests fuer Issue #473 — Transkript-Ingest und Kategorienbildung.

Deckt die Akzeptanzkriterien AC2 (belegfaehige Stellenangabe) und AC3
(material- und theoriegestuetzte Kategorienbildung inkl. dokumentiertem
Vorgehen) ab. Alles Urteilende bleibt Skill-Prosa; hier wird nur der
deterministische Teil geprueft: Segmentierung, Vault-Schreibpfade und das
Rendern der Kodier-Uebersicht.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "skills" / "qualitative-coding" / "scripts" / "transcript_import.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "qualitative_coding" / "interview_01.txt"


def _load_module():
    """Laedt das Skill-Skript als Modul (Skills liegen nicht im Python-Paketpfad)."""
    spec = importlib.util.spec_from_file_location("transcript_import", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"Skript nicht ladbar: {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vault(tmp_path):
    from academic_vault.db import VaultDB

    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    return db_path


# ---------------------------------------------------------------------------
# AC2 — Transkript aufnehmen, Textstelle eindeutig belegbar
# ---------------------------------------------------------------------------


def test_transcript_import_creates_addressable_segments(vault):
    mod = _load_module()
    from academic_vault.db import VaultDB

    result = mod.import_transcript(
        db_path=vault,
        paper_id="interview-01",
        transcript_path=str(FIXTURE),
        title="Interview 01",
    )

    assert result["segments"] == 5, result

    segments = VaultDB(vault).list_transcript_segments("interview-01")
    assert [s["seq"] for s in segments] == [1, 2, 3, 4, 5]
    assert [s["speaker"] for s in segments] == ["I", "B1", "B1", "I", "B1"]
    assert segments[0]["timecode"] == "00:00:12"
    assert segments[2]["timecode"] is None
    assert "Abstimmung im Team" in segments[1]["text"]
    # Sprecherpraefix und Timecode gehoeren in die Metadaten, nicht in den Text.
    assert not segments[0]["text"].startswith("[")
    assert not segments[0]["text"].startswith("I:")


def test_transcript_paper_is_marked_as_primary_material(vault):
    mod = _load_module()
    from academic_vault.db import VaultDB

    mod.import_transcript(
        db_path=vault,
        paper_id="interview-01",
        transcript_path=str(FIXTURE),
        title="Interview 01",
    )
    paper = VaultDB(vault).get_paper("interview-01")
    assert paper is not None
    assert paper["source_kind"] == "primary"


def test_reimport_is_idempotent(vault):
    mod = _load_module()
    from academic_vault.db import VaultDB

    for _ in range(2):
        mod.import_transcript(
            db_path=vault,
            paper_id="interview-01",
            transcript_path=str(FIXTURE),
            title="Interview 01",
        )

    segments = VaultDB(vault).list_transcript_segments("interview-01")
    assert len(segments) == 5, "Zweiter Import hat Duplikate erzeugt"
    assert [s["seq"] for s in segments] == [1, 2, 3, 4, 5]
    assert len({s["segment_id"] for s in segments}) == 5


def test_quote_carries_segment_reference(vault):
    """Ein Zitat aus dem Transkript traegt Transkript-Paper und Stellenangabe."""
    mod = _load_module()
    from academic_vault.db import VaultDB

    mod.import_transcript(
        db_path=vault,
        paper_id="interview-01",
        transcript_path=str(FIXTURE),
        title="Interview 01",
    )
    db = VaultDB(vault)
    segment = db.list_transcript_segments("interview-01")[4]

    db.add_quote(
        quote_id="q-interview-01-5",
        paper_id="interview-01",
        verbatim=segment["text"],
        extraction_method="manual",
        section=f"Abs. {segment['seq']}",
    )
    quote = db.get_quote("q-interview-01-5")
    assert quote is not None
    assert quote["paper_id"] == "interview-01"
    assert quote["section"] == "Abs. 5"
    assert quote["verbatim"] == segment["text"]


# ---------------------------------------------------------------------------
# AC3 — Kategorienbildung material- und theoriegestuetzt, Vorgehen dokumentiert
# ---------------------------------------------------------------------------


def test_coding_origin_accepts_both_and_rejects_other(vault):
    from academic_vault.db import VaultDB

    db = VaultDB(vault)
    db.add_paper(paper_id="interview-01", csl_json=json.dumps({"title": "Interview 01"}))

    db.add_coding(paper_id="interview-01", category="Teamabstimmung", category_origin="induktiv")
    db.add_coding(paper_id="interview-01", category="Autonomie", category_origin="deduktiv")

    with pytest.raises(ValueError) as exc:
        db.add_coding(paper_id="interview-01", category="Sonstiges", category_origin="gemischt")
    assert "category_origin" in str(exc.value)

    rows = db.list_codings(paper_id="interview-01")
    assert sorted(r["category_origin"] for r in rows) == ["deduktiv", "induktiv"]


def test_overview_reports_origin_and_anchor(vault):
    mod = _load_module()
    from academic_vault.db import VaultDB

    mod.import_transcript(
        db_path=vault,
        paper_id="interview-01",
        transcript_path=str(FIXTURE),
        title="Interview 01",
    )
    db = VaultDB(vault)
    segments = db.list_transcript_segments("interview-01")
    db.add_quote(
        quote_id="q-anchor",
        paper_id="interview-01",
        verbatim=segments[4]["text"],
        extraction_method="manual",
        section="Abs. 5",
    )
    db.add_coding(
        paper_id="interview-01",
        category="Teamabstimmung",
        category_origin="induktiv",
        segment_id=segments[4]["segment_id"],
        quote_id="q-anchor",
        memo="Abstimmung wird als hilfreich und zugleich zeitraubend beschrieben.",
    )
    db.add_coding(
        paper_id="interview-01",
        category="Teamabstimmung",
        category_origin="induktiv",
        segment_id=segments[1]["segment_id"],
    )

    report = mod.render_overview(db_path=vault, paper_id="interview-01")

    assert "Teamabstimmung" in report
    assert "induktiv" in report
    assert "2" in report, "Haeufigkeit fehlt in der Uebersicht"
    assert "q-anchor" in report, "Ankerzitat wird ohne pruefbare quote_id ausgegeben"
    assert segments[4]["text"][:30] in report
    # Das Ankerzitat muss im Vault aufloesbar sein.
    assert db.get_quote("q-anchor") is not None


def test_overview_marks_category_without_anchor_quote(vault):
    """Ohne Ankerzitat wird das Fehlen markiert statt eines erfundenen Zitats."""
    mod = _load_module()
    from academic_vault.db import VaultDB

    db = VaultDB(vault)
    db.add_paper(paper_id="interview-01", csl_json=json.dumps({"title": "Interview 01"}))
    db.add_coding(paper_id="interview-01", category="Autonomie", category_origin="deduktiv")

    report = mod.render_overview(db_path=vault, paper_id="interview-01")
    assert "Autonomie" in report
    assert "kein Ankerzitat" in report


def test_procedure_is_recorded_as_decision(vault, tmp_path):
    """Der Kodierleitfaden dokumentiert das Vorgehen als Decision-Log-Eintrag."""
    mod = _load_module()
    from academic_vault.db import VaultDB

    db = VaultDB(vault)
    db.add_paper(paper_id="interview-01", csl_json=json.dumps({"title": "Interview 01"}))
    db.add_coding(paper_id="interview-01", category="Teamabstimmung", category_origin="induktiv")

    out = tmp_path / "empirie" / "kodierleitfaden.md"
    mod.write_codebook(
        db_path=vault,
        paper_id="interview-01",
        output_path=str(out),
        verfahren="Qualitative Inhaltsanalyse nach Mayring (zusammenfassend)",
        abstraktionsniveau="Handlungsroutinen im Arbeitsalltag",
        selektionskriterium="Aussagen zur Zusammenarbeit im Team",
    )

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Teamabstimmung" in text
    assert "induktiv" in text

    decisions = db.list_decisions(category="kodierung")
    assert len(decisions) == 1, decisions
    assert "Mayring" in decisions[0]["text"] + (decisions[0]["rationale"] or "")
    assert "Handlungsroutinen im Arbeitsalltag" in (
        decisions[0]["text"] + (decisions[0]["rationale"] or "")
    )


# ---------------------------------------------------------------------------
# Bestands-Vault: Lesepfade des Skripts duerfen nicht am fehlenden Schema
# scheitern (P1-Regression aus dem Review zu PR #561)
# ---------------------------------------------------------------------------


def _legacy_vault_without_empirical_tables(tmp_path) -> str:
    """Vault, wie er vor #473 angelegt und seither nur gelesen wurde.

    ``papers`` und ``notes_fts`` sind vorhanden -- die beiden Tabellen, an
    denen ``server._ensure_schema_for_read()`` frueher allein festmachte --,
    ``transcript_segments``/``codings`` fehlen.
    """
    import sqlite3

    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE papers ("
            "  paper_id TEXT PRIMARY KEY,"
            "  type TEXT NOT NULL DEFAULT 'article-journal',"
            "  csl_json TEXT NOT NULL,"
            "  added_at INTEGER NOT NULL,"
            "  updated_at INTEGER NOT NULL)"
        )
        conn.execute("CREATE VIRTUAL TABLE notes_fts USING fts5(note_id, text)")
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_overview_on_legacy_vault_reports_empty_instead_of_crashing(tmp_path):
    """``overview`` ist der in SKILL.md dokumentierte Einstieg — auf einem
    Bestands-Vault endete er in ``sqlite3.OperationalError: no such table:
    codings``, statt die vorgesehene Leermeldung auszugeben. Der Lesepfad
    ``collect_categories()`` ging direkt auf ``VaultDB``, also am Guard vorbei,
    den ``server.list_codings()`` mitbringt.
    """
    mod = _load_module()
    db_path = _legacy_vault_without_empirical_tables(tmp_path)

    assert mod.collect_categories(db_path, paper_id=None) == []

    report = mod.render_overview(db_path=db_path, paper_id=None)
    assert "Noch keine Kodierungen" in report
