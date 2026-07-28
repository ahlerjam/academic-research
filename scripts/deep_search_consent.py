"""Consent-Gate fuer Tiefensuche mit Hochschul-Zugangsdaten (Issue #458).

``commands/search.md`` startet im Tiefensuche-Modus (``--mode deep``) Browser-
Sessions gegen EBSCOhost, ProQuest und den Hochschul-OPAC, die per HAN-Login
(``config/browser_guides/han_login.md``, ``agents/auth-helper.md``)
Hochschul-Zugangsdaten verwenden. Bevor das erste dieser Auth-Module
(``ebscohost``, ``proquest``, ``opac``) startet, muss dafuer eine einmalige,
erklaerte Zustimmung vorliegen.

Dieses Modul kapselt nur den Zustimmungs-Zustand:

- ``has_consent()`` prueft, ob bereits zugestimmt wurde
  (``~/.academic-research/consent.json``).
- ``record_consent()`` speichert die Zustimmung atomar und idempotent.

Kein Auth-Logik, keine Credentials — die bleiben vollstaendig in
``auth-helper``/``han_login.md`` (Out of Scope fuer Issue #458).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONSENT_PATH = Path.home() / ".academic-research" / "consent.json"

# Ein Key pro unabhaengigem Consent-Zweck. Aktuell nur die Tiefensuche mit
# Hochschul-Zugangsdaten (EBSCOhost/ProQuest/OPAC via HAN); weitere Zwecke
# koennen spaeter als eigene Keys ergaenzt werden, ohne bestehende Zustimmungen
# zu beeinflussen.
DEEP_SEARCH_CONSENT_KEY = "deep_search_uni_credentials"


def _default_consent_path() -> Path:
    return CONSENT_PATH


def atomic_write_text(path: Path, text: str) -> None:
    """Schreibe ``text`` atomar nach ``path`` (Tempfile + ``os.replace``).

    Analog ``configure_permissions.atomic_write_text`` — bricht der Prozess
    vor dem finalen ``os.replace`` ab, bleibt die alte Datei unveraendert.
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
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _load(consent_path: Path) -> dict:
    if not consent_path.exists():
        return {}
    try:
        data = json.loads(consent_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def has_consent(consent_path: Path | None = None) -> bool:
    """True, wenn fuer die Tiefensuche mit Hochschul-Zugangsdaten bereits eine
    Zustimmung gespeichert ist. Fehlt die Datei oder der Key, gilt der sichere
    Default: keine Zustimmung (``False``)."""
    path = Path(consent_path) if consent_path is not None else _default_consent_path()
    return bool(_load(path).get(DEEP_SEARCH_CONSENT_KEY, False))


def record_consent(consent_path: Path | None = None) -> None:
    """Speichert die Zustimmung atomar. Idempotent: mehrfacher Aufruf
    veraendert den gespeicherten Zustand nicht (bleibt ``True``), erhaelt
    andere bereits vorhandene Keys in derselben Datei."""
    path = Path(consent_path) if consent_path is not None else _default_consent_path()
    data = _load(path)
    data[DEEP_SEARCH_CONSENT_KEY] = True
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    """CLI-Fassade fuer den Aufruf aus commands/search.md heraus.

    ``--check``: druckt ``yes``/``no`` je nach ``has_consent()``.
    ``--record``: ruft ``record_consent()`` auf.
    Ohne Argument: wie ``--check``.
    """
    import sys

    args = sys.argv[1:]
    if "--record" in args:
        record_consent()
        print("yes")
        return 0
    print("yes" if has_consent() else "no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
