"""Tests fuer Issue #535 -- ``files_api.py`` als optionaler Legacy-Pfad.

Seit der Umstellung auf lokale Verbatim-Zitate (#507/#512/#532) haengt kein
Standard-Workflow mehr an der Anthropic-Files-API. Das Modul bleibt fuer den
optionalen Citations-API-Pfad erhalten, darf ohne ``ANTHROPIC_API_KEY`` aber
in keinem Standard-Flow mehr einen Fehler erzeugen.

AC -> Testfall (siehe Issue #535):
  - AC1 Import + Zitat-Workflow ohne Key erzeugen keinen ``ensure_file``-Fehler
    und keinen Eintrag in ``result.errors``: :class:`TestAc1NoKeyNoError`
  - AC2 Mit gesetztem Key laeuft der Upload-Pfad unveraendert (Regression):
    :class:`TestAc2WithKeyUnchanged`
  - AC3 Riskante Zweige (TTL-Reupload, Cache-Miss ohne ``paper_row``) haben
    Tests, Modul + Doku sind als Legacy/optional gekennzeichnet:
    :class:`TestAc3RiskyBranchesAndLegacyMarking`

Kein Test macht einen echten API-Aufruf: Uploads laufen ausschliesslich ueber
``patch.object(..., "_upload_file")`` bzw. einen Fake-Client (#55/#390 --
Testsuite verbraucht kein API-Budget).
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import time
from unittest.mock import MagicMock, patch

import pytest
import yaml
from academic_vault import files_api as files_api_module
from academic_vault.db import VaultDB
from academic_vault.files_api import FilesAPIClient
from academic_vault.server import add_quote, ensure_file

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
ATTACHMENT_A = FIXTURES / "zotero_attachments" / "paper_a.pdf"
VERBATIM_PDF = FIXTURES / "verbatim" / "verbatim_source.pdf"

# Wortlaut aus tests/fixtures/verbatim/create_fixtures.py, Seite 2.
VERBATIM_EXACT_PAGE2 = 'Die Teilnehmenden beschrieben "implizites Wissen" als zentralen Faktor.'

sys.path.insert(0, str(REPO_ROOT / "skills" / "zotero-import" / "scripts"))

_PAPER_ID = "files-api-fixture"
_CSL = '{"title": "Files API Fixture"}'


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _vault_with_pdf(tmp_path, pdf_path: str) -> str:
    """Frischer Vault mit genau einem Paper samt ``pdf_path``."""
    db_path = str(tmp_path / "vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    db.add_paper(_PAPER_ID, _CSL, pdf_path=pdf_path)
    return db_path


def _paper_row(db_path: str, paper_id: str = _PAPER_ID) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT file_id, file_id_expires_at FROM papers WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
    finally:
        conn.close()


def _paper_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])
    finally:
        conn.close()


def _zotero_config(tmp_path) -> str:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.dump(
            {
                "zotero_api_key": "zotero_test_key_MOCK",
                "zotero_library_id": "123456",
                "zotero_library_type": "group",
            }
        ),
        encoding="utf-8",
    )
    os.chmod(cfg, 0o600)
    return str(cfg)


def _zotero_item_with_pdf() -> tuple[list, list]:
    """Ein Zotero-Item mit genau einem PDF-Attachment-Kind."""
    item = [
        {
            "key": "LEGACY01",
            "version": 1,
            "data": {
                "key": "LEGACY01",
                "itemType": "journalArticle",
                "title": "Paper mit Attachment",
                "creators": [{"creatorType": "author", "firstName": "Franz", "lastName": "Weber"}],
                "date": "2023",
                "DOI": "10.9999/legacy.535",
                "ISBN": "",
                "abstractNote": "Hat PDF",
            },
        }
    ]
    attachments = [
        {
            "key": "LEGACYATT",
            "version": 1,
            "data": {
                "key": "LEGACYATT",
                "itemType": "attachment",
                "linkMode": "linked_file",
                "contentType": "application/pdf",
                "filename": "paper_a.pdf",
                "title": "paper_a.pdf",
            },
        }
    ]
    return item, attachments


def _zotero_mock(items: list, attachments: list) -> MagicMock:
    mock = MagicMock()
    mock.everything.return_value = items
    mock.children.side_effect = lambda key: attachments if key == "LEGACY01" else []
    mock.fulltext_item.return_value = {}
    return mock


# ---------------------------------------------------------------------------
# AC1: ohne ANTHROPIC_API_KEY kein Fehler in Standard-Flows
# ---------------------------------------------------------------------------


class TestAc1NoKeyNoError:
    """AC1: kein Key -> kein ``ensure_file``-Fehler, kein ``result.errors``."""

    def test_ensure_file_without_key_returns_none_instead_of_raising(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))

        assert ensure_file(db_path=db_path, paper_id=_PAPER_ID) is None

    def test_no_anthropic_client_constructed_without_key(self, tmp_path, monkeypatch):
        """Der Skip greift vor dem SDK, nicht erst beim Request."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))

        with patch("anthropic.Anthropic") as anthropic_ctor:
            assert ensure_file(db_path=db_path, paper_id=_PAPER_ID) is None

        anthropic_ctor.assert_not_called()

    def test_unknown_paper_still_raises_value_error(self, tmp_path, monkeypatch):
        """Business-Logik-Fehler bleiben Fehler -- auch ohne Key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))

        with pytest.raises(ValueError, match="nicht gefunden"):
            ensure_file(db_path=db_path, paper_id="gibt-es-nicht")

    def test_paper_without_pdf_path_still_raises_value_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        db_path = str(tmp_path / "vault.db")
        db = VaultDB(db_path)
        db.init_schema()
        db.add_paper("kein-pdf", _CSL)

        with pytest.raises(ValueError, match="pdf_path"):
            ensure_file(db_path=db_path, paper_id="kein-pdf")

    def test_import_without_api_key_records_no_error(self, tmp_path, monkeypatch):
        """Zotero-Import ohne Key: sauberer Skip statt Eintrag in errors."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from zotero_pull import run_import

        cfg_path = _zotero_config(tmp_path)
        db_path = str(tmp_path / "vault.db")
        items, attachments = _zotero_item_with_pdf()

        with patch("zotero_pull.zotero") as mock_zotero_module:
            mock_zotero_module.Zotero.return_value = _zotero_mock(items, attachments)
            with patch("zotero_pull._download_attachment", return_value=str(ATTACHMENT_A)):
                result = run_import(config_path=cfg_path, db_path=db_path)

        assert result.imported == 1
        assert result.errors == []
        assert result.file_ids == []
        assert result.files_api_skipped == 1

    def test_local_verbatim_quote_path_never_touches_files_api(self, tmp_path, monkeypatch):
        """Der Zitat-Standardweg baut keinen Files-API-Client."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        db_path = _vault_with_pdf(tmp_path, str(VERBATIM_PDF))

        with patch("academic_vault.server.FilesAPIClient") as client_cls:
            quote_id = add_quote(
                db_path=db_path,
                paper_id=_PAPER_ID,
                verbatim=VERBATIM_EXACT_PAGE2,
                extraction_method="local-verbatim",
            )

        assert quote_id
        client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# AC2: mit Key laeuft der Upload-Pfad unveraendert
# ---------------------------------------------------------------------------


class TestAc2WithKeyUnchanged:
    """AC2: gesetzter Key -> Upload + Cache wie bisher."""

    def test_ensure_file_with_key_uploads_and_caches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))

        with patch.object(FilesAPIClient, "_upload_file", return_value="file-abc123") as upload:
            first = ensure_file(db_path=db_path, paper_id=_PAPER_ID)
            second = ensure_file(db_path=db_path, paper_id=_PAPER_ID)

        assert first == second == "file-abc123"
        upload.assert_called_once()

        row = _paper_row(db_path)
        assert row["file_id"] == "file-abc123"
        assert row["file_id_expires_at"] > int(time.time())

    def test_explicit_api_key_argument_still_wins(self, tmp_path, monkeypatch):
        """``api_key=`` als Argument funktioniert auch ohne Env-Variable."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))

        with patch.object(FilesAPIClient, "_upload_file", return_value="file-xyz"):
            assert ensure_file(db_path=db_path, paper_id=_PAPER_ID, api_key="sk-test") == (
                "file-xyz"
            )

    def test_upload_still_sends_files_api_beta_header(self, tmp_path):
        """Der Beta-Kontrakt bleibt erhalten -- nur an einer Stelle definiert."""
        pdf_path = tmp_path / "dummy.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")

        fake_client = MagicMock()
        fake_client.beta.files.upload.return_value = MagicMock(id="file-beta-1")

        client = FilesAPIClient(anthropic_api_key="test-key", cache_db_path=":memory:")
        with patch.object(client, "_get_client", return_value=fake_client):
            assert client._upload_file(str(pdf_path)) == "file-beta-1"

        kwargs = fake_client.beta.files.upload.call_args.kwargs
        assert kwargs["extra_headers"]["anthropic-beta"] == files_api_module.FILES_API_BETA
        assert files_api_module.FILES_API_BETA == "files-api-2025-04-14"


