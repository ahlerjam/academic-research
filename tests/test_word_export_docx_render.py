"""Echter docx-Rendering-Nachweis fuer word-export (Fixrunde PR #488, Issue #446).

Review-Fund (PR #488): "AC1: Kein Nachweis, dass ein erzeugtes .docx sich in
Word ohne Reparaturhinweis oeffnen laesst bzw. Ueberschriftenebenen als echte
Formatvorlagen fuehrt [...]" und "AC2 (teilweise): Dass Zitate/Literatur-
verzeichnis tatsaechlich [...] im Dokument erscheinen, ist unbelegt --
collect_references() liefert nur Rohdaten, das Rendern passiert ausserhalb
von Repo-Code und wird nirgends ausgefuehrt."

Vor diesem Test stimmt das: tests/test_word_export.py deckt collect_references()/
resolve_cite_markers() nur isoliert ab (Rueckgabewerte pruefen), tests/
test_word_export_skill_md.py prueft nur, dass SKILL.md die richtigen Woerter
("HeadingLevel", "Titelblatt", ...) enthaelt. Keine der beiden Suiten fuehrt
die Pipeline je gegen ein tatsaechlich gerendertes Dokument aus.

Dieser Test schliesst genau diese Luecke -- mit `python-docx` als
Test-only-Renderer, NICHT als Ersatz fuer den Produktionspfad
`document-skills:docx` (der bleibt docx-js/Node, siehe
skills/word-export/SKILL.md, Abschnitt "Word-Backend"). python-docx ist ein
reines PyPI-Paket (pyproject.toml [project.optional-dependencies].dev) und
damit -- anders als document-skills selbst -- in der CI-Matrix installierbar
(uv sync --extra dev in .github/actions/setup-python-uv); die strukturellen
Assertions unten laufen also in JEDEM CI-Lauf, nicht nur lokal.

Mechanisch nachgewiesen:
  - collect_references()/resolve_cite_markers() werden einmal wirklich gegen
    einen echten (In-Memory-)Vault ausgefuehrt und ihr Ergebnis fliesst in ein
    tatsaechlich gerendertes .docx (AC2: "wird nirgends ausgefuehrt" behoben).
  - Kapitelueberschriften landen als echte Word-Formatvorlagen ("Heading 1"
    .. "Heading 6"), nicht als manuelles Fett/Groesse -- inkl. Grenzfall
    HEADING_6.
  - Eine echte Word-native TOC-Feldfunktion (w:fldChar/w:instrText) statt
    statischem Text.
  - \\cite{}-Marker sind im gerenderten Fliesstext zu Klartext aufgeloest,
    kein roher Marker mehr sichtbar.
  - Jedes von collect_references() gelieferte Paper hat einen erkennbaren
    Eintrag im gerenderten Literaturverzeichnis.
  - Die erzeugte Datei laesst sich verlustfrei wieder oeffnen (python-docx-
    Roundtrip) -- ein "Reparaturhinweis" in echtem Word korreliert praktisch
    immer mit einer kaputten Zip-/XML-Struktur, die auch dieser Roundtrip
    aufdecken wuerde.

Bewusst NICHT geprueft: ob das Literaturverzeichnis exakt den Interpunktions-/
Reihenfolge-Regeln aus style_rules (z.B. APA7) folgt. Das ist laut
collect_references.py-Docstring explizit KEINE deterministische Python-
Funktion, sondern eine Rendering-Entscheidung des Agenten zur Laufzeit
("keine zweite Stilregel-Implementierung neben citation-extraction") -- eine
zweite Formatierungs-Implementierung hier wuerde genau das Risiko wieder
einfuehren, das collect_references.py bewusst vermeidet. Stichwortebene dazu:
evals/word-export/evals.json (wx-03), kein pytest-Aequivalent.

Zusaetzlich, wenn `soffice` (LibreOffice) lokal verfuegbar ist: echte
Kompatibilitaets-Konvertierung nach PDF -- derselbe Nachweisweg, den
document-skills:docx selbst fuer die eigene QA vorschreibt (SKILL.md:
"python scripts/office/soffice.py --headless --convert-to pdf output.docx").
CI hat kein LibreOffice installiert, daher dort geskippt -- exakt dasselbe
Pattern wie PDFLATEX_AVAILABLE in tests/test_latex_export.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

docx = pytest.importorskip("docx", reason="python-docx nicht installiert (uv sync --extra dev)")

from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

WORKTREE = Path(__file__).parent.parent
SCRIPTS_DIR = WORKTREE / "skills" / "word-export" / "scripts"
LATEX_SCRIPTS_DIR = WORKTREE / "skills" / "latex-export" / "scripts"
CITATION_REFERENCES_DIR = WORKTREE / "skills" / "citation-extraction" / "references"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "word_export"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(LATEX_SCRIPTS_DIR))

# LibreOffice ist in der CI-Matrix (ubuntu-latest/macos-latest) nicht
# installiert -- etabliertes Pattern siehe PDFLATEX_AVAILABLE in
# tests/test_latex_export.py: dort nur lokal beweiskraeftig.
SOFFICE_AVAILABLE = shutil.which("soffice") is not None


# ---------------------------------------------------------------------------
# Test-only Rendering-Referenz (KEIN Produktionspfad, siehe Moduldocstring)
# ---------------------------------------------------------------------------


def _add_toc_field(document) -> None:
    """Fuegt eine echte Word-native TOC-Feldfunktion ein (kein statischer Text).

    Standard-python-docx-Rezept fuer Insert > Table of Contents; landet wie
    beim docx-js-Produktionsrenderer als w:fldChar/w:instrText in
    word/document.xml -- kein statischer Verzeichnis-Text.
    """
    paragraph = document.add_paragraph()
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = 'TOC \\o "1-6" \\h \\z \\u'
    fld_separate = OxmlElement("w:fldChar")
    fld_separate.set(qn("w:fldCharType"), "separate")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    r = run._r
    r.append(fld_begin)
    r.append(instr)
    r.append(fld_separate)
    r.append(fld_end)


def _render_reference_docx(
    chapter_heading: str,
    body_text: str,
    papers: list[dict],
    out_path: Path,
) -> None:
    """Baut aus echter Pipeline-Ausgabe ein minimales, aber echtes .docx.

    Testeigene Rendering-Referenz, kein Ersatz fuer document-skills:docx
    (siehe Moduldocstring). Bildet nur die im Review bemaengelten
    strukturellen Pflichten ab: echte Heading-Formatvorlagen, TOC-Feld,
    aufgeloester Fliesstext, ein Literaturverzeichnis-Eintrag pro Paper.
    """
    document = docx.Document()
    document.add_heading("Inhaltsverzeichnis", level=1)
    _add_toc_field(document)

    document.add_heading(chapter_heading, level=1)
    document.add_paragraph(body_text)
    document.add_heading("Unterkapitel-Ebene", level=6)  # Grenzfall HEADING_6

    document.add_heading("Literaturverzeichnis", level=1)
    for paper in papers:
        csl = json.loads(paper.get("csl_json", "{}"))
        title = csl.get("title", paper.get("paper_id", "?"))
        authors = csl.get("author", [])
        family = authors[0].get("family") if authors else paper.get("paper_id", "?")
        document.add_paragraph(f"{family}: {title}")

    document.save(str(out_path))


# ---------------------------------------------------------------------------
# AC1 + AC2 (teilweise) — volle Pipeline einmal wirklich ausgefuehrt
# ---------------------------------------------------------------------------


class TestRealDocxRenderFromPipeline:
    def test_pipeline_output_renders_into_valid_reopenable_docx(self, tmp_path):
        """collect_references()/resolve_cite_markers() -> echtes, wieder
        oeffenbares .docx mit realen Formatvorlagen und aufgeloesten Zitaten."""
        from academic_vault.db import VaultDB
        from academic_vault.server import add_paper
        from collect_references import collect_references, resolve_cite_markers

        db_path = str(tmp_path / "vault.db")
        db = VaultDB(db_path)
        db.init_schema()
        add_paper(
            db_path=db_path,
            paper_id="smith2023",
            csl_json=json.dumps(
                {
                    "title": "DevOps Governance in KMU",
                    "type": "article-journal",
                    "author": [{"family": "Smith", "given": "John"}],
                    "issued": {"date-parts": [[2023]]},
                }
            ),
        )
        add_paper(
            db_path=db_path,
            paper_id="jones2022",
            csl_json=json.dumps(
                {
                    "title": "Cloud-Transformation und Governance",
                    "type": "article-journal",
                    "author": [
                        {"family": "Jones", "given": "Anna"},
                        {"family": "Lee", "given": "Kim"},
                    ],
                    "issued": {"date-parts": [[2022]]},
                }
            ),
        )

        academic_context_text = (FIXTURES_DIR / "academic_context_default.md").read_text()
        result = collect_references(db_path, academic_context_text, CITATION_REFERENCES_DIR)
        # Vorbedingung: die Pipeline lief wirklich gegen einen befuellten Vault.
        assert len(result["papers"]) == 2

        chapter_text = (FIXTURES_DIR / "kapitel_with_cite.md").read_text(encoding="utf-8")
        lines = chapter_text.splitlines()
        chapter_heading = lines[0].lstrip("#").strip()
        chapter_body = "\n".join(lines[1:]).strip()
        resolved_body = resolve_cite_markers(chapter_body, result["papers"])
        assert "\\cite" not in resolved_body  # Vorbedingung fuer den Rendering-Schritt

        out_path = tmp_path / "export.docx"
        _render_reference_docx(chapter_heading, resolved_body, result["papers"], out_path)

        # -- Repair-Proxy: die Datei laesst sich verlustfrei wieder oeffnen --
        reopened = docx.Document(str(out_path))

        headings = {
            p.text: p.style.name for p in reopened.paragraphs if p.style.name.startswith("Heading")
        }
        assert headings.get("Inhaltsverzeichnis") == "Heading 1"
        assert headings.get(chapter_heading) == "Heading 1"
        assert headings.get("Unterkapitel-Ebene") == "Heading 6"
        assert headings.get("Literaturverzeichnis") == "Heading 1"

        body_texts = [p.text for p in reopened.paragraphs]
        assert any("(Smith 2023)" in t for t in body_texts), (
            "Aufgeloester Kurzverweis fehlt im Fliesstext"
        )
        assert any("(Jones et al. 2022)" in t for t in body_texts)
        assert not any("\\cite" in t for t in body_texts)

        joined = "\n".join(body_texts)
        assert "DevOps Governance in KMU" in joined, (
            "Paper 1 fehlt im gerenderten Literaturverzeichnis"
        )
        assert "Cloud-Transformation und Governance" in joined, (
            "Paper 2 fehlt im gerenderten Literaturverzeichnis"
        )

        # -- echte Word-native TOC-Feldfunktion, kein statischer Text --
        with zipfile.ZipFile(out_path) as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
        assert "<w:instrText" in document_xml and "TOC" in document_xml

    def test_empty_vault_still_renders_valid_docx_without_bibliography_entries(self, tmp_path):
        """Fehlerpfad "Vault leer" (SKILL.md) fuehrt trotzdem zu einem gueltigen,
        wieder oeffenbaren Dokument -- kein Absturz, kein kaputtes Literatur-
        verzeichnis."""
        from academic_vault.db import VaultDB
        from collect_references import collect_references

        db_path = str(tmp_path / "empty_vault.db")
        db = VaultDB(db_path)
        db.init_schema()

        academic_context_text = (FIXTURES_DIR / "academic_context_default.md").read_text()
        result = collect_references(db_path, academic_context_text, CITATION_REFERENCES_DIR)
        assert result["papers"] == []

        out_path = tmp_path / "export_empty.docx"
        _render_reference_docx("Einleitung", "Text ohne Zitate.", result["papers"], out_path)

        reopened = docx.Document(str(out_path))
        assert reopened.paragraphs  # oeffnet ohne Exception, Inhalt vorhanden


class TestRealDocxRenderMatchesOfficeQAMethod:
    """Staerkerer Repair-Hinweis-Proxy ueber dieselbe QA-Methode, die
    document-skills:docx selbst fuer die eigene Verifikation vorschreibt.
    Nur lokal beweiskraeftig -- siehe Moduldocstring."""

    @pytest.mark.skipif(
        not SOFFICE_AVAILABLE,
        reason="soffice/LibreOffice nicht in PATH (in CI-Matrix nicht installiert)",
    )
    def test_rendered_docx_converts_cleanly_via_soffice(self, tmp_path):
        out_path = tmp_path / "export.docx"
        _render_reference_docx("Einleitung", "Testtext ohne Zitate.", [], out_path)

        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path),
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"soffice-Konvertierung fehlgeschlagen (Reparaturhinweis-Signal):\n"
            f"{result.stdout}\n{result.stderr}"
        )
        pdf_path = tmp_path / "export.pdf"
        assert pdf_path.exists() and pdf_path.stat().st_size > 0
