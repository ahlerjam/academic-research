"""Tests fuer hooks/session-snapshot.mjs (#625).

Der Hook laeuft unter dem `Stop`-Event zusaetzlich zum bestehenden
`PreCompact`-Snapshot (pre-compact.mjs) und sichert den Vault auch am Ende
kurzer Sitzungen, die nie verdichtet werden.

Protokoll (analog pre-compact.mjs / tests/test_hook_snapshot.py):
  - Eingabe: JSON auf stdin (Claude Code Stop-Format), tolerant bei leerem/
    kaputtem Payload.
  - Exit 0 immer (fail-open).
  - Snapshot nur bei geaendertem Vault-Fingerprint (size + mtimeMs) gegenueber
    dem Marker `<snapshotsDir>/<slug>/.last-session-snapshot.json`.
  - Retention: aelteste .tgz im Slug-Verzeichnis werden auf
    ACADEMIC_SNAPSHOTS_KEEP (Default 20) zurueckgeschnitten.
"""

import json
import os
import subprocess
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "session-snapshot.mjs"
WORKTREE_ROOT = Path(__file__).parent.parent

MARKER_NAME = ".last-session-snapshot.json"


def run_hook(payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Startet den Hook als Subprocess mit JSON-Eingabe auf stdin."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _make_vault_db(path: Path, content: bytes = b"vault-content-v1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_hook_exits_zero_on_empty_input():
    """Hook ist fail-open: exit 0 auch bei leerem Payload."""
    result = run_hook({})
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"


def test_session_snapshot_creates_tarball_when_vault_changed(tmp_path):
    """AC1/AC6: Nach einer Sitzung mit Vault-Aenderung existiert ein Snapshot,
    auch ohne dass PreCompact je gelaufen ist — der Hook wird isoliert als
    eigener Subprocess gestartet, pre-compact.mjs taucht im Testpfad nicht auf.
    """
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(vault_db),
    }

    result = run_hook({"hook_event_name": "Stop"}, env_overrides=env_overrides)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"

    slug_dir = snapshots_dir / slug
    tarballs = list(slug_dir.glob("*.tgz"))
    assert len(tarballs) == 1, f"Erwartet genau 1 .tgz, gefunden: {tarballs}"

    import tarfile

    with tarfile.open(tarballs[0], "r:gz") as tar:
        names = tar.getnames()
    assert any("vault.db" in n for n in names), f"vault.db nicht im Tarball enthalten: {names}"


def test_session_snapshot_skips_when_vault_unchanged(tmp_path):
    """AC2: Ein zweiter Lauf mit unveraendertem Vault erzeugt keinen neuen Snapshot."""
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(vault_db),
    }

    result1 = run_hook({"hook_event_name": "Stop"}, env_overrides=env_overrides)
    assert result1.returncode == 0

    slug_dir = snapshots_dir / slug
    tarballs_after_first = list(slug_dir.glob("*.tgz"))
    assert len(tarballs_after_first) == 1

    result2 = run_hook({"hook_event_name": "Stop"}, env_overrides=env_overrides)
    assert result2.returncode == 0, f"stderr: {result2.stderr}"

    tarballs_after_second = list(slug_dir.glob("*.tgz"))
    assert len(tarballs_after_second) == 1, (
        f"Unveraenderter Vault haette keinen neuen Snapshot erzeugen duerfen: "
        f"{tarballs_after_second}"
    )


def test_session_snapshot_prunes_to_retention_limit(tmp_path):
    """AC3: Retention schneidet auf ACADEMIC_SNAPSHOTS_KEEP zurueck, aeltere zuerst."""
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    slug_dir = snapshots_dir / slug
    slug_dir.mkdir(parents=True)

    keep = 3
    # 5 aeltere Dummy-Tarballs vorab anlegen (Namen sortierbar aeltester zuerst)
    for i in range(5):
        (slug_dir / f"2020010{i}-0000.tgz").write_bytes(b"dummy")

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(vault_db),
        "ACADEMIC_SNAPSHOTS_KEEP": str(keep),
    }

    result = run_hook({"hook_event_name": "Stop"}, env_overrides=env_overrides)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    tarballs = sorted(slug_dir.glob("*.tgz"))
    assert len(tarballs) == keep, f"Erwartet {keep} .tgz nach Pruning, gefunden: {tarballs}"
    # Die aeltesten Dummy-Dateien (20200100, 20200101) muessen weg sein
    names = {t.name for t in tarballs}
    assert "20200100-0000.tgz" not in names
    assert "20200101-0000.tgz" not in names

    marker = slug_dir / MARKER_NAME
    assert marker.exists(), "Marker-Datei muss Pruning ueberleben"


