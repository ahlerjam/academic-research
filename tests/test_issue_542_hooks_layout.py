"""Akzeptanz-Guards fuer Issue #542 — ``hooks/`` sauber nach Rolle getrennt.

Befund der Review-Runde zu PR #555 (zwei Symptome, EINE Ursache):

* AC1 verfehlt: ``hooks/vault-bridge.mjs`` lag weiter flach in ``hooks/``,
  obwohl der eigene Dateikopf sie als "KEIN Hook" ausweist — also dieselbe
  Kategorie wie die bereits verschobenen ``citation-*.mjs``.
* AC2 verfehlt: der stehende CI-Gate (``.github/workflows/ci.yml``, Job
  ``hook-syntax``) iterierte ueber den **nicht-rekursiven** Shell-Glob
  ``hooks/*.mjs``. Nach dem Move waren ``hooks/lib/*.mjs`` ungeprueft.

Ursache beider Symptome ist derselbe Glob: sein fehlendes Rekursions-Verhalten
war laut Dateikopf sogar die ausdrueckliche Begruendung dafuer, dass
``vault-bridge.mjs`` NICHT nach ``hooks/lib/`` durfte. Das Gate diktierte das
Verzeichnislayout statt ihm zu folgen.

Fix-Richtung: ein rekursiver, driftfester Gate ueber **alle** getrackten
``*.mjs`` (Vorbild: ``scripts/dev/check-shell-syntax.sh`` aus #469), danach
kann ``vault-bridge.mjs`` zu den uebrigen Bibliotheken.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
HOOKS_JSON = HOOKS_DIR / "hooks.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GATE_SCRIPT = REPO_ROOT / "scripts" / "dev" / "check-mjs-syntax.sh"
AGENTS_MD = REPO_ROOT / "AGENTS.md"

_NODE_MISSING = shutil.which("node") is None


def _tracked_mjs() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.mjs"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(line for line in out.splitlines() if line.strip())


def _registered_mjs() -> set[str]:
    """Basenamen aller in hooks.json per ``node ...`` verdrahteten .mjs-Dateien."""
    raw = HOOKS_JSON.read_text(encoding="utf-8")
    json.loads(raw)  # Manifest muss valide bleiben
    return set(re.findall(r"([A-Za-z0-9_.-]+\.mjs)", raw))


# --------------------------------------------------------------------------
# AC1 — Top-Level hooks/*.mjs = exakt die registrierten Hooks
# --------------------------------------------------------------------------


def test_toplevel_mjs_are_exactly_the_registered_hooks() -> None:
    """Flach in ``hooks/`` liegt nur, was ``hooks.json`` auch startet."""
    toplevel = {p.name for p in HOOKS_DIR.glob("*.mjs")}
    registered = _registered_mjs()
    assert toplevel == registered, (
        "Top-Level-.mjs und in hooks.json registrierte Hooks weichen ab.\n"
        f"  nur flach in hooks/: {sorted(toplevel - registered)}\n"
        f"  nur in hooks.json:   {sorted(registered - toplevel)}\n"
        "Importierte Module gehoeren nach hooks/lib/."
    )


def test_vault_bridge_lives_in_hooks_lib() -> None:
    """vault-bridge.mjs ist ein importiertes Modul, kein Hook (#527)."""
    assert (HOOKS_DIR / "lib" / "vault-bridge.mjs").is_file(), (
        "hooks/lib/vault-bridge.mjs fehlt — importierte Module gehoeren nach hooks/lib/."
    )
    assert not (HOOKS_DIR / "vault-bridge.mjs").exists(), (
        "hooks/vault-bridge.mjs liegt weiter flach in hooks/, obwohl sie kein Hook ist."
    )


@pytest.mark.skipif(_NODE_MISSING, reason="node nicht verfuegbar")
def test_vault_bridge_still_resolves_the_plugin_root() -> None:
    """``VAULT_SRC`` zeigt nach dem Move weiter auf die Plugin-Wurzel.

    Regressionsgefahr: ``VAULT_SRC`` wird aus dem eigenen Dateipfad abgeleitet
    (``dirname(HOOK_DIR)``). Eine Verzeichnisebene tiefer zeigt dieselbe Formel
    auf ``hooks/`` statt auf die Wurzel — exakt der Fehler, der in dieser PR
    schon einmal fuer ``onboard-project-uni-prompt.sh`` korrigiert werden
    musste. Der Pfad landet zur Laufzeit in ``sys.path``; ist er falsch, faellt
    der Import von ``academic_vault`` in beiden Hooks lautlos aus.
    """
    bridge = HOOKS_DIR / "lib" / "vault-bridge.mjs"
    if not bridge.is_file():  # pragma: no cover - von obigem Test abgedeckt
        pytest.fail("hooks/lib/vault-bridge.mjs fehlt")
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            f"import {{ VAULT_SRC }} from {json.dumps(bridge.as_uri())};"
            "process.stdout.write(VAULT_SRC);",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Import von VAULT_SRC fehlgeschlagen: {result.stderr}"
    vault_src = Path(result.stdout.strip())
    assert (vault_src / "academic_vault" / "__init__.py").is_file(), (
        f"VAULT_SRC={vault_src} ist nicht die Plugin-Wurzel — das Paket "
        "academic_vault liegt dort nicht. Pfadableitung nach dem Move nicht nachgezogen."
    )


def test_hooks_json_only_references_toplevel_hooks() -> None:
    """hooks.json startet keine Datei aus hooks/lib/."""
    raw = HOOKS_JSON.read_text(encoding="utf-8")
    assert "hooks/lib/" not in raw, (
        "hooks.json referenziert hooks/lib/ — Bibliotheken werden importiert, nicht gestartet."
    )


# --------------------------------------------------------------------------
# AC2 — der Syntax-Gate erfasst ALLE .mjs, auch unterhalb von hooks/lib/
# --------------------------------------------------------------------------


def test_gate_script_exists_and_is_executable_by_bash() -> None:
    assert GATE_SCRIPT.is_file(), (
        "scripts/dev/check-mjs-syntax.sh fehlt — der rekursive Syntax-Gate "
        "(Vorbild: scripts/dev/check-shell-syntax.sh, #469)."
    )
    syntax = subprocess.run(
        ["bash", "-n", str(GATE_SCRIPT)], capture_output=True, text=True, timeout=30
    )
    assert syntax.returncode == 0, f"bash -n fehlgeschlagen: {syntax.stderr}"


@pytest.mark.skipif(_NODE_MISSING, reason="node nicht verfuegbar")
def test_gate_covers_every_tracked_mjs_file() -> None:
    """Der Gate prueft jede getrackte .mjs — auch die unter hooks/lib/."""
    tracked = _tracked_mjs()
    assert any(f.startswith("hooks/lib/") for f in tracked), (
        "Vorbedingung verletzt: keine .mjs unterhalb von hooks/lib/ — "
        "der Test wuerde die Regression nicht mehr fangen."
    )
    result = subprocess.run(
        ["bash", str(GATE_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"Syntax-Gate rot: {result.stdout}\n{result.stderr}"
    match = re.search(r"OK: (\d+) ", result.stdout)
    assert match, f"Gate meldet keine Anzahl geprueffter Dateien: {result.stdout!r}"
    assert int(match.group(1)) == len(tracked), (
        f"Gate prueft {match.group(1)} Dateien, getrackt sind aber {len(tracked)}: {tracked}"
    )


@pytest.mark.skipif(_NODE_MISSING, reason="node nicht verfuegbar")
def test_gate_detects_a_broken_mjs_in_a_subdirectory(tmp_path: Path) -> None:
    """Der Gate faellt bei kaputter Syntax um — und zwar auch rekursiv."""
    nested = tmp_path / "hooks" / "lib"
    nested.mkdir(parents=True)
    (tmp_path / "hooks" / "fine.mjs").write_text("export const ok = 1;\n", encoding="utf-8")
    (nested / "broken.mjs").write_text("export const = ;\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(GATE_SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0, (
        "Gate meldet Erfolg, obwohl hooks/lib/broken.mjs Syntaxfehler hat "
        f"(rekursive Erfassung fehlt?): {result.stdout}"
    )
    assert "broken.mjs" in result.stdout, f"Gate nennt die kaputte Datei nicht: {result.stdout!r}"


def test_gate_fails_loudly_when_it_finds_nothing(tmp_path: Path) -> None:
    """Ein leerer Scope ist ein Fehlkonfigurations-Signal, kein Erfolg."""
    result = subprocess.run(
        ["bash", str(GATE_SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, (
        "Gate meldet Erfolg, obwohl er keine einzige .mjs gefunden hat — "
        "genau so bleibt ein Coverage-Verlust still."
    )


def test_ci_job_delegates_to_the_gate_script() -> None:
    """ci.yml ruft den Gate auf, statt einen eigenen Glob zu bauen."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/dev/check-mjs-syntax.sh" in text, (
        "Job hook-syntax in ci.yml nutzt den rekursiven Gate nicht."
    )
    assert "for f in hooks/*.mjs" not in text, (
        "ci.yml iteriert weiter ueber den nicht-rekursiven Glob 'hooks/*.mjs' — "
        "hooks/lib/*.mjs bleiben ungeprueft."
    )


def test_docs_do_not_advertise_the_non_recursive_glob() -> None:
    """AGENTS.md und docs/development.md nennen den rekursiven Befehl."""
    stale = []
    for rel in ("AGENTS.md", "docs/development.md", "docs/reference/hooks.md"):
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        if "node --check hooks/*.mjs" in path.read_text(encoding="utf-8"):
            stale.append(rel)
    assert not stale, (
        f"Diese Dateien empfehlen weiter den nicht-rekursiven Glob: {stale}. "
        "Referenzbefehl ist bash scripts/dev/check-mjs-syntax.sh."
    )
    assert "scripts/dev/check-mjs-syntax.sh" in AGENTS_MD.read_text(encoding="utf-8"), (
        "AGENTS.md nennt den Syntax-Gate-Befehl nicht."
    )
