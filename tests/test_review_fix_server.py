"""Regressionstests zu den Review-Funden in ``academic_vault/server.py``.

Abgedeckt werden vier unabhaengige Fehlerbilder:

* **Fund 2** — ``verify_citations()`` war der einzige Lesepfad ohne
  ``_ensure_schema_for_read()``. Auf einer frischen, schemalosen ``vault.db``
  flog ``sqlite3.OperationalError: no such table: papers`` — und
  ``hooks/verbatim-guard.mjs`` wertet den Nicht-Null-Exit als
  "unavailable" (fail-open), statt erfundene Belege zu blocken.
* **Fund 3** — ``add_quote()`` ersetzte bei ``extraction_method='local-verbatim'``
  die uebergebene ``pdf_page`` durch die verifizierte, liess ``printed_page``
  aber stehen. Ergebnis: ein Zitat, dessen gedruckte Seite nicht zu seiner
  PDF-Seite passt — und damit ein spaeterer, KORREKTER Klammerbeleg, den der
  verbatim-guard als ``page-mismatch`` hart blockt.
* **Fund 8** — ``restore_snapshot()`` entpackte das ``vault.db``-Member ins
  Arbeitsverzeichnis, waehrend der Server den Vault ausschliesslich unter
  ``VAULT_DB_PATH``/``~/.academic-research/projects/<slug>/vault.db`` liest.
  Der Rollback lief ins Leere und meldete trotzdem Erfolg. Nachtrag zum
  Fix (Datenverlust-Vorfall 11.08.2026, s. eigener Abschnitt am Dateiende):
  ohne ausdruecklichen ``db_path`` wird gar keine DB mehr geschrieben.
* **Fund 13** — ``check_retractions()`` verdrahtete das Kapitelverzeichnis fest
  auf ``kapitel`` und ignorierte ``ACADEMIC_CHAPTER_DIR`` (das
  ``hooks/lib/protected-path.mjs`` und die Doku sehr wohl kennen).

Dazu die Server-Seite von **Fund 10**: der Schreibpfad ``set_page_offset()``
muss ueber die gesperrte ``VaultDB``-Methode laufen und einen
``VaultLockedError`` unveraendert nach oben durchreichen.
"""

import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest
from academic_vault import retraction as _retraction
from academic_vault.db import VaultDB, VaultLockedError
from academic_vault.server import (
    add_paper,
    add_quote,
    check_retractions,
    export_snapshot,
    get_paper,
    get_quote,
    lock_passport,
    restore_snapshot,
    set_ocr_done,
    set_page_offset,
    update_pdf_path,
    verify_citation,
    verify_citations,
)

# ---------------------------------------------------------------------------
# Fund 2 — verify_citations auf schemaloser DB
# ---------------------------------------------------------------------------


def _leere_db_datei(tmp_path: Path) -> str:
    """Legt eine existierende, aber voellig schemalose vault.db an."""
    db_path = tmp_path / "vault.db"
    sqlite3.connect(str(db_path)).close()
    assert db_path.exists()
    return str(db_path)


def test_verify_citations_auf_schemaloser_db_liefert_no_match(tmp_path):
    """Fund 2: frische vault.db -> sauberes 'no-match' statt OperationalError."""
    db_path = _leere_db_datei(tmp_path)

    ergebnis = verify_citations(db_path, [{"family": "Mueller", "year": 2021, "page": 45}])

    assert ergebnis == [{"status": "no-match", "paper_ids": []}]


def test_verify_citation_auf_schemaloser_db_liefert_no_match(tmp_path):
    """Fund 2: derselbe Schutz gilt fuer den Ein-Item-Wrapper (Hook-Aufrufer)."""
    db_path = _leere_db_datei(tmp_path)

    assert verify_citation(db_path, "Mueller", 2021, 45) == {
        "status": "no-match",
        "paper_ids": [],
    }


def test_verify_citations_legt_lesbares_schema_an(tmp_path):
    """Fund 2: nach dem Aufruf ist die DB nutzbar (papers-Tabelle vorhanden)."""
    db_path = _leere_db_datei(tmp_path)

    verify_citations(db_path, [])

    conn = sqlite3.connect(db_path)
    try:
        namen = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "papers" in namen


# ---------------------------------------------------------------------------
# Fund 3 — printed_page folgt der verifizierten pdf_page
# ---------------------------------------------------------------------------

_CSL_ARTIKEL = json.dumps(
    {
        "type": "article-journal",
        "title": "DevOps-Governance",
        "author": [{"family": "Müller", "given": "Anna"}],
        "issued": {"date-parts": [[2021]]},
    }
)


@pytest.fixture
def paper_mit_offset(temp_vault_db):
    """Paper 'p1' mit page_offset=12 (pdf_page 57 == gedruckte Seite 45)."""
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL, page_offset=12)
    return temp_vault_db


def _fake_verifikation(monkeypatch, verifizierte_seite: int) -> None:
    """Ersetzt die PDF-Verifikation durch eine feste, abweichende Fundstelle."""
    import academic_vault.server as server

    def _stub(db_path, paper_id, verbatim, pdf_page):
        return verbatim, verifizierte_seite

    monkeypatch.setattr(server, "_verify_local_verbatim", _stub)


def test_add_quote_korrigiert_printed_page_mit_der_verifizierten_seite(
    monkeypatch, paper_mit_offset
):
    """Fund 3: verifizierte pdf_page=59 -> printed_page 47, nicht das alte 45."""
    _fake_verifikation(monkeypatch, 59)

    quote_id = add_quote(
        paper_mit_offset,
        paper_id="p1",
        verbatim="Governance ist kein Werkzeug.",
        extraction_method="local-verbatim",
        pdf_page=57,
        printed_page=45,
    )

    quote = get_quote(paper_mit_offset, quote_id)
    assert quote is not None
    assert quote["pdf_page"] == 59
    assert quote["printed_page"] == 47, (
        "printed_page wurde nicht an die verifizierte pdf_page angepasst — "
        "der Vault haelt eine gedruckte Seite, die nicht zur PDF-Seite passt."
    )


def test_add_quote_laesst_printed_page_bei_passender_seite_unveraendert(
    monkeypatch, paper_mit_offset
):
    """Kein Umrechnen, wenn die verifizierte Seite der uebergebenen entspricht."""
    _fake_verifikation(monkeypatch, 57)

    quote_id = add_quote(
        paper_mit_offset,
        paper_id="p1",
        verbatim="Zitat.",
        extraction_method="local-verbatim",
        pdf_page=57,
        printed_page=45,
    )

    quote = get_quote(paper_mit_offset, quote_id)
    assert quote is not None
    assert quote["pdf_page"] == 57
    assert quote["printed_page"] == 45


