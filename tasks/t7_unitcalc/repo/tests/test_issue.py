"""验收测试：不同单位相加必须先把右操作数换算到左操作数的单位。"""
import pytest

from unitcalc import eval_expr, parse_quantity, add_all, UnitError


def test_add_km_and_m():
    # 核心 bug：3 km + 500 m 应当是 3.5 km，而不是 503 km
    assert eval_expr("3 km + 500 m").value == pytest.approx(3.5)


def test_add_h_and_min():
    assert eval_expr("1 h + 30 min").value == pytest.approx(1.5)


def test_add_kg_and_g():
    assert eval_expr("1 kg + 500 g").value == pytest.approx(1.5)


def test_add_small_to_large_unit():
    # 反过来：以 m 为左操作数
    assert eval_expr("500 m + 1 km").value == pytest.approx(1500.0)


def test_add_cm_and_m():
    assert eval_expr("100 cm + 1 m").value == pytest.approx(200.0)


def test_add_chain_across_units():
    assert eval_expr("1 h + 30 min + 1800 s").value == pytest.approx(2.0)


def test_add_keeps_left_unit():
    q = eval_expr("3 km + 500 m")
    assert q.unit.name == "km"


def test_add_zero_across_units():
    assert eval_expr("1 km + 0 m").value == pytest.approx(1.0)


def test_add_dimension_mismatch_still_raises():
    with pytest.raises(UnitError):
        eval_expr("1 km + 1 kg")


def test_add_result_matches_base_value():
    # 换算到基准单位后两者必须真的相等
    q = eval_expr("3 km + 500 m")
    assert q.base_value == pytest.approx(3500.0)


def test_parse_quantity_add():
    a = parse_quantity("2 km")
    b = parse_quantity("250 m")
    assert (a + b).value == pytest.approx(2.25)


def test_add_all_mixed_units():
    from unitcalc import parse_quantity as pq
    assert add_all([pq("1 km"), pq("500 m"), pq("250 m")]).value == pytest.approx(1.75)
