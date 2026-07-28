"""Regressionstest fuer Issue #455: Vault-Datenintegritaet.

Zwei unabhaengige Fehler:

1. ``VaultDB.add_paper()`` ist ein Upsert (``ON CONFLICT DO UPDATE``), dessen
   ``UPDATE SET``-Klausel bisher ALLE optionalen Spalten unbedingt auf ihre
   Funktions-Defaults (``None``/``0``) zurueckschrieb -- ein zweiter Aufruf
   fuer dieselbe ``paper_id`` ohne z.B. ``pdf_path`` loeschte den zuvor
   gesetzten Wert, statt ihn unangetastet zu lassen. Fix: ein Sentinel
   (``_UNSET``) unterscheidet "nicht uebergeben" von "bewusst geleert" durch
   alle drei Aufrufebenen (``VaultDB.add_paper`` -> ``server.add_paper`` ->
   MCP-Tool-Wrapper ``_vault_add_paper``).
2. Mehrere Lesepfade in ``server.py`` instanziierten ``VaultDB(db_path)``
   ohne ``init_schema()`` aufzurufen (bzw. umgingen ``VaultDB`` komplett via
   ``VaultDB._open()``, siehe ``search_papers()``). Auf einer frischen,
   unbenutzten DB-Datei stuerzte damit der allererste Lesezugriff mit einem
   rohen ``sqlite3.OperationalError`` ab, statt ein leeres Ergebnis zu
   liefern.

Akzeptanzkriterien (Issue #455):
- AC1: Zweiter add_paper()-Aufruf ohne optionale Felder erhaelt Seitenversatz
  (page_offset), PDF-Pfad, ISBN und Herkunft (provenance).
- AC2: Ein bewusst geleertes Feld laesst sich weiterhin explizit leeren.
- AC3: Suche auf frischer, leerer DB liefert [] statt sqlite3.OperationalError.
- AC4: Diese Tests schlagen ohne den Fix fehl (TDD-Nachweis).
"""

import json
import sqlite3

import pytest
from academic_vault import server as vault_server
from academic_vault.db import VaultDB

_CSL_ARTICLE = json.dumps({"type": "article-journal", "title": "Ein Artikel"})
_CSL_CHAPTER = json.dumps({"type": "chapter", "title": "Kapitel 1"})


# ---------------------------------------------------------------------------
# AC1 -- Upsert ohne optionale Felder darf Bestandswerte nicht loeschen
# ---------------------------------------------------------------------------


def test_server_add_paper_repeat_call_preserves_page_offset_pdf_isbn_provenance(
    temp_vault_db,
):
    """Zweiter add_paper()-Aufruf ohne optionale Felder behaelt page_offset,
    pdf_path, isbn und provenance des ersten Aufrufs (Issue #455, AC1)."""
    db_path = temp_vault_db
    paper_id = "upsert-preserve-2024"

    vault_server.add_paper(
        db_path,
        paper_id,
        _CSL_ARTICLE,
        page_offset=12,
        pdf_path="a.pdf",
        isbn="978-3-16-148410-0",
        provenance="oa",
    )

    # Zweiter Aufruf: nur paper_id + csl_json, alle optionalen Felder weggelassen.
    vault_server.add_paper(db_path, paper_id, _CSL_ARTICLE)

    paper = vault_server.get_paper(db_path, paper_id)
    assert paper is not None
    assert paper["page_offset"] == 12, "page_offset wurde faelschlich zurueckgesetzt"
    assert paper["pdf_path"] == "a.pdf", "pdf_path wurde faelschlich geloescht"
    assert paper["isbn"] == "978-3-16-148410-0", "isbn wurde faelschlich geloescht"
    assert paper["provenance"] == "oa", "provenance wurde faelschlich geloescht"


