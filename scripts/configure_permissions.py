#!/usr/bin/env python3
"""Configure Claude Code permissions for academic-research v4.

Adds required tool permissions to ~/.claude/settings.local.json.

Diese Datei ist BENUTZERWEIT (nicht projektbezogen): Die Regeln gelten fuer
ALLE Claude-Code-Projekte auf diesem Rechner, nicht nur fuer academic-research.
Deshalb zeigt die CLI (``__main__``-Block unten, ueber ``confirm_write()``) die
neu zu setzenden Regeln vor dem Schreiben an und verlangt eine Bestaetigung
(Issue #458). ``main()`` selbst bleibt davon unberuehrt und schreibt weiterhin
direkt — das haelt die Bestandstests aus Issue #230 (atomarer Schreibvorgang,
direkter ``main(settings_path=...)``-Aufruf ohne Stdin-Mock) gruen; das
Bestaetigungs-Gate sitzt strikt VOR dem ``main()``-Aufruf, nicht darin.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.local.json"

REQUIRED_PERMISSIONS = [
    "Bash(~/.academic-research/venv/bin/python *)",
    "Bash(~/.academic-research/venv/bin/pip *)",
    "Bash(browser-use:*)",
    "Bash(browser-use *)",
]


def atomic_write_text(path: Path, text: str) -> None:
    """Schreibe ``text`` atomar nach ``path``.

    Es wird zunächst in eine temporäre Datei im selben Verzeichnis geschrieben,
    auf die Platte geflusht und anschließend per ``os.replace`` an die Zielposition
    umbenannt. ``os.replace`` ist auf POSIX und Windows atomar. Bricht der Prozess
    vor dem ``os.replace`` ab (SIGKILL, Stromausfall, volle Disk), bleibt die alte
    Zieldatei unverändert erhalten; ein eventuell übrig gebliebenes Tempfile wird
    weggeräumt.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Bei jedem Fehler keine halbfertige Tempdatei zurücklassen.
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def pending_permissions(settings_path: Path) -> list[str]:
    """Gibt die ``REQUIRED_PERMISSIONS`` zurueck, die in ``settings_path`` noch
    fehlen (Diff gegen den bestehenden ``permissions.allow``-Array).

    Existiert die Datei nicht oder ist sie kein valides JSON, gilt die Liste
    als leer und alle ``REQUIRED_PERMISSIONS`` sind "pending".
    """
    settings_path = Path(settings_path)
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    allow_list: list[str] = settings.get("permissions", {}).get("allow", [])
    return [perm for perm in REQUIRED_PERMISSIONS if perm not in allow_list]


def confirm_write(pending: list[str], settings_path: Path) -> bool:
    """Zeigt die zu setzenden Berechtigungen an und fragt nach Bestaetigung.

    - Ohne neue Regeln (idempotenter Re-Lauf, ``pending`` leer): keine Rueckfrage
      noetig, gilt als bestaetigt (kein Prompt-Spam bei jedem Setup-Aufruf).
    - Nicht-interaktives stdin (CI/Pipe): sicherer Default = NICHT schreiben,
      analog ``scihub_optin.py``/``uni_profile_setup.py``.
    - Interaktiv: explizite Zustimmung ("j"/"ja"/"y"/"yes") erforderlich.
    """
    if not pending:
        return True

    print(
        "Folgende neue Claude-Code-Berechtigungen werden BENUTZERWEIT "
        "(alle Projekte, nicht nur academic-research) eingetragen:"
    )
    print(f"  Datei: {settings_path}")
    for perm in pending:
        print(f"  + {perm}")
    print(
        "Ruecknahme: die obigen Zeilen manuell aus dem 'permissions.allow'-Array "
        f"in {settings_path} entfernen."
    )

    if not sys.stdin.isatty():
        print(
            "ℹ️  Nicht-interaktives stdin — Berechtigungen werden NICHT automatisch "
            "geschrieben (sicherer Default). Zum Bestaetigen configure_permissions.py "
            "direkt in einem Terminal ausfuehren."
        )
        return False

    answer = input("Bestaetigen? [j/N] ").strip().lower()
    return answer in ("j", "ja", "y", "yes")


def main(settings_path: Path | None = None) -> int:
    settings_path = Path(settings_path) if settings_path is not None else SETTINGS_PATH

    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    allow_list: list[str] = settings.get("permissions", {}).get("allow", [])
    added = 0
    for perm in REQUIRED_PERMISSIONS:
        if perm not in allow_list:
            allow_list.append(perm)
            added += 1

    settings.setdefault("permissions", {})["allow"] = allow_list
    atomic_write_text(
        settings_path,
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
    )

    print(f"✅ Permissions updated ({added} new rules added)")
    print(f"   File: {settings_path}")
    return 0


if __name__ == "__main__":
    _pending = pending_permissions(SETTINGS_PATH)
    if confirm_write(_pending, SETTINGS_PATH):
        sys.exit(main(SETTINGS_PATH))
    print("⚠️  Abgebrochen — keine Berechtigungen geschrieben.")
    sys.exit(0)
