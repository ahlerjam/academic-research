"""Tests fuer scripts/workflow_status.py (Issue #877).

Werten `academic_context.md` gegen `config/workflow-phases.json` aus: aktuelle
Phase (erste Phase mit unerfuellter Vorbedingung), erledigte Phasen, naechster
Schritt inkl. Ausloeser (Claude/Operator), Restkette bis 'export'. Jeder
Fehlerpfad (fehlende/kaputte Datei) degradiert lautlos -- kein Ausnahmefall
darf nach aussen dringen.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "workflow_status.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("workflow_status", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["workflow_status"] = module
    spec.loader.exec_module(module)
    return module


ws = _load_module()

# Minimale Phasenkette fuer isolierte Tests (unabhaengig von der realen Datei,
# damit der Test nicht bricht, wenn #876 die echte Datei aendert).
PHASES = [
    {
        "id": "context-setup",
        "title": "Kontext einrichten",
        "is_entry_point": True,
        "preconditions": [],
        "skills": ["academic-context"],
        "commands": [],
        "agents": [],
    },
    {
        "id": "topic-finding",
        "title": "Thema finden",
        "is_entry_point": False,
        "preconditions": [{"field": "Universität", "expected": "filled"}],
        "skills": ["topic-brainstorm"],
        "commands": [],
        "agents": [],
    },
    {
        "id": "research-question",
        "title": "Forschungsfrage schärfen",
        "is_entry_point": False,
        "preconditions": [{"field": "Thema", "expected": "filled"}],
        "skills": ["research-question-refiner"],
        "commands": [],
        "agents": [],
    },
    {
        "id": "literature-search",
        "title": "Literatur suchen",
        "is_entry_point": False,
        "preconditions": [{"field": "Gliederung steht", "expected": "checked"}],
        "skills": [],
        "commands": ["search"],
        "agents": [],
    },
    {
        "id": "vault-query",
        "title": "Vault abfragen",
        "is_entry_point": False,
        "preconditions": [{"field": "Literatur gesammelt", "expected": "checked_partial"}],
        "skills": [],
        "commands": [],
        "agents": [],
    },
    {
        "id": "export",
        "title": "Exportieren",
        "is_entry_point": False,
        "preconditions": [{"field": "Kapitel geschrieben", "expected": "checked"}],
        "skills": [],
        "commands": ["latex", "word", "slides"],
        "agents": [],
    },
    {
        "id": "reproducible-freeze",
        "title": "Abgabe reproduzierbar einfrieren",
        "is_entry_point": False,
        "preconditions": [{"field": "Kapitel geschrieben", "expected": "checked"}],
        "skills": ["material-passport"],
        "commands": [],
        "agents": [],
    },
]

PARTIAL_CONTEXT = """\
## Profil
- Universität: TU Beispiel
- Studiengang: TODO

## Arbeit
- Thema: Governance in DevOps-Teams
- Forschungsfrage: TODO

## Gliederung
TODO

## Fortschritt
- [ ] Thema festgelegt
- [ ] Forschungsfrage formuliert
- [ ] Gliederung steht
- [ ] Literatur gesammelt
- [ ] Kapitel geschrieben
"""

FRESH_STUB_CONTEXT = """\
## Profil
- Universität: TODO (Default: Leibniz FH Hannover)