def test_db_add_paper_repeat_call_preserves_all_optional_columns(temp_vault_db):
    """DB-Ebene: alle optionalen Spalten (nicht nur die vier aus AC1) bleiben
    bei einem Upsert ohne diese Felder unveraendert."""
    db_path = temp_vault_db
    db = VaultDB(db_path)
    db.init_schema()
    paper_id = "upsert-preserve-all-2024"

    db.add_paper(
        paper_id,
        _CSL_ARTICLE,
        doi="10.1234/test",
        isbn="978-0-13-468599-1",
        pdf_path="b.pdf",
        page_offset=7,
        editor="Editor Name",
        chapter="3",
        page_first=10,
        page_last=20,
        container_title="Sammelband",
        parent_paper_id=None,
        provenance="scihub",
    )

    # Upsert nur mit den beiden Pflichtparametern.
    db.add_paper(paper_id, _CSL_ARTICLE)

    paper = db.get_paper(paper_id)
    assert paper is not None
    assert paper["doi"] == "10.1234/test"
    assert paper["isbn"] == "978-0-13-468599-1"
    assert paper["pdf_path"] == "b.pdf"
    assert paper["page_offset"] == 7
    assert paper["editor"] == "Editor Name"
    assert paper["chapter"] == "3"
    assert paper["page_first"] == 10
    assert paper["page_last"] == 20
    assert paper["container_title"] == "Sammelband"
    assert paper["provenance"] == "scihub"
    # type + csl_json werden dagegen IMMER aktualisiert (kein optionales Feld).
    assert paper["csl_json"] == _CSL_ARTICLE


# ---------------------------------------------------------------------------
# AC2 -- bewusst geleertes Feld muss weiterhin leerbar sein
# ---------------------------------------------------------------------------


def test_server_add_paper_explicit_none_clears_pdf_path(temp_vault_db):
    """Explizit uebergebenes pdf_path=None loescht den Wert weiterhin
    (Issue #455, AC2) -- Sentinel darf nur "nicht uebergeben" abfangen."""
    db_path = temp_vault_db
    paper_id = "explicit-clear-2024"

    vault_server.add_paper(db_path, paper_id, _CSL_ARTICLE, pdf_path="a.pdf")
    assert vault_server.get_paper(db_path, paper_id)["pdf_path"] == "a.pdf"

    vault_server.add_paper(db_path, paper_id, _CSL_ARTICLE, pdf_path=None)

    paper = vault_server.get_paper(db_path, paper_id)
    assert paper["pdf_path"] is None, "explizites pdf_path=None muss weiterhin leeren"


def test_db_add_paper_explicit_zero_clears_page_offset(temp_vault_db):
    """Explizit uebergebenes page_offset=0 setzt den Wert weiterhin auf 0,
    auch wenn zuvor ein anderer Wert gesetzt war."""
    db_path = temp_vault_db
    db = VaultDB(db_path)
    db.init_schema()
    paper_id = "explicit-zero-2024"

    db.add_paper(paper_id, _CSL_ARTICLE, page_offset=12)
    assert db.get_paper(paper_id)["page_offset"] == 12

    db.add_paper(paper_id, _CSL_ARTICLE, page_offset=0)

    assert db.get_paper(paper_id)["page_offset"] == 0


# ---------------------------------------------------------------------------
# AC3 -- Lesezugriff auf frischer, unbenutzter DB darf nicht crashen
# ---------------------------------------------------------------------------


def test_search_papers_on_fresh_uninitialized_db_returns_empty_list(tmp_path):
    """vault.search auf einer frisch angelegten, NIE angefassten DB-Datei
    liefert [] statt sqlite3.OperationalError (Issue #455, AC3).

    Bewusst KEIN init_schema()- oder sonstiger Vault-Aufruf vor der Suche --
    der Pfad zeigt lediglich auf eine Datei, die noch nicht existiert.
    """
    db_path = str(tmp_path / "brand_new_vault.db")

    result = vault_server.search_papers(db_path, "query")

    assert result == []


def test_get_paper_on_fresh_uninitialized_db_returns_none(tmp_path):
    """vault.get_paper auf frischer DB liefert None statt OperationalError."""
    db_path = str(tmp_path / "brand_new_vault_2.db")

    result = vault_server.get_paper(db_path, "irgendeine-id")

    assert result is None


