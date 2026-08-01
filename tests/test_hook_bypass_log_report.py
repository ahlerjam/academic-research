"""Tests fuer Issue #517 — SessionStart-Hook meldet neue vault-guard-Bypaesse.

Der Hook `hooks/bypass-log-report.mjs` liest das Bypass-Log
(`VAULT_GUARD_BYPASS_LOG`, geschrieben von `verbatim-guard.mjs`) ab einem
persistierten Byte-Offset und meldet neue Eintraege seit dem letzten
SessionStart auf stdout. Scope laut Issue: NUR die Leseseite — die Schreibseite
(`verbatim-guard.mjs`) bleibt unangetastet.

Abgedeckt:
  AC1 — Nach Bypass-Nutzung erscheint beim naechsten SessionStart ein Hinweis
        mit Zaehler + betroffenen Dateien; ein Folgelauf ohne neue Zeilen
        zaehlt keine neuen Eintraege mehr.
  AC2 — Ohne neue Eintraege erscheint keine Meldung (kein Rauschen).
  AC3 — Lese-/Rotationsfehler blockieren den SessionStart nie (fail-open,
        exit 0): fehlende Logdatei, "rotierte" (geschrumpfte) Logdatei,
        korrupte State-Datei.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "bypass-log-report.mjs"


def run_hook(env_overrides: dict) -> subprocess.CompletedProcess:
    """Startet den Hook als Subprocess mit einem minimalen SessionStart-Payload."""
    payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup"})
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def write_bypass_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# AC1 — Hinweis mit Zaehler + betroffenen Dateien nach Bypass-Nutzung
# ---------------------------------------------------------------------------


def test_reports_count_and_files_for_new_bypass_entries(tmp_path):
    log_path = tmp_path / "vault-guard-bypass.log"
    state_path = tmp_path / "report-state.json"
    write_bypass_log(
        log_path,
        [
            "2026-08-01T09:00:00.000Z | vault-guard: skip | kapitel/kap1.md",
            "2026-08-01T09:05:00.000Z | vault-guard: skip | kapitel/kap2.md",
        ],
    )

    result = run_hook(
        {
            "VAULT_GUARD_BYPASS_LOG": str(log_path),
            "VAULT_GUARD_BYPASS_REPORT_STATE": str(state_path),
        }
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "2" in result.stdout, f"Zaehler fehlt in stdout: {result.stdout!r}"
    assert "kapitel/kap1.md" in result.stdout
    assert "kapitel/kap2.md" in result.stdout


def test_second_run_after_state_persisted_finds_no_new_entries(tmp_path):
    log_path = tmp_path / "vault-guard-bypass.log"
    state_path = tmp_path / "report-state.json"
    write_bypass_log(
        log_path,
        ["2026-08-01T09:00:00.000Z | vault-guard: skip | kapitel/kap1.md"],
    )
    env = {
        "VAULT_GUARD_BYPASS_LOG": str(log_path),
        "VAULT_GUARD_BYPASS_REPORT_STATE": str(state_path),
    }

    first = run_hook(env)
    assert first.returncode == 0
    assert "kapitel/kap1.md" in first.stdout

    second = run_hook(env)
    assert second.returncode == 0
    assert second.stdout.strip() == "", (
        f"Zweiter Lauf ohne neue Zeilen darf nichts melden: {second.stdout!r}"
    )


# ---------------------------------------------------------------------------
# AC2 — kein Rauschen ohne neue Eintraege
# ---------------------------------------------------------------------------


def test_no_output_when_log_unchanged_between_runs(tmp_path):
    log_path = tmp_path / "vault-guard-bypass.log"
    state_path = tmp_path / "report-state.json"
    write_bypass_log(
        log_path,
        ["2026-08-01T09:00:00.000Z | vault-guard: skip | kapitel/kap1.md"],
    )
    env = {
        "VAULT_GUARD_BYPASS_LOG": str(log_path),
        "VAULT_GUARD_BYPASS_REPORT_STATE": str(state_path),
    }

    run_hook(env)  # State auf aktuellen Stand bringen
    second = run_hook(env)

    assert second.returncode == 0
    assert second.stdout.strip() == ""


def test_no_output_when_log_never_existed(tmp_path):
    log_path = tmp_path / "does-not-exist.log"
    state_path = tmp_path / "report-state.json"

    result = run_hook(
        {
            "VAULT_GUARD_BYPASS_LOG": str(log_path),
            "VAULT_GUARD_BYPASS_REPORT_STATE": str(state_path),
        }
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# AC3 — Lese-/Rotationsfehler blockieren nie
# ---------------------------------------------------------------------------


def test_missing_log_file_is_fail_open(tmp_path):
    log_path = tmp_path / "missing.log"
    state_path = tmp_path / "report-state.json"

    result = run_hook(
        {
            "VAULT_GUARD_BYPASS_LOG": str(log_path),
            "VAULT_GUARD_BYPASS_REPORT_STATE": str(state_path),
        }
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_shrunk_log_file_resets_offset_instead_of_crashing(tmp_path):
    """Simuliert externe Rotation: Logdatei ist kuerzer als der gespeicherte Offset."""
    log_path = tmp_path / "vault-guard-bypass.log"
    state_path = tmp_path / "report-state.json"
    env = {
        "VAULT_GUARD_BYPASS_LOG": str(log_path),
        "VAULT_GUARD_BYPASS_REPORT_STATE": str(state_path),
    }

    # Erster Lauf: grosses Log, Offset wird auf die volle Groesse gesetzt.
    write_bypass_log(
        log_path,
        [
            "2026-08-01T09:00:00.000Z | vault-guard: skip | kapitel/kap1.md",
            "2026-08-01T09:01:00.000Z | vault-guard: skip | kapitel/kap2.md",
            "2026-08-01T09:02:00.000Z | vault-guard: skip | kapitel/kap3.md",
        ],
    )
    first = run_hook(env)
    assert first.returncode == 0

    # "Rotation": Log wird durch eine kuerzere Datei ersetzt (Groesse < Offset).
    log_path.write_text(
        "2026-08-01T10:00:00.000Z | vault-guard: skip | kapitel/kap-neu.md\n",
        encoding="utf-8",
    )

    second = run_hook(env)

    assert second.returncode == 0, f"stderr: {second.stderr}"
    assert "kapitel/kap-neu.md" in second.stdout, (
        f"Nach Offset-Reset sollte die verbliebene Zeile als neu gelten: {second.stdout!r}"
    )


def test_corrupt_state_file_warns_on_stderr_and_stays_fail_open(tmp_path):
    log_path = tmp_path / "vault-guard-bypass.log"
    state_path = tmp_path / "report-state.json"
    write_bypass_log(
        log_path,
        ["2026-08-01T09:00:00.000Z | vault-guard: skip | kapitel/kap1.md"],
    )
    state_path.write_text("{ das ist kein gueltiges JSON", encoding="utf-8")

    result = run_hook(
        {
            "VAULT_GUARD_BYPASS_LOG": str(log_path),
            "VAULT_GUARD_BYPASS_REPORT_STATE": str(state_path),
        }
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert result.stderr.strip() != "", "Erwartet eine stderr-Warnung bei korrupter State-Datei"
    # Verhaelt sich wie ohne State: die vorhandene Zeile gilt als neu.
    assert "kapitel/kap1.md" in result.stdout
