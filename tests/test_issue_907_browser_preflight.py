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


def test_preflight_fails_when_daemon_alive_but_no_active_connections(tmp_path, capsys):
    """P1-Regression (PR #923 Review): genau der Zustand, der Issue #907
    ausgeloest hat — Doctor meldet '[ok] chrome running'/'daemon alive' bei
    gleichzeitig '[FAIL] active browser connections — 0'. Der urspruengliche
    Test an dieser Stelle fror das faelschlich als OK ein (Henne-Ei-Annahme);
    tatsaechlich ist das exakt der Zustand, in dem der Modul-Loop mitten im
    Lauf mit 'permission-blocked' abstirbt. Preflight muss ihn blockieren."""
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={}, path=state_path)

    exit_code = browser_preflight.main(
        [],
        state_path=state_path,
        doctor_runner=lambda: DOCTOR_DAEMON_OK_NO_CONNECTIONS,
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "allow" in out.lower()


DOCTOR_DAEMON_OK_CONNECTIONS_LINE_MISSING = """
  [ok  ] chrome running
  [ok  ] daemon alive
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""


def test_preflight_ok_when_active_connections_line_missing_from_doctor(tmp_path, capsys):
    """Fehlt die active-connections-Zeile im Doctor-Output komplett (kein
    Key im Snapshot, z.B. andere CLI-Version), bleibt der lenient Fallback
    auf daemon_alive bestehen — anders als beim expliziten '[FAIL]' oben."""
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_LOCAL, checks={}, path=state_path)

    exit_code = browser_preflight.main(
        [],
        state_path=state_path,
        doctor_runner=lambda: DOCTOR_DAEMON_OK_CONNECTIONS_LINE_MISSING,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower()
