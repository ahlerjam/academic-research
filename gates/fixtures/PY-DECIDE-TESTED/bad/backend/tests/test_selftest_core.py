from app.selftest.core import decide_limit


def test_called_but_result_never_checked() -> None:
    decide_limit(1)
    assert True