def test_add_quote_ohne_printed_page_bleibt_ohne(monkeypatch, paper_mit_offset):
    """Ohne uebergebene printed_page wird auch keine erfunden."""
    _fake_verifikation(monkeypatch, 59)

    quote_id = add_quote(
        paper_mit_offset,
        paper_id="p1",
        verbatim="Zitat ohne gedruckte Seite.",
        extraction_method="local-verbatim",
        pdf_page=57,
    )

    quote = get_quote(paper_mit_offset, quote_id)
    assert quote is not None
    assert quote["pdf_page"] == 59
    assert quote["printed_page"] is None


def test_add_quote_manual_bleibt_unangetastet(temp_vault_db):
    """'manual' wird nicht verifiziert — Seitenangaben bleiben wie uebergeben."""
    add_paper(temp_vault_db, paper_id="p2", csl_json=_CSL_ARTIKEL, page_offset=12)

    quote_id = add_quote(
        temp_vault_db,
        paper_id="p2",
        verbatim="Handbeleg.",
        extraction_method="manual",
        pdf_page=57,
        printed_page=45,
    )

    quote = get_quote(temp_vault_db, quote_id)
    assert quote is not None
    assert (quote["pdf_page"], quote["printed_page"]) == (57, 45)


# ---------------------------------------------------------------------------
# Fund 8 — restore_snapshot rollt den echten Vault zurueck
# ---------------------------------------------------------------------------


def _projekt_mit_snapshot(tmp_path, monkeypatch):
    """Baut Projektordner + echten Vault + Snapshot; gibt (pfade, ts) zurueck."""
    vault_dir = tmp_path / "vault-home"
    vault_dir.mkdir()
    db_path = vault_dir / "vault.db"
    monkeypatch.setenv("VAULT_DB_PATH", str(db_path))

    add_paper(str(db_path), paper_id="p-original", csl_json=_CSL_ARTIKEL)

    project_dir = tmp_path / "projekt"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Original Kontext", encoding="utf-8")

    snapshots_dir = tmp_path / "snapshots"
    tgz = export_snapshot(
        db_path=str(db_path),
        slug="proj",
        project_dir=str(project_dir),
        snapshots_dir=str(snapshots_dir),
    )
    assert tgz is not None
    return db_path, project_dir, snapshots_dir, Path(tgz).stem


def test_restore_snapshot_stellt_den_gelesenen_vault_wieder_her(tmp_path, monkeypatch):
    """Fund 8: der Rollback trifft die DB, die der Server auch liest."""
    db_path, project_dir, snapshots_dir, ts = _projekt_mit_snapshot(tmp_path, monkeypatch)

    # Vault "beschaedigen": das Paper verschwindet.
    conn = VaultDB._open(str(db_path))
    try:
        conn.execute("DELETE FROM papers WHERE paper_id = 'p-original'")
        conn.commit()
    finally:
        conn.close()
    assert get_paper(str(db_path), "p-original") is None

    ergebnis = restore_snapshot(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(project_dir),
        db_path=str(db_path),
    )

    assert ergebnis is True
    assert get_paper(str(db_path), "p-original") is not None, (
        "Der Live-Vault wurde nicht zurueckgerollt — restore_snapshot hat das "
        "vault.db-Member woanders hin entpackt."
    )


def test_restore_snapshot_legt_keine_streu_vault_db_im_projekt_ab(tmp_path, monkeypatch):
    """Fund 8: kein '<project_dir>/vault.db', das nie jemand liest."""
    db_path, project_dir, snapshots_dir, ts = _projekt_mit_snapshot(tmp_path, monkeypatch)

    restore_snapshot(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(project_dir),
        db_path=str(db_path),
    )

    assert not (project_dir / "vault.db").exists(), (
        "vault.db landete im Projektverzeichnis statt am gelesenen db_path."
    )
    assert (project_dir / "academic_context.md").exists()


def test_restore_snapshot_sichert_den_bestehenden_vault_vor_dem_ueberschreiben(
    tmp_path, monkeypatch
):
    """Fund 8: der ueberschriebene Live-Vault wird vorher weggesichert."""
    db_path, project_dir, snapshots_dir, ts = _projekt_mit_snapshot(tmp_path, monkeypatch)

    add_paper(str(db_path), paper_id="p-nur-live", csl_json=_CSL_ARTIKEL)

    restore_snapshot(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(project_dir),
        db_path=str(db_path),
    )

    backups = sorted(db_path.parent.glob("vault.db.*.bak"))
    assert backups, f"Keine Sicherung des ueberschriebenen Vaults in {db_path.parent}"
    assert get_paper(str(backups[-1]), "p-nur-live") is not None, (
        "Die Sicherung enthaelt nicht den Stand von VOR dem Restore."
    )


def test_restore_snapshot_report_nennt_das_wiederhergestellte(tmp_path, monkeypatch):
    """Fund 8: der Tool-Report sagt, was tatsaechlich zurueckgerollt wurde."""
    from academic_vault.server import restore_snapshot_report

    db_path, project_dir, snapshots_dir, ts = _projekt_mit_snapshot(tmp_path, monkeypatch)

    report = restore_snapshot_report(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(project_dir),
        db_path=str(db_path),
    )

    assert report["ok"] is True
    assert "academic_context.md" in report["restored_files"]
    assert report["vault_db_restored"] == str(db_path)
    assert report["vault_db_backup"], "Backup-Pfad fehlt im Report"


def test_restore_snapshot_meldet_false_wenn_nichts_wiederhergestellt_wurde(tmp_path):
    """Fund 8: ein Snapshot ohne Nutzdaten darf kein True melden."""
    import io

    from academic_vault.server import restore_snapshot_report

    snapshots_dir = tmp_path / "snapshots"
    tar_path = snapshots_dir / "leer" / "20990101-0003.tgz"
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(tar_path), "w:gz") as tar:
        nutzlast = b"Keine State-Dateien vorhanden.\n"
        info = tarfile.TarInfo(name="snapshot-empty.txt")
        info.size = len(nutzlast)
        tar.addfile(info, io.BytesIO(nutzlast))

    target = tmp_path / "ziel"
    target.mkdir()

    report = restore_snapshot_report(
        slug="leer",
        ts="20990101-0003",
        snapshots_dir=str(snapshots_dir),
        target_dir=str(target),
        db_path=str(tmp_path / "kein-vault.db"),
    )

    assert report["ok"] is False
    assert (
        restore_snapshot(
            slug="leer",
            ts="20990101-0003",
            snapshots_dir=str(snapshots_dir),
            target_dir=str(target),
            db_path=str(tmp_path / "kein-vault.db"),
        )
        is False
    )


