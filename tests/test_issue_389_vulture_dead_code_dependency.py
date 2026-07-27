"""Regressionstest fuer Issue #389 — vulture als Dev-Dependency + sichtbarer Fehlschlag.

Befund (verifiziert): .github/workflows/pr-deep-review.yml:215 rief `uv run vulture`
mit einem pauschalen `|| true` auf; vulture stand weder in pyproject.toml noch in
uv.lock. Ein echter vulture-Fehlschlag (Exit-Code 1 = Syntaxfehler/ungueltige Eingabe,
2 = ungueltige CLI-Argumente) wurde dadurch stillschweigend verschluckt.

4 Test-Cases (rein strukturell — TOML/YAML-Ebene, kein echter CI-Lauf, kein LLM-Call):
1. pyproject.toml listet vulture im dev-Extra (AC1-Voraussetzung).
2. uv.lock enthaelt einen vulture-Eintrag (AC2).
3. Der dead-code-Job in pr-deep-review.yml haengt vulture NICHT mehr pauschal an
   `|| true` (der bisherige Ist-Defekt aus dem Issue).
4. Der neue vulture-Aufruf wertet den Exit-Code aus und laesst den Step bei einem
   echten Fehlschlag (nicht 0/3) sichtbar rot werden (AC4), waehrend Exit-Code 3
   (totem Code gefunden — der Normalfall) den Step weiterhin nicht rot macht.
"""

import re
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
PR_DEEP_REVIEW_WORKFLOW = ROOT / ".github" / "workflows" / "pr-deep-review.yml"


def _dead_code_job() -> dict:
    data = yaml.safe_load(PR_DEEP_REVIEW_WORKFLOW.read_text(encoding="utf-8"))
    jobs = data.get("jobs", {})
    assert "dead-code" in jobs, "pr-deep-review.yml hat keinen dead-code-Job mehr."
    return jobs["dead-code"]


def _vulture_step_run() -> str:
    job = _dead_code_job()
    for step in job["steps"]:
        run = str(step.get("run", ""))
        if "uv run vulture" in run:
            return run
    raise AssertionError("Kein Step im dead-code-Job ruft 'uv run vulture' auf.")


# --------------------------------------------------------------------------- #
# 1. pyproject.toml: vulture im dev-Extra
# --------------------------------------------------------------------------- #
def test_pyproject_dev_extra_lists_vulture():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dev_deps = data["project"]["optional-dependencies"]["dev"]
    assert any(
        dep.split(">")[0].split("=")[0].split("<")[0].strip() == "vulture" for dep in dev_deps
    ), f"vulture fehlt im [project.optional-dependencies].dev-Extra: {dev_deps}"


# --------------------------------------------------------------------------- #
# 2. uv.lock: vulture-Eintrag vorhanden
# --------------------------------------------------------------------------- #
def test_uv_lock_has_vulture_entry():
    text = UV_LOCK.read_text(encoding="utf-8")
    assert re.search(r'^name = "vulture"$', text, re.MULTILINE), (
        "uv.lock enthaelt keinen vulture-Eintrag."
    )


# --------------------------------------------------------------------------- #
# 3. dead-code-Job: vulture-Aufruf haengt nicht mehr pauschal an '|| true'
# --------------------------------------------------------------------------- #
def test_vulture_invocation_no_longer_swallows_all_exit_codes():
    run = _vulture_step_run()
    # Der bisherige Ist-Defekt: direkt nach der Umleitung nach vulture.txt ein
    # pauschales '|| true', das JEDEN Exit-Code (auch 1/2 = echter Fehlschlag)
    # verschluckt.
    assert not re.search(r"vulture\.txt\"\s*2>&1\s*\|\|\s*true", run), (
        "Der vulture-Aufruf haengt weiterhin pauschal an '|| true' — "
        "ein echter Fehlschlag (Exit 1/2) bleibt unsichtbar (Ist-Defekt aus Issue #389)."
    )


# --------------------------------------------------------------------------- #
# 4. dead-code-Job: Exit-Code wird ausgewertet, {0,3} bleiben unkritisch,
#    alles andere macht den Step sichtbar rot.
# --------------------------------------------------------------------------- #
def test_vulture_invocation_evaluates_exit_code_and_allows_only_0_and_3():
    run = _vulture_step_run()
    # Der Exit-Code muss erfasst werden (z.B. via $? nach 'set +e' oder einer
    # eigenen if/case-Verzweigung) UND explizit auf die vulture-Normalfaelle
    # 0 (kein Fund) und 3 (totem Code gefunden) eingeschraenkt werden.
    assert "$?" in run or "VULTURE_EXIT" in run, (
        "Der vulture-Schritt wertet den Exit-Code nicht sichtbar aus."
    )
    assert re.search(r"[^0-9](0|3)[^0-9].*(0|3)[^0-9]", run) or ("0" in run and "3" in run), (
        "Der vulture-Schritt referenziert nicht beide erlaubten Exit-Codes (0 und 3)."
    )
    # Ein Fehlschlag muss den Step sichtbar (GitHub-Annotation und/oder exit
    # ungleich 0) machen statt ihn stillschweigend weiterlaufen zu lassen.
    assert "::error::" in run and re.search(r"\bexit 1\b", run), (
        "Der vulture-Schritt macht einen echten Fehlschlag nicht sichtbar "
        "(erwartet '::error::'-Annotation + 'exit 1')."
    )
