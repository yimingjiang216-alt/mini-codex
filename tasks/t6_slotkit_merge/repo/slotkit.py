"""slotkit —— 时间区间运算与排期工具。

提供三类能力：
1. 区间的规范化、合并、求交、求差
2. 在已有占用（busy）中寻找空闲窗口
3. 把若干会议塞进工作日，做简单的贪心排期

所有时间用「当日分钟数」表示（0..1439），不涉及时区。
"""

from __future__ import annotations

from dataclasses import dataclass


DAY_MINUTES = 24 * 60

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class SlotError(ValueError):
    """区间非法。"""


@dataclass(frozen=True)
class Slot:
    """左闭右开的分钟区间 [start, end)。"""

    start: int
    end: int

    def __post_init__(self):
        if self.start < 0 or self.end > DAY_MINUTES:
            raise SlotError("slot out of day: {}-{}".format(self.start, self.end))
        if self.end < self.start:
            raise SlotError("slot end before start: {}-{}".format(self.start, self.end))

    @property
    def minutes(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Slot") -> bool:
        """是否真重叠（共用端点不算重叠）。"""
        return self.start < other.end and other.start < self.end

    def touches(self, other: "Slot") -> bool:
        """是否相接或重叠。"""
        return self.start <= other.end and other.start <= self.end

    def contains(self, minute: int) -> bool:
        return self.start <= minute < self.end

    def __str__(self):
        return "{:02d}:{:02d}-{:02d}:{:02d}".format(
            self.start // 60, self.start % 60, self.end // 60, self.end % 60)


def _as_slot(obj) -> Slot:
    """把 (start, end) 元组或 Slot 统一成 Slot。"""
    if isinstance(obj, Slot):
        return obj
    if isinstance(obj, (tuple, list)) and len(obj) == 2:
        return Slot(int(obj[0]), int(obj[1]))
    raise SlotError("cannot convert to Slot: {!r}".format(obj))


def normalize(slots) -> list:
    """排序 + 去掉零长度区间。"""
    out = [_as_slot(s) for s in slots]
    out = [s for s in out if s.minutes > 0]
    out.sort(key=lambda s: (s.start, s.end))
    return out


def merge_busy(slots) -> list:
    """合并相接或重叠的区间。

    注意：相接（如 9:00-10:00 与 10:00-11:00）也要合并成一个，
    否则会在空闲窗口计算里凭空多出一个 0 分钟的窗口。
    """
    merged = []
    for s in normalize(slots):
        if merged and merged[-1].overlaps(s):
            last = merged.pop()
            merged.append(Slot(last.start, max(last.end, s.end)))
        else:
            merged.append(s)
    return merged

def intersect(a: "Slot", b: "Slot") -> "Slot | None":
    """两个区间的交集；不相交返回 None。"""
    lo = max(a.start, b.start)
    hi = min(a.end, b.end)
    if hi <= lo:
        return None
    return Slot(lo, hi)


def subtract(a: "Slot", b: "Slot") -> list:
    """a 减去 b，返回 0~2 个区间。"""
    if not a.overlaps(b):
        return [a]
    out = []
    if b.start > a.start:
        out.append(Slot(a.start, min(b.start, a.end)))
    if b.end < a.end:
        out.append(Slot(max(b.end, a.start), a.end))
    return out


def free_slots(busy, work_start: int = 9 * 60, work_end: int = 18 * 60) -> list:
    """在工作时段内找出所有空闲区间。"""
    window = Slot(work_start, work_end)
    cur = [window]
    for b in merge_busy(busy):
        nxt = []
        for c in cur:
            nxt.extend(subtract(c, b))
        cur = nxt
    return sorted([c for c in cur if c.minutes > 0], key=lambda s: s.start)


def total_free(busy, work_start: int = 9 * 60, work_end: int = 18 * 60) -> int:
    """空闲总分钟数。"""
    return sum(s.minutes for s in free_slots(busy, work_start, work_end))


def has_gap(busy, need: int, work_start: int = 9 * 60, work_end: int = 18 * 60) -> bool:
    """是否存在一个长度 >= need 的空闲窗口。"""
    return any(s.minutes >= need for s in free_slots(busy, work_start, work_end))


def largest_gap(busy, work_start: int = 9 * 60, work_end: int = 18 * 60) -> int:
    """最大空闲窗口长度；没有则 0。"""
    gaps = free_slots(busy, work_start, work_end)
    return max((s.minutes for s in gaps), default=0)


def fit_slot(busy, need: int, prefer_after: int = None,
             work_start: int = 9 * 60, work_end: int = 18 * 60):
    """找一个长度够用的最早空闲窗口，返回 Slot 或 None。"""
    for gap in free_slots(busy, work_start, work_end):
        if gap.minutes >= need:
            start = gap.start
            if prefer_after is not None and start < prefer_after:
                start = prefer_after
                if start + need > gap.end:
                    continue
            return Slot(start, start + need)
    return None


def busiest_hour(busy) -> int:
    """被占用最多的那个小时（0..23），用于统计。"""
    counts = [0] * 24
    for b in merge_busy(busy):
        for m in range(b.start, b.end):
            counts[m // 60] += 1
    best = 0
    for h in range(24):
        if counts[h] > counts[best]:
            best = h
    return best


def utilization(busy, work_start: int = 9 * 60, work_end: int = 18 * 60) -> float:
    """工作时段内被占用的比例（0..1）。"""
    span = work_end - work_start
    if span <= 0:
        return 0.0
    used = span - total_free(busy, work_start, work_end)
    return used / span


def to_slots(pairs) -> list:
    """把 (start, end) 列表转成 Slot 列表。"""
    return [_as_slot(p) for p in pairs]


def to_pairs(slots) -> list:
    """把 Slot 列表转成 (start, end) 列表。"""
    return [(s.start, s.end) for s in slots]


def fmt(slot: "Slot") -> str:
    return str(slot)


def fmt_many(slots) -> str:
    return ", ".join(str(s) for s in slots) if slots else "(无)"


def parse_hhmm(text: str) -> int:
    """把 'HH:MM' 转成分钟数。"""
    text = text.strip()
    if ":" not in text:
        raise SlotError("expect HH:MM, got {!r}".format(text))
    hh, mm = text.split(":", 1)
    if not hh.isdigit() or not mm.isdigit():
        raise SlotError("expect HH:MM, got {!r}".format(text))
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise SlotError("time out of range: {!r}".format(text))
    return h * 60 + m


def parse_range(text: str):
    """把 'HH:MM-HH:MM' 转成 Slot。"""
    if "-" not in text:
        raise SlotError("expect HH:MM-HH:MM, got {!r}".format(text))
    left, right = text.split("-", 1)
    return Slot(parse_hhmm(left), parse_hhmm(right))


def day_of_week_name(idx: int) -> str:
    if not (0 <= idx <= 6):
        raise SlotError("weekday index out of range: {}".format(idx))
    return WEEKDAY_NAMES[idx]


def expand_weekly(pattern: dict) -> dict:
    """把 {weekday: [slots]} 里的简写转成规范化结构。"""
    out = {}
    for day, slots in pattern.items():
        if not (0 <= day <= 6):
            raise SlotError("bad weekday: {}".format(day))
        out[day] = merge_busy(slots)
    return out


def weekly_load(pattern: dict) -> int:
    """一周总占用分钟数。"""
    return sum(total_free([], 0, DAY_MINUTES) and sum(s.minutes for s in merge_busy(v))
               for v in expand_weekly(pattern).values())

def greedy_schedule(tasks, busy, work_start: int = 9 * 60, work_end: int = 18 * 60):
    """贪心排期：按耗时降序依次塞进空闲窗口。

    tasks: [(名字, 需要分钟数), ...]
    返回 [(名字, Slot), ...]，塞不下的任务放进 unscheduled。
    """
    remaining = sorted(tasks, key=lambda t: -t[1])
    placed = []
    cur_busy = list(busy)
    unscheduled = []
    for name, need in remaining:
        got = fit_slot(cur_busy, need, work_start=work_start, work_end=work_end)
        if got is None:
            unscheduled.append(name)
            continue
        placed.append((name, got))
        cur_busy.append(got)
    return placed, unscheduled


def summarize(busy, work_start: int = 9 * 60, work_end: int = 18 * 60) -> dict:
    """给一段 busy 生成摘要，方便打日志。"""
    merged = merge_busy(busy)
    return {
        "busy_count": len(merged),
        "busy_minutes": sum(s.minutes for s in merged),
        "free_windows": len(free_slots(busy, work_start, work_end)),
        "free_minutes": total_free(busy, work_start, work_end),
        "max_gap": largest_gap(busy, work_start, work_end),
        "utilization": round(utilization(busy, work_start, work_end), 3),
        "busiest_hour": busiest_hour(busy),
    }


def is_workday(idx: int) -> bool:
    """周一到周五。"""
    return 0 <= idx <= 4


def next_workday(idx: int) -> int:
    """下一个工作日（含自身）。"""
    cur = idx
    for _ in range(7):
        if is_workday(cur):
            return cur
        cur = (cur + 1) % 7
    return 0


def clamp(minute: int) -> int:
    """把分钟数夹到一天之内。"""
    return max(0, min(DAY_MINUTES, minute))


def overlaps_any(slot: "Slot", busy) -> bool:
    return any(slot.overlaps(b) for b in busy)


def free_ratio(busy, work_start: int = 9 * 60, work_end: int = 18 * 60) -> float:
    """空闲比例。"""
    return 1.0 - utilization(busy, work_start, work_end)


def longest_continuous_free(busy, work_start: int = 9 * 60, work_end: int = 18 * 60) -> "Slot | None":
    gaps = free_slots(busy, work_start, work_end)
    if not gaps:
        return None
    return max(gaps, key=lambda s: s.minutes)


def slots_equal(a, b) -> bool:
    return to_pairs(a) == to_pairs(b)

SUPPORTED_HINTS = [
    "09:00-18:00 工作时段",
    "Slot 是左闭右开",
    "busy 之间相接会合并",
]


def validate_all(busy) -> list:
    """返回所有发现的区间问题（用于数据清洗前的自检）。"""
    problems = []
    for i, raw in enumerate(busy):
        try:
            s = _as_slot(raw)
        except SlotError as e:
            problems.append("第 {} 项无法解析: {}".format(i, e))
            continue
        if s.minutes == 0:
            problems.append("第 {} 项是零长度区间: {}".format(i, s))
    return problems


def dedupe(slots) -> list:
    """去掉完全重复的区间，保持原顺序。"""
    seen = []
    for s in [_as_slot(x) for x in slots]:
        if s not in seen:
            seen.append(s)
    return seen


def complement(slots, day_start: int = 0, day_end: int = DAY_MINUTES) -> list:
    """在 [day_start, day_end) 里求补集。"""
    return free_slots(slots, day_start, day_end)


def scale_ratio(a: "Slot", b: "Slot") -> float:
    """两个区间的长度比（b 为 0 时返回 0）。"""
    if b.minutes == 0:
        return 0.0
    return a.minutes / b.minutes
