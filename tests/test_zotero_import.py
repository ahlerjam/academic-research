"""Tests fuer Zotero-Import (Chunk A, Ticket #88).

Sicherheits-Labels: security, v6, credentials
Alle pyzotero-Calls werden vollstaendig gemockt — keine echten API-Calls.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Pfad fuer Import setzen
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "skills" / "zotero-import" / "scripts")
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIBRARY_JSON = FIXTURES / "zotero_library.json"
ATTACHMENT_A = FIXTURES / "zotero_attachments" / "paper_a.pdf"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict, mode: int = 0o600) -> Path:
    """Schreibt Test-Config-YAML mit angegebenem Dateimodus."""
    import yaml

    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump(data), encoding="utf-8")
    os.chmod(cfg, mode)
    return cfg


def _minimal_config(tmp_path: Path, mode: int = 0o600) -> Path:
    return _write_config(
        tmp_path,
        {
            "zotero_api_key": "zotero_test_key_MOCK",
            "zotero_library_id": "123456",
            "zotero_library_type": "group",
        },
        mode=mode,
    )


def _load_library() -> list:
    return json.loads(LIBRARY_JSON.read_text())


def _make_zotero_mock(items: list) -> MagicMock:
    """Gibt Mock-pyzotero-Zotero-Instanz zurueck."""
    mock = MagicMock()
    mock.everything.return_value = items
    mock.children.return_value = []  # Keine Attachments by default
    return mock


# ---------------------------------------------------------------------------
# Test 1: Smoke — 1 Item wird importiert
# ---------------------------------------------------------------------------


class TestSmokeImport:
    def test_smoke_import_single_item(self, tmp_path):
        """1 Item ohne PDF → 1 Paper im Vault, keine Fehler."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        single_item = [
            {
                "key": "SMOKE001",
                "version": 1,
                "data": {
                    "key": "SMOKE001",
                    "itemType": "journalArticle",
                    "title": "Smoke Test Paper",
                    "creators": [
                        {"creatorType": "author", "firstName": "Test", "lastName": "Author"}
                    ],
                    "date": "2023",
                    "DOI": "10.9999/smoke.001",
                    "ISBN": "",
                    "abstractNote": "Smoke test abstract",
                },
            }
        ]

        with patch("zotero_pull.zotero") as mock_zotero_module:
            mock_zotero_module.Zotero.return_value = _make_zotero_mock(single_item)
            with patch("zotero_pull.ensure_file"):
                result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 1
        assert result.skipped == 0
        assert result.errors == []


# ---------------------------------------------------------------------------
# Test 2: 50 Items — alle importiert
# ---------------------------------------------------------------------------


class TestBulkImport:
    def test_50_items_all_imported(self, tmp_path):
        """50-Item-Fixture → alle 50 Papers im Vault."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")
        items = _load_library()
        assert len(items) == 50

        with patch("zotero_pull.zotero") as mock_zotero_module:
            mock_zotero_module.Zotero.return_value = _make_zotero_mock(items)
            with patch("zotero_pull.ensure_file"):
                result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 50
        assert result.skipped == 0
        assert result.errors == []


# ---------------------------------------------------------------------------
# Test 3: Re-Run → keine Duplikate
# ---------------------------------------------------------------------------


class TestDedup:
    def test_rerun_no_duplicates(self, tmp_path):
        """Zweiter Pull mit identischen Items → nur Items ohne DOI/ISBN nochmals importiert.

        Items mit DOI oder ISBN werden dedupliziert (49 von 50 in der Fixture).
        Das Item ohne DOI/ISBN (NODOI001) kann nicht dedupliziert werden und
        wird erneut importiert — das ist Spec-konformes Verhalten.
        """
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")
        items = _load_library()

        # Zaehle Items mit und ohne DOI/ISBN in der Fixture
        items_with_id = sum(1 for it in items if it["data"].get("DOI") or it["data"].get("ISBN"))
        items_without_id = len(items) - items_with_id

        with patch("zotero_pull.zotero") as mock_zotero_module:
            mock_zotero_module.Zotero.return_value = _make_zotero_mock(items)
            with patch("zotero_pull.ensure_file"):
                result_1 = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result_1.imported == 50

        # Zweiter Run — Items mit DOI/ISBN werden dedupliziert
        with patch("zotero_pull.zotero") as mock_zotero_module:
            mock_zotero_module.Zotero.return_value = _make_zotero_mock(items)
            with patch("zotero_pull.ensure_file"):
                result_2 = run_import(config_path=str(cfg_path), db_path=db_path)

        # Items mit Identifier werden uebersprungen
        assert result_2.skipped == items_with_id
        # Items ohne Identifier werden (nicht-dedup-faehig) erneut importiert
        assert result_2.imported == items_without_id


# ---------------------------------------------------------------------------
# Test 4: Item ohne DOI/ISBN wird trotzdem importiert
# ---------------------------------------------------------------------------


class TestMissingIdentifier:
    def test_missing_doi_always_imported(self, tmp_path):
        """Item ohne DOI und ISBN wird nicht dedupliziert, sondern importiert."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        no_id_item = [
            {
                "key": "NODOI001",
                "version": 1,
                "data": {
                    "key": "NODOI001",
                    "itemType": "journalArticle",
                    "title": "Paper ohne DOI oder ISBN",
                    "creators": [
                        {"creatorType": "author", "firstName": "Dana", "lastName": "Braun"}
                    ],
                    "date": "2021",
                    "DOI": "",
                    "ISBN": "",
                    "abstractNote": "Kein Identifier",
                },
            }
        ]

        with patch("zotero_pull.zotero") as mock_zotero_module:
            mock_zotero_module.Zotero.return_value = _make_zotero_mock(no_id_item)
            with patch("zotero_pull.ensure_file"):
                result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 1
        assert result.skipped == 0


