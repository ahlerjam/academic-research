"""Regressionstests fuer Issue #604 — Vault-weite Retraction-Pruefung.

Deckt die im Plan-Kommentar (<!-- plan:v1 -->) benannten Testfaelle je
Akzeptanzkriterium ab:

- AC1: ein Durchgang ueber alle Vault-Papers mit DOI, unabhaengig vom
  Importweg (``provenance``).
- AC2: die Crossref-Abfragelogik existiert genau einmal im Repo
  (``academic_vault.retraction``); ``parse_list.py`` definiert keine eigene
  Crossref-URL-Konstante mehr und liefert ueber denselben Codepfad
  identische Ergebnisse.
- AC3: nur unzureichend gepruefte Papers werden erneut abgefragt
  (``max_age_days``/``force``).
- AC4: ein Treffer wird nur vorgelegt, nie automatisch nach
  ``excluded_sources`` geschrieben.
- AC5: Unterscheidung zitiert/ungenutzt ueber die Kapitelzitat-Heuristik.
- AC6: Papers ohne DOI erscheinen als "nicht pruefbar" (eigene Kategorie).
- AC7: ein Crossref-Ausfall ist sichtbar (eigene Fehlerkategorie,
  ``error_count``), kein leeres "keine Rueckzuege"-Resultat.
"""

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from academic_vault import migrate
from academic_vault.db import CURRENT_SCHEMA_VERSION, VaultDB, paper_cited_in_chapters
from academic_vault.retraction import RetractionCheckResult, check_retraction
from academic_vault.server import check_retractions

CROSSREF_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crossref"


def load_crossref_fixture(name: str) -> dict:
    return json.loads((CROSSREF_FIXTURES / name).read_text(encoding="utf-8"))


def crossref_response(payload: dict, status_code: int = 200):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def _csl(doi: str, family: str = "Mueller", year: int = 2019) -> str:
    return json.dumps(
        {
            "type": "article-journal",
            "title": "A Test Paper",
            "author": [{"family": family, "given": "A."}],
            "issued": {"date-parts": [[year]]},
            "DOI": doi,
        },
        ensure_ascii=False,
    )


def make_db(tmp_path: Path) -> tuple[str, VaultDB]:
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    return db_path, db


# ---------------------------------------------------------------------------
# academic_vault.retraction — geteilte Crossref-Logik (Grundlage fuer AC2/AC7)
# ---------------------------------------------------------------------------


