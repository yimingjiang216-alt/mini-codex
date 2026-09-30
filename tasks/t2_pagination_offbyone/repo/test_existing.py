from pagination import page, total_pages


def test_page_returns_at_most_per_page_items():
    # 契约：任何合法 page_no 返回的元素个数都不超过 per_page
    got = page(list(range(25)), 1, 10)
    assert len(got) <= 10


def test_page_returns_slice_of_input():
    # 契约：返回值始终是输入列表的连续子序列，不夹带、不越界
    items = list(range(25))
    got = page(items, 2, 10)
    assert all(x in items for x in got)
    if got:
        assert got == items[items.index(got[0]):items.index(got[0]) + len(got)]


def test_total_pages_is_positive_for_nonempty():
    assert total_pages(25, 10) >= 1
