"""Tests fuer scripts/workflow_status.py (Issue #877).

Werten `academic_context.md` gegen `config/workflow-phases.json` aus: aktuelle
Phase (erste Phase mit unerfuellter Eintrittsbedingung), deren Position in
der Kette, naechster Schritt inkl. Ausloeser (Claude/Operator), Restkette
bis 'export'. Jeder Fehlerpfad (fehlende/kaputte Datei) degradiert lautlos --
kein Ausnahmefall darf nach aussen dringen.

Bewusst reduzierter Geltungsbereich (Convergence-Alert auf PR #930, Issue
#946): config/workflow-phases.json modelliert nur Eintrittsbedingungen, kein
Abschlusskriterium. compute_status() behauptet deshalb NICHT, dass Phasen vor
current_phase "erledigt" sind -- `phases_before_current` ist eine reine
Positionsangabe. Echte Abschlusserkennung ist Issue #946.
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
    def test_partial_context_identifies_current_phase_and_phases_before_it(self) -> None:
        status = ws.compute_status(PARTIAL_CONTEXT, PHASES)
        assert status is not None
        # Universität gefuellt -> topic-finding-Vorbedingung erfuellt, Thema
        # gefuellt -> research-question-Vorbedingung erfuellt, "Gliederung
        # steht" nicht angehakt -> literature-search ist die erste offene Phase.
        assert status["current_phase"]["id"] == "literature-search"
        assert [p["id"] for p in status["phases_before_current"]] == [
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
        assert [p["id"] for p in status["phases_before_current"]] == ["context-setup"]

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

    def test_checked_partial_precondition_keeps_vault_query_as_current_phase(self) -> None:
        # "Literatur gesammelt" ist NICHT angehakt -> vault-query bleibt die
        # aktuelle Phase, taucht also nicht in phases_before_current auf (es
        # liegt nicht davor, es IST die aktuelle Phase).
        context = PARTIAL_CONTEXT.replace("- [ ] Gliederung steht", "- [x] Gliederung steht")
        status = ws.compute_status(context, PHASES)
        assert status["current_phase"]["id"] == "vault-query"
        assert "vault-query" not in [p["id"] for p in status["phases_before_current"]]

    def test_remaining_until_export_lists_phases_in_order_through_export(self) -> None:
        status = ws.compute_status(PARTIAL_CONTEXT, PHASES)
        ids = [p["id"] for p in status["remaining_until_export"]]
        assert ids == ["literature-search", "vault-query", "export"]
        # reproducible-freeze liegt hinter 'export' -> nicht mehr enthalten.
        assert "reproducible-freeze" not in ids

    def test_all_preconditions_satisfied_yields_no_current_phase(self) -> None:
        # Keine Phase hat mehr eine unerfuellte Eintrittsbedingung -- das
        # sagt nur "current_phase wird None", NICHT "alles ist erledigt"
        # (#946: kein Abschlusskriterium im Modell).
        all_satisfied = (
            PARTIAL_CONTEXT.replace("- [ ] Gliederung steht", "- [x] Gliederung steht")
            .replace("- [ ] Literatur gesammelt", "- [x] Literatur gesammelt")
            .replace("- [ ] Kapitel geschrieben", "- [x] Kapitel geschrieben")
        )
        status = ws.compute_status(all_satisfied, PHASES)
        assert status["current_phase"] is None
        assert status["next_step"] is None
        assert status["remaining_until_export"] == []
        assert [p["id"] for p in status["phases_before_current"]] == [p["id"] for p in PHASES]


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
    """Reduzierter Geltungsbereich nach Convergence-Alert auf PR #930 (Issue
    #946): die reale config/workflow-phases.json hat echte Mehrphasen-
    Kohorten -- mehrere aufeinanderfolgende Phasen mit identischer
    Vorbedingung (z. B. teilen sich sechs Phasen -- literature-search bis
    reading-notes -- das Eintritts-Gate 'Gliederung steht: checked'). Eine
    Kohorte hat keine individuelle Abschluss-Evidenz je Mitglied; eine
    erfuellte (geteilte) Eintrittsbedingung belegt nur "betretbar", nicht
    "die Arbeit ist getan". Mehrere Anlaeufe, das ueber Kohorten-Logik
    nachzumodellieren, haben in Review-Runden wiederholt neue Bruchstellen
    aufgedeckt (Kohorten selbst, dann Einzelphasen, dann Kettenende).

    compute_status() behauptet deshalb ab jetzt bewusst NICHTS mehr ueber
    "erledigt" -- phases_before_current ist eine reine Positionsangabe
    (Phasen, die in phases[] vor current_phase stehen), keine Abschluss-
    Behauptung. Diese Tests laufen weiterhin gegen die ECHTE Config (nicht
    nur die 7-Phasen-Testfixture) und belegen genau das: keine Phase gilt
    hier je als "erledigt", weil dieses Konzept aus der Funktion entfernt
    wurde. Echte Abschlusserkennung mit eigenen Belegen ist Issue #946.
    """

    def test_status_has_no_completion_claiming_field(self) -> None:
        """Es gibt kein 'done_phases'/'completed'-Feld mehr -- nur die reine
        Positionsangabe 'phases_before_current'."""
        phases = _real_phases()
        context = _real_context(gliederung=True, literatur=False, kapitel=False)
        status = ws.compute_status(context, phases)
        assert status is not None
        assert set(status.keys()) == {
            "current_phase",
            "phases_before_current",
            "next_step",
            "remaining_until_export",
        }
        assert "done_phases" not in status

    def test_current_phase_is_first_phase_with_unmet_precondition_across_a_shared_gate(
        self,
    ) -> None:
        """Sechs Phasen teilen sich die Eintrittsbedingung 'Gliederung steht:
        checked'. Ist sie erfuellt, hat jede der sechs -- individuell
        geprueft -- eine erfuellte EIGENE Eintrittsbedingung; current_phase
        wandert deshalb korrekt bis zur naechsten Phase mit einer ANDEREN,
        noch unerfuellten Eintrittsbedingung (vault-query, 'Literatur
        gesammelt'). Das ist keine Abschluss-Behauptung ueber die sechs
        Phasen -- nur, dass ihre eigene Eintrittsbedingung erfuellt ist."""
        phases = _real_phases()
        context = _real_context(gliederung=True, literatur=False, kapitel=False)
        status = ws.compute_status(context, phases)
        assert status["current_phase"]["id"] == "vault-query"

        cohort_ids = [
            "literature-search",
            "reading-list-import",
            "book-acquisition",
            "screening",
            "source-quality-check",
            "reading-notes",
        ]
        before_ids = [p["id"] for p in status["phases_before_current"]]
        for phase_id in cohort_ids:
            assert phase_id in before_ids, (
                f"{phase_id} sollte in phases_before_current stehen (reine "
                "Positionsangabe -- es liegt vor vault-query in der Kette)."
            )

    def test_phases_before_current_is_exactly_the_positional_slice(self) -> None:
        """phases_before_current ist ausschliesslich eine Positionsangabe:
        exakt phases[:index(current_phase)] -- keine Kohorten-Sonderlogik,
        keine Abschluss-Pruefung."""
        phases = _real_phases()
        ids = [p["id"] for p in phases]
        for gliederung, literatur, kapitel in [
            (False, False, False),
            (True, False, False),
            (True, True, False),
            (True, True, True),
        ]:
            context = _real_context(gliederung=gliederung, literatur=literatur, kapitel=kapitel)
            status = ws.compute_status(context, phases)
            current = status["current_phase"]
            expected_index = ids.index(current["id"]) if current is not None else len(phases)
            assert [p["id"] for p in status["phases_before_current"]] == ids[:expected_index]

    def test_no_real_phase_before_export_ever_disappears_from_the_chain(self) -> None:
        """Jede Phase bis einschliesslich 'export' muss in JEDEM Fortschritts-
        zustand entweder in phases_before_current, current_phase oder
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
                    covered = {p["id"] for p in status["phases_before_current"]}
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

    def test_no_current_phase_does_not_claim_completion(self) -> None:
        """#946: keine offene Eintrittsbedingung mehr gefunden ist NICHT
        dasselbe wie 'alles erledigt/abgeschlossen' -- die Ausgabe darf das
        nicht behaupten."""
        all_satisfied = (
            PARTIAL_CONTEXT.replace("- [ ] Gliederung steht", "- [x] Gliederung steht")
            .replace("- [ ] Literatur gesammelt", "- [x] Literatur gesammelt")
            .replace("- [ ] Kapitel geschrieben", "- [x] Kapitel geschrieben")
        )
        status = ws.compute_status(all_satisfied, PHASES)
        lines = ws.format_lines(status, full=False)
        assert len(lines) == 1
        assert "keine offene Eintrittsbedingung" in lines[0]
        joined = "\n".join(lines).lower()
        assert "erledigt" not in joined
        assert "abgeschlossen" not in joined


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
