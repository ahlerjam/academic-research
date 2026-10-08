"""Selftest fixture: a skipped test must turn the run red."""

import pytest


@pytest.mark.skip(reason="selftest")
def test_selftest_core() -> None:
    """Selftest fixture."""
    assert 1 + 1 == 3
