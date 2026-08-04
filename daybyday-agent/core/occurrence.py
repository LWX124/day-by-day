"""ensure_occurrences_up_to 的纯函数内核。

core 不碰 DB（spec/backend/directory-structure.md §Module Organization：
core 函数签名一律接收已加载的内存数据 + now 参数，不接收数据库连接）。
因此本模块输入是内存里的 recurring 任务列表 + today + backfill_days + 已存在的
occurrence 日期集合，输出**需要补齐的 occurrence 描述列表**，由调用方
（scheduler/store）落库。

幂等语义：给定 recur_rule 算出从 (today - backfill_days) 到 today 之间应有的
occurrence 日期，与已存在的对比，输出缺失的。

改规则只重算未来、过去冻结：已存在的过去 occurrence 不在输出里
（不能改写历史，design.md §3.3）。

recur_rule 是 RRULE 子集，本任务支持 FREQ=DAILY 与 FREQ=WEEKLY（BYDAY）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from core.schedule import RecurTarget


@dataclass(frozen=True)
class RecurringTaskView:
    """ensure_occurrences 需要的 recurring 任务视图。

    不直接依赖 store 模型，由调用方从投影表取好传入。
    `existing_dates` 是该任务**已存在**的 occurrence 日期集合（YYYY-MM-DD），
    用于幂等去重与"过去冻结"判定。
    """

    id: str
    recur_rule: str
    recur_target: RecurTarget | None
    created_at: date  # 任务创建日，occurrence 不会早于此日
    existing_dates: frozenset[date]


@dataclass(frozen=True)
class OccurrenceToCreate:
    """需要补齐的 occurrence 描述。调用方据此 INSERT。"""

    task_id: str
    occurrence_date: date
    target_amount: float | None  # 取自 recur_target.amount；无 target 则 None


def _parse_freq(rule: str) -> str | None:
    """从 RRULE 子集解析 FREQ。只认 FREQ=DAILY / FREQ=WEEKLY。"""
    for part in rule.split(";"):
        part = part.strip().upper()
        if part.startswith("FREQ="):
            return part.split("=", 1)[1]
    return None


def _parse_interval(rule: str) -> int:
    """解析 INTERVAL，默认 1。"""
    for part in rule.split(";"):
        part = part.strip().upper()
        if part.startswith("INTERVAL="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return 1
    return 1


def _parse_byday(rule: str) -> set[int] | None:
    """解析 BYDAY，返回星期几集合（周一=0..周日=6）。无 BYDAY 返回 None。"""
    mapping = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    for part in rule.split(";"):
        part = part.strip().upper()
        if part.startswith("BYDAY="):
            days: set[int] = set()
            for token in part.split("=", 1)[1].split(","):
                token = token.strip()
                if token in mapping:
                    days.add(mapping[token])
            return days if days else None
    return None


def _expected_dates(task: RecurringTaskView, start: date, end: date) -> list[date]:
    """算出 [start, end] 闭区间内该任务应有的 occurrence 日期。

    - 起点取 max(start, created_at)：任务创建前不应有 occurrence。
    - DAILY：从起点按 INTERVAL 天步进，含起点（若起点本身应有）。
    - WEEKLY：按 INTERVAL 周步进；有 BYDAY 则取每周指定星期，否则取 created_at 的星期。
    """
    if end < start:
        return []
    freq = _parse_freq(task.recur_rule)
    interval = max(1, _parse_interval(task.recur_rule))
    # 任务创建前不应有 occurrence。
    lo = max(start, task.created_at)
    if lo > end:
        return []

    out: list[date] = []
    if freq == "DAILY":
        # 找到 >= lo 的第一个对齐日：从 created_at 按 interval 步进。
        # 对齐基线用 created_at，使得改 interval 时序列稳定。
        base = task.created_at
        # 步进到 >= lo
        delta = (lo - base).days
        steps = max(0, (delta + interval - 1) // interval) if interval > 0 else 0
        cur = base + timedelta(days=steps * interval)
        while cur <= end:
            if cur >= lo:
                out.append(cur)
            cur += timedelta(days=interval)
    elif freq == "WEEKLY":
        byday = _parse_byday(task.recur_rule)
        base = task.created_at
        # 逐日扫描 [lo, end]，判断是否落在"应有的周 + 应有的星期"上。
        # 对齐：以 created_at 所在周为第 0 周，每 interval 周一轮。
        base_week_monday = base - timedelta(days=base.weekday())
        cur = lo
        while cur <= end:
            cur_week_monday = cur - timedelta(days=cur.weekday())
            weeks_diff = (cur_week_monday - base_week_monday).days // 7
            in_cycle = (weeks_diff % interval) == 0 if interval > 0 else True
            if in_cycle:
                if byday is None:
                    # 无 BYDAY：取 created_at 的星期
                    if cur.weekday() == base.weekday():
                        out.append(cur)
                else:
                    if cur.weekday() in byday:
                        out.append(cur)
            cur += timedelta(days=1)
    return out


def ensure_occurrences_up_to(
    tasks: list[RecurringTaskView],
    today: date,
    backfill_days: int = 30,
) -> list[OccurrenceToCreate]:
    """算出需要补齐的 occurrence 列表（纯函数，不写库）。

    - 窗口 [today - backfill_days, today] 闭区间。
    - 与各任务 existing_dates 对比，输出缺失的。
    - 已存在的过去 occurrence 不输出（历史冻结，design.md §3.3）。
    - target_amount 取 recur_target.amount；无 recur_target 则 None。

    幂等：多次调用同一输入结果一致；已存在的不会重复输出。
    """
    start = today - timedelta(days=backfill_days)
    out: list[OccurrenceToCreate] = []
    for task in tasks:
        for d in _expected_dates(task, start, today):
            if d in task.existing_dates:
                continue  # 已存在，幂等跳过（含过去已冻结的）
            target = task.recur_target.amount if task.recur_target is not None else None
            out.append(
                OccurrenceToCreate(
                    task_id=task.id,
                    occurrence_date=d,
                    target_amount=target,
                )
            )
    return out


__all__ = [
    "OccurrenceToCreate",
    "RecurringTaskView",
    "ensure_occurrences_up_to",
]