def test_restore_snapshot_ueberschreibt_vault_nicht_ueber_symlink_member(tmp_path):
    """Fund 8: ein als Symlink getarntes vault.db-Member fasst den Vault nicht an."""
    import io

    snapshots_dir = tmp_path / "snapshots"
    tar_path = snapshots_dir / "boese" / "20990101-0004.tgz"
    tar_path.parent.mkdir(parents=True, exist_ok=True)

    ziel = tmp_path / "echte" / "vault.db"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(b"ORIGINAL-VAULT")

    opfer = tmp_path / "geheim.txt"
    opfer.write_text("ORIGINAL-GEHEIM", encoding="utf-8")

    with tarfile.open(str(tar_path), "w:gz") as tar:
        link = tarfile.TarInfo(name="vault.db")
        link.type = tarfile.SYMTYPE
        link.linkname = str(opfer)
        tar.addfile(link)
        nutzlast = b"PWNED"
        info = tarfile.TarInfo(name="academic_context.md")
        info.size = len(nutzlast)
        tar.addfile(info, io.BytesIO(nutzlast))

    target = tmp_path / "ziel2"
    target.mkdir()

    restore_snapshot(
        slug="boese",
        ts="20990101-0004",
        snapshots_dir=str(snapshots_dir),
        target_dir=str(target),
        db_path=str(ziel),
    )

    assert ziel.read_bytes() == b"ORIGINAL-VAULT"
    assert opfer.read_text(encoding="utf-8") == "ORIGINAL-GEHEIM"


# ---------------------------------------------------------------------------
# Fund 13 — ACADEMIC_CHAPTER_DIR wird respektiert
# ---------------------------------------------------------------------------


def _retraction_stub(monkeypatch, status: str = "retracted") -> None:
    """Ersetzt den Crossref-Aufruf (keine Netzwerkzugriffe im Test)."""

    def _stub(doi: str):
        return _retraction.RetractionCheckResult(
            status=status,
            doi=doi,
            source="10.0000/retraction-notice",
        )

    monkeypatch.setattr(_retraction, "check_retraction", _stub)


def _projekt_mit_kapiteltext(tmp_path, ordnername: str) -> Path:
    project_dir = tmp_path / "projekt"
    kapitel = project_dir / ordnername
    kapitel.mkdir(parents=True)
    (kapitel / "03.md").write_text(
        "Wie Müller (2021) zeigt, ist Governance kein Werkzeug.\n", encoding="utf-8"
    )
    return project_dir


def test_check_retractions_honoriert_academic_chapter_dir(tmp_path, monkeypatch, temp_vault_db):
    """Fund 13: mit ACADEMIC_CHAPTER_DIR=manuskript wird dort gesucht."""
    _retraction_stub(monkeypatch)
    monkeypatch.setenv("ACADEMIC_CHAPTER_DIR", "manuskript")
    project_dir = _projekt_mit_kapiteltext(tmp_path, "manuskript")
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL, doi="10.1234/abc")

    ergebnis = check_retractions(temp_vault_db, project_dir=str(project_dir))

    assert len(ergebnis["retracted"]) == 1
    assert ergebnis["retracted"][0]["cited_in_chapter"] is True, (
        "Das zurueckgezogene Paper steht in manuskript/03.md, wird aber als "
        "'nicht zitiert' gemeldet — ACADEMIC_CHAPTER_DIR wurde ignoriert."
    )


def test_check_retractions_default_bleibt_kapitel(tmp_path, monkeypatch, temp_vault_db):
    """Ohne Override bleibt 'kapitel' das Kapitelverzeichnis."""
    _retraction_stub(monkeypatch)
    monkeypatch.delenv("ACADEMIC_CHAPTER_DIR", raising=False)
    project_dir = _projekt_mit_kapiteltext(tmp_path, "kapitel")
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL, doi="10.1234/abc")

    ergebnis = check_retractions(temp_vault_db, project_dir=str(project_dir))

    assert ergebnis["retracted"][0]["cited_in_chapter"] is True


def test_check_retractions_leerer_override_faellt_auf_kapitel_zurueck(
    tmp_path, monkeypatch, temp_vault_db
):
    """Gleiche Semantik wie hooks/lib/protected-path.mjs: '  ' -> Default."""
    _retraction_stub(monkeypatch)
    monkeypatch.setenv("ACADEMIC_CHAPTER_DIR", "   ")
    project_dir = _projekt_mit_kapiteltext(tmp_path, "kapitel")
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL, doi="10.1234/abc")

    ergebnis = check_retractions(temp_vault_db, project_dir=str(project_dir))

    assert ergebnis["retracted"][0]["cited_in_chapter"] is True


# ---------------------------------------------------------------------------
# Fund 10 (Server-Seite) — Passport-Lock wird nicht umgangen
# ---------------------------------------------------------------------------


def test_set_page_offset_laeuft_ueber_die_gesperrte_db_methode(monkeypatch, temp_vault_db):
    """Der Server schreibt page_offset nicht an VaultDB.set_page_offset vorbei."""
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL)
    aufrufe: list[tuple] = []
    original = VaultDB.set_page_offset

    def _spion(self, paper_id, offset):
        aufrufe.append((paper_id, offset))
        return original(self, paper_id, offset)

    monkeypatch.setattr(VaultDB, "set_page_offset", _spion)

    set_page_offset(temp_vault_db, "p1", 12)

    assert aufrufe == [("p1", 12)], (
        "set_page_offset() schreibt an der (lock-geschuetzten) VaultDB-Methode vorbei."
    )


def test_set_page_offset_reicht_vault_locked_error_durch(monkeypatch, temp_vault_db):
    """Ein VaultLockedError der DB-Schicht wird NICHT verschluckt."""
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL)

    def _gesperrt(self, paper_id, offset):
        raise VaultLockedError("Vault ist gesperrt (Testschicht).")

    monkeypatch.setattr(VaultDB, "set_page_offset", _gesperrt)

    with pytest.raises(VaultLockedError):
        set_page_offset(temp_vault_db, "p1", 12)


def test_set_page_offset_auf_gesperrtem_vault_wirft(temp_vault_db):
    """End-to-End: gesperrter Vault -> kein Schreibzugriff mehr (Fund 10).

    Der eigentliche Guard (``_raise_if_locked``) sitzt in ``db.py``; dieser
    Test haelt fest, dass der Server-Schreibpfad ihn nicht umgeht.
    """
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL)
    lock_passport(temp_vault_db, slug="proj")

    with pytest.raises(VaultLockedError):
        set_page_offset(temp_vault_db, "p1", 12)


