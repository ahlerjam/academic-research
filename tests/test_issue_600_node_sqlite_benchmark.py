"""Tests fuer Issue #600 — node:sqlite vs. Python-Subprozess, gemessen statt vermutet.

Vorbedingung des Issues: die Umstellung der Node-Hooks von einem Python-
Subprozess (`hooks/lib/vault-bridge.mjs::runVaultPython`) auf das eingebaute
`node:sqlite` lohnt erst ab CI-Node 22.5+ (dort landete das Modul, wenn auch
hinter `--experimental-sqlite`; unflagged nutzbar erst ab 22.13/23.4 -- Quelle:
https://nodejs.org/api/sqlite.html, Abschnitt "History"). Und: "Ohne Zahl keine
Umstellung" -- der Geschwindigkeitsunterschied muss gemessen sein, nicht nur
behauptet.

Diese Datei prueft:
  AC1  CI-Node-Version ist in beiden Jobs auf mindestens Node 22 angehoben.
  AC2  `scripts/dev/bench_vault_bridge.mjs` liefert ein Benchmark mit
       Median-Millisekunden ueber mehrere Wiederholungen (kein Einzelwert),
       fuer beide Zugriffswege -- und der Python-Subprozess ist (strukturell,
       Prozessstart + Interpreter-Import) langsamer als der direkte
       node:sqlite-Zugriff.
  AC3  Entscheidung gegen die Umstellung (siehe PR-Begruendung): der veraltete
       Satz "Node hat vor 22.5 kein `node:sqlite`" steht weder im Modulkopf von
       `vault-bridge.mjs` noch in `docs/reference/hooks.md`, sobald die CI-Node-
       Version >=22 ist -- die alte Begruendung waere dann falsch.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
BRIDGE = REPO_ROOT / "hooks" / "lib" / "vault-bridge.mjs"
HOOKS_DOC = REPO_ROOT / "docs" / "reference" / "hooks.md"
BENCH_SCRIPT = REPO_ROOT / "scripts" / "dev" / "bench_vault_bridge.mjs"

STALE_SENTENCE = "Node hat vor 22.5 kein `node:sqlite`"

# node:sqlite ist ab 22.5.0 vorhanden (hinter --experimental-sqlite), der Flag
# faellt erst ab 22.13.0/23.4.0 weg (https://nodejs.org/api/sqlite.html). Die
# Node-Hooks werden von Claude Code direkt per `node datei.mjs` gestartet --
# ohne Moeglichkeit, einen Flag mitzugeben. Massgeblich ist daher die
# unflagged-Schwelle, nicht die reine Verfuegbarkeit.
MIN_NODE_MINOR_FOR_UNFLAGGED_SQLITE = 22


def _node_versions_in_ci() -> list[str]:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    return re.findall(r'node-version:\s*"([^"]+)"', text)


# ---------------------------------------------------------------------------
# AC1 -- CI-Node-Version angehoben
# ---------------------------------------------------------------------------


def test_ci_pins_node_22_or_newer_in_all_node_jobs():
    """Beide `setup-node`-Stellen in ci.yml zeigen auf Node >=22 (node:sqlite)."""
    versions = _node_versions_in_ci()
    assert len(versions) == 2, (
        f"Erwartet genau zwei node-version-Stellen (hook-syntax + python-tests), "
        f"gefunden: {versions}"
    )
    for raw in versions:
        major = int(raw.split(".")[0])
        assert major >= MIN_NODE_MINOR_FOR_UNFLAGGED_SQLITE, (
            f"node-version {raw!r} liegt unter Node {MIN_NODE_MINOR_FOR_UNFLAGGED_SQLITE} "
            "-- node:sqlite waere ohne --experimental-sqlite-Flag nicht nutzbar, und "
            "die Node-Hooks werden ohne Flag-Kontrolle per `node datei.mjs` gestartet."
        )


# ---------------------------------------------------------------------------
# AC2 -- Benchmark mit Median ueber mehrere Wiederholungen
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht installiert")
def test_benchmark_script_reports_median_over_multiple_reps(tmp_path):
    """Das Benchmark-Skript liefert Median-ms fuer beide Zugriffswege, reps > 1."""
    assert BENCH_SCRIPT.exists(), "scripts/dev/bench_vault_bridge.mjs fehlt"

    env = _bench_env()
    result = subprocess.run(
        ["node", str(BENCH_SCRIPT), "--reps", "5", "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    payload = json.loads(result.stdout)
    assert payload["reps"] >= 5, payload
    assert isinstance(payload["pythonSubprocessMedianMs"], (int, float))
    assert isinstance(payload["nodeSqliteMedianMs"], (int, float))
    assert payload["pythonSubprocessMedianMs"] > 0
    assert payload["nodeSqliteMedianMs"] > 0
    assert len(payload["pythonSubprocessSamplesMs"]) == payload["reps"]
    assert len(payload["nodeSqliteSamplesMs"]) == payload["reps"]

    # Strukturelle Erwartung, kein Einzelwert-Zufallstreffer: ein
    # Python-Subprozess kostet mindestens den Interpreter-Start (typischerweise
    # zwei- bis dreistellige ms), ein In-Process-Zugriff via node:sqlite nicht.
    assert payload["pythonSubprocessMedianMs"] > payload["nodeSqliteMedianMs"], (
        "Erwartet: Python-Subprozess misst langsamer als node:sqlite in-process -- "
        f"gemessen: {payload}"
    )


def _bench_env() -> dict[str, str]:
    import os

    venv_bin = REPO_ROOT / ".venv" / "bin"
    env = os.environ.copy()
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    env["ACADEMIC_PYTHON"] = sys.executable
    return env


# ---------------------------------------------------------------------------
# AC3 -- veraltete Begruendung ersetzt, sobald CI-Node >=22 ist
# ---------------------------------------------------------------------------


def test_stale_pre_225_reasoning_removed_from_bridge_header():
    """Der Modulkopf von vault-bridge.mjs behauptet nicht mehr, node:sqlite fehle."""
    text = BRIDGE.read_text(encoding="utf-8")
    assert STALE_SENTENCE not in text, (
        "vault-bridge.mjs behauptet weiterhin, Node habe vor 22.5 kein node:sqlite -- "
        "das ist seit dem CI-Bump (AC1) nicht mehr die aktuelle Begruendung."
    )
    # Die neue Begruendung muss trotzdem irgendwo stehen, sonst haengt der
    # Python-Pfad ohne Erklaerung in der Luft.
    assert "node:sqlite" in text, "Modulkopf erwaehnt node:sqlite gar nicht mehr"


def test_stale_pre_225_reasoning_removed_from_hooks_doc():
    """docs/reference/hooks.md wiederholt dieselbe veraltete Begruendung nicht."""
    text = HOOKS_DOC.read_text(encoding="utf-8")
    assert STALE_SENTENCE not in text, (
        "docs/reference/hooks.md wiederholt die veraltete node:sqlite-Begruendung "
        "aus vault-bridge.mjs -- Doku/Code-Divergenz (vgl. #616)."
    )
