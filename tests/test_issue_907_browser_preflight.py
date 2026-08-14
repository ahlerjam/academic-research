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
    """Echter AC2-Fall: kein Vermerk UND keine funktionierende Verbindung.

    Korrigiert (PR #923 Review, fuenfter Fund): dieser Test benutzte vorher
    DOCTOR_READY — also eine STEHENDE Verbindung ohne Vermerk — und schrieb
    damit versehentlich den Bug fest, den der Review meldete: eine
    Bestandsinstallation ohne browser_connection.json (die Datei legt erst
    der neue setup.sh-Schritt 4 an), aber mit laengst funktionierender
    Verbindung, wurde faelschlich blockiert, bis der Nutzer manuell erneut
    '/setup' aufruft. Dieser Fall gehoert jetzt zu
    test_preflight_backfills_state_for_preexisting_install_with_working_connection
    unten und darf durchlaufen. "Nie konfiguriert" im Sinne von Issue #907
    AC2 ist nur der Fall ohne Vermerk UND ohne funktionierende Verbindung —
    das prueft dieser Test jetzt mit DOCTOR_BLOCKED."""
    exit_code = browser_preflight.main(
        [], state_path=tmp_path / "missing.json", doctor_runner=lambda: DOCTOR_BLOCKED
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


# ---------------------------------------------------------------------------
# P1-Regression (PR #923 Review, vierter Fund): der Fail-closed-Fix fuer
# "nie konfiguriert" (test_preflight_fails_when_never_configured) darf nicht
# JEDE unlesbare/veraltete Vermerk-Datei wie "nie konfiguriert" behandeln.
# Setup IST in dem Fall schon mal gelaufen (die Datei existiert) — nur das
# Format, das eine aeltere Plugin-Version geschrieben hat, versteht der
# aktuelle Code nicht. Das darf nach einem gewoehnlichen Plugin-Update nicht
# jeden Browser-Lauf blockieren, solange die Verbindung tatsaechlich steht.
# ---------------------------------------------------------------------------


def test_preflight_ok_when_existing_state_file_predates_current_json_format(tmp_path, capsys):
    """Simuliert einen Vermerk aus einer aelteren Plugin-Version: die Datei
    existiert (Setup ist gelaufen), ihr Inhalt ist aber kein JSON-Objekt im
    aktuellen Schema (hier: reiner Text statt {"method": ...}). Bei stehender
    Verbindung darf das nicht wie ein fehlendes Setup blockieren."""
    state_path = tmp_path / "browser_connection.json"
    state_path.write_text("local_chrome\n", encoding="utf-8")  # aelteres Nicht-JSON-Format

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_READY
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower()


def test_preflight_blocks_with_recovery_message_when_legacy_state_and_connection_down(
    tmp_path, capsys
):
    """Derselbe veraltete Vermerk, aber diesmal steht die Verbindung
    tatsaechlich nicht — dann muss weiterhin blockiert werden, allerdings
    mit der Wiederherstellungs-Anleitung (LOCAL_BLOCKED_MESSAGE), nicht mit
    der 'noch nie eingerichtet'-Meldung (UNCONFIGURED_MESSAGE)."""
    state_path = tmp_path / "browser_connection.json"
    state_path.write_text("local_chrome\n", encoding="utf-8")

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_BLOCKED
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    # LOCAL_BLOCKED_MESSAGE (Wiederherstellung), nicht UNCONFIGURED_MESSAGE
    # ("noch nicht eingerichtet") — die Datei existiert ja, Setup lief schon:
    assert "noch nicht eingerichtet" not in out.lower()
    assert "allow" in out.lower()


# ---------------------------------------------------------------------------
# P1-Regression (PR #923 Review, fuenfter Fund): eine Bestandsinstallation,
# die '/academic-research:setup' schon VOR diesem PR ausgefuehrt hat, besitzt
# ueberhaupt keine browser_connection.json — die legt erst der in diesem
# Diff neue setup.sh-Schritt 4 an. state ist in dem Fall None, nicht "Datei
# existiert, aber unlesbar" (das war der vierte Fund oben). Der naechste
# '/search --mode standard'-Lauf darf nicht leer laufen, obwohl Chrome
# verbunden und browser-use einsatzbereit ist — nur weil die Zustandsdatei
# fehlt. Steht die Verbindung, wird der Weg nachgetragen und der Lauf
# durchgelassen; steht sie nicht, bleibt es beim echten AC2-Fall (siehe
# test_preflight_fails_when_never_configured oben).
# ---------------------------------------------------------------------------


def test_preflight_backfills_state_for_preexisting_install_with_working_connection(
    tmp_path, capsys
):
    state_path = tmp_path / "browser_connection.json"
    assert not state_path.exists()  # echte Bestandsinstallation: nie geschrieben

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_READY
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "nachtragen" in out.lower() or "nachgetragen" in out.lower()

    state = bcs.load_state(state_path)
    assert state is not None
    assert state["method"] == bcs.METHOD_LOCAL


def test_preflight_still_blocks_when_no_state_and_no_working_connection(tmp_path, capsys):
    """Gegenprobe zum Backfill oben: fehlt der Vermerk UND steht keine
    Verbindung, bleibt es beim Blockieren mit UNCONFIGURED_MESSAGE — kein
    Weg wird nachgetragen, da nichts auf eine Bestandsinstallation mit
    funktionierender Verbindung hindeutet."""
    state_path = tmp_path / "browser_connection.json"
    assert not state_path.exists()

    exit_code = browser_preflight.main(
        [], state_path=state_path, doctor_runner=lambda: DOCTOR_BLOCKED
    )
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "noch nicht eingerichtet" in out.lower()
    assert not state_path.exists()  # kein Nachtragen ohne funktionierende Verbindung
