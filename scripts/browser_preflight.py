"""Preflight-Pruefung der Browser-Verbindung (Issue #907).

``commands/search.md`` ruft dieses Skript in Schritt 4 auf, **bevor** das
erste Browser-Modul eines Laufs startet. Es liest den in
``browser_connection_setup.py`` vermerkten Verbindungsweg und prueft ihn
billig (ein ``browser-use --doctor``-Aufruf, keine Navigation, kein neuer
Tab). Steht die Verbindung nicht, sagt die Ausgabe, was zu tun ist —
welcher Dialog, welche Alternative, wie der Lauf danach fortgesetzt wird —
statt der blossen Fehlerkonstante ``permission-blocked``.

Exit-Codes:
  0 -> Browser-Teil des Laufs kann starten.
  1 -> Browser-Teil wird fuer diesen Lauf uebersprungen (Grund + naechster
       Schritt stehen auf stdout); der uebrige Lauf (API-Module etc.) ist
       davon nicht betroffen.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from browser_connection_setup import (
    METHOD_CLOUD,
    METHOD_LOCAL,
    cloud_available,
    load_state,
    parse_doctor,
    preflight_ready,
    record_method,
)
from browser_connection_setup import run_doctor as _run_doctor_real

UNCONFIGURED_MESSAGE = (
    "❌ Browser-Verbindung ist noch nicht eingerichtet.\n"
    "   Fuehre zuerst das Setup aus: /academic-research:setup (Schritt 4)\n"
    "   oder direkt: ~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/browser_connection_setup.py --setup\n"
    "   Browser-Module dieses Laufs werden uebersprungen; die API-Module\n"
    "   laufen davon unabhaengig weiter."
)

BACKFILLED_MESSAGE = (
    "✅ Verbindungsweg nachtragen: local_chrome. Kein Vermerk in\n"
    "   ~/.academic-research/browser_connection.json gefunden — vermutlich eine\n"
    "   Bestandsinstallation, die '/academic-research:setup' schon vor Issue #907\n"
    "   ausgefuehrt hat (die Vermerk-Datei legt erst der neue Setup-Schritt 4 an).\n"
    "   browser-use meldet aber eine funktionierende lokale Verbindung, also wird\n"
    "   der Weg jetzt automatisch nachgetragen. Dieser Hinweis erscheint nur beim\n"
    "   ersten Lauf nach dem Update; danach ist der Vermerk vorhanden."
)

LOCAL_BLOCKED_MESSAGE = (
    "❌ Browser-Verbindung nicht aktiv (browser-use meldet keine aktive\n"
    "   Verbindung/Daemon).\n"
    "   1. Chrome oeffnen und chrome://inspect/#remote-debugging aufrufen.\n"
    "   2. Im Chrome-Popup auf 'Allow' klicken, um Remote-Debugging fuer\n"
    "      diese Sitzung zu erlauben.\n"
    "   3. Diesen Lauf danach erneut starten — Browser-Module dieses Laufs\n"
    "      werden fuer jetzt uebersprungen, die API-Module laufen unabhaengig\n"
    "      davon weiter.\n"
    "   Alternative ohne Klick (kostenpflichtig): Cloud-Browser einrichten\n"
    "   mit 'browser-use auth login' und danach erneut\n"
    "   '~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/browser_connection_setup.py --setup --force'\n"
    "   ausfuehren, dort Option 2 waehlen."
)

CLOUD_BLOCKED_MESSAGE = (
    "❌ Cloud-Browser ist als Weg vermerkt, aber nicht (mehr) authentifiziert.\n"
    "   1. 'browser-use auth login' ausfuehren.\n"
    "   2. Danach '~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/browser_connection_setup.py --setup --force'\n"
    "      erneut ausfuehren.\n"
    "   Browser-Module dieses Laufs werden uebersprungen; die API-Module\n"
    "   laufen davon unabhaengig weiter."
)


def check(state: dict | None, checks: dict[str, bool]) -> tuple[bool, str, str | None]:
    """Reine Entscheidungsfunktion: (ok, message, backfill_method).

    ``backfill_method`` ist nicht ``None``, wenn ``main()`` den vermerkten
    Weg nachtragen soll (siehe unten) — ``check()`` selbst schreibt nicht,
    das bleibt I/O-Aufgabe von ``main()``."""
    if state is None:
        # Kein Weg vermerkt. Zwei ununterscheidbare Ursachen von aussen:
        # (a) Setup ist nie gelaufen (Issue #907 AC2) -> blockieren.
        # (b) Bestandsinstallation, die '/academic-research:setup' schon VOR
        #     diesem PR ausgefuehrt hat -- die Vermerk-Datei legt erst der
        #     neue setup.sh-Schritt 4 an, es gibt aber laengst eine
        #     funktionierende Verbindung (P1-Fund, PR #923 Review). Ihren
        #     naechsten Lauf leer laufen zu lassen, bis sie manuell erneut
        #     '/setup' aufruft, waere ein neuer, selbst verursachter Ausfall.
        # Das einzige von aussen pruefbare Unterscheidungsmerkmal ist, ob
        # die Verbindung tatsaechlich steht: steht sie, ist state=None mit
        # hoher Wahrscheinlichkeit Fall (b) -- der Weg wird nachgetragen und
        # der Lauf durchgelassen. Steht sie nicht, bleibt es bei Fall (a).
        if preflight_ready(checks):
            return True, BACKFILLED_MESSAGE, METHOD_LOCAL
        return False, UNCONFIGURED_MESSAGE, None

    method = state.get("method")
    if method == METHOD_CLOUD:
        if cloud_available(checks):
            return True, "ok", None
        return False, CLOUD_BLOCKED_MESSAGE, None

    # Default/METHOD_LOCAL (und jeder unbekannte/kuenftige Wert faellt
    # sicherheitshalber auf den lokalen Pfad zurueck statt stillschweigend
    # als Erfolg zu gelten).
    # preflight_ready() verlangt daemon_alive UND (falls im Doctor-Snapshot
    # vorhanden) ein explizites [ok] bei active_browser_connections — der
    # Zustand aus Issue #907 ([ok] daemon alive + [FAIL] active connections)
    # gilt seit dem P1-Fix (PR #923 Review) nicht mehr als bereit.
    if preflight_ready(checks):
        return True, "ok", None
    return False, LOCAL_BLOCKED_MESSAGE, None


def main(
    argv: list[str] | None = None,
    *,
    state_path: Path | None = None,
    doctor_runner: Callable[[], str] | None = None,
) -> int:
    state = load_state(state_path)
    runner = doctor_runner if doctor_runner is not None else _run_doctor_real
    checks = parse_doctor(runner())

    ok, message, backfill_method = check(state, checks)
    if backfill_method is not None:
        record_method(backfill_method, checks, path=state_path)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