def test_find_quotes_on_fresh_uninitialized_db_returns_empty_list(tmp_path):
    """vault.find_quotes auf frischer DB liefert [] statt OperationalError."""
    db_path = str(tmp_path / "brand_new_vault_3.db")

    result = vault_server.find_quotes(db_path, "irgendeine-id")

    assert result == []


def test_add_paper_on_fresh_db_path_still_works_end_to_end(tmp_path):
    """Sanity-Check: der eigentliche Schreibpfad auf einer frischen DB-Datei
    funktioniert unveraendert (kein Kollateralschaden durch den Fix)."""
    db_path = str(tmp_path / "brand_new_vault_4.db")

    vault_server.add_paper(db_path, "fresh-write-2024", _CSL_ARTICLE)

    assert vault_server.get_paper(db_path, "fresh-write-2024") is not None


# ---------------------------------------------------------------------------
# Plan-Risikonotiz: add_chapter() reicht schon heute nur eine Teilmenge der
# Felder an add_paper() durch -- nach dem Fix bleiben zuvor gesetzte Felder
# (doi/provenance) bei einem Kapitel-Update automatisch erhalten.
# ---------------------------------------------------------------------------


def test_add_chapter_repeat_call_preserves_fields_set_via_add_paper(temp_vault_db):
    """add_chapter() ruft add_paper() nur mit chapter/page_first/page_last/
    parent_paper_id/pdf_path auf. doi/provenance, die zuvor direkt via
    add_paper() gesetzt wurden, muessen einen add_chapter()-Folgeaufruf
    ueberleben (kein Rueckfall in altes Verhalten bei kuenftigen Refactors)."""
    db_path = temp_vault_db
    paper_id = "buch-kapitel-1"

    # Eltern-Buch muss existieren -- parent_paper_id ist ein FOREIGN KEY auf
    # papers.paper_id (schema.sql) und PRAGMA foreign_keys=ON ist aktiv.
    vault_server.add_paper(db_path, "buch", json.dumps({"type": "book", "title": "Das Buch"}))
    vault_server.add_paper(
        db_path,
        paper_id,
        _CSL_CHAPTER,
        doi="10.9999/kapitel",
        provenance="oa",
    )

    returned_id = vault_server.add_chapter(
        db_path,
        parent_paper_id="buch",
        chapter_number=1,
        csl_json=_CSL_CHAPTER,
        paper_id=paper_id,
        page_first=1,
        page_last=15,
    )

    assert returned_id == paper_id
    paper = vault_server.get_paper(db_path, paper_id)
    assert paper["doi"] == "10.9999/kapitel", "doi haette den Kapitel-Update ueberleben muessen"
    assert paper["provenance"] == "oa", "provenance haette den Kapitel-Update ueberleben muessen"
    assert paper["page_first"] == 1
    assert paper["page_last"] == 15


# ---------------------------------------------------------------------------
# MCP-Tool-Ebene: Sentinel muss auch durch den FastMCP-Wrapper durchgereicht
# werden, sonst geht die Unterscheidung auf der letzten Zwischenschicht
# verloren (Plan-Risikonotiz).
# ---------------------------------------------------------------------------


def test_vault_add_paper_mcp_tool_preserves_fields_when_omitted(temp_vault_db):
    """vault.add_paper (MCP-Tool) ohne optionale Felder loescht sie nicht."""
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio
    import importlib

    server_module = importlib.import_module("academic_vault.server")

    db_path = temp_vault_db
    paper_id = "mcp-upsert-preserve-2024"
    # server._DEFAULT_DB muss VOR _build_mcp_server() umgebogen werden: die
    # registrierten Tool-Closures lesen `db_path = _DEFAULT_DB` einmalig beim
    # Bau des Servers, nicht bei jedem Aufruf.
    server_module._DEFAULT_DB = db_path
    mcp_server = server_module._build_mcp_server()
    assert mcp_server is not None

    async def _call(name: str, args: dict):
        return await mcp_server.call_tool(name, args)

    asyncio.run(
        _call(
            "vault.add_paper",
            {
                "paper_id": paper_id,
                "csl_json": _CSL_ARTICLE,
                "provenance": "oa",
                "isbn": "978-3-16-148410-0",
            },
        )
    )
    asyncio.run(_call("vault.add_paper", {"paper_id": paper_id, "csl_json": _CSL_ARTICLE}))

    paper = vault_server.get_paper(db_path, paper_id)
    assert paper["provenance"] == "oa"
    assert paper["isbn"] == "978-3-16-148410-0"


