"""Diskriminierungs-Tests fuer die sparring-partner-Eval-Kriterien (Issue #454, PR #494).

Warum diese Suite existiert
---------------------------
Der AC-Verifier zu PR #494 markierte AC2/AC3/AC4/AC5 als "verfehlt". Die
Ursachenanalyse (systematic-debugging, Fix-Runde 2026-07-29) foerderte einen
Defekt zutage, der tiefer liegt als die fehlende API-Key-Ausfuehrung: **die
Erwartungen in evals/sparring-partner/evals.json hatten keinerlei
Unterscheidungskraft.** Gemessen wurde nur, ob eine Antwort die Formatmarker
gesetzt hat -- nicht, ob sie das tut, was die Akzeptanzkriterien verlangen.

Belegter Ausgangsbefund (reproduzierbar gegen den Stand vor dieser Suite):

    SCHWÄCHE:
    Keine nennenswerte — die Frage ist klar formuliert und gut gewählt.

    ALTERNATIVE:
    Keine nötig, ich würde sie genau so lassen.

Diese reine Bestaetigung erfuellte ``sp-01``/``sp-02``/``sp-05`` (Regex
``(?s)SCHWÄCHE:\\s*\\S.+ALTERNATIVE:\\s*\\S``) -- also genau das Gegenteil von
AC2 ("nennt mindestens eine substanzielle Schwaeche ... statt sie nur zu
bestaetigen") und AC5 ("widerspricht bei einer bewusst schwachen
Forschungsfrage"). Ebenso bestand Kapitel-Prosa den ``sp-04``-Check, solange
irgendwo das Wort ``chapter-writer`` vorkam (AC4), und eine zustimmende Antwort
bestand ``sp-03``, solange sie das Stichwort ``Meier`` aus der Eingabe
wiederholte (AC3).

Konsequenz: Der Befund traf **beide** Ausfuehrungspfade. Auch mit gesetztem
ANTHROPIC_API_KEY und echtem Modell-Output haette
tests/evals/test_sparring_partner_evals.py eine sykophantische Antwort
durchgewinkt. Die Kriterien -- nicht nur die Aufnahme -- waren strukturell
unfaehig zu scheitern.

Was diese Suite prueft
----------------------
Fuer jede in evals/sparring-partner/counter_examples.json hinterlegte
Negativkontrolle: ``expected`` des zugehoerigen Prompts muss sie **ablehnen**.
Die Gegenproben sind bewusst format-konform -- sie setzen dieselben
Abschnittsmarker wie eine gute Antwort und scheitern nur an dem, was inhaltlich
zaehlt. Damit haben die Kriterien einen nachweisbaren Fehlerpfad, der weder am
API-Key noch am sha256-Hash-Pin haengt.

Diese Suite laeuft offline, ohne API-Key, ohne Netz -- in jedem pytest-Lauf.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.evals.eval_runner import check_expected

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "sparring-partner"
EVALS_PATH = EVAL_DIR / "evals.json"
COUNTER_EXAMPLES_PATH = EVAL_DIR / "counter_examples.json"
RECORDINGS_PATH = EVAL_DIR / "recordings.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_by_id() -> dict[str, dict[str, Any]]:
    return {p["id"]: p["expected"] for p in _load(EVALS_PATH)["prompts"]}


def _counter_example_cases() -> list[tuple[str, str, str]]:
    """(prompt_id, label, text) fuer jede hinterlegte Negativkontrolle."""
    if not COUNTER_EXAMPLES_PATH.exists():
        return []
    data = _load(COUNTER_EXAMPLES_PATH)
    return [
        (prompt_id, case["label"], case["text"])
        for prompt_id, cases in data["counter_examples"].items()
        for case in cases
    ]


# ---------------------------------------------------------------------------
# Kern: die Kriterien muessen nicht-konforme Antworten ablehnen koennen.
# ---------------------------------------------------------------------------


def test_counter_examples_file_exists():
    assert COUNTER_EXAMPLES_PATH.exists(), (
        f"{COUNTER_EXAMPLES_PATH} fehlt -- ohne Negativkontrollen belegt ein "
        f"bestandener Eval nur Formattreue, nicht Widerspruchsverhalten "
        f"(AC2/AC3/AC4/AC5, Issue #454)."
    )


def test_every_prompt_has_at_least_one_counter_example():
    """Kein Eval-Prompt darf ohne Gegenprobe bleiben."""
    prompt_ids = list(_expected_by_id())
    covered = set(_load(COUNTER_EXAMPLES_PATH)["counter_examples"])
    missing = [pid for pid in prompt_ids if pid not in covered or not covered]
    assert not missing, (
        f"Prompts ohne Negativkontrolle: {missing} -- deren expected-Kriterium "
        f"ist nicht als unterscheidungsfaehig nachgewiesen."
    )


@pytest.mark.parametrize(
    ("prompt_id", "label", "text"),
    _counter_example_cases(),
    ids=lambda v: v if isinstance(v, str) and len(v) < 40 else "",
)
def test_expected_criteria_reject_counter_example(prompt_id: str, label: str, text: str):
    """Die Erwartung muss die nicht-konforme Antwort ablehnen.

    Schlaegt dieser Test fehl, ist das Kriterium zahnlos: es wuerde auch dann
    "bestanden" melden, wenn das Modell genau das Gegenteil des geforderten
    Verhaltens liefert.
    """
    expected = _expected_by_id()[prompt_id]
    assert not check_expected(text, expected), (
        f"{prompt_id}/{label}: expected={expected} akzeptiert eine Antwort, die "
        f"das Akzeptanzkriterium verletzt. Das Kriterium hat keine "
        f"Unterscheidungskraft -- ein bestandener Eval belegt damit nichts."
    )


# ---------------------------------------------------------------------------
# Gegenprobe zur Gegenprobe: die Kriterien duerfen nicht alles ablehnen.
# ---------------------------------------------------------------------------


def test_standalone_runner_agrees_with_shared_check_expected():
    """evals/sparring-partner/runner.py baut check_expected bewusst autark nach.

    Driften beide Implementierungen auseinander, meldet der CI-feste Offline-Pfad
    etwas anderes als der API-gated Live-Pfad -- und die Gegenproben belegen dann
    nur noch fuer eine der beiden Ketten etwas.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("sparring_partner_runner", EVAL_DIR / "runner.py")
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    samples = [text for _, _, text in _counter_example_cases()]
    samples += list(_load(RECORDINGS_PATH)["transcripts"].values())
    divergent = [
        (pid, sample[:60])
        for pid, expected in _expected_by_id().items()
        for sample in samples
        if check_expected(sample, expected) != runner._check_expected(sample, expected)
    ]
    assert not divergent, f"check_expected-Implementierungen divergieren: {divergent}"


def test_recorded_transcripts_still_pass_the_tightened_criteria():
    """Die verschaerften Kriterien duerfen die konformen Antworten nicht mit
    ausschliessen -- sonst waere "unterscheidungsfaehig" nur ein Alles-Nein."""
    expected_by_id = _expected_by_id()
    transcripts = _load(RECORDINGS_PATH)["transcripts"]
    rejected = [
        pid
        for pid, expected in expected_by_id.items()
        if pid in transcripts and not check_expected(transcripts[pid], expected)
    ]
    assert not rejected, (
        f"Verschaerfte Kriterien lehnen auch konforme Antworten ab: {rejected}. "
        f"Ein Kriterium, das alles ablehnt, misst genauso wenig wie eines, das "
        f"alles annimmt."
    )
