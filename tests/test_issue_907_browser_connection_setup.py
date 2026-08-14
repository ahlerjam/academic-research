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
# preflight_ready(): P1-Regression PR #923 Review — der Zustand, der #907
# ausgeloest hat (Daemon laeuft, aber active_browser_connections explizit
# False), darf nicht mehr als bereit gelten.
# ---------------------------------------------------------------------------

DOCTOR_DAEMON_OK_NO_ACTIVE_CONNECTIONS = """
  [ok  ] chrome running
  [ok  ] daemon alive
  [FAIL] active browser connections — 0
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""

DOCTOR_DAEMON_OK_CONNECTIONS_LINE_MISSING = """
  [ok  ] chrome running
  [ok  ] daemon alive
  [FAIL] Browser Use cloud auth — optional: browser-harness auth login
"""


def test_preflight_ready_false_when_active_connections_explicitly_false():
    """Genau der Zustand aus Issue #907: '[ok] chrome running'/'daemon alive'
    bei gleichzeitig '[FAIL] active browser connections — 0'. Der Key ist
    im Doctor-Snapshot vorhanden (nicht fehlend) und explizit False -> nicht
    bereit."""
    checks = bcs.parse_doctor(DOCTOR_DAEMON_OK_NO_ACTIVE_CONNECTIONS)
    assert checks["active_browser_connections"] is False
    assert bcs.preflight_ready(checks) is False


def test_preflight_ready_falls_back_to_daemon_alive_when_key_missing():
    """Fehlt die active-connections-Zeile im Doctor-Output komplett (kein
    Key im Snapshot), bleibt der lenient Fallback auf daemon_alive bestehen
    (P1-Empfehlung PR #923: 'nur bei fehlendem Key auf daemon_alive
    zurueckfallen')."""
    checks = bcs.parse_doctor(DOCTOR_DAEMON_OK_CONNECTIONS_LINE_MISSING)
    assert "active_browser_connections" not in checks
    assert bcs.preflight_ready(checks) is True


def test_preflight_ready_true_when_daemon_and_connections_ok():
    assert bcs.preflight_ready(bcs.parse_doctor(DOCTOR_READY)) is True


def test_preflight_ready_false_when_daemon_down():
    assert bcs.preflight_ready(bcs.parse_doctor(DOCTOR_BLOCKED)) is False


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
# choose_method(): P1-Regression PR #923 Review — '--setup --force' konnte
# den Weg nicht aendern, weil die connection_ready-Abkuerzung den Prompt bei
# bereits verbundenem lokalem Chrome immer uebersprang, auch interaktiv.
# ---------------------------------------------------------------------------

DOCTOR_LOCAL_AND_CLOUD_READY = DOCTOR_READY.replace(
    "[FAIL] Browser Use cloud auth — optional: browser-harness auth login",
    "[ok  ] Browser Use cloud auth",
)


def test_choose_method_interactive_prompts_even_when_local_already_connected(monkeypatch):
    """Vorher: connection_ready(checks) == True liess choose_method() sofort
    METHOD_LOCAL zurueckgeben, OHNE jemals zu fragen — auch interaktiv, auch
    mit --force. Damit konnte ein Nutzer den Weg nie mehr aendern, sobald
    Chrome zufaellig gerade verbunden war."""
    checks = bcs.parse_doctor(DOCTOR_READY)  # connection_ready(checks) is True
    asked = {"value": False}

    def fake_input(*_a: object, **_k: object) -> str:
        asked["value"] = True
        return "1"

    monkeypatch.setattr("builtins.input", fake_input)
    bcs.choose_method(interactive=True, checks=checks)
    assert asked["value"] is True


def test_choose_method_explicit_cloud_without_auth_prints_reason_instead_of_silent_fallback(
    monkeypatch, capsys
):
    """Waehlt der Nutzer explizit '2', ist Cloud aber nicht authentifiziert,
    darf choose_method() nicht wortlos auf local_chrome zurueckfallen."""
    checks = bcs.parse_doctor(DOCTOR_BLOCKED)  # cloud_available(checks) is False
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "2")
    result = bcs.choose_method(interactive=True, checks=checks)
    assert result == bcs.METHOD_LOCAL
    out = capsys.readouterr().out
    assert "auth login" in out.lower()


def test_main_force_interactive_does_not_silently_overwrite_recorded_cloud_with_local(
    tmp_path, monkeypatch
):
    """Integrationstest auf main()-Ebene: ein bereits vermerkter Cloud-Weg
    darf durch '--setup --force' nicht stillschweigend auf local_chrome
    zurueckfallen, nur weil Chrome gerade zufaellig lokal verbunden ist."""
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_CLOUD, checks={}, path=state_path)

    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "2")
    exit_code = bcs.main(
        ["--setup", "--force"],
        state_path=state_path,
        doctor_runner=lambda: DOCTOR_LOCAL_AND_CLOUD_READY,
        interactive=True,
    )
    assert exit_code == 0
    state = bcs.load_state(state_path)
    assert state["method"] == bcs.METHOD_CLOUD


def test_choose_method_non_interactive_force_keeps_recorded_cloud_method():
    """P1-Regression (PR #923 Review, dritter Fund): der interaktive Zweig
    ist seit dem vorigen Fix geschlossen, der nicht-interaktive Zweig
    (--force ohne TTY, z.B. aus einem Skript/CI) gab bislang immer
    METHOD_LOCAL zurueck — unabhaengig vom vermerkten Weg. Niemand kann
    nicht-interaktiv gefragt werden, also gilt: den vermerkten Weg
    beibehalten statt ihn stillschweigend zu ersetzen."""
    checks = bcs.parse_doctor(DOCTOR_READY)  # lokales Chrome verbunden
    assert (
        bcs.choose_method(interactive=False, checks=checks, current_method=bcs.METHOD_CLOUD)
        == bcs.METHOD_CLOUD
    )


def test_main_force_non_interactive_does_not_silently_overwrite_recorded_cloud_with_local(
    tmp_path,
):
    """Integrationstest auf main()-Ebene fuer den dritten P1-Fund: ein
    bereits vermerkter Cloud-Weg darf durch nicht-interaktives
    '--setup --force' (z.B. aus einem Skript/CI ohne TTY) nicht
    stillschweigend auf local_chrome zurueckfallen."""
    state_path = tmp_path / "browser_connection.json"
    bcs.record_method(bcs.METHOD_CLOUD, checks={}, path=state_path)

    exit_code = bcs.main(
        ["--setup", "--force"],
        state_path=state_path,
        doctor_runner=lambda: DOCTOR_READY,
        interactive=False,
    )
    assert exit_code == 0
    state = bcs.load_state(state_path)
    assert state["method"] == bcs.METHOD_CLOUD


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
