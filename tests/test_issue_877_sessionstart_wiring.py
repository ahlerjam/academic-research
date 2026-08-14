"""Issue #877: SessionStart-Hook meldet Phasenstand.

Prueft, dass hooks/hooks.json den neuen Phasenstand-Block im matcher==""
SessionStart-Eintrag registriert (fail-silent nach dem Muster der
Nachbar-Kommandos: python3-Verfuegbarkeit geprueft, stderr unterdrueckt,
exit 0 immer) und dass das Kommando im echten Prozess tatsaechlich lautlos
degradiert, wenn kein academic_context.md vorhanden ist.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"


def _sessionstart_default_commands() -> list[str]:
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    entries = data["hooks"]["SessionStart"]
    default_entry = next(e for e in entries if e.get("matcher") == "")
    return [h["command"] for h in default_entry["hooks"]]


def test_sessionstart_registers_workflow_status_script() -> None:
    commands = _sessionstart_default_commands()
    assert any("scripts/workflow_status.py" in c for c in commands), (
        f"Kein SessionStart-Kommando ruft scripts/workflow_status.py auf: {commands}"
    )


def test_workflow_status_command_is_fail_silent_like_neighbors() -> None:
    commands = _sessionstart_default_commands()
    target = next(c for c in commands if "scripts/workflow_status.py" in c)
    assert "python3" in target
    # Fail-silent-Muster: stderr unterdrueckt (2>/dev/null) analog zu den
    # Nachbar-Kommandos, und exit 0 wird nicht dem Skript-Exitcode ueberlassen.
    assert "2>/dev/null" in target
    assert "exit 0" in target
    assert "CLAUDE_PLUGIN_ROOT" in target
    assert "CLAUDE_PROJECT_DIR" in target


def test_workflow_status_command_runs_silently_without_context(tmp_path) -> None:
    """Fuehrt das registrierte Kommando echt aus, gegen ein Projekt ohne
    academic_context.md -- degradiert lautlos (AC2), kein Fehlertext, exit 0."""
    commands = _sessionstart_default_commands()
    target = next(c for c in commands if "scripts/workflow_status.py" in c)

    project = tmp_path / "project"
    project.mkdir()

    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(project)

    result = subprocess.run(
        ["bash", "-c", target],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert result.stderr.strip() == ""


def test_workflow_status_command_prints_phase_with_partial_context(tmp_path) -> None:
    """Selbes Kommando gegen ein Projekt mit teilweise gefuellter
    academic_context.md -- meldet die aktuelle Phase (AC1)."""
    commands = _sessionstart_default_commands()
    target = next(c for c in commands if "scripts/workflow_status.py" in c)

    project = tmp_path / "project"
    project.mkdir()
    (project / "academic_context.md").write_text(
        "## Profil\n- Universität: TU Beispiel\n\n## Fortschritt\n- [ ] Thema festgelegt\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(project)

    result = subprocess.run(
        ["bash", "-c", target],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "[flowkit] Phase:" in result.stdout
