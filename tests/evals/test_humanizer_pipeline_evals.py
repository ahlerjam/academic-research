"""pytest-Integration fuer den humanizer-de-pipeline-Eval-Runner (Issue #390).

Bis Issue #390 war ``evals/humanizer-de-pipeline/`` eine tote Eval-Definition:
Das Material (3 Vorher-/Nachher-Draft-Paare) lag im Repo, der dokumentierte
Messweg war aber ein MANUELLER GPTZero-Abgleich — kein Code hat die Drafts je
gelesen, kein CI-Lauf hat sie je bewertet.

Diese Datei bindet einen deterministischen, kostenlosen Ersatz-Messweg ein:
``evals/humanizer-de-pipeline/runner.py`` zaehlt kuratierte KI-Tell-Marker aus
``skills/humanizer-de/references/patterns.md`` und berechnet je Draft eine
Tell-Dichte (Marker pro 100 Woerter). Kein Netz, kein ANTHROPIC_API_KEY,
kein GPTZero — die Cases laufen in jeder CI-Matrix durch.

Negativkontrolle (Muster: Risiko „Placebo-Metrik"): Der Vorher-Draft muss eine
Mindest-Tell-Dichte UEBERSCHREITEN. Ohne diese Assertion wuerde ein Runner,
der gar nichts misst (alle Dichten 0.0), die Drop-Assertion trivial bestehen.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "humanizer-de-pipeline"
RUNNER_PATH = EVAL_DIR / "runner.py"

DRAFT_IDS = ["draft-01-theorie", "draft-02-methodik", "draft-03-diskussion"]


def _load_runner():
    """Laedt evals/humanizer-de-pipeline/runner.py (Verzeichnis mit Bindestrich)."""
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} — evals/humanizer-de-pipeline haette ohne ihn "
        f"weiterhin keinen Ausfuehrungspfad (Issue #390, AC2)."
    )
    spec = importlib.util.spec_from_file_location("humanizer_pipeline_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def eval_results(runner):
    """Fuehrt den Tell-Density-Eval genau einmal pro Modul aus."""
    assert hasattr(runner, "run_eval_cases"), (
        "runner.py muss eine importierbare run_eval_cases()-Funktion exportieren "
        "(Muster: evals/verbatim-guard/runner.py, Issue #390)."
    )
    return runner.run_eval_cases()


# ---------------------------------------------------------------------------
# AC2: humanizer-de-pipeline hat einen echten, kostenlosen Ausfuehrungspfad.
# ---------------------------------------------------------------------------


def test_runner_is_importable_via_pytest(runner):
    """runner.py wird ueber pytest erreicht und exportiert run_eval_cases()."""
    assert hasattr(runner, "run_eval_cases")


def test_all_three_draft_pairs_execute(eval_results):
    """Alle 3 Vorher/Nachher-Paare werden ausgefuehrt — kein Skip, kein Leerlauf."""
    details = eval_results["details"]
    assert [d["draft"] for d in details] == DRAFT_IDS, (
        f"Erwartet die 3 Draft-Paare {DRAFT_IDS}, erhalten: {[d['draft'] for d in details]}"
    )


@pytest.mark.parametrize("draft_id", DRAFT_IDS)
def test_tell_density_drops_per_draft(draft_id, eval_results):
    """Kernmetrik: Die Tell-Dichte sinkt nach dem humanizer-de-Pass — pro Draft."""
    detail = next(d for d in eval_results["details"] if d["draft"] == draft_id)
    assert detail["density_after"] < detail["density_before"], (
        f"{draft_id}: Tell-Dichte sinkt nicht "
        f"(vorher={detail['density_before']:.2f}, nachher={detail['density_after']:.2f}); "
        f"Marker vorher={detail['markers_before']}, nachher={detail['markers_after']}"
    )


@pytest.mark.parametrize("draft_id", DRAFT_IDS)
def test_before_draft_exceeds_detection_floor(draft_id, eval_results, runner):
    """Negativkontrolle: Der Vorher-Draft muss den Detection-Floor ueberschreiten.

    Sonst misst der Runner nichts und die Drop-Assertion waere ein Placebo.
    """
    detail = next(d for d in eval_results["details"] if d["draft"] == draft_id)
    floor = runner.DETECTION_FLOOR
    assert detail["density_before"] > floor, (
        f"{draft_id}: Vorher-Dichte {detail['density_before']:.2f} liegt nicht ueber "
        f"dem Detection-Floor {floor} — die Marker-Liste erkennt die KI-Tells nicht."
    )


@pytest.mark.parametrize("draft_id", DRAFT_IDS)
def test_substance_is_retained(draft_id, eval_results, runner):
    """Anti-Gaming: Die Tell-Dichte darf nicht durch Textloeschung gesenkt werden.

    Ein Nachher-Draft mit 5 Woertern haette Dichte 0.0 und wuerde jede
    Drop-Assertion bestehen — ohne dass der Humanizer irgendetwas geleistet hat.
    Der Substanz-Quotient (Woerter nachher / Woerter vorher) haelt dagegen.
    """
    detail = next(d for d in eval_results["details"] if d["draft"] == draft_id)
    assert detail["substance_ratio"] >= runner.MIN_SUBSTANCE_RATIO, (
        f"{draft_id}: Nachher-Draft hat nur {detail['substance_ratio']:.0%} der "
        f"Wortmenge des Vorher-Drafts — die Tell-Reduktion beruht auf Kuerzung, "
        f"nicht auf Umformulierung."
    )


def test_relative_reduction_meets_target(eval_results):
    """AC des Eval-Sets: mindestens 2 von 3 Drafts erreichen >= 20 % Reduktion."""
    reduced = [d for d in eval_results["details"] if d["reduction_pct"] >= 20.0]
    assert len(reduced) >= 2, (
        "Weniger als 2 von 3 Drafts erreichen 20 % Tell-Reduktion: "
        f"{[(d['draft'], round(d['reduction_pct'], 1)) for d in eval_results['details']]}"
    )


def test_runner_needs_no_api_key(runner):
    """AC4: Der neue Runner verbraucht kein API-Budget (kein anthropic-Import)."""
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "anthropic" not in source, (
        "humanizer-de-pipeline-Runner darf keinen LLM-Call ausloesen (Issue #390, AC4)."
    )
    assert eval_module_has_no_network(source), (
        "humanizer-de-pipeline-Runner darf keinen Netzwerk-Client verwenden."
    )


def eval_module_has_no_network(source: str) -> bool:
    return not any(token in source for token in ("httpx", "requests", "urllib.request"))


def test_marker_catalog_is_traceable_to_patterns(runner):
    """Jeder Marker verweist auf eine Musternummer aus patterns.md (Nachvollziehbarkeit)."""
    catalog = runner.TELL_MARKERS
    assert catalog, "TELL_MARKERS darf nicht leer sein."
    patterns_md = (REPO_ROOT / "skills" / "humanizer-de" / "references" / "patterns.md").read_text(
        encoding="utf-8"
    )
    for pattern_no, phrases in catalog.items():
        assert isinstance(pattern_no, int) and 1 <= pattern_no <= 45, (
            f"Muster-Nummer {pattern_no!r} liegt ausserhalb der 45 Muster aus patterns.md."
        )
        assert f"| {pattern_no} |" in patterns_md, (
            f"Muster {pattern_no} steht nicht in der Kurzreferenz von patterns.md."
        )
        assert phrases, f"Muster {pattern_no} hat keine Marker-Phrasen."
        assert all(p == p.lower() and p.strip() for p in phrases), (
            f"Muster {pattern_no}: Marker muessen normalisiert (lowercase, getrimmt) sein."
        )
