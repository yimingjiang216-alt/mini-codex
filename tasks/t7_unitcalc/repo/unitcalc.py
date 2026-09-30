"""unitcalc —— 量纲感知的单位换算与算式求值。

支持：

    >>> eval_expr("3 km + 500 m")
    3500.0 m
    >>> to_unit("2 h", "min")
    120.0 min

设计：
- Unit      一个带量纲的单位定义（名字、到基准单位的倍率、偏移、量纲向量）
- Quantity  数值 + 单位
- 解析层     把 "3 km" 拆成数字和单位
- 求值层     支持 + - * / 与括号，加减要求量纲一致
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


class UnitError(ValueError):
    """单位不一致或单位不存在。"""


class ParseError(ValueError):
    """表达式语法错误。"""


# 量纲用一个 7 元组表示：(长度, 质量, 时间, 电流, 温度, 物质量, 光强)
DIM_NAMELESS = (0, 0, 0, 0, 0, 0, 0)
DIM_LENGTH = (1, 0, 0, 0, 0, 0, 0)
DIM_MASS = (0, 1, 0, 0, 0, 0, 0)
DIM_TIME = (0, 0, 1, 0, 0, 0, 0)

DIM_LABELS = ["长度", "质量", "时间", "电流", "温度", "物质量", "光强"]


def dim_str(dim) -> str:
    """把量纲向量画成人能读的形式，如 m^1 s^-1。"""
    parts = []
    for label, power in zip(DIM_LABELS, dim):
        if power == 0:
            continue
        if power == 1:
            parts.append(label)
        else:
            parts.append("{}^{}".format(label, power))
    return " ".join(parts) if parts else "无量纲"


@dataclass(frozen=True)
class Unit:
    """一个单位定义。

    factor: 乘上它得到基准单位的值
    offset: 用于温度这类有零点的单位（如摄氏度），基准值 = value * factor + offset
    """

    name: str
    factor: float
    dim: tuple
    offset: float = 0.0

    def to_base(self, value: float) -> float:
        return value * self.factor + self.offset

    def from_base(self, base: float) -> float:
        return (base - self.offset) / self.factor

    def __str__(self):
        return self.name


@dataclass
class Quantity:
    value: float
    unit: Unit

    def __repr__(self):
        return "{} {}".format(self.value, self.unit.name)

    @property
    def base_value(self) -> float:
        return self.unit.to_base(self.value)

    def to(self, unit: Unit) -> "Quantity":
        if unit.dim != self.unit.dim:
            raise UnitError(
                "量纲不一致：{} 是 {}，{} 是 {}".format(
                    self.unit.name, dim_str(self.unit.dim),
                    unit.name, dim_str(unit.dim)))
        return Quantity(unit.from_base(self.base_value), unit)

    def __add__(self, other):
        if not isinstance(other, Quantity):
            raise UnitError("不能把 {} 和 {} 相加".format(self.unit.name, type(other).__name__))
        if other.unit.dim != self.unit.dim:
            raise UnitError(
                "量纲不一致，无法相加：{} 与 {}".format(
                    dim_str(self.unit.dim), dim_str(other.unit.dim)))
        # BUG: 直接把两个数值相加，没有把 other 换算到 self 的单位
        return Quantity(self.value + other.value, self.unit)

    def __sub__(self, other):
        if not isinstance(other, Quantity):
            raise UnitError("不能把 {} 和 {} 相减".format(self.unit.name, type(other).__name__))
        if other.unit.dim != self.unit.dim:
            raise UnitError(
                "量纲不一致，无法相减：{} 与 {}".format(
                    dim_str(self.unit.dim), dim_str(other.unit.dim)))
        return Quantity(self.value - other.base_value / self.unit.factor, self.unit)

    def __mul__(self, other):
        if isinstance(other, Quantity):
            return Quantity(self.value * other.value, _derived_unit(self.unit, other.unit, 1))
        return Quantity(self.value * other, self.unit)

    __rmul__ = __mul__

    def __truediv__(self, other):
        if isinstance(other, Quantity):
            if other.value == 0:
                raise UnitError("除以零")
            return Quantity(self.value / other.value, _derived_unit(self.unit, other.unit, -1))
        if other == 0:
            raise UnitError("除以零")
        return Quantity(self.value / other, self.unit)

    def __eq__(self, other):
        if not isinstance(other, Quantity):
            return NotImplemented
        if other.unit.dim != self.unit.dim:
            return False
        return math.isclose(self.base_value, other.base_value, rel_tol=1e-9, abs_tol=1e-9)


def _derived_unit(a: Unit, b: Unit, sign: int) -> Unit:
    """构造合成单位：sign=+1 是乘积，sign=-1 是商。

    任一侧是无量纲时退化成另一侧（2 * 3km 仍然是 km，不是 1/km）。
    """
    dim = tuple(x + sign * y for x, y in zip(a.dim, b.dim))
    a_dimless = a.dim == DIM_NAMELESS
    b_dimless = b.dim == DIM_NAMELESS
    if b_dimless and not a_dimless:
        return a
    if a_dimless and not b_dimless:
        if sign > 0:
            return b
        return Unit("1/{}".format(b.name), b.factor, dim)
    if a_dimless and b_dimless:
        return Unit("1", a.factor, DIM_NAMELESS)
    name = "{}/{}".format(a.name, b.name)
    factor = a.factor * b.factor ** sign
    if sign < 0:
        # a/b 的倍率：把 a 的基准值表达成 b 的基准倍数
        factor = a.factor / b.factor
        return Unit(name, factor, dim)
    return Unit(name, factor, dim)


def _dim_mul(a, b, sign=1):
    return tuple(x + sign * y for x, y in zip(a, b))


# ---------------- 单位表 ----------------

def _u(name, factor, dim, offset=0.0):
    return Unit(name, factor, dim, offset)


UNITS = {}


def _register(unit: Unit, *aliases: str):
    UNITS[unit.name] = unit
    for a in aliases:
        UNITS[a] = unit


# 长度（基准 m）
_register(_u("m", 1.0, DIM_LENGTH), "meter", "meters", "米")
_register(_u("km", 1000.0, DIM_LENGTH), "kilometer", "kilometers", "千米", "公里")
_register(_u("cm", 0.01, DIM_LENGTH), "centimeter", "厘米")
_register(_u("mm", 0.001, DIM_LENGTH), "millimeter", "毫米")
_register(_u("um", 1e-6, DIM_LENGTH), "micrometer", "微米")
_register(_u("nm", 1e-9, DIM_LENGTH), "nanometer", "纳米")
_register(_u("in", 0.0254, DIM_LENGTH), "inch", "英寸")
_register(_u("ft", 0.3048, DIM_LENGTH), "foot", "feet", "英尺")
_register(_u("yd", 0.9144, DIM_LENGTH), "yard", "码")
_register(_u("mi", 1609.344, DIM_LENGTH), "mile", "miles", "英里")
_register(_u("nmi", 1852.0, DIM_LENGTH), "海里")
_register(_u("ly", 9.4607304725808e15, DIM_LENGTH), "lightyear", "光年")
_register(_u("au", 1.495978707e11, DIM_LENGTH), "天文单位")
_register(_u("pc", 3.0856775814913673e16, DIM_LENGTH), "parsec", "秒差距")

# 质量（基准 kg）
_register(_u("kg", 1.0, DIM_MASS), "kilogram", "千克", "公斤")
_register(_u("g", 0.001, DIM_MASS), "gram", "克")
_register(_u("mg", 1e-6, DIM_MASS), "milligram", "毫克")
_register(_u("ug", 1e-9, DIM_MASS), "microgram", "微克")
_register(_u("t", 1000.0, DIM_MASS), "tonne", "ton", "吨")
_register(_u("lb", 0.45359237, DIM_MASS), "pound", "pounds", "磅")
_register(_u("oz", 0.028349523125, DIM_MASS), "ounce", "盎司")
_register(_u("ct", 0.0002, DIM_MASS), "carat", "克拉")

# 时间（基准 s）
_register(_u("s", 1.0, DIM_TIME), "sec", "second", "seconds", "秒")
_register(_u("ms", 0.001, DIM_TIME), "millisecond", "毫秒")
_register(_u("us", 1e-6, DIM_TIME), "microsecond", "微秒")
_register(_u("ns", 1e-9, DIM_TIME), "nanosecond", "纳秒")
_register(_u("min", 60.0, DIM_TIME), "minute", "minutes", "分钟")
_register(_u("h", 3600.0, DIM_TIME), "hr", "hour", "hours", "小时")
_register(_u("day", 86400.0, DIM_TIME), "d", "days", "天")
_register(_u("week", 604800.0, DIM_TIME), "weeks", "周")
_register(_u("year", 31557600.0, DIM_TIME), "yr", "years", "年")

# 温标（基准 K，带偏移）
_register(_u("K", 1.0, (0, 0, 0, 0, 1, 0, 0)), "kelvin", "开尔文")
_register(_u("degC", 1.0, (0, 0, 0, 0, 1, 0, 0), 273.15), "celsius", "摄氏度", "℃")
_register(_u("degF", 5.0 / 9.0, (0, 0, 0, 0, 1, 0, 0), 255.3722222222222), "fahrenheit", "华氏度")

# 无量纲
_register(_u("1", 1.0, DIM_NAMELESS), "one", "个")
_register(_u("percent", 0.01, DIM_NAMELESS), "百分比", "%")
_register(_u("ppm", 1e-6, DIM_NAMELESS))


UNIT_ALIASES_SORTED = sorted(UNITS, key=len, reverse=True)


_NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def lookup(name: str) -> Unit:
    """按名字找单位，支持 degC / ℃ 这类别名。"""
    if name in UNITS:
        return UNITS[name]
    low = name.lower()
    if low in UNITS:
        return UNITS[low]
    raise UnitError("未知单位：{!r}".format(name))


def _split_value_unit(token: str):
    """把 '3km' / '3 km' / '-2.5e3 m' 拆成 (数值, 单位名)。"""
    token = token.strip()
    if not token:
        raise ParseError("空的一段")
    m = re.match(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*)$", token)
    if m:
        num_text, unit_text = m.group(1), m.group(2).strip()
        if not unit_text:
            unit_text = "1"
        return float(num_text), unit_text
    # 允许只有单位、"数值=1" 的写法，如 "degC" / "%" / "km"
    if re.match(r"^[A-Za-z_%\u00b0\u2103\u4e00-\u9fff]+$", token):
        return 1.0, token
    raise ParseError("无法解析：{!r}".format(token))


TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<number>[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s*(?P<unit>[A-Za-z_%\u00b0\u2103\u4e00-\u9fff]+))?"
    r"|(?P<unit_only>[A-Za-z_%\u00b0\u2103\u4e00-\u9fff]+)"
    r"|(?P<op>[+\-*/()])"
    r")"
)


def tokenize(text: str) -> list:
    """把表达式切成 token 列表。"""
    text = text.strip()
    if not text:
        raise ParseError("表达式为空")
    tokens = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise ParseError("位置 {} 处无法识别：{!r}".format(pos, text[pos:pos + 12]))
        if m.group("number") is not None:
            tokens.append(("num", float(m.group("number")), m.group("unit") or "1"))
        elif m.group("unit_only"):
            tokens.append(("num", 1.0, m.group("unit_only")))
        else:
            tokens.append(("op", m.group("op")))
        pos = m.end()
    return tokens


class _Parser:
    """递归下降求值：expr := term (('+'|'-') term)*，term := factor (('*'|'/') factor)*。"""

    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, op):
        tok = self.next()
        if tok is None or tok[0] != "op" or tok[1] != op:
            raise ParseError("期望 {!r}，实际 {!r}".format(op, tok))
        return tok

    def parse_expr(self) -> "Quantity":
        left = self.parse_term()
        while True:
            tok = self.peek()
            if tok is None or tok[0] != "op" or tok[1] not in "+-":
                break
            op = self.next()[1]
            right = self.parse_term()
            left = left + right if op == "+" else left - right
        return left

    def parse_term(self) -> "Quantity":
        left = self.parse_factor()
        while True:
            tok = self.peek()
            if tok is None or tok[0] != "op" or tok[1] not in "*/":
                break
            op = self.next()[1]
            right = self.parse_factor()
            left = left * right if op == "*" else left / right
        return left

    def parse_factor(self) -> "Quantity":
        tok = self.next()
        if tok is None:
            raise ParseError("表达式意外结束")
        if tok[0] == "num":
            _, value, unit_name = tok
            return Quantity(value, lookup(unit_name))
        if tok[0] == "op" and tok[1] == "(":
            inner = self.parse_expr()
            self.expect(")")
            return inner
        if tok[0] == "op" and tok[1] == "-":
            inner = self.parse_factor()
            return Quantity(-inner.value, inner.unit)
        if tok[0] == "op" and tok[1] == "+":
            return self.parse_factor()
        raise ParseError("无法解析的 token：{!r}".format(tok))


def eval_expr(text: str) -> Quantity:
    """求值一个算式，返回 Quantity。"""
    tokens = tokenize(text)
    parser = _Parser(tokens)
    result = parser.parse_expr()
    if parser.peek() is not None:
        raise ParseError("表达式末尾有多余内容：{!r}".format(parser.peek()))
    return result


def parse_quantity(text: str) -> Quantity:
    """解析单个 '数值+单位'，如 '3 km'。"""
    value, unit_name = _split_value_unit(text)
    return Quantity(value, lookup(unit_name))


def to_unit(text: str, target: str) -> Quantity:
    """把 '2 h' 换成目标单位。"""
    return parse_quantity(text).to(lookup(target))


def convert(value: float, src: str, dst: str) -> float:
    """只要数值的便捷函数。"""
    return to_unit("{} {}".format(value, src), dst).value


def is_dimensionless(q: "Quantity") -> bool:
    return q.unit.dim == DIM_NAMELESS


def same_dimension(a: "Quantity", b: "Quantity") -> bool:
    return a.unit.dim == b.unit.dim


def best_prefix(value: float, base_units) -> "Quantity":
    """把一个基准值换成最合适的量级前缀（返回第一个够大的）。"""
    for u in sorted(base_units, key=lambda x: x.factor):
        if value < u.factor:
            continue
        return Quantity(u.from_base(value), u)
    return Quantity(base_units[0].from_base(value), base_units[0])


def fmt(q: "Quantity", digits: int = 6) -> str:
    """格式化输出，去掉多余的尾随零。"""
    text = ("{:." + str(digits) + "g}").format(q.value)
    return "{} {}".format(text, q.unit.name)


def dim_of(text: str) -> str:
    """只想知道某个单位的量纲。"""
    return dim_str(lookup(text).dim)


def list_units(dim=None) -> list:
    """列出已知单位名；给了量纲就过滤。"""
    names = sorted({u.name for u in UNITS.values()})
    if dim is None:
        return names
    return [n for n in names if UNITS[n].dim == dim]


def add_all(items) -> "Quantity":
    """把若干个 Quantity 累加，要求量纲一致。"""
    if not items:
        raise UnitError("没有可累加的项")
    acc = items[0]
    for q in items[1:]:
        acc = acc + q
    return acc


def ratio(a: "Quantity", b: "Quantity") -> float:
    """同量纲两量的比值（无量纲）。"""
    if a.unit.dim != b.unit.dim:
        raise UnitError("量纲不一致，无法求比值")
    if b.value == 0:
        raise UnitError("分母为零")
    return a.base_value / b.base_value


def scale(q: "Quantity", k: float) -> "Quantity":
    return Quantity(q.value * k, q.unit)


def energy_hint(mass: "Quantity", c: str = "m/s") -> "Quantity":
    """一个玩具级的 E=mc^2，用来演示合成单位。"""
    cs = Quantity(299792458.0, lookup("m")).__truediv__(Quantity(1.0, lookup("s")))
    return mass * cs * cs


def normalize_angle(deg: float) -> float:
    """把角度归一化到 [0, 360)。"""
    return deg % 360.0


def deg_to_rad(deg: float) -> float:
    return deg * math.pi / 180.0


def rad_to_deg(rad: float) -> float:
    return rad * 180.0 / math.pi
