"""Tests fuer den bibliography-auditor Skill (Issue #391).

TDD: geschrieben gegen die Plan-Task-Checkliste aus dem Plan-Kommentar
<!-- plan:v1 --> zu Issue #391.

Abdeckung je Akzeptanzkriterium:
- AC1: SKILL.md existiert mit gueltigem Frontmatter (durch die glob-basierten
  Tests in tests/test_skills_manifest.py bereits abgedeckt, sobald der Skill
  einen Baseline-Eintrag hat -- hier zusaetzlich ein direkter Smoke-Test).
- AC2: Kapitel mit \\cite{ghost2020} ohne passendes Vault-Paper ->
  audit_bibliography() meldet ["ghost2020"] in missing_in_bibliography.
- AC3: Vault-Paper "p1", das in keinem Kapitel zitiert wird ->
  audit_bibliography() meldet ["p1"] in orphaned_entries.
- AC4: Nur lesend -- allowed-tools ohne Write/Edit/NotebookEdit und ohne
  schreibende MCP-Vault-Tool-Namen; Skript ruft keine schreibenden
  academic_vault-Funktionen auf.
- AC5: erfuellt durch AC2-/AC3-Tests selbst (dieser Testfall).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).parent.parent
SKILL_DIR = WORKTREE / "skills" / "bibliography-auditor"
SKILL_MD = SKILL_DIR / "SKILL.md"
SCRIPTS_DIR = WORKTREE / "skills" / "bibliography-auditor" / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "audit_bibliography.py"
LATEX_SCRIPTS_DIR = WORKTREE / "skills" / "latex-export" / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(LATEX_SCRIPTS_DIR))


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, "Kein YAML-Frontmatter gefunden"
    return m.group(1)


# ---------------------------------------------------------------------------
# AC1 -- SKILL.md-Struktur
# ---------------------------------------------------------------------------


class TestSkillMdStructure:
    def test_skill_md_exists(self):
        assert SKILL_MD.exists(), f"{SKILL_MD} fehlt"

    def test_frontmatter_has_name(self):
        fm = _frontmatter(SKILL_MD.read_text())
        assert re.search(r"^name:\s*bibliography-auditor\s*$", fm, re.M), (
            "name != bibliography-auditor"
        )

    def test_frontmatter_has_description(self):
        fm = _frontmatter(SKILL_MD.read_text())
        assert re.search(r"^description:\s*\S+", fm, re.M | re.S), "description fehlt"

    def test_frontmatter_has_mit_license(self):
        fm = _frontmatter(SKILL_MD.read_text())
        assert re.search(r"^license:\s*MIT\s*$", fm, re.M), "license != MIT"

    def test_mentions_submission_checker_delimitation(self):
        text = SKILL_MD.read_text()
        assert "submission-checker" in text, "Abgrenzung zu submission-checker fehlt"

    def test_mentions_mit_source(self):
        text = SKILL_MD.read_text()
        assert "andrehuang/academic-writing-agents" in text, "MIT-Quellenhinweis fehlt"


# ---------------------------------------------------------------------------
# AC4 -- Nur lesend
# ---------------------------------------------------------------------------

_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
_WRITE_VAULT_PREFIXES = ("add_", "update_", "lock_", "restore_", "supersede_", "set_")


class TestReadOnly:
    def test_allowed_tools_has_no_write_capability(self):
        text = SKILL_MD.read_text()
        m = re.search(r"^allowed-tools:\s*(.*?)(?=^\S|\Z)", text, re.M | re.S)
        assert m, "allowed-tools fehlt im Frontmatter"
        block = m.group(1)
        for tool in _WRITE_TOOLS:
            assert tool not in block, f"allowed-tools enthaelt schreibendes Tool '{tool}'"
        for prefix in _WRITE_VAULT_PREFIXES:
            assert prefix not in block, (
                f"allowed-tools enthaelt vermutlich schreibenden Vault-Tool-Namen "
                f"mit Praefix '{prefix}'"
            )
        assert "Read" in block, "allowed-tools enthaelt kein Read"

    def test_script_calls_no_writing_vault_functions(self):
        """String-Scan: audit_bibliography.py darf keine schreibenden
        academic_vault-Funktionen aufrufen (nur get_all_papers/resolve_chapters)."""
        text = SCRIPT_PATH.read_text()
        for prefix in _WRITE_VAULT_PREFIXES:
            assert f"vault_{prefix}" not in text and f"{prefix}paper" not in text, (
                f"audit_bibliography.py enthaelt vermutlich einen schreibenden "
                f"Vault-Aufruf (Praefix '{prefix}')"
            )
        assert "def get_all_papers" not in text, (
            "get_all_papers muss importiert, nicht kopiert sein"
        )


# ---------------------------------------------------------------------------
# AC2/AC3 -- Diff-Logik
# ---------------------------------------------------------------------------


class TestAuditBibliography:
    def test_missing_citation_reported_as_gap(self, tmp_path):
        """AC2: zitierter Key ohne Vault-Paper -> missing_in_bibliography."""
        from academic_vault.db import VaultDB

        db_path = str(tmp_path / "vault.db")
        VaultDB(db_path).init_schema()

        kapitel_dir = tmp_path / "kapitel"
        kapitel_dir.mkdir()
        (kapitel_dir / "1.md").write_text(
            "# Einleitung\n\nEin Beleg fehlt \\cite{ghost2020}.\n", encoding="utf-8"
        )

        from audit_bibliography import audit_bibliography

        result = audit_bibliography(str(kapitel_dir), "all", db_path)

        assert result["missing_in_bibliography"] == ["ghost2020"]
        assert result["orphaned_entries"] == []

    def test_uncited_paper_reported_as_orphan(self, tmp_path):
        """AC3: Vault-Paper, das in keinem Kapitel zitiert wird -> orphaned_entries."""
        from academic_vault.db import VaultDB
        from academic_vault.server import add_paper

        db_path = str(tmp_path / "vault.db")
        VaultDB(db_path).init_schema()
        add_paper(
            db_path=db_path,
            paper_id="p1",
            csl_json=json.dumps(
                {
                    "title": "Nie zitiert",
                    "type": "article-journal",
                    "author": [{"family": "Nobody", "given": "N"}],
                    "issued": {"date-parts": [[2021]]},
                }
            ),
        )

        kapitel_dir = tmp_path / "kapitel"
        kapitel_dir.mkdir()
        (kapitel_dir / "1.md").write_text("# Einleitung\n\nKein Zitat hier.\n", encoding="utf-8")

        from audit_bibliography import audit_bibliography

        result = audit_bibliography(str(kapitel_dir), "all", db_path)

        assert result["orphaned_entries"] == ["p1"]
        assert result["missing_in_bibliography"] == []

    def test_matching_citation_is_neither_missing_nor_orphaned(self, tmp_path):
        from academic_vault.db import VaultDB
        from academic_vault.server import add_paper

        db_path = str(tmp_path / "vault.db")
        VaultDB(db_path).init_schema()
        add_paper(
            db_path=db_path,
            paper_id="smith2023",
            csl_json=json.dumps(
                {
                    "title": "Passt",
                    "type": "article-journal",
                    "author": [{"family": "Smith", "given": "A"}],
                    "issued": {"date-parts": [[2023]]},
                }
            ),
        )

        kapitel_dir = tmp_path / "kapitel"
        kapitel_dir.mkdir()
        (kapitel_dir / "1.md").write_text(
            "# Einleitung\n\nBeleg \\cite{smith2023}.\n", encoding="utf-8"
        )

        from audit_bibliography import audit_bibliography

        result = audit_bibliography(str(kapitel_dir), "all", db_path)

        assert result["missing_in_bibliography"] == []
        assert result["orphaned_entries"] == []

    def test_multi_key_cite_marker_extracts_both_keys(self, tmp_path):
        from audit_bibliography import extract_cited_keys

        chapter = tmp_path / "1.md"
        chapter.write_text("Text \\cite{a,b} weiter.\n", encoding="utf-8")

        assert extract_cited_keys([chapter]) == {"a", "b"}

    def test_missing_chapter_dir_raises_chapter_resolution_error(self, tmp_path):
        from audit_bibliography import ChapterResolutionError, audit_bibliography

        db_path = str(tmp_path / "vault.db")
        with pytest.raises(ChapterResolutionError):
            audit_bibliography(str(tmp_path / "nope"), "all", db_path)


# ---------------------------------------------------------------------------
# CLI-Smoke-Test
# ---------------------------------------------------------------------------


class TestCli:
    def test_main_returns_zero_on_success(self, tmp_path, capsys):
        from academic_vault.db import VaultDB

        db_path = str(tmp_path / "vault.db")
        VaultDB(db_path).init_schema()

        kapitel_dir = tmp_path / "kapitel"
        kapitel_dir.mkdir()
        (kapitel_dir / "1.md").write_text("# Einleitung\n\nKein Zitat.\n", encoding="utf-8")

        from audit_bibliography import main

        exit_code = main(
            ["--kapitel", "all", "--kapitel-dir", str(kapitel_dir), "--vault-db", db_path]
        )
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Geprueft" in out

    def test_main_reports_error_on_missing_kapitel_dir(self, tmp_path, capsys):
        from audit_bibliography import main

        exit_code = main(
            [
                "--kapitel",
                "all",
                "--kapitel-dir",
                str(tmp_path / "nope"),
                "--vault-db",
                str(tmp_path / "vault.db"),
            ]
        )
        assert exit_code == 1
        err = capsys.readouterr().err
        assert err.startswith("FEHLER:")
