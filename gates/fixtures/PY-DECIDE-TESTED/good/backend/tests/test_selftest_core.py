from app.selftest.core import decide_limit


def test_negative_becomes_zero() -> None:
    assert decide_limit(-1) == 0
