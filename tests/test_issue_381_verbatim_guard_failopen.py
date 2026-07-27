"""Tests fuer Issue #381 — verbatim-guard: Fail-open differenzieren, Bypass-Nutzung loggen.

Abgedeckt:
  AC2 — Exception bei VORHANDENER (aber defekter) Vault-DB wird sichtbar anders
        behandelt als der reine "DB fehlt"-Fall (beide bleiben fail-open, exit 0).
  AC4 — Nutzung des Bypass-Markers <!-- vault-guard: skip --> wird nachvollziehbar
        geloggt (stderr-Warnung + persistenter Log-Eintrag via VAULT_GUARD_BYPASS_LOG).

AC1 (DB fehlt bleibt fail-open mit unveraendertem Wortlaut) und AC3 (Block-Message
ohne Bypass-Marker-Wortlaut) sind als Regressions-Pins in test_verbatim_figure_guard.py
mituntergebracht.
"""

import json
import os
import subprocess
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hooks" / "verbatim-guard.mjs"
WORKTREE_ROOT = Path(__file__).parent.parent


def run_hook(
    tool_name: str, file_path: str, content: str, env_overrides: dict = None
) -> subprocess.CompletedProcess:
    """Startet den Hook als Subprocess mit JSON-Eingabe auf stdin."""
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {
                "file_path": file_path,
                "content": content,
            },
        }
    )
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = str(WORKTREE_ROOT / "nonexistent_vault_for_tests.db")
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["node", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# AC2 — Exception bei vorhandener (aber korrupter) DB != "DB fehlt"
# ---------------------------------------------------------------------------


def test_hook_failopen_distinguishes_corrupt_db_from_missing_db(tmp_path):
    """Existiert die DB-Datei, ist aber keine gueltige SQLite-DB, wirft der Python-
    Subprozess eine Exception. Der Guard bleibt fail-open (exit 0, Regressionsschutz),
    aber der Wortlaut muss sich sichtbar vom "DB fehlt"-Fall unterscheiden."""
    corrupt_db = tmp_path / "corrupt_vault.db"
    corrupt_db.write_text("dies ist keine sqlite-datenbank")

    content = 'Laut Autor "Dies ist ein sehr wichtiger Satz aus dem Buch" stimmt das.'
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_DB_PATH": str(corrupt_db)},
    )

    assert result.returncode == 0, (
        f"Erwartet 0 (weiterhin fail-open bei korrupter DB), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "Vault-DB nicht gefunden" not in result.stderr, (
        f"Korrupte (aber vorhandene) DB darf nicht wie 'DB fehlt' behandelt werden: {result.stderr}"
    )
    # Neuer, unterscheidbarer Marker fuer den Exception-Fall bei vorhandener DB.
    assert "vorhandener" in result.stderr or "trotz vorhandener DB" in result.stderr, (
        f"Erwartet einen expliziten Hinweis auf 'DB vorhanden, aber Fehler' in stderr: {result.stderr}"
    )


def test_figure_hook_failopen_distinguishes_corrupt_db_from_missing_db(tmp_path):
    """Wie oben, aber fuer den Figure-Guard-Pfad (lookupFigureInVault)."""
    corrupt_db = tmp_path / "corrupt_vault2.db"
    corrupt_db.write_text("dies ist keine sqlite-datenbank")

    content = "Wie in Abb. 3.4 gezeigt, ist der Effekt signifikant."
    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_DB_PATH": str(corrupt_db)},
    )

    assert result.returncode == 0, (
        f"Erwartet 0 (weiterhin fail-open bei korrupter DB), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "Vault-DB nicht gefunden" not in result.stderr
    assert "vorhandener" in result.stderr or "trotz vorhandener DB" in result.stderr, (
        f"Erwartet einen expliziten Hinweis auf 'DB vorhanden, aber Fehler' in stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# AC4 — Bypass-Nutzung wird geloggt
# ---------------------------------------------------------------------------


def test_bypass_marker_usage_is_logged(tmp_path):
    """Content mit dem Bypass-Marker erzeugt eine stderr-Warnung UND einen
    persistenten Log-Eintrag unter VAULT_GUARD_BYPASS_LOG (Env-Override,
    analog ACADEMIC_DECISIONS_LOG)."""
    bypass_log = tmp_path / "vault-guard-bypass.log"
    content = '<!-- vault-guard: skip -->\n"Ein unverifiziertes Zitat, das den Bypass nutzt."'

    result = run_hook(
        "Write",
        "kapitel/kap1.md",
        content,
        env_overrides={"VAULT_GUARD_BYPASS_LOG": str(bypass_log)},
    )

    assert result.returncode == 0, (
        f"Bypass-Marker soll weiterhin allow (exit 0) ergeben, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "Bypass" in result.stderr, f"Erwartet Bypass-Warnung in stderr: {result.stderr}"

    assert bypass_log.exists(), "Bypass-Log-Datei wurde nicht angelegt"
    log_content = bypass_log.read_text()
    assert "kapitel/kap1.md" in log_content, (
        f"Erwartet Datei-Referenz im Bypass-Log: {log_content!r}"
    )
    assert any(ch.isdigit() for ch in log_content), (
        f"Erwartet einen Zeitstempel im Bypass-Log: {log_content!r}"
    )


def test_bypass_marker_log_is_append_only_across_calls(tmp_path):
    """Mehrere Bypass-Nutzungen haengen mehrere Zeilen an (kein Ueberschreiben)."""
    bypass_log = tmp_path / "vault-guard-bypass.log"

    for i in range(2):
        content = f'<!-- vault-guard: skip -->\n"Zitat Nummer {i} das lang genug ist."'
        result = run_hook(
            "Write",
            f"kapitel/kap{i}.md",
            content,
            env_overrides={"VAULT_GUARD_BYPASS_LOG": str(bypass_log)},
        )
        assert result.returncode == 0

    lines = [line for line in bypass_log.read_text().splitlines() if line.strip()]
    assert len(lines) >= 2, f"Erwartet mindestens 2 Log-Zeilen, got {len(lines)}: {lines}"