# ---------------------------------------------------------------------------
# Test 5: PDF-Attachment → ensure_file aufgerufen, file_id gecacht
# ---------------------------------------------------------------------------


class TestPDFAttachment:
    def test_pdf_attachment_uploaded_file_id_cached(self, tmp_path):
        """Item mit PDF-Attachment → ensure_file wird aufgerufen."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item = [
            {
                "key": "ATTACH001",
                "version": 1,
                "data": {
                    "key": "ATTACH001",
                    "itemType": "journalArticle",
                    "title": "Paper mit Attachment",
                    "creators": [
                        {"creatorType": "author", "firstName": "Franz", "lastName": "Weber"}
                    ],
                    "date": "2023",
                    "DOI": "10.9999/attach.001",
                    "ISBN": "",
                    "abstractNote": "Hat PDF",
                },
            }
        ]

        attachment_record = [
            {
                "key": "ATT0001A",
                "version": 1,
                "data": {
                    "key": "ATT0001A",
                    "itemType": "attachment",
                    "linkMode": "linked_file",
                    "contentType": "application/pdf",
                    "filename": "paper_a.pdf",
                    "title": "paper_a.pdf",
                },
            }
        ]

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.return_value = attachment_record
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id_abc") as mock_ef:
                with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 1
        mock_ef.assert_called_once()
        # ensure_file gibt file_id zurueck — result.file_ids nicht leer
        assert len(result.file_ids) >= 1
        assert "file_mock_id_abc" in result.file_ids


# ---------------------------------------------------------------------------
# Test 6: 0600-Permission-Check
# ---------------------------------------------------------------------------


class TestConfigPermissions:
    def test_config_perm_check_0644_raises(self, tmp_path):
        """config.yaml mit 0644 → PermissionError wird geworfen."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path, mode=0o644)
        db_path = str(tmp_path / "vault.db")

        with pytest.raises(PermissionError, match="0600"):
            run_import(config_path=str(cfg_path), db_path=db_path)

    def test_config_perm_check_0600_passes(self, tmp_path):
        """config.yaml mit 0600 → kein Fehler."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path, mode=0o600)
        db_path = str(tmp_path / "vault.db")

        with patch("zotero_pull.zotero") as mock_zotero_module:
            mock_zotero_module.Zotero.return_value = _make_zotero_mock([])
            with patch("zotero_pull.ensure_file"):
                result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 0


# ---------------------------------------------------------------------------
# Test 7: Annotation-Import (Issue #395)
# ---------------------------------------------------------------------------


def _item_with_pdf_attachment(item_key: str, doi: str) -> tuple[list, list, str]:
    """Baut ein Journal-Item + zugehoeriges PDF-Attachment-Kind.

    Gibt (items, attachment_children, attachment_key) zurueck.
    """
    item = [
        {
            "key": item_key,
            "version": 1,
            "data": {
                "key": item_key,
                "itemType": "journalArticle",
                "title": "Paper mit Annotationen",
                "creators": [{"creatorType": "author", "firstName": "Nora", "lastName": "Klein"}],
                "date": "2024",
                "DOI": doi,
                "ISBN": "",
                "abstractNote": "Hat Annotationen",
            },
        }
    ]
    att_key = "ATTPDF01"
    attachment_children = [
        {
            "key": att_key,
            "version": 1,
            "data": {
                "key": att_key,
                "itemType": "attachment",
                "linkMode": "linked_file",
                "contentType": "application/pdf",
                "filename": "paper_a.pdf",
                "title": "paper_a.pdf",
            },
        }
    ]
    return item, attachment_children, att_key


def _quotes_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT verbatim, printed_page, extraction_method FROM quotes"
        ).fetchall()
    finally:
        conn.close()


class TestAnnotationImport:
    def test_annotation_creates_quote_with_page(self, tmp_path):
        """Annotation-Kind mit Highlight-Text + Seitenlabel → genau 1 Quote."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_with_pdf_attachment(
            "ANNOITEM", "10.9999/annot.001"
        )
        annotation_children = [
            {
                "key": "ANNOKEY1",
                "version": 1,
                "data": {
                    "key": "ANNOKEY1",
                    "itemType": "annotation",
                    "annotationType": "highlight",
                    "annotationText": "Ein wichtiges Highlight.",
                    "annotationPageLabel": "42",
                },
            }
        ]

        def children_side_effect(key):
            if key == "ANNOITEM":
                return attachment_children
            if key == att_key:
                return annotation_children
            return []

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.side_effect = children_side_effect
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 1
        assert result.errors == []

        rows = _quotes_rows(db_path)
        assert len(rows) == 1
        assert rows[0]["verbatim"] == "Ein wichtiges Highlight."
        assert rows[0]["printed_page"] == 42
        assert rows[0]["extraction_method"] == "manual"

    def test_annotation_non_numeric_page_label_yields_null_page(self, tmp_path):
        """Nicht-numerisches annotationPageLabel (z.B. 'iv') → printed_page NULL, kein Crash."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_with_pdf_attachment(
            "ANNOITM2", "10.9999/annot.002"
        )
        annotation_children = [
            {
                "key": "ANNOKEY2",
                "version": 1,
                "data": {
                    "key": "ANNOKEY2",
                    "itemType": "annotation",
                    "annotationType": "highlight",
                    "annotationText": "Randbemerkung ohne nummerische Seite.",
                    "annotationPageLabel": "iv",
                },
            }
        ]

        def children_side_effect(key):
            if key == "ANNOITM2":
                return attachment_children
            if key == att_key:
                return annotation_children
            return []

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.side_effect = children_side_effect
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 1
        assert result.errors == []

        rows = _quotes_rows(db_path)
        assert len(rows) == 1
        assert rows[0]["printed_page"] is None
        assert rows[0]["extraction_method"] == "manual"

    def test_annotation_unicode_digit_page_label_does_not_crash(self, tmp_path):
        """annotationPageLabel mit Unicode-Ziffer (z.B. Hochstellung '²') crasht nicht.

        Regression: ``str.isdigit()`` gibt fuer ``"²"`` ``True`` zurueck,
        ``int("²")`` wirft aber ``ValueError`` — die Annotation wuerde
        dann komplett verworfen und als Fehler gemeldet statt mit
        ``printed_page = NULL`` importiert zu werden (``str.isdecimal()``
        lehnt den Fall korrekt ab).
        """
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_with_pdf_attachment(
            "ANNOITM3", "10.9999/annot.004"
        )
        annotation_children = [
            {
                "key": "ANNOKEY5",
                "version": 1,
                "data": {
                    "key": "ANNOKEY5",
                    "itemType": "annotation",
                    "annotationType": "highlight",
                    "annotationText": "Fussnotenverweis.",
                    "annotationPageLabel": "²",
                },
            }
        ]

        def children_side_effect(key):
            if key == "ANNOITM3":
                return attachment_children
            if key == att_key:
                return annotation_children
            return []

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.side_effect = children_side_effect
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 1
        assert result.errors == []

        rows = _quotes_rows(db_path)
        assert len(rows) == 1
        assert rows[0]["printed_page"] is None
        assert rows[0]["extraction_method"] == "manual"


# ---------------------------------------------------------------------------
# Test 8: PDF-Attachment-Fallback bleibt erhalten (Regression zu Issue #395)
# ---------------------------------------------------------------------------


def _item_with_two_pdf_attachments(item_key: str, doi: str) -> tuple[list, list, str, str]:
    """Baut ein Journal-Item mit ZWEI PDF-Attachment-Kindern.

    Gibt (items, attachment_children, erster_key, zweiter_key) zurueck.
    """
    item, _single_child, first_key = _item_with_pdf_attachment(item_key, doi)
    second_key = "ATTPDF02"
    attachment_children = [
        {
            "key": key,
            "version": 1,
            "data": {
                "key": key,
                "itemType": "attachment",
                "linkMode": "linked_file",
                "contentType": "application/pdf",
                "filename": "paper_a.pdf",
                "title": "paper_a.pdf",
            },
        }
        for key in (first_key, second_key)
    ]
    return item, attachment_children, first_key, second_key


def _paper_pdf_path(db_path: str, paper_id: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT pdf_path FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


class TestPDFAttachmentFallback:
    def test_failed_first_download_falls_back_to_second_pdf(self, tmp_path):
        """Schlaegt der Download des ersten PDFs fehl, wird das zweite versucht."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, first_key, second_key = _item_with_two_pdf_attachments(
            "FALLBACK", "10.9999/fallback.001"
        )

        def children_side_effect(key):
            if key == "FALLBACK":
                return attachment_children
            return []

        attempted: list[str] = []

        def download_side_effect(_zot, _item_key, att_key, _tmp_dir):
            attempted.append(att_key)
            return None if att_key == first_key else str(ATTACHMENT_A)

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.side_effect = children_side_effect
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id_abc") as mock_ef:
                with patch("zotero_pull._download_attachment", side_effect=download_side_effect):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert attempted == [first_key, second_key]
        assert result.imported == 1
        mock_ef.assert_called_once()
        assert "file_mock_id_abc" in result.file_ids
        assert _paper_pdf_path(db_path, "zotero-FALLBACK") == str(ATTACHMENT_A)

    def test_successful_first_download_stops_after_first_pdf(self, tmp_path):
        """Erfolgreicher Download → zweites PDF-Attachment wird nicht angefasst."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, first_key, _second_key = _item_with_two_pdf_attachments(
            "FIRSTPDF", "10.9999/fallback.002"
        )

        def children_side_effect(key):
            if key == "FIRSTPDF":
                return attachment_children
            return []

        attempted: list[str] = []

        def download_side_effect(_zot, _item_key, att_key, _tmp_dir):
            attempted.append(att_key)
            return str(ATTACHMENT_A)

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.side_effect = children_side_effect
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id_abc") as mock_ef:
                with patch("zotero_pull._download_attachment", side_effect=download_side_effect):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert attempted == [first_key]
        assert result.imported == 1
        mock_ef.assert_called_once()

    def test_annotations_imported_even_when_download_fails(self, tmp_path):
        """Annotationen haengen nicht am Download-Erfolg des PDFs."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_with_pdf_attachment(
            "ANNONOPD", "10.9999/annot.003"
        )
        annotation_children = [
            {
                "key": "ANNOKEY3",
                "version": 1,
                "data": {
                    "key": "ANNOKEY3",
                    "itemType": "annotation",
                    "annotationType": "highlight",
                    "annotationText": "Highlight ohne heruntergeladenes PDF.",
                    "annotationPageLabel": "7",
                },
            }
        ]

        def children_side_effect(key):
            if key == "ANNONOPD":
                return attachment_children
            if key == att_key:
                return annotation_children
            return []

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.side_effect = children_side_effect
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id") as mock_ef:
                with patch("zotero_pull._download_attachment", return_value=None):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.imported == 1
        assert result.errors == []
        mock_ef.assert_not_called()

        rows = _quotes_rows(db_path)
        assert len(rows) == 1
        assert rows[0]["verbatim"] == "Highlight ohne heruntergeladenes PDF."
        assert rows[0]["printed_page"] == 7


