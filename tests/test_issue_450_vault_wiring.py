"""Regressionstest fuer Issue #450 / PR #498, Fix-Runde AC4.

Ausgangslage laut Review-Fund: das neue `edition`-Feld der drei freien
Archiv-Fetcher (hathitrust-fetcher, internetarchive-fetcher, mdz-fetcher) war
zwar im Subagenten-Output-Vertrag definiert (siehe
``tests/test_free_archive_fetchers.py::TestEditionField``), erreichte aber nie
den Vault: ``agents/book-fetcher.md`` reichte `edition` nicht in seinem
eigenen Output-Schema durch, und ``commands/fetch.md`` rief bei `success`
niemals ``vault.add_paper()`` auf -- nur `literature_state.md` wurde
geschrieben. Issue #450 AC4 verlangt woertlich die korrekte Ausgabe-/
Jahresangabe des Digitalisats **im Vault**.

Die Weiterleitung durch den Router selbst ist in
``tests/test_book_fetcher.py::TestBookFetcherRouting`` per Python-Spiegel
abgedeckt (``test_oa_subagent_edition_field_propagates_to_master_output``).
Dieser Testmodul deckt die beiden Prompt-Vertraege ab, die nur als Markdown
existieren: das Output-Schema von ``agents/book-fetcher.md`` und die
Vault-Anbindung in ``commands/fetch.md``.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BOOK_FETCHER_AGENT = REPO_ROOT / "agents" / "book-fetcher.md"
FETCH_COMMAND = REPO_ROOT / "commands" / "fetch.md"


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    end = lines.index("---", 1)
    return "\n".join(lines[1:end])


class TestBookFetcherOutputSchemaPropagatesEdition:
    """Der Master-Output-Vertrag muss `edition` kennen, sonst kann Schritt 3
    das Feld der OA-Subagenten gar nicht erst weiterreichen."""

    def setup_method(self):
        self.body = BOOK_FETCHER_AGENT.read_text(encoding="utf-8")

    def test_output_schema_documents_edition_field(self):
        schema_match = re.search(
            r"##\s*Output-Schema(.*?)(?:\n##\s|\Z)", self.body, re.IGNORECASE | re.DOTALL
        )
        assert schema_match, "Kein Output-Schema-Abschnitt in agents/book-fetcher.md"
        assert '"edition"' in schema_match.group(1), (
            "Output-Schema von agents/book-fetcher.md muss ein 'edition'-Feld "
            "dokumentieren (AC4, Issue #450) -- sonst wird das Feld der "
            "OA-Subagenten am Master-Ausgang verworfen"
        )

    def test_step3_instructs_forwarding_edition_on_success(self):
        step3_match = re.search(
            r"##\s*Schritt 3(.*?)(?:\n##\s|\Z)", self.body, re.IGNORECASE | re.DOTALL
        )
        assert step3_match, "Kein 'Schritt 3'-Abschnitt in agents/book-fetcher.md"
        assert "edition" in step3_match.group(1).lower(), (
            "Schritt 3 (OA-Subagenten-Entscheidungslogik) muss erwaehnen, dass "
            "ein `edition`-Feld aus der Subagenten-Antwort in den Master-Output "
            "uebernommen wird (AC4)"
        )


class TestFetchCommandCallsVaultAddPaper:
    """AC4: Uebernommene Titel muessen die korrekte Ausgabe-/Jahresangabe im
    Vault tragen -- das setzt einen tatsaechlichen vault.add_paper()-Aufruf
    bei `success` voraus, nicht nur den literature_state.md-Block."""

    def setup_method(self):
        self.body = FETCH_COMMAND.read_text(encoding="utf-8")
        self.fm = _frontmatter(FETCH_COMMAND)

    def test_allowed_tools_declares_vault_add_paper_mcp_tool(self):
        assert "mcp__academic-vault__vault_add_paper" in self.fm, (
            "commands/fetch.md muss das MCP-Tool "
            "'mcp__academic-vault__vault_add_paper' in allowed-tools "
            "deklarieren, sonst kann der Aufruf zur Laufzeit nicht erlaubt sein"
        )

    def test_success_section_calls_vault_add_paper(self):
        success_section = self.body.split("#### Bei `success`", 1)[1].split("\n#### ", 1)[0]
        assert "vault.add_paper(" in success_section, (
            "Der `success`-Handler in commands/fetch.md muss vault.add_paper(...) "
            "aufrufen -- sonst erreicht kein Titel (und damit auch keine "
            "edition-Angabe) je den Vault (AC4, Issue #450)"
        )

    def test_vault_add_paper_call_sources_edition_from_result_not_input(self):
        success_section = self.body.split("#### Bei `success`", 1)[1].split("\n#### ", 1)[0]
        call_match = re.search(r"vault\.add_paper\((.*?)\)\n", success_section, re.DOTALL)
        assert call_match, "vault.add_paper(...)-Aufruf nicht gefunden oder nicht parsebar"
        call_body = call_match.group(1)
        assert "edition" in call_body, (
            "vault.add_paper(...) muss die edition-Angabe des Ergebnisses uebernehmen (AC4)"
        )
        assert "result.edition" in success_section or "result\\.edition" in success_section, (
            "Die edition-Angabe muss ausdruecklich aus dem Subagenten-/"
            "Router-Ergebnis (`result.edition`) stammen"
        )
        # Regressions-Schutz gegen die Eingabe als (falsche) Quelle der Edition,
        # analog zur Anforderung in den drei Fetcher-Agents selbst.
        lowered_section = success_section.lower()
        assert (
            "niemals aus" in lowered_section or "nicht aus identifier_value" in lowered_section
        ), (
            "commands/fetch.md muss -- wie die drei Fetcher-Agents selbst -- "
            "ausdruecklich ausschliessen, dass edition aus identifier_value/"
            "der Eingabe abgeleitet wird (AC4)"
        )

    def test_success_section_does_not_reintroduce_bold_quelle_field(self):
        """Regressions-Schutz: der neue Schritt darf das in Issue #459 entfernte
        `**Quelle:**`-Feld nicht versehentlich in den persistenten Block
        zurueckbringen."""
        success_section = self.body.split("#### Bei `success`", 1)[1].split("\n#### ", 1)[0]
        assert "**Quelle:**" not in success_section