## Arbeit
- Thema: TODO
"""


class TestComputeStatus:
    def test_partial_context_identifies_current_phase_and_done_phases(self) -> None:
        status = ws.compute_status(PARTIAL_CONTEXT, PHASES)
        assert status is not None
        # Universität gefuellt -> topic-finding-Vorbedingung erfuellt, Thema
        # gefuellt -> research-question-Vorbedingung erfuellt, "Gliederung
        # steht" nicht angehakt -> literature-search ist die erste offene Phase.
        assert status["current_phase"]["id"] == "literature-search"
        assert [p["id"] for p in status["done_phases"]] == [
            "context-setup",
            "topic-finding",
            "research-question",
        ]

    def test_no_context_returns_none(self) -> None:
        assert ws.compute_status(None, PHASES) is None

    def test_fresh_stub_stops_at_second_phase(self) -> None:
        status = ws.compute_status(FRESH_STUB_CONTEXT, PHASES)
        assert status is not None
        assert status["current_phase"]["id"] == "topic-finding"
        assert [p["id"] for p in status["done_phases"]] == ["context-setup"]

    def test_garbled_context_does_not_raise_and_yields_conservative_result(self) -> None:
        garbled = "\x00\x01 not markdown at all {{{ ]]] üöä \n\n---"
        status = ws.compute_status(garbled, PHASES)
        assert status is not None
        assert status["current_phase"]["id"] == "topic-finding"

    def test_next_step_trigger_is_claude_when_skill_present(self) -> None:
        status = ws.compute_status(FRESH_STUB_CONTEXT, PHASES)
        assert status["next_step"]["trigger"] == "Claude"
        assert status["next_step"]["id"] == "topic-finding"

    def test_next_step_trigger_is_operator_when_only_command_present(self) -> None:
        status = ws.compute_status(PARTIAL_CONTEXT, PHASES)
        assert status["next_step"]["trigger"] == "Operator"
        assert status["next_step"]["id"] == "literature-search"

    def test_next_step_trigger_is_operator_when_neither_skill_nor_command(self) -> None:
        # vault-query hat weder skills noch commands -> direkter MCP-Zugriff,
        # Ausloeser bleibt Operator.
        vault_only_context = PARTIAL_CONTEXT.replace(
            "- [ ] Gliederung steht", "- [x] Gliederung steht"
        )
        status = ws.compute_status(vault_only_context, PHASES)
        assert status["current_phase"]["id"] == "vault-query"
        assert status["next_step"]["trigger"] == "Operator"

    def test_checked_partial_is_not_treated_as_fully_done(self) -> None:
        # "Literatur gesammelt" ist NICHT angehakt -> vault-query bleibt die
        # aktuelle Phase, wird nicht faelschlich als erledigt gewertet.
        context = PARTIAL_CONTEXT.replace("- [ ] Gliederung steht", "- [x] Gliederung steht")
        status = ws.compute_status(context, PHASES)
        assert status["current_phase"]["id"] == "vault-query"
        assert "vault-query" not in [p["id"] for p in status["done_phases"]]

    def test_remaining_until_export_lists_phases_in_order_through_export(self) -> None:
        status = ws.compute_status(PARTIAL_CONTEXT, PHASES)
        ids = [p["id"] for p in status["remaining_until_export"]]
        assert ids == ["literature-search", "vault-query", "export"]
        # reproducible-freeze liegt hinter 'export' -> nicht mehr enthalten.
        assert "reproducible-freeze" not in ids

    def test_all_phases_satisfied_yields_no_current_phase(self) -> None:
        all_done = (
            PARTIAL_CONTEXT.replace("- [ ] Gliederung steht", "- [x] Gliederung steht")
            .replace("- [ ] Literatur gesammelt", "- [x] Literatur gesammelt")
            .replace("- [ ] Kapitel geschrieben", "- [x] Kapitel geschrieben")
        )
        status = ws.compute_status(all_done, PHASES)
        assert status["current_phase"] is None
        assert status["next_step"] is None
        assert status["remaining_until_export"] == []


class TestFormatLines:
    def test_no_status_yields_no_lines(self) -> None:
        assert ws.format_lines(None) == []

    def test_default_mode_names_phase_and_next_step(self) -> None:
        status = ws.compute_status(PARTIAL_CONTEXT, PHASES)
        lines = ws.format_lines(status, full=False)
        assert any(
            line.startswith("[flowkit] Phase:") and "Literatur suchen" in line for line in lines
        )
        assert any(
            line.startswith("[flowkit] Naechster Schritt:") and "Operator" in line for line in lines
        )

    def test_full_mode_lists_remaining_phases_through_export(self) -> None:
        status = ws.compute_status(PARTIAL_CONTEXT, PHASES)
        lines = ws.format_lines(status, full=True)
        joined = "\n".join(lines)
        assert "Literatur suchen" in joined
        assert "Vault abfragen" in joined
        assert "Exportieren" in joined
        assert "Abgabe reproduzierbar einfrieren" not in joined


class TestLoadHelpers:
    def test_load_phases_returns_none_on_broken_json(self, tmp_path) -> None:
        bad = tmp_path / "workflow-phases.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert ws.load_phases(bad) is None

    def test_load_phases_returns_none_when_missing(self, tmp_path) -> None:
        assert ws.load_phases(tmp_path / "nope.json") is None

    def test_load_context_returns_none_when_missing(self, tmp_path) -> None:
        assert ws.load_context(tmp_path / "academic_context.md") is None

    def test_load_context_reads_existing_file(self, tmp_path) -> None:
        f = tmp_path / "academic_context.md"
        f.write_text(PARTIAL_CONTEXT, encoding="utf-8")
        assert ws.load_context(f) == PARTIAL_CONTEXT


class TestMainCli:
    def _write_fixture_repo(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "academic_context.md").write_text(PARTIAL_CONTEXT, encoding="utf-8")
        config_dir = tmp_path / "plugin" / "config"
        config_dir.mkdir(parents=True)
        import json

        (config_dir / "workflow-phases.json").write_text(
            json.dumps({"phases": PHASES}), encoding="utf-8"
        )
        return project, tmp_path / "plugin"

    def test_cli_exits_zero_and_prints_status(self, tmp_path, capsys) -> None:
        project, plugin_root = self._write_fixture_repo(tmp_path)
        rc = ws.main(["--project-dir", str(project), "--plugin-root", str(plugin_root)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "[flowkit] Phase:" in out

    def test_cli_never_raises_on_missing_context(self, tmp_path, capsys) -> None:
        project = tmp_path / "empty_project"
        project.mkdir()
        config_dir = tmp_path / "plugin" / "config"
        config_dir.mkdir(parents=True)
        import json

        (config_dir / "workflow-phases.json").write_text(
            json.dumps({"phases": PHASES}), encoding="utf-8"
        )
        rc = ws.main(["--project-dir", str(project), "--plugin-root", str(tmp_path / "plugin")])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == ""

    def test_cli_never_raises_on_missing_phases_file(self, tmp_path, capsys) -> None:
        project, _ = self._write_fixture_repo(tmp_path)
        rc = ws.main(["--project-dir", str(project), "--plugin-root", str(tmp_path / "no-plugin")])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == ""

    def test_cli_full_flag_lists_remaining_chain(self, tmp_path, capsys) -> None:
        project, plugin_root = self._write_fixture_repo(tmp_path)
        rc = ws.main(["--project-dir", str(project), "--plugin-root", str(plugin_root), "--full"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Exportieren" in out
