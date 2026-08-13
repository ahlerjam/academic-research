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
    cloud_available,
    load_state,
    parse_doctor,
    preflight_ready,
)
from browser_connection_setup import run_doctor as _run_doctor_real

UNCONFIGURED_MESSAGE = (
    "❌ Browser-Verbindung ist noch nicht eingerichtet.\n"
    "   Fuehre zuerst das Setup aus: /academic-research:setup (Schritt 4)\n"
    "   oder direkt: ~/.academic-research/venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/browser_connection_setup.py --setup\n"
    "   Browser-Module dieses Laufs werden uebersprungen; die API-Module\n"
    "   laufen davon unabhaengig weiter."
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


def check(state: dict | None, checks: dict[str, bool]) -> tuple[bool, str]:
    """Reine Entscheidungsfunktion: (ok, message)."""
    if state is None:
        # Wenn der Weg nicht vermerkt ist, aber die Verbindung steht:
        # Funktioniert die Preflight-Pruefung, dann erlauben wir den Browser-Teil
        # mit einem Hinweis, das Setup nachzuholen (statt komplett abzubrechen).
        if preflight_ready(checks):
            return (
                True,
                "✓ Browser-Verbindung aktiv (Weg noch nicht vermerkt — /setup Schritt 4 nachholen)",
            )
        return False, UNCONFIGURED_MESSAGE

    method = state.get("method")
    if method == METHOD_CLOUD:
        if cloud_available(checks):
            return True, "ok"
        return False, CLOUD_BLOCKED_MESSAGE

    # Default/METHOD_LOCAL (und jeder unbekannte/kuenftige Wert faellt
    # sicherheitshalber auf den lokalen Pfad zurueck statt stillschweigend
    # als Erfolg zu gelten).
    # Fuer Preflight: daemon_alive genuegt (active_browser_connections koennen
    # noch nicht da sein nach Setup, bis der Chrome-Dialog bestaetigt ist).
    if preflight_ready(checks):
        return True, "ok"
    return False, LOCAL_BLOCKED_MESSAGE


def main(
    argv: list[str] | None = None,
    *,
    state_path: Path | None = None,
    doctor_runner: Callable[[], str] | None = None,
) -> int:
    state = load_state(state_path)
    runner = doctor_runner if doctor_runner is not None else _run_doctor_real
    checks = parse_doctor(runner())

    ok, message = check(state, checks)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
