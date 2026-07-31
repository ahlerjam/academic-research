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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def make_unusable_python3_path(tmp_path) -> str:
    """PATH, dessen `python3` den Vault-Import nicht leisten kann.

    Bildet die reale Endnutzer-Situation nach: in einer echten Claude-Code-Session
    erbt der Hook die Shell-PATH des Nutzers, dort steht typischerweise das
    System-Python (macOS: /usr/bin/python3 == 3.9), das `academic_vault` mangels
    PEP-604-Syntax gar nicht importieren kann. Der Stub scheitert wie dieses
    Interpreter-Exemplar: Exit != 0 mit Traceback auf stderr.

    Der PATH enthaelt zusaetzlich alles, was zum Starten von `node` noetig ist —
    auch dann, wenn `node` selbst ein Shell-Shim ist (asdf/nvm/volta/mise:
    `#!/usr/bin/env bash`, exec auf den eigentlichen Versionsmanager). Dafuer
    wird der Stub vor das volle, unveraenderte `os.environ["PATH"]` gesetzt statt
    eine eigene Minimal-Liste zu bauen: die reale PATH-Struktur bleibt erhalten,
    also bleiben auch transitive Abhaengigkeiten des Shims (bash, asdf/nvm/volta
    selbst) aufloesbar. Die Garantie "kein brauchbares python3 erreichbar" bleibt
    davon unberuehrt, weil Standard-PATH-Auflösung (execvp/`which`) immer den
    ersten Treffer nimmt — und das ist per Konstruktion der kaputte Stub in
    `bin_dir`, unabhaengig davon, was weiter hinten im PATH steht.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/bin/sh\n"
        "echo 'Traceback (most recent call last):' >&2\n"
        "echo \"TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'\" >&2\n"
        "exit 1\n"
    )
    stub.chmod(0o755)

    if shutil.which("node") is None:  # pragma: no cover - node ist Testvoraussetzung
        pytest.skip("node nicht im PATH")
    return f"{bin_dir}:{os.environ.get('PATH', '')}"


def make_vault_with_decision(tmp_path, text: str) -> str:
    """Legt eine Vault-DB mit genau einer aktiven Decision an und gibt den Pfad zurueck."""
    from academic_vault.db import VaultDB
    from academic_vault.server import add_decision

    db_path = str(tmp_path / "test_vault.db")
    db = VaultDB(db_path)
    db.init_schema()
    add_decision(db_path, category="Zitierstil", text=text, rationale=None)
    return db_path


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


def test_hook_persists_counter_before_vault_lookup(tmp_path):
    """Regression: ein Hook-Timeout auf dem Trigger-Pfad darf den Zaehler nicht einfrieren.

    `hooks/hooks.json` gibt dem UserPromptSubmit-Hook 15 s; der Vault-Lookup
    wartet dagegen pro Interpreter-Kandidat bis zu 10 s (bis zu vier Kandidaten).
    Haengt der Lookup, killt Claude Code den Hook-Prozess mitten drin.

    Wird der bereits inkrementierte `prompt_count` erst NACH dem Lookup
    persistiert, steht in der State-Datei danach weiterhin TRIGGER_N-1: der
    naechste Prompt trifft wieder den Trigger-Pfad, haengt wieder, wird wieder
    gekillt. Der Zaehler ist damit dauerhaft auf TRIGGER_N-1 eingefroren und der
    teure Lookup laeuft ab da bei JEDER Message statt nur bei jeder N-ten.

    Erwartung: der Zaehler ist vor dem Lookup persistiert, also auch nach einem
    SIGKILL fortgeschritten — der Folge-Aufruf triggert nicht erneut.
    """
    marker = "Zaehler muss vor dem Lookup persistiert sein"
    db_path = make_vault_with_decision(tmp_path, marker)

    state_file = tmp_path / "state.json"
    trigger_n = 2
    # Vorzustand: TRIGGER_N-1 Prompts gezaehlt -> der naechste Aufruf triggert.
    state_file.write_text(json.dumps({"prompt_count": trigger_n - 1}), encoding="utf-8")

    # Interpreter, der beim Vault-Lookup haengt (bildet den langsamen/blockierten
    # Subprozess nach, der den 15-s-Hook-Timeout reisst).
    hanging_python = tmp_path / "hanging-python"
    hanging_python.write_text("#!/bin/sh\nsleep 15\n")
    hanging_python.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    base_env = os.environ.copy()
    base_env.update(
        {
            "HOME": str(home),
            "VIRTUAL_ENV": "",
            "VAULT_DB_PATH": db_path,
            "ACADEMIC_REINFORCEMENT_STATE": str(state_file),
            "ACADEMIC_REINFORCEMENT_N": str(trigger_n),
        }
    )

    killed_env = dict(base_env, ACADEMIC_PYTHON=str(hanging_python))
    proc = subprocess.Popen(
        ["node", str(HOOK_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=killed_env,
    )
    try:
        proc.communicate(input=json.dumps({"hook_event_name": "UserPromptSubmit"}), timeout=5)
        pytest.fail("Hook beendete sich unerwartet — der Lookup sollte blockieren")
    except subprocess.TimeoutExpired:
        # Entspricht dem Hook-Timeout von Claude Code: Prozess wird abgeschossen.
        proc.kill()
        proc.communicate()

    assert state_file.exists(), "State-Datei fehlt nach dem abgeschossenen Trigger-Aufruf"
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted.get("prompt_count") == trigger_n, (
        "prompt_count wurde erst nach dem Vault-Lookup persistiert — ein Hook-Timeout "
        f"friert den Zaehler auf TRIGGER_N-1 ein. State: {persisted!r}"
    )

    # Folgeaufruf mit funktionierendem Interpreter: der Zaehler steht jetzt auf
    # TRIGGER_N+1, es darf also KEIN erneuter Trigger stattfinden.
    follow_up = run_hook(
        {"hook_event_name": "UserPromptSubmit"},
        env_overrides=dict(killed_env, ACADEMIC_PYTHON=sys.executable),
    )
    assert follow_up.returncode == 0, f"Erwartet 0, got {follow_up.returncode}"
    combined = follow_up.stdout + follow_up.stderr
    assert "Aktive Decisions" not in combined, (
        "Nach dem abgeschossenen Trigger-Aufruf triggert der Hook sofort erneut — "
        f"der Zaehler haengt fest: {combined!r}"
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


def test_make_unusable_python3_path_never_exposes_working_python3(tmp_path):
    """Regression fuer AC1: der PATH-Helper darf trotz vererbtem PATH nie ein
    brauchbares `python3` durchsickern lassen.

    Absicherung gegen eine versehentliche Aufweichung (z. B. Stub ans PATH-Ende
    statt an den Anfang) — falls jemand den Fix aus #549 rueckgaengig macht oder
    die Reihenfolge vertauscht, muss genau dieser Test fehlschlagen.
    """
    resolved = shutil.which("python3", path=make_unusable_python3_path(tmp_path))
    assert resolved == str(tmp_path / "fakebin" / "python3"), (
        "Der kaputte Stub muss der ERSTE python3-Treffer im PATH sein, sonst "
        f"koennte ein echtes System-python3 gewinnen. Aufgeloest: {resolved!r}"
    )


def test_hook_injects_real_decisions_when_path_python3_cannot_import_vault(tmp_path):
    """Der injizierte Hinweis muss die ECHTEN Decisions enthalten (AC1, #382).

    Regression-Test fuer die Luecke aus dem PR-#420-Review: dass der Hook auf
    einem Context-Injection-Event haengt, garantiert noch nicht, dass beim Modell
    etwas Brauchbares ankommt. Der Vault-Lookup laeuft als Subprozess ueber
    `python3` aus dem PATH — in einer echten Session ist das das System-Python
    (macOS 3.9), das `academic_vault` nicht importieren kann. Folge: der Hook
    injiziert zwar Text, aber nur die leere Huelle "(keine aktiven Decisions)",
    obwohl der Vault gefuellt ist. Der Reinforcement-Hinweis waere damit
    faktisch weiterhin wirkungslos.

    Erwartung: der Hook faellt auf den kanonischen Setup-Interpreter
    `~/.academic-research/venv/bin/python` zurueck (dasselbe venv, das
    hooks.json im SessionStart-Block prueft) und liefert die Decision aus.
    """
    marker = "APA 7th Edition verwenden"
    db_path = make_vault_with_decision(tmp_path, marker)

    # HOME umbiegen: Node's os.homedir() folgt $HOME, damit bleibt der Test
    # hermetisch und unabhaengig vom echten Setup-venv der Maschine.
    home = tmp_path / "home"
    venv_bin = home / ".academic-research" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(sys.executable)

    result = run_hook(
        {"hook_event_name": "UserPromptSubmit"},
        env_overrides={
            "HOME": str(home),
            "PATH": make_unusable_python3_path(tmp_path),
            # Aktives venv des Testlaufs ausblenden: sonst wuerde der
            # uv-Interpreter den Lookup retten und der Test bewiese nichts
            # ueber den kanonischen Setup-Pfad.
            "VIRTUAL_ENV": "",
            "VAULT_DB_PATH": db_path,
            "ACADEMIC_REINFORCEMENT_STATE": str(tmp_path / "state.json"),
            "ACADEMIC_REINFORCEMENT_N": "1",
        },
    )

    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"
    assert marker in result.stdout, (
        "Der injizierte Kontext enthaelt die aktive Decision nicht — der Hook hat "
        f"nur eine leere Huelle ausgegeben. stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert "(keine aktiven Decisions)" not in result.stdout, (
        f"Leerer Reminder trotz gefuelltem Vault: {result.stdout!r}"
    )


def test_hook_honours_academic_python_override(tmp_path):
    """`ACADEMIC_PYTHON` erzwingt einen bestimmten Interpreter fuer den Vault-Lookup.

    Explizite Escape-Hatch fuer Setups, in denen weder PATH-`python3` noch das
    kanonische Setup-venv passt (z. B. conda, pyenv, Systempakete).
    """
    marker = "Systematisches Review nach PRISMA"
    db_path = make_vault_with_decision(tmp_path, marker)

    # Kein Setup-venv unter HOME -> nur der Override kann greifen.
    home = tmp_path / "home"
    home.mkdir()

    result = run_hook(
        {"hook_event_name": "UserPromptSubmit"},
        env_overrides={
            "HOME": str(home),
            "PATH": make_unusable_python3_path(tmp_path),
            "VIRTUAL_ENV": "",
            "ACADEMIC_PYTHON": sys.executable,
            "VAULT_DB_PATH": db_path,
            "ACADEMIC_REINFORCEMENT_STATE": str(tmp_path / "state.json"),
            "ACADEMIC_REINFORCEMENT_N": "1",
        },
    )

    assert result.returncode == 0, f"Erwartet 0, got {result.returncode}. stderr: {result.stderr}"
    assert marker in result.stdout, (
        f"ACADEMIC_PYTHON-Override wurde ignoriert: stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}"
    )


def test_hook_failopen_when_no_python_interpreter_works(tmp_path):
    """Faellt jeder Kandidat aus, bleibt der Hook fail-open (exit 0, kein Crash)."""
    db_path = make_vault_with_decision(tmp_path, "Wird nicht geladen")

    home = tmp_path / "home"
    home.mkdir()

    result = run_hook(
        {"hook_event_name": "UserPromptSubmit"},
        env_overrides={
            "HOME": str(home),
            "PATH": make_unusable_python3_path(tmp_path),
            "VIRTUAL_ENV": "",
            "ACADEMIC_PYTHON": str(tmp_path / "gibt-es-nicht" / "python"),
            "VAULT_DB_PATH": db_path,
            "ACADEMIC_REINFORCEMENT_STATE": str(tmp_path / "state.json"),
            "ACADEMIC_REINFORCEMENT_N": "1",
        },
    )

    assert result.returncode == 0, (
        f"Erwartet 0 (fail-open), got {result.returncode}. stderr: {result.stderr}"
    )
    assert "(keine aktiven Decisions)" in result.stdout, (
        f"Fail-open-Reminder fehlt: stdout={result.stdout!r}"
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