# ---------------------------------------------------------------------------
# Nachtrag zu Fund 8 — Datenverlust-Vorfall 11.08.2026
#
# Der Fund-8-Fix schrieb das vault.db-Member nach ``db_path or
# default_db_path()`` zurueck. Der ``or``-Zweig hat beim Verifizieren einen
# ECHTEN Vault ueberschrieben: ein Alt-Test rief restore_snapshot() mit einem
# tmp-Tarball, aber ohne db_path und ohne VAULT_DB_PATH auf -- und traf damit
# ~/.academic-research/projects/<slug>/vault.db. Seitdem gilt: ohne
# ausdruecklichen Zielpfad wird die DB gar nicht angefasst.
# ---------------------------------------------------------------------------


def _snapshot_mit_vault_db(tmp_path, quell_db: Path) -> tuple[Path, str]:
    """Baut aus ``quell_db`` einen Snapshot-Tarball; gibt (snapshots_dir, ts)."""
    project_dir = tmp_path / "quelle"
    project_dir.mkdir(exist_ok=True)
    (project_dir / "academic_context.md").write_text("# Original Kontext", encoding="utf-8")

    snapshots_dir = tmp_path / "snapshots"
    tgz = export_snapshot(
        db_path=str(quell_db),
        slug="proj",
        project_dir=str(project_dir),
        snapshots_dir=str(snapshots_dir),
    )
    assert tgz is not None
    with tarfile.open(tgz, "r:gz") as tar:
        assert "vault.db" in tar.getnames(), "Testaufbau: Tarball ohne vault.db-Member"
    return snapshots_dir, Path(tgz).stem


def _default_db_path_als_falle(monkeypatch) -> None:
    """Laesst den Test hart scheitern, wenn der Restore doch wieder raet."""
    import academic_vault.server as server

    def _knallt() -> str:
        raise AssertionError(
            "restore_snapshot_report() hat default_db_path() aufgerufen — der "
            "implizite Fallback auf den echten Vault ist zurueck (Datenverlust-Vorfall)."
        )

    monkeypatch.setattr(server, "default_db_path", _knallt)


def test_restore_ohne_db_path_fasst_keine_vault_db_an(tmp_path, monkeypatch):
    """Ohne expliziten Zielpfad wird NIRGENDWO eine vault.db geschrieben."""
    from academic_vault.server import restore_snapshot_report

    quell_db = tmp_path / "quelle" / "vault.db"
    quell_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(quell_db), paper_id="p-original", csl_json=_CSL_ARTIKEL)
    snapshots_dir, ts = _snapshot_mit_vault_db(tmp_path, quell_db)

    # Was der Restore NICHT anfassen darf, obwohl es der kanonische Default waere:
    verbotenes_ziel = tmp_path / "live" / "vault.db"
    monkeypatch.setenv("VAULT_DB_PATH", str(verbotenes_ziel))
    _default_db_path_als_falle(monkeypatch)

    target = tmp_path / "ziel"
    report = restore_snapshot_report(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(target),
    )

    assert not verbotenes_ziel.exists(), (
        "restore_snapshot_report() hat ohne db_path eine Live-DB geschrieben."
    )
    assert not (target / "vault.db").exists(), (
        "vault.db landete als Streudatei im Zielverzeichnis (Fund 8 zurueck)."
    )
    assert list(tmp_path.rglob("vault.db")) == [quell_db], (
        "Es ist irgendwo eine vault.db entstanden, die es vorher nicht gab."
    )
    assert report["vault_db_restored"] is None
    assert report["vault_db_backup"] is None


def test_restore_ohne_db_path_meldet_das_uebergangene_vault_member(tmp_path, monkeypatch):
    """Kein stiller No-Op: der Report benennt, dass die DB nicht zurueckkam."""
    from academic_vault.server import restore_snapshot_report

    quell_db = tmp_path / "quelle" / "vault.db"
    quell_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(quell_db), paper_id="p-original", csl_json=_CSL_ARTIKEL)
    snapshots_dir, ts = _snapshot_mit_vault_db(tmp_path, quell_db)
    _default_db_path_als_falle(monkeypatch)

    report = restore_snapshot_report(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(tmp_path / "ziel"),
    )

    assert isinstance(report["vault_db_skipped"], str) and report["vault_db_skipped"], (
        "Der Report verschweigt, dass das vault.db-Member uebergangen wurde."
    )
    assert "db_path" in report["vault_db_skipped"]
    # Die State-Dateien kommen trotzdem zurueck.
    assert report["ok"] is True
    assert "academic_context.md" in report["restored_files"]


def test_restore_nur_vault_member_ohne_db_path_meldet_misserfolg(tmp_path, monkeypatch):
    """Enthaelt der Snapshot NUR die DB, ist der uebergangene Restore kein Erfolg."""
    import io

    from academic_vault.server import restore_snapshot_report

    _default_db_path_als_falle(monkeypatch)
    snapshots_dir = tmp_path / "snapshots"
    tar_path = snapshots_dir / "nurdb" / "20990101-0005.tgz"
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(tar_path), "w:gz") as tar:
        nutzlast = b"SQLite format 3\x00"
        info = tarfile.TarInfo(name="vault.db")
        info.size = len(nutzlast)
        tar.addfile(info, io.BytesIO(nutzlast))

    report = restore_snapshot_report(
        slug="nurdb",
        ts="20990101-0005",
        snapshots_dir=str(snapshots_dir),
        target_dir=str(tmp_path / "ziel"),
    )

    assert report["ok"] is False
    assert report["error"] == report["vault_db_skipped"], (
        "Der Fehlertext soll den wahren Grund nennen, nicht 'keine Inhalte'."
    )


def test_restore_mit_explizitem_db_path_stellt_wieder_her_und_sichert(tmp_path, monkeypatch):
    """Mit ausdruecklichem Ziel rollt der Restore die Live-DB wirklich zurueck."""
    from academic_vault.server import restore_snapshot_report

    quell_db = tmp_path / "quelle" / "vault.db"
    quell_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(quell_db), paper_id="p-original", csl_json=_CSL_ARTIKEL)
    snapshots_dir, ts = _snapshot_mit_vault_db(tmp_path, quell_db)
    _default_db_path_als_falle(monkeypatch)

    live_db = tmp_path / "live" / "vault.db"
    live_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(live_db), paper_id="p-nur-live", csl_json=_CSL_ARTIKEL)

    report = restore_snapshot_report(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(tmp_path / "ziel"),
        db_path=str(live_db),
    )

    assert report["ok"] is True
    assert report["vault_db_restored"] == str(live_db)
    assert report["vault_db_skipped"] is None
    assert get_paper(str(live_db), "p-original") is not None
    backup = report["vault_db_backup"]
    assert backup, "Kein Backup des ueberschriebenen Live-Vaults im Report"
    assert get_paper(backup, "p-nur-live") is not None, (
        "Die Sicherung enthaelt nicht den Stand von VOR dem Restore."
    )


