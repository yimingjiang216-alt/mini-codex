from intervals import merge


def test_empty():
    assert merge([]) == []


def test_single():
    assert merge([(1, 5)]) == [(1, 5)]


def test_clear_overlap():
    assert merge([(1, 5), (3, 8)]) == [(1, 8)]
