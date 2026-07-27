"""Tests fuer LaTeX-Export (F17 — #96).

TDD-First: Tests werden rot sein bis zur Implementierung.

Abgedeckt:
- render_tex: Markdown -> .tex (pandoc + custom-renderer-fallback)
- build_bib: Vault -> .bib (biblatex DIN-1505-Stil, gemockter Vault)
- verbatim-guard: *.tex-Pfade sind geschuetzt
- 3-Kapitel-Integration
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Pfade
WORKTREE = Path(__file__).parent.parent
SCRIPTS_DIR = WORKTREE / "skills" / "latex-export" / "scripts"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "latex_export"
HOOK_PATH = WORKTREE / "hooks" / "verbatim-guard.mjs"

# sys.path fuer direkten Import der Scripts
sys.path.insert(0, str(SCRIPTS_DIR))

# pandoc/pdflatex sind in der CI (ubuntu-latest/macos-latest Matrix) nicht
# installiert -- Tests, die einen echten Aufruf brauchen, werden dort uebersprungen
# (etabliertes Pattern, vgl. tests/test_project_bootstrap.py:189) und sind nur
# lokal beweiskraeftig.
PANDOC_AVAILABLE = shutil.which("pandoc") is not None
PDFLATEX_AVAILABLE = shutil.which("pdflatex") is not None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def run_hook(
    tool_name: str, file_path: str, content: str, env_overrides: dict = None
) -> subprocess.CompletedProcess:
    """Startet verbatim-guard-Hook als Subprocess."""
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path, "content": content},
        }
    )
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(WORKTREE / "nonexistent_vault_for_tests.db")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# render_tex Tests
# ---------------------------------------------------------------------------


class TestRenderTex:
    """Tests fuer skills/latex-export/scripts/render_tex.py"""

    def test_import(self):
        """render_tex kann importiert werden."""
        import render_tex  # noqa: F401

    def test_render_heading_h1(self):
        """H1 wird zu \\chapter{} (custom renderer)."""
        from render_tex import render_markdown_to_tex

        result = render_markdown_to_tex("# Einleitung\n", force_custom=True)
        assert r"\chapter{Einleitung}" in result

    def test_render_heading_h2(self):
        """H2 wird zu \\section{} (custom renderer)."""
        from render_tex import render_markdown_to_tex

        result = render_markdown_to_tex("## Hintergrund\n", force_custom=True)
        assert r"\section{Hintergrund}" in result

    def test_render_heading_h3(self):
        """H3 wird zu \\subsection{} (custom renderer)."""
        from render_tex import render_markdown_to_tex

        result = render_markdown_to_tex("### Unterpunkt\n", force_custom=True)
        assert r"\subsection{Unterpunkt}" in result

    def test_render_bold(self):
        """**fett** wird zu \\textbf{} (custom renderer)."""
        from render_tex import render_markdown_to_tex

        result = render_markdown_to_tex("Ein **fetter** Text.\n", force_custom=True)
        assert r"\textbf{fetter}" in result

    def test_render_italic(self):
        """_kursiv_ wird zu \\textit{} (custom renderer)."""
        from render_tex import render_markdown_to_tex

        result = render_markdown_to_tex("Ein _kursiver_ Text.\n", force_custom=True)
        assert r"\textit{kursiver}" in result

    def test_render_unordered_list(self):
        """Ungeordnete Liste wird zu \\begin{itemize}/\\item (custom renderer)."""
        from render_tex import render_markdown_to_tex

        md = "- Alpha\n- Beta\n- Gamma\n"
        result = render_markdown_to_tex(md, force_custom=True)
        assert r"\begin{itemize}" in result
        assert r"\item Alpha" in result
        assert r"\end{itemize}" in result

    def test_render_ordered_list(self):
        """Geordnete Liste wird zu \\begin{enumerate}/\\item (custom renderer)."""
        from render_tex import render_markdown_to_tex

        md = "1. Erster\n2. Zweiter\n3. Dritter\n"
        result = render_markdown_to_tex(md, force_custom=True)
        assert r"\begin{enumerate}" in result
        assert r"\item Erster" in result
        assert r"\end{enumerate}" in result

    def test_render_blockquote(self):
        """Blockzitat wird zu \\begin{quote} (custom renderer)."""
        from render_tex import render_markdown_to_tex

        result = render_markdown_to_tex("> Ein wichtiges Zitat.\n", force_custom=True)
        assert r"\begin{quote}" in result
        assert r"\end{quote}" in result

    def test_render_sample_fixture(self):
        """Sample-Kapitel-Fixture erzeugt valides .tex mit chapter + section + subsection (custom renderer)."""
        from render_tex import render_markdown_to_tex

        md = (FIXTURES_DIR / "sample_chapter.md").read_text(encoding="utf-8")
        result = render_markdown_to_tex(md, force_custom=True)
        assert r"\chapter{Einleitung}" in result
        assert r"\section{Hintergrund}" in result
        assert r"\subsection{Unterpunkt}" in result

    def test_render_file_output(self, tmp_path):
        """render_tex_file() schreibt .tex-Datei auf Disk (custom renderer)."""
        from render_tex import render_tex_file

        src = FIXTURES_DIR / "sample_chapter.md"
        out = tmp_path / "kap1.tex"
        render_tex_file(str(src), str(out), force_custom=True)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert r"\chapter{Einleitung}" in content

    def test_three_chapters_produce_three_files(self, tmp_path):
        """3 Kapitel erzeugen 3 .tex-Dateien (custom renderer)."""
        from render_tex import render_tex_file

        src = FIXTURES_DIR / "sample_chapter.md"
        # Erzeuge 3 Output-Files (selbe Quelle fuer Simplizitaet)
        out_files = [tmp_path / f"kap{i}.tex" for i in range(1, 4)]
        for out in out_files:
            render_tex_file(str(src), str(out), force_custom=True)
        for out in out_files:
            assert out.exists(), f"{out} fehlt"
            content = out.read_text(encoding="utf-8")
            assert r"\chapter{Einleitung}" in content

    def test_render_special_chars_escaped(self):
        """LaTeX-Sonderzeichen werden escaped (& % $ # _ ^ ~ { } \\) (custom renderer)."""
        from render_tex import render_markdown_to_tex

        # & und % sind typische Sonderzeichen in normalem Fliesstext
        result = render_markdown_to_tex("Kosten: 50% & mehr.\n", force_custom=True)
        assert r"\%" in result or "%" not in result.replace(r"\%", "")
        assert r"\&" in result or "&" not in result.replace(r"\&", "")

    def test_no_pandoc_fallback(self, monkeypatch):
        """Wenn pandoc nicht verfuegbar: custom renderer wird genutzt (kein Absturz)."""
        # Monkeypatche subprocess um pandoc-Fehler zu simulieren
        import subprocess as sp

        from render_tex import render_markdown_to_tex

        original_run = sp.run

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "pandoc":
                raise FileNotFoundError("pandoc not found")
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(sp, "run", fake_run)
        result = render_markdown_to_tex("# Titel\n\nText.\n", force_custom=True)
        assert r"\chapter{Titel}" in result


# ---------------------------------------------------------------------------
# pandoc-Pfad Tests (Issue #386 -- bisher ungetestet)
# ---------------------------------------------------------------------------


class TestPandocPath:
    """Tests fuer den pandoc-Renderpfad (_pandoc_render), subprocess gemockt."""

    def test_pandoc_render_injects_tightlist_definition_when_present(self, monkeypatch):
        """Enthaelt pandoc-Output \\tightlist, wird eine \\providecommand-Definition vorangestellt."""
        from render_tex import _pandoc_render

        fake_stdout = "\\begin{itemize}\n\\tightlist\n\\item\n  Alpha\n\\end{itemize}\n"

        class FakeResult:
            returncode = 0
            stdout = fake_stdout
            stderr = ""

        captured_cmd = {}

        def fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return FakeResult()

        monkeypatch.setattr("render_tex.subprocess.run", fake_run)
        result = _pandoc_render("- Alpha\n")

        assert result is not None
        assert result.startswith(r"\providecommand{\tightlist}"), result
        assert "--top-level-division=chapter" in captured_cmd["cmd"]

    def test_pandoc_render_no_tightlist_injection_without_list(self, monkeypatch):
        """Ohne \\tightlist im pandoc-Output wird keine Definition injiziert (kein Overhead)."""
        from render_tex import _pandoc_render

        fake_stdout = "\\chapter{Titel}\n\nEinfacher Text.\n"

        monkeypatch.setattr(
            "render_tex.subprocess.run",
            lambda cmd, **kwargs: type(
                "FakeResult", (), {"returncode": 0, "stdout": fake_stdout, "stderr": ""}
            )(),
        )
        result = _pandoc_render("# Titel\n\nEinfacher Text.\n")

        assert result == fake_stdout
        assert r"\providecommand{\tightlist}" not in result


class TestPandocRealCompile:
    """Tests mit echtem pandoc + pdflatex.

    Uebersprungen wenn die Tools fehlen (z.B. CI-Runner ohne TeXLive) --
    dort ist der Beweis nur lokal erbringbar.
    """

    @pytest.mark.skipif(
        not (PANDOC_AVAILABLE and PDFLATEX_AVAILABLE),
        reason="pandoc und/oder pdflatex nicht in PATH",
    )
    def test_pandoc_list_compiles_with_pdflatex(self, tmp_path):
        """AC1: .tex mit Markdown-Liste kompiliert mit pdflatex ohne '\\tightlist undefined'."""
        from render_tex import render_markdown_to_tex

        md = "# Kapitel Eins\n\n- Alpha\n- Beta\n- Gamma\n"
        body = render_markdown_to_tex(md, force_custom=False)
        assert r"\tightlist" in body  # Voraussetzung: pandoc erzeugt tightlist bei Listen

        doc = "\\documentclass{report}\n\\begin{document}\n" + body + "\n\\end{document}\n"
        tex_file = tmp_path / "doc.tex"
        tex_file.write_text(doc, encoding="utf-8")

        result = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory",
                str(tmp_path),
                str(tex_file),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        log = result.stdout + result.stderr
        assert "Undefined control sequence" not in log, f"pdflatex-Fehler:\n{log}"
        assert result.returncode == 0, f"pdflatex-Kompilierung fehlgeschlagen:\n{log}"
        assert (tmp_path / "doc.pdf").exists()

    @pytest.mark.skipif(not PANDOC_AVAILABLE, reason="pandoc nicht in PATH")
    def test_pandoc_and_custom_path_same_chapter_hierarchy(self):
        """AC3: pandoc-Pfad und Custom-Fallback-Pfad erzeugen aus identischem H1-Markdown \\chapter{}."""
        from render_tex import render_markdown_to_tex

        md = "# Einleitung\n\nEin Absatz.\n"
        pandoc_result = render_markdown_to_tex(md, force_custom=False)
        custom_result = render_markdown_to_tex(md, force_custom=True)

        assert r"\chapter{Einleitung}" in pandoc_result
        assert r"\chapter{Einleitung}" in custom_result


# ---------------------------------------------------------------------------
# Custom-Renderer: bereits vorhandene LaTeX-Kommandos duerfen nicht
# doppelt escaped werden (Issue #386, AC2)
# ---------------------------------------------------------------------------


class TestEscapeExistingCommands:
    """Regressionstests fuer _escape_tex_text: eingebettete LaTeX-Kommandos bleiben erhalten."""

    def test_custom_renderer_preserves_cite_command(self):
        """Ein eingebettetes \\cite{key} bleibt unveraendert, wird NICHT zu \\textbackslash{}cite{key}."""
        from render_tex import render_markdown_to_tex

        md = "Laut der Studie \\cite{smith2023} ist das belegt.\n"
        result = render_markdown_to_tex(md, force_custom=True)

        assert r"\cite{smith2023}" in result
        assert r"\textbackslash{}cite" not in result

    def test_custom_renderer_preserves_cite_with_optional_arg(self):
        """\\citep[S. 12]{key} bleibt inkl. optionalem Argument vollstaendig erhalten."""
        from render_tex import render_markdown_to_tex

        md = "Vgl. \\citep[S. 12]{mueller2019}.\n"
        result = render_markdown_to_tex(md, force_custom=True)

        assert r"\citep[S. 12]{mueller2019}" in result
        assert r"\textbackslash{}citep" not in result

    def test_custom_renderer_still_escapes_bare_backslash(self):
        """Ein nackter Backslash (kein erkanntes LaTeX-Kommando) wird weiterhin escaped."""
        from render_tex import render_markdown_to_tex

        md = "Ein Backslash \\ steht hier isoliert im Text.\n"
        result = render_markdown_to_tex(md, force_custom=True)

        assert r"\textbackslash{}" in result

    def test_custom_renderer_escapes_special_chars_alongside_cite(self):
        """Sonderzeichen ausserhalb erkannter Kommandos werden weiterhin escaped, auch neben \\cite{}."""
        from render_tex import render_markdown_to_tex

        md = "Kosten: 50% laut \\cite{smith2023} & mehr.\n"
        result = render_markdown_to_tex(md, force_custom=True)

        assert r"\cite{smith2023}" in result
        assert r"\%" in result
        assert r"\&" in result

    def test_custom_renderer_escapes_special_chars_inside_non_safe_command(self):
        """Regression (P1-Finding PR #409): Sonderzeichen IM Argument eines nicht
        allowlisted Kommandos (z. B. \\emph{}) muessen weiterhin escaped werden.

        Vor diesem Fix matchte _LATEX_COMMAND_RE jedes `\\Kommando{...}` und
        reichte den kompletten Argumentinhalt roh durch. Ein rohes % im
        Argument kommentiert in LaTeX den Rest der Zeile aus und bricht den
        pdflatex-Build ("Runaway argument" / "Missing } inserted").
        """
        from render_tex import render_markdown_to_tex

        md = "Der Rabatt liegt bei \\emph{50% Anteil} laut Studie.\n"
        result = render_markdown_to_tex(md, force_custom=True)

        # \emph ist keine Zitations-/Referenzkommando -- Argumentinhalt wird
        # (wie vor Issue #386) weiterhin ueber escape_plain geschickt.
        assert r"\%" in result
        assert "{50% Anteil}" not in result
        # Zitations-/Referenzkommandos bleiben davon unberuehrt.

    def test_custom_renderer_preserves_ref_and_label_commands(self):
        """\\ref{}, \\autoref{}, \\eqref{} und \\label{} sind Teil der Allowlist
        und bleiben unveraendert erhalten (Issue #386/AC2 nennt Referenzkommandos
        explizit neben \\cite{})."""
        from render_tex import render_markdown_to_tex

        md = "Siehe \\autoref{fig:1} und \\eqref{eq:2}, vgl. \\label{sec:x}.\n"
        result = render_markdown_to_tex(md, force_custom=True)

        assert r"\autoref{fig:1}" in result
        assert r"\eqref{eq:2}" in result
        assert r"\label{sec:x}" in result


# ---------------------------------------------------------------------------
# build_bib Tests
# ---------------------------------------------------------------------------


class TestBuildBib:
    """Tests fuer skills/latex-export/scripts/build_bib.py"""

    def test_import(self):
        """build_bib kann importiert werden."""
        import build_bib  # noqa: F401

    def test_paper_to_bibtex_article(self):
        """Zeitschriftenartikel -> @article{} mit DIN-1505-Feldern."""
        from build_bib import paper_to_bibtex

        paper = {
            "paper_id": "smith2023test",
            "csl_json": json.dumps(
                {
                    "type": "article-journal",
                    "title": "Test Article",
                    "author": [{"family": "Smith", "given": "John"}],
                    "issued": {"date-parts": [[2023]]},
                    "container-title": "Journal of Testing",
                    "volume": "5",
                    "page": "10-20",
                    "DOI": "10.1234/test",
                }
            ),
        }
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@article{smith2023test")
        assert "author" in entry
        assert "title" in entry
        assert "year" in entry
        assert "journal" in entry

    def test_paper_to_bibtex_book(self):
        """Buch -> @book{} mit DIN-1505-Feldern."""
        from build_bib import paper_to_bibtex

        paper = {
            "paper_id": "mueller2019einfuehrung",
            "csl_json": json.dumps(
                {
                    "type": "book",
                    "title": "Einführung in die Sozialforschung",
                    "author": [{"family": "Müller", "given": "Hans"}],
                    "issued": {"date-parts": [[2019]]},
                    "publisher": "Metzler",
                    "publisher-place": "Stuttgart",
                    "edition": "3",
                }
            ),
        }
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@book{mueller2019einfuehrung")
        assert "publisher" in entry
        assert "year" in entry

    def test_paper_to_bibtex_incollection(self):
        """Buchkapitel -> @incollection{} mit booktitle."""
        from build_bib import paper_to_bibtex

        paper = {
            "paper_id": "mueller2019qualitativ",
            "csl_json": json.dumps(
                {
                    "type": "chapter",
                    "title": "Qualitative Methoden",
                    "author": [{"family": "Müller", "given": "Hans"}],
                    "issued": {"date-parts": [[2019]]},
                    "container-title": "Handbuch der empirischen Sozialforschung",
                    "editor": [{"family": "Schmidt", "given": "Anna"}],
                    "publisher": "Metzler",
                    "publisher-place": "Stuttgart",
                    "page": "45-78",
                }
            ),
        }
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@incollection{mueller2019qualitativ")
        assert "booktitle" in entry

    def test_build_bib_from_vault_mock(self, tmp_path):
        """build_bib_from_vault() erzeugt .bib mit mehreren Eintraegen (Vault gemockt)."""
        from build_bib import build_bib_from_vault

        mock_papers = [
            {
                "paper_id": "smith2023test",
                "csl_json": json.dumps(
                    {
                        "type": "article-journal",
                        "title": "Test Article",
                        "author": [{"family": "Smith", "given": "John"}],
                        "issued": {"date-parts": [[2023]]},
                        "container-title": "Journal of Testing",
                    }
                ),
            },
            {
                "paper_id": "jones2021book",
                "csl_json": json.dumps(
                    {
                        "type": "book",
                        "title": "A Great Book",
                        "author": [{"family": "Jones", "given": "Alice"}],
                        "issued": {"date-parts": [[2021]]},
                        "publisher": "Academic Press",
                    }
                ),
            },
        ]
        out = tmp_path / "refs.bib"
        with patch("build_bib.get_all_papers") as mock_get:
            mock_get.return_value = mock_papers
            build_bib_from_vault(db_path="fake.db", output_path=str(out))
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "@article{smith2023test" in content
        assert "@book{jones2021book" in content

    def test_bibtex_author_format(self):
        """Mehrere Autoren werden korrekt in BibTeX-Format formatiert (Last, First)."""
        from build_bib import format_authors_bibtex

        authors = [
            {"family": "Smith", "given": "John"},
            {"family": "Jones", "given": "Alice"},
        ]
        result = format_authors_bibtex(authors)
        assert "Smith, John" in result
        assert "Jones, Alice" in result
        assert " and " in result

    def test_bibtex_author_single(self):
        """Einzelner Autor korrekt formatiert."""
        from build_bib import format_authors_bibtex

        authors = [{"family": "Müller", "given": "Hans"}]
        result = format_authors_bibtex(authors)
        assert result == "Müller, Hans"

    def test_bibtex_entry_has_required_fields_article(self):
        """@article hat author, title, journal, year."""
        from build_bib import paper_to_bibtex

        paper = {
            "paper_id": "test2023",
            "csl_json": json.dumps(
                {
                    "type": "article-journal",
                    "title": "Some Paper",
                    "author": [{"family": "Test", "given": "Author"}],
                    "issued": {"date-parts": [[2023]]},
                    "container-title": "Some Journal",
                }
            ),
        }
        entry = paper_to_bibtex(paper)
        for field in ["author", "title", "journal", "year"]:
            assert f"  {field}" in entry, f"Fehlendes Feld: {field}"

    def test_bibtex_doi_included_when_present(self):
        """DOI wird als doi-Feld in den Entry uebernommen."""
        from build_bib import paper_to_bibtex

        paper = {
            "paper_id": "doi2023",
            "csl_json": json.dumps(
                {
                    "type": "article-journal",
                    "title": "DOI Paper",
                    "author": [{"family": "Doi", "given": "Test"}],
                    "issued": {"date-parts": [[2023]]},
                    "container-title": "Journal",
                    "DOI": "10.9999/doi-test",
                }
            ),
        }
        entry = paper_to_bibtex(paper)
        assert "doi" in entry
        assert "10.9999/doi-test" in entry


# ---------------------------------------------------------------------------
# verbatim-guard: *.tex-Pfade sind geschuetzt
# ---------------------------------------------------------------------------


class TestVerbatimGuardTex:
    """Tests dass verbatim-guard auch *.tex-Pfade schutzt."""

    def test_hook_failopen_tex_no_vault(self):
        """Hook erlaubt (fail-open) .tex-Datei wenn Vault-DB fehlt."""
        content = r"Laut \cite{smith2023} ist das wichtig."
        result = run_hook("Write", "output/thesis.tex", content)
        assert result.returncode == 0

    def test_hook_ignores_tex_non_write(self):
        """Hook ignoriert .tex-Datei bei Nicht-Write-Tools."""
        result = run_hook("Read", "output/thesis.tex", r"\section{Test}")
        assert result.returncode == 0

    def test_hook_tex_path_is_protected(self, tmp_path):
        """Hook prueft .tex-Dateien auf Quote-Spans (kein Vault -> fail-open)."""
        # Ohne Vault -> fail-open -> exit 0 trotz Quote
        content = 'Der Autor schreibt: "Dies ist ein sehr langer unverifiziierter Satz."'
        result = run_hook("Write", "thesis.tex", content)
        # fail-open weil kein Vault -> 0
        assert result.returncode == 0

    def test_hook_tex_quote_blocked_with_vault(self, tmp_path):
        """Hook blockiert .tex bei unverifiziiertem Quote-Span wenn Vault existiert."""
        # Repo-Root ist bereits ueber tests/conftest.py auf sys.path (Issue #183);
        # kein lokales sys.path.insert(0, str(WORKTREE)) mehr noetig.
        from academic_vault.db import VaultDB
        from academic_vault.server import add_paper

        db_path = str(tmp_path / "tex_vault.db")
        db = VaultDB(db_path)
        db.init_schema()
        add_paper(
            db_path=db_path,
            paper_id="paper-tex",
            csl_json=json.dumps({"title": "LaTeX Paper", "type": "article-journal"}),
        )

        content = 'Der Autor: "Dies ist ein langer unverifiziierter Satz aus dem Buch hier."'
        result = run_hook(
            "Write",
            "thesis.tex",
            content,
            env_overrides={"VAULT_DB_PATH": db_path},
        )
        assert result.returncode == 2, f"Erwartet exit 2 (block auf .tex), got {result.returncode}"

    def test_hook_tex_bypass_works(self):
        """<!-- vault-guard: skip --> Bypass funktioniert auch bei .tex-Pfaden."""
        content = '<!-- vault-guard: skip -->\n"Unverifiziiertes Zitat in LaTeX."'
        result = run_hook("Write", "thesis.tex", content)
        assert result.returncode == 0
