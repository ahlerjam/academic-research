"""Chrome-Verbindungsweg fuer browser-use einrichten und vermerken (Issue #907).

`browser-use` verbindet sich per CDP mit Chrome. Chrome fragt die Erlaubnis
dafuer ueber einen nativen Dialog ab, und die Erteilung haelt nicht dauerhaft
an — nach einer Weile meldet `browser-use --doctor` wieder
`[FAIL] active browser connections — 0`, obwohl Chrome laeuft.

Dieses Modul ermittelt einmalig (im Rahmen von `setup.sh`), ueber welchen Weg
der Browser erreicht wird, und vermerkt das Ergebnis atomar in
`~/.academic-research/browser_connection.json`. Ein spaeterer Lauf (siehe
`browser_preflight.py`) liest diesen Zustand statt die Entscheidung erneut
auszuhandeln.

Zwei Wege stehen zur Wahl:

- ``METHOD_LOCAL`` — das lokale, per CDP verbundene Chrome. Braucht i.d.R.
  einen einmaligen Klick auf "Allow" im Chrome-Berechtigungsdialog; danach
  laeuft die Verbindung, bis Chrome sie von sich aus wieder schliesst.
- ``METHOD_CLOUD`` — ein von Browser Use gehosteter Cloud-Browser. Kostet
  Geld und setzt eine vorherige ``browser-use auth login`` voraus. Wird laut
  Issue-Scope **nie** automatisch gewaehlt, auch wenn er verfuegbar waere —
  nur bei explizitem interaktivem Opt-in.

Bei nicht-interaktivem stdin (z.B. der primaere `/setup`-Aufruf durch Claude
Code, oder CI) gilt der sichere Default: ``METHOD_LOCAL``, ohne Rueckfrage.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from deep_search_consent import atomic_write_text

STATE_PATH = Path.home() / ".academic-research" / "browser_connection.json"

METHOD_LOCAL = "local_chrome"
METHOD_CLOUD = "cloud"

PROMPT = (
    "Wie soll browser-use den Browser erreichen?\n"
    "  [1] Lokales Chrome (einmaliger Klick auf 'Allow' im Chrome-Popup) [Default]\n"
    "  [2] Cloud-Browser (kostenpflichtig, kein Klick noetig, benoetigt 'browser-use auth login')\n"
    "Auswahl [1]: "
)

# Eine Zeile aus `browser-use --doctor`, z.B.:
#   [ok  ] chrome running
#   [FAIL] active browser connections — 0
#   [FAIL] Browser Use cloud auth — optional: browser-harness auth login
_DOCTOR_LINE = re.compile(r"^\s*\[\s*(ok|FAIL)\s*\]\s+(.+?)\s*(?:—.*)?$")


def _default_state_path() -> Path:
    return STATE_PATH


def _label_to_key(label: str) -> str:
    key = label.strip().lower()
    key = re.sub(r"[^a-z0-9]+", "_", key)
    return key.strip("_")


def parse_doctor(text: str) -> dict[str, bool]:
    """Parst die Ausgabe von ``browser-use --doctor`` in ein Status-Dict.

    Jede ``[ok ]``/``[FAIL]``-Zeile wird zu einem Key (normalisiertes Label)
    -> Bool. Unbekannter/leerer Text ergibt ein leeres Dict — das behandelt
    ein aufrufender Code bewusst wie "nichts geprueft", nicht wie Erfolg."""
    checks: dict[str, bool] = {}
    for line in text.splitlines():
        match = _DOCTOR_LINE.match(line)
        if not match:
            continue
        status, label = match.groups()
        checks[_label_to_key(label)] = status == "ok"
    return checks


def run_doctor() -> str:
    """Ruft ``browser-use --doctor`` real auf. Fehlt die CLI, leerer String —
    ``parse_doctor("")`` liefert dann ein leeres Dict statt eines Crashes."""
    try:
        result = subprocess.run(
            ["browser-use", "--doctor"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return (result.stdout or "") + (result.stderr or "")


def connection_ready(checks: dict[str, bool]) -> bool:
    """True, wenn ``browser-use`` laut Doctor-Snapshot ohne weiteres Zutun
    verbinden kann (Daemon laeuft und mindestens eine aktive Verbindung)."""
    return bool(checks.get("daemon_alive")) and bool(checks.get("active_browser_connections"))


def cloud_available(checks: dict[str, bool]) -> bool:
    """True nur, wenn Doctor die Cloud-Auth als ``[ok]`` meldet (nicht bei
    der ``[FAIL] ... optional: ...``-Zeile eines nicht eingeloggten Kontos)."""
    return bool(checks.get("browser_use_cloud_auth"))


def choose_method(interactive: bool, checks: dict[str, bool]) -> str:
    """Ermittelt den Verbindungsweg. Cloud wird ausschliesslich bei
    explizitem interaktivem Opt-in gewaehlt (Issue #907 AC5) — nie als
    automatischer/nicht-interaktiver Default, selbst wenn Cloud-Auth laut
    Doctor bereits verfuegbar waere."""
    if connection_ready(checks):
        return METHOD_LOCAL
    if not interactive:
        return METHOD_LOCAL
    answer = input(PROMPT).strip()
    if answer == "2" and cloud_available(checks):
        return METHOD_CLOUD
    return METHOD_LOCAL


def record_method(method: str, checks: dict[str, bool], path: Path | None = None) -> None:
    """Schreibt den ermittelten Weg atomar nach ``path`` (Default: STATE_PATH)."""
    target = Path(path) if path is not None else _default_state_path()
    data = {
        "method": method,
        "configured_at": datetime.now(UTC).isoformat(),
        "doctor_snapshot": checks,
    }
    atomic_write_text(target, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_state(path: Path | None = None) -> dict | None:
    """Liest den vermerkten Zustand. ``None`` wenn nie eingerichtet oder die
    Datei kaputt/kein Dict ist — der sichere "nicht konfiguriert"-Fall."""
    target = Path(path) if path is not None else _default_state_path()
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def main(
    argv: list[str] | None = None,
    *,
    state_path: Path | None = None,
    doctor_runner: Callable[[], str] | None = None,
    interactive: bool | None = None,
) -> int:
    """CLI-Fassade fuer den Aufruf aus ``setup.sh``.

    ``--check``: druckt den vermerkten Weg (oder ``unset``), Exit 0/1.
    ``--setup`` (Default): ermittelt und vermerkt den Weg. Existiert bereits
    ein vermerkter Weg, wird nicht erneut gefragt (Idempotenz) — es sei denn
    ``--force`` steht zusaetzlich in argv.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    path = state_path if state_path is not None else _default_state_path()
    runner = doctor_runner if doctor_runner is not None else run_doctor
    is_interactive = sys.stdin.isatty() if interactive is None else interactive

    if "--check" in args:
        state = load_state(path)
        if state is None:
            print("unset")
            return 1
        print(state.get("method", "unset"))
        return 0

    force = "--force" in args
    if not force:
        existing = load_state(path)
        if existing is not None and existing.get("method"):
            print(f"✅ Browser-Verbindungsweg bereits eingerichtet: {existing['method']}")
            return 0

    checks = parse_doctor(runner())
    method = choose_method(interactive=is_interactive, checks=checks)
    record_method(method, checks, path=path)

    if method == METHOD_LOCAL and not connection_ready(checks):
        print(
            "⚠️  Browser-Verbindungsweg vermerkt: local_chrome (Chrome-Berechtigung "
            "aktuell nicht aktiv — beim naechsten Browser-Lauf ggf. 'Allow' im "
            "Chrome-Popup bestaetigen)."
        )
    else:
        print(f"✅ Browser-Verbindungsweg vermerkt: {method}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
