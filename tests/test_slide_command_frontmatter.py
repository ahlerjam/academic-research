"""Regressions-Test fuer commands/slides.md Frontmatter (Issue #446, AC5).

Struktur analog tests/test_latex_command_frontmatter.py /
tests/test_word_command_frontmatter.py.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
COMMAND_FILE = REPO_ROOT / "commands" / "slides.md"
COMMANDS_DOC = REPO_ROOT / "docs" / "reference" / "commands.md"
SKILL_MD = REPO_ROOT / "skills" / "slide-export" / "SKILL.md"


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}
    return yaml.safe_load("\n".join(lines[1:end])) or {}


def test_command_file_exists():
    assert COMMAND_FILE.exists(), f"commands/slides.md fehlt: {COMMAND_FILE}"


def test_frontmatter_starts_with_dashes():
    lines = COMMAND_FILE.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---"


def test_frontmatter_has_closing_dashes():
    lines = COMMAND_FILE.read_text(encoding="utf-8").splitlines()
    closing = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    assert closing is not None, "commands/slides.md hat kein schliessendes --- im Frontmatter"


def test_frontmatter_description_not_empty():
    fm = _parse_frontmatter(COMMAND_FILE)
    assert fm.get("description", ""), f"description fehlt oder leer (Frontmatter: {fm!r})"


def test_frontmatter_argument_hint():
    fm = _parse_frontmatter(COMMAND_FILE)
    hint = fm.get("argument-hint", "")
    assert hint, f"argument-hint fehlt oder leer (Frontmatter: {fm!r})"
    assert "--kapitel" in hint
    assert "--output" in hint


def test_frontmatter_allowed_tools():
    fm = _parse_frontmatter(COMMAND_FILE)
    allowed = fm.get("allowed-tools", "")
    assert allowed, f"allowed-tools fehlt oder leer (Frontmatter: {fm!r})"
    assert "Skill(document-skills:pptx)" in allowed


def test_frontmatter_disable_model_invocation():
    fm = _parse_frontmatter(COMMAND_FILE)
    assert fm.get("disable-model-invocation") is True


def test_command_listed_in_docs():
    text = COMMANDS_DOC.read_text(encoding="utf-8")
    assert "/academic-research:slides" in text, (
        "docs/reference/commands.md listet /academic-research:slides nicht (AC5)."
    )


# ---------------------------------------------------------------------------
# skills/slide-export/SKILL.md — Struktur-Checks (kein eigenes Testfile laut
# Plan; hier mitgefuehrt statt eines sechsten Testfiles)
# ---------------------------------------------------------------------------


class TestSlideSkillMd:
    def test_skill_md_exists(self):
        assert SKILL_MD.exists(), f"skills/slide-export/SKILL.md fehlt: {SKILL_MD}"

    def test_one_core_statement_per_slide_documented(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "Kernaussage" in text

    def test_abgrenzung_to_word_export(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "word-export" in text

    def test_backend_block_present(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "<!-- pptx-backend:start -->" in text
        assert "<!-- pptx-backend:end -->" in text

    def test_backend_block_parity_with_command(self):
        skill_text = SKILL_MD.read_text(encoding="utf-8")
        command_text = COMMAND_FILE.read_text(encoding="utf-8")
        skill_block = skill_text.split("<!-- pptx-backend:start -->", 1)[1].split(
            "<!-- pptx-backend:end -->", 1
        )[0]
        command_block = command_text.split("<!-- pptx-backend:start -->", 1)[1].split(
            "<!-- pptx-backend:end -->", 1
        )[0]
        assert skill_block == command_block
