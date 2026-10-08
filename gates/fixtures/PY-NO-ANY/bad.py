"""Selftest fixture."""

from typing import Any


def decide_size(value: Any) -> int:
    """Decide the size."""
    return len(value)
