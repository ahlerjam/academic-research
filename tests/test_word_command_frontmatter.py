"""Regressions-Test fuer commands/word.md Frontmatter (Issue #446, AC5).

Struktur analog tests/test_latex_command_frontmatter.py.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
COMMAND_FILE = REPO_ROOT / "commands" / "word.md"
COMMANDS_DOC = REPO_ROOT / "docs" / "reference" / "commands.md"


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
    assert COMMAND_FILE.exists(), f"commands/word.md fehlt: {COMMAND_FILE}"


def test_frontmatter_starts_with_dashes():
    lines = COMMAND_FILE.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---"


def test_frontmatter_has_closing_dashes():
    lines = COMMAND_FILE.read_text(encoding="utf-8").splitlines()
    closing = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    assert closing is not None, "commands/word.md hat kein schliessendes --- im Frontmatter"


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
    assert "Skill(document-skills:docx)" in allowed


def test_frontmatter_disable_model_invocation():
    fm = _parse_frontmatter(COMMAND_FILE)
    assert fm.get("disable-model-invocation") is True


def test_command_listed_in_docs():
    text = COMMANDS_DOC.read_text(encoding="utf-8")
    assert "/academic-research:word" in text, (
        "docs/reference/commands.md listet /academic-research:word nicht (AC5)."
    )
