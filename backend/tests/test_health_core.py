"""Core tests for the health decision."""

from app.health.core import Facts, decide_status


def test_reachable_dependencies_are_ok() -> None:
    assert decide_status(Facts(dependencies_reachable=True)).status == "ok"


def test_unreachable_dependency_is_degraded() -> None:
    assert decide_status(Facts(dependencies_reachable=False)).status == "degraded"
