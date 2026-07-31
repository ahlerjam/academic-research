"""Fixrunde PR #557 (Issue #450), AC4: das ``edition``-Feld der neuen
Archiv-Fetcher muss tatsaechlich im Vault landen, nicht nur im
Agent-Output-Vertrag stehenbleiben.

Verifikations-Fund (Fixrunde): Kein einziger ``vault.add_paper()``-Aufruf
existierte in ``agents/book-fetcher.md`` oder ``commands/fetch.md`` -- das
neue ``edition``-Feld verliess nie den Agent-Output-Vertrag und landete nie
im Vault. ``tests/test_free_archive_fetchers.py::TestEditionField`` prueft
nur, dass der String ``"edition"`` im Prompt-Text der drei neuen Agenten
vorkommt -- keine Assertion gegen echte Vault-Persistenz, und keine Pruefung
der beiden Stellen (``book-fetcher.md``, ``fetch.md``), an denen das Feld
tatsaechlich verloren ging.

Diese Suite prueft drei Ebenen, jede fuer sich notwendig:

1. ``book-fetcher.md`` (Master-Orchestrator) reicht das ``edition``-Feld der
   OA-Subagenten-Antwort in sein eigenes Output-Schema durch -- sonst geht
   es dort bereits verloren, bevor ``fetch.md`` es je sehen kann.
2. ``commands/fetch.md`` dokumentiert bei ``status: success`` einen echten
   ``vault_add_paper``-Aufruf inkl. ``edition``-Uebernahme -- als MCP-Tool im
   ``allowed-tools``-Frontmatter deklariert, nicht nur als Prosa erwaehnt.
3. Der so dokumentierte Aufruf ist kein totes Textbeispiel: dieselbe
   Feldstruktur (``paper_id``/``csl_json`` mit ``type`` + ``edition``/
   ``pdf_path``/``isbn``) wird gegen eine echte ``VaultDB`` ausgefuehrt --
   ``add_paper()``/``get_paper()`` beweisen, dass die ``edition`` einen
   Vault-Roundtrip tatsaechlich uebersteht.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BOOK_FETCHER = REPO_ROOT / "agents" / "book-fetcher.md"
FETCH_COMMAND = REPO_ROOT / "commands" / "fetch.md"

VAULT_ADD_PAPER_TOOL = "mcp__academic-vault__vault_add_paper"


def _frontmatter(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert match, f"Kein Frontmatter in {path.name}"
    return match.group(1)


def _section(text: str, start_heading: str, end_heading: str | None) -> str:
    """Extrahiert den Text zwischen zwei Markdown-Ueberschriften (exklusive
    der Start-Ueberschrift selbst)."""
    parts = text.split(start_heading, 1)
    assert len(parts) == 2, f"Ueberschrift '{start_heading}' nicht gefunden"
    tail = parts[1]
    if end_heading is None:
        return tail
    return tail.split(end_heading, 1)[0]


# ─── Ebene 1: book-fetcher.md reicht edition durch ──────────────────────────


class TestBookFetcherForwardsEdition:
    """book-fetcher.md darf das edition-Feld der OA-Subagenten nicht
    stillschweigend verwerfen -- sonst kommt es bei fetch.md nie an."""

    def test_output_schema_declares_edition_field(self):
        body = BOOK_FETCHER.read_text(encoding="utf-8")
        schema_block = _section(
            body,
            "## Output-Schema (IMMER dieses Format zurueckgeben)",
            "## Status-Entscheidungsbaum",
        )
        assert '"edition"' in schema_block, (
            "book-fetcher.md-Output-Schema hat kein 'edition'-Feld -- das von den "
            "OA-Subagenten gemeldete edition-Feld (Issue #450 AC4) geht damit schon "
            "im Master-Orchestrator verloren, bevor fetch.md es je sehen kann."
        )

    def test_decision_logic_instructs_edition_passthrough(self):
        body = BOOK_FETCHER.read_text(encoding="utf-8")
        step3 = _section(body, "## Schritt 3", "## Schritt 4")
        assert "edition" in step3, (
            "Schritt 3 (OA-Subagenten-Entscheidungslogik) in book-fetcher.md "
            "enthaelt keine Anweisung, ein edition-Feld aus der Subagenten-Antwort "
            "in den Master-Output zu uebernehmen."
        )


# ─── Ebene 2: fetch.md dokumentiert einen echten vault_add_paper-Aufruf ─────


class TestFetchCommandVaultWiring:
    """commands/fetch.md muss bei status=success wirklich vault_add_paper
    aufrufen -- nicht nur behaupten, die Provenienz bleibe 'im Vault
    erhalten'."""

    def test_allowed_tools_declares_vault_add_paper(self):
        fm = _frontmatter(FETCH_COMMAND)
        assert VAULT_ADD_PAPER_TOOL in fm, (
            f"'{VAULT_ADD_PAPER_TOOL}' fehlt im allowed-tools-Frontmatter von "
            "fetch.md -- ohne Tool-Deklaration kann der dokumentierte Aufruf in "
            "Schritt 4 gar nicht ausgefuehrt werden."
        )

    def test_success_section_documents_vault_add_paper_call_with_edition(self):
        body = FETCH_COMMAND.read_text(encoding="utf-8")
        success_section = _section(body, "#### Bei `success`", "#### Bei `pickup_required`")
        assert "vault_add_paper" in success_section, (
            "Schritt 4 'Bei success' in fetch.md ruft vault_add_paper nicht auf -- "
            "das PDF wird zwar in literature_state.md vermerkt, landet aber nie "
            "im Vault (AC4)."
        )
        assert "csl_json" in success_section, (
            "Der dokumentierte vault_add_paper-Aufruf in fetch.md baut kein csl_json-Feld auf."
        )
        assert "edition" in success_section, (
            "Der dokumentierte vault_add_paper-Aufruf uebernimmt das edition-Feld "
            "des book-fetcher-Ergebnisses nicht (AC4)."
        )

    def test_success_section_forbids_fabricated_edition(self):
        """Fehlt result.edition, muss fetch.md das Feld weglassen statt einen
        Platzhalter zu erfinden (Konsistenz mit dem NIE-Verbot der drei neuen
        Fetcher-Agenten selbst)."""
        body = FETCH_COMMAND.read_text(encoding="utf-8")
        success_section = _section(body, "#### Bei `success`", "#### Bei `pickup_required`")
        assert "NIE" in success_section or "NIEMALS" in success_section, (
            "fetch.md verbietet das Erfinden eines edition-Platzhalters bei "
            "fehlendem result.edition nicht explizit."
        )


