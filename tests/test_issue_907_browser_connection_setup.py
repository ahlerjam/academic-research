"""Regressionstests fuer Issue #907 — Chrome-Verbindungsweg fuer browser-use
einrichten und vermerken.

Akzeptanzkriterien (Issue #907):
- AC1: Nach dem Setup steht fest und ist vermerkt, ueber welchen Weg der
  Browser erreicht wird.
- AC5: Der Cloud-Browser bleibt optional (nie automatischer Default).

Die installierte `browser-use`-CLI wird nie echt aufgerufen — alle Tests
injizieren einen Fake-Runner statt subprocess.
"""

from __future__ import annotations

import json

import browser_connection_setup as bcs

# ---------------------------------------------------------------------------
# parse_doctor(): Text -> dict[str, bool]
# ---------------------------------------------------------------------------

DOCTOR_READY = """browser-harness doctor
  platform          Darwin 25.6.0
  python            3.12.13
  version           0.1.8 (pypi)
  latest release    0.1.8
  [ok  ] chrome running
  [ok  ] daemon alive
  [ok  ] active browser connections — 1
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""

DOCTOR_BLOCKED = """browser-harness doctor
  platform          Darwin 25.6.0
  python            3.12.13
  version           0.1.8 (pypi)
  latest release    0.1.8
  [ok  ] chrome running
  [FAIL] daemon alive — see install.md
  [FAIL] active browser connections — 0
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""

DOCTOR_CLOUD_READY = DOCTOR_BLOCKED.replace(
    "[FAIL] Browser Use cloud auth — optional: browser-harness auth login",
    "[ok  ] Browser Use cloud auth",
)


def test_parse_doctor_marks_ok_lines_true():
    checks = bcs.parse_doctor(DOCTOR_READY)
    assert checks["chrome_running"] is True
    assert checks["daemon_alive"] is True
    assert checks["active_browser_connections"] is True


def test_parse_doctor_marks_fail_lines_false():
    checks = bcs.parse_doctor(DOCTOR_BLOCKED)
    assert checks["chrome_running"] is True
    assert checks["daemon_alive"] is False
    assert checks["active_browser_connections"] is False


def test_parse_doctor_empty_text_returns_empty_dict():
    assert bcs.parse_doctor("") == {}


# ---------------------------------------------------------------------------
# connection_ready() / cloud_available()
# ---------------------------------------------------------------------------


def test_connection_ready_true_when_daemon_and_connections_ok():
    assert bcs.connection_ready(bcs.parse_doctor(DOCTOR_READY)) is True


def test_connection_ready_false_when_daemon_down():
    assert bcs.connection_ready(bcs.parse_doctor(DOCTOR_BLOCKED)) is False


def test_cloud_available_false_by_default():
    assert bcs.cloud_available(bcs.parse_doctor(DOCTOR_BLOCKED)) is False


def test_cloud_available_true_when_doctor_reports_ok():
    assert bcs.cloud_available(bcs.parse_doctor(DOCTOR_CLOUD_READY)) is True


# ---------------------------------------------------------------------------
# choose_method(): AC5 — Cloud ist nie automatischer Default
# ---------------------------------------------------------------------------


def test_choose_method_picks_local_when_connection_already_ready():
    checks = bcs.parse_doctor(DOCTOR_READY)
    assert bcs.choose_method(interactive=False, checks=checks) == bcs.METHOD_LOCAL


def test_choose_method_non_interactive_defaults_to_local_even_when_blocked():
    """Nicht-interaktives stdin (z.B. CI/Automatisierung): sicherer Default
    ist der lokale Weg — Cloud wird NIE automatisch gewaehlt, auch wenn
    Cloud-Auth verfuegbar waere (AC5)."""
    checks = bcs.parse_doctor(DOCTOR_CLOUD_READY)
    assert bcs.choose_method(interactive=False, checks=checks) == bcs.METHOD_LOCAL


def test_choose_method_interactive_cloud_requires_explicit_choice(monkeypatch):
    checks = bcs.parse_doctor(DOCTOR_CLOUD_READY)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "2")
    assert bcs.choose_method(interactive=True, checks=checks) == bcs.METHOD_CLOUD


def test_choose_method_interactive_default_answer_is_local(monkeypatch):
    checks = bcs.parse_doctor(DOCTOR_CLOUD_READY)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "")
    assert bcs.choose_method(interactive=True, checks=checks) == bcs.METHOD_LOCAL


# ---------------------------------------------------------------------------
# record_method() / load_state(): AC1 — Weg ist nach dem Setup vermerkt
# ---------------------------------------------------------------------------


def test_record_method_writes_state_file(tmp_path):
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={"chrome_running": True}, path=state_path)

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["method"] == bcs.METHOD_LOCAL
    assert "configured_at" in data


def test_load_state_returns_none_when_missing(tmp_path):
    assert bcs.load_state(tmp_path / "missing.json") is None


def test_load_state_roundtrips_recorded_method(tmp_path):
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_CLOUD, checks={}, path=state_path)

    state = bcs.load_state(state_path)
    assert state is not None
    assert state["method"] == bcs.METHOD_CLOUD


def test_record_method_idempotent_second_run_no_reprompt(tmp_path):
    """Zweiter Setup-Lauf: der bereits vermerkte Weg wird nicht neu erfragt —
    hier geprueft ueber main(), das bei vorhandenem State nicht erneut nach
    stdin greift."""
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={}, path=state_path)

    exit_code = bcs.main(
        ["--setup"],
        state_path=state_path,
        doctor_runner=lambda: DOCTOR_READY,
        interactive=True,
    )
    assert exit_code == 0
    state = bcs.load_state(state_path)
    assert state["method"] == bcs.METHOD_LOCAL


# ---------------------------------------------------------------------------
# main(): CLI-Fassade
# ---------------------------------------------------------------------------


def test_main_check_prints_unset_without_state(tmp_path, capsys):
    exit_code = bcs.main(["--check"], state_path=tmp_path / "missing.json")
    assert exit_code == 1
    assert "unset" in capsys.readouterr().out


def test_main_check_prints_method_when_state_exists(tmp_path, capsys):
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={}, path=state_path)

    exit_code = bcs.main(["--check"], state_path=state_path)
    assert exit_code == 0
    assert bcs.METHOD_LOCAL in capsys.readouterr().out


def test_main_setup_records_state_non_interactively(tmp_path):
    state_path = tmp_path / "browser_connection.json"
    exit_code = bcs.main(
        ["--setup"],
        state_path=state_path,
        doctor_runner=lambda: DOCTOR_BLOCKED,
        interactive=False,
    )
    assert exit_code == 0
    state = bcs.load_state(state_path)
    assert state["method"] == bcs.METHOD_LOCAL
