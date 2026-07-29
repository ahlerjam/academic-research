"""Akzeptanz-Guard fuer Issue #468 (AC1) — Setup prueft die Node.js-Laufzeit.

Befund: 5 der 7 Hooks sind ``.mjs``-Dateien und werden in ``hooks/hooks.json``
per ``node ...`` gestartet — darunter der beworbene Halluzinationsschutz
(``verbatim-guard``). Fehlt Node, fallen diese Hooks lautlos aus; das Setup
gab bislang keinerlei Hinweis.

AC1 (Issue #468): "Fehlt die JavaScript-Laufzeit, meldet das Setup das
deutlich und nennt den Installationsweg."

Vorbild fuer den Test-Zuschnitt: ``tests/test_issue_201_python_version.py``
(statische Text-Assertion gegen ``scripts/setup.sh``).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SETUP_SH = REPO_ROOT / "scripts" / "setup.sh"


def _text() -> str:
    assert SETUP_SH.exists(), "scripts/setup.sh fehlt."
    return SETUP_SH.read_text(encoding="utf-8")


def test_setup_sh_checks_node_presence() -> None:
    """setup.sh prueft explizit, ob eine Node-Laufzeit verfuegbar ist."""
    text = _text()
    assert re.search(r"command -v node\b", text), (
        "setup.sh prueft die Node.js-Verfuegbarkeit nicht (erwartet 'command -v node')."
    )


def test_setup_sh_node_check_precedes_python_env_setup() -> None:
    """Der Node-Check laeuft frueh, nicht erst nach der venv-Erstellung."""
    text = _text()
    node_pos = text.find("command -v node")
    venv_pos = text.find("python3 -m venv")
    assert node_pos != -1, "Node-Check fehlt."
    assert venv_pos != -1, "venv-Erstellung fehlt (Referenzpunkt fuer die Reihenfolge)."
    assert node_pos < venv_pos, (
        "Der Node-Check sollte vor der venv-Erstellung laufen, analog zum "
        "Python-Versions-Check (#201)."
    )


def test_setup_sh_missing_node_warns_clearly_with_install_hint() -> None:
    """Fehlt Node, meldet das Setup das sichtbar UND nennt den Installationsweg."""
    text = _text()
    match = re.search(r"if ! command -v node[^\n]*\n(.*?)\nfi\n", text, re.DOTALL)
    assert match, "Kein 'if ! command -v node ...; then ... fi'-Block gefunden."
    warn_block = match.group(1)
    assert "⚠️" in warn_block, "Der Fehlerpfad meldet nicht sichtbar (kein ⚠️)."
    assert "brew install node" in warn_block, (
        "Der Fehlerpfad nennt keinen konkreten Installationsbefehl (erwartet 'brew install node')."
    )


def test_setup_sh_missing_node_does_not_hard_exit() -> None:
    """Fehlende Node-Laufzeit bricht das Setup NICHT hart ab (nur Warnung).

    Begruendung: venv, Permissions, Bootstrap, Uni-Profil und SciHub-Opt-in
    sind node-unabhaengig — nur 5 der 7 Hooks faellen sonst lautlos aus.
    Konsistent mit dem bestehenden browser-use-Muster (Abschnitt 3), das bei
    fehlenden Tools ebenfalls warnt statt abzubrechen.
    """
    text = _text()
    match = re.search(r"if ! command -v node[^\n]*\n(.*?)\nfi\n", text, re.DOTALL)
    assert match, "Kein 'if ! command -v node ...; then ... fi'-Block gefunden."
    warn_block = match.group(1)
    assert "exit 1" not in warn_block, (
        "Der Node-Check darf bei fehlendem Node nicht hart abbrechen (nur Warnung, kein 'exit 1')."
    )
