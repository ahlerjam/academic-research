"""Regressionstests fuer Issue #907 — Preflight-Pruefung der Browser-
Verbindung vor dem ersten Browser-Modul eines Laufs.

Akzeptanzkriterien (Issue #907):
- AC2: Ein Lauf mit Browser-Modulen prueft die Verbindung, bevor das erste
  Modul startet, und sagt beim Fehlen, was zu tun ist (nicht nur
  `permission-blocked`).
"""

from __future__ import annotations

import browser_connection_setup as bcs
import browser_preflight

DOCTOR_READY = """
  [ok  ] chrome running
  [ok  ] daemon alive
  [ok  ] active browser connections — 1
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""

DOCTOR_BLOCKED = """
  [ok  ] chrome running
  [FAIL] daemon alive — see install.md
  [FAIL] active browser connections — 0
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""

DOCTOR_CLOUD_OK = """
  [ok  ] chrome running
  [FAIL] daemon alive — see install.md
  [FAIL] active browser connections — 0
  [ok  ] Browser Use cloud auth
"""

DOCTOR_DAEMON_OK_NO_CONNECTIONS = """
  [ok  ] chrome running
  [ok  ] daemon alive
  [FAIL] active browser connections — 0
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""


def test_preflight_fails_when_never_configured(tmp_path, capsys):
    exit_code = browser_preflight.main(
        [], state_path=tmp_path / "missing.json", doctor_runner=lambda: DOCTOR_READY
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "setup" in out.lower()


def test_preflight_ok_when_local_connection_ready(tmp_path, capsys):
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={}, path=state_path)

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_READY
    )
    assert exit_code == 0


def test_preflight_fails_with_actionable_message_when_local_blocked(tmp_path, capsys):
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={}, path=state_path)

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_BLOCKED
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    # Handlungsanweisung, nicht die blosse Fehlerkonstante:
    assert "permission-blocked" not in out
    assert "allow" in out.lower()
    assert "cloud" in out.lower()


def test_preflight_ok_when_cloud_method_and_cloud_authenticated(tmp_path):
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_CLOUD, checks={}, path=state_path)

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_CLOUD_OK
    )
    assert exit_code == 0


def test_preflight_fails_when_cloud_method_but_not_authenticated(tmp_path, capsys):
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_CLOUD, checks={}, path=state_path)

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_BLOCKED
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "auth login" in out


def test_preflight_ok_when_daemon_alive_no_active_connections_yet(tmp_path, capsys):
    """Issue #907 P1: Henne-Ei-Szenario nach Setup — Daemon laeuft, aber
    noch keine aktiven Verbindungen, weil der Nutzer den Chrome-Dialog
    noch nicht bestaetigt hat. Preflight sollte OK sein und den Browser-
    Teil nicht blockieren."""
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={}, path=state_path)

    exit_code = browser_preflight.main(
        [],
        state_path=state_path,
        doctor_runner=lambda: DOCTOR_DAEMON_OK_NO_CONNECTIONS,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower()
