"""Regressionstests fuer Issue #458 — Berechtigungen eng fassen + Confirm-Gate.

Akzeptanzkriterien (Issue #458):
- AC1: Das Setup zeigt die zu setzenden Berechtigungen an und schreibt sie
  erst nach Bestaetigung.
- AC2: Keine der gesetzten Regeln erlaubt pauschale Codeausfuehrung.
- AC3: Die Doku (docs/guide/installation.md) benennt, dass die Aenderung
  benutzerweit wirkt, und beschreibt die Ruecknahme.

``main(settings_path=...)`` selbst bleibt unveraendert direkt schreibend
(Bestandstests aus Issue #230) — das Confirm-Gate sitzt strikt auf
CLI-Ebene (``pending_permissions`` + ``confirm_write``), nicht in ``main()``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import configure_permissions

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLATION_DOC = REPO_ROOT / "docs" / "guide" / "installation.md"

# ---------------------------------------------------------------------------
# AC2: keine pauschalen Exec-Muster
# ---------------------------------------------------------------------------

BLANKET_EXEC_PATTERNS = {
    "Bash(python3 *)",
    "Bash(python *)",
    "Bash(bash *)",
    "Bash(sh *)",
    "Bash(sh -c *)",
    "Bash(mkdir *)",
    "Bash(ls *)",
    "Bash(cat *)",
    "Bash(rm *)",
    "Bash(*)",
}

REMOVED_LEGACY_PATTERNS = {
    "Bash(python3 *)",
    "Bash(mkdir *)",
    "Bash(ls *)",
    "Bash(cat *)",
}


def test_required_permissions_has_no_blanket_exec_pattern():
    for perm in configure_permissions.REQUIRED_PERMISSIONS:
        assert perm not in BLANKET_EXEC_PATTERNS, (
            f"{perm} erlaubt pauschale Codeausfuehrung (Issue #458 AC2)"
        )


def test_legacy_blanket_patterns_removed():
    """Die im Plan genannten Blanket-Muster duerfen nicht mehr enthalten sein."""
    for perm in REMOVED_LEGACY_PATTERNS:
        assert perm not in configure_permissions.REQUIRED_PERMISSIONS, (
            f"{perm} haette aus REQUIRED_PERMISSIONS entfernt werden sollen (Issue #458)"
        )


def test_required_permissions_still_covers_venv_and_browser_use():
    """Eng gescopte, tatsaechlich benoetigte Muster bleiben erhalten."""
    allow = configure_permissions.REQUIRED_PERMISSIONS
    assert "Bash(~/.academic-research/venv/bin/python *)" in allow
    assert "Bash(~/.academic-research/venv/bin/pip *)" in allow
    assert "Bash(browser-use:*)" in allow
    assert "Bash(browser-use *)" in allow


# ---------------------------------------------------------------------------
# P1-Fix (PR #476-Review, Runde 2): eng gescoptes Ersatzmuster fuer das
# ersatzlos entfernte Bash(mkdir *) -- ohne dieses Muster loesen
# commands/search.md (mkdir -p unter sessions/) und commands/latex.md
# (mkdir -p unter library-profiles/) bei jedem Lauf eine Permission-
# Rueckfrage aus, weil weder die globale Regel noch die command-eigenen
# allowed-tools mkdir abdecken.
# ---------------------------------------------------------------------------

SCOPED_MKDIR_PATTERN = "Bash(mkdir -p ~/.academic-research/*)"
SEARCH_COMMAND_MD = REPO_ROOT / "commands" / "search.md"
LATEX_COMMAND_MD = REPO_ROOT / "commands" / "latex.md"


def test_required_permissions_has_scoped_mkdir_replacement():
    assert SCOPED_MKDIR_PATTERN in configure_permissions.REQUIRED_PERMISSIONS, (
        "REQUIRED_PERMISSIONS muss ein eng gescoptes Ersatzmuster fuer das "
        "entfernte Bash(mkdir *) enthalten (PR #476-Review P1)"
    )
    assert SCOPED_MKDIR_PATTERN not in BLANKET_EXEC_PATTERNS, (
        "das Ersatzmuster darf keine pauschale Codeausfuehrung sein (AC2)"
    )


def test_scoped_mkdir_pattern_covers_search_command_invocation():
    content = SEARCH_COMMAND_MD.read_text(encoding="utf-8")
    assert 'mkdir -p "$SESSION_DIR/pdfs"' in content, (
        "commands/search.md legt weiterhin ein Session-Verzeichnis per mkdir -p an"
    )
    # Der Praefix vor der Variablenexpansion muss zum Muster passen: die
    # Regel matcht "mkdir -p ~/.academic-research/" + beliebiger Rest, und
    # $SESSION_DIR ist als ~/.academic-research/sessions/... definiert.
    assert "SESSION_DIR=~/.academic-research/sessions/" in content


def test_scoped_mkdir_pattern_covers_latex_command_invocation():
    content = LATEX_COMMAND_MD.read_text(encoding="utf-8")
    assert "mkdir -p ~/.academic-research/library-profiles/" in content, (
        "commands/latex.md legt weiterhin library-profiles/ per mkdir -p an"
    )


# ---------------------------------------------------------------------------
# pending_permissions()
# ---------------------------------------------------------------------------


def test_pending_permissions_returns_all_when_file_missing(tmp_path):
    target = tmp_path / "settings.local.json"
    pending = configure_permissions.pending_permissions(target)
    assert set(pending) == set(configure_permissions.REQUIRED_PERMISSIONS)


def test_pending_permissions_empty_when_already_present(tmp_path):
    target = tmp_path / "settings.local.json"
    target.write_text(
        json.dumps({"permissions": {"allow": list(configure_permissions.REQUIRED_PERMISSIONS)}}),
        encoding="utf-8",
    )
    assert configure_permissions.pending_permissions(target) == []


def test_pending_permissions_partial_diff(tmp_path):
    target = tmp_path / "settings.local.json"
    existing = configure_permissions.REQUIRED_PERMISSIONS[0]
    target.write_text(
        json.dumps({"permissions": {"allow": [existing]}}),
        encoding="utf-8",
    )
    pending = configure_permissions.pending_permissions(target)
    assert existing not in pending
    for perm in configure_permissions.REQUIRED_PERMISSIONS[1:]:
        assert perm in pending


# ---------------------------------------------------------------------------
# AC1: Anzeige + Bestaetigung vor dem Schreiben (CLI-Gate)
# ---------------------------------------------------------------------------


class _FakeStdinTTY:
    @staticmethod
    def isatty():
        return True


class _FakeStdinNonTTY:
    @staticmethod
    def isatty():
        return False


def test_confirm_write_declines_without_writing(monkeypatch, tmp_path):
    """Stdin=Nein -> settings.local.json bleibt unveraendert (main() nicht aufgerufen)."""
    target = tmp_path / "settings.local.json"
    original = {"theme": "dark", "permissions": {"allow": []}}
    target.write_text(json.dumps(original), encoding="utf-8")

    monkeypatch.setattr(sys, "stdin", _FakeStdinTTY())
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "n")

    pending = configure_permissions.pending_permissions(target)
    confirmed = configure_permissions.confirm_write(pending, target)
    assert confirmed is False

    # main() wird nur bei confirmed==True aufgerufen (__main__-Gate) -> Datei
    # bleibt unveraendert.
    assert json.loads(target.read_text(encoding="utf-8")) == original


def test_confirm_write_accepts_then_main_writes(monkeypatch, tmp_path):
    """Stdin=Ja -> confirm_write() True, anschliessendes main() schreibt neue Regeln."""
    target = tmp_path / "settings.local.json"
    target.write_text(json.dumps({"permissions": {"allow": []}}), encoding="utf-8")

    monkeypatch.setattr(sys, "stdin", _FakeStdinTTY())
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "j")

    pending = configure_permissions.pending_permissions(target)
    confirmed = configure_permissions.confirm_write(pending, target)
    assert confirmed is True

    rc = configure_permissions.main(settings_path=target)
    assert rc == 0
    allow = json.loads(target.read_text(encoding="utf-8"))["permissions"]["allow"]
    for perm in configure_permissions.REQUIRED_PERMISSIONS:
        assert perm in allow


def test_confirm_write_non_interactive_defaults_to_false(monkeypatch, tmp_path):
    """Nicht-interaktives stdin (CI/Pipe) -> sicherer Default: kein Schreiben."""
    target = tmp_path / "settings.local.json"
    monkeypatch.setattr(sys, "stdin", _FakeStdinNonTTY())

    pending = configure_permissions.pending_permissions(target)
    confirmed = configure_permissions.confirm_write(pending, target)
    assert confirmed is False
    assert not target.exists()


def test_confirm_write_skips_prompt_when_nothing_pending(monkeypatch, tmp_path):
    """Idempotenz (Plan-Risiko #4): ohne neue Permissions wird nicht gefragt."""
    target = tmp_path / "settings.local.json"
    target.write_text(
        json.dumps({"permissions": {"allow": list(configure_permissions.REQUIRED_PERMISSIONS)}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "stdin", _FakeStdinTTY())

    def _boom(*_a, **_kw):
        raise AssertionError("input() haette bei pending==[] nicht aufgerufen werden duerfen")

    monkeypatch.setattr("builtins.input", _boom)

    pending = configure_permissions.pending_permissions(target)
    assert pending == []
    assert configure_permissions.confirm_write(pending, target) is True


def test_confirm_write_assume_yes_bypasses_non_interactive_default(monkeypatch, tmp_path):
    """P1-Fix (#458, PR #476-Review): --yes/assume_yes muss auch OHNE TTY
    bestaetigen -- genau der primaere /setup-Pfad via Claude Code (kein
    Terminal), fuer den es zuvor keinen nicht-interaktiven Zustimmungsweg gab.
    """
    target = tmp_path / "settings.local.json"
    monkeypatch.setattr(sys, "stdin", _FakeStdinNonTTY())

    def _boom(*_a, **_kw):
        raise AssertionError("input() haette bei assume_yes=True nicht aufgerufen werden duerfen")

    monkeypatch.setattr("builtins.input", _boom)

    pending = configure_permissions.pending_permissions(target)
    confirmed = configure_permissions.confirm_write(pending, target, assume_yes=True)
    assert confirmed is True


def test_confirm_write_assume_yes_false_default_unchanged(monkeypatch, tmp_path):
    """assume_yes ist optional und defaultet auf False -- bestehendes
    Verhalten (sicherer Default ohne TTY) bleibt unveraendert."""
    target = tmp_path / "settings.local.json"
    monkeypatch.setattr(sys, "stdin", _FakeStdinNonTTY())

    pending = configure_permissions.pending_permissions(target)
    assert configure_permissions.confirm_write(pending, target) is False


# ---------------------------------------------------------------------------
# CLI-Fassade: --yes / ACADEMIC_RESEARCH_CONFIRM_PERMISSIONS / --pending-count
# (P1-Fix #458, PR #476-Review: nicht-interaktiver Bestaetigungsweg fuer den
# primaeren /setup-Pfad, der ohne TTY laeuft)
# ---------------------------------------------------------------------------


def _run_cli(
    args: list[str], settings_path: Path, env_extra: dict | None = None
) -> subprocess.CompletedProcess:
    module_path = Path(configure_permissions.__file__)
    env = dict(os.environ)
    env["HOME"] = str(settings_path.parent.parent)  # SETTINGS_PATH = ~/.claude/settings.local.json
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(module_path), *args],
        input="",  # explizit leeres stdin -> nicht-interaktiv (kein TTY)
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _isolated_settings_path(tmp_path: Path) -> Path:
    claude_dir = tmp_path / "home" / ".claude"
    claude_dir.mkdir(parents=True)
    return claude_dir / "settings.local.json"


def test_cli_without_yes_non_interactive_does_not_write(tmp_path):
    target = _isolated_settings_path(tmp_path)
    result = _run_cli([], target)
    assert result.returncode == 0
    assert not target.exists()
    assert "NICHT automatisch" in result.stdout


def test_cli_yes_flag_writes_without_tty(tmp_path):
    target = _isolated_settings_path(tmp_path)
    result = _run_cli(["--yes"], target)
    assert result.returncode == 0
    assert target.exists(), "CLI --yes haette trotz fehlendem TTY schreiben muessen"
    allow = json.loads(target.read_text(encoding="utf-8"))["permissions"]["allow"]
    for perm in configure_permissions.REQUIRED_PERMISSIONS:
        assert perm in allow


def test_cli_env_var_confirms_without_tty(tmp_path):
    target = _isolated_settings_path(tmp_path)
    result = _run_cli([], target, env_extra={"ACADEMIC_RESEARCH_CONFIRM_PERMISSIONS": "1"})
    assert result.returncode == 0
    assert target.exists()


def test_cli_pending_count_reports_full_count_without_writing(tmp_path):
    target = _isolated_settings_path(tmp_path)
    result = _run_cli(["--pending-count"], target)
    assert result.returncode == 0
    assert result.stdout.strip() == str(len(configure_permissions.REQUIRED_PERMISSIONS))
    assert not target.exists()


def test_cli_pending_count_zero_after_yes_write(tmp_path):
    target = _isolated_settings_path(tmp_path)
    _run_cli(["--yes"], target)
    result = _run_cli(["--pending-count"], target)
    assert result.stdout.strip() == "0"


def test_main_signature_unchanged_for_issue_230_compat():
    """main(settings_path=...) bleibt fuer Bestandstests aus #230 direkt
    schreibend und ohne Bestaetigungs-Gate."""
    import inspect

    sig = inspect.signature(configure_permissions.main)
    assert "settings_path" in sig.parameters


# ---------------------------------------------------------------------------
# AC3: Doku benennt benutzerweiten Scope + Ruecknahme
# ---------------------------------------------------------------------------


def test_installation_doc_mentions_user_wide_scope_and_rollback():
    assert INSTALLATION_DOC.exists(), f"Doku fehlt: {INSTALLATION_DOC}"
    content = INSTALLATION_DOC.read_text(encoding="utf-8")

    assert "benutzerweit" in content.lower(), (
        "installation.md muss den benutzerweiten (nicht projektbezogenen) "
        "Scope der Permission-Aenderung benennen (Issue #458 AC3)"
    )
    assert "~/.claude/settings.local.json" in content, (
        "installation.md muss den konkreten Pfad der benutzerweiten Datei nennen"
    )
    assert "ücknahme" in content or "ueckgaengig" in content.lower(), (
        "installation.md muss eine Ruecknahme-Anleitung beschreiben"
    )
    assert "entfernen" in content.lower(), (
        "installation.md muss konkret beschreiben, wie die Aenderung rueckgaengig "
        "gemacht wird (manuelles Entfernen aus permissions.allow)"
    )
