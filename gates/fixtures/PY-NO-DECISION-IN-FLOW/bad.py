"""Selftest fixture."""

from app.selftest.core import decide_limit


def run_limit(value: int) -> int | None:
    """Decide the limit for a value."""
    return decide_limit(value) if value > 0 else None