class TestRetractionModule:
    def test_retracted_status_with_source(self):
        """Realer zurueckgezogener Artikel -> status='retracted' + Fundstelle (Notiz-DOI)."""
        payload = load_crossref_fixture("retracted_article.json")
        msg = payload["message"]
        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction(msg["DOI"])
        assert result.status == "retracted"
        assert result.source == "10.1016/s0140-6736(10)60175-4"

    def test_clean_status_for_regular_article(self):
        payload = load_crossref_fixture("regular_article.json")
        msg = payload["message"]
        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction(msg["DOI"])
        assert result.status == "clean"
        assert result.source is None

    def test_retraction_notice_itself_is_clean(self):
        """Die Notiz selbst (traegt nur `update-to`) ist nicht zurueckgezogen."""
        payload = load_crossref_fixture("retraction_notice.json")
        msg = payload["message"]
        with patch("requests.get", return_value=crossref_response(payload)):
            result = check_retraction(msg["DOI"])
        assert result.status == "clean"

    def test_error_status_on_404(self):
        """AC7: 404 ist ein sichtbarer Fehler, nicht 'clean'."""
        with patch("requests.get", return_value=crossref_response({}, status_code=404)):
            result = check_retraction("10.9999/nonexistent")
        assert result.status == "error"
        assert result.error_message

    def test_error_status_on_network_exception(self):
        with patch("requests.get", side_effect=ConnectionError("network down")):
            result = check_retraction("10.1234/whatever")
        assert result.status == "error"
        assert "network down" in result.error_message

    def test_error_status_on_empty_doi_without_network_call(self):
        with patch("requests.get") as mock_get:
            result = check_retraction("")
        assert result.status == "error"
        mock_get.assert_not_called()

    def test_result_is_frozen_dataclass(self):
        import dataclasses

        r = RetractionCheckResult(status="clean", doi="10.1/x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.status = "retracted"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC2: parse_list.py hat keine eigene Crossref-URL-Konstante mehr und liefert
# ueber denselben Codepfad identische Ergebnisse wie das geteilte Modul.
# ---------------------------------------------------------------------------


class TestAC2SharedLogic:
    def test_parse_list_defines_no_own_crossref_url_constant(self):
        source = Path("skills/reading-list-import/scripts/parse_list.py").read_text(
            encoding="utf-8"
        )
        assert "_CROSSREF_API" not in source
        assert "api.crossref.org" not in source

    def test_parse_list_and_shared_module_agree_on_retracted_payload(self):
        import sys

        sys.path.insert(
            0,
            str(
                Path(__file__).resolve().parent.parent
                / "skills"
                / "reading-list-import"
                / "scripts"
            ),
        )
        import parse_list

        payload = load_crossref_fixture("retracted_article.json")
        msg = payload["message"]
        with patch("requests.get", return_value=crossref_response(payload)):
            bool_result = parse_list.check_retraction(msg["DOI"])
            shared_result = check_retraction(msg["DOI"])
        assert bool_result is True
        assert shared_result.status == "retracted"
        assert bool_result == (shared_result.status == "retracted")


# ---------------------------------------------------------------------------
# db.paper_cited_in_chapters — Heuristik fuer AC5
# ---------------------------------------------------------------------------


class TestPaperCitedInChapters:
    def test_true_when_family_and_year_present(self, tmp_path):
        kapitel = tmp_path / "kapitel"
        kapitel.mkdir()
        (kapitel / "einleitung.md").write_text("Wie (Müller 2019) zeigt, ...", encoding="utf-8")
        csl = json.loads(_csl("10.1/x", family="Mueller", year=2019))
        assert paper_cited_in_chapters(csl, kapitel) is True

    def test_false_when_only_year_matches(self, tmp_path):
        kapitel = tmp_path / "kapitel"
        kapitel.mkdir()
        (kapitel / "einleitung.md").write_text("Im Jahr 2019 geschah viel.", encoding="utf-8")
        csl = json.loads(_csl("10.1/x", family="Mueller", year=2019))
        assert paper_cited_in_chapters(csl, kapitel) is False

    def test_false_when_kapitel_dir_missing(self, tmp_path):
        csl = json.loads(_csl("10.1/x", family="Mueller", year=2019))
        assert paper_cited_in_chapters(csl, tmp_path / "kapitel") is False

    def test_true_for_nested_subfolder(self, tmp_path):
        kapitel = tmp_path / "kapitel" / "teil1"
        kapitel.mkdir(parents=True)
        (kapitel / "kap3.md").write_text("(Mueller 2019) argumentiert ...", encoding="utf-8")
        csl = json.loads(_csl("10.1/x", family="Mueller", year=2019))
        assert paper_cited_in_chapters(csl, tmp_path / "kapitel") is True


# ---------------------------------------------------------------------------
# server.check_retractions — MCP-Tool-Logik
# ---------------------------------------------------------------------------


class TestCheckRetractionsTool:
    def test_ac1_covers_all_provenances(self, tmp_path):
        db_path, db = make_db(tmp_path)
        for i, prov in enumerate(["zotero-import", "anchor-paper-survey", "fetch", None]):
            db.add_paper(
                f"p{i}",
                _csl(f"10.1/{i}"),
                doi=f"10.1/{i}",
                provenance=prov,
            )

        with patch(
            "academic_vault.server._retraction.check_retraction",
            return_value=RetractionCheckResult(status="clean", doi="x"),
        ) as mocked:
            result = check_retractions(db_path)

        assert mocked.call_count == 4
        assert len(result["clean"]) == 4

    def test_ac3_staleness_filter_and_force(self, tmp_path):
        db_path, db = make_db(tmp_path)
        now = int(time.time())
        db.add_paper("fresh", _csl("10.1/fresh"), doi="10.1/fresh")
        db.update_retraction_checked_at("fresh", now - 3600)  # 1h alt
        db.add_paper("stale", _csl("10.1/stale"), doi="10.1/stale")
        db.update_retraction_checked_at("stale", now - 100 * 86400)  # 100 Tage
        db.add_paper("never", _csl("10.1/never"), doi="10.1/never")
        # kein retraction_checked_at gesetzt -> NULL

        with patch(
            "academic_vault.server._retraction.check_retraction",
            return_value=RetractionCheckResult(status="clean", doi="x"),
        ) as mocked:
            result = check_retractions(db_path, max_age_days=90)

        checked_ids = {c[0][0] for c in mocked.call_args_list}
        assert checked_ids == {"10.1/stale", "10.1/never"}
        assert result["skipped_fresh_count"] == 1
        assert result["checked_count"] == 2

        # force=True erzwingt Call auch fuer frisch geprueftes Paper.
        with patch(
            "academic_vault.server._retraction.check_retraction",
            return_value=RetractionCheckResult(status="clean", doi="x"),
        ) as mocked_force:
            result_force = check_retractions(db_path, max_age_days=90, force=True)

        assert mocked_force.call_count == 3
        assert result_force["skipped_fresh_count"] == 0

    def test_ac4_hit_is_not_auto_excluded_and_carries_source(self, tmp_path):
        db_path, db = make_db(tmp_path)
        db.add_paper("retracted-paper", _csl("10.1/retracted"), doi="10.1/retracted")

        with patch(
            "academic_vault.server._retraction.check_retraction",
            return_value=RetractionCheckResult(
                status="retracted", doi="10.1/retracted", source="10.1/notice"
            ),
        ):
            result = check_retractions(db_path)

        assert db.is_excluded("retracted-paper") is False
        assert len(result["retracted"]) == 1
        hit = result["retracted"][0]
        assert hit["paper_id"] == "retracted-paper"
        assert hit["source"] == "10.1/notice"

    def test_ac5_distinguishes_cited_from_unused(self, tmp_path):
        db_path, db = make_db(tmp_path)
        db.add_paper(
            "cited",
            _csl("10.1/cited", family="Schmidt", year=2020),
            doi="10.1/cited",
        )
        db.add_paper(
            "unused",
            _csl("10.1/unused", family="Weber", year=2018),
            doi="10.1/unused",
        )
        kapitel = tmp_path / "kapitel"
        kapitel.mkdir()
        (kapitel / "kap1.md").write_text("(Schmidt 2020) argumentiert ...", encoding="utf-8")

        def fake_check(doi):
            return RetractionCheckResult(status="retracted", doi=doi, source="10.1/notice")

        with patch("academic_vault.server._retraction.check_retraction", side_effect=fake_check):
            result = check_retractions(db_path, project_dir=str(tmp_path))

        by_id = {h["paper_id"]: h for h in result["retracted"]}
        assert by_id["cited"]["cited_in_chapter"] is True
        assert by_id["unused"]["cited_in_chapter"] is False

    def test_ac6_no_doi_papers_are_not_probable_and_sums_correctly(self, tmp_path):
        db_path, db = make_db(tmp_path)
        db.add_paper("with-doi", _csl("10.1/x"), doi="10.1/x")
        db.add_paper("no-doi", _csl(""), doi=None)

        with patch(
            "academic_vault.server._retraction.check_retraction",
            return_value=RetractionCheckResult(status="clean", doi="x"),
        ):
            result = check_retractions(db_path)

        assert result["no_doi"] == ["no-doi"]
        total = (
            len(result["retracted"])
            + len(result["clean"])
            + len(result["error"])
            + len(result["no_doi"])
        )
        assert total == 2  # == Gesamtzahl Papers mit source_kind='literature'

    def test_ac7_crossref_failure_is_visible_not_empty_clean_result(self, tmp_path):
        db_path, db = make_db(tmp_path)
        db.add_paper("broken", _csl("10.1/broken"), doi="10.1/broken")
        db.add_paper("ok", _csl("10.1/ok"), doi="10.1/ok")

        def fake_check(doi):
            if doi == "10.1/broken":
                return RetractionCheckResult(status="error", doi=doi, error_message="Crossref down")
            return RetractionCheckResult(status="clean", doi=doi)

        with patch("academic_vault.server._retraction.check_retraction", side_effect=fake_check):
            result = check_retractions(db_path)

        assert result["error_count"] == 1
        assert result["error"][0]["paper_id"] == "broken"
        assert result["error"][0]["error_message"] == "Crossref down"
        assert result["clean"] == ["ok"]

        # Kein Timestamp-Update bei Fehler -- naechster Lauf versucht erneut.
        paper = db.get_paper("broken")
        assert paper["retraction_checked_at"] is None

    def test_source_kind_primary_is_excluded(self, tmp_path):
        """Nur `source_kind='literature'` wird geprueft -- kein Retraction-Check
        fuer eigenes Erhebungsmaterial (Transkripte etc.)."""
        db_path, db = make_db(tmp_path)
        db.add_paper(
            "transcript",
            _csl("10.1/t"),
            doi="10.1/t",
            source_kind="primary",
        )

        with patch("academic_vault.server._retraction.check_retraction") as mocked:
            result = check_retractions(db_path)

        mocked.assert_not_called()
        assert result["checked_count"] == 0
        assert result["no_doi"] == []


# ---------------------------------------------------------------------------
# Schema/Migration: retraction_checked_at-Spalte
# ---------------------------------------------------------------------------


class TestRetractionCheckedAtMigration:
    def test_fresh_db_has_column_and_current_version(self, tmp_path):
        db_path, db = make_db(tmp_path)
        columns = {
            row[1]
            for row in sqlite3.connect(db_path).execute("PRAGMA table_info(papers)").fetchall()
        }
        assert "retraction_checked_at" in columns

        version = sqlite3.connect(db_path).execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION

    def test_add_retraction_checked_at_column_is_idempotent(self, tmp_path):
        db_path, _ = make_db(tmp_path)
        migrate.add_retraction_checked_at_column(db_path)
        migrate.add_retraction_checked_at_column(db_path)  # zweiter Aufruf darf nicht crashen
        columns = {
            row[1]
            for row in sqlite3.connect(db_path).execute("PRAGMA table_info(papers)").fetchall()
        }
        assert "retraction_checked_at" in columns

    def test_legacy_db_without_column_gets_migrated(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE papers (
              paper_id           TEXT PRIMARY KEY,
              type                TEXT NOT NULL DEFAULT 'article-journal',
              csl_json            TEXT NOT NULL,
              doi                 TEXT,
              isbn                TEXT,
              pdf_path            TEXT,
              file_id             TEXT,
              file_id_expires_at  INTEGER,
              page_offset         INTEGER DEFAULT 0,
              ocr_done            INTEGER DEFAULT 0,
              editor              TEXT,
              chapter             TEXT,
              page_first          INTEGER,
              page_last           INTEGER,
              container_title     TEXT,
              parent_paper_id     TEXT,
              provenance          TEXT,
              added_at            INTEGER NOT NULL,
              updated_at          INTEGER NOT NULL,
              source_kind         TEXT NOT NULL DEFAULT 'literature'
            )
        """)
        conn.commit()
        conn.close()

        db = VaultDB(db_path)
        db.init_schema()

        columns = {
            row[1]
            for row in sqlite3.connect(db_path).execute("PRAGMA table_info(papers)").fetchall()
        }
        assert "retraction_checked_at" in columns
        version = sqlite3.connect(db_path).execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION
