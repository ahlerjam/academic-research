"""Regressionstests fuer Issue #458 — nicht-interaktiver Bestaetigungsweg im
primaeren /setup-Pfad (PR #476-Review, P1-Finding).

Befund: `scripts/configure_permissions.py` schrieb Berechtigungen nur nach
TTY-Bestaetigung. Der dokumentierte Hauptinstallationspfad
(`/academic-research:setup` -> `commands/setup.md` -> `scripts/setup.sh`)
laeuft aber ohne Terminal (Claude-Code-Bash-Tool) -- es gab dafuer keinen
Bestaetigungsweg, AC1 war im Claude-Code-Pfad nur zur Haelfte erfuellt.

Fix (dieser Test deckt ihn ab):
- `scripts/setup.sh` meldet sichtbar, wenn Schritt 5 offen bleibt, inkl.
  Nachhol-Befehl.
- `commands/setup.md` deklariert `AskUserQuestion` in `allowed-tools` und
  beschreibt das Claude-seitige Bestaetigungs-Gate (Anzeige -> AskUserQuestion
  -> `configure_permissions.py --yes`), analog zum Consent-Gate in
  `commands/search.md` (vgl. test_issue_458_deep_search_consent.py).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_SH = REPO_ROOT / "scripts" / "setup.sh"
SETUP_COMMAND = REPO_ROOT / "commands" / "setup.md"

# ---------------------------------------------------------------------------
# scripts/setup.sh: sichtbare Meldung + Nachhol-Befehl im Nicht-TTY-Fall
# ---------------------------------------------------------------------------


def test_setup_sh_queries_pending_count_after_configure_permissions():
    content = SETUP_SH.read_text(encoding="utf-8")
    configure_idx = content.find('python3 "$SCRIPT_DIR/configure_permissions.py"')
    pending_count_idx = content.find("--pending-count")
    assert configure_idx != -1, "setup.sh muss configure_permissions.py weiterhin aufrufen"
    assert pending_count_idx != -1, (
        "setup.sh muss --pending-count nutzen, um offene Regeln sichtbar zu melden"
    )
    assert configure_idx < pending_count_idx


def test_setup_sh_reports_incomplete_step_five_with_followup_command():
    content = SETUP_SH.read_text(encoding="utf-8")
    assert "nicht abgeschlossen" in content, (
        "setup.sh muss sichtbar melden, wenn Schritt 5 (Permissions) offen bleibt"
    )
    assert "configure_permissions.py --yes" in content, (
        "setup.sh muss den konkreten Nachhol-Befehl (--yes) nennen"
    )


def test_setup_sh_is_still_valid_bash_syntax():
    import subprocess

    result = subprocess.run(
        ["bash", "-n", str(SETUP_SH)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"setup.sh hat einen Syntaxfehler:\n{result.stderr}"


# ---------------------------------------------------------------------------
# commands/setup.md: AskUserQuestion-Gate analog commands/search.md
# ---------------------------------------------------------------------------


def test_setup_command_allowed_tools_includes_ask_user_question():
    content = SETUP_COMMAND.read_text(encoding="utf-8")
    frontmatter = content.split("---")[1]
    for line in frontmatter.splitlines():
        if line.strip().startswith("allowed-tools:"):
            assert "AskUserQuestion" in line, (
                "setup.md nutzt AskUserQuestion fuer das Permissions-Bestaetigungs-Gate, "
                "muss es aber auch in allowed-tools deklarieren"
            )
            return
    raise AssertionError("Kein 'allowed-tools:' in setup.md-Frontmatter gefunden")


def test_setup_command_describes_ask_user_question_gate_before_yes_call():
    content = SETUP_COMMAND.read_text(encoding="utf-8")
    ask_idx = content.find("AskUserQuestion")
    yes_call_idx = content.find("configure_permissions.py --yes")
    assert ask_idx != -1, "setup.md muss das AskUserQuestion-Gate beschreiben"
    assert yes_call_idx != -1, "setup.md muss den '--yes'-Aufruf nach Zustimmung beschreiben"
    assert ask_idx < yes_call_idx, (
        "Die AskUserQuestion-Bestaetigung muss textuell VOR dem '--yes'-Aufruf stehen"
    )


def test_setup_command_still_mentions_confirm_before_write_semantics():
    content = SETUP_COMMAND.read_text(encoding="utf-8")
    assert "configure_permissions.py" in content
    assert "Bestätigung" in content or "Bestätigungs-Gate" in content
