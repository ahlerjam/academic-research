"""FilesAPIClient — optionaler Legacy-Pfad: Anthropic-Files-API-Cache fuer PDFs.

Status: LEGACY / OPTIONAL (Issue #535). Seit der Umstellung auf lokale
Verbatim-Zitate (#507/#512/#532) haengt kein Standard-Workflow mehr an diesem
Modul; gebraucht wird es nur noch fuer den optionalen Citations-API-Pfad, der
einen eigenen ANTHROPIC_API_KEY voraussetzt (siehe
skills/chapter-writer/references/citations-api.md).

Vertrag ohne Key: es wird KEIN Anthropic-Client gebaut. Aufrufer im
Standard-Flow bekommen ``None`` (``academic_vault.server.ensure_file``) bzw.
einen gezaehlten Skip (``zotero_pull``) — niemals eine Exception. Nur der
direkte Modul-Aufruf ohne Key wirft :class:`FilesAPINotConfiguredError`.

Gibt file_id zurueck (gecacht mit 1h-TTL in papers-Tabelle). Die
Beta-Abhaengigkeit der Anthropic-API ist auf die Konstante
:data:`FILES_API_BETA` isoliert.
"""

import os
import time
from pathlib import Path

from .db import VaultDB

_TTL = 3600  # 1 Stunde in Sekunden

# Einzige Stelle, an der die Files-API-Beta-Version im Repo steht (#535).
FILES_API_BETA = "files-api-2025-04-14"


class FilesAPINotConfiguredError(RuntimeError):
    """Kein ANTHROPIC_API_KEY vorhanden — der optionale Files-API-Pfad ist inaktiv."""


def is_configured(api_key: str = "") -> bool:
    """True, wenn ein ANTHROPIC_API_KEY vorliegt (Argument oder Umgebung).

    Zur Aufrufzeit ausgewertet, damit Aufrufer und Tests die Umgebung
    nachtraeglich setzen koennen.
    """
    return bool(api_key or os.environ.get("ANTHROPIC_API_KEY", ""))


class FilesAPIClient:
    """Anthropic Files-API-Client mit TTL-Cache in der Vault-Datenbank."""

    def __init__(self, anthropic_api_key: str, cache_db_path: str) -> None:
        self.api_key = anthropic_api_key
        self.cache_db_path = cache_db_path
        self._client = None  # lazy init

    def _get_client(self):
        """Lazy-Init des Anthropic-Clients.

        Raises:
            FilesAPINotConfiguredError: wenn kein API-Key gesetzt ist. Der
                Guard sitzt bewusst VOR dem SDK-Import, damit ohne Key weder
                ein Client gebaut noch ein Request versucht wird (#535).
        """
        if not self.api_key:
            raise FilesAPINotConfiguredError(
                "Files-API ist ein optionaler Pfad und braucht einen eigenen "
                "ANTHROPIC_API_KEY. Ohne Key gibt es keinen Upload."
            )
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _upload_file(self, pdf_path: str) -> str:
        """Laedt PDF hoch und gibt file_id zurueck.

        Nutzt anthropic.beta.files.upload mit dem Files-API-Beta-Header aus
        :data:`FILES_API_BETA` (einzige Stelle der Beta-Abhaengigkeit, #535).
        Kann in Tests per patch.object gemockt werden.
        """
        client = self._get_client()
        with open(pdf_path, "rb") as fh:
            response = client.beta.files.upload(
                file=(Path(pdf_path).name, fh, "application/pdf"),
                extra_headers={"anthropic-beta": FILES_API_BETA},
            )
        return response.id

    def ensure_file(self, pdf_path: str) -> str:
        """Gibt gecachte file_id zurueck, laedt hoch bei Cache-Miss.

        Prüft papers-Tabelle nach pdf_path. TTL = 3600s.
        Bei Ablauf oder fehlendem file_id wird re-uploaded.
        """
        now = int(time.time())

        conn = VaultDB._open(self.cache_db_path)
        try:
            row = conn.execute(
                "SELECT paper_id, file_id FROM papers "
                "WHERE pdf_path = ? AND file_id IS NOT NULL AND file_id_expires_at > ?",
                (pdf_path, now),
            ).fetchone()
            if row is not None:
                return row["file_id"]

            paper_row = conn.execute(
                "SELECT paper_id FROM papers WHERE pdf_path = ?", (pdf_path,)
            ).fetchone()
        finally:
            conn.close()

        # Cache-Miss: hochladen
        file_id = self._upload_file(pdf_path)
        if paper_row is not None:
            VaultDB(self.cache_db_path).set_file_id(paper_row["paper_id"], file_id, now + _TTL)
        return file_id

    @staticmethod
    def get_stats(db_path: str) -> dict:
        """Gibt Statistik-Dict zurueck: paper_count, quote_count, cached_files.

        Keine Token-Ersparnis-Schaetzung (#534): es gibt keinen Messpfad fuer
        tatsaechliche Token-Zahlen aus der Anthropic-API, jede solche Zahl waere
        eine unbelegte Phantomgroesse (Honesty-Linie #387/#453).
        """
        now = int(time.time())
        conn = VaultDB._open(db_path)
        paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        quote_count = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
        cached_files = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE file_id IS NOT NULL AND file_id_expires_at > ?",
            (now,),
        ).fetchone()[0]
        conn.close()

        return {
            "paper_count": paper_count,
            "quote_count": quote_count,
            "cached_files": cached_files,
        }
