#!/usr/bin/env python3
"""Issue #877: Phasenstand von academic_context.md gegen
config/workflow-phases.json auswerten.

Gemeinsame Auswertungslogik fuer drei Konsumenten: den SessionStart-Block in
hooks/hooks.json (matcher==""), den Compaction-Block von
hooks/mid-session-reinforcement.mjs und den Skill skills/workflow-status.

Hinweis zur Verortung: der Plan-Kommentar des Issues nannte urspruenglich
.claude/hooks/inject-context.sh als Ziel -- das ist jedoch ein rein
repo-lokales Dev-Tool von flowkit fuer DIESES Repo (branch/dirty-files,
gestrandete Issues), nicht Teil des an Endnutzer ausgelieferten Plugins. Der
Issue-Body selbst beschreibt den SessionStart-Hook, der "nur das Python-Venv
und den Bypass-Log" prueft -- das ist eindeutig der Block in hooks/hooks.json
(venv-Check + bypass-log-report.mjs), der tatsaechlich mit ${CLAUDE_PLUGIN_ROOT}
in jedem Zielprojekt laeuft. Dort ist dieser Block verdrahtet.

Vertragslage (siehe AGENTS.md/Issue #877):
  - Jeder Fehlerpfad (fehlende/kaputte academic_context.md, fehlende/kaputte
    workflow-phases.json) degradiert lautlos -- keine Exception dringt nach
    aussen, exit 0 immer.
  - 'checked_partial' wird beim Auswerten von "erledigten Phasen" konservativ
    behandelt: nicht als erledigt gewertet, nur eine gesetzte Checkbox zaehlt
    (Learning #876: binaere Checkboxen kennen kein echtes "teilweise").
  - is_entry_point hat keine Eindeutigkeits-Garantie -- die Auswertung
    verlaesst sich nicht auf genau eine Startphase, sondern iteriert die
    Phasenliste schlicht in der gegebenen Reihenfolge.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXPORT_PHASE_ID = "export"


def load_context(path: Path) -> str | None:
    """Liest academic_context.md. None bei fehlender/unlesbarer Datei."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def load_phases(path: Path) -> list[dict] | None:
    """Liest config/workflow-phases.json. None bei fehlender/kaputter Datei
    oder wenn das erwartete 'phases'-Feld fehlt/kein Array ist."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    phases = data.get("phases") if isinstance(data, dict) else None
    if not isinstance(phases, list):
        return None
    return phases


def _field_satisfied(context_text: str, field: str, expected: str) -> bool:
    """Prueft eine einzelne Vorbedingung per Fliesstext-Match gegen den
    Kontext-Text -- kein YAML-Parsing, rein regelbasiertes Scannen (haelt den
    Weg robust gegen kaputtes Markdown/Frontmatter, statt daran zu scheitern).
    """
    escaped = re.escape(field)
    if expected == "filled":
        m = re.search(rf"-\s*{escaped}\s*:\s*(.+)", context_text)
        if not m:
            return False
        value = m.group(1).strip()
        return bool(value) and not value.upper().startswith("TODO")
    if expected in ("checked", "checked_partial"):
        # Binaere Checkbox: [x]/[X] = gesetzt. 'checked_partial' hat in der
        # realen Datei keine dritte Auspraegung -- konservativ wie 'checked'
        # behandelt (Learning #876).
        m = re.search(rf"-\s*\[([ xX])\]\s*{escaped}", context_text)
        return m is not None and m.group(1).strip().lower() == "x"
    return False


def _preconditions_satisfied(context_text: str, phase: dict) -> bool:
    preconditions = phase.get("preconditions") or []
    return all(
        _field_satisfied(context_text, cond["field"], cond["expected"])
        for cond in preconditions
        if "field" in cond and "expected" in cond
    )


def _trigger_for(phase: dict) -> str:
    """Wer loest den Schritt aus: 'Claude' bei einem selbst-aktivierenden
    Skill, sonst 'Operator' (expliziter Slash-Command oder direkter
    MCP-/Vault-Zugriff ohne eigenen Skill/Command)."""
    if phase.get("skills"):
        return "Claude"
    return "Operator"


def compute_status(context_text: str | None, phases: list[dict]) -> dict | None:
    """Kernauswertung. Gibt None zurueck, wenn kein Kontext vorhanden ist
    (AC2: kein academic_context.md -> keine Ausgabe statt einer Warnung).

    Rueckgabe bei vorhandenem Kontext:
      {
        "current_phase": dict | None,      # erste Phase mit unerfuellter Vorbedingung
        "done_phases": [dict, ...],        # alle Phasen davor
        "next_step": {..., "trigger": "Claude"|"Operator"} | None,
        "remaining_until_export": [dict, ...],  # current_phase .. 'export' inklusive
      }
    """
    if context_text is None:
        return None

    current_phase: dict | None = None
    done_phases: list[dict] = []
    for phase in phases:
        if _preconditions_satisfied(context_text, phase):
            done_phases.append(phase)
            continue
        current_phase = phase
        break

    next_step = None
    remaining_until_export: list[dict] = []
    if current_phase is not None:
        next_step = {
            "id": current_phase.get("id"),
            "title": current_phase.get("title"),
            "skills": current_phase.get("skills") or [],
            "commands": current_phase.get("commands") or [],
            "agents": current_phase.get("agents") or [],
            "trigger": _trigger_for(current_phase),
        }
        ids = [p.get("id") for p in phases]
        try:
            start_idx = ids.index(current_phase.get("id"))
        except ValueError:
            start_idx = len(phases)
        try:
            export_idx = ids.index(EXPORT_PHASE_ID)
        except ValueError:
            export_idx = -1
        if export_idx != -1 and start_idx <= export_idx:
            remaining_until_export = phases[start_idx : export_idx + 1]

    return {
        "current_phase": current_phase,
        "done_phases": done_phases,
        "next_step": next_step,
        "remaining_until_export": remaining_until_export,
    }


def _target_ref(phase: dict) -> str:
    """Kompakte Zustaendigkeits-Angabe: Skill, Command oder direkter Zugriff."""
    skills = phase.get("skills") or []
    commands = phase.get("commands") or []
    if skills:
        return "Skill: " + ", ".join(skills)
    if commands:
        return "Command: " + ", ".join(f"/{c}" for c in commands)
    return "direkter Zugriff (kein eigener Skill/Command)"


def format_lines(status: dict | None, full: bool = False) -> list[str]:
    """Formatiert den Status als flowkit-Zeilen fuer Hook/Skill-Ausgabe.
    Leere Liste, wenn kein Status vorhanden ist (AC2/AC3: keine Ausgabe)."""
    if status is None:
        return []

    lines: list[str] = []
    current = status.get("current_phase")
    if current is None:
        lines.append("[flowkit] Phase: alle Phasen bis Export abgeschlossen")
        return lines

    lines.append(f"[flowkit] Phase: {current.get('title')}")
    next_step = status.get("next_step")
    if next_step is not None:
        lines.append(
            f"[flowkit] Naechster Schritt: {next_step['title']} "
            f"({_target_ref(current)}) — ausgeloest von: {next_step['trigger']}"
        )

    if full:
        remaining = status.get("remaining_until_export") or []
        if remaining:
            lines.append("[flowkit] Verbleibend bis Export:")
            for phase in remaining:
                trigger = _trigger_for(phase)
                lines.append(
                    f"  - {phase.get('title')} ({_target_ref(phase)}, ausgeloest von: {trigger})"
                )

    return lines


def main(argv: list[str] | None = None) -> int:
    """CLI-Einstieg. Degradiert bei JEDEM Fehler lautlos (leere Ausgabe,
    exit 0) -- SessionStart-Hooks duerfen nie blockieren oder Fehler zeigen."""
    try:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--project-dir", default=".")
        parser.add_argument("--plugin-root", default=None)
        parser.add_argument("--context-file", default=None)
        parser.add_argument("--phases-file", default=None)
        parser.add_argument("--full", action="store_true")
        args = parser.parse_args(argv)

        project_dir = Path(args.project_dir)
        context_path = (
            Path(args.context_file) if args.context_file else project_dir / "academic_context.md"
        )
        if args.phases_file:
            phases_path = Path(args.phases_file)
        elif args.plugin_root:
            phases_path = Path(args.plugin_root) / "config" / "workflow-phases.json"
        else:
            phases_path = Path("config") / "workflow-phases.json"

        context_text = load_context(context_path)
        if context_text is None:
            return 0

        phases = load_phases(phases_path)
        if phases is None:
            return 0

        status = compute_status(context_text, phases)
        for line in format_lines(status, full=args.full):
            print(line)
        return 0
    except Exception:  # noqa: BLE001 - Fail-silent ist hier die Spezifikation
        return 0


if __name__ == "__main__":
    sys.exit(main())
