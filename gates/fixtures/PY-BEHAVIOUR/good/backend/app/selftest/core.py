"""Selftest fixture."""

def decide_limit(value: int) -> int:
    """Decide."""
    return max(value, 0)