def test_session_snapshot_reports_last_backup_timestamp(tmp_path):
    """AC4: Sowohl im 'erstellt'- als auch im 'uebersprungen'-Pfad meldet der
    Hook auf stderr, wann zuletzt gesichert wurde, und schreibt einen validen
    Marker mit Timestamp."""
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(vault_db),
    }

    result1 = run_hook({"hook_event_name": "Stop"}, env_overrides=env_overrides)
    assert result1.returncode == 0
    assert result1.stderr.strip(), "Erster Lauf muss eine Stderr-Meldung liefern"

    marker_path = snapshots_dir / slug / MARKER_NAME
    assert marker_path.exists(), "Marker-Datei fehlt nach erfolgreichem Snapshot"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker.get("lastSnapshotAt"), "Marker enthaelt keinen Timestamp"

    result2 = run_hook({"hook_event_name": "Stop"}, env_overrides=env_overrides)
    assert result2.returncode == 0
    assert result2.stderr.strip(), "Uebersprungener Lauf muss trotzdem stderr melden"


def test_session_snapshot_failopen_on_export_failure(tmp_path):
    """AC5: Scheitert der Export, bricht die Sitzung nicht ab (exit 0), aber
    der Fehlschlag wird sichtbar gemeldet und der Marker bleibt unveraendert."""
    slug = "test-project"
    snapshots_dir = tmp_path / "snapshots"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    vault_db = tmp_path / "vault.db"
    _make_vault_db(vault_db)

    broken_python = tmp_path / "no-such-python-binary"
    fake_home = tmp_path / "fake-home"  # kein ~/.academic-research/venv hier
    fake_home.mkdir()

    # Fake-'python3' vor den Rest der geerbten PATH haengen: garantiert einen
    # scheiternden Import unabhaengig davon, welche echten Interpreter auf
    # der jeweiligen Maschine sonst noch in PATH stehen (asdf/pyenv/conda).
    # Node selbst bleibt ueber die geerbte PATH auffindbar.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python3 = fake_bin / "python3"
    fake_python3.write_text("#!/bin/sh\nexit 1\n")
    fake_python3.chmod(0o755)

    env_overrides = {
        "ACADEMIC_SNAPSHOTS_DIR": str(snapshots_dir),
        "ACADEMIC_PROJECT_SLUG": slug,
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "VAULT_DB_PATH": str(vault_db),
        "ACADEMIC_PYTHON": str(broken_python),
        "VIRTUAL_ENV": "",
        "HOME": str(fake_home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
    }

    result = run_hook({"hook_event_name": "Stop"}, env_overrides=env_overrides)
    assert result.returncode == 0, f"Erwartet fail-open exit 0, got {result.returncode}"
    assert "fehlgeschlagen" in result.stderr or "⚠️" in result.stderr, (
        f"Fehlschlag muss sichtbar gemeldet werden. stderr: {result.stderr}"
    )

    slug_dir = snapshots_dir / slug
    tarballs = list(slug_dir.glob("*.tgz")) if slug_dir.exists() else []
    assert len(tarballs) == 0, f"Bei Fehlschlag darf kein Tarball entstehen: {tarballs}"


def test_hooks_json_wires_session_snapshot_under_stop():
    """hooks/hooks.json muss session-snapshot.mjs zusaetzlich unter Stop verdrahten,
    ohne den bestehenden Inline-Bash-Reminder zu entfernen."""
    hooks_json = json.loads((WORKTREE_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    stop_entries = hooks_json["hooks"]["Stop"]
    commands = [h["command"] for e in stop_entries for h in e["hooks"]]

    assert any("session-snapshot.mjs" in c for c in commands), (
        f"session-snapshot.mjs ist nicht unter Stop verdrahtet: {commands}"
    )
    assert any("academic_context.md" in c for c in commands), (
        "Der bestehende Inline-Bash-Reminder unter Stop wurde entfernt statt ergaenzt."
    )


def test_session_snapshot_does_not_import_or_shell_out_to_pre_compact():
    """AC6: session-snapshot.mjs referenziert pre-compact.mjs nicht — beide
    Snapshot-Pfade sind unabhaengig voneinander."""
    source = HOOK_PATH.read_text(encoding="utf-8")
    assert "pre-compact" not in source, (
        "session-snapshot.mjs darf pre-compact.mjs nicht referenzieren "
        "(unabhaengiger Snapshot-Pfad, #625 AC6)."
    )
