"""Tests fuer den geteilten Batch-Vault-Cache der drei Kapitel-Guards (Issue #844).

``verbatim-guard.mjs``, ``claim-drift-guard.mjs`` und ``context-fidelity-guard.mjs``
laufen als drei separate OS-Prozesse (hooks.json, PreToolUse Write|Edit|MultiEdit)
und schlugen bisher fuer denselben Write groesstenteils dieselben Zitat-Texte im
Vault nach — jeder mit einem eigenen Python-Subprozess. Seit #844 teilen sie sich
dafuer einen dateibasierten Cache (``hooks/lib/vault-bridge.mjs::ensureQuoteBatch``).

Geprueft werden die Akzeptanzkriterien aus #844:
  AC1  Ein Write mit N Zitaten loest hoechstens EINEN Python-Subprozess-Start
       fuer die Vault-Lookups aller drei Guards aus.
  AC2  Bestehende Guard-Suiten bleiben gruen (separat abgedeckt, siehe
       tests/test_verbatim_figure_guard.py, tests/test_issue_397_claim_drift.py,
       tests/test_issue_522_context_fidelity.py, scripts/dev/test-pretooluse-blocker.sh).
  AC3  Fail-open bleibt erhalten: eine kaputte/unschreibbare Cache-Datei blockiert
       keinen Write.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
VERBATIM_HOOK = REPO_ROOT / "hooks" / "verbatim-guard.mjs"
CLAIM_DRIFT_HOOK = REPO_ROOT / "hooks" / "claim-drift-guard.mjs"
CONTEXT_FIDELITY_HOOK = REPO_ROOT / "hooks" / "context-fidelity-guard.mjs"

PAPER_ID = "mueller-2021-batch-cache"
VAULT_VERBATIM = "Der Effekt war in allen Kohorten nachweisbar und stabil."
# Bewusst OHNE Klammer-Beleg (Autor-Jahr-Form): eine erkannte Zitation loest in
# verbatim-guard.mjs einen ZWEITEN, eigenstaendigen Subprozess aus
# (verifyCitationsInVault — nicht Teil dieses Issues, Out-of-Scope). Fuer den
# reinen Zitat-Lookup-Nachweis (AC1) bleibt der Testtext deshalb citation-frei.
CHAPTER_OLD = (
    "## Ergebnisse\n\n"
    "Die Studie zeigt einen moderaten Effekt auf die Lesekompetenz. "
    f'"{VAULT_VERBATIM}"\n'
)
CHAPTER_NEW = CHAPTER_OLD.replace("moderaten", "starken")


def _make_vault(tmp_path: Path, name: str = "batch_cache_vault.db") -> str:
    from academic_vault.db import VaultDB
    from academic_vault.server import add_paper, add_quote

    db_path = str(tmp_path / name)
    db = VaultDB(db_path)
    db.init_schema()
    add_paper(
        db_path=db_path,
        paper_id=PAPER_ID,
        csl_json=json.dumps({"title": "Lesekompetenz", "type": "article-journal"}),
    )
    add_quote(
        db_path=db_path,
        paper_id=PAPER_ID,
        verbatim=VAULT_VERBATIM,
        extraction_method="manual",
        printed_page=45,
        context_before="Vorheriger Satz zur Einordnung.",
        context_after="Nachfolgender Satz mit Einschraenkung.",
    )
    return db_path


def _write_counting_wrapper(path: Path, marker_file: Path) -> None:
    """Legt einen Interpreter-Wrapper an, der JEDEN Aufruf in ``marker_file``
    protokolliert und danach an den ECHTEN Test-Python-Interpreter
    durchreicht (academic_vault muss importierbar bleiben, #382)."""
    path.write_text(f'#!/bin/sh\necho call >> "{marker_file}"\nexec "{sys.executable}" "$@"\n')
    path.chmod(0o755)


def _run_hook(hook: Path, payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _base_env(tmp_path: Path, vault_db: str, marker_file: Path, wrapper: Path) -> dict:
    env = os.environ.copy()
    env["VAULT_DB_PATH"] = vault_db
    env["ACADEMIC_PYTHON"] = str(wrapper)
    env["HOOK_BATCH_CACHE_DIR"] = str(tmp_path / "hook-batch-cache")
    # Bypass-/Env-Switch-Logs isoliert vom echten Nutzerverzeichnis halten.
    env["VAULT_GUARD_BYPASS_LOG"] = str(tmp_path / "bypass.log")
    env["VAULT_GUARD_ENV_SWITCH_LOG"] = str(tmp_path / "env-switch.log")
    marker_file.touch(exist_ok=True)
    return env


# ---------------------------------------------------------------------------
# AC1 — hoechstens EIN Subprozess fuer alle drei Guards zusammen
# ---------------------------------------------------------------------------


def test_three_guards_share_one_vault_subprocess_per_write(tmp_path):
    vault_db = _make_vault(tmp_path)
    marker_file = tmp_path / "python-calls.log"
    wrapper = tmp_path / "counting-python"
    _write_counting_wrapper(wrapper, marker_file)
    env = _base_env(tmp_path, vault_db, marker_file, wrapper)

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(tmp_path / "kapitel" / "kap1.md"),
            "old_string": CHAPTER_OLD,
            "new_string": CHAPTER_NEW,
        },
    }

    # Exakt wie hooks.json, PreToolUse Write|Edit|MultiEdit: verbatim-guard
    # zuerst, dann claim-drift-guard, dann context-fidelity-guard.
    results = [
        _run_hook(VERBATIM_HOOK, payload, env),
        _run_hook(CLAIM_DRIFT_HOOK, payload, env),
        _run_hook(CONTEXT_FIDELITY_HOOK, payload, env),
    ]

    for result in results:
        assert result.returncode == 0, (
            f"Guard hat blockiert/ist abgestuerzt (returncode={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    calls = marker_file.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1, (
        f"Erwartet genau EINEN Python-Subprozess-Start fuer die Vault-Lookups "
        f"aller drei Guards zusammen (Issue #844, AC1), tatsaechlich: {len(calls)} "
        f"(marker_file={calls})"
    )


