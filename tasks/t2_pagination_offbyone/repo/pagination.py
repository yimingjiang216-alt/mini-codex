"""列表分页工具。"""


def page(items: list, page_no: int, per_page: int = 10) -> list:
    """返回第 page_no 页（从 1 开始计数）的元素。

    当前实现直接用切片，边界处理不正确。
    """
    if page_no < 1:
        raise ValueError("page_no 必须从 1 开始")
    start = page_no * per_page
    end = start + per_page
    return items[start:end]


def total_pages(total_items: int, per_page: int = 10) -> int:
    """返回总页数。"""
    return total_items // per_page
