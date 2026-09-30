from jsonpath_lite import get


def test_simple_nested():
    assert get({"a": {"b": 1}}, "a.b") == 1


def test_missing_returns_default():
    assert get({"a": 1}, "b", default=-1) == -1