# ---------------------------------------------------------------------------
# Test 9: Annotation-Quotes werden beim Re-Import nicht dupliziert (Issue #395)
# ---------------------------------------------------------------------------


def _item_without_identifier_with_pdf(item_key: str) -> tuple[list, list, str]:
    """Item OHNE DOI/ISBN + PDF-Attachment-Kind.

    Solche Items koennen von ``_paper_exists_in_vault`` nicht dedupliziert
    werden (dokumentierte Einschraenkung) und durchlaufen bei jedem Lauf den
    vollen Importpfad inklusive Annotation-Verarbeitung.
    """
    items, attachment_children, att_key = _item_with_pdf_attachment(item_key, "")
    items[0]["data"]["title"] = "Paper ohne Identifier mit Annotationen"
    return items, attachment_children, att_key


class TestAnnotationReimportDedup:
    def test_reimport_without_identifier_does_not_duplicate_quotes(self, tmp_path):
        """Zweiter Lauf ueber dieselbe Annotation legt keinen zweiten Quote an.

        Regression zu Issue #395: ``paper_id`` ist ueber den stabilen
        Zotero-Key deterministisch, ``add_paper`` ist ein Upsert — die
        Annotation-Schleife rief ``add_quote`` aber ungeprueft auf und legte
        pro Lauf eine weitere Kopie derselben Markierung an.
        """
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_without_identifier_with_pdf("NOIDANNO")
        annotation_children = [
            {
                "key": "ANNOKEY4",
                "version": 1,
                "data": {
                    "key": "ANNOKEY4",
                    "itemType": "annotation",
                    "annotationType": "highlight",
                    "annotationText": "Markierung ohne Identifier-Dedup.",
                    "annotationPageLabel": "11",
                },
            }
        ]

        def children_side_effect(key):
            if key == "NOIDANNO":
                return attachment_children
            if key == att_key:
                return annotation_children
            return []

        def _run():
            with patch("zotero_pull.zotero") as mock_zotero_module:
                zot_mock = _make_zotero_mock(item)
                zot_mock.children.side_effect = children_side_effect
                mock_zotero_module.Zotero.return_value = zot_mock
                with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                    with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                        return run_import(config_path=str(cfg_path), db_path=db_path)

        result_1 = _run()
        assert result_1.quotes_imported == 1
        assert len(_quotes_rows(db_path)) == 1

        result_2 = _run()
        assert result_2.errors == []
        # Das Paper selbst ist nicht dedup-faehig und wird erneut importiert
        # (Upsert auf identische paper_id) — die Annotation aber schon.
        assert result_2.quotes_imported == 0, (
            f"Re-Import legte {result_2.quotes_imported} Quote(s) erneut an"
        )
        rows = _quotes_rows(db_path)
        assert len(rows) == 1, f"Quote-Duplikate nach Re-Import: {[r['verbatim'] for r in rows]}"

    def test_same_verbatim_on_different_pages_stays_separate(self, tmp_path):
        """Identischer Text auf zwei Seiten sind zwei echte Markierungen.

        Der Dedup-Schluessel ist (verbatim, printed_page) — er darf zwei
        Markierungen desselben Wortlauts auf verschiedenen Seiten nicht
        zusammenfallen lassen.
        """
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_without_identifier_with_pdf("NOIDANN2")
        annotation_children = [
            {
                "key": f"ANNPG{page}",
                "version": 1,
                "data": {
                    "key": f"ANNPG{page}",
                    "itemType": "annotation",
                    "annotationType": "highlight",
                    "annotationText": "Wiederkehrende Definition.",
                    "annotationPageLabel": page,
                },
            }
            for page in ("3", "9")
        ]

        def children_side_effect(key):
            if key == "NOIDANN2":
                return attachment_children
            if key == att_key:
                return annotation_children
            return []

        def _run():
            with patch("zotero_pull.zotero") as mock_zotero_module:
                zot_mock = _make_zotero_mock(item)
                zot_mock.children.side_effect = children_side_effect
                mock_zotero_module.Zotero.return_value = zot_mock
                with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                    with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                        return run_import(config_path=str(cfg_path), db_path=db_path)

        assert _run().quotes_imported == 2
        assert sorted(r["printed_page"] for r in _quotes_rows(db_path)) == [3, 9]

        assert _run().quotes_imported == 0
        assert len(_quotes_rows(db_path)) == 2