def test_db_path_ist_nur_als_schluesselwort_uebergebbar(tmp_path):
    """Ein durchgereichtes 5. Positionsargument darf nie zum DB-Ziel werden."""
    from academic_vault.server import restore_snapshot_report

    with pytest.raises(TypeError):
        restore_snapshot_report(
            "proj",
            "20990101-0009",
            str(tmp_path / "snapshots"),
            str(tmp_path / "ziel"),
            str(tmp_path / "versehentlich.db"),  # type: ignore[misc]
        )
    with pytest.raises(TypeError):
        restore_snapshot(
            "proj",
            "20990101-0009",
            str(tmp_path / "snapshots"),
            str(tmp_path / "ziel"),
            str(tmp_path / "versehentlich.db"),  # type: ignore[misc]
        )


def test_restore_verweigert_dotdot_und_absolute_member(tmp_path):
    """Der Traversal-Guard haelt: '../' und '/'-Member werden abgelehnt."""
    import io

    from academic_vault.server import restore_snapshot_report

    ausbruch = tmp_path / "escaped.txt"
    absolutes_ziel = tmp_path / "absolut.txt"
    absolutes_ziel.write_text("ORIGINAL-ABSOLUT", encoding="utf-8")

    def _tarball(name: str, member_name: str) -> tuple[Path, str]:
        snapshots_dir = tmp_path / "snapshots"
        ts = f"20990101-{name}"
        tar_path = snapshots_dir / name / f"{ts}.tgz"
        tar_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(str(tar_path), "w:gz") as tar:
            nutzlast = b"PWNED"
            info = tarfile.TarInfo(name=member_name)
            info.size = len(nutzlast)
            tar.addfile(info, io.BytesIO(nutzlast))
            harmlos = b"# Kontext\n"
            info2 = tarfile.TarInfo(name="academic_context.md")
            info2.size = len(harmlos)
            tar.addfile(info2, io.BytesIO(harmlos))
        return snapshots_dir, ts

    for name, member_name, erwarteter_fehler in (
        ("0006", "../escaped.txt", "path traversal"),
        ("0007", str(absolutes_ziel), "absolute path not allowed"),
    ):
        snapshots_dir, ts = _tarball(name, member_name)
        target = tmp_path / f"ziel-{name}"
        report = restore_snapshot_report(
            slug=name,
            ts=ts,
            snapshots_dir=str(snapshots_dir),
            target_dir=str(target),
            db_path=str(tmp_path / f"kein-vault-{name}.db"),
        )
        assert report["ok"] is False, f"Boeses Member {member_name!r} wurde akzeptiert."
        assert erwarteter_fehler in report["error"], (
            f"Falscher Ablehnungsgrund fuer {member_name!r}: {report['error']!r}"
        )
        assert not (target / "academic_context.md").exists(), (
            "Es wurde extrahiert, obwohl ein Member abgelehnt gehoert."
        )

    assert not ausbruch.exists(), f"Path-Traversal erfolgreich: {ausbruch}"
    assert absolutes_ziel.read_text(encoding="utf-8") == "ORIGINAL-ABSOLUT", (
        "Absoluter Member-Pfad hat eine Datei ausserhalb des Ziels ueberschrieben."
    )


def test_export_snapshot_ueberschreibt_keinen_gleichnamigen_snapshot(tmp_path, temp_vault_db):
    """Zwei Exporte in derselben Minute duerfen sich nicht gegenseitig loeschen."""
    project_dir = tmp_path / "projekt"
    project_dir.mkdir()
    (project_dir / "academic_context.md").write_text("# Stand A", encoding="utf-8")
    snapshots_dir = tmp_path / "snapshots"

    erster = export_snapshot(
        db_path=temp_vault_db,
        slug="proj",
        project_dir=str(project_dir),
        snapshots_dir=str(snapshots_dir),
    )
    (project_dir / "academic_context.md").write_text("# Stand B", encoding="utf-8")
    zweiter = export_snapshot(
        db_path=temp_vault_db,
        slug="proj",
        project_dir=str(project_dir),
        snapshots_dir=str(snapshots_dir),
    )

    assert erster is not None and zweiter is not None
    assert erster != zweiter, "Der zweite Export hat den ersten Snapshot ueberschrieben."
    assert Path(erster).exists() and Path(zweiter).exists()


# ---------------------------------------------------------------------------
# Runde 2, Regression A — der Lock aus Fund 10 darf check_retractions nicht
# unbrauchbar machen.
#
# ``update_retraction_checked_at()`` ist seit Fund 10 lock-geschuetzt. Der
# einzige Aufrufer (``check_retractions()``) ruft sie fuer JEDES Paper mit
# Crossref-Status 'clean' auf. Nach ``lock_passport()`` — dem normalen
# Endzustand eines abgeschlossenen Material-Passports — flog der erste
# 'clean'-Treffer als ``VaultLockedError`` aus der Pruefung heraus: kein
# Report mehr, auch nicht ueber bereits gefundene Rueckzuege.
# ---------------------------------------------------------------------------


def test_check_retractions_liefert_report_auf_gesperrtem_vault(
    tmp_path, monkeypatch, temp_vault_db
):
    """Regression A: gesperrter Vault -> Pruefung laeuft, statt zu werfen."""
    _retraction_stub(monkeypatch, status="clean")
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL, doi="10.1234/abc")
    lock_passport(temp_vault_db, slug="proj")

    ergebnis = check_retractions(temp_vault_db, project_dir=str(tmp_path))

    assert ergebnis["clean"] == ["p1"]
    assert ergebnis["checked_count"] == 1
    assert ergebnis["error"] == []


def test_check_retractions_meldet_rueckzug_auch_auf_gesperrtem_vault(
    tmp_path, monkeypatch, temp_vault_db
):
    """Regression A: die Rueckzugswarnung ueberlebt einen 'clean'-Treffer davor."""
    add_paper(temp_vault_db, paper_id="p-clean", csl_json=_CSL_ARTIKEL, doi="10.1234/sauber")
    add_paper(temp_vault_db, paper_id="p-weg", csl_json=_CSL_ARTIKEL, doi="10.1234/zurueck")

    def _stub(doi: str):
        return _retraction.RetractionCheckResult(
            status="clean" if doi.endswith("sauber") else "retracted",
            doi=doi,
            source="10.0000/retraction-notice",
        )

    monkeypatch.setattr(_retraction, "check_retraction", _stub)
    lock_passport(temp_vault_db, slug="proj")

    ergebnis = check_retractions(temp_vault_db, project_dir=str(tmp_path))

    assert [e["paper_id"] for e in ergebnis["retracted"]] == ["p-weg"]
    assert ergebnis["clean"] == ["p-clean"]


def test_check_retractions_schreibt_auf_gesperrtem_vault_keinen_zeitstempel(
    tmp_path, monkeypatch, temp_vault_db
):
    """Regression A: die Pruefung laeuft — geschrieben wird trotzdem nichts (Fund 10)."""
    _retraction_stub(monkeypatch, status="clean")
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL, doi="10.1234/abc")
    lock_passport(temp_vault_db, slug="proj")

    check_retractions(temp_vault_db, project_dir=str(tmp_path))

    paper = get_paper(temp_vault_db, "p1")
    assert paper is not None
    assert paper["retraction_checked_at"] is None, (
        "Auf dem gesperrten Vault wurde doch geschrieben — der Lock aus Fund 10 ist umgangen."
    )


def test_check_retractions_schreibt_ohne_lock_weiterhin_den_zeitstempel(
    tmp_path, monkeypatch, temp_vault_db
):
    """Gegenprobe: ohne Lock bleibt das Timestamp-Update erhalten (#604)."""
    _retraction_stub(monkeypatch, status="clean")
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL, doi="10.1234/abc")

    check_retractions(temp_vault_db, project_dir=str(tmp_path))

    paper = get_paper(temp_vault_db, "p1")
    assert paper is not None
    assert paper["retraction_checked_at"] is not None, (
        "Ohne Lock muss der Zeitstempel weiterhin vorruecken, sonst prueft der "
        "naechste Lauf alles erneut gegen Crossref."
    )


def test_echte_schreibpfade_bleiben_auf_gesperrtem_vault_gesperrt(temp_vault_db):
    """Fund 10 bleibt: set_ocr_done/update_pdf_path werfen weiterhin."""
    add_paper(temp_vault_db, paper_id="p1", csl_json=_CSL_ARTIKEL)
    lock_passport(temp_vault_db, slug="proj")

    with pytest.raises(VaultLockedError):
        set_ocr_done(temp_vault_db, "p1", 1)
    with pytest.raises(VaultLockedError):
        update_pdf_path(temp_vault_db, "p1", "/tmp/neu.pdf")
    with pytest.raises(VaultLockedError):
        set_page_offset(temp_vault_db, "p1", 12)


# ---------------------------------------------------------------------------
# Runde 2, Regression B — printed_page-Korrektur greift auch ohne uebergebene
# pdf_page.
#
# ``_verify_local_verbatim()`` liefert IMMER eine verifizierte Seite, auch bei
# ``pdf_page=None``. Der Fund-3-Fix rechnete ``printed_page`` aber nur um, wenn
# eine ``pdf_page`` mituebergeben wurde — der dokumentierte Weg "ich kenne nur
# die gedruckte Seite" speicherte also weiter das inkonsistente Paar.
# ---------------------------------------------------------------------------


def test_add_quote_ohne_pdf_page_korrigiert_printed_page(monkeypatch, paper_mit_offset):
    """Regression B: pdf_page=None, printed_page=45, offset 12, verifiziert 59 -> 47."""
    _fake_verifikation(monkeypatch, 59)

    quote_id = add_quote(
        paper_mit_offset,
        paper_id="p1",
        verbatim="Governance ist kein Werkzeug.",
        extraction_method="local-verbatim",
        pdf_page=None,
        printed_page=45,
    )

    quote = get_quote(paper_mit_offset, quote_id)
    assert quote is not None
    assert quote["pdf_page"] == 59
    assert quote["printed_page"] == 47, (
        "printed_page=45 gehoerte laut hinterlegtem page_offset zu pdf_page=57, "
        "das Zitat steht aber auf der verifizierten Seite 59 — die gedruckte "
        "Seite haette mitwandern muessen."
    )


def test_add_quote_ohne_pdf_page_laesst_stimmige_printed_page_stehen(monkeypatch, paper_mit_offset):
    """Passt printed_page zur verifizierten Seite, wird nicht angefasst."""
    _fake_verifikation(monkeypatch, 59)

    quote_id = add_quote(
        paper_mit_offset,
        paper_id="p1",
        verbatim="Stimmige Seite.",
        extraction_method="local-verbatim",
        printed_page=47,
    )

    quote = get_quote(paper_mit_offset, quote_id)
    assert quote is not None
    assert (quote["pdf_page"], quote["printed_page"]) == (59, 47)


def test_add_quote_ohne_offset_erfindet_keine_gedruckte_seite(monkeypatch, temp_vault_db):
    """Ohne hinterlegten page_offset gibt es keine Umrechnungsregel — kein Raten."""
    add_paper(temp_vault_db, paper_id="p-ohne-offset", csl_json=_CSL_ARTIKEL)
    _fake_verifikation(monkeypatch, 59)

    quote_id = add_quote(
        temp_vault_db,
        paper_id="p-ohne-offset",
        verbatim="Nur die Buchseite bekannt.",
        extraction_method="local-verbatim",
        printed_page=45,
    )

    quote = get_quote(temp_vault_db, quote_id)
    assert quote is not None
    assert quote["pdf_page"] == 59
    assert quote["printed_page"] == 45, (
        "Ohne page_offset wurde die vom Nutzer genannte Buchseite durch die "
        "PDF-Seite ersetzt — das ist geraten, nicht gerechnet."
    )


def test_add_quote_ohne_offset_nutzt_die_uebergebene_seitenzuordnung(monkeypatch, temp_vault_db):
    """Ohne page_offset liefert das uebergebene Paar (pdf 57 / gedruckt 45) die Regel."""
    add_paper(temp_vault_db, paper_id="p-ohne-offset", csl_json=_CSL_ARTIKEL)
    _fake_verifikation(monkeypatch, 59)

    quote_id = add_quote(
        temp_vault_db,
        paper_id="p-ohne-offset",
        verbatim="Beide Seiten genannt.",
        extraction_method="local-verbatim",
        pdf_page=57,
        printed_page=45,
    )

    quote = get_quote(temp_vault_db, quote_id)
    assert quote is not None
    assert quote["pdf_page"] == 59
    assert quote["printed_page"] == 47, (
        "Der Nutzer hat mit (pdf 57 / gedruckt 45) selbst einen Versatz von 12 "
        "genannt; die um zwei Seiten verschobene Fundstelle ist gedruckte Seite 47."
    )


