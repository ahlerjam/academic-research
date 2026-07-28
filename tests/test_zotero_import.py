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