# ---------------------------------------------------------------------------
# Test 10: Annotation-Doku liegt in references/, nicht inline in SKILL.md
# ---------------------------------------------------------------------------

_SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "zotero-import"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_ANNOTATIONS_REF = _SKILL_DIR / "references" / "annotations.md"


class TestAnnotationDocsProgressiveDisclosure:
    """Progressive Disclosure fuer die Annotation-Doku (Issue #395).

    Die Detaildoku (Textquelle, Seitenlabel-Parsing, Idempotenz, Companion-MCP)
    gehoert nach ``references/annotations.md``. Inline in SKILL.md gestellt,
    sprengt sie das Token-Budget der Guards in tests/baselines/ — was in der
    Vergangenheit zum Anheben genau dieser Baselines verleitet hat, statt den
    Inhalt auszulagern. Dieser Test haelt die Auslagerung fest.
    """

    def test_reference_file_exists_and_documents_contract(self):
        assert _ANNOTATIONS_REF.exists(), f"Ausgelagerte Referenz fehlt: {_ANNOTATIONS_REF}"
        text = _ANNOTATIONS_REF.read_text(encoding="utf-8")
        for marker in (
            "annotationText",
            "annotationComment",
            "annotationPageLabel",
            "printed_page",
            "54yyyu/zotero-mcp",
        ):
            assert marker in text, f"references/annotations.md dokumentiert '{marker}' nicht"

    def test_skill_md_links_to_reference(self):
        assert "references/annotations.md" in _SKILL_MD.read_text(encoding="utf-8"), (
            "SKILL.md verlinkt nicht auf references/annotations.md"
        )

    def test_skill_md_has_no_inlined_annotation_detail(self):
        """Die Detailfelder duerfen NICHT zurueck nach SKILL.md wandern."""
        text = _SKILL_MD.read_text(encoding="utf-8")
        for marker in ("annotationText", "annotationComment", "annotationPageLabel"):
            assert marker not in text, (
                f"SKILL.md enthaelt Detailfeld '{marker}' inline — "
                "gehoert nach references/annotations.md"
            )

    def test_skill_md_mentions_companion_with_correct_license(self):
        """AC3 (Issue #395): SKILL.md selbst muss 54yyyu/zotero-mcp + MIT nennen.

        Nur references/annotations.md zu verlinken reicht nicht (Progressive
        Disclosure wird nur bei Bedarf geladen) — die Nennung muss in
        SKILL.md selbst stehen, inkl. korrektem Lizenzstatus in derselben
        Zeile (nicht nur zufaellig `license: MIT` im Frontmatter des Skills
        selbst, das ist eine andere Lizenz als die von 54yyyu/zotero-mcp).
        """
        text = _SKILL_MD.read_text(encoding="utf-8")
        assert "54yyyu/zotero-mcp" in text, (
            "SKILL.md muss 54yyyu/zotero-mcp als optionale Companion-Integration "
            "nennen (AC3, Issue #395)"
        )
        mention_line = next(line for line in text.splitlines() if "54yyyu/zotero-mcp" in line)
        assert "MIT" in mention_line, (
            f"SKILL.md nennt 54yyyu/zotero-mcp, aber nicht dessen MIT-Lizenzstatus "
            f"in derselben Zeile: {mention_line!r}"
        )


