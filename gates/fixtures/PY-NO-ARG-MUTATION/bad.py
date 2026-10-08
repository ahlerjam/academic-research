"""Selftest fixture."""

def decide_items(items: list[int]) -> list[int]:
    """Add the default item."""
    items.append(1)
    return items
