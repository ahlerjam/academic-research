"""pytest-Integration fuer den sparring-partner-Recording-Snapshot (PR #494, Issue #454).

Kontext: Ein AC-Verifier-Lauf (PR #494, Kommentar vom 2026-07-29) markierte AC2/AC3/AC4/AC5
als "verfehlt", weil die einzige inhaltliche Evidenz tests/evals/test_sparring_partner_evals.py
war -- API-gated, ohne ANTHROPIC_API_KEY (kein Workflow unter .github/workflows/ setzt ihn)
niemals ausgefuehrt.

evals/sparring-partner/recordings.json haelt daraufhin fuenf Transkripte fest, die eine
Claude-Session waehrend der PR-#494-Fix-Runde erzeugt hat: Agent-Body aus
agents/sparring-partner.md als System-Prompt, die fuenf Eval-Inputs aus
evals/sparring-partner/evals.json als User-Message. Kein Live-Aufruf des in der Frontmatter
spezifizierten ``model: opus`` per Anthropic-API (Provenienz inkl. Einschraenkungen ist in
recordings.json::provenance offengelegt).

**Was dieser Test NICHT ist:** ein unabhaengiger Verhaltensbeleg. Transkript
(recordings.json) und Erwartung (evals.json::expected) stammen aus derselben Sitzung --
wer die Regex geschrieben hat, kannte die Antwort bereits. Der einzige Pfad, auf dem dieser
Test tatsaechlich fehlschlagen kann, ist der sha256-Hash-Pin (siehe unten): Aendert sich
agents/sparring-partner.md, ohne dass recordings.json neu aufgenommen wird, schlaegt
test_recording_is_pinned_to_current_agent_file fehl, statt die veraltete Aufnahme
stillschweigend weiterlaufen zu lassen. Das macht diesen Runner zu einem
Snapshot-/Konsistenz-Check zwischen eingefrorenem Text und Regex -- deshalb fuehrt
docs/evals/STRATEGY.md die Komponente als ``structural``, nicht als ``metric``.

Zusaetzlich unterscheidet sich der Prompt-Aufbau vom API-gated Pfad: Diese Aufnahme nutzte
nur den Agent-Body nach dem Frontmatter-Abschluss ``---`` als System-Prompt, waehrend
tests/evals/test_sparring_partner_evals.py ueber ``load_agent_content()``
(tests/evals/eval_runner.py) die komplette Datei inklusive YAML-Frontmatter (mit den
``<example>``-Bloecken) uebergibt. Beide Pfade prompten also unterschiedlich und sind keine
austauschbare Evidenzkette (Coordinator-Gate-Befund, PR #494).

Der inhaltliche AC-Beleg fuer AC2/AC3/AC5 bleibt deshalb
tests/evals/test_sparring_partner_evals.py -- API-gated, Live-Aufruf gegen ein echtes
Modell, ohne Key Skip.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "sparring-partner"
RUNNER_PATH = EVAL_DIR / "runner.py"
RECORDINGS_PATH = EVAL_DIR / "recordings.json"
EVALS_PATH = EVAL_DIR / "evals.json"
AGENT_PATH = REPO_ROOT / "agents" / "sparring-partner.md"


def _load_runner():
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} -- sparring-partner haette ohne ihn weiterhin "
        f"keinen echten Ausfuehrungspfad (PR #494 Fix-Runde, AC2/AC3/AC5)."
    )
    spec = importlib.util.spec_from_file_location("sparring_partner_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def eval_results(runner):
    assert hasattr(runner, "run_eval_cases"), (
        "runner.py muss eine importierbare run_eval_cases()-Funktion exportieren "
        "(Muster: evals/auto-download/runner.py, Issue #390)."
    )
    return runner.run_eval_cases()


def _prompt_ids() -> list[str]:
    data = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    return [p["id"] for p in data["prompts"]]


# ---------------------------------------------------------------------------
# AC2/AC3/AC5: Es liegt tatsaechlicher, geprueft-passender Modell-Output vor.
# ---------------------------------------------------------------------------


def test_recordings_file_exists():
    assert RECORDINGS_PATH.exists(), (
        f"recordings.json fehlt: {RECORDINGS_PATH} -- ohne echte aufgenommene "
        f"Transkripte bleibt sparring-partner ohne tatsaechlichen Modell-Output "
        f"(AC-Verifier-Befund zu PR #494)."
    )


def test_every_eval_prompt_has_a_recorded_transcript(eval_results):
    """Kein Prompt aus evals.json faellt stillschweigend unter den Tisch."""
    recorded = {d["id"]: d["has_transcript"] for d in eval_results["details"]}
    missing = [pid for pid in _prompt_ids() if not recorded.get(pid)]
    assert not missing, f"Kein aufgenommenes Transkript fuer: {missing}"


@pytest.mark.parametrize("prompt_id", _prompt_ids())
def test_recorded_transcript_matches_expected(prompt_id, eval_results):
    """Snapshot-Konsistenz: Das eingefrorene Transkript erfuellt evals.json::expected.

    Kein unabhaengiger Verhaltensbeleg (siehe Modul-Docstring) -- der einzige echte
    Fehlerpfad ist der Hash-Pin in test_recording_is_pinned_to_current_agent_file.
    prompt_id ordnet trotzdem den AC-Verifier-Punkten zu, die der API-gated Suite
    (tests/evals/test_sparring_partner_evals.py) inhaltlich zugrunde liegen:
    sp-01/sp-05 -> AC2 (Schwaeche + Alternative statt Bestaetigung), sp-01 zusaetzlich
    AC5 (bewusst schwache/tautologische Forschungsfrage). sp-03 -> AC3 (Argumentation
    am konkreten Vault-Material "meier2024"/"Review-Mehraufwand"). sp-04 -> AC4 (Verweis
    an chapter-writer statt Kapitel-Prosa).
    """
    detail = next(d for d in eval_results["details"] if d["id"] == prompt_id)
    assert detail["ok"], (
        f"{prompt_id}: aufgenommenes Transkript erfuellt expected nicht ({detail['expected']})."
    )


def test_overall_recording_pass(eval_results):
    assert eval_results["failed"] == 0, (
        f"{eval_results['failed']} aufgenommene(s) Transkript(e) erfuellt/erfuellen "
        f"expected nicht: {[d for d in eval_results['details'] if not d['ok']]}"
    )


# ---------------------------------------------------------------------------
# Anti-Drift: eine veraltete Aufnahme darf nicht stillschweigend weiterlaufen.
# ---------------------------------------------------------------------------


def test_recording_is_pinned_to_current_agent_file(eval_results):
    """Aenderung an agents/sparring-partner.md ohne Neu-Aufnahme faellt hier auf --
    verhindert, dass veraltetes Modellverhalten stillschweigend als aktuell gilt."""
    assert eval_results["hash_pin_ok"], (
        f"recordings.json ist an einen aelteren Stand von agents/sparring-partner.md "
        f"gepinnt (erwartet {eval_results['hash_pin_expected'][:12]}…, aktuell "
        f"{eval_results['hash_pin_actual'][:12]}…). agents/sparring-partner.md hat "
        f"sich seit der Aufnahme geaendert -- recordings.json braucht eine neue "
        f"Aufnahme."
    )


# ---------------------------------------------------------------------------
# Konsistenz mit Issue #390 AC4: kein neuer Runner unter evals/ verbraucht Budget.
# ---------------------------------------------------------------------------


def test_runner_needs_no_api_key_and_no_network():
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "anthropic" not in source, "sparring-partner-Runner darf keinen LLM-Call ausloesen."
    assert "require_api_key" not in source, (
        "sparring-partner-Runner darf nicht an require_api_key haengen (sonst wieder ein Skip)."
    )