# ---------------------------------------------------------------------------
# Test 11: annotationComment darf NIE als verbatim landen (Issue #395)
# ---------------------------------------------------------------------------


def _annotation_child(key: str, **data) -> dict:
    """Baut ein Annotation-Kind mit den uebergebenen Datenfeldern."""
    payload = {"key": key, "itemType": "annotation"}
    payload.update(data)
    return {"key": key, "version": 1, "data": payload}


def _run_with_annotations(tmp_path, item_key: str, doi: str, annotation_children: list):
    """Fuehrt run_import fuer ein Item mit den gegebenen Annotationen aus."""
    from zotero_pull import run_import

    cfg_path = _minimal_config(tmp_path)
    db_path = str(tmp_path / "vault.db")

    item, attachment_children, att_key = _item_with_pdf_attachment(item_key, doi)

    def children_side_effect(key):
        if key == item_key:
            return attachment_children
        if key == att_key:
            return annotation_children
        return []

    with patch("zotero_pull.zotero") as mock_zotero_module:
        zot_mock = _make_zotero_mock(item)
        zot_mock.children.side_effect = children_side_effect
        mock_zotero_module.Zotero.return_value = zot_mock

        with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
            with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                result = run_import(config_path=str(cfg_path), db_path=db_path)

    return result, db_path


