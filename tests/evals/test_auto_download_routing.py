"""pytest-Integration fuer den auto-download-Routing-Eval (Issue #390).

Bis Issue #390 war ``evals/auto-download/`` eine tote Eval-Definition: die 20
kuratierten Quellen in ``sources.yaml`` wurden von keinem Code gelesen, sondern
nur in ``docs/evals/v6.2-tier-eval.md`` erwaehnt. Der dort beschriebene
„Eval-Lauf" war ein YAML-Dump ohne jede Pruefung.

Der neue Runner prueft das, was ohne Netz ueberhaupt pruefbar ist: das
**Routing**. Fuer jede Quelle wird genau der in ``expected_tier`` genannte Tier
auf Treffer gestellt, alle uebrigen auf Fehlschlag — ``resolve_pdf_url()`` muss
dann genau diesen Tier zurueckmelden. Das faellt auf, sobald

  * einer Quelle die Metadaten fehlen, die ihr Tier ueberhaupt erreichbar machen
    (EuropePMC braucht eine DOI, arXiv einen Titel, DOAB ISBN oder Titel), oder
  * die Tier-Reihenfolge in ``scripts/pdf.py`` so umgebaut wird, dass der
    erwartete Tier nicht mehr erreicht wird (z. B. Buch-Vorrang von DOAB).

Was der Runner bewusst NICHT prueft: ``expected_hit``. Ob eine reale API heute
ein PDF liefert, ist netzabhaengig und gehoert nicht in eine hermetische CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "auto-download"
RUNNER_PATH = EVAL_DIR / "runner.py"
SOURCES_PATH = EVAL_DIR / "sources.yaml"


def _load_runner():
    assert RUNNER_PATH.exists(), (
        f"Runner fehlt: {RUNNER_PATH} — evals/auto-download haette ohne ihn "
        f"weiterhin keinen Ausfuehrungspfad (Issue #390, AC2)."
    )
    spec = importlib.util.spec_from_file_location("auto_download_runner", RUNNER_PATH)
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
        "(Muster: evals/verbatim-guard/runner.py, Issue #390)."
    )
    return runner.run_eval_cases()


def _source_ids() -> list[str]:
    """Liest die Quell-IDs direkt aus sources.yaml (unabhaengig vom Runner)."""
    import yaml

    data = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    return [s["id"] for s in data["sources"]]


# ---------------------------------------------------------------------------
# AC2: auto-download hat einen echten, kostenlosen Ausfuehrungspfad.
# ---------------------------------------------------------------------------


def test_runner_is_importable_via_pytest(runner):
    assert hasattr(runner, "run_eval_cases")


def test_every_source_is_executed(eval_results):
    """Alle 20 kuratierten Quellen laufen durch — kein Skip, keine Teilmenge."""
    executed = [d["id"] for d in eval_results["details"]]
    assert executed == _source_ids(), (
        f"Nicht alle Quellen aus sources.yaml wurden ausgefuehrt: {executed}"
    )
    assert len(executed) == 20, f"Erwartet 20 Quellen, erhalten: {len(executed)}"


def test_expected_tier_vocabulary_is_valid(runner):
    """Jede expected_tier-Angabe entspricht einem Tier-Label aus scripts/pdf.py."""
    for source in runner.load_sources():
        tier = source.get("expected_tier")
        assert tier is None or tier in runner.TIER_FUNCTIONS, (
            f"{source['id']}: unbekannter expected_tier {tier!r}; "
            f"bekannt sind {sorted(runner.TIER_FUNCTIONS)}."
        )


@pytest.mark.parametrize("source_id", _source_ids())
def test_expected_tier_is_reachable(source_id, eval_results):
    """Kernmetrik: Mit ausschliesslich dem erwarteten Tier auf Treffer liefert
    ``resolve_pdf_url()`` genau diesen Tier zurueck."""
    detail = next(d for d in eval_results["details"] if d["id"] == source_id)
    if detail["expected_tier"] is None:
        pytest.skip("Kontroll-Quelle ohne erwarteten Tier — siehe eigenen Test.")
    assert detail["routed_tier"] == detail["expected_tier"], (
        f"{source_id}: erwarteter Tier '{detail['expected_tier']}' wird nicht erreicht "
        f"(geroutet: {detail['routed_tier']!r}). Fehlen der Quelle die noetigen "
        f"Metadaten (doi/title/isbn) oder hat sich die Tier-Reihenfolge geaendert?"
    )


def test_control_sources_resolve_to_nothing(eval_results):
    """Quellen ohne erwarteten Tier duerfen keinen Tier erreichen (Kontrollgruppe)."""
    controls = [d for d in eval_results["details"] if d["expected_tier"] is None]
    assert controls, "sources.yaml muss mindestens eine Kontroll-Quelle enthalten."
    for detail in controls:
        assert detail["routed_tier"] is None, (
            f"{detail['id']}: Kontroll-Quelle wurde unerwartet auf Tier "
            f"'{detail['routed_tier']}' geroutet."
        )


@pytest.mark.parametrize("source_id", _source_ids())
def test_no_tier_hit_yields_no_url(source_id, eval_results):
    """Negativkontrolle: Trifft kein Tier, liefert resolve_pdf_url() (None, None).

    Beweist, dass der Mock die Aufloesung tatsaechlich steuert — ohne diesen Test
    koennte der Runner den erwarteten Tier auch schlicht zurueckerfinden.
    """
    detail = next(d for d in eval_results["details"] if d["id"] == source_id)
    assert detail["blank_run_tier"] is None and detail["blank_run_url"] is None, (
        f"{source_id}: ohne Treffer wurde trotzdem "
        f"{detail['blank_run_tier']!r}/{detail['blank_run_url']!r} zurueckgegeben."
    )


def test_overall_routing_pass(eval_results):
    assert eval_results["failed"] == 0, (
        f"{eval_results['failed']} Routing-Case(s) fehlgeschlagen: "
        f"{[d for d in eval_results['details'] if not d['ok']]}"
    )


def test_runner_needs_no_api_key_and_no_network(runner):
    """AC4: Der Runner verbraucht kein API-Budget und oeffnet keine Verbindung."""
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "anthropic" not in source, "auto-download-Runner darf keinen LLM-Call ausloesen."
    assert "httpx.Client(" not in source, (
        "auto-download-Runner darf keinen echten httpx-Client oeffnen — der Eval "
        "ist hermetisch (Issue #390)."
    )