def test_three_guards_share_cache_regardless_of_order(tmp_path):
    """Robustheit gegen eine kuenftige hooks.json-Reihenfolge-Aenderung
    (Plan-Risiko: Producer-Rolle ist NICHT an "verbatim-guard laeuft zuerst"
    gekoppelt, sondern an "wer zuerst einen Cache-Miss sieht")."""
    vault_db = _make_vault(tmp_path, name="batch_cache_vault_reorder.db")
    marker_file = tmp_path / "python-calls-reorder.log"
    wrapper = tmp_path / "counting-python-reorder"
    _write_counting_wrapper(wrapper, marker_file)
    env = _base_env(tmp_path, vault_db, marker_file, wrapper)

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(tmp_path / "kapitel" / "kap2.md"),
            "old_string": CHAPTER_OLD,
            "new_string": CHAPTER_NEW,
        },
    }

    # Umgekehrte Reihenfolge: context-fidelity-guard sieht den Cache-Miss zuerst.
    results = [
        _run_hook(CONTEXT_FIDELITY_HOOK, payload, env),
        _run_hook(CLAIM_DRIFT_HOOK, payload, env),
        _run_hook(VERBATIM_HOOK, payload, env),
    ]
    for result in results:
        assert result.returncode == 0, result.stderr

    calls = marker_file.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1, (
        f"Producer-Rolle darf nicht an eine feste Guard-Reihenfolge gekoppelt sein "
        f"— tatsaechlich {len(calls)} Subprozess-Starts bei umgekehrter Reihenfolge."
    )


# ---------------------------------------------------------------------------
# AC3 — Fail-open bei kaputtem/unschreibbarem Cache
# ---------------------------------------------------------------------------


def test_corrupt_cache_file_does_not_block_write(tmp_path):
    """Eine korrupte Cache-Datei (kein valides JSON) darf den Write nicht
    blockieren — der betroffene Guard behandelt den Eintrag wie einen
    Cache-Miss und berechnet frisch (fail-open, AC3)."""
    vault_db = _make_vault(tmp_path, name="batch_cache_vault_corrupt.db")
    marker_file = tmp_path / "python-calls-corrupt.log"
    wrapper = tmp_path / "counting-python-corrupt"
    _write_counting_wrapper(wrapper, marker_file)
    env = _base_env(tmp_path, vault_db, marker_file, wrapper)

    cache_dir = Path(env["HOOK_BATCH_CACHE_DIR"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Jede beliebige Datei im Cache-Verzeichnis reicht nicht, um GENAU den
    # richtigen Schluessel zu treffen — stattdessen fuellen wir das
    # Verzeichnis mit einer garantiert falsch benannten korrupten Datei, um
    # sicherzustellen, dass ein grundsaetzlich lesbares, aber kaputtes
    # Verzeichnis den Guard nicht aus der Bahn wirft.
    (cache_dir / "garbage.json").write_text("{not valid json", encoding="utf-8")

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(tmp_path / "kapitel" / "kap3.md"),
            "content": CHAPTER_NEW,
        },
    }
    result = _run_hook(VERBATIM_HOOK, payload, env)
    assert result.returncode == 0, (
        f"Korrupte Fremd-Cache-Datei darf verbatim-guard.mjs nicht blockieren: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignoriert Verzeichnisrechte")
def test_unwritable_cache_dir_does_not_block_write(tmp_path):
    """Ein nicht beschreibbares Cache-Verzeichnis darf den Write nicht
    blockieren — writeBatchCache() schluckt den Fehler best-effort (AC3)."""
    vault_db = _make_vault(tmp_path, name="batch_cache_vault_unwritable.db")
    marker_file = tmp_path / "python-calls-unwritable.log"
    wrapper = tmp_path / "counting-python-unwritable"
    _write_counting_wrapper(wrapper, marker_file)
    env = _base_env(tmp_path, vault_db, marker_file, wrapper)

    cache_dir = Path(env["HOOK_BATCH_CACHE_DIR"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.chmod(0o500)  # lesbar/betretbar, aber nicht beschreibbar

    try:
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(tmp_path / "kapitel" / "kap4.md"),
                "content": CHAPTER_NEW,
            },
        }
        result = _run_hook(VERBATIM_HOOK, payload, env)
        assert result.returncode == 0, (
            f"Unschreibbares Cache-Verzeichnis darf verbatim-guard.mjs nicht "
            f"blockieren: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    finally:
        cache_dir.chmod(0o700)
