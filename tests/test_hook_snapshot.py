"""Tests fuer pre-compact.mjs Snapshot-Hook.

Der Hook wird als Node.js-Subprocess gestartet.
Eingabe: JSON auf stdin (Claude Code PreCompact-Format).
Der Hook schreibt academic_context.md, literature_state.md, writing_state.md
und einen Vault-Tarball nach ~/.academic-research/snapshots/<slug>/<ts>.tgz.
Exit 0 immer (fail-open).

ISOLATION: der Hook faellt ohne Env-Vorgaben auf ``os.homedir()`` zurueck und
schreibt dann in den ECHTEN Nutzer-Baum. Am 11.08.2026 ist genau das passiert:
``test_hook_exits_zero_on_empty_input`` und
``test_hook_exits_zero_on_compact_event`` liefen ohne Overrides, und weil der
Vault-Export im Hook zwischenzeitlich scharf geschaltet wurde, landeten aus
einem einzigen Testlauf zwei echte Tarballs in
``~/.academic-research/snapshots/``. Deshalb setzt :func:`run_hook` die drei
Isolationsvariablen jetzt selbst und weigert sich, den Subprozess ohne sie zu
starten. Der Schutzwall in tests/conftest.py sieht Subprozess-Schreibzugriffe
prinzipbedingt nicht kommen -- er meldet sie nur hinterher.
"""

import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.conftest import REAL_ACADEMIC_ROOT, is_protected_path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "pre-compact.mjs"
WORKTREE_ROOT = Path(__file__).parent.parent

#: Variablen, ohne die der Hook in den echten Nutzer-Baum schreibt.
ISOLATION_VARS = ("ACADEMIC_SNAPSHOTS_DIR", "CLAUDE_PROJECT_DIR", "VAULT_DB_PATH")


def isolation_env(sandbox: Path) -> dict:
    """Vollstaendige Isolation des Hooks in einem tmp-Verzeichnis.

    HOME wird mitgesetzt, damit auch die Pfade greifen, die der Hook nicht ueber
    eine eigene Variable, sondern ueber ``os.homedir()`` bildet.
    """
    return {
        "HOME": str(sandbox),
        "ACADEMIC_SNAPSHOTS_DIR": str(sandbox / "snapshots"),
        "CLAUDE_PROJECT_DIR": str(sandbox / "project"),
        "VAULT_DB_PATH": str(sandbox / "vault.db"),
    }


def _assert_isolated(env: dict) -> None:
    """Bricht ab, bevor der Subprozess ueberhaupt startet, statt danach zu klagen."""
    for name in ISOLATION_VARS:
        wert = env.get(name)
        assert wert, (
            f"{name} ist nicht gesetzt -- der Hook wuerde in den echten "
            f"~/.academic-research-Baum schreiben (Vorfall 11.08.2026)."
        )
        assert not is_protected_path(wert), f"{name} zeigt in den echten Nutzer-Baum: {wert}"


def run_hook(
    payload: dict, env_overrides: dict = None, *, sandbox: Path = None
) -> subprocess.CompletedProcess:
    """Startet den Hook als Subprocess mit JSON-Eingabe auf stdin.

    ``sandbox`` (in der Regel ``tmp_path``) setzt die Isolationsvariablen auf
    einen Schlag; ``env_overrides`` sticht sie fuer Tests, die einzelne Pfade
    gezielt brauchen. Ohne beides startet der Subprozess nicht.
    """
    env = os.environ.copy()
    if sandbox is not None:
        env.update(isolation_env(sandbox))
    if env_overrides:
        env.update(env_overrides)
    _assert_isolated(env)

    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_hook_exits_zero_on_empty_input(tmp_path):
    """Hook ist fail-open: exit 0 auch bei leerem Payload."""
    result = run_hook({}, sandbox=tmp_path)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"


def test_hook_exits_zero_on_compact_event(tmp_path):
    """Hook laeuft bei PreCompact-Event durch (exit 0)."""
    payload = {
        "hook_event_name": "PreCompact",
        "trigger_reason": "manual",
    }
    result = run_hook(payload, sandbox=tmp_path)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"


def test_run_hook_verweigert_lauf_ohne_isolation(tmp_path):
    """Ohne Isolationsvariablen startet der Subprozess gar nicht erst.

    Regression zum Vorfall vom 11.08.2026 (zwei echte Tarballs in
    ~/.academic-research/snapshots/ aus einem Testlauf).
    """
    echt = REAL_ACADEMIC_ROOT / "snapshots"
    for luecke in (
        {"ACADEMIC_SNAPSHOTS_DIR": ""},
        {"CLAUDE_PROJECT_DIR": ""},
        {"VAULT_DB_PATH": ""},
    ):
        with pytest.raises(AssertionError):
            run_hook({}, env_overrides=luecke, sandbox=tmp_path)

    # Und ebenso, wenn eine Variable zwar gesetzt ist, aber in den echten Baum zeigt.
    with pytest.raises(AssertionError):
        run_hook(
            {},
            env_overrides={"ACADEMIC_SNAPSHOTS_DIR": str(echt)},
            sandbox=tmp_path,
        )


