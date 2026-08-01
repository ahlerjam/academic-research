"""Tests fuer Issue #519 — guard-schwaechende Env-Schalter sichtbar loggen.

Zwei Seiten:
  Schreibseite (hooks/verbatim-guard.mjs::logEnvSwitchUsage) — AC1: jeder
    Guard-Lauf auf einer geschuetzten Datei mit gesetztem Schalter erzeugt
    genau einen Logeintrag mit Schalter, Wert und Zieldatei.
  Leseseite (hooks/bypass-log-report.mjs) — AC2: die SessionStart-Meldung
    schliesst diese Eintraege in einem eigenen Abschnitt ein.

Die drei betroffenen Schalter: ACADEMIC_CITATION_AMBIGUOUS,
ACADEMIC_CITATION_CASCADE, ACADEMIC_CITATION_MAX_PER_WRITE.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
GUARD_PATH = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
REPORT_PATH = REPO_ROOT / "hooks" / "bypass-log-report.mjs"


def run_guard(tool_input: dict, env_overrides: dict) -> subprocess.CompletedProcess:
    """Startet verbatim-guard.mjs als Subprocess mit einem Write-Payload."""
    payload = json.dumps({"tool_name": "Write", "tool_input": tool_input})
    env = os.environ.copy()
    env.update(env_overrides)
    # Vault-DB bewusst fehlend lassen (fail-open) — der Content enthaelt
    # ohnehin keine Zitate/Belege, die einen Vault-Lookup ausloesen wuerden.
    env.pop("VAULT_DB_PATH", None)
    return subprocess.run(
        ["node", str(GUARD_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def run_report(env_overrides: dict) -> subprocess.CompletedProcess:
    payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup"})
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        ["node", str(REPORT_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def base_env(tmp_path: Path) -> dict:
    return {
        "VAULT_GUARD_BYPASS_LOG": str(tmp_path / "bypass.log"),
        "VAULT_GUARD_ENV_SWITCH_LOG": str(tmp_path / "env-switch.log"),
        "VAULT_DB_PATH": str(tmp_path / "does-not-exist.db"),
    }


# ---------------------------------------------------------------------------
# AC1 — Schreibseite: genau ein Logeintrag pro gesetztem Schalter
# ---------------------------------------------------------------------------


def test_single_switch_writes_one_log_line_with_name_value_and_file(tmp_path):
    env = base_env(tmp_path)
    log_path = Path(env["VAULT_GUARD_ENV_SWITCH_LOG"])
    env["ACADEMIC_CITATION_AMBIGUOUS"] = "mark"

    result = run_guard(
        {"file_path": "kapitel/kap1.md", "content": "Normaler Text ohne Belege."},
        env,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert log_path.exists(), "Env-Switch-Log wurde nicht angelegt"
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, f"Erwartet genau eine Zeile, gefunden: {lines!r}"
    assert "ACADEMIC_CITATION_AMBIGUOUS=mark" in lines[0]
    assert "kapitel/kap1.md" in lines[0]


def test_all_three_switches_set_write_three_distinct_lines(tmp_path):
    env = base_env(tmp_path)
    log_path = Path(env["VAULT_GUARD_ENV_SWITCH_LOG"])
    env["ACADEMIC_CITATION_AMBIGUOUS"] = "mark"
    env["ACADEMIC_CITATION_CASCADE"] = "off"
    env["ACADEMIC_CITATION_MAX_PER_WRITE"] = "5"

    result = run_guard(
        {"file_path": "kapitel/kap2.md", "content": "Text ohne Belege."},
        env,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3, f"Erwartet drei Zeilen, gefunden: {lines!r}"
    joined = "\n".join(lines)
    assert "ACADEMIC_CITATION_AMBIGUOUS=mark" in joined
    assert "ACADEMIC_CITATION_CASCADE=off" in joined
    assert "ACADEMIC_CITATION_MAX_PER_WRITE=5" in joined
    for line in lines:
        assert "kapitel/kap2.md" in line


def test_no_switches_set_writes_no_log_line(tmp_path):
    env = base_env(tmp_path)
    log_path = Path(env["VAULT_GUARD_ENV_SWITCH_LOG"])
    for name in (
        "ACADEMIC_CITATION_AMBIGUOUS",
        "ACADEMIC_CITATION_CASCADE",
        "ACADEMIC_CITATION_MAX_PER_WRITE",
    ):
        env.pop(name, None)

    result = run_guard(
        {"file_path": "kapitel/kap3.md", "content": "Text ohne Belege."},
        env,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert not log_path.exists(), "Ohne gesetzte Schalter darf kein Log entstehen"


def test_unprotected_path_does_not_log_even_with_switch_set(tmp_path):
    """Der Schalter greift nur auf geschuetzten Pfaden (kapitel/*.md, *.tex)."""
    env = base_env(tmp_path)
    log_path = Path(env["VAULT_GUARD_ENV_SWITCH_LOG"])
    env["ACADEMIC_CITATION_AMBIGUOUS"] = "mark"

    result = run_guard(
        {"file_path": "notizen/sonstiges.md", "content": "Text ohne Belege."},
        env,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert not log_path.exists()


# ---------------------------------------------------------------------------
# AC2 — Leseseite: SessionStart-Report zeigt neue Env-Switch-Eintraege
# ---------------------------------------------------------------------------


def test_session_start_report_includes_env_switch_section(tmp_path):
    guard_env = base_env(tmp_path)
    guard_env["ACADEMIC_CITATION_AMBIGUOUS"] = "mark"
    guard_result = run_guard(
        {"file_path": "kapitel/kap4.md", "content": "Text ohne Belege."},
        guard_env,
    )
    assert guard_result.returncode == 0, f"stderr: {guard_result.stderr}"

    report_env = {
        "VAULT_GUARD_BYPASS_LOG": guard_env["VAULT_GUARD_BYPASS_LOG"],
        "VAULT_GUARD_ENV_SWITCH_LOG": guard_env["VAULT_GUARD_ENV_SWITCH_LOG"],
        "VAULT_GUARD_BYPASS_REPORT_STATE": str(tmp_path / "bypass-state.json"),
        "VAULT_GUARD_ENV_SWITCH_REPORT_STATE": str(tmp_path / "env-switch-state.json"),
    }
    report_result = run_report(report_env)

    assert report_result.returncode == 0, f"stderr: {report_result.stderr}"
    assert "ACADEMIC_CITATION_AMBIGUOUS" in report_result.stdout
    assert "mark" in report_result.stdout
    assert "kapitel/kap4.md" in report_result.stdout


def test_second_report_run_without_new_activity_is_silent_on_env_switch(tmp_path):
    guard_env = base_env(tmp_path)
    guard_env["ACADEMIC_CITATION_CASCADE"] = "off"
    guard_result = run_guard(
        {"file_path": "kapitel/kap5.md", "content": "Text ohne Belege."},
        guard_env,
    )
    assert guard_result.returncode == 0, f"stderr: {guard_result.stderr}"

    report_env = {
        "VAULT_GUARD_BYPASS_LOG": guard_env["VAULT_GUARD_BYPASS_LOG"],
        "VAULT_GUARD_ENV_SWITCH_LOG": guard_env["VAULT_GUARD_ENV_SWITCH_LOG"],
        "VAULT_GUARD_BYPASS_REPORT_STATE": str(tmp_path / "bypass-state.json"),
        "VAULT_GUARD_ENV_SWITCH_REPORT_STATE": str(tmp_path / "env-switch-state.json"),
    }

    first = run_report(report_env)
    assert first.returncode == 0
    assert "ACADEMIC_CITATION_CASCADE" in first.stdout

    second = run_report(report_env)
    assert second.returncode == 0
    assert "ACADEMIC_CITATION_CASCADE" not in second.stdout, (
        f"Zweiter Lauf ohne neue Aktivitaet darf keinen Env-Switch-Abschnitt zeigen: "
        f"{second.stdout!r}"
    )


def test_report_without_any_log_present_is_silent(tmp_path):
    report_env = {
        "VAULT_GUARD_BYPASS_LOG": str(tmp_path / "no-bypass.log"),
        "VAULT_GUARD_ENV_SWITCH_LOG": str(tmp_path / "no-env-switch.log"),
        "VAULT_GUARD_BYPASS_REPORT_STATE": str(tmp_path / "bypass-state.json"),
        "VAULT_GUARD_ENV_SWITCH_REPORT_STATE": str(tmp_path / "env-switch-state.json"),
    }

    result = run_report(report_env)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Fail-open: Log-Verzeichnis nicht schreibbar blockiert den Guard nicht
# ---------------------------------------------------------------------------


def test_unwritable_log_dir_does_not_block_guard(tmp_path):
    unwritable_parent = tmp_path / "readonly"
    unwritable_parent.mkdir(mode=0o500)
    env = base_env(tmp_path)
    env["VAULT_GUARD_ENV_SWITCH_LOG"] = str(unwritable_parent / "nested" / "env-switch.log")
    env["ACADEMIC_CITATION_AMBIGUOUS"] = "mark"

    try:
        result = run_guard(
            {"file_path": "kapitel/kap6.md", "content": "Text ohne Belege."},
            env,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
    finally:
        unwritable_parent.chmod(0o700)
