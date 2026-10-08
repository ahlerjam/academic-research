"""Selftest fixture."""

from pathlib import Path


def load_text(path: Path) -> str:
    """Read a file."""
    return path.read_text()
