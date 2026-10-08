"""Selftest fixture."""

def decide_limit(value: int) -> int | None:
    """Return the value, or None for a negative one."""
    return value if value >= 0 else None
