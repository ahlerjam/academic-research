"""Regressionstest fuer Issue #515 -- citation-extraction-Doku auf den
local-verbatim-Standardpfad umstellen.

Ausgangslage laut Plan-Kommentar (`gh issue view 515`): `SKILL.md` beschreibt
die Claude-Citations-API (`documents[] + citations.enabled`) aktuell als
unconditional-Default (Uebersicht-Satz, eigene `## Citations-API`-Sektion,
Core-Workflow Schritt 2/3 mit `vault.ensure_file(paper_id)` als Standardweg).
Das weicht vom tatsaechlichen Agenten-Verhalten ab: `agents/quote-extractor.md`
(#514, bereits gemergt) nutzt `vault.get_paper(paper_id)` -> `pdf_path` ->
`Read` -> optional `vault.verify_verbatim()` ->
`vault.add_quote(..., extraction_method="local-verbatim")` als Standardpfad
(kein `ANTHROPIC_API_KEY` noetig), Citations-API nur noch als Opt-in mit
`api_response_id`-Pflichtfeld. Analog zu PR #587 (Issue #532, gleiches Muster
fuer chapter-writer/zotero-import/reading-notes) wird die Doku auf den
lokalen Pfad als Standard umgestellt.

AC1 - Standard-Workflow beschreibt den API-freien Pfad; Citations-API nur noch
      als Opt-in mit explizit genannter Key-Voraussetzung.
AC2 - Keine Anleitung im Skill verlangt mehr zwingend `ANTHROPIC_API_KEY`.
AC3 - Groessen-/Token-Baseline-Tests bleiben gruen (separat in
      `test_skills_manifest.py` abgedeckt; hier nur der Zeichen-Budget-Check).
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "citation-extraction"
SKILL_MD = SKILL_DIR / "SKILL.md"
OUTPUT_FORMATS_REF = SKILL_DIR / "references" / "output-formats.md"

# Marker, die eine Citations-/Files-API-Erwaehnung als optionalen Zusatzweg
# mit eigenem API-Key kennzeichnen (case-insensitiv) -- identisch zu #532.
OPTIONAL_MARKERS = ("optional", "eigenen api-key", "eigener api-key")

CITATIONS_FILES_API_PATTERN = re.compile(r"citations-api|files-api", re.IGNORECASE)
CONTEXT_WINDOW = 200  # Zeichen vor/nach dem Treffer

# Byte-Budget aus dem Plan-Kommentar: skill_sizes.json["citation-extraction"]
# (11296) - test_token_reduction verlangt >= 1400 Reduktion -> Obergrenze
# 9896 Zeichen.
MAX_SKILL_MD_CHARS = 9896


class TestAc1LocalVerbatimIsDefaultWorkflow:
    """AC1: Standard-Workflow beschreibt den API-freien Pfad."""

    def test_skill_md_documents_local_verbatim_extraction_method(self):
        body = SKILL_MD.read_text(encoding="utf-8")
        assert 'extraction_method="local-verbatim"' in body, (
            'SKILL.md muss den lokalen extraction_method="local-verbatim"-Weg als Standard nennen'
        )

    def test_skill_md_no_longer_promises_unconditional_citations_api(self):
        body = SKILL_MD.read_text(encoding="utf-8")
        assert "Nutzt die Claude-API `documents[] + citations.enabled`." not in body, (
            "Uebersicht-Satz bewirbt die Citations-API weiterhin als unconditional-Default"
        )

    def test_skill_md_does_not_require_ensure_file_as_default_extraction_path(self):
        body = SKILL_MD.read_text(encoding="utf-8")
        assert "vault.ensure_file(paper_id)` als `file_id`" not in body, (
            "Core-Workflow Schritt 2 darf vault.ensure_file() nicht mehr als "
            "Pflichtschritt fuer den Standard-Extraktionspfad beschreiben"
        )
        assert "Der Agent holt das PDF via `vault.ensure_file(paper_id)`" not in body, (
            "Core-Workflow Schritt 3 darf den Agenten-Pfad nicht mehr ueber "
            "vault.ensure_file() beschreiben (tatsaechlicher Agent nutzt "
            "vault.get_paper -> pdf_path -> Read)"
        )


class TestAc2NoMandatoryApiKey:
    """AC2: Keine Anleitung verlangt mehr zwingend ANTHROPIC_API_KEY."""

    def _tracked_files(self) -> list[pathlib.Path]:
        out = subprocess.run(
            ["git", "ls-files", str(SKILL_DIR)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return [REPO_ROOT / line for line in out.stdout.splitlines() if line]

    def test_citations_files_api_mentions_are_marked_optional(self):
        """Jeder citations-api/files-api-Treffer im gesamten Skill-Verzeichnis
        hat einen Optional-Marker im Kontextfenster (analog #532 AC3)."""
        unmarked = []
        for path in self._tracked_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lowered = text.lower()
            for match in CITATIONS_FILES_API_PATTERN.finditer(text):
                start = max(0, match.start() - CONTEXT_WINDOW)
                end = min(len(text), match.end() + CONTEXT_WINDOW)
                window = lowered[start:end]
                if not any(marker in window for marker in OPTIONAL_MARKERS):
                    unmarked.append(
                        f"{path.relative_to(REPO_ROOT)}: {text[match.start() : match.end()]!r}"
                    )
        assert unmarked == [], (
            f"Treffer ohne Optional-Marker im +/-{CONTEXT_WINDOW}-Zeichen-Fenster: {unmarked}"
        )

    def test_output_formats_reference_names_local_path_for_page_numbers(self):
        text = OUTPUT_FORMATS_REF.read_text(encoding="utf-8")
        assert "vault.get_quote" in text or "vault.find_quotes" in text, (
            "references/output-formats.md muss den lokalen Seitenzahl-Pfad "
            "(vault.find_quotes/vault.get_quote -> pdf_page) als Alternative "
            "zur Citations-API nennen"
        )


class TestAc3ByteBudget:
    """AC3: Groessen-Baseline bleibt eingehalten (dokumentierter Beweis fuer
    test_skills_manifest.py::test_token_reduction)."""

    def test_skill_md_stays_within_byte_budget(self):
        size = len(SKILL_MD.read_bytes())
        assert size <= MAX_SKILL_MD_CHARS, (
            f"SKILL.md ist {size} Bytes, Budget laut skill_sizes.json-Baseline "
            f"ist {MAX_SKILL_MD_CHARS} Bytes (11296 - 1400 Token-Reduction-Marge)"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
