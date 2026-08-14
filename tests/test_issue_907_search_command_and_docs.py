"""Regressionstests fuer Issue #907 — Prosa-Anforderungen in
``commands/search.md`` und der Doku, die sich nicht als reiner Python-Aufruf
testen lassen (String-Assertions, analog
``tests/test_issue_458_deep_search_consent.py``).

Akzeptanzkriterien (Issue #907):
- AC2: Preflight steht textuell VOR dem Modul-Loop.
- AC3: Verbindungsabbruch mitten im Lauf nennt die betroffenen Module; der
  uebrige Lauf laeuft weiter.
- AC4: Die Doku nennt die Bedingung fuer unbeaufsichtigtes `--mode deep`.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_COMMAND = REPO_ROOT / "commands" / "search.md"
TROUBLESHOOTING = REPO_ROOT / "docs" / "guide" / "troubleshooting.md"
INSTALLATION = REPO_ROOT / "docs" / "guide" / "installation.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC2: Preflight-Aufruf steht vor dem Modul-Loop
# ---------------------------------------------------------------------------


def test_search_md_calls_browser_preflight():
    text = _text(SEARCH_COMMAND)
    assert "browser_preflight.py" in text


def test_search_md_preflight_precedes_module_loop():
    text = _text(SEARCH_COMMAND)
    preflight_pos = text.index("browser_preflight.py")
    loop_pos = text.index("No-Auth zuerst")
    assert preflight_pos < loop_pos, (
        "Preflight-Aufruf muss textuell VOR dem Modul-Loop stehen (Issue #907 AC2)"
    )


# ---------------------------------------------------------------------------
# AC3: Verbindungsabbruch waehrend des Loops
# ---------------------------------------------------------------------------


def test_search_md_has_connection_drop_case():
    text = _text(SEARCH_COMMAND)
    assert "Verbindungsabbruch" in text


def test_search_md_connection_drop_names_affected_modules_and_continues():
    text = _text(SEARCH_COMMAND)
    drop_pos = text.index("Verbindungsabbruch")
    section = text[drop_pos : drop_pos + 900]
    assert "Module" in section
    assert "weiter" in section


# ---------------------------------------------------------------------------
# AC4: Doku nennt die Bedingung fuer unbeaufsichtigtes --mode deep
# ---------------------------------------------------------------------------


def test_troubleshooting_states_unattended_deep_mode_condition():
    text = _text(TROUBLESHOOTING)
    assert "--mode deep" in text
    assert "unbeaufsichtigt" in text
    assert "nicht" in text


def test_installation_mentions_907_connection_setup_step():
    text = _text(INSTALLATION)
    assert "browser_connection.json" in text
    assert "unbeaufsichtigt" in text