def test_sqlite_operational_error_would_have_been_raised_without_fix():
    """Dokumentiert das urspruengliche Fehlerbild (#455, AC3-Kontext):
    eine raw sqlite3-Query gegen eine Tabelle, die noch nicht existiert,
    wirft tatsaechlich sqlite3.OperationalError -- server.search_papers()
    faengt genau das ab, indem es init_schema() vorschaltet."""
    with pytest.raises(sqlite3.OperationalError):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("SELECT * FROM papers_fts WHERE papers_fts MATCH ?", ("x",))
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Review-Fund PR #478 (P1, Performance): die neun reinen Lesepfade in
# server.py (get_paper, search_papers, get_quote, search_quote_text,
# find_quotes, get_figure, list_figures, find_figure_by_caption,
# get_printed_page) riefen bislang unbedingt ``VaultDB.init_schema()`` auf.
# schema.sql enthaelt bewusst unbedingte DROP TRIGGER + CREATE TRIGGER-Paare
# (siehe Kommentar dort) -- ``init_schema()`` selbst muss diese fuer Schreib-
# pfade (add_paper, add_quote, ...) unbedingt ausfuehren koennen, damit
# Bestands-Drift (z.B. per Test/extern veraenderte Trigger, Issue #373)
# weiterhin repariert wird. ``_ensure_schema_for_read()`` verlagert den Guard
# deshalb auf die Lesepfade selbst: ein billiger sqlite_master-Check statt
# eines vollen init_schema()-Laufs, sobald die DB bereits eine
# ``papers``-Tabelle hat.
# ---------------------------------------------------------------------------


def test_server_get_paper_repeat_call_does_not_rerun_ddl(temp_vault_db):
    """Zweiter ``vault_server.get_paper()``-Aufruf auf einer bereits
    initialisierten DB darf kein DDL (u.a. DROP+CREATE TRIGGER) mehr
    ausloesen. `PRAGMA schema_version` steigt bei JEDER Schema-Aenderung --
    bleibt er stabil, lief kein DDL erneut."""
    db_path = temp_vault_db  # Fixture hat init_schema() bereits einmal gerufen
    vault_server.add_paper(db_path, "read-hotpath-2024", _CSL_ARTICLE)

    with sqlite3.connect(db_path) as conn:
        schema_version_before = conn.execute("PRAGMA schema_version").fetchone()[0]

    vault_server.get_paper(db_path, "read-hotpath-2024")

    with sqlite3.connect(db_path) as conn:
        schema_version_after = conn.execute("PRAGMA schema_version").fetchone()[0]

    assert schema_version_after == schema_version_before, (
        "vault_server.get_paper() hat auf einer bereits initialisierten DB "
        "erneut DDL ausgefuehrt statt nur einen billigen Read zu machen "
        "(Review-Fund P1 zu PR #478)."
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda db_path: vault_server.get_paper(db_path, "read-hotpath-2024"),
        lambda db_path: vault_server.search_papers(db_path, "hotpath"),
        lambda db_path: vault_server.get_quote(db_path, "does-not-exist"),
        lambda db_path: vault_server.search_quote_text(db_path, "hotpath"),
        lambda db_path: vault_server.find_quotes(db_path, "read-hotpath-2024"),
        lambda db_path: vault_server.get_figure(db_path, "does-not-exist"),
        lambda db_path: vault_server.list_figures(db_path, "read-hotpath-2024"),
        lambda db_path: vault_server.find_figure_by_caption(db_path, "Abb. 1"),
        lambda db_path: vault_server.get_printed_page(db_path, "read-hotpath-2024", 5),
    ],
    ids=[
        "get_paper",
        "search_papers",
        "get_quote",
        "search_quote_text",
        "find_quotes",
        "get_figure",
        "list_figures",
        "find_figure_by_caption",
        "get_printed_page",
    ],
)
def test_server_read_paths_do_not_rerun_ddl_on_initialized_db(temp_vault_db, call):
    """Alle neun in PR #478 P1 genannten Lesepfade: kein DDL-Rerun auf einer
    bereits initialisierten DB (Review-Fund P1, konkrete Liste der
    betroffenen Zeilen aus dem Sticky-Comment)."""
    db_path = temp_vault_db  # Fixture hat init_schema() bereits einmal gerufen
    vault_server.add_paper(db_path, "read-hotpath-2024", _CSL_ARTICLE)

    with sqlite3.connect(db_path) as conn:
        schema_version_before = conn.execute("PRAGMA schema_version").fetchone()[0]

    call(db_path)

    with sqlite3.connect(db_path) as conn:
        schema_version_after = conn.execute("PRAGMA schema_version").fetchone()[0]

    assert schema_version_after == schema_version_before, (
        "Lesepfad hat auf einer bereits initialisierten DB erneut DDL "
        "ausgefuehrt statt nur einen billigen Read zu machen "
        "(Review-Fund P1 zu PR #478)."
    )


