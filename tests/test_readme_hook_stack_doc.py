"""Regressions-Tests fuer Doku-Konsistenz des Hook-Stacks (#205, #402).

Testet:
  (a) Die Nutzerdoku enthaelt NICHT den erfundenen "SessionMid"-Event.
  (b) Die dokumentierten Hook-Events stimmen mit den real in hooks/hooks.json
      konfigurierten Events ueberein.
  (c) Die Doku behauptet keine falsche Hook-Anzahl.
  (d) Die Hooks-Tabelle nennt keine Skripte, die gar nicht verdrahtet sind.

Die Hooks-Tabelle stand bis #402 in der README; sie liegt jetzt in
docs/reference/hooks.md. Geprueft wird derselbe Inhalt an der neuen Stelle.

(Der fruehere Teil pruefte docs/MIGRATION-v5-to-v6.md — Datei mit #346 entfernt.)
"""

import json
from pathlib import Path

from tests.helpers import docs as _docs

REPO_ROOT = Path(__file__).parent.parent
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"


def _hooks_doc() -> str:
    """Gibt den Inhalt der Hooks-Referenz zurueck."""
    text = _docs.HOOKS_DOC.read_text(encoding="utf-8")
    assert text.startswith("# Hooks-Stack"), (
        "docs/reference/hooks.md hat keine '# Hooks-Stack'-Ueberschrift mehr"
    )
    return text


def test_readme_does_not_contain_session_mid():
    """'SessionMid' existiert in Claude Code nicht — nirgends in der Nutzerdoku."""
    for path in _docs.doc_surface():
        if not path.exists():
            continue
        assert "SessionMid" not in path.read_text(encoding="utf-8"), (
            f"{path.name} enthaelt den nicht-existierenden Claude-Code-Event 'SessionMid'. "
            "Die echten Event-Namen sind 'Notification' und 'PostCompact'."
        )


def test_readme_hook_events_match_hooks_json():
    """Die Hook-Events in der Doku muessen mit hooks/hooks.json uebereinstimmen."""
    hooks_data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    real_events = set(hooks_data["hooks"].keys())

    hooks_section = _hooks_doc()

    for event in real_events:
        assert event in hooks_section, (
            f"Event '{event}' ist in hooks/hooks.json konfiguriert, "
            f"wird aber in der Hooks-Referenz nicht erwaehnt."
        )


def test_readme_hook_count_not_four():
    """Doku soll nicht 'vier Hooks' behaupten (tatsaechlich 7 Events)."""
    hooks_section = _hooks_doc()
    assert "vier Hooks" not in hooks_section, (
        "Doku behauptet noch 'vier Hooks', aber hooks/hooks.json konfiguriert 7 Events."
    )


def test_hooks_json_has_expected_events():
    """hooks/hooks.json muss alle sieben erwarteten Events enthalten."""
    hooks_data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    real_events = set(hooks_data["hooks"].keys())

    expected_events = {
        "PreToolUse",
        "PostToolUse",
        "PreCompact",
        "Notification",
        "PostCompact",
        "SessionStart",
        "Stop",
    }
    assert expected_events == real_events, (
        f"hooks.json enthaelt andere Events als erwartet.\n"
        f"Erwartet: {sorted(expected_events)}\n"
        f"Gefunden: {sorted(real_events)}"
    )


def test_doc_names_only_wired_hook_scripts():
    """Jede in der Hooks-Tabelle genannte Skriptdatei ist real verdrahtet.

    Befund aus #387/#402: die alte README fuehrte
    hooks/onboard-project-uni-prompt.sh als SessionStart-Hook, obwohl
    hooks/hooks.json dort ein Inline-Bash-Kommando aufruft. Das Skript ist ein
    manuell aufzurufender Helfer, kein Hook.
    """
    wired = json.dumps(json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"])
    table_rows = [ln for ln in _hooks_doc().splitlines() if ln.strip().startswith("|")]

    ghosts = []
    for row in table_rows:
        for script in (REPO_ROOT / "hooks").glob("*"):
            if script.name == "hooks.json":
                continue
            if script.name in row and script.name not in wired:
                ghosts.append(f"{script.name} in Zeile: {row.strip()}")
    assert not ghosts, f"Hooks-Tabelle nennt nicht verdrahtete Skripte als Hook: {ghosts}"
