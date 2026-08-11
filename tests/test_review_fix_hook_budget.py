"""Regression-Tests fuer Finding 15 (Code-Review, Trigger-Mess-Harness).

``hooks/claim-drift-guard.mjs`` und ``hooks/mid-session-reinforcement.mjs``
trugen bisher je eine eigene Kopie von ``pythonCandidates()`` samt eigener
``execFileSync``-Schleife statt ``runVaultPython()`` aus
``hooks/lib/vault-bridge.mjs`` zu nutzen -- und ohne Gesamtbudget gegen das
Hook-Timeout aus ``hooks/hooks.json``.

Konkret:
  - claim-drift-guard.mjs: Hook-Timeout 15 s (hooks.json). Ohne Budget kann
    ``lookupQuotes()`` bis zu vier Kandidaten a 10 s durchprobieren (bis zu
    40 s) -- Claude Code toetet den Hook laengst vorher, die Claim-Drift-Pruefung
    faellt fuer den betroffenen Schreibvorgang ganz aus.
  - mid-session-reinforcement.mjs: Hook-Timeout ebenfalls 15 s (UserPromptSubmit
    UND SessionStart/compact). ``runVaultPython()`` wurde zwar schon verwendet,
    aber ohne ``budget``-Option (Default in vault-bridge.mjs: ``Infinity``) --
    derselbe unbeschraenkte Kandidaten-Durchlauf.

Diese Tests binden ALLE VIER Interpreter-Kandidaten (ACADEMIC_PYTHON,
$VIRTUAL_ENV/bin/python, ~/.academic-research/venv/bin/python, PATH-python3)
an denselben langsam scheiternden Stub und messen die Wanduhrzeit: ohne
Gesamtbudget braucht der Lookup laenger als das Hook-Timeout erlaubt, mit
Budget bleibt er klar darunter.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CLAIM_DRIFT_HOOK = REPO_ROOT / "hooks" / "claim-drift-guard.mjs"
REINFORCEMENT_HOOK = REPO_ROOT / "hooks" / "mid-session-reinforcement.mjs"

# Jeder Kandidat braucht diese Zeit, um zu scheitern. Vier Kandidaten ohne
# Budget summieren sich auf 4 * STUB_SLEEP_S; das muss klar ueber dem
# Hook-Timeout (15 s in hooks.json) liegen, damit der Unterschied zwischen
# "mit" und "ohne" Budget zuverlaessig messbar ist.
STUB_SLEEP_S = 3.5
UNBUDGETED_TOTAL_S = 4 * STUB_SLEEP_S  # 14 s
# Deadline, die nur mit funktionierendem Gesamtbudget einzuhalten ist: klar
# unter UNBUDGETED_TOTAL_S, aber mit Puffer ueber der budgetierten Laufzeit
# (~10 s bei budget=10000ms, siehe Fix).
TEST_DEADLINE_S = 12.0


def _write_slow_failing_stub(path: Path) -> None:
    """Legt ein ausfuehrbares Skript an, das STUB_SLEEP_S schlaeft und dann scheitert."""
    path.write_text(
        f"#!/bin/sh\nsleep {STUB_SLEEP_S}\necho 'stub: kein echtes Python' >&2\nexit 1\n"
    )
    path.chmod(0o755)


def _rig_all_four_candidates_slow(tmp_path: Path) -> dict:
    """Bindet alle vier Interpreter-Kandidaten an denselben langsamen Fehlschlag-Stub.

    Kandidaten-Kaskade (hooks/lib/vault-bridge.mjs::pythonCandidates()):
      1. ACADEMIC_PYTHON
      2. $VIRTUAL_ENV/bin/python
      3. ~/.academic-research/venv/bin/python (haengt an HOME)
      4. python3 aus PATH
    """
    home = tmp_path / "home"
    home.mkdir()

    academic_python = tmp_path / "academic-python-stub"
    _write_slow_failing_stub(academic_python)

    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    _write_slow_failing_stub(venv_dir / "bin" / "python")

    home_venv_bin = home / ".academic-research" / "venv" / "bin"
    home_venv_bin.mkdir(parents=True)
    _write_slow_failing_stub(home_venv_bin / "python")

    path_bin = tmp_path / "pathbin"
    path_bin.mkdir()
    _write_slow_failing_stub(path_bin / "python3")

    return {
        "HOME": str(home),
        "ACADEMIC_PYTHON": str(academic_python),
        "VIRTUAL_ENV": str(venv_dir),
        # Der Stub-PATH-Eintrag muss VOR dem Rest stehen, sonst gewinnt ein
        # echtes System-python3 und der Kandidat scheitert sofort statt langsam.
        "PATH": f"{path_bin}:{os.environ.get('PATH', '')}",
    }


def _run_with_deadline(cmd: list[str], payload: dict, env: dict, deadline_s: float):
    """Startet den Hook und meldet, ob er innerhalb von deadline_s fertig wurde.

    Gibt (finished_in_time, completed_process_or_None) zurueck, statt die
    Deadline als hartes Testkriterium ueber subprocess.run(timeout=...) zu
    erzwingen -- so bleibt der Prozess sauber terminiert und der Testausgang
    ist eine Assertion, kein Timeout-Traceback.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(input=json.dumps(payload), timeout=deadline_s)
        return True, subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return False, None


