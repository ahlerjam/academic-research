"""Selftest fixture."""

from pathlib import Path


def load_text(path: Path) -> str:
    """Read a file."""
    try:
        return path.read_text()
    except OSError:
        return ""