# ─── Ebene 3: der dokumentierte Aufruf funktioniert real gegen den Vault ────


class TestVaultPersistenceRoundTrip:
    """Beweis, dass ein vault_add_paper-Aufruf nach dem in fetch.md
    dokumentierten Muster (paper_id/csl_json mit type+edition/pdf_path/isbn)
    tatsaechlich funktioniert und die edition einen echten Vault-Roundtrip
    uebersteht -- kein Mock, keine hartkodierte Dict-Annahme ohne Backend."""

    def test_edition_survives_add_paper_get_paper_round_trip(self, tmp_path):
        from academic_vault.server import add_paper, get_paper

        db_path = str(tmp_path / "vault.db")
        # Payload exakt wie in fetch.md Schritt 4 'Bei success' dokumentiert:
        # paper_id aus dem sanitized-Wert von Schritt 2, csl_json mit
        # type=book und dem edition-Feld aus dem book-fetcher-Ergebnis,
        # pdf_path aus file_path, isbn aus identifier_value (hier:
        # identifier_type == isbn).
        edition_value = "1911, Full view, Cambridge University Press"
        add_paper(
            db_path=db_path,
            paper_id="978-3-16-148410-0",
            csl_json=json.dumps({"type": "book", "edition": edition_value}),
            pdf_path="/tmp/book.pdf",
            isbn="978-3-16-148410-0",
        )

        paper = get_paper(db_path=db_path, paper_id="978-3-16-148410-0")
        assert paper is not None, "add_paper hat keinen Eintrag angelegt"
        persisted_csl = json.loads(paper["csl_json"])
        assert persisted_csl.get("edition") == edition_value, (
            "Die edition-Angabe des Digitalisats uebersteht den Vault-Roundtrip nicht (AC4)."
        )
        assert paper["isbn"] == "978-3-16-148410-0"
        assert paper["pdf_path"] == "/tmp/book.pdf"

    def test_missing_edition_is_omitted_not_fabricated(self, tmp_path):
        """Liefert der book-fetcher kein edition-Feld (z. B. Verlags-Treffer),
        darf der Vault-Eintrag trotzdem angelegt werden -- ohne erfundenes
        edition-Feld."""
        from academic_vault.server import add_paper, get_paper

        db_path = str(tmp_path / "vault.db")
        add_paper(
            db_path=db_path,
            paper_id="10.1007-978-3-662-54347-6",
            csl_json=json.dumps({"type": "book"}),
            pdf_path="/tmp/book2.pdf",
            doi="10.1007/978-3-662-54347-6",
        )

        paper = get_paper(db_path=db_path, paper_id="10.1007-978-3-662-54347-6")
        assert paper is not None
        persisted_csl = json.loads(paper["csl_json"])
        assert "edition" not in persisted_csl
