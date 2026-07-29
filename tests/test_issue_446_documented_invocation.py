"""Der dokumentierte Aufrufpfad von /academic-research:word und :slides muss laufen.

Fixrunde PR #488 (Issue #446). Verifikations-Fund, live reproduziert:

    commands/word.md:82 und commands/slides.md:79 oeffnen den vorbereitenden
    Python-Block mit einem QUOTIERTEN Heredoc (``<<'PY'``). Ein quotierter
    Heredoc-Delimiter schaltet in POSIX-Shells jede Expansion ab -- weder
    ``${CLAUDE_PLUGIN_ROOT}`` noch ``$KAPITEL`` noch ``$VAULT_DB_PATH`` werden
    ersetzt. ``sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/...")`` fuegt
    damit ein literales, nicht existierendes Verzeichnis ein und der folgende
    Import stirbt mit einem rohen ``ModuleNotFoundError``-Traceback -- bevor
    ``document-skills:docx``/``:pptx`` ueberhaupt erreicht wird.

Betroffene Akzeptanzkriterien von #446: AC1 (.docx entsteht ueberhaupt),
AC3 (gleiche Literatureintrag-Menge docx/LaTeX -- ``$VAULT_DB_PATH`` wird
nirgends definiert), AC4 (Foliensatz entsteht ueberhaupt) und AC6 (fehlende
Dokument-Abhaengigkeit meldet verstaendlich statt Stacktrace).

Keine der bestehenden Suiten hat das gefunden, weil alle nur *Python-Funktionen*
direkt importieren (tests/test_word_export.py, tests/test_slide_export.py) oder
den *Text* der Command-Datei nach Stichworten durchsuchen
(tests/test_word_command_frontmatter.py). Die Luecke: der in der Command-Datei
dokumentierte Shell-Aufruf wurde nie ausgefuehrt.

Diese Suite fuehrt genau das aus: sie extrahiert die ``bash``-Bloecke aus
``commands/word.md``/``commands/slides.md``, laesst sie in einem echten
Mini-Projekt (``kapitel/``, ``academic_context.md``, befuellter Vault) durch
``bash`` laufen und prueft Exit-Code, Ausgabe und Traceback-Freiheit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).parent.parent
COMMANDS_DIR = WORKTREE / "commands"
WORD_COMMAND = COMMANDS_DIR / "word.md"
SLIDES_COMMAND = COMMANDS_DIR / "slides.md"

sys.path.insert(0, str(WORKTREE / "skills" / "word-export" / "scripts"))
sys.path.insert(0, str(WORKTREE / "skills" / "latex-export" / "scripts"))
sys.path.insert(0, str(WORKTREE / "skills" / "slide-export" / "scripts"))

_BASH_BLOCK_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL)
# Heredoc-Eroeffnung: <<[-] [Anfuehrungszeichen]DELIMITER[Anfuehrungszeichen]
_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SHELL_VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
_SHELL_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", re.MULTILINE)
_DOC_ASSIGN_RE = re.compile(r"`([A-Z][A-Z0-9_]*)`\s*=")
#: Slash-Command-Beispielbloecke sind Doku, kein ausfuehrbares Shell-Skript.
_SLASH_INVOCATION_RE = re.compile(r"^\s*/[a-z][\w-]*:", re.MULTILINE)


def bash_blocks(command_file: Path) -> list[str]:
    return _BASH_BLOCK_RE.findall(command_file.read_text(encoding="utf-8"))


def executable_bash_blocks(command_file: Path) -> list[str]:
    """bash-Bloecke ohne die reinen `/academic-research:x`-Aufrufbeispiele."""
    return [b for b in bash_blocks(command_file) if not _SLASH_INVOCATION_RE.search(b)]


def step_bash_block(command_file: Path, step: int) -> str:
    """Der bash-Block unter `### Schritt <n>` -- der real auszufuehrende Aufruf."""
    text = command_file.read_text(encoding="utf-8")
    section = re.split(rf"^###\s+Schritt\s+{step}\b", text, maxsplit=1, flags=re.MULTILINE)
    assert len(section) == 2, f"{command_file.name}: kein '### Schritt {step}'-Abschnitt"
    tail = re.split(r"^###\s", section[1], maxsplit=1, flags=re.MULTILINE)[0]
    blocks = _BASH_BLOCK_RE.findall(tail)
    assert blocks, f"{command_file.name}: Schritt {step} enthaelt keinen bash-Block"
    return blocks[0]


def make_project(tmp_path: Path) -> Path:
    """Minimales Projekt: zwei Kapitel + academic_context.md, wie im Command erwartet."""
    project = tmp_path / "projekt"
    (project / "kapitel").mkdir(parents=True)
    (project / "kapitel" / "1-einleitung.md").write_text(
        "# Einleitung\n\nDevOps-Governance ist der Kern dieser Arbeit "
        r"\cite{smith2023,jones2022}." + "\n",
        encoding="utf-8",
    )
    (project / "kapitel" / "2-methodik.md").write_text(
        "# Methodik\n\nQualitative Inhaltsanalyse nach Mayring.\n",
        encoding="utf-8",
    )
    (project / "academic_context.md").write_text(
        "# Kontext\n\n- Zitationsstil: APA7\n",
        encoding="utf-8",
    )
    return project


def make_vault(tmp_path: Path) -> str:
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper

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
    return db_path


def run_block(block: str, cwd: Path, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_extra)
    # Der Agent fuehrt Command-Bloecke ueber das Bash-Tool aus; PYTHONPATH sorgt
    # nur dafuer, dass `academic_vault` im Subprozess auffindbar bleibt (im
    # echten Betrieb liefert das die installierte Plugin-Umgebung).
    env["PYTHONPATH"] = os.pathsep.join(
        [str(WORKTREE), env.get("PYTHONPATH", "")],
    ).rstrip(os.pathsep)
    env.setdefault("PATH", os.defpath)
    return subprocess.run(
        ["bash", "-c", block],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Klassen-Invariante: quotierte Heredocs duerfen keine Shell-Variablen erwarten
# ---------------------------------------------------------------------------


class TestNoDeadShellExpansionInCommands:
    """Repo-weite Invariante gegen die Ursache, nicht nur gegen das Symptom."""

    @pytest.mark.parametrize(
        "command_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name
    )
    def test_quoted_heredocs_contain_no_variable_references(self, command_file):
        for block in bash_blocks(command_file):
            for match in _HEREDOC_OPEN_RE.finditer(block):
                quote, delimiter = match.group(1), match.group(2)
                if not quote:
                    continue  # unquotiert -> Expansion aktiv, in Ordnung
                body = block[match.end() :].split(f"\n{delimiter}", 1)[0]
                assert not _SHELL_VAR_RE.search(body), (
                    f"{command_file.name}: Heredoc <<{quote}{delimiter}{quote} ist quotiert, "
                    f"der Rumpf referenziert aber Shell-Variablen "
                    f"({sorted(set(_SHELL_VAR_RE.findall(body)))}). Quotierte Delimiter "
                    f"schalten jede Expansion ab -- die Variablen bleiben literal stehen."
                )


class TestNoUndefinedShellVariables:
    """Jede in einem bash-Block benutzte Variable muss im Command definiert sein.

    ``$VAULT_DB_PATH`` in commands/word.md kam in keinem Schritt-1-Parse-Abschnitt
    vor und war auch keine dokumentierte Umgebungsvariable (AC3).
    """

    #: Von der Laufzeitumgebung/dem Harness gestellt, nicht vom Command selbst.
    AMBIENT = {"CLAUDE_PLUGIN_ROOT", "ARGUMENTS", "HOME", "PATH", "PWD", "TMPDIR"}

    @pytest.mark.parametrize("command_file", [WORD_COMMAND, SLIDES_COMMAND], ids=lambda p: p.name)
    def test_every_used_variable_is_defined_or_ambient(self, command_file):
        text = command_file.read_text(encoding="utf-8")
        blocks = executable_bash_blocks(command_file)
        # Definiert = im Ablauf-Text ("- `KAPITEL` = Wert von ...") oder direkt
        # im bash-Block zugewiesen (LATEST=$(...)).
        defined = set(_DOC_ASSIGN_RE.findall(text)) | self.AMBIENT
        for block in blocks:
            defined |= set(_SHELL_ASSIGN_RE.findall(block))
        used: set[str] = set()
        for block in blocks:
            used |= set(_SHELL_VAR_RE.findall(block))
        undefined = {name for name in used - defined if not name.startswith("_")}
        assert not undefined, (
            f"{command_file.name}: bash-Block nutzt undefinierte Shell-Variablen "
            f"{sorted(undefined)} -- weder in 'Argumente parsen' definiert noch "
            f"als Umgebungsvariable dokumentiert."
        )


# ---------------------------------------------------------------------------
# Der dokumentierte Aufruf muss real durchlaufen
# ---------------------------------------------------------------------------


class TestWordCommandDocumentedInvocation:
    def test_documented_bash_block_runs_without_traceback(self, tmp_path):
        project = make_project(tmp_path)
        db_path = make_vault(tmp_path)
        payload = project / "word_payload.json"

        block = step_bash_block(WORD_COMMAND, 3)

        proc = run_block(
            block,
            cwd=project,
            env_extra={
                "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
                "KAPITEL": "all",
                "OUTPUT": str(project / "thesis.docx"),
                "PAYLOAD": str(payload),
                "VAULT_DB_PATH": db_path,
            },
        )

        assert "Traceback" not in proc.stderr, (
            f"Der dokumentierte Aufruf bricht mit einem rohen Traceback ab (AC6):\n{proc.stderr}"
        )
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert payload.is_file(), "Kein Payload fuer den document-skills:docx-Schritt erzeugt"

        data = json.loads(payload.read_text(encoding="utf-8"))
        assert [c["source"] for c in data["chapters"]] == ["1-einleitung.md", "2-methodik.md"]
        assert data["style_file"] == "apa.md"
        assert data["style_rules"].strip(), "style_rules leer -- Stilregeln nicht geladen"

    def test_cite_markers_are_resolved_in_the_documented_payload(self, tmp_path):
        """AC2 auf dem echten Aufrufweg: Mehrfachzitat -> zwei Kurzbelege."""
        project = make_project(tmp_path)
        db_path = make_vault(tmp_path)
        payload = project / "word_payload.json"

        proc = run_block(
            step_bash_block(WORD_COMMAND, 3),
            cwd=project,
            env_extra={
                "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
                "KAPITEL": "all",
                "OUTPUT": str(project / "thesis.docx"),
                "PAYLOAD": str(payload),
                "VAULT_DB_PATH": db_path,
            },
        )
        assert proc.returncode == 0, proc.stderr

        body = json.loads(payload.read_text(encoding="utf-8"))["chapters"][0]["body"]
        assert "\\cite" not in body
        assert "(Smith 2023; Jones et al. 2022)" in body

    def test_bibliography_matches_latex_export_entry_set(self, tmp_path):
        """AC3 auf dem echten Aufrufweg: gleiche Vault-Quelle wie der .bib-Pfad."""
        from build_bib import get_all_papers

        project = make_project(tmp_path)
        db_path = make_vault(tmp_path)
        payload = project / "word_payload.json"

        proc = run_block(
            step_bash_block(WORD_COMMAND, 3),
            cwd=project,
            env_extra={
                "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
                "KAPITEL": "all",
                "OUTPUT": str(project / "thesis.docx"),
                "PAYLOAD": str(payload),
                "VAULT_DB_PATH": db_path,
            },
        )
        assert proc.returncode == 0, proc.stderr

        data = json.loads(payload.read_text(encoding="utf-8"))
        docx_ids = sorted(p["paper_id"] for p in data["papers"])
        latex_ids = sorted(p["paper_id"] for p in get_all_papers(db_path))
        assert docx_ids == latex_ids == ["jones2022", "smith2023"]

    def test_unknown_chapter_fails_with_readable_message(self, tmp_path):
        """AC6: verstaendliche Meldung statt Stacktrace."""
        project = make_project(tmp_path)
        db_path = make_vault(tmp_path)

        proc = run_block(
            step_bash_block(WORD_COMMAND, 3),
            cwd=project,
            env_extra={
                "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
                "KAPITEL": "99",
                "OUTPUT": str(project / "thesis.docx"),
                "PAYLOAD": str(project / "word_payload.json"),
                "VAULT_DB_PATH": db_path,
            },
        )
        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr
        assert "FEHLER:" in proc.stderr


class TestSlidesCommandDocumentedInvocation:
    def test_documented_bash_block_runs_without_traceback(self, tmp_path):
        project = make_project(tmp_path)
        payload = project / "slides_payload.json"

        proc = run_block(
            step_bash_block(SLIDES_COMMAND, 3),
            cwd=project,
            env_extra={
                "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
                "KAPITEL": "all",
                "OUTPUT": str(project / "deck.pptx"),
                "PAYLOAD": str(payload),
            },
        )

        assert "Traceback" not in proc.stderr, (
            f"Der dokumentierte Aufruf bricht mit einem rohen Traceback ab (AC6):\n{proc.stderr}"
        )
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        assert payload.is_file(), "Kein Payload fuer den document-skills:pptx-Schritt erzeugt"

        slides = json.loads(payload.read_text(encoding="utf-8"))["slides"]
        assert [s["title"] for s in slides] == ["Einleitung", "Methodik"]
        assert all(s["core_statement"] for s in slides)

    def test_unknown_chapter_fails_with_readable_message(self, tmp_path):
        project = make_project(tmp_path)

        proc = run_block(
            step_bash_block(SLIDES_COMMAND, 3),
            cwd=project,
            env_extra={
                "CLAUDE_PLUGIN_ROOT": str(WORKTREE),
                "KAPITEL": "99",
                "OUTPUT": str(project / "deck.pptx"),
                "PAYLOAD": str(project / "slides_payload.json"),
            },
        )
        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr
        assert "FEHLER:" in proc.stderr
