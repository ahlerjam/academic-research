"""AC1/AC2/AC4 auf dem PRODUKTIONSPFAD -- nicht mit einem test-eigenen Renderer.

Fixrunde PR #488 (Issue #446), Review-Fund:

    "AC1: .docx-Erzeugung/Reparaturfreiheit in Word ist nicht belegt -- nur ein
     als 'Test-only, kein Ersatz fuer document-skills:docx' deklarierter
     Renderer existiert."
    "AC2 (teilweise): [...] dass Zitate/Literaturverzeichnis tatsaechlich im
     Zielstil im gerenderten Dokument erscheinen, ist laut Testdocstring
     bewusst nicht geprueft."
    "AC4: Foliensatz-Oeffnenbarkeit in PowerPoint ist nicht belegt -- gleiche
     Luecke wie AC1."

Gemeinsame Ursache (eine, nicht drei): **kein Repo-Code hat die Datei je
erzeugt.** Die Pipeline endete bei einer JSON-Payload, das eigentliche
Rendern war Prosa-Anweisung an den Agenten (SKILL.md Schritt 4). Damit gibt es
kein Artefakt, das eine Suite ausfuehren koennte -- die Vorrunde hat den
Renderer deshalb *in die Testdatei* gelegt (``_render_reference_docx`` /
``_render_reference_pptx``) und damit nur bewiesen, dass der Test ein docx
schreiben kann.

Gegenmittel ist das Muster des funktionierenden Geschwister-Skills
``latex-export``: dort erzeugt ``render_tex.py`` die ``.tex``-Datei wirklich,
und genau deshalb ist der LaTeX-Pfad testbar. Analog dazu rendern jetzt
``skills/word-export/scripts/render_docx.py`` und
``skills/slide-export/scripts/render_pptx.py`` die Zieldatei deterministisch.

Diese Suite fuehrt ausschliesslich die in ``commands/word.md`` /
``commands/slides.md`` dokumentierten bash-Bloecke aus (Schritt 3 = Payload,
Schritt 4 = Rendern) und prueft die dabei entstandene Datei. Kein Rendering-
Code in dieser Datei -- was hier gruen ist, ist am Produktionspfad gruen.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tests.test_issue_446_documented_invocation import (
    WORKTREE,
    make_project,
    make_vault,
    run_block,
    step_bash_block,
)

SLIDES_COMMAND = WORKTREE / "commands" / "slides.md"
WORD_COMMAND = WORKTREE / "commands" / "word.md"

docx = pytest.importorskip("docx", reason="python-docx nicht installiert (uv sync)")
pptx = pytest.importorskip("pptx", reason="python-pptx nicht installiert (uv sync)")

SOFFICE_AVAILABLE = shutil.which("soffice") is not None

#: Layout-Index "Title and Content" im Standard-python-pptx-Template.
_CONTENT_PLACEHOLDER_IDX = 1

#: Literatureintraege, wie der Agent sie aus ``style_rules`` formatiert in die
#: Payload zurueckschreibt (Schritt 4 der Commands). Bewusst mit der exakten
#: Interpunktion zweier VERSCHIEDENER Stile, damit der Test nicht versehentlich
#: gegen eine im Renderer fest verdrahtete Formatierung gruen wird.
APA_ENTRIES = [
    "Smith, J. (2023). DevOps Governance in KMU. Journal of Governance, 12(3), 45-67.",
    "Jones, A., & Lee, K. (2022). Cloud-Transformation und Governance. Springer.",
]
HARVARD_ENTRIES = [
    "Smith, J. 2023. 'DevOps Governance in KMU', Journal of Governance, 12(3), pp. 45-67.",
    "Jones, A. and Lee, K. 2022. Cloud-Transformation und Governance. Berlin: Springer.",
]


# ---------------------------------------------------------------------------
# Hilfen: dokumentierten Aufrufweg fahren (Schritt 3 -> Payload -> Schritt 4)
# ---------------------------------------------------------------------------


def _word_env(project: Path, payload: Path, output: Path, db_path: str) -> dict[str, str]:
    return {
        "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
        "KAPITEL": "all",
        "OUTPUT": str(output),
        "PAYLOAD": str(payload),
        "FORMAT": "docx",
        "TEMPLATE": "",
        "VAULT_DB_PATH": db_path,
    }


def prepare_word_payload(tmp_path: Path, bibliography: list[str] | None) -> tuple[Path, Path, dict]:
    """Schritt 3 real fahren und die Agenten-Stilstufe (Schritt 4) simulieren.

    `bibliography` = die Eintraege, die der Agent aus `style_rules` formatiert
    in die Payload zurueckschreibt. `None` = der Agent hat den Schritt
    ausgelassen (Fehlerpfad).
    """
    project = make_project(tmp_path)
    db_path = make_vault(tmp_path)
    payload = project / "word_payload.json"
    output = project / "thesis.docx"

    proc = run_block(
        step_bash_block(WORD_COMMAND, 3),
        cwd=project,
        env_extra=_word_env(project, payload, output, db_path),
    )
    assert proc.returncode == 0, f"Schritt 3 (Payload) scheiterte:\n{proc.stdout}\n{proc.stderr}"

    data = json.loads(payload.read_text(encoding="utf-8"))
    if bibliography is not None:
        data["bibliography"] = bibliography
    payload.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return project, output, {"payload": payload, "db_path": db_path}


def render_word(project: Path, output: Path, extra: dict, **env) -> subprocess.CompletedProcess:
    env_extra = _word_env(project, extra["payload"], output, extra["db_path"])
    env_extra.update(env)
    return run_block(step_bash_block(WORD_COMMAND, 4), cwd=project, env_extra=env_extra)


def render_slides(tmp_path: Path, **env) -> tuple[Path, subprocess.CompletedProcess]:
    project = make_project(tmp_path)
    payload = project / "slides_payload.json"
    output = project / "deck.pptx"
    env_extra = {
        "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
        "KAPITEL": "all",
        "OUTPUT": str(output),
        "PAYLOAD": str(payload),
        "RAHMEN": "",
    }

    proc = run_block(step_bash_block(SLIDES_COMMAND, 3), cwd=project, env_extra=env_extra)
    assert proc.returncode == 0, f"Schritt 3 (Payload) scheiterte:\n{proc.stdout}\n{proc.stderr}"

    env_extra.update(env)
    return output, run_block(step_bash_block(SLIDES_COMMAND, 4), cwd=project, env_extra=env_extra)


def stub_missing_module(tmp_path: Path, module: str) -> str:
    """PYTHONPATH-Praefix, unter dem `import <module>` mit ImportError stirbt.

    Simuliert eine Installation ohne den Renderer -- der Pfad, auf dem AC6
    ("verstaendliche Meldung statt Stacktrace") greifen muss.
    """
    stub_root = tmp_path / f"stub_no_{module}"
    (stub_root / module).mkdir(parents=True)
    (stub_root / module / "__init__.py").write_text(
        f'raise ImportError("simuliert: {module} ist nicht installiert")\n',
        encoding="utf-8",
    )
    return str(stub_root)


# ---------------------------------------------------------------------------
# AC1 — aus Kapiteln entsteht ein .docx, das Word ohne Reparaturhinweis oeffnet
# ---------------------------------------------------------------------------


class TestWordDocumentIsProducedByTheDocumentedPath:
    def test_documented_render_step_writes_a_reopenable_docx(self, tmp_path):
        project, output, extra = prepare_word_payload(tmp_path, APA_ENTRIES)

        proc = render_word(project, output, extra)

        assert "Traceback" not in proc.stderr, f"Roher Traceback statt Meldung:\n{proc.stderr}"
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert output.is_file(), "Der dokumentierte Aufrufweg erzeugt keine .docx-Datei (AC1)"

        # Reparaturhinweis-Proxy 1: intakte OPC-Zip-Struktur mit Pflichtteilen.
        with zipfile.ZipFile(output) as zf:
            assert zf.testzip() is None, "Beschaedigtes Zip -> Word meldet Reparaturbedarf"
            names = set(zf.namelist())
        assert {"[Content_Types].xml", "word/document.xml"} <= names, sorted(names)

        # Reparaturhinweis-Proxy 2: verlustfrei wieder oeffenbar.
        assert docx.Document(str(output)).paragraphs

    def test_markdown_heading_levels_become_real_word_heading_styles(self, tmp_path):
        """AC1: echte Formatvorlagen, kein manuelles Fett/Groesse."""
        project, output, extra = prepare_word_payload(tmp_path, APA_ENTRIES)
        payload = json.loads(extra["payload"].read_text(encoding="utf-8"))
        payload["chapters"] = [
            {
                "source": "1-einleitung.md",
                "path": "kapitel/1-einleitung.md",
                "body": (
                    "# Einleitung\n\nFliesstext.\n\n"
                    "## Motivation\n\nZweiter Absatz.\n\n"
                    "###### Sechste Ebene\n\nGrenzfall.\n"
                ),
            }
        ]
        extra["payload"].write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = render_word(project, output, extra)
        assert proc.returncode == 0, proc.stderr

        document = docx.Document(str(output))
        styles = {p.text: p.style.name for p in document.paragraphs if p.text.strip()}
        assert styles.get("Einleitung") == "Heading 1"
        assert styles.get("Motivation") == "Heading 2"
        assert styles.get("Sechste Ebene") == "Heading 6"

        body = next(p for p in document.paragraphs if p.text == "Fliesstext.")
        assert body.style.name not in {f"Heading {i}" for i in range(1, 10)}
        assert not any(run.bold for run in body.runs), (
            "Fliesstext darf nicht per manuellem Fett formatiert sein"
        )

    def test_document_contains_word_native_toc_field_not_static_text(self, tmp_path):
        project, output, extra = prepare_word_payload(tmp_path, APA_ENTRIES)
        assert render_word(project, output, extra).returncode == 0

        with zipfile.ZipFile(output) as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
        assert "<w:instrText" in document_xml and "TOC" in document_xml, (
            "Kein Word-natives Inhaltsverzeichnis-Feld -- ein statischer Text "
            "kann in Word nicht aktualisiert werden (AC1)."
        )

    def test_title_page_and_declaration_are_part_of_the_document(self, tmp_path):
        project, output, extra = prepare_word_payload(tmp_path, APA_ENTRIES)
        assert render_word(project, output, extra).returncode == 0

        texts = [p.text for p in docx.Document(str(output)).paragraphs]
        joined = "\n".join(texts)
        assert "Eidesstattliche Erkl" in joined, "Eidesstattliche Erklaerung fehlt im Dokument"
        assert any("Inhaltsverzeichnis" == t for t in texts)

    @pytest.mark.skipif(
        not SOFFICE_AVAILABLE,
        reason="soffice/LibreOffice nicht in PATH (in CI-Matrix nicht installiert)",
    )
    def test_rendered_docx_converts_cleanly_via_soffice(self, tmp_path):
        """Staerkster verfuegbarer Reparaturhinweis-Proxy: echte Office-Konvertierung."""
        project, output, extra = prepare_word_payload(tmp_path, APA_ENTRIES)
        assert render_word(project, output, extra).returncode == 0

        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path),
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"soffice-Konvertierung fehlgeschlagen (Reparaturhinweis-Signal):\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert (tmp_path / "thesis.pdf").stat().st_size > 0


# ---------------------------------------------------------------------------
# AC2 — Zitate und Literaturverzeichnis erscheinen im Zielstil IM Dokument
# ---------------------------------------------------------------------------


class TestCitationsAndBibliographyReachTheDocument:
    def test_resolved_in_text_citations_appear_in_the_rendered_body(self, tmp_path):
        project, output, extra = prepare_word_payload(tmp_path, APA_ENTRIES)
        assert render_word(project, output, extra).returncode == 0

        texts = [p.text for p in docx.Document(str(output)).paragraphs]
        assert any("(Smith 2023; Jones & Lee 2022)" in t for t in texts), (
            "Aufgeloester Kurzbeleg fehlt im gerenderten Fliesstext (AC2)"
        )
        assert not any("\\cite" in t for t in texts), "Roher LaTeX-Marker im Word-Dokument"

    @pytest.mark.parametrize(
        ("entries", "probe"),
        [
            (APA_ENTRIES, "Smith, J. (2023). DevOps Governance in KMU."),
            (HARVARD_ENTRIES, "Smith, J. 2023. 'DevOps Governance in KMU'"),
        ],
        ids=["apa", "harvard"],
    )
    def test_bibliography_entries_reach_the_document_verbatim(self, tmp_path, entries, probe):
        """Der Zielstil landet zeichengenau im Dokument -- der Renderer formt ihn
        nicht um und ersetzt ihn nicht durch eine eigene Formatierung.

        Zusammen mit tests/test_word_export.py (style_rules stammen nachweislich
        unveraendert aus citation-extraction/references/) ist damit die ganze
        AC2-Kette belegt: Regelherkunft -> Anwendung -> Dokument.
        """
        project, output, extra = prepare_word_payload(tmp_path, entries)
        assert render_word(project, output, extra).returncode == 0

        document = docx.Document(str(output))
        texts = [p.text for p in document.paragraphs]
        assert any(probe in t for t in texts), (
            f"Literatureintrag im Zielstil fehlt im Dokument. Absaetze: {texts}"
        )
        for entry in entries:
            assert entry in texts, f"Eintrag nicht zeichengenau uebernommen: {entry!r}"

        # Reihenfolge der Stilstufe bleibt erhalten (kein Umsortieren im Renderer).
        positions = [texts.index(entry) for entry in entries]
        assert positions == sorted(positions)

        heading = next(
            (i for i, t in enumerate(texts) if t.strip() == "Literaturverzeichnis"), None
        )
        assert heading is not None, "Kein Literaturverzeichnis-Abschnitt im Dokument"
        assert min(positions) > heading, "Eintraege stehen nicht unter dem Verzeichnis-Heading"

    def test_papers_without_style_formatted_entries_abort_readably(self, tmp_path):
        """Kein erfundener Stil: fehlt die Stilstufe, bricht der Renderer
        verstaendlich ab, statt das Verzeichnis in einem unbelegten Format zu
        schreiben (Preamble "Keine Fabrikation", AC2/AC6)."""
        project, output, extra = prepare_word_payload(tmp_path, bibliography=None)

        proc = render_word(project, output, extra)

        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr
        assert "FEHLER:" in proc.stderr
        assert "bibliography" in proc.stderr

    def test_empty_vault_renders_document_without_bibliography_entries(self, tmp_path):
        """Fehlerpfad "Vault leer": kein Abbruch, gueltiges Dokument."""
        project, output, extra = prepare_word_payload(tmp_path, bibliography=[])
        payload = json.loads(extra["payload"].read_text(encoding="utf-8"))
        payload["papers"] = []
        extra["payload"].write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        proc = render_word(project, output, extra)

        assert proc.returncode == 0, proc.stderr
        assert docx.Document(str(output)).paragraphs


# ---------------------------------------------------------------------------
# AC4 — Foliensatz entsteht und laesst sich oeffnen
# ---------------------------------------------------------------------------


class TestSlideDeckIsProducedByTheDocumentedPath:
    def test_documented_render_step_writes_a_reopenable_pptx(self, tmp_path):
        output, proc = render_slides(tmp_path)

        assert "Traceback" not in proc.stderr, f"Roher Traceback statt Meldung:\n{proc.stderr}"
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert output.is_file(), "Der dokumentierte Aufrufweg erzeugt keine .pptx-Datei (AC4)"

        with zipfile.ZipFile(output) as zf:
            assert zf.testzip() is None, "Beschaedigtes Zip -> PowerPoint meldet Reparaturbedarf"
            names = set(zf.namelist())
        assert "[Content_Types].xml" in names
        assert any(n.startswith("ppt/slides/slide") for n in names), sorted(names)

        presentation = pptx.Presentation(str(output))
        assert len(presentation.slides) == 2, "Eine Folie je Kapitel erwartet (AC4)"
        assert [s.shapes.title.text for s in presentation.slides] == ["Einleitung", "Methodik"]
        first_body = presentation.slides[0].placeholders[_CONTENT_PLACEHOLDER_IDX].text_frame.text
        assert "DevOps-Governance" in first_body
        assert "\\cite" not in first_body

    @pytest.mark.skipif(
        not SOFFICE_AVAILABLE,
        reason="soffice/LibreOffice nicht in PATH (in CI-Matrix nicht installiert)",
    )
    def test_rendered_pptx_converts_cleanly_via_soffice(self, tmp_path):
        output, proc = render_slides(tmp_path)
        assert proc.returncode == 0, proc.stderr

        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path),
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"soffice-Konvertierung fehlgeschlagen (Reparaturhinweis-Signal):\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert (tmp_path / "deck.pdf").stat().st_size > 0


# ---------------------------------------------------------------------------
# AC6 — fehlende Dokument-Abhaengigkeit meldet verstaendlich statt Traceback
# ---------------------------------------------------------------------------


class TestMissingRendererDependencyIsReported:
    def test_word_renderer_without_python_docx_reports_install_hint(self, tmp_path):
        project, output, extra = prepare_word_payload(tmp_path, APA_ENTRIES)

        proc = render_word(
            project,
            output,
            extra,
            PYTHONPATH=stub_missing_module(tmp_path, "docx") + ":" + str(WORKTREE),
        )

        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "FEHLER:" in proc.stderr
        assert "python-docx" in proc.stderr

    def test_slide_renderer_without_python_pptx_reports_install_hint(self, tmp_path):
        _, proc = render_slides(
            tmp_path,
            PYTHONPATH=stub_missing_module(tmp_path, "pptx") + ":" + str(WORKTREE),
        )

        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr, proc.stderr
        assert "FEHLER:" in proc.stderr
        assert "python-pptx" in proc.stderr


# ---------------------------------------------------------------------------
# Klassen-Invariante gegen den Rueckfall in "Renderer lebt im Test"
# ---------------------------------------------------------------------------


class TestRendererLivesInTheSkillNotInTheSuite:
    """Die Ursache selbst absichern, nicht nur ihr Symptom.

    Beide Skills muessen ein ausfuehrbares Renderer-Skript mitbringen; sonst
    faellt der naechste Umbau wieder auf "der Agent rendert irgendwie" zurueck
    und AC1/AC4 waeren erneut unbelegbar.
    """

    @pytest.mark.parametrize(
        ("skill", "script"),
        [("word-export", "render_docx.py"), ("slide-export", "render_pptx.py")],
    )
    def test_skill_ships_the_renderer(self, skill, script):
        path = WORKTREE / "skills" / skill / "scripts" / script
        assert path.is_file(), f"{skill} bringt keinen eigenen Renderer mit: {path}"

    @pytest.mark.parametrize(
        ("command", "script"),
        [("word.md", "render_docx.py"), ("slides.md", "render_pptx.py")],
    )
    def test_documented_step_4_invokes_the_renderer(self, command, script):
        block = step_bash_block(WORKTREE / "commands" / command, 4)
        assert script in block, (
            f"commands/{command} Schritt 4 ruft {script} nicht auf -- das Rendern "
            "waere wieder reine Prosa-Anweisung."
        )

    @pytest.mark.parametrize("script", ["render_docx.py", "render_pptx.py"])
    def test_renderer_is_runnable_as_cli(self, script):
        skill = "word-export" if "docx" in script else "slide-export"
        path = WORKTREE / "skills" / skill / "scripts" / script
        proc = subprocess.run(
            [sys.executable, str(path), "--help"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "--payload" in proc.stdout and "--output" in proc.stdout
