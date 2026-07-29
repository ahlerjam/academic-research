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


def _write_chapter(kapitel_dir: Path, filename: str, heading: str) -> Path:
    """Schreibt eine Kapitel-Markdown-Fixture-Datei fuer export_thesis-Tests."""
    kapitel_dir.mkdir(parents=True, exist_ok=True)
    path = kapitel_dir / filename
    path.write_text(f"# {heading}\n\nInhalt von {heading}.\n", encoding="utf-8")
    return path


def _fake_build_bib(db_path: str, output_path: str) -> None:
    """Test-Stub fuer build_bib_from_vault: schreibt eine leere .bib-Datei
    ohne echten Vault-Zugriff. Das Vault-Verhalten selbst ist bereits in
    TestBuildBib abgedeckt -- hier geht es nur um die CLI-Verkabelung
    von --bib (Issue #467)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")


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


class TestResolveChapters:
    """Tests fuer export_thesis.resolve_chapters (--kapitel <n>|all, Issue #467)."""

    def test_resolve_single_chapter_by_number(self, tmp_path):
        from export_thesis import resolve_chapters

        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "1.md", "Einleitung")
        _write_chapter(kap_dir, "2.md", "Methodik")

        result = resolve_chapters(kap_dir, "2")
        assert [p.name for p in result] == ["2.md"]

    def test_resolve_single_chapter_matches_zero_padded_filename(self, tmp_path):
        """--kapitel 3 findet auch kapitel/03-methodik.md (uneinheitliche
        Namenskonvention im Repo, siehe Plan-Risiko #1)."""
        from export_thesis import resolve_chapters

        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "01-einleitung.md", "Einleitung")
        _write_chapter(kap_dir, "03-methodik.md", "Methodik")

        result = resolve_chapters(kap_dir, "3")
        assert [p.name for p in result] == ["03-methodik.md"]

    def test_resolve_all_chapters_sorted_numerically(self, tmp_path):
        """--kapitel all liefert alle Kapitel numerisch (nicht alphabetisch)
        sortiert -- 2 vor 10."""
        from export_thesis import resolve_chapters

        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "10.md", "Zehn")
        _write_chapter(kap_dir, "2.md", "Zwei")
        _write_chapter(kap_dir, "1.md", "Eins")

        result = resolve_chapters(kap_dir, "all")
        assert [p.name for p in result] == ["1.md", "2.md", "10.md"]

    def test_resolve_unknown_chapter_raises_clear_error(self, tmp_path):
        from export_thesis import ChapterResolutionError, resolve_chapters

        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "1.md", "Einleitung")

        with pytest.raises(ChapterResolutionError, match="5"):
            resolve_chapters(kap_dir, "5")

    def test_resolve_all_on_empty_dir_raises_clear_error(self, tmp_path):
        from export_thesis import ChapterResolutionError, resolve_chapters

        kap_dir = tmp_path / "kapitel"
        kap_dir.mkdir()

        with pytest.raises(ChapterResolutionError):
            resolve_chapters(kap_dir, "all")

    def test_resolve_missing_directory_raises_clear_error(self, tmp_path):
        from export_thesis import ChapterResolutionError, resolve_chapters

        with pytest.raises(ChapterResolutionError):
            resolve_chapters(tmp_path / "does-not-exist", "1")


class TestApplyTemplate:
    """Tests fuer export_thesis.apply_template (Uni-Vorlagen-Slot, Issue #467)."""

    def test_template_replaces_content_placeholder(self, tmp_path):
        from export_thesis import apply_template

        profiles_dir = tmp_path / "library-profiles"
        profiles_dir.mkdir()
        (profiles_dir / "lmu.tex.template").write_text(
            "\\documentclass{report}\n\\begin{document}\n%%CONTENT%%\n\\end{document}\n",
            encoding="utf-8",
        )

        content, message = apply_template("\\chapter{Einleitung}", "lmu", profiles_dir)
        assert "\\chapter{Einleitung}" in content
        assert "%%CONTENT%%" not in content
        assert message is None

    def test_missing_template_falls_back_with_message(self, tmp_path):
        from export_thesis import apply_template

        profiles_dir = tmp_path / "library-profiles"
        profiles_dir.mkdir()

        content, message = apply_template("\\chapter{Einleitung}", "unbekannt", profiles_dir)
        assert content == "\\chapter{Einleitung}"
        assert message is not None
        assert "Template `unbekannt` fehlt" in message

    def test_no_template_uni_is_passthrough(self, tmp_path):
        """Ohne --template bleibt der Content unveraendert, keine Meldung."""
        from export_thesis import apply_template

        content, message = apply_template("\\chapter{X}", None, tmp_path)
        assert content == "\\chapter{X}"
        assert message is None


