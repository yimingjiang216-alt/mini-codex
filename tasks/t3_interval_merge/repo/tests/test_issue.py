from intervals import merge


def test_touching_intervals_merge():
    # [1,3] 与 [3,5] 首尾相接，应合并为 [1,5]
    assert merge([(1, 3), (3, 5)]) == [(1, 5)]


def test_nested_interval():
    assert merge([(1, 10), (3, 4)]) == [(1, 10)]


def test_chain_of_touching():
    assert merge([(1, 2), (2, 3), (3, 4)]) == [(1, 4)]


def test_unsorted_input():
    assert merge([(5, 7), (1, 3), (2, 4)]) == [(1, 4), (5, 7)]


def test_contained_after_merge():
    assert merge([(1, 4), (2, 3), (6, 8)]) == [(1, 4), (6, 8)]


def test_duplicate_intervals():
    assert merge([(1, 2), (1, 2)]) == [(1, 2)]
