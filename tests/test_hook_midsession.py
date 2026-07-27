"""Tests fuer mid-session-reinforcement.mjs Reinforcement-Hook.

Der Hook ist nicht-blockierend und laeuft auf zwei Events, deren stdout laut
Claude-Code-Doku tatsaechlich als Modell-Kontext injiziert wird (#382):
  - UserPromptSubmit: Trigger nach jeder 20. User-Message.
  - SessionStart mit source="compact": Trigger nach Compaction.
Liest Top-5 aktive Decisions aus Vault und erinnert Modell als System-Hint.
Max 1× pro 20 Messages.
Exit 0 immer.
"""

import json
import os
import subprocess
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "mid-session-reinforcement.mjs"
WORKTREE_ROOT = Path(__file__).parent.parent


def run_hook(payload: dict, env_overrides: dict = None) -> subprocess.CompletedProcess:
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
        timeout=15,
    )


def test_hook_exits_zero_always():
    """Hook ist immer exit 0 (nie blockierend, auch bei leerem Payload)."""
    result = run_hook({})
    assert result.returncode == 0


def test_hook_exits_zero_on_userpromptsubmit_event():
    """Hook verarbeitet UserPromptSubmit-Event ohne Fehler."""
    payload = {
        "hook_event_name": "UserPromptSubmit",
    }
    result = run_hook(payload)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"


def test_hook_outputs_hint_on_userpromptsubmit(tmp_path):
    """Hook gibt System-Hint mit Decision-Inhalt aus, wenn der Intervall-Zaehler erreicht ist.

    `ACADEMIC_REINFORCEMENT_N=1` macht bereits den ersten realen
    UserPromptSubmit-Aufruf zum Trigger (kein `message_count` im Payload —
    das Feld existiert im realen Payload nicht, siehe #382 P2-Fix).
    """
    # Erstelle Vault mit Decisions
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()

    add_decision(
        db_path,
        category="Zitierstil",
        text="APA 7th Edition verwenden",
        rationale="Fachbereich-Standard",
    )
    add_decision(
        db_path,
        category="Methodik",
        text="Systematisches Review nach PRISMA",
        rationale="Qualitaetsanforderung",
    )

    state_file = tmp_path / "reinforcement_state.json"

    payload = {
        "hook_event_name": "UserPromptSubmit",
    }
    env_overrides = {
        "VAULT_DB_PATH": db_path,
        "ACADEMIC_REINFORCEMENT_STATE": str(state_file),
        "ACADEMIC_REINFORCEMENT_N": "1",
    }

    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"

    # Hook soll Reminder ausgeben (stdout oder stderr)
    combined = result.stdout + result.stderr
    # Hint soll Decisions enthalten
    assert (
        "APA" in combined or "PRISMA" in combined or "Decision" in combined or "Aktive" in combined
    ), f"Kein Decision-Hint in Ausgabe: stdout={result.stdout!r}, stderr={result.stderr!r}"


def test_hook_no_output_before_interval_reached(tmp_path):
    """Hook gibt keinen Hint aus, solange der Intervall-Zaehler TRIGGER_N noch nicht erreicht hat."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_decision(db_path, category="test", text="Testdecision", rationale=None)

    state_file = tmp_path / "reinforcement_state.json"

    payload = {
        "hook_event_name": "UserPromptSubmit",
    }
    env_overrides = {
        "VAULT_DB_PATH": db_path,
        "ACADEMIC_REINFORCEMENT_STATE": str(state_file),
        "ACADEMIC_REINFORCEMENT_N": "5",
    }

    # Erster Aufruf (prompt_count=1) liegt weit vor TRIGGER_N=5 -> kein Reminder.
    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "Aktive Decisions" not in combined, f"Unerwarteter Hint vor Intervall: {combined}"


def test_hook_fires_max_once_per_interval(tmp_path):
    """Hook loest max 1× pro Intervall aus (persistenter Zaehler in der State-Datei)."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_decision(db_path, category="test", text="Entscheidung A", rationale=None)

    state_file = tmp_path / "reinforcement_state.json"
    env_overrides = {
        "VAULT_DB_PATH": db_path,
        "ACADEMIC_REINFORCEMENT_STATE": str(state_file),
        "ACADEMIC_REINFORCEMENT_N": "3",
    }
    payload = {"hook_event_name": "UserPromptSubmit"}

    # Aufrufe 1 und 2 (prompt_count 1, 2) -> kein Hint.
    result1 = run_hook(payload, env_overrides=env_overrides)
    result2 = run_hook(payload, env_overrides=env_overrides)
    # Aufruf 3 (prompt_count == TRIGGER_N) -> Hint.
    result3 = run_hook(payload, env_overrides=env_overrides)
    # Aufruf 4 (prompt_count == TRIGGER_N + 1) -> wieder kein Hint.
    result4 = run_hook(payload, env_overrides=env_overrides)

    for i, result in enumerate([result1, result2, result3, result4], start=1):
        assert result.returncode == 0, f"Aufruf {i}: erwartet 0, got {result.returncode}"

    combined1 = result1.stdout + result1.stderr
    combined2 = result2.stdout + result2.stderr
    combined3 = result3.stdout + result3.stderr
    combined4 = result4.stdout + result4.stderr

    assert "Aktive Decisions" not in combined1, f"Aufruf 1 sollte keinen Hint haben: {combined1!r}"
    assert "Aktive Decisions" not in combined2, f"Aufruf 2 sollte keinen Hint haben: {combined2!r}"
    assert "Entscheidung" in combined3 or "Aktive Decisions" in combined3, (
        f"Aufruf 3 (TRIGGER_N) sollte Hint haben: {combined3!r}"
    )
    assert "Aktive Decisions" not in combined4, (
        f"Aufruf 4 sollte nicht sofort erneut triggern: {combined4!r}"
    )