def test_hook_writes_snapshot_files(tmp_path):
    """Hook schreibt Snapshot-Dateien in SNAPSHOTS_DIR."""
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Erstelle Testdateien im Projekt-Verzeichnis
    (project_dir / "academic_context.md").write_text("# Kontext\nTestinhalt")
    (project_dir / "literature_state.md").write_text("# Literatur\nTestpaper")
    (project_dir / "writing_state.md").write_text("# Schreibstatus\nKapitel 1")

    payload = {
        "hook_event_name": "PreCompact",
        "trigger_reason": "auto",
    }

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(tmp_path / "nonexistent.db"),  # fail-open fuer Vault
    }

    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"

    # Snapshot-Verzeichnis muss existieren
    slug_dir = snapshots_dir / slug
    assert slug_dir.exists(), f"Snapshot-Verzeichnis {slug_dir} nicht erstellt"

    # Mindestens eine .tgz-Datei muss existieren
    tarballs = list(slug_dir.glob("*.tgz"))
    assert len(tarballs) >= 1, f"Keine .tgz-Dateien in {slug_dir}"


def test_hook_tarball_contains_state_files(tmp_path):
    """Tarball enthaelt academic_context.md, literature_state.md, writing_state.md."""
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    (project_dir / "academic_context.md").write_text("# Kontext\nTestinhalt")
    (project_dir / "literature_state.md").write_text("# Literatur\nTestpaper")
    (project_dir / "writing_state.md").write_text("# Schreibstatus\nKapitel 1")

    payload = {"hook_event_name": "PreCompact"}
    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(tmp_path / "nonexistent.db"),
    }

    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0

    slug_dir = snapshots_dir / slug
    tarballs = list(slug_dir.glob("*.tgz"))
    assert len(tarballs) >= 1

    # Tarball oeffnen und Inhalt pruefen
    with tarfile.open(tarballs[0], "r:gz") as tar:
        names = tar.getnames()

    # Mindestens state-Dateien muessen vorhanden sein
    assert any("academic_context.md" in n for n in names), (
        f"academic_context.md nicht in Tarball: {names}"
    )
    assert any("literature_state.md" in n for n in names), (
        f"literature_state.md nicht in Tarball: {names}"
    )
    assert any("writing_state.md" in n for n in names), (
        f"writing_state.md nicht in Tarball: {names}"
    )


def test_hook_slug_defaults_to_project_dir_basename_without_override(tmp_path):
    """Ohne ACADEMIC_PROJECT_SLUG-Override landen Snapshots im <basename(CLAUDE_PROJECT_DIR)>-Ordner.

    Regression fuer #382: SLUG (Snapshot-Ordner) und DB_SLUG (Vault-Pfad) muessen
    fuer dasselbe Projekt denselben Wert liefern. Zwei verschiedene Projekt-
    Verzeichnisse muessen in getrennten Snapshot-Ordnern landen.
    """
    snapshots_dir = tmp_path / "snapshots"

    project_a = tmp_path / "project-alpha"
    project_a.mkdir()
    (project_a / "academic_context.md").write_text("# Alpha")

    project_b = tmp_path / "project-beta"
    project_b.mkdir()
    (project_b / "academic_context.md").write_text("# Beta")

    for project_dir in (project_a, project_b):
        payload = {"hook_event_name": "PreCompact"}
        # Bewusst KEIN ACADEMIC_PROJECT_SLUG -> Default muss basename(CLAUDE_PROJECT_DIR) sein
        env_overrides = {
            "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "VAULT_DB_PATH": str(tmp_path / "nonexistent.db"),
        }
        result = run_hook(payload, env_overrides=env_overrides)
        assert result.returncode == 0, (
            f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"
        )

    alpha_dir = snapshots_dir / "project-alpha"
    beta_dir = snapshots_dir / "project-beta"
    assert alpha_dir.exists(), (
        f"Snapshot-Ordner fuer project-alpha fehlt: {list(snapshots_dir.iterdir())}"
    )
    assert beta_dir.exists(), (
        f"Snapshot-Ordner fuer project-beta fehlt: {list(snapshots_dir.iterdir())}"
    )
    assert list(alpha_dir.glob("*.tgz")), "Kein Tarball im project-alpha-Snapshot-Ordner"
    assert list(beta_dir.glob("*.tgz")), "Kein Tarball im project-beta-Snapshot-Ordner"

    # 'default'-Ordner darf NICHT verwendet werden, wenn CLAUDE_PROJECT_DIR gesetzt ist
    default_dir = snapshots_dir / "default"
    assert not default_dir.exists(), (
        f"SLUG fiel auf 'default' zurueck statt basename(CLAUDE_PROJECT_DIR) zu nutzen: "
        f"{list(snapshots_dir.iterdir())}"
    )


def test_hook_failopen_when_project_dir_missing(tmp_path):
    """Hook ist fail-open wenn CLAUDE_PROJECT_DIR nicht existiert."""
    payload = {"hook_event_name": "PreCompact"}
    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(tmp_path / "snapshots"),
        "ACADEMIC_PROJECT_SLUG": "test",
        "CLAUDE_PROJECT_DIR": str(tmp_path / "nonexistent_project"),
        "VAULT_DB_PATH": str(tmp_path / "nonexistent.db"),
    }

    result = run_hook(payload, env_overrides=env_overrides)
    # Immer fail-open
    assert result.returncode == 0, (
        f"Erwartet 0 (fail-open), got {result.returncode}. stderr: {result.stderr}"
    )