def _node_binary() -> str:
    """Realer Node-Interpreter-Pfad (kein Versionsmanager-Shim, siehe test_hook_midsession.py)."""
    shim = shutil.which("node")
    if shim is None:  # pragma: no cover - node ist Testvoraussetzung
        pytest.skip("node nicht im PATH")
    try:
        proc = subprocess.run(
            [shim, "-e", "process.stdout.write(process.execPath)"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - Defensive
        return shim
    real = proc.stdout.strip()
    if proc.returncode == 0 and real and Path(real).is_file():
        return real
    return shim  # pragma: no cover


# ---------------------------------------------------------------------------
# mid-session-reinforcement.mjs
# ---------------------------------------------------------------------------


def test_reinforcement_lookup_stays_within_hook_timeout_budget(tmp_path):
    """UserPromptSubmit-Timeout in hooks.json ist 15 s; der Vault-Lookup muss
    darunter bleiben, selbst wenn alle vier Interpreter-Kandidaten langsam
    scheitern (Finding 15: fehlendes ``budget`` an ``runVaultPython()``).
    """
    rig_env = _rig_all_four_candidates_slow(tmp_path)
    env = {
        **os.environ,
        **rig_env,
        "VAULT_DB_PATH": str(tmp_path / "nonexistent-vault-triggers-python-path.db"),
        "ACADEMIC_REINFORCEMENT_STATE": str(tmp_path / "state.json"),
        "ACADEMIC_REINFORCEMENT_N": "1",
    }
    # VAULT_DB muss existieren, sonst bricht loadTopDecisions() vor dem
    # Python-Lookup ab und der Stub wird nie aufgerufen.
    Path(env["VAULT_DB_PATH"]).write_bytes(b"")

    finished, result = _run_with_deadline(
        [_node_binary(), str(REINFORCEMENT_HOOK)],
        {"hook_event_name": "UserPromptSubmit"},
        env,
        TEST_DEADLINE_S,
    )
    assert finished, (
        f"Der Reinforcement-Hook lief laenger als {TEST_DEADLINE_S}s (Hook-Timeout in "
        "hooks.json: 15s fuer UserPromptSubmit) -- runVaultPython() bekommt kein "
        "Gesamtbudget und probiert alle vier Interpreter-Kandidaten nacheinander "
        f"durch (ungebudgetet ~{UNBUDGETED_TOTAL_S:.0f}s)."
    )
    assert result.returncode == 0, f"Hook darf nie blockieren: {result.stderr}"


# ---------------------------------------------------------------------------
# claim-drift-guard.mjs
# ---------------------------------------------------------------------------

VAULT_VERBATIM = "Der Effekt war in allen Kohorten nachweisbar."
CHAPTER_OLD = (
    "## Ergebnisse\n\n"
    "Die Studie zeigt einen moderaten Effekt auf die Lesekompetenz. "
    f'"{VAULT_VERBATIM}" (Mueller 2021, S. 45)\n'
)
CHAPTER_NEW_DRIFTED = CHAPTER_OLD.replace("moderaten", "starken")


def test_claim_drift_lookup_stays_within_hook_timeout_budget(tmp_path):
    """PreToolUse-Timeout fuer claim-drift-guard.mjs ist 15 s (hooks.json). Die
    lokale ``lookupQuotes()``-Kopie probiert bislang bis zu vier Kandidaten a
    10 s Einzel-Timeout OHNE Gesamtbudget durch (Finding 15).
    """
    rig_env = _rig_all_four_candidates_slow(tmp_path)
    # existsSync(VAULT_DB) muss true sein, damit lookupQuotes() ueberhaupt einen
    # Interpreter startet -- der Dateiinhalt ist irrelevant, der Stub scheitert
    # ohnehin vor jedem echten Vault-Zugriff.
    vault_db = tmp_path / "dummy-vault.db"
    vault_db.write_bytes(b"")

    env = {**os.environ, **rig_env, "VAULT_DB_PATH": str(vault_db)}
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "kapitel/kap1.md",
            "old_string": CHAPTER_OLD,
            "new_string": CHAPTER_NEW_DRIFTED,
        },
    }

    finished, result = _run_with_deadline(
        [_node_binary(), str(CLAIM_DRIFT_HOOK)],
        payload,
        env,
        TEST_DEADLINE_S,
    )
    assert finished, (
        f"Der Claim-Drift-Guard lief laenger als {TEST_DEADLINE_S}s (Hook-Timeout in "
        "hooks.json: 15s) -- die lokale lookupQuotes()-Schleife hat kein "
        f"Gesamtbudget und probiert bis zu vier Kandidaten a 10s durch "
        f"(ungebudgetet ~{UNBUDGETED_TOTAL_S:.0f}s)."
    )
    assert result.returncode == 0, f"Hook darf nie blockieren: {result.stderr}"


def test_claim_drift_uses_shared_vault_bridge_not_local_copy():
    """Finding 15: keine eigene ``pythonCandidates()``-Kopie mehr im Hook --
    der Interpreter-Lookup kommt aus ``hooks/lib/vault-bridge.mjs``.
    """
    source = CLAIM_DRIFT_HOOK.read_text(encoding="utf-8")
    assert "function pythonCandidates" not in source, (
        "claim-drift-guard.mjs traegt weiterhin eine eigene pythonCandidates()-Kopie "
        "statt runVaultPython() aus hooks/lib/vault-bridge.mjs zu nutzen."
    )
    assert "from './lib/vault-bridge.mjs'" in source, (
        "claim-drift-guard.mjs importiert die gemeinsame Vault-Bruecke nicht."
    )


def test_reinforcement_passes_explicit_budget_to_shared_bridge():
    """Finding 15: ``runVaultPython()`` bekommt in mid-session-reinforcement.mjs
    explizit ein ``budget`` -- sonst bleibt der Default (Infinity) wirksam.
    """
    source = REINFORCEMENT_HOOK.read_text(encoding="utf-8")
    assert "budget" in source, (
        "mid-session-reinforcement.mjs uebergibt runVaultPython() kein budget -- "
        "der Kandidaten-Durchlauf bleibt gegen das 15s-Hook-Timeout unbeschraenkt."
    )