def test_hook_triggers_after_compaction(tmp_path):
    """Hook gibt Hint aus nach SessionStart(source=compact), unabhaengig vom Intervall-Zaehler."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_decision(db_path, category="Methodik", text="Qualitative Analyse", rationale=None)

    state_file = tmp_path / "reinforcement_state.json"

    payload = {
        "hook_event_name": "SessionStart",
        "source": "compact",
    }
    env_overrides = {
        "VAULT_DB_PATH": db_path,
        "ACADEMIC_REINFORCEMENT_STATE": str(state_file),
    }

    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"

    combined = result.stdout + result.stderr
    assert "Qualitative" in combined or "Aktive" in combined or "Decision" in combined, (
        f"Kein Hint nach Compaction: stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


def test_hook_triggers_on_real_userpromptsubmit_payload_without_message_count(tmp_path):
    """Regression-Test fuer Issue #382 P2-Finding.

    Der reale UserPromptSubmit-Payload von Claude Code enthaelt laut Doku
    (code.claude.com/docs/en/hooks) KEIN `message_count`-Feld (nur session_id,
    prompt_id, transcript_path, cwd, permission_mode, effort, hook_event_name,
    optional agent_id/agent_type). Der Hook darf sich daher fuer den
    Intervall-Trigger nicht auf ein synthetisches `message_count` verlassen —
    sonst bleibt `messageCount` immer 0 und der Trigger feuert nie (siehe
    flowkit-code-review P2 auf PR #420).

    Simuliert TRIGGER_N reale Aufrufe (kein message_count im Payload) und
    erwartet einen Hint erst beim TRIGGER_N-ten Aufruf.
    """
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_decision(
        db_path, category="Methodik", text="Reale Payload ohne message_count", rationale=None
    )

    state_file = tmp_path / "reinforcement_state.json"
    trigger_n = 3
    env_overrides = {
        "VAULT_DB_PATH": db_path,
        "ACADEMIC_REINFORCEMENT_STATE": str(state_file),
        "ACADEMIC_REINFORCEMENT_N": str(trigger_n),
    }

    # Realer Payload: session_id/prompt_id/transcript_path/cwd/permission_mode/
    # hook_event_name — explizit KEIN message_count.
    real_payload = {
        "session_id": "sess-123",
        "prompt_id": "prompt-1",
        "transcript_path": str(tmp_path / "transcript.jsonl"),
        "cwd": str(tmp_path),
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
    }

    results = [run_hook(dict(real_payload), env_overrides=env_overrides) for _ in range(trigger_n)]
    for i, result in enumerate(results, start=1):
        assert result.returncode == 0, (
            f"Aufruf {i}: erwartet 0, got {result.returncode}. stderr: {result.stderr}"
        )

    combined_before = results[0].stdout + results[0].stderr
    combined_last = results[-1].stdout + results[-1].stderr

    assert "Aktive Decisions" not in combined_before, (
        f"Unerwarteter Hint vor Erreichen von TRIGGER_N: {combined_before!r}"
    )
    assert "Reale Payload" in combined_last or "Aktive Decisions" in combined_last, (
        f"Kein Hint beim {trigger_n}. Aufruf trotz realem Payload: stdout={results[-1].stdout!r}, "
        f"stderr={results[-1].stderr!r}"
    )


def test_hook_no_trigger_on_sessionstart_without_compact_source(tmp_path):
    """SessionStart mit anderer source (z. B. 'startup') loest KEINEN Hint aus.

    Regression-Guard: nur der explizite Compaction-Matcher darf feuern, nicht
    jeder SessionStart (sonst wuerde der Hook bei jedem Sessionstart triggern).
    """
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_decision(db_path, category="Methodik", text="Sollte nicht erscheinen", rationale=None)

    state_file = tmp_path / "reinforcement_state.json"

    payload = {
        "hook_event_name": "SessionStart",
        "source": "startup",
    }
    env_overrides = {
        "VAULT_DB_PATH": db_path,
        "ACADEMIC_REINFORCEMENT_STATE": str(state_file),
    }

    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "Aktive Decisions" not in combined, (
        f"Unerwarteter Hint bei SessionStart/startup: {combined}"
    )


def test_hook_failopen_when_vault_missing():
    """Hook ist fail-open wenn Vault-DB nicht existiert."""
    payload = {
        "hook_event_name": "UserPromptSubmit",
    }
    env_overrides = {
        "VAULT_DB_PATH": "/nonexistent/vault.db",
        "ACADEMIC_REINFORCEMENT_STATE": "/tmp/test_state_nonexistent.json",
        "ACADEMIC_REINFORCEMENT_N": "1",
    }
    result = run_hook(payload, env_overrides=env_overrides)
    assert result.returncode == 0, (
        f"Erwartet 0 (fail-open), got {result.returncode}. stderr: {result.stderr}"
    )