class TestAnnotationCommentIsNotVerbatim:
    """``annotationComment`` ist Nutzertext, kein Beleg aus der Quelle.

    ``quotes.verbatim`` traegt im Vault genau eine Zusage: *dieser Wortlaut
    steht so in der Quelle*. ``hooks/verbatim-guard.mjs`` loest ein in einem
    Kapitel gesetztes Anfuehrungszeichen-Span ausschliesslich ueber
    ``search_quote_text()`` auf — eine LIKE-Suche in ``quotes.verbatim`` ohne
    jeden weiteren Diskriminator (``extraction_method`` wird nicht gelesen).
    Alles, was in ``verbatim`` steht, ist fuer den Guard damit ein belegtes
    Zitat.

    ``annotationComment`` ist aber der eigene Kommentar der forschenden Person
    (Zettel-Notiz im PDF), nicht der Wortlaut der Quelle. Zotero selbst trennt
    beides strikt: In den Note-Templates wird ``{{:highlight}}``
    (= ``annotationText``) in Anfuehrungszeichen bzw. ``<blockquote>``
    gerendert, ``{{:comment}}`` dagegen als Fliesstext ausserhalb des Zitats.

    Ein Fallback von ``annotationText`` auf ``annotationComment`` liesse den
    eigenen Kommentar also als vermeintlich belegtes Zitat in den Vault
    wandern — der Guard winkt ihn spaeter durch, und die eigene Formulierung
    stuende mit Quellenzuschreibung in Anfuehrungszeichen im Kapitel. Genau
    diese Klasse von Fehlzuschreibung soll der Guard verhindern.
    """

    USER_COMMENT = "Dieser Ansatz erscheint mir methodisch fragwuerdig."

    def test_note_only_annotation_creates_no_quote(self, tmp_path):
        """Reine Notiz-Annotation (nur Kommentar) erzeugt KEINEN Quote."""
        annotation_children = [
            _annotation_child(
                "ANNONOTE",
                annotationType="note",
                annotationComment=self.USER_COMMENT,
                annotationPageLabel="12",
            )
        ]

        result, db_path = _run_with_annotations(
            tmp_path, "ANNOCMT1", "10.9999/annot.010", annotation_children
        )

        assert result.imported == 1
        assert result.errors == []
        assert _quotes_rows(db_path) == []
        assert result.quotes_imported == 0

    def test_note_only_annotation_does_not_pass_verbatim_guard(self, tmp_path):
        """Der Nutzerkommentar ist ueber den Guard-Lookup nicht auffindbar.

        Das ist die eigentliche Sicherheitszusage: ``verbatim-guard.mjs`` fragt
        genau diese Funktion, um ein Zitat im Kapitel freizugeben.
        """
        from academic_vault.server import search_quote_text

        annotation_children = [
            _annotation_child(
                "ANNONOT2",
                annotationType="note",
                annotationComment=self.USER_COMMENT,
            )
        ]

        _, db_path = _run_with_annotations(
            tmp_path, "ANNOCMT2", "10.9999/annot.011", annotation_children
        )

        assert search_quote_text(db_path, self.USER_COMMENT) == [], (
            "Eigener Annotation-Kommentar ist als Vault-Zitat auffindbar — "
            "der verbatim-guard wuerde ihn als belegtes Zitat durchwinken"
        )

    def test_highlight_with_comment_imports_only_the_highlight(self, tmp_path):
        """Highlight + Kommentar: nur der markierte Quellentext wird Quote."""
        annotation_children = [
            _annotation_child(
                "ANNOMIX1",
                annotationType="highlight",
                annotationText="Der markierte Satz aus der Quelle.",
                annotationComment=self.USER_COMMENT,
                annotationPageLabel="8",
            )
        ]

        result, db_path = _run_with_annotations(
            tmp_path, "ANNOCMT3", "10.9999/annot.012", annotation_children
        )

        rows = _quotes_rows(db_path)
        assert result.errors == []
        assert [r["verbatim"] for r in rows] == ["Der markierte Satz aus der Quelle."]
        assert rows[0]["printed_page"] == 8
        assert all(self.USER_COMMENT not in r["verbatim"] for r in rows)

    def test_image_annotation_with_comment_creates_no_quote(self, tmp_path):
        """Auch Nicht-Text-Annotationen (image/ink) duerfen keinen Quote erzeugen.

        Sie tragen nie ``annotationText``; ihr ``annotationComment`` ist
        genauso Nutzertext wie bei der Notiz-Annotation.
        """
        annotation_children = [
            _annotation_child(
                "ANNOIMG1",
                annotationType="image",
                annotationComment=self.USER_COMMENT,
                annotationPageLabel="3",
            )
        ]

        result, db_path = _run_with_annotations(
            tmp_path, "ANNOCMT4", "10.9999/annot.013", annotation_children
        )

        assert result.errors == []
        assert _quotes_rows(db_path) == []

    def test_skipped_notes_are_counted_not_silently_dropped(self, tmp_path):
        """Uebersprungene Nur-Kommentar-Annotationen bleiben sichtbar.

        Der Kommentar gehoert fachlich nicht in ``quotes`` (und die
        ``notes``-Tabelle hat noch keine Python-API). Er darf aber auch nicht
        spurlos verschwinden — sonst wundert sich die Nutzerin, warum ihre
        PDF-Notizen nach dem Import fehlen.
        """
        annotation_children = [
            _annotation_child(
                "ANNOCNT1",
                annotationType="note",
                annotationComment=self.USER_COMMENT,
            ),
            _annotation_child(
                "ANNOCNT2",
                annotationType="highlight",
                annotationText="Belegter Wortlaut aus der Quelle.",
                annotationComment="Nebenbemerkung zum Highlight.",
            ),
        ]

        result, db_path = _run_with_annotations(
            tmp_path, "ANNOCMT5", "10.9999/annot.014", annotation_children
        )

        assert result.quotes_imported == 1
        assert result.comments_skipped == 1, (
            "Nur-Kommentar-Annotationen werden still verworfen — ImportResult muss sie zaehlen"
        )


