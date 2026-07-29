"""Regressions-Tests fuer skills/word-export/SKILL.md (Issue #446).

Prueft AC1 (echte Formatvorlagen statt manuellem Fett/Groesse), AC6
(verstaendliche Fehlermeldung statt Stacktrace bei fehlendem Backend) und die
dokumentierte Abgrenzung zu latex-export/citation-extraction/submission-checker.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / "skills" / "word-export" / "SKILL.md"
COMMAND_MD = REPO_ROOT / "commands" / "word.md"

BLOCK_START = "<!-- docx-backend:start -->"
BLOCK_END = "<!-- docx-backend:end -->"


@pytest.fixture(scope="module")
def skill_text():
    return SKILL_MD.read_text(encoding="utf-8")


def _backend_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert BLOCK_START in text and BLOCK_END in text, (
        f"{path.name}: Herkunfts-Textbaustein ({BLOCK_START} … {BLOCK_END}) fehlt."
    )
    return text.split(BLOCK_START, 1)[1].split(BLOCK_END, 1)[0]


class TestFrontmatter:
    def test_skill_md_exists(self):
        assert SKILL_MD.exists(), f"skills/word-export/SKILL.md fehlt: {SKILL_MD}"

    def test_name_matches_directory(self, skill_text):
        assert "name: word-export" in skill_text


class TestFormatvorlagenPflicht:
    """AC1: echte Formatvorlagen (HeadingLevel) statt manuellem Fett/Groesse."""

    def test_heading_level_mentioned(self, skill_text):
        assert "HeadingLevel" in skill_text, (
            "SKILL.md muss HeadingLevel.* (echte Formatvorlagen) vorschreiben."
        )

    def test_no_manual_bold_size_instruction(self, skill_text):
        assert "manuell" in skill_text.lower() and (
            "fett" in skill_text.lower()
            or "größe" in skill_text.lower()
            or "groesse" in skill_text.lower()
        ), "SKILL.md muss manuelles Fett/Groesse explizit ausschliessen."

    def test_table_of_contents_mentioned(self, skill_text):
        lower = skill_text.lower()
        assert "inhaltsverzeichnis" in lower or "toc" in lower

    def test_title_page_mentioned(self, skill_text):
        assert "Titelblatt" in skill_text

    def test_eidesstattliche_erklaerung_mentioned(self, skill_text):
        assert "eidesstattlich" in skill_text.lower()


class TestAbgrenzung:
    def test_latex_export_mentioned(self, skill_text):
        assert "latex-export" in skill_text

    def test_citation_extraction_mentioned(self, skill_text):
        assert "citation-extraction" in skill_text

    def test_submission_checker_mentioned(self, skill_text):
        assert "submission-checker" in skill_text

    def test_abgrenzung_section_exists(self, skill_text):
        assert "## Abgrenzung" in skill_text


class TestFehlerpfade:
    def test_error_section_exists(self, skill_text):
        assert "## Fehlerpfade" in skill_text

    def test_backend_missing_documented(self, skill_text):
        assert "Backend fehlt" in skill_text

    def test_vault_empty_documented(self, skill_text):
        assert "Vault leer" in skill_text

    def test_template_missing_documented(self, skill_text):
        assert "Template" in skill_text and "fehlt" in skill_text

    def test_style_rules_missing_documented(self, skill_text):
        assert "StyleRulesNotFoundError" in skill_text


class TestBackendBlockParityWithCommand:
    """AC6: Skill und Command beschreiben die Backend-Herkunft identisch."""

    def test_command_file_exists(self):
        assert COMMAND_MD.exists(), f"commands/word.md fehlt: {COMMAND_MD}"

    def test_skill_and_command_describe_same_backend(self):
        assert _backend_block(SKILL_MD) == _backend_block(COMMAND_MD), (
            "skills/word-export/SKILL.md und commands/word.md beschreiben die "
            "Herkunft des Word-Backends unterschiedlich."
        )

    def test_backend_block_names_upstream_plugin_and_marketplace(self):
        block = _backend_block(SKILL_MD)
        assert "document-skills:docx" in block
        assert "anthropic-agent-skills" in block
        assert "anthropics/skills" in block

    def test_backend_block_documents_recovery_path(self):
        block = _backend_block(SKILL_MD)
        assert "claude plugin marketplace add anthropics/skills" in block
        assert "claude plugin install document-skills@anthropic-agent-skills" in block
        assert "keine Word-Datei" in block

    def test_error_path_checks_availability_before_first_skill_call(self):
        block = _backend_block(SKILL_MD)
        assert "Vor dem ersten Skill-Aufruf" in block
        assert "Ist der Skill `document-skills:docx` aufrufbar?" in block
