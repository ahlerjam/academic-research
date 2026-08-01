"""Regressionstest fuer Issue #532 -- restliche Citations-/Files-API-Referenzen
auf local-verbatim umstellen (chapter-writer, zotero-import, reading-notes).

Ausgangslage laut Plan-Kommentar (`gh issue view 532`): `chapter-writer`,
`zotero-import` und `reading-notes` bewerben lokal die Citations-/Files-API
(Anthropic Beta, eigener `ANTHROPIC_API_KEY` noetig) als Standardweg, obwohl
der etablierte Default seit #512/#514/#525
`vault.add_quote(extraction_method="local-verbatim")` bzw. lokales
PDF-Lesen ist (kanonisch dokumentiert in `docs/reference/vault.md:117-139`).

AC1 - Keine Frontmatter-`description` verspricht mehr Files-API-Upload als
      Skill-Faehigkeit.
AC2 - chapter-writer dokumentiert den Zitat-Weg ueber Vault + local-verbatim;
      `references/citations-api.md` ist ersetzt oder eindeutig als optionaler
      API-Key-Pfad gekennzeichnet.
AC3 - `rg -i "citations-api|files-api" skills/chapter-writer skills/zotero-import
      skills/reading-notes` trifft nur noch explizit als optional
      gekennzeichnete Stellen.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
CHAPTER_WRITER_SKILL = REPO_ROOT / "skills" / "chapter-writer" / "SKILL.md"
CHAPTER_WRITER_CITATIONS_API_REF = (
    REPO_ROOT / "skills" / "chapter-writer" / "references" / "citations-api.md"
)
ZOTERO_IMPORT_SKILL = REPO_ROOT / "skills" / "zotero-import" / "SKILL.md"
READING_NOTES_SKILL = REPO_ROOT / "skills" / "reading-notes" / "SKILL.md"

# Marker, die eine Citations-/Files-API-Erwaehnung als optionalen
# Zusatzweg mit eigenem API-Key kennzeichnen (case-insensitiv).
OPTIONAL_MARKERS = ("optional", "eigenen api-key", "eigener api-key")

# Fundstellen-Pattern fuer AC3 (Kontextfenster-Check).
CITATIONS_FILES_API_PATTERN = re.compile(r"citations-api|files-api", re.IGNORECASE)
CONTEXT_WINDOW = 200  # Zeichen vor/nach dem Treffer


def _frontmatter_description(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} ohne Frontmatter"
    end = text.index("\n---\n", 4)
    frontmatter = text[4:end]
    m = re.search(r"^description:\s*(.*(?:\n\s{2,}.*)*)", frontmatter, re.MULTILINE)
    assert m, f"{path}: description-Frontmatter fehlt"
    # YAML-Block-Skalar (">") oder Single-Line -- beide Faelle sind fuer
    # diesen Test reine Textsuche, kein voller YAML-Parse noetig.
    return m.group(1)


class TestAc1DescriptionDoesNotPromiseFilesApiUpload:
    """AC1: Keine Frontmatter-description verspricht Files-API-Upload."""

    def test_zotero_import_description_does_not_promise_files_api_upload(self):
        description = _frontmatter_description(ZOTERO_IMPORT_SKILL)
        assert "Files-API" not in description, (
            "zotero-import description bewirbt Files-API-Upload als "
            "Kernfaehigkeit -- lokaler pdf_path via add_paper() ist der Default"
        )

    def test_chapter_writer_description_does_not_promise_files_api_upload(self):
        description = _frontmatter_description(CHAPTER_WRITER_SKILL)
        assert "Files-API" not in description

    def test_reading_notes_description_does_not_promise_files_api_upload(self):
        description = _frontmatter_description(READING_NOTES_SKILL)
        assert "Files-API" not in description


class TestAc2ChapterWriterDocumentsLocalVerbatimAsDefault:
    """AC2: chapter-writer nennt local-verbatim als Standardweg."""

    def test_chapter_writer_documents_local_verbatim_as_default(self):
        body = CHAPTER_WRITER_SKILL.read_text(encoding="utf-8")
        assert 'extraction_method="local-verbatim"' in body, (
            "chapter-writer/SKILL.md muss den lokalen "
            'extraction_method="local-verbatim"-Weg als Standard nennen'
        )

    def test_citations_api_reference_marks_optional_api_key(self):
        assert CHAPTER_WRITER_CITATIONS_API_REF.exists(), (
            "references/citations-api.md fehlt -- laut AC2 muss die Datei "
            "entweder ersetzt oder als optionaler Pfad markiert sein"
        )
        text = CHAPTER_WRITER_CITATIONS_API_REF.read_text(encoding="utf-8").lower()
        assert any(marker in text for marker in OPTIONAL_MARKERS), (
            "references/citations-api.md muss einen Optional-/API-Key-Marker "
            f"enthalten ({OPTIONAL_MARKERS})"
        )
        cleaned = text.replace("$", "").replace("{", "").replace("}", "")
        assert "anthropic_api_key" in cleaned, (
            "references/citations-api.md muss auf den eigenen ANTHROPIC_API_KEY hinweisen"
        )


SKILL_PATHS_FOR_AC3 = [CHAPTER_WRITER_SKILL, ZOTERO_IMPORT_SKILL, READING_NOTES_SKILL]


@pytest.mark.parametrize("skill_path", SKILL_PATHS_FOR_AC3, ids=lambda p: p.parent.name)
def test_citations_files_api_mentions_are_marked_optional(skill_path: pathlib.Path) -> None:
    """AC3: jede citations-api/files-api-Erwaehnung hat einen Optional-Marker im Kontextfenster."""
    text = skill_path.read_text(encoding="utf-8")
    lowered = text.lower()
    # Vollstaendige Entfernung aller Treffer ist eine gueltige Loesung (z. B.
    # reading-notes) -- diese Assertion prueft nur, dass JEDER verbleibende
    # Treffer einen Optional-Marker im Kontextfenster hat, nicht dass
    # mindestens einer existieren muss.
    matches = list(CITATIONS_FILES_API_PATTERN.finditer(text))
    unmarked = []
    for match in matches:
        start = max(0, match.start() - CONTEXT_WINDOW)
        end = min(len(text), match.end() + CONTEXT_WINDOW)
        window = lowered[start:end]
        if not any(marker in window for marker in OPTIONAL_MARKERS):
            unmarked.append(text[match.start() : match.end()])
    assert unmarked == [], (
        f"{skill_path}: Treffer ohne Optional-Marker im ±{CONTEXT_WINDOW}-Zeichen-"
        f"Fenster: {unmarked}"
    )


class TestAc2ReadingNotesUsesLocalPdfRead:
    """AC2 (sinngemaess auf reading-notes uebertragen): kein Files-API-Lesepfad."""

    def test_reading_notes_references_local_paper_read_not_files_api(self):
        body = READING_NOTES_SKILL.read_text(encoding="utf-8")
        assert "Files-API" not in body, (
            "reading-notes/SKILL.md soll PDF-Volltext lokal via "
            "vault.get_paper()/Read lesen, nicht ueber die Files-API"
        )
        assert "vault.get_paper()" in body