def test_add_quote_verwirft_printed_page_vor_dem_textbeginn(monkeypatch, paper_mit_offset):
    """Rechnet die Korrektur unter Seite 1, wird keine gedruckte Seite behauptet."""
    _fake_verifikation(monkeypatch, 5)

    quote_id = add_quote(
        paper_mit_offset,
        paper_id="p1",
        verbatim="Vorspann.",
        extraction_method="local-verbatim",
        pdf_page=57,
        printed_page=45,
    )

    quote = get_quote(paper_mit_offset, quote_id)
    assert quote is not None
    assert quote["pdf_page"] == 5
    assert quote["printed_page"] is None


# ---------------------------------------------------------------------------
# Runde 2, Regression C — ein FEHLGESCHLAGENER Restore darf den Ausgangszustand
# nicht anfassen.
#
# ``_backup_live_vault()`` legte die WAL-/SHM-Beidateien beiseite, BEVOR die
# neue DB geschrieben war. Brach das Schreiben danach ab (korruptes Tarball,
# Platte voll), meldete der Report ``ok=False`` — die Live-DB lag aber ohne
# ihr WAL da, und alle dort committeten, noch nicht gecheckpointeten
# Transaktionen waren aus Nutzersicht weg.
# ---------------------------------------------------------------------------


def _live_vault_mit_wal(tmp_path) -> tuple[Path, sqlite3.Connection]:
    """Live-Vault mit echtem, offenem WAL. Rueckgabe: (db_pfad, offene Verbindung).

    Die Verbindung bleibt bewusst offen: SQLite checkpointet erst, wenn die
    LETZTE Verbindung schliesst — nur so existiert waehrend des Restores ein
    ``vault.db-wal`` mit Inhalt, der noch nicht in der Hauptdatei steht.
    """
    live_db = tmp_path / "live" / "vault.db"
    live_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(live_db), paper_id="p-live", csl_json=_CSL_ARTIKEL)

    conn = sqlite3.connect(str(live_db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("UPDATE papers SET updated_at = 424242 WHERE paper_id = 'p-live'")
    conn.commit()
    assert live_db.with_name("vault.db-wal").exists(), "Testaufbau: kein WAL entstanden"
    return live_db, conn


def _extractfile_bricht_ab(monkeypatch) -> None:
    """Laesst das Lesen des vault.db-Members mittendrin scheitern (Platte voll)."""

    class _AbbruchDatei:
        def read(self, *_args):
            raise OSError(28, "No space left on device")

        def close(self) -> None:
            pass

    original = tarfile.TarFile.extractfile

    def _stub(self, member):
        name = getattr(member, "name", member)
        if name == "vault.db":
            return _AbbruchDatei()
        return original(self, member)

    monkeypatch.setattr(tarfile.TarFile, "extractfile", _stub)


def test_fehlgeschlagener_restore_laesst_wal_daten_unangetastet(tmp_path, monkeypatch):
    """Regression C: abgebrochener Restore -> WAL-Stand bleibt lesbar."""
    from academic_vault.server import restore_snapshot_report

    quell_db = tmp_path / "quelle" / "vault.db"
    quell_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(quell_db), paper_id="p-original", csl_json=_CSL_ARTIKEL)
    snapshots_dir, ts = _snapshot_mit_vault_db(tmp_path, quell_db)

    live_db, conn = _live_vault_mit_wal(tmp_path)
    vorher = {p.name: p.read_bytes() for p in live_db.parent.iterdir()}
    _extractfile_bricht_ab(monkeypatch)

    try:
        report = restore_snapshot_report(
            slug="proj",
            ts=ts,
            snapshots_dir=str(snapshots_dir),
            target_dir=str(tmp_path / "ziel"),
            db_path=str(live_db),
        )
        assert report["ok"] is False
        assert live_db.with_name("vault.db-wal").exists(), (
            "Der fehlgeschlagene Restore hat das WAL der Live-DB beiseitegelegt."
        )
        nachher = {p.name: p.read_bytes() for p in live_db.parent.iterdir()}
        assert set(nachher) == set(vorher), (
            f"Der fehlgeschlagene Restore hat den Dateibestand veraendert: "
            f"{sorted(set(nachher) ^ set(vorher))}"
        )
    finally:
        conn.close()

    # Erst nach dem Schliessen checkpointet SQLite — der WAL-Stand muss da sein.
    paper = get_paper(str(live_db), "p-live")
    assert paper is not None and paper["updated_at"] == 424242, (
        "Die im WAL committete Transaktion ist verloren, obwohl der Restore als "
        "fehlgeschlagen gemeldet wurde."
    )


def test_fehlgeschlagener_restore_laesst_keine_restore_tmp_zurueck(tmp_path, monkeypatch):
    """Kein halbfertiges ``vault.db.restore-tmp`` als Streudatei."""
    from academic_vault.server import restore_snapshot_report

    quell_db = tmp_path / "quelle" / "vault.db"
    quell_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(quell_db), paper_id="p-original", csl_json=_CSL_ARTIKEL)
    snapshots_dir, ts = _snapshot_mit_vault_db(tmp_path, quell_db)

    live_db = tmp_path / "live2" / "vault.db"
    live_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(live_db), paper_id="p-live", csl_json=_CSL_ARTIKEL)
    _extractfile_bricht_ab(monkeypatch)

    report = restore_snapshot_report(
        slug="proj",
        ts=ts,
        snapshots_dir=str(snapshots_dir),
        target_dir=str(tmp_path / "ziel2"),
        db_path=str(live_db),
    )

    assert report["ok"] is False
    assert not live_db.with_name("vault.db.restore-tmp").exists()
    assert get_paper(str(live_db), "p-live") is not None, "Die Live-DB wurde beschaedigt."
    assert get_paper(str(live_db), "p-original") is None, (
        "Es wurde etwas zurueckgespielt, obwohl der Restore fehlgeschlagen ist."
    )


