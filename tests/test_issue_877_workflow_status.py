"""Tests fuer scripts/workflow_status.py (Issue #877).

Werten `academic_context.md` gegen `config/workflow-phases.json` aus: aktuelle
Phase (erste Phase mit unerfuellter Vorbedingung), erledigte Phasen, naechster
Schritt inkl. Ausloeser (Claude/Operator), Restkette bis 'export'. Jeder
Fehlerpfad (fehlende/kaputte Datei) degradiert lautlos -- kein Ausnahmefall
darf nach aussen dringen.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "workflow_status.py"
REAL_PHASES_PATH = REPO_ROOT / "config" / "workflow-phases.json"


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


def _real_phases() -> list[dict]:
    return json.loads(REAL_PHASES_PATH.read_text(encoding="utf-8"))["phases"]


def _real_context(
    *, gliederung: bool = False, literatur: bool = False, kapitel: bool = False
) -> str:
    def box(v: bool) -> str:
        return "x" if v else " "

    return f"""\
## Profil
- Universität: FH Leibniz Hannover

## Arbeit
- Thema: DevOps Governance in KMU
- Forschungsfrage: Welche Faktoren erklären DevOps-Adoption in KMU?

## Fortschritt
- [x] Thema festgelegt
- [x] Forschungsfrage formuliert
- [{box(gliederung)}] Gliederung steht
- [{box(literatur)}] Literatur gesammelt
- [{box(kapitel)}] Kapitel geschrieben
"""


class TestComputeStatusAgainstRealConfig:
    """Review-Fund (PR #930): die reale config/workflow-phases.json hat echte
    Mehrphasen-Kohorten -- mehrere aufeinanderfolgende Phasen mit identischer
    Vorbedingung (z. B. 'Gliederung steht: checked' gilt fuer sechs Phasen:
    literature-search, reading-list-import, book-acquisition, screening,
    source-quality-check, reading-notes). Eine Kohorte hat aber keine eigene,
    individuelle Abschluss-Evidenz je Mitglied -- die einzige verfuegbare
    Evidenz, dass die Kohorte tatsaechlich abgeschlossen ist (nicht nur
    betretbar), ist die Vorbedingung der naechsten, andersartigen Phase
    (hier: vault-querys 'Literatur gesammelt'). Ein Fix, der jede Phase nur
    gegen ihre EIGENE (geteilte) Vorbedingung prueft, haelt die ganze
    Kohorte faelschlich fuer erledigt, sobald deren gemeinsames Eintritts-Gate
    erfuellt ist -- die sechs Phasen 'fallen aus der Kette', weil das Tool
    sofort zu vault-query springt, obwohl keine der sechs Aktivitaeten
    stattgefunden hat.
    """

    def test_multi_phase_cohort_stays_undone_until_next_stage_precondition_met(self) -> None:
        phases = _real_phases()
        # Gliederung steht ist das GEMEINSAME Eintritts-Gate von sechs Phasen;
        # Literatur gesammelt (die Vorbedingung von vault-query, der ersten
        # Phase NACH der Kohorte) ist noch nicht erfuellt -- keine der sechs
        # Kohorten-Phasen darf schon als erledigt gelten.
        context = _real_context(gliederung=True, literatur=False, kapitel=False)
        status = ws.compute_status(context, phases)
        assert status is not None

        cohort_ids = [
            "literature-search",
            "reading-list-import",
            "book-acquisition",
            "screening",
            "source-quality-check",
            "reading-notes",
        ]
        done_ids = {p["id"] for p in status["done_phases"]}
        for phase_id in cohort_ids:
            assert phase_id not in done_ids, (
                f"{phase_id} faelschlich als erledigt markiert, obwohl 'Literatur "
                "gesammelt' (Vorbedingung der Folgephase vault-query) noch nicht "
                "erfuellt ist -- die Kohorte 'Gliederung steht' faellt aus der Kette."
            )
        assert status["current_phase"]["id"] == "literature-search", (
            "current_phase muss das erste Mitglied der noch nicht erledigten "
            f"Kohorte sein, ist aber {status['current_phase']['id']!r}."
        )
        # Positional muessen alle sechs trotzdem in der Restkette auftauchen.
        remaining_ids = [p["id"] for p in status["remaining_until_export"]]
        for phase_id in cohort_ids:
            assert phase_id in remaining_ids, f"{phase_id} fehlt in remaining_until_export."

    def test_multi_phase_cohort_becomes_done_once_next_stage_precondition_met(self) -> None:
        # Sobald 'Literatur gesammelt' (die Vorbedingung von vault-query, der
        # ersten Phase NACH der 'Gliederung steht'-Kohorte) erfuellt ist, ist
        # deren Arbeit nachweislich abgeschlossen -- jetzt duerfen alle sechs
        # Phasen als erledigt gelten.
        phases = _real_phases()
        context = _real_context(gliederung=True, literatur=True, kapitel=False)
        status = ws.compute_status(context, phases)
        done_ids = {p["id"] for p in status["done_phases"]}
        for phase_id in [
            "literature-search",
            "reading-list-import",
            "book-acquisition",
            "screening",
            "source-quality-check",
            "reading-notes",
        ]:
            assert phase_id in done_ids, f"{phase_id} sollte jetzt erledigt sein."
        # vault-query (Vorbedingung 'Literatur gesammelt: checked_partial',
        # ebenfalls erfuellt) ist damit ebenfalls erledigt.
        assert "vault-query" in done_ids
        # Die naechste Kohorte (study-comparison bis chapter-writing) teilt
        # sich 'Literatur gesammelt: checked' als EIGENE Vorbedingung -- die
        # ist zwar auch erfuellt, aber das ist wieder nur ihr Eintritts-Gate.
        # Abschluss-Evidenz ist erst 'Kapitel geschrieben' (Vorbedingung von
        # anti-ai-audit, der ersten Phase danach) -- die fehlt noch, also
        # bleibt study-comparison (das erste Mitglied dieser naechsten
        # Kohorte) die aktuelle Phase, nicht anti-ai-audit.
        assert status["current_phase"]["id"] == "study-comparison"
        for phase_id in ["scoring-and-excel-export", "literature-gap-analysis"]:
            assert phase_id not in done_ids, (
                f"{phase_id} faelschlich als erledigt markiert -- 'Kapitel "
                "geschrieben' (Vorbedingung der Folgephase anti-ai-audit) ist "
                "noch nicht erfuellt."
            )

    def test_downstream_cohort_becomes_done_once_final_stage_precondition_met(self) -> None:
        # Alles erfuellt (inkl. 'Kapitel geschrieben') -> auch die
        # study-comparison-Kohorte ist jetzt erledigt, current_phase wird
        # None (keine Kohorte bleibt offen).
        phases = _real_phases()
        context = _real_context(gliederung=True, literatur=True, kapitel=True)
        status = ws.compute_status(context, phases)
        assert status["current_phase"] is None
        assert len(status["done_phases"]) == len(phases)

    def test_no_real_phase_before_export_ever_disappears_from_the_chain(self) -> None:
        """Jede Phase bis einschliesslich 'export' muss in JEDEM Fortschritts-
        zustand entweder in done_phases, current_phase oder
        remaining_until_export auftauchen -- keine darf spurlos verschwinden.
        ('reproducible-freeze' liegt per Vertrag (Docstring) hinter 'export'
        und ist bewusst ausgenommen, siehe
        test_remaining_until_export_lists_phases_in_order_through_export.)
        """
        phases = _real_phases()
        all_ids_before_export = [
            p["id"] for p in phases[: [p["id"] for p in phases].index("export") + 1]
        ]
        for gliederung in (False, True):
            for literatur in (False, True):
                for kapitel in (False, True):
                    context = _real_context(
                        gliederung=gliederung, literatur=literatur, kapitel=kapitel
                    )
                    status = ws.compute_status(context, phases)
                    covered = {p["id"] for p in status["done_phases"]}
                    if status["current_phase"] is not None:
                        covered.add(status["current_phase"]["id"])
                    covered |= {p["id"] for p in status["remaining_until_export"]}
                    missing = set(all_ids_before_export) - covered
                    assert not missing, (
                        f"Zustand (gliederung={gliederung}, literatur={literatur}, "
                        f"kapitel={kapitel}): Phasen fehlen komplett aus der Kette: "
                        f"{sorted(missing)}"
                    )


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