# ---------------------------------------------------------------------------
# AC3: riskante Zweige + Legacy-Kennzeichnung
# ---------------------------------------------------------------------------


class TestAc3RiskyBranchesAndLegacyMarking:
    """AC3: TTL-Reupload und Cache-Miss ohne ``paper_row`` sind abgedeckt."""

    def test_expired_ttl_triggers_reupload(self, tmp_path):
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))
        db = VaultDB(db_path)
        db.set_file_id(_PAPER_ID, "file-stale", int(time.time()) - 1)

        client = FilesAPIClient(anthropic_api_key="test-key", cache_db_path=db_path)
        with patch.object(client, "_upload_file", return_value="file-fresh") as upload:
            assert client.ensure_file(str(ATTACHMENT_A)) == "file-fresh"

        upload.assert_called_once()
        row = _paper_row(db_path)
        assert row["file_id"] == "file-fresh"
        assert row["file_id_expires_at"] > int(time.time())

    def test_valid_ttl_does_not_reupload(self, tmp_path):
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))
        db = VaultDB(db_path)
        db.set_file_id(_PAPER_ID, "file-cached", int(time.time()) + 3600)

        client = FilesAPIClient(anthropic_api_key="test-key", cache_db_path=db_path)
        with patch.object(client, "_upload_file", return_value="file-new") as upload:
            assert client.ensure_file(str(ATTACHMENT_A)) == "file-cached"

        upload.assert_not_called()

    def test_cache_miss_without_paper_row_returns_file_id_without_db_write(self, tmp_path):
        """PDF ohne Paper-Zeile: file_id kommt zurueck, nichts wird geschrieben."""
        db_path = str(tmp_path / "vault.db")
        db = VaultDB(db_path)
        db.init_schema()
        before = _paper_count(db_path)

        client = FilesAPIClient(anthropic_api_key="test-key", cache_db_path=db_path)
        with patch.object(client, "_upload_file", return_value="file-orphan"):
            assert client.ensure_file(str(ATTACHMENT_A)) == "file-orphan"

        assert _paper_count(db_path) == before

    def test_client_without_key_raises_dedicated_error(self, tmp_path):
        """Direkter Modul-Aufruf ohne Key: eigene Exception, kein SDK-TypeError."""
        db_path = _vault_with_pdf(tmp_path, str(ATTACHMENT_A))
        client = FilesAPIClient(anthropic_api_key="", cache_db_path=db_path)

        with patch("anthropic.Anthropic") as anthropic_ctor:
            with pytest.raises(files_api_module.FilesAPINotConfiguredError):
                client.ensure_file(str(ATTACHMENT_A))

        anthropic_ctor.assert_not_called()

    def test_is_configured_reads_environment(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert files_api_module.is_configured() is False
        assert files_api_module.is_configured("sk-explicit") is True

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
        assert files_api_module.is_configured() is True

    def test_module_is_marked_legacy_optional(self):
        docstring = files_api_module.__doc__ or ""
        lowered = docstring.lower()
        assert "legacy" in lowered
        assert "optional" in lowered
        assert "ANTHROPIC_API_KEY" in docstring

    def test_vault_reference_documents_legacy_status(self):
        text = (REPO_ROOT / "docs" / "reference" / "vault.md").read_text(encoding="utf-8")
        heading = "**`vault.ensure_file` — optionaler Legacy-Pfad**"
        assert heading in text, "docs/reference/vault.md braucht den Legacy-Statusabsatz"
        section = text[text.index(heading) :]
        assert "ANTHROPIC_API_KEY" in section
        assert "`None`" in section
        assert "files_api.FILES_API_BETA" in section


# ---------------------------------------------------------------------------
# Contract-Check: MCP-Tool-Signatur folgt der Funktion
# ---------------------------------------------------------------------------


def test_ensure_file_return_annotation_allows_none():
    """``ensure_file`` deklariert ``str | None`` -- der MCP-Contract folgt daraus."""
    import typing

    from academic_vault import server as server_module

    hints = typing.get_type_hints(server_module.ensure_file)
    assert hints["return"] == (str | None)
