"""Guard fuer die Eval-Sitzungsprofile (Issue #830).

Drei Dinge werden geprueft, ohne dass ein einziger echter ``claude``-Aufruf
noetig ist:

1. ``_run_claude_cli`` verdrahtet ``cwd``/``allowed_tools``/``mcp_config``/
   ``env`` nicht mehr fest, sondern nimmt sie entgegen und reicht sie an
   ``subprocess.run`` bzw. das CLI-Kommando durch (AC2).
2. Eine Fixture, die eine Suite in ihrem eigenen Arbeitsverzeichnis ablegt,
   ist fuer eine andere Suite mit anderem ``cwd`` nicht sichtbar (AC3).
3. Jede ``evals/``-Komponente hat genau ein Profil aus
   ``eval_runner.SESSION_PROFILES``, keine fehlt und keine ist doppelt
   benannt (AC1, Teil "jede Suite genau einem Profil zugeordnet").
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests.evals.eval_runner import (
    COMPONENT_PROFILES,
    EVALS_ROOT,
    SESSION_PROFILES,
    ClaudeCliError,
    _run_claude_cli,
    call_claude_for_component,
    profile_for,
)


def _eval_dirs() -> set[str]:
    return {
        p.name for p in EVALS_ROOT.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
    }


class _FakeCompletedProcess:
    def __init__(self, cwd: str | None) -> None:
        self.returncode = 0
        self.stdout = '{"result": "ok", "is_error": false}'
        self.stderr = ""
        self.cwd = cwd


# ---------------------------------------------------------------------------
# AC2: _run_claude_cli nimmt die vier Achsen entgegen und reicht sie durch.
# ---------------------------------------------------------------------------


def test_run_claude_cli_forwards_cwd_to_subprocess(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured.update(kwargs)
        return _FakeCompletedProcess(cwd=kwargs.get("cwd"))

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x", cwd=tmp_path)

    assert captured["cwd"] == str(tmp_path), (
        "_run_claude_cli muss das uebergebene cwd an subprocess.run durchreichen (Issue #830, AC2)."
    )


def test_run_claude_cli_default_cwd_is_none_unchanged_behaviour() -> None:
    """Ohne cwd-Angabe bleibt das bisherige Verhalten: subprocess.run(cwd=None)."""
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured.update(kwargs)
        return _FakeCompletedProcess(cwd=kwargs.get("cwd"))

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x")

    assert captured["cwd"] is None


def test_run_claude_cli_forwards_allowed_tools_into_command() -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(cwd=None)

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x", allowed_tools="Read")

    command = captured["command"]
    idx = command.index("--allowedTools")
    assert command[idx + 1] == "Read", (
        "_run_claude_cli muss ein uebergebenes allowed_tools statt der bisherigen "
        "Konstante '' in --allowedTools verwenden (Issue #830, AC2)."
    )


def test_run_claude_cli_default_allowed_tools_is_empty_unchanged_behaviour() -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(cwd=None)

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x")

    command = captured["command"]
    idx = command.index("--allowedTools")
    assert command[idx + 1] == "", "Ohne allowed_tools muss weiterhin --allowedTools '' stehen."


def test_run_claude_cli_forwards_mcp_config_flags() -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(cwd=None)

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x", mcp_config="/tmp/mcp.json")

    command = captured["command"]
    assert "--mcp-config" in command
    assert command[command.index("--mcp-config") + 1] == "/tmp/mcp.json"
    assert "--strict-mcp-config" in command


def test_run_claude_cli_omits_mcp_config_flags_by_default() -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured["command"] = command
        return _FakeCompletedProcess(cwd=None)

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x")

    assert "--mcp-config" not in captured["command"]
    assert "--strict-mcp-config" not in captured["command"]


def test_run_claude_cli_forwards_env() -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured.update(kwargs)
        return _FakeCompletedProcess(cwd=None)

    custom_env = {"VAULT_DB_PATH": "/tmp/vault.db"}
    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x", env=custom_env)

    assert captured["env"] == custom_env


def test_run_claude_cli_default_env_is_none_unchanged_behaviour() -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured.update(kwargs)
        return _FakeCompletedProcess(cwd=None)

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x")

    assert captured["env"] is None


def test_run_claude_cli_raises_on_timeout_regardless_of_new_axes(tmp_path: Path) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=command, timeout=1)

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(ClaudeCliError):
            _run_claude_cli("sys", "user", "model-x", cwd=tmp_path, allowed_tools="Read")


# ---------------------------------------------------------------------------
# AC3: Fixture in einem Arbeitsverzeichnis ist fuer eine andere Suite mit
# anderem cwd nicht sichtbar.
# ---------------------------------------------------------------------------


def test_fixture_in_one_suite_cwd_is_invisible_to_another(tmp_path: Path) -> None:
    suite_a_dir = tmp_path / "suite-a"
    suite_b_dir = tmp_path / "suite-b"
    suite_a_dir.mkdir()
    suite_b_dir.mkdir()
    (suite_a_dir / "academic_context.md").write_text("Suite-A-Fixture")

    captured_cwds: list[str | None] = []

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        cwd = kwargs.get("cwd")
        captured_cwds.append(cwd)
        # Simuliert, was eine ls-artige Anfrage im jeweiligen cwd saehe.
        visible = [p.name for p in Path(cwd).iterdir()] if cwd else []
        assert "academic_context.md" not in visible or cwd == str(suite_a_dir)
        return _FakeCompletedProcess(cwd=cwd)

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x", cwd=suite_a_dir)
        _run_claude_cli("sys", "user", "model-x", cwd=suite_b_dir)

    # Suite B's Arbeitsverzeichnis enthaelt die Fixture aus Suite A nicht.
    assert not (suite_b_dir / "academic_context.md").exists()
    assert captured_cwds == [str(suite_a_dir), str(suite_b_dir)]


def test_bare_profile_without_cwd_sees_repo_root_not_a_fixture_dir(tmp_path: Path) -> None:
    """Regressionsschutz fuer den im Issue beschriebenen Root-Leak.

    Vor Issue #830 setzte _run_claude_cli kein cwd -- jede Fixture, die eine
    Suite im Repo-Root ablegte, war fuer alle anderen Suiten sichtbar. Mit
    explizitem cwd=None (bare-Profil-Default) bleibt das Aufrufer-cwd
    massgeblich, nicht ein fest verdrahtetes Fixture-Verzeichnis.
    """
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured.update(kwargs)
        return _FakeCompletedProcess(cwd=kwargs.get("cwd"))

    with patch("subprocess.run", side_effect=fake_run):
        _run_claude_cli("sys", "user", "model-x", cwd=None)

    assert captured["cwd"] is None


# ---------------------------------------------------------------------------
# AC1: jede evals/-Komponente hat genau ein Profil, keine fehlt/doppelt.
# ---------------------------------------------------------------------------


def test_every_eval_component_has_exactly_one_session_profile() -> None:
    on_disk = _eval_dirs()
    documented = set(COMPONENT_PROFILES)
    missing = on_disk - documented
    stale = documented - on_disk
    assert not missing, (
        f"Komponenten ohne Sitzungsprofil: {sorted(missing)} (Issue #830, AC1) -- "
        "COMPONENT_PROFILES in eval_runner.py ergaenzen."
    )
    assert not stale, (
        f"COMPONENT_PROFILES nennt Komponenten, die es unter evals/ nicht (mehr) gibt: "
        f"{sorted(stale)}."
    )


@pytest.mark.parametrize("component", sorted(COMPONENT_PROFILES))
def test_component_profile_is_a_known_profile_name(component: str) -> None:
    profile = profile_for(component)
    assert profile in SESSION_PROFILES, (
        f"{component}: Profil {profile!r} ist nicht in SESSION_PROFILES definiert."
    )


def test_profile_for_unknown_component_raises_instead_of_defaulting_silently() -> None:
    """Kein stiller Fallback auf 'bare' fuer eine unbekannte Komponente (AC1)."""
    with pytest.raises(KeyError):
        profile_for("does-not-exist-as-a-component")


def test_session_profiles_cover_the_four_named_profiles() -> None:
    """Die Achsen-Tabelle kennt genau die im Plan benannten vier Profile."""
    assert set(SESSION_PROFILES) == {"bare", "context-fs", "vault", "net-excluded"}


def test_context_fs_and_vault_profiles_need_a_cwd() -> None:
    assert SESSION_PROFILES["context-fs"]["needs_cwd"] is True
    assert SESSION_PROFILES["vault"]["needs_cwd"] is True
    assert SESSION_PROFILES["bare"]["needs_cwd"] is False


def test_only_vault_profile_needs_mcp() -> None:
    assert SESSION_PROFILES["vault"]["needs_mcp"] is True
    for name in ("bare", "context-fs", "net-excluded"):
        assert SESSION_PROFILES[name]["needs_mcp"] is False


# ---------------------------------------------------------------------------
# Callsite-Anbindung: profile_for()/SESSION_PROFILES muessen einen
# tatsaechlichen call_claude-Aufruf steuern, nicht nur als Tabelle
# herumliegen (Issue #830, Task 5).
# ---------------------------------------------------------------------------


def test_call_claude_for_component_passes_profile_allowed_tools_through() -> None:
    """call_claude_for_component('chapter-writer', ...) muss das vault-Profil ziehen.

    chapter-writer ist in COMPONENT_PROFILES als 'vault' hinterlegt --
    allowed_tools muss also SESSION_PROFILES['vault']['allowed_tools'] sein,
    nicht der bisherige feste Leerstring.
    """
    captured: dict[str, Any] = {}

    def fake_call_claude(
        system: str, user: str, model: str = "claude-sonnet-4-6", **kwargs: Any
    ) -> str:
        captured.update(kwargs)
        return "ok"

    with patch("tests.evals.eval_runner.call_claude", side_effect=fake_call_claude):
        result = call_claude_for_component("chapter-writer", "sys", "user")

    assert result == "ok"
    assert captured["allowed_tools"] == SESSION_PROFILES["vault"]["allowed_tools"]


def test_call_claude_for_component_bare_profile_keeps_no_tools() -> None:
    """'fetch' ist als 'bare' hinterlegt -- allowed_tools bleibt '' (--allowedTools '')."""
    captured: dict[str, Any] = {}

    def fake_call_claude(
        system: str, user: str, model: str = "claude-sonnet-4-6", **kwargs: Any
    ) -> str:
        captured.update(kwargs)
        return "ok"

    with patch("tests.evals.eval_runner.call_claude", side_effect=fake_call_claude):
        call_claude_for_component("fetch", "sys", "user")

    assert captured["allowed_tools"] == SESSION_PROFILES["bare"]["allowed_tools"] == ""


def test_call_claude_for_component_forwards_cwd_and_mcp_config_overrides(tmp_path: Path) -> None:
    """Optionale cwd/mcp_config-Overrides (kuenftige Fixtures aus #823/#824) werden durchgereicht."""
    captured: dict[str, Any] = {}

    def fake_call_claude(
        system: str, user: str, model: str = "claude-sonnet-4-6", **kwargs: Any
    ) -> str:
        captured.update(kwargs)
        return "ok"

    with patch("tests.evals.eval_runner.call_claude", side_effect=fake_call_claude):
        call_claude_for_component(
            "academic-context", "sys", "user", cwd=tmp_path, mcp_config="/tmp/mcp.json"
        )

    assert captured["cwd"] == tmp_path
    assert captured["mcp_config"] == "/tmp/mcp.json"


def test_call_claude_for_component_unknown_component_raises() -> None:
    """Kein stiller Fallback -- profile_for() feuert unveraendert (AC1)."""
    with pytest.raises(KeyError):
        call_claude_for_component("does-not-exist-as-a-component", "sys", "user")
