"""回归测试：修复前后都必须通过，不依赖 bug 行为。"""
import math

from unitcalc import (
    Quantity, UnitError, ParseError, eval_expr, parse_quantity, to_unit,
    convert, is_dimensionless, same_dimension, dim_of, list_units,
    normalize_angle, deg_to_rad, rad_to_deg, DIM_LENGTH,
)


def test_parse_quantity_basic():
    q = parse_quantity("3 km")
    assert q.value == 3.0
    assert q.unit.name == "km"


def test_to_unit_hours_to_minutes():
    assert to_unit("2 h", "min").value == 120.0


def test_convert_m_to_km():
    assert convert(1000, "m", "km") == 1.0


def test_same_unit_addition_still_works():
    # 同单位相加与单位换算无关，修复前后都必须是 7
    assert eval_expr("3 km + 4 km").value == 7.0


def test_subtraction_across_units():
    # 减法本来就写对了，不能因为修加法而弄坏
    assert eval_expr("2 kg - 500 g").value == 1.5


def test_multiplication_by_scalar():
    q = eval_expr("2 * 3 km")
    assert q.value == 6.0
    assert q.unit.dim == DIM_LENGTH


def test_division_gives_compound_unit():
    q = eval_expr("6 km / 2 h")
    assert q.value == 3.0
    assert q.unit.dim == (1, 0, -1, 0, 0, 0, 0)


def test_dimension_mismatch_raises():
    try:
        eval_expr("1 km + 1 kg")
    except UnitError:
        pass
    else:
        raise AssertionError("量纲不一致时应当报 UnitError")


def test_temperature_conversion():
    assert abs(convert(0, "degC", "K") - 273.15) < 1e-9
    assert abs(convert(32, "degF", "degC")) < 1e-9


def test_is_dimensionless_and_same_dimension():
    assert is_dimensionless(parse_quantity("50 %")) is True
    assert same_dimension(parse_quantity("1 km"), parse_quantity("1 m")) is True
    assert same_dimension(parse_quantity("1 km"), parse_quantity("1 s")) is False


def test_dim_of():
    assert dim_of("km") == "长度"
    assert dim_of("kg") == "质量"


def test_list_units_contains_common():
    names = list_units()
    for n in ("m", "km", "kg", "s", "min", "h"):
        assert n in names


def test_angle_helpers():
    assert normalize_angle(370.0) == 10.0
    assert abs(rad_to_deg(deg_to_rad(90.0)) - 90.0) < 1e-9


def test_parse_error_on_garbage():
    try:
        eval_expr("km +")
    except ParseError:
        pass
    else:
        raise AssertionError("非法表达式应当报 ParseError")
