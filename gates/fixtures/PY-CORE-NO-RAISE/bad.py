"""Selftest fixture."""

def decide_limit(value: int) -> int:
    """Reject a negative value."""
    if value < 0:
        raise ValueError("negative")
    return value
