import pytest

from jsonpath_lite import get, PathNotFound


def test_list_index():
    assert get({"a": [10, 20, 30]}, "a.1") == 20


def test_list_index_first():
    assert get({"a": [10, 20]}, "a.0") == 10


def test_nested_list_of_dicts():
    data = {"items": [{"name": "x"}, {"name": "y"}]}
    assert get(data, "items.1.name") == "y"


def test_missing_key_raises_when_no_default():
    with pytest.raises(PathNotFound):
        get({"a": 1}, "b")


def test_out_of_range_index_raises_when_no_default():
    with pytest.raises(PathNotFound):
        get({"a": [1, 2]}, "a.5")


def test_negative_index_raises():
    with pytest.raises(PathNotFound):
        get({"a": [1, 2]}, "a.-1")


def test_non_index_path_into_list_raises():
    with pytest.raises(PathNotFound):
        get({"a": [1, 2]}, "a.x")


def test_default_used_for_missing_list_index():
    assert get({"a": [1, 2]}, "a.9", default="none") == "none"


def test_empty_path_returns_whole_data():
    data = {"a": 1}
    assert get(data, "") is data
