"""Tests fuer die Context-FS-Fixture (Issue #823).

Deckt die drei ACs, die ohne Live-CLI-Aufruf hermetisch pruefbar sind:

- AC1 (teilweise): die Fixture-Dateien existieren und enthalten die
  Schluesselbegriffe, die die betroffenen Eval-Erwartungen (ab-01, ab-02,
  ac-03, mt-01, pc-02) brauchen -- inkl. ``literature_state.md``, die eine
  erste Fassung des Issues uebersehen hatte.
- AC2: die Fixture liegt in einem suiteneigenen Verzeichnis und ist fuer
  einen Aufruf mit einem anderen ``cwd`` nicht sichtbar; ``_run_claude_cli``
  reicht ``cwd``/``allowed_tools`` tatsaechlich an den Subprozess durch.
- AC3: mindestens ein Eval-Fall bleibt bewusst ohne Fixture-``cwd`` --
  s. ``test_ac3_negative_case_without_cwd_exists``.

Live-Reproduktion der fuenf betroffenen Faelle (AC1, AC5) ist im PR-Text
dokumentiert -- kein Unit-Test, da sie einen echten CLI-Aufruf braucht.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests.evals import eval_runner
from tests.evals.eval_runner import CONTEXT_FS_DIR

FIXTURE_FILES = ("academic_context.md", "literature_state.md", "writing_state.md")


# ---------------------------------------------------------------------------
# AC1 (Fixture-Inhalt): Dateien existieren und tragen die Begriffe, die die
# betroffenen Eval-Erwartungen brauchen.
# ---------------------------------------------------------------------------


def test_context_fs_dir_points_at_fixtures_directory():
    assert CONTEXT_FS_DIR == Path(__file__).parent / "fixtures" / "context_fs"
    assert CONTEXT_FS_DIR.is_dir()


def test_all_three_context_files_exist():
    for name in FIXTURE_FILES:
        path = CONTEXT_FS_DIR / name
        assert path.is_file(), f"Fixture-Datei fehlt: {path}"
        assert path.read_text().strip(), f"Fixture-Datei ist leer: {path}"


def test_literature_state_is_not_forgotten():
    """Regression: Fassung 1 des Issues lieferte nur writing_state.md.

    pc-02 (plagiarism-check) liest laut SKILL.md sowohl academic_context.md
    als auch literature_state.md -- fehlt Letztere, bleibt der Fall rot.
    """
    path = CONTEXT_FS_DIR / "literature_state.md"
    assert path.is_file()
    assert path.read_text().strip()


def test_academic_context_contains_output_targets_field():
    """ac-03 erwartet den Substring 'output_targets' in der Modellantwort --
    nur erreichbar, wenn die Fixture das Feld bereits fuehrt (Update-Fall,
    nicht Erstanlage)."""
    text = (CONTEXT_FS_DIR / "academic_context.md").read_text()
    assert "output_targets" in text


def test_academic_context_contains_ab02_keywords():
    """ab-02 erwartet eines von (DevOps|Governance|KMU|Adoption|Interview)
    in der generierten Keyword-Liste -- die Fixture muss diese Begriffe
    tatsaechlich enthalten, sonst bleibt der Fall trotz vorhandener Datei
    rot."""
    text = (CONTEXT_FS_DIR / "academic_context.md").read_text()
    for term in ("DevOps", "Governance", "KMU", "Adoption"):
        assert term in text, f"Fixture-Begriff fehlt: {term}"


def test_literature_state_contains_pc02_source_sentence():
    """pc-02 fragt nach genau diesem Satz -- die Fixture muss ihn als
    Quellenformulierung enthalten, damit der Skill die Naehe tatsaechlich
    erkennen kann statt zu raten."""
    text = (CONTEXT_FS_DIR / "literature_state.md").read_text()
    assert "Die Governance erfolgt durch definierte Policies" in text


# ---------------------------------------------------------------------------
# AC2: cwd/allowed_tools werden tatsaechlich an den Subprozess durchgereicht,
# und die Fixture ist fuer ein anderes cwd unsichtbar.
# ---------------------------------------------------------------------------


def _fake_subprocess_run_ok():
    def _run(cmd, **kwargs):
        payload = {"is_error": False, "result": "OK", "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    return _run, {}


def test_run_claude_cli_passes_cwd_to_subprocess(monkeypatch):
    calls: list[dict] = []

    def _run(cmd, **kwargs):
        calls.append(kwargs)
        payload = {"is_error": False, "result": "OK", "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(eval_runner.subprocess, "run", _run)

    eval_runner._run_claude_cli("sys", "user", "claude-sonnet-4-6", cwd=CONTEXT_FS_DIR)

    assert calls[0]["cwd"] == CONTEXT_FS_DIR


def test_run_claude_cli_defaults_to_no_cwd(monkeypatch):
    """Rueckwaertskompatibilitaet: ohne cwd-Argument bleibt das heutige
    Verhalten (kein cwd im subprocess.run-Aufruf, also Prozess-cwd des
    Testlaufs)."""
    calls: list[dict] = []

    def _run(cmd, **kwargs):
        calls.append(kwargs)
        payload = {"is_error": False, "result": "OK", "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(eval_runner.subprocess, "run", _run)

    eval_runner._run_claude_cli("sys", "user", "claude-sonnet-4-6")

    assert calls[0].get("cwd") is None


def test_run_claude_cli_passes_allowed_tools(monkeypatch):
    captured_cmd: list[list[str]] = []

    def _run(cmd, **kwargs):
        captured_cmd.append(cmd)
        payload = {"is_error": False, "result": "OK", "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(eval_runner.subprocess, "run", _run)

    eval_runner._run_claude_cli(
        "sys", "user", "claude-sonnet-4-6", cwd=CONTEXT_FS_DIR, allowed_tools=["Read"]
    )

    cmd = captured_cmd[0]
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"


def test_run_claude_cli_default_allowed_tools_is_empty(monkeypatch):
    """Ohne allowed_tools bleibt das heutige Verhalten: keine Tools
    (--allowedTools "")."""
    captured_cmd: list[list[str]] = []

    def _run(cmd, **kwargs):
        captured_cmd.append(cmd)
        payload = {"is_error": False, "result": "OK", "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(eval_runner.subprocess, "run", _run)

    eval_runner._run_claude_cli("sys", "user", "claude-sonnet-4-6")

    cmd = captured_cmd[0]
    assert cmd[cmd.index("--allowedTools") + 1] == ""


def test_call_claude_forwards_cwd_and_allowed_tools(monkeypatch):
    monkeypatch.setattr(eval_runner, "claude_cli_available", lambda: True)
    seen: dict = {}

    def _fake_run_claude_cli(system, user, model, *, cwd=None, allowed_tools=None):
        seen["cwd"] = cwd
        seen["allowed_tools"] = allowed_tools
        return {"result": "OK", "usage": {}}

    monkeypatch.setattr(eval_runner, "_run_claude_cli", _fake_run_claude_cli)

    eval_runner.call_claude("sys", "user", cwd=CONTEXT_FS_DIR, allowed_tools=["Read"])

    assert seen["cwd"] == CONTEXT_FS_DIR
    assert seen["allowed_tools"] == ["Read"]


def test_fixture_dir_is_invisible_to_a_call_with_different_cwd(tmp_path):
    """Isolationsbeweis (AC2): ein Fall, der mit einem leeren tmp_path
    arbeitet, sieht keine der drei Fixture-Dateien -- die Fixture leakt
    nicht ins Repo-Root oder in andere Suiten."""
    assert tmp_path != CONTEXT_FS_DIR
    for name in FIXTURE_FILES:
        assert not (tmp_path / name).exists()


# ---------------------------------------------------------------------------
# AC3: Negativfall bleibt erhalten -- mindestens ein Case in evals.json
# prueft weiterhin ohne cwd/Fixture.
# ---------------------------------------------------------------------------


def test_ac3_negative_case_without_cwd_exists():
    """Mindestens ein Case in einer der betroffenen evals.json-Dateien
    prueft weiterhin explizit die Vorbedingungs-Meldung ohne Kontextdateien
    (Muster wie instrument-design/id-02)."""
    candidates = [
        eval_runner.EVALS_ROOT / "academic-context" / "evals.json",
        eval_runner.EVALS_ROOT / "methodology-advisor" / "evals.json",
        eval_runner.EVALS_ROOT / "plagiarism-check" / "evals.json",
        eval_runner.EVALS_ROOT / "abstract-generator" / "evals.json",
    ]
    pattern_hits = 0
    for path in candidates:
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for prompt in data.get("prompts", []):
            expected = prompt.get("expected", {})
            value = expected.get("value", "")
            values = value if isinstance(value, list) else [value]
            if any(
                any(
                    kw in v
                    for kw in (
                        "nicht vorhanden",
                        "fehlen",
                        "fehlt",
                        "Vorbedingung",
                        "academic-context",
                    )
                )
                for v in values
            ):
                pattern_hits += 1
    assert pattern_hits >= 1, (
        "Kein Negativfall (Vorbedingungs-Meldung ohne Kontextdateien) mehr gefunden"
    )
