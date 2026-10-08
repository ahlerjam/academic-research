"""Selftest fixture."""

def decide_items(items: list[int]) -> list[int]:
    """Add the default item."""
    return [*items, 1]
