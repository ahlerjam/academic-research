"""Regression-Tests fuer Issue #631: Auth-Weiche SDK/CLI/Skip in eval_runner.py.

Deckt die Akzeptanzkriterien, die sich ohne echten Modellaufruf pruefen
lassen (gemockter Subprozess): AC2 (SDK-Pfad bleibt bei gesetztem Key
unveraendert, CLI wird NICHT gestartet), AC4 (Modellkennung sichtbar), AC5
(Auth-/Rate-Limit-Fehler der CLI ist von einer regulaeren Antwort
unterscheidbar), AC7 (ohne Key und ohne CLI: unveraendertes Skip-Verhalten).
Der reale Probelauf ohne ANTHROPIC_API_KEY (AC1) ist kein Unit-Test -- er
braucht eine echte, eingeloggte claude-CLI-Session und wird separat als
Evidenz im PR dokumentiert.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.evals import eval_runner


class _CaptureClient:
    """Anthropic-Client-Stub wie in test_issue_231_temperature.py."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - Stub
        self.captured: dict | None = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.captured = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(text="ok")],
            usage=SimpleNamespace(input_tokens=7, output_tokens=3),
        )


@pytest.fixture
def fake_anthropic(monkeypatch):
    holder: dict[str, _CaptureClient] = {}

    def _client_factory(*args, **kwargs):
        client = _CaptureClient(*args, **kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(eval_runner, "anthropic", SimpleNamespace(Anthropic=_client_factory))
    return holder


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
# AC2: SDK-Pfad bei gesetztem ANTHROPIC_API_KEY bleibt unveraendert -- CLI
# wird nicht gestartet.
# ---------------------------------------------------------------------------


def test_call_claude_uses_sdk_when_api_key_set_and_does_not_spawn_cli(fake_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "subprocess.run wurde aufgerufen, obwohl ANTHROPIC_API_KEY gesetzt ist"
        )

    monkeypatch.setattr(eval_runner.subprocess, "run", _fail_if_called)

    output = eval_runner.call_claude("sys", "user")
    assert output == "ok"
    assert fake_anthropic["client"].captured is not None


def test_call_claude_with_tokens_uses_sdk_when_api_key_set(fake_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        eval_runner.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("CLI haette nicht laufen duerfen")),
    )
    text, tokens_in, tokens_out = eval_runner.call_claude_with_tokens("sys", "user")
    assert (text, tokens_in, tokens_out) == ("ok", 7, 3)


# ---------------------------------------------------------------------------
# AC1 / AC4: CLI-Pfad ohne Key, wenn die CLI verfuegbar ist -- Modellkennung
# geht ins Kommando ein und wird geloggt.
# ---------------------------------------------------------------------------


def test_call_claude_uses_cli_when_no_api_key_and_cli_available(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    monkeypatch.setattr(eval_runner.subprocess, "run", _fake_subprocess_run_ok("claude-sonnet-4-6"))

    output = eval_runner.call_claude("sys", "user", model="claude-sonnet-4-6")
    assert output == "PONG"
    captured = capsys.readouterr()
    assert "model=claude-sonnet-4-6" in captured.err
    assert "mode=cli" in captured.err


def test_call_claude_with_tokens_uses_cli_and_reads_usage(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    monkeypatch.setattr(eval_runner.subprocess, "run", _run)

    with pytest.raises(eval_runner.ClaudeCliError) as excinfo:
        eval_runner.call_claude("sys", "user")
    assert excinfo.value.exit_code == 1


# ---------------------------------------------------------------------------
# AC7: Weder Key noch CLI verfuegbar -- unveraendertes Skip-Verhalten.
# ---------------------------------------------------------------------------


def test_call_claude_skips_when_no_key_and_no_cli(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: False)
    with pytest.raises(pytest.skip.Exception):
        eval_runner.call_claude("sys", "user")


def test_call_claude_with_tokens_skips_when_no_key_and_no_cli(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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