# ---------------------------------------------------------------------------
# Test 10: Zotero-Volltext-Uebernahme statt lokaler PDF-Extraktion (Issue #525)
# ---------------------------------------------------------------------------

NONCE_PDF = FIXTURES / "fulltext" / "nonce_paper.pdf"


def _paper_fulltext_row(db_path: str, paper_id: str) -> tuple[str, str] | None:
    """Liest ``(text, extractor)`` aus ``paper_fulltext`` oder ``None``."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT text, extractor FROM paper_fulltext WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()
    return (row[0], row[1]) if row else None


class TestZoteroFulltext:
    def test_available_zotero_fulltext_skips_local_pdf_parse(self, tmp_path):
        """`fulltext_item()` liefert Content -> ohne lokalen PDF-Parse uebernommen.

        Der Download-Mock schlaegt bewusst fehl: der Sparerfekt gilt
        unabhaengig vom Download-Erfolg des PDFs (separater API-Call).
        """
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_with_pdf_attachment("ZFTEXT1", "10.9999/zft.001")

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.return_value = attachment_children
            zot_mock.fulltext_item.return_value = {
                "content": "Von Zotero indizierter Volltext.",
                "indexedPages": 3,
                "totalPages": 3,
            }
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                with patch("zotero_pull._download_attachment", return_value=None):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        zot_mock.fulltext_item.assert_called_once_with(att_key)
        assert result.fulltext_from_zotero == 1
        row = _paper_fulltext_row(db_path, "zotero-ZFTEXT1")
        assert row is not None
        text, extractor = row
        assert extractor == "zotero"
        assert text == "Von Zotero indizierter Volltext."

    def test_zotero_fulltext_not_indexed_falls_back_to_local_pdf(self, tmp_path):
        """404 (`ResourceNotFoundError`) -> sauberer Fallback auf lokalen pypdf-Pfad."""
        from pyzotero.errors import ResourceNotFoundError
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_with_pdf_attachment("ZFTEXT2", "10.9999/zft.002")

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.return_value = attachment_children
            zot_mock.fulltext_item.side_effect = ResourceNotFoundError("nicht indiziert")
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                with patch("zotero_pull._download_attachment", return_value=str(NONCE_PDF)):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.errors == []
        assert result.fulltext_from_zotero == 0
        row = _paper_fulltext_row(db_path, "zotero-ZFTEXT2")
        assert row is not None
        text, extractor = row
        assert extractor == "pypdf"
        assert "zqxwvfulltextnonce373" in text

    def test_zotero_fulltext_empty_content_falls_back_to_local_pdf(self, tmp_path):
        """Leerer Content zaehlt wie 'nicht verfuegbar' -- kein falsches 'true'."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, att_key = _item_with_pdf_attachment("ZFTEXT3", "10.9999/zft.003")

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.return_value = attachment_children
            zot_mock.fulltext_item.return_value = {
                "content": "",
                "indexedPages": 0,
                "totalPages": 0,
            }
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                with patch("zotero_pull._download_attachment", return_value=str(NONCE_PDF)):
                    result = run_import(config_path=str(cfg_path), db_path=db_path)

        assert result.errors == []
        assert result.fulltext_from_zotero == 0
        row = _paper_fulltext_row(db_path, "zotero-ZFTEXT3")
        assert row is not None
        assert row[1] == "pypdf"

    def test_read_only_guarantee_no_mutating_zotero_calls(self, tmp_path):
        """Nur lesende pyzotero-Methoden werden aufgerufen -- kein Push nach Zotero."""
        from zotero_pull import run_import

        cfg_path = _minimal_config(tmp_path)
        db_path = str(tmp_path / "vault.db")

        item, attachment_children, _att_key = _item_with_pdf_attachment(
            "ZFTEXT4", "10.9999/zft.004"
        )

        with patch("zotero_pull.zotero") as mock_zotero_module:
            zot_mock = _make_zotero_mock(item)
            zot_mock.children.return_value = attachment_children
            zot_mock.fulltext_item.return_value = {
                "content": "Text.",
                "indexedPages": 1,
                "totalPages": 1,
            }
            mock_zotero_module.Zotero.return_value = zot_mock

            with patch("zotero_pull.ensure_file", return_value="file_mock_id"):
                with patch("zotero_pull._download_attachment", return_value=str(NONCE_PDF)):
                    run_import(config_path=str(cfg_path), db_path=db_path)

        called_method_names = {call[0] for call in zot_mock.method_calls}
        mutating_methods = {
            "update_item",
            "update_items",
            "create_items",
            "upload_attachments",
            "attachment_simple",
            "delete_item",
            "delete_items",
            "set_fulltext",
        }
        assert called_method_names.isdisjoint(mutating_methods)
        assert "fulltext_item" in called_method_names
