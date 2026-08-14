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


def preflight_ready(checks: dict[str, bool]) -> bool:
    """Pruefung fuer Preflight: der Daemon muss laufen, UND falls der Doctor
    etwas zu aktiven Verbindungen sagt, muss das ein ``[ok]`` sein.

    Issue #907 trat exakt im Zustand ``daemon alive`` + ``[FAIL] active
    browser connections — 0`` auf (P1-Review PR #923) — dieser Zustand darf
    nicht mehr als bereit gelten, sonst startet der Modul-Loop trotzdem und
    stirbt mittendrin mit ``permission-blocked``. Fehlt die
    ``active_browser_connections``-Zeile im Doctor-Snapshot dagegen
    komplett (kein Key, z.B. andere CLI-Version), bleibt der lenient
    Fallback auf ``daemon_alive`` bestehen — dafuer war die urspruengliche
    Kulanz gedacht, nicht fuer ein explizites ``[FAIL]``."""
    if not checks.get("daemon_alive"):
        return False
    if "active_browser_connections" not in checks:
        return True
    return bool(checks["active_browser_connections"])


def cloud_available(checks: dict[str, bool]) -> bool:
    """True nur, wenn Doctor die Cloud-Auth als ``[ok]`` meldet (nicht bei
    der ``[FAIL] ... optional: ...``-Zeile eines nicht eingeloggten Kontos)."""
    return bool(checks.get("browser_use_cloud_auth"))


CLOUD_NOT_AUTHENTICATED_MESSAGE = (
    "Cloud-Browser nicht verfuegbar: 'browser-use auth login' ausfuehren und "
    "danach erneut '--setup --force' aufrufen. Bleibe vorerst beim vermerkten "
    "Weg."
)


def choose_method(
    interactive: bool,
    checks: dict[str, bool],
    current_method: str | None = None,
) -> str:
    """Ermittelt den Verbindungsweg. Cloud wird ausschliesslich bei
    explizitem interaktivem Opt-in gewaehlt (Issue #907 AC5) — nie als
    automatischer/nicht-interaktiver Default, selbst wenn Cloud-Auth laut
    Doctor bereits verfuegbar waere.

    ``current_method`` ist der zuvor vermerkte Weg (falls vorhanden). Die
    fruehere connection_ready-Abkuerzung (sofort METHOD_LOCAL, ohne
    Rueckfrage) griff auch interaktiv — dadurch kam ein interaktives
    ``--setup --force`` bei zufaellig gerade verbundenem lokalem Chrome nie
    zum Prompt und ueberschrieb einen vermerkten Cloud-Weg stillschweigend
    mit local_chrome (P1-Review PR #923). Die Abkuerzung gilt jetzt nur noch
    im nicht-interaktiven Fall.

    Nicht-interaktiv (kein TTY, z.B. ein Skript oder CI ruft ``--force``
    ohne Rueckfrage auf) kann niemand gefragt werden. Ist bereits ein Weg
    vermerkt, bleibt er deshalb erhalten statt ihn stillschweigend durch
    METHOD_LOCAL zu ersetzen (dritter P1-Fund, PR #923 Review) — dieselbe
    Regel wie beim expliziten '2' ohne Cloud-Auth oben: ein vermerkter Weg
    wird nie kommentarlos ueberschrieben. Nur wenn ueberhaupt noch nichts
    vermerkt ist (Erstlauf), bleibt METHOD_LOCAL der sichere Default
    (Issue #907 AC5: Cloud nie automatischer Default)."""
    if not interactive:
        if current_method in (METHOD_LOCAL, METHOD_CLOUD):
            return current_method
        return METHOD_LOCAL
    answer = input(PROMPT).strip()
    if answer == "2":
        if cloud_available(checks):
            return METHOD_CLOUD
        print(CLOUD_NOT_AUTHENTICATED_MESSAGE)
        return current_method if current_method in (METHOD_LOCAL, METHOD_CLOUD) else METHOD_LOCAL
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
    """Liest den vermerkten Zustand.

    ``None`` bedeutet ausschliesslich "die Datei existiert nicht" — der
    einzige echte "nie konfiguriert"-Fall (Issue #907 AC2), den
    ``browser_preflight.check()`` mit der UNCONFIGURED_MESSAGE blockiert.

    Existiert die Datei, aber laesst sich ihr Inhalt nicht als JSON-Objekt
    lesen (kaputtes JSON, kein Dict, oder — der P1-Fund aus dem PR-#923-
    Review — ein Vermerk in einem Format, das eine aeltere/neuere
    Plugin-Version geschrieben hat), ist das KEIN "nie konfiguriert": das
    Setup ist ja gelaufen, nur der aktuelle Code versteht das Format nicht.
    Ein Plugin-Update darf bestehende Installationen deshalb nicht bei
    jedem internen Formatwechsel zum erneuten Setup zwingen. Statt ``None``
    liefert dieser Fall ein leeres Dict: ``check()`` behandelt das wie
    "Weg unbekannt" und faellt auf den regulaeren, verbindungsbasierten
    Preflight-Check zurueck (blockiert nur bei tatsaechlich fehlender
    Verbindung, mit der Wiederherstellungs-Anleitung statt der
    Setup-Aufforderung)."""
    target = Path(path) if path is not None else _default_state_path()
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


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
        # state kann None (Datei fehlt) ODER ein leeres/methodenloses Dict
        # sein (Datei existiert, aber Format unbekannt/aelterer Vermerk,
        # siehe load_state()-Docstring) — in beiden Faellen ist kein Weg
        # bekannt, also "unset"/Exit 1.
        method = state.get("method") if isinstance(state, dict) else None
        if not method:
            print("unset")
            return 1
        print(method)
        return 0

    force = "--force" in args
    existing = load_state(path)
    if not force and existing is not None and existing.get("method"):
        print(f"✅ Browser-Verbindungsweg bereits eingerichtet: {existing['method']}")
        return 0

    current_method = existing.get("method") if isinstance(existing, dict) else None

    checks = parse_doctor(runner())
    method = choose_method(interactive=is_interactive, checks=checks, current_method=current_method)
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
