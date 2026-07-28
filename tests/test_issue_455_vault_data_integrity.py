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