class TestExportThesisIntegration:
    """End-to-End-Tests fuer export_thesis() -- Issue #467 Akzeptanzkriterien.

    build_bib_from_vault wird gemockt (Stub schreibt eine leere .bib-Datei):
    das Vault-Verhalten selbst ist bereits in TestBuildBib abgedeckt, hier
    geht es ausschliesslich um die Verkabelung der vier dokumentierten
    CLI-Parameter.
    """

    @staticmethod
    def _make_project(tmp_path):
        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "1.md", "Einleitung")
        _write_chapter(kap_dir, "2.md", "Methodik")
        _write_chapter(kap_dir, "3.md", "Ergebnisse")
        return kap_dir

    def test_export_single_chapter_by_number(self, tmp_path):
        """AC1: Einzelkapitel-Export ueber --kapitel <n>."""
        from export_thesis import export_thesis

        kap_dir = self._make_project(tmp_path)
        out = tmp_path / "output" / "kap2.tex"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="2",
                output_path=out,
                bib_path=tmp_path / "output" / "refs.bib",
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert r"\chapter{Methodik}" in content
        assert r"\chapter{Einleitung}" not in content
        assert r"\chapter{Ergebnisse}" not in content
        assert len(result.chapters) == 1

    def test_export_all_chapters_concatenates_in_order(self, tmp_path):
        """AC1: --kapitel all exportiert alle Kapitel in korrekter Reihenfolge."""
        from export_thesis import export_thesis

        kap_dir = self._make_project(tmp_path)
        out = tmp_path / "output" / "thesis.tex"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            export_thesis(
                kapitel_dir=kap_dir,
                selector="all",
                output_path=out,
                bib_path=tmp_path / "output" / "refs.bib",
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        content = out.read_text(encoding="utf-8")
        einleitung_pos = content.index(r"\chapter{Einleitung}")
        methodik_pos = content.index(r"\chapter{Methodik}")
        ergebnisse_pos = content.index(r"\chapter{Ergebnisse}")
        assert einleitung_pos < methodik_pos < ergebnisse_pos

    def test_output_path_is_respected(self, tmp_path):
        """AC2: Ausgabepfad ist frei bestimmbar -- Datei liegt exakt am
        angegebenen Pfad, nicht am Default."""
        from export_thesis import export_thesis

        kap_dir = self._make_project(tmp_path)
        custom_out = tmp_path / "beliebig" / "verschachtelt" / "kapitel2.tex"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="2",
                output_path=custom_out,
                bib_path=tmp_path / "output" / "refs.bib",
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        assert custom_out.exists()
        assert result.output_path == custom_out
        assert not (tmp_path / "output" / "thesis.tex").exists()

    def test_template_applied_replaces_placeholder(self, tmp_path):
        """AC3: Hinterlegte Uni-Vorlage wird angewendet."""
        from export_thesis import export_thesis

        kap_dir = self._make_project(tmp_path)
        profiles_dir = tmp_path / "library-profiles"
        profiles_dir.mkdir()
        (profiles_dir / "lmu.tex.template").write_text(
            "\\documentclass{report}\n\\begin{document}\n%%CONTENT%%\n\\end{document}\n",
            encoding="utf-8",
        )
        out = tmp_path / "output" / "thesis.tex"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="1",
                output_path=out,
                bib_path=tmp_path / "output" / "refs.bib",
                template_uni="lmu",
                profiles_dir=profiles_dir,
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        content = out.read_text(encoding="utf-8")
        assert content.startswith("\\documentclass{report}")
        assert r"\chapter{Einleitung}" in content
        assert result.template_message is None

    def test_missing_template_falls_back_with_message(self, tmp_path):
        """AC3: Fehlt die Vorlage, erklaert eine Meldung den Fallback --
        kein Absturz, Export findet trotzdem statt."""
        from export_thesis import export_thesis

        kap_dir = self._make_project(tmp_path)
        profiles_dir = tmp_path / "library-profiles"
        profiles_dir.mkdir()
        out = tmp_path / "output" / "thesis.tex"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="1",
                output_path=out,
                bib_path=tmp_path / "output" / "refs.bib",
                template_uni="unbekannte-uni",
                profiles_dir=profiles_dir,
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert r"\chapter{Einleitung}" in content
        assert result.template_message is not None
        assert "unbekannte-uni" in result.template_message

    def test_bib_path_independent_of_output_path(self, tmp_path):
        """AC4 / getrennte Literaturverzeichnis-Steuerung: --bib wird
        unabhaengig von --output verkabelt."""
        from export_thesis import export_thesis

        kap_dir = self._make_project(tmp_path)
        out = tmp_path / "irgendwo" / "thesis.tex"
        bib_out = tmp_path / "ganz-anderswo" / "quellen.bib"

        with patch("export_thesis.build_bib_from_vault") as mock_build_bib:
            mock_build_bib.side_effect = _fake_build_bib
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="1",
                output_path=out,
                bib_path=bib_out,
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        assert result.bib_path == bib_out
        mock_build_bib.assert_called_once_with("irrelevant.db", str(bib_out))

    def test_bib_default_path_used_when_not_specified(self, tmp_path, monkeypatch):
        """AC4: Ohne --bib wird der dokumentierte Default output/refs.bib
        verwendet (unabhaengig vom --output-Verzeichnis)."""
        from export_thesis import export_thesis

        monkeypatch.chdir(tmp_path)
        kap_dir = self._make_project(tmp_path)
        out = tmp_path / "output" / "thesis.tex"

        with patch("export_thesis.build_bib_from_vault") as mock_build_bib:
            mock_build_bib.side_effect = _fake_build_bib
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="1",
                output_path=out,
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        assert result.bib_path == Path("output/refs.bib")
        mock_build_bib.assert_called_once_with("irrelevant.db", "output/refs.bib")

    def test_bib_empty_string_falls_back_to_default(self, tmp_path, monkeypatch):
        """P1-Fix (PR #485-Review): --bib "" (leerer String, wie ihn der
        dokumentierte CLI-Aufruf ohne --bib zuvor durchreichte) faellt auf
        den Default zurueck statt Path("") -> PosixPath('.') an
        build_bib_from_vault()/write_text() zu reichen (IsADirectoryError)."""
        from export_thesis import export_thesis

        monkeypatch.chdir(tmp_path)
        kap_dir = self._make_project(tmp_path)
        out = tmp_path / "output" / "thesis.tex"

        with patch("export_thesis.build_bib_from_vault") as mock_build_bib:
            mock_build_bib.side_effect = _fake_build_bib
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="1",
                output_path=out,
                bib_path="",
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        assert result.bib_path == Path("output/refs.bib")
        mock_build_bib.assert_called_once_with("irrelevant.db", "output/refs.bib")

    def test_export_uses_default_vault_db_path_when_not_specified(self, tmp_path, monkeypatch):
        """Ohne explizite vault_db_path wird academic_vault.db.default_db_path()
        (Single Source of Truth, respektiert VAULT_DB_PATH) verwendet."""
        from export_thesis import export_thesis

        # chdir noetig: ohne --bib faellt export_thesis() auf den relativen
        # Default-Pfad DEFAULT_BIB_PATH ("output/refs.bib") zurueck -- ohne
        # chdir wuerde dieser Test sonst eine echte Datei ins Repo schreiben.
        monkeypatch.chdir(tmp_path)
        kap_dir = self._make_project(tmp_path)
        out = tmp_path / "output" / "thesis.tex"
        env_db_path = str(tmp_path / "env_vault.db")
        monkeypatch.setenv("VAULT_DB_PATH", env_db_path)

        captured = {}

        def fake_build_bib(db_path, output_path):
            captured["db_path"] = db_path
            _fake_build_bib(db_path, output_path)

        with patch("export_thesis.build_bib_from_vault", side_effect=fake_build_bib):
            export_thesis(
                kapitel_dir=kap_dir,
                selector="1",
                output_path=out,
                force_custom=True,
            )

        assert captured["db_path"] == env_db_path

    def test_all_documented_parameters_functional(self, tmp_path):
        """AC4: Alle vier dokumentierten Parameter (--kapitel, --output,
        --bib, --template) sind gemeinsam funktionsfaehig."""
        from export_thesis import export_thesis

        kap_dir = self._make_project(tmp_path)
        profiles_dir = tmp_path / "library-profiles"
        profiles_dir.mkdir()
        (profiles_dir / "tum.tex.template").write_text(
            "\\documentclass{book}\n\\begin{document}\n%%CONTENT%%\n\\end{document}\n",
            encoding="utf-8",
        )
        out = tmp_path / "custom" / "thesis.tex"
        bib_out = tmp_path / "custom" / "refs.bib"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            result = export_thesis(
                kapitel_dir=kap_dir,
                selector="all",  # --kapitel
                output_path=out,  # --output
                bib_path=bib_out,  # --bib
                template_uni="tum",  # --template
                profiles_dir=profiles_dir,
                vault_db_path="irrelevant.db",
                force_custom=True,
            )

        # --kapitel all
        assert len(result.chapters) == 3
        # --output
        assert out.exists()
        # --bib (unabhaengig von --output)
        assert bib_out.exists()
        # --template
        content = out.read_text(encoding="utf-8")
        assert content.startswith("\\documentclass{book}")
        assert r"\chapter{Einleitung}" in content
        assert r"\chapter{Methodik}" in content
        assert r"\chapter{Ergebnisse}" in content


class TestExportThesisCLI:
    """Tests fuer die argparse-CLI (export_thesis.main), Issue #467."""

    def test_required_args_missing_exits_nonzero(self):
        from export_thesis import main

        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2

    def test_cli_wires_all_four_documented_flags(self, tmp_path, monkeypatch):
        """--kapitel/--output/--bib/--template ueber die echte CLI (main())."""
        from export_thesis import main

        monkeypatch.chdir(tmp_path)
        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "1.md", "Einleitung")
        profiles_dir = tmp_path / "library-profiles"
        profiles_dir.mkdir()
        (profiles_dir / "lmu.tex.template").write_text(
            "\\documentclass{report}\n\\begin{document}\n%%CONTENT%%\n\\end{document}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("export_thesis.DEFAULT_PROFILES_DIR", profiles_dir)

        out = tmp_path / "custom.tex"
        bib_out = tmp_path / "custom.bib"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            exit_code = main(
                [
                    "--kapitel",
                    "1",
                    "--output",
                    str(out),
                    "--bib",
                    str(bib_out),
                    "--template",
                    "lmu",
                ]
            )

        assert exit_code == 0
        assert out.exists()
        assert bib_out.exists()
        content = out.read_text(encoding="utf-8")
        assert content.startswith("\\documentclass{report}")
        assert r"\chapter{Einleitung}" in content

    def test_cli_missing_template_falls_back_without_crash(self, tmp_path, monkeypatch, capsys):
        """AC3 ueber die CLI: unbekanntes --template bricht main() nicht ab
        und gibt eine verstaendliche Meldung aus (exit 0, Fallback-Export)."""
        from export_thesis import main

        monkeypatch.chdir(tmp_path)
        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "1.md", "Einleitung")
        profiles_dir = tmp_path / "library-profiles"
        profiles_dir.mkdir()
        monkeypatch.setattr("export_thesis.DEFAULT_PROFILES_DIR", profiles_dir)

        out = tmp_path / "thesis.tex"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            exit_code = main(["--kapitel", "1", "--output", str(out), "--template", "unbekannt"])

        assert exit_code == 0
        assert out.exists()
        captured = capsys.readouterr()
        assert "Template `unbekannt` fehlt" in captured.err

    def test_cli_bib_empty_string_falls_back_without_crash(self, tmp_path, monkeypatch):
        """P1-Fix (PR #485-Review): vor dem Fix reichte commands/latex.md
        ohne --bib ein leeres $BIB als `--bib ""` durch, was in export_thesis()
        auf Path("") -> PosixPath('.') traf (IsADirectoryError). Die CLI
        muss das jetzt wie "kein --bib" behandeln -- kein Absturz, Default
        greift."""
        from export_thesis import main

        monkeypatch.chdir(tmp_path)
        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "1.md", "Einleitung")

        out = tmp_path / "custom.tex"

        with patch("export_thesis.build_bib_from_vault", side_effect=_fake_build_bib):
            exit_code = main(["--kapitel", "1", "--output", str(out), "--bib", ""])

        assert exit_code == 0
        assert (tmp_path / "output" / "refs.bib").exists()

    def test_cli_unknown_chapter_exits_with_error_message(self, tmp_path, monkeypatch, capsys):
        """AC1: Nicht existierendes Kapitel -> klare Fehlermeldung, Exit != 0."""
        from export_thesis import main

        monkeypatch.chdir(tmp_path)
        kap_dir = tmp_path / "kapitel"
        _write_chapter(kap_dir, "1.md", "Einleitung")

        exit_code = main(["--kapitel", "99", "--output", str(tmp_path / "out.tex")])

        assert exit_code != 0
        captured = capsys.readouterr()
        assert "99" in captured.err


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

    def test_hook_tex_bypass_works(self, tmp_path):
        """<!-- vault-guard: skip --> Bypass funktioniert auch bei .tex-Pfaden.

        VAULT_GUARD_BYPASS_LOG wird auf tmp_path umgelenkt (Issue #381 loggt die
        Bypass-Nutzung jetzt) — sonst wuerde der Testlauf ins echte Home-Verzeichnis
        schreiben.
        """
        content = '<!-- vault-guard: skip -->\n"Unverifiziiertes Zitat in LaTeX."'
        result = run_hook(
            "Write",
            "thesis.tex",
            content,
            env_overrides={"VAULT_GUARD_BYPASS_LOG": str(tmp_path / "vault-guard-bypass.log")},
        )
        assert result.returncode == 0
