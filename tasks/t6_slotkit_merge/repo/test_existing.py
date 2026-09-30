"""回归测试：这些行为在修复前后都必须成立。"""
from slotkit import Slot, merge_busy, free_slots, total_free, intersect, subtract, parse_range


def test_slot_minutes():
    assert Slot(540, 600).minutes == 60


def test_slot_touches_but_not_overlaps():
    a, b = Slot(540, 600), Slot(600, 660)
    assert a.touches(b) is True
    assert a.overlaps(b) is False


def test_merge_true_overlap():
    assert merge_busy([(540, 620), (600, 660)]) == [Slot(540, 660)]


def test_merge_disjoint_kept_separate():
    assert merge_busy([(540, 600), (660, 720)]) == [Slot(540, 600), Slot(660, 720)]


def test_total_free_no_busy():
    assert total_free([], 540, 1080) == 540


def test_intersect_partial():
    assert intersect(Slot(540, 600), Slot(570, 630)) == Slot(570, 600)


def test_subtract_middle():
    assert subtract(Slot(540, 660), Slot(570, 600)) == [Slot(540, 570), Slot(600, 660)]


def test_parse_range():
    assert parse_range("09:30-11:00") == Slot(570, 660)
