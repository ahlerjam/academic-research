"""Kontext-Injection des Reinforcement-Hooks — Verdrahtung offline, Wirkung live (#382, AC1).

Zwei Ebenen:

1. Offline (laeuft immer): die aus `hooks/hooks.json` abgeleitete settings.json
   enthaelt genau die Events, deren stdout laut Claude-Code-Doku als Modell-Kontext
   wirkt (UserPromptSubmit, SessionStart) — und keine, bei denen stdout nur im
   Debug-Log landet (Notification, das nicht existierende PostCompact).

2. Live (per `ACADEMIC_LIVE_CONTEXT_TEST=1` gegated, analog zu VAULT_E5_LIVE_TEST):
   Nonce-Round-Trip gegen eine echte headless-Session. Das ist der direkte Nachweis
   fuer den zweiten Teil von AC1 ("im tatsaechlichen Modell-Kontext nachweisbar"),
   den Unit-Tests prinzipiell nicht erbringen koennen: sie zeigen nur, dass der Hook
   Text auf stdout schreibt, nicht dass Claude Code ihn dem Modell zufuehrt.
   Der Lauf kostet einen kurzen Haiku-Aufruf und braucht Netz + Anmeldung, deshalb
   nicht in der Default-Suite.
"""

import os
import shutil
from pathlib import Path

import pytest

# Repo-Root liegt via tests/conftest.py auf sys.path; `scripts` ist ein Package.
from scripts.dev.verify_reinforcement_context import (
    REINFORCEMENT_HOOK,
    LiveCheckError,
    build_settings,
    run_live_check,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Events, deren stdout laut code.claude.com/docs/en/hooks als Modell-Kontext
# injiziert wird ("The exceptions are UserPromptSubmit, UserPromptExpansion and
# SessionStart, where stdout is added as context that Claude can see and act on").
CONTEXT_INJECTING_EVENTS = {"UserPromptSubmit", "UserPromptExpansion", "SessionStart"}

LIVE_GATE = os.environ.get("ACADEMIC_LIVE_CONTEXT_TEST") == "1"


# ---------------------------------------------------------------------------
# Offline: Verdrahtung
# ---------------------------------------------------------------------------


def test_settings_are_derived_from_deployed_hooks_json():
    """Der Live-Check baut seine settings.json aus der echten hooks.json.

    Guard gegen eine Attrappe: wuerde der Check eine handgeschriebene Konfiguration
    verwenden, bewiese ein gruener Lauf nichts ueber das ausgelieferte Plugin.
    """
    settings = build_settings(REPO_ROOT)
    commands = [
        hook["command"]
        for blocks in settings["hooks"].values()
        for block in blocks
        for hook in block["hooks"]
    ]
    assert commands, "Keine Reinforcement-Hooks aus hooks.json uebernommen"
    for command in commands:
        assert REINFORCEMENT_HOOK in command
        assert "${CLAUDE_PLUGIN_ROOT}" not in command, f"Platzhalter nicht aufgeloest: {command!r}"
        assert str(REPO_ROOT) in command


def test_reinforcement_runs_only_on_context_injecting_events():
    """Jedes verdrahtete Event muss stdout tatsaechlich als Kontext injizieren.

    Regression-Guard fuer den Kern von #382: auf Notification/PostCompact lief der
    Hinweis ins Leere, weil deren stdout nur ins Debug-Log geht (PostCompact
    existiert als Event ueberhaupt nicht).
    """
    settings = build_settings(REPO_ROOT)
    events = set(settings["hooks"])
    assert events, "Reinforcement-Hook ist an kein Event gebunden"
    assert events <= CONTEXT_INJECTING_EVENTS, (
        f"Events ohne Context-Injection verdrahtet: {sorted(events - CONTEXT_INJECTING_EVENTS)}"
    )


def test_sessionstart_entry_uses_compact_matcher():
    """Der SessionStart-Pfad greift nur nach Compaction, nicht bei jedem Sessionstart."""
    settings = build_settings(REPO_ROOT)
    session_start = settings["hooks"].get("SessionStart")
    assert session_start, "Kein SessionStart-Eintrag fuer den Reinforcement-Hook"
    matchers = {block.get("matcher") for block in session_start}
    assert matchers == {"compact"}, f"Unerwartete SessionStart-Matcher: {matchers}"


# ---------------------------------------------------------------------------
# Live: Wirkung
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not LIVE_GATE,
    reason="Live-Kontext-Check nur mit ACADEMIC_LIVE_CONTEXT_TEST=1 (kostet einen API-Aufruf)",
)
@pytest.mark.skipif(shutil.which("claude") is None, reason="`claude` nicht im PATH")
def test_reminder_reaches_real_model_context():
    """Nonce-Round-Trip: der Marker aus dem Vault taucht in der Modellantwort auf.

    Der Marker wird frisch gewuerfelt und existiert ausschliesslich in der
    temporaeren Vault-DB. Nennt das Modell ihn, kann er nur ueber die
    Hook-Injection in seinen Kontext gelangt sein.
    """
    try:
        result = run_live_check()
    except LiveCheckError as exc:
        pytest.skip(f"Live-Check nicht durchfuehrbar: {exc}")

    assert result["model_saw_nonce"], (
        f"Marker {result['nonce']} fehlt in der Modellantwort {result['answer']!r} — "
        "der Reinforcement-Hinweis erreicht den Modell-Kontext nicht."
    )
    assert result["transcript_confirms"], (
        f"Transcript {result['transcript']} verbucht keine Hook-Injection mit {result['nonce']}."
    )
