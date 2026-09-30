"""区间合并。"""


def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """合并重叠区间，返回按起点升序的结果。

    当前只合并严格重叠的情况。
    """
    if not intervals:
        return []
    ordered = sorted(intervals)
    result = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = result[-1]
        if start < last_end:
            result[-1] = (last_start, max(last_end, end))
        else:
            result.append((start, end))
    return result