def test_server_get_paper_on_fresh_db_still_initializes_schema(tmp_path):
    """Gegenprobe zu AC3: der neue Guard darf die Fresh-DB-Reparatur aus
    #455 nicht regressieren -- eine wirklich frische, leere DB-Datei muss
    weiterhin transparent initialisiert werden statt zu crashen."""
    db_path = str(tmp_path / "fresh.db")
    assert vault_server.get_paper(db_path, "irrelevant") is None


def test_write_paths_still_call_init_schema_unconditionally_for_repair(temp_vault_db):
    """Schreibpfade (hier: add_quote) muessen weiterhin unbedingt
    ``init_schema()`` aufrufen, damit Bestands-Drift reparierbar bleibt --
    der P1-Fix darf nur die reinen Lesepfade betreffen (Review-Fund P1 zu
    PR #478, Abgrenzung zur Reparatur-Semantik aus Issue #373)."""
    db_path = temp_vault_db
    vault_server.add_paper(db_path, "write-path-2024", _CSL_ARTICLE)

    # Trigger papers_ai auf einen kaputten (pre-#373) Stand zuruecksetzen,
    # analog zu tests/test_issue_373_fulltext.py::_downgrade_to_legacy_schema.
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            DROP TRIGGER IF EXISTS papers_ai;
            CREATE TRIGGER papers_ai AFTER INSERT ON papers BEGIN
              INSERT INTO papers_fts(paper_id, title, abstract, fulltext)
              VALUES (new.paper_id, json_extract(new.csl_json, '$.title'),
                      json_extract(new.csl_json, '$.abstract'), NULL);
            END;
        """)
        conn.commit()

    # add_quote() ruft init_schema() unbedingt auf und muss den Trigger
    # dabei reparieren (DROP+CREATE aus dem aktuellen schema.sql).
    vault_server.add_quote(db_path, "write-path-2024", "Zitat", "manual")

    with sqlite3.connect(db_path) as conn:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='papers_ai'"
        ).fetchone()[0]

    assert "paper_fulltext" in trigger_sql, (
        "add_quote() hat den (kuenstlich zurueckgesetzten) Trigger papers_ai "
        "nicht repariert -- Schreibpfade muessen weiterhin unbedingt "
        "init_schema() aufrufen (Review-Fund P1 zu PR #478 betrifft nur "
        "Lesepfade)."
    )
