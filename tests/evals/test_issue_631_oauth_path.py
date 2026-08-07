"""Regression-Tests fuer Issue #631: CLI/Skip-Pfad in eval_runner.py.

Der frueher parallele SDK-Pfad (``ANTHROPIC_API_KEY``) ist mit Issue #716
entfallen -- ``call_claude``/``call_claude_with_tokens`` kennen seither nur
noch zwei Zustaende: claude-CLI verfuegbar (Subprozess ueber die
OAuth-Session) oder ``pytest.skip()``. Deckt weiterhin: AC4 (Modellkennung
sichtbar), AC5 (Auth-/Rate-Limit-Fehler der CLI ist von einer regulaeren
Antwort unterscheidbar), AC7 (ohne CLI: Skip-Verhalten). Der reale Probelauf
mit einer eingeloggten claude-CLI-Session (AC1/AC4 aus #631, jetzt AC4 aus
#716) ist kein Unit-Test -- er wird separat als Evidenz im PR dokumentiert.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.evals import eval_runner


def _fake_subprocess_run_ok(model: str):
    """Baut einen subprocess.run-Stub, der eine erfolgreiche CLI-Antwort liefert."""

    def _run(cmd, **kwargs):
        assert cmd[0] == "claude"
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == model
        # Kein --temperature-Flag im Kommando -- die CLI kennt es nicht (AC6).
        assert "--temperature" not in cmd
        payload = {
            "is_error": False,
            "result": "PONG",
            "usage": {"input_tokens": 11, "output_tokens": 2},
            "modelUsage": {model: {"inputTokens": 11, "outputTokens": 2}},
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    return _run


def _fake_subprocess_run_error(*, api_error_status: int = 429):
    def _run(cmd, **kwargs):
        payload = {
            "is_error": True,
            "result": "Rate limit exceeded",
            "api_error_status": api_error_status,
        }
        return SimpleNamespace(returncode=1, stdout=json.dumps(payload), stderr="")

    return _run


# ---------------------------------------------------------------------------
# AC1 / AC4: CLI-Pfad, wenn die CLI verfuegbar ist -- Modellkennung geht ins
# Kommando ein und wird geloggt.
# ---------------------------------------------------------------------------


def test_call_claude_uses_cli_when_available(monkeypatch, capsys):
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    monkeypatch.setattr(eval_runner.subprocess, "run", _fake_subprocess_run_ok("claude-sonnet-4-6"))

    output = eval_runner.call_claude("sys", "user", model="claude-sonnet-4-6")
    assert output == "PONG"
    captured = capsys.readouterr()
    assert "model=claude-sonnet-4-6" in captured.err
    assert "mode=cli" in captured.err


def test_call_claude_with_tokens_uses_cli_and_reads_usage(monkeypatch):
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    monkeypatch.setattr(
        eval_runner.subprocess, "run", _fake_subprocess_run_ok("claude-haiku-4-5-20251001")
    )

    text, tokens_in, tokens_out = eval_runner.call_claude_with_tokens(
        "sys", "user", model="claude-haiku-4-5-20251001"
    )
    assert text == "PONG"
    assert (tokens_in, tokens_out) == (11, 2)


# ---------------------------------------------------------------------------
# AC5: Auth-/Rate-Limit-Fehler der CLI ist von einer regulaeren (moeglicherweise
# falschen) Antwort unterscheidbar -- eigene Exception statt Fehlklassifikation.
# ---------------------------------------------------------------------------


def test_call_claude_raises_claude_cli_error_on_is_error_response(monkeypatch):
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    monkeypatch.setattr(
        eval_runner.subprocess, "run", _fake_subprocess_run_error(api_error_status=429)
    )

    with pytest.raises(eval_runner.ClaudeCliError) as excinfo:
        eval_runner.call_claude("sys", "user")
    assert excinfo.value.api_error_status == 429
    assert excinfo.value.exit_code == 1


def test_call_claude_does_not_raise_on_normal_wrong_answer(monkeypatch):
    """Gegenprobe: eine inhaltlich falsche, aber technisch saubere Antwort
    (is_error: false) loest KEINE ClaudeCliError aus -- sie bleibt eine
    regulaere (falsche) Modellantwort, die in Recall/FPR eingeht."""
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    monkeypatch.setattr(eval_runner.subprocess, "run", _fake_subprocess_run_ok("claude-sonnet-4-6"))

    output = eval_runner.call_claude("sys", "user", model="claude-sonnet-4-6")
    assert output == "PONG"  # kein Raise, auch wenn "PONG" != erwarteter Wert waere


def test_claude_cli_error_from_nonzero_exit_without_is_error_flag(monkeypatch):
    """Nicht-null Exit-Code allein (ohne is_error im JSON) muss ebenfalls
    ClaudeCliError sein -- Rueckgabewert ist nicht vertrauenswuerdig."""

    def _run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1, stdout=json.dumps({"result": "irgendwas"}), stderr="boom"
        )

    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    monkeypatch.setattr(eval_runner.subprocess, "run", _run)

    with pytest.raises(eval_runner.ClaudeCliError) as excinfo:
        eval_runner.call_claude("sys", "user")
    assert excinfo.value.exit_code == 1


# ---------------------------------------------------------------------------
# AC7: CLI nicht verfuegbar -- unveraendertes Skip-Verhalten.
# ---------------------------------------------------------------------------


def test_call_claude_skips_when_no_cli(monkeypatch):
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: False)
    with pytest.raises(pytest.skip.Exception):
        eval_runner.call_claude("sys", "user")


def test_call_claude_with_tokens_skips_when_no_cli(monkeypatch):
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: False)
    with pytest.raises(pytest.skip.Exception):
        eval_runner.call_claude_with_tokens("sys", "user")


def test_claude_cli_available_reflects_shutil_which(monkeypatch):
    monkeypatch.setattr(eval_runner.shutil, "which", lambda name: None)
    assert eval_runner.claude_cli_available() is False
    monkeypatch.setattr(eval_runner.shutil, "which", lambda name: "/usr/local/bin/claude")
    assert eval_runner.claude_cli_available() is True


# ---------------------------------------------------------------------------
# AC6: Determinismus-Luecke ist dokumentiert (keine --temperature-Option im
# CLI-Kommando -- s. Docstring von _run_claude_cli und STRATEGY.md).
# ---------------------------------------------------------------------------


def test_cli_helper_documents_missing_temperature_control():
    assert "temperature" in (eval_runner._run_claude_cli.__doc__ or "").lower()
