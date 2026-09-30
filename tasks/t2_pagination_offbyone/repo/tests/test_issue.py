import pytest

from pagination import page, total_pages


def test_page_one_starts_at_first_item():
    assert page(["a", "b", "c"], 1, 2) == ["a", "b"]


def test_last_partial_page():
    assert page(list(range(25)), 3, 10) == list(range(20, 25))


def test_page_beyond_end_is_empty():
    assert page(list(range(5)), 9, 10) == []


def test_total_pages_rounds_up():
    assert total_pages(25, 10) == 3
    assert total_pages(20, 10) == 2
    assert total_pages(0, 10) == 0


def test_invalid_page_zero():
    with pytest.raises(ValueError):
        page([1, 2, 3], 0, 2)


def test_invalid_per_page():
    with pytest.raises(ValueError):
        page([1, 2, 3], 1, 0)
