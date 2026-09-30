"""验收测试：首尾相接的区间必须合并。"""
from slotkit import Slot, merge_busy, free_slots, total_free, has_gap, largest_gap,     fit_slot, busiest_hour, utilization, summarize


def test_touching_intervals_merge():
    # 核心 bug：9:00-10:00 与 10:00-11:00 相接，应合并
    assert merge_busy([(540, 600), (600, 660)]) == [Slot(540, 660)]


def test_touching_chain_merges_into_one():
    assert merge_busy([(540, 600), (600, 660), (660, 720)]) == [Slot(540, 720)]


def test_no_zero_length_gap_between_touching():
    # 相接的两个区间之间不应该产生 0 分钟的空闲窗口
    gaps = free_slots([(540, 600), (600, 660)], 540, 1080)
    assert all(g.minutes > 0 for g in gaps)
    assert gaps == [Slot(660, 1080)]


def test_free_minutes_correct_when_touching():
    # 9:00-10:00 和 10:00-11:00 占满到 11:00，空闲 420 分钟
    assert total_free([(540, 600), (600, 660)], 540, 1080) == 420


def test_largest_gap_when_touching():
    assert largest_gap([(540, 600), (600, 660)], 540, 1080) == 420


def test_has_gap_when_touching():
    assert has_gap([(540, 600), (600, 660)], 420, 540, 1080) is True
    assert has_gap([(540, 600), (600, 660)], 421, 540, 1080) is False


def test_fit_slot_does_not_reuse_tiny_gap():
    # 修复前会在 10:00 处看到一个 0 分钟窗口，导致选错位置
    got = fit_slot([(540, 600), (600, 660)], 60, work_start=540, work_end=1080)
    assert got == Slot(660, 720)


def test_busiest_hour_unaffected_by_touching():
    assert busiest_hour([(540, 600), (600, 660)]) == 9


def test_utilization_when_touching():
    # 120 分钟占用 / 540 分钟工作时段
    assert round(utilization([(540, 600), (600, 660)], 540, 1080), 3) == 0.222


def test_summarize_busy_count_when_touching():
    s = summarize([(540, 600), (600, 660)], 540, 1080)
    assert s["busy_count"] == 1
    assert s["busy_minutes"] == 120
    assert s["free_windows"] == 1