def test_erfolgreicher_restore_legt_wal_und_shm_beiseite(tmp_path, monkeypatch):
    """Gegenprobe: beim ERFOLG gehoert das alte WAL weiterhin beiseitegelegt."""
    from academic_vault.server import restore_snapshot_report

    quell_db = tmp_path / "quelle" / "vault.db"
    quell_db.parent.mkdir(parents=True, exist_ok=True)
    add_paper(str(quell_db), paper_id="p-original", csl_json=_CSL_ARTIKEL)
    snapshots_dir, ts = _snapshot_mit_vault_db(tmp_path, quell_db)

    live_db, conn = _live_vault_mit_wal(tmp_path)
    try:
        report = restore_snapshot_report(
            slug="proj",
            ts=ts,
            snapshots_dir=str(snapshots_dir),
            target_dir=str(tmp_path / "ziel3"),
            db_path=str(live_db),
        )
    finally:
        conn.close()

    assert report["ok"] is True
    assert report["vault_db_restored"] == str(live_db)
    assert not live_db.with_name("vault.db-wal").exists(), (
        "Das WAL der ALTEN DB liegt noch neben der zurueckgespielten Datei."
    )
    assert not live_db.with_name("vault.db-shm").exists()
    backup = report["vault_db_backup"]
    assert backup and get_paper(backup, "p-live") is not None, (
        "Die Sicherung enthaelt den Stand von vor dem Restore nicht."
    )
    assert get_paper(str(live_db), "p-original") is not None


# ---------------------------------------------------------------------------
# Runde 3, Regression D — Snapshots mit Herkunftskennzeichnung waren ueber den
# einzigen dokumentierten Wiederherstellungsweg unerreichbar.
#
# ``restore_snapshot_report()`` baute den Tarball-Pfad hart als
# ``<snapshots_dir>/<slug>/<ts>.tgz``. Die beiden Snapshot-Hooks benennen ihre
# Exporte aber um und haengen eine Herkunftskennzeichnung an:
# ``.session.tgz`` (hooks/session-snapshot.mjs, seit #650 — VORBESTEHEND) und
# ``.precompact.tgz`` (hooks/pre-compact.mjs, Runde 2 dieses Reviews — NEU).
# Beide Sorten meldete der Restore mit "Snapshot nicht gefunden", obwohl die
# Datei dalag — ausgerechnet die Snapshots, die als einzige die vault.db
# enthalten.
# ---------------------------------------------------------------------------


def _tarball_mit_namen(slug_dir: Path, dateiname: str, inhalt: str) -> Path:
    """Legt einen Tarball mit genau diesem Dateinamen und einer State-Datei an."""
    import io

    slug_dir.mkdir(parents=True, exist_ok=True)
    pfad = slug_dir / dateiname
    with tarfile.open(str(pfad), "w:gz") as tar:
        nutzlast = inhalt.encode("utf-8")
        info = tarfile.TarInfo(name="academic_context.md")
        info.size = len(nutzlast)
        tar.addfile(info, io.BytesIO(nutzlast))
    return pfad


@pytest.mark.parametrize(
    "dateiname",
    [
        "20990101-1200.tgz",
        "20990101-1200-1.tgz",
        "20990101-1200.precompact.tgz",
        "20990101-1200-2.precompact.tgz",
        "20990101-1200.session.tgz",
        "20990101-1200-3.session.tgz",
    ],
)
def test_restore_findet_alle_gueltigen_namensformen(tmp_path, dateiname):
    """Regression D: jede von Export/Hooks erzeugte Namensform ist aufloesbar."""
    from academic_vault.server import restore_snapshot_report

    snapshots_dir = tmp_path / "snapshots"
    quelle = _tarball_mit_namen(snapshots_dir / "proj", dateiname, "# Stand aus dem Hook")
    ziel = tmp_path / "ziel"

    report = restore_snapshot_report(
        slug="proj",
        ts="20990101-1200",
        snapshots_dir=str(snapshots_dir),
        target_dir=str(ziel),
        db_path=str(tmp_path / "kein-vault.db"),
    )

    assert report["ok"] is True, (
        f"{dateiname} wurde nicht aufgeloest: {report['error']!r} — genau diese "
        f"Snapshots enthalten als einzige die vault.db."
    )
    assert report["tarball"] == str(quelle)
    assert (ziel / "academic_context.md").read_text(encoding="utf-8") == "# Stand aus dem Hook"


def test_restore_waehlt_bei_mehreren_treffern_den_juengsten_und_nennt_ihn(tmp_path):
    """Mehrere Namensformen zu EINEM ts: der juengste gewinnt, sichtbar im Report."""
    from academic_vault.server import restore_snapshot_report

    snapshots_dir = tmp_path / "snapshots"
    slug_dir = snapshots_dir / "proj"
    alt = _tarball_mit_namen(slug_dir, "20990101-1200.tgz", "# alt")
    mittel = _tarball_mit_namen(slug_dir, "20990101-1200.session.tgz", "# mittel")
    neu = _tarball_mit_namen(slug_dir, "20990101-1200.precompact.tgz", "# neu")

    # mtime deterministisch staffeln (die Dateien entstehen in derselben
    # Sekunde; ohne feste Zeiten waere der Test von der Uhr abhaengig).
    for pfad, sekunde in ((alt, 1_000_000), (mittel, 2_000_000), (neu, 3_000_000)):
        os.utime(pfad, (sekunde, sekunde))

    ziel = tmp_path / "ziel"
    report = restore_snapshot_report(
        slug="proj",
        ts="20990101-1200",
        snapshots_dir=str(snapshots_dir),
        target_dir=str(ziel),
        db_path=str(tmp_path / "kein-vault.db"),
    )

    assert report["ok"] is True
    assert report["tarball"] == str(neu), (
        "Bei mehreren Treffern muss der juengste gewinnen und im Report stehen."
    )
    assert (ziel / "academic_context.md").read_text(encoding="utf-8") == "# neu"
    assert set(report["tarball_candidates"]) == {str(alt), str(mittel), str(neu)}, (
        "Der Report muss die verworfenen Treffer benennen, damit die Auswahl nachvollziehbar ist."
    )


def test_restore_ts_bricht_nicht_aus_dem_slug_verzeichnis_aus(tmp_path):
    """Ein praeparierter ts darf keinen Tarball ausserhalb des Slugs oeffnen."""
    from academic_vault.server import restore_snapshot_report

    snapshots_dir = tmp_path / "snapshots"
    _tarball_mit_namen(snapshots_dir / "fremd", "20990101-1200.tgz", "# fremder Slug")
    (snapshots_dir / "proj").mkdir(parents=True, exist_ok=True)

    ziel = tmp_path / "ziel"
    for boeser_ts in (
        "../fremd/20990101-1200",
        f"..{os.sep}..{os.sep}fremd{os.sep}20990101-1200",
        str(snapshots_dir / "fremd" / "20990101-1200"),
    ):
        report = restore_snapshot_report(
            slug="proj",
            ts=boeser_ts,
            snapshots_dir=str(snapshots_dir),
            target_dir=str(ziel),
            db_path=str(tmp_path / "kein-vault.db"),
        )
        assert report["ok"] is False, f"ts={boeser_ts!r} hat aus dem Slug ausgebrochen."
        assert report["tarball"] is None
        assert not (ziel / "academic_context.md").exists()
