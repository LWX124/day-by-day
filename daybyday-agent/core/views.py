"""today_view 纯函数。

输入今日相关任务 + occurrences + now，输出今日应做的结构化视图。

包含三类（design.md §5.1、PRD 验收）：
- deadline 到期/临近的（但**未到 lead_days 窗口的 deadline 不进催办区**——
  对应验收第 2 条"未到 lead_days 窗口不出现在 today_view 的催办区"）
- recurring 当日 occurrence
- 其他 in_progress 的任务（one_shot / openended）

纯函数，不读系统时钟（now 作参数传入），不碰 DB。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from core.schedule import ScheduleKind, Weight, lead_days


@dataclass(frozen=True)
class TaskView:
    """today_view 需要的任务视图。由调用方从投影表取好传入。"""

    id: str
    title: str
    schedule_kind: ScheduleKind
    weight: Weight
    status: str  # pending | in_progress | done | deferred | abandoned
    due_at: datetime | None
    last_activity_at: datetime | None


@dataclass(frozen=True)
class OccurrenceView:
    """今日 occurrence 视图。"""

    task_id: str
    occurrence_date: date
    target_amount: float | None
    done_amount: float
    status: str  # pending | partial | done | skipped


@dataclass(frozen=True)
class TodayDeadlineItem:
    """催办区里的 deadline 项。"""

    task: TaskView
    days_until_due: int  # 负数=已逾期，0=今天，正数=未来
    in_window: bool  # 是否已进入 lead_days 窗口


@dataclass(frozen=True)
class TodayView:
    """今日视图。"""

    # 今日应做的 recurring occurrence（含 partial / pending）
    recurring_today: list[OccurrenceView] = field(default_factory=list)
    # 进入催办窗口的 deadline 任务
    deadlines: list[TodayDeadlineItem] = field(default_factory=list)
    # 其他 in_progress 的任务（one_shot / openended / 未到窗口的 deadline 不在此）
    in_progress: list[TaskView] = field(default_factory=list)


def _to_date(dt: datetime) -> date:
    return dt.date()


def today_view(
    tasks: list[TaskView],
    occurrences: list[OccurrenceView],
    now: datetime,
    today: date | None = None,
) -> TodayView:
    """算今日视图。

    - recurring_today：occurrences 里 occurrence_date == today 的（状态非 done/skipped）。
    - deadlines：schedule_kind == deadline 且 status != done/abandoned 的任务，
      计算 days_until_due。**仅当 days_until_due <= lead_days(weight) 才进催办区**
      （验收第 2 条）。逾期任务一律进催办区。
    - in_progress：status == in_progress 的其他任务（one_shot / openended，
      以及未到窗口的 deadline 仍按 in_progress 显示在通用区，但不进催办区）。

    `today` 缺省取 now 的日期（允许伪造时钟时同时伪造 today，便于跨日测试）。
    """
    td = today if today is not None else _to_date(now)

    recurring_today = [
        o
        for o in occurrences
        if o.occurrence_date == td and o.status not in ("done", "skipped")
    ]

    deadlines: list[TodayDeadlineItem] = []
    in_progress: list[TaskView] = []
    for t in tasks:
        if t.status in ("done", "abandoned"):
            continue
        if t.schedule_kind is ScheduleKind.DEADLINE and t.due_at is not None:
            due_date = _to_date(t.due_at)
            days_until_due = (due_date - td).days
            window = lead_days(t.weight)
            in_window = days_until_due <= window
            if in_window:
                deadlines.append(
                    TodayDeadlineItem(task=t, days_until_due=days_until_due, in_window=True)
                )
            elif t.status == "in_progress":
                # 未到窗口的 deadline：若已在推进中，仍显示在通用 in_progress 区，
                # 但不进催办区（验收第 2 条只约束"催办区"）。
                in_progress.append(t)
        elif t.status == "in_progress":
            in_progress.append(t)

    return TodayView(
        recurring_today=recurring_today,
        deadlines=deadlines,
        in_progress=in_progress,
    )


__all__ = [
    "OccurrenceView",
    "TaskView",
    "TodayDeadlineItem",
    "TodayView",
    "today_view",
]
