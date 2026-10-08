"""Selftest fixture."""

from app.adapters.store import load_count


def decide_count() -> int:
    """Decide the count."""
    return load_count()
