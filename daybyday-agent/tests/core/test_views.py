"""today_view 测试。

验证：
- one_shot in_progress 出现在 today_view
- deadline 未到 lead_days 窗口不进催办区（验收第 2 条）
- recurring 当日 occurrence 出现
- 已 done/abandoned 不出现
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from core.schedule import ScheduleKind, Weight
from core.views import (
    OccurrenceView,
    TaskView,
    TodayView,
    today_view,
)

NOW = datetime(2026, 8, 4, 18, 30, tzinfo=UTC)
TODAY = NOW.date()


def _task(
    tid: str = "t1",
    kind: ScheduleKind = ScheduleKind.ONE_SHOT,
    status: str = "in_progress",
    weight: Weight = Weight.M,
    due_at: datetime | None = None,
    last_activity_at: datetime | None = None,
) -> TaskView:
    return TaskView(
        id=tid,
        title=f"task-{tid}",
        schedule_kind=kind,
        weight=weight,
        status=status,
        due_at=due_at,
        last_activity_at=last_activity_at,
    )


def _occ(tid: str, d: date, status: str = "pending", target: float | None = 5.0) -> OccurrenceView:
    return OccurrenceView(
        task_id=tid,
        occurrence_date=d,
        target_amount=target,
        done_amount=0.0,
        status=status,
    )


def test_one_shot_in_progress_appears():
    """one_shot in_progress 出现在 today_view 的 in_progress 区。"""
    t = _task(tid="t1", kind=ScheduleKind.ONE_SHOT, status="in_progress")
    view = today_view([t], [], NOW)
    assert any(x.id == "t1" for x in view.in_progress)


def test_one_shot_pending_not_in_progress():
    """pending 状态的 one_shot 不在 in_progress 区（只显示 in_progress 的）。"""
    t = _task(tid="t1", kind=ScheduleKind.ONE_SHOT, status="pending")
    view = today_view([t], [], NOW)
    assert not any(x.id == "t1" for x in view.in_progress)


def test_deadline_not_in_window_excluded_from_nag_zone():
    """验收第 2 条：deadline 未到 lead_days 窗口不出现在催办区。

    M 任务 lead_days=2。due 在 10 天后，远超窗口 -> 不进催办区。
    """
    due = NOW + timedelta(days=10)
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        status="in_progress",
        weight=Weight.M,
        due_at=due,
    )
    view = today_view([t], [], NOW)
    assert not any(d.task.id == "t1" for d in view.deadlines)


def test_deadline_in_window_appears_in_nag_zone():
    """进入 lead_days 窗口的 deadline 进催办区。M lead_days=2，due 在 1 天后。"""
    due = NOW + timedelta(days=1)
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        status="in_progress",
        weight=Weight.M,
        due_at=due,
    )
    view = today_view([t], [], NOW)
    items = [d for d in view.deadlines if d.task.id == "t1"]
    assert len(items) == 1
    assert items[0].days_until_due == 1
    assert items[0].in_window


def test_deadline_due_today_in_nag_zone():
    """due 当天进催办区，days_until_due=0。"""
    due = datetime(2026, 8, 4, 23, 59, tzinfo=UTC)
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        status="in_progress",
        weight=Weight.S,  # lead_days=1
        due_at=due,
    )
    view = today_view([t], [], NOW)
    items = [d for d in view.deadlines if d.task.id == "t1"]
    assert len(items) == 1
    assert items[0].days_until_due == 0


def test_deadline_overdue_in_nag_zone():
    """逾期 deadline 进催办区，days_until_due 为负。"""
    due = NOW - timedelta(days=3)
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        status="in_progress",
        weight=Weight.M,
        due_at=due,
    )
    view = today_view([t], [], NOW)
    items = [d for d in view.deadlines if d.task.id == "t1"]
    assert len(items) == 1
    assert items[0].days_until_due == -3


def test_deadline_not_in_window_but_in_progress_shown_in_general():
    """未到窗口的 deadline：若 in_progress，仍显示在通用 in_progress 区，但不进催办区。"""
    due = NOW + timedelta(days=10)
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        status="in_progress",
        weight=Weight.M,
        due_at=due,
    )
    view = today_view([t], [], NOW)
    # 不在催办区
    assert not any(d.task.id == "t1" for d in view.deadlines)
    # 但在通用 in_progress 区
    assert any(x.id == "t1" for x in view.in_progress)


def test_recurring_today_occurrence_appears():
    """recurring 当日 occurrence 出现在 recurring_today。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING, status="in_progress")
    o = _occ("t1", TODAY, status="pending")
    view = today_view([t], [o], NOW)
    assert any(oc.task_id == "t1" for oc in view.recurring_today)


def test_recurring_today_done_excluded():
    """当日 occurrence 已 done 不出现在 recurring_today。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING, status="in_progress")
    o = _occ("t1", TODAY, status="done")
    view = today_view([t], [o], NOW)
    assert not any(oc.task_id == "t1" for oc in view.recurring_today)


def test_recurring_today_partial_included():
    """partial 状态的当日 occurrence 仍出现（未完成）。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING, status="in_progress")
    o = _occ("t1", TODAY, status="partial")
    view = today_view([t], [o], NOW)
    assert any(oc.task_id == "t1" for oc in view.recurring_today)


def test_done_task_excluded():
    """done 状态的任务不出现在任何区。"""
    t = _task(tid="t1", status="done")
    view = today_view([t], [], NOW)
    assert not any(x.id == "t1" for x in view.in_progress)
    assert not any(d.task.id == "t1" for d in view.deadlines)


def test_abandoned_task_excluded():
    t = _task(tid="t1", status="abandoned")
    view = today_view([t], [], NOW)
    assert not any(x.id == "t1" for x in view.in_progress)


def test_openended_in_progress_appears():
    """openended in_progress 出现在通用 in_progress 区。"""
    t = _task(tid="t1", kind=ScheduleKind.OPENENDED, status="in_progress")
    view = today_view([t], [], NOW)
    assert any(x.id == "t1" for x in view.in_progress)


def test_today_from_now_when_not_provided():
    """today 缺省取 now 的日期。"""
    due = NOW + timedelta(days=1)
    t = _task(tid="t1", kind=ScheduleKind.DEADLINE, weight=Weight.M, due_at=due)
    view = today_view([t], [], NOW)
    assert any(d.task.id == "t1" for d in view.deadlines)


def test_today_override_for_cross_day_test():
    """显式传 today 用于跨日测试。"""
    # now 是 8-04，但假装今天是 8-05
    tomorrow = TODAY + timedelta(days=1)
    due = datetime(2026, 8, 5, 23, 59, tzinfo=UTC)
    t = _task(tid="t1", kind=ScheduleKind.DEADLINE, weight=Weight.S, due_at=due)
    view = today_view([t], [], NOW, today=tomorrow)
    items = [d for d in view.deadlines if d.task.id == "t1"]
    assert len(items) == 1
    assert items[0].days_until_due == 0


def test_returns_today_view_instance():
    t = _task(tid="t1")
    view = today_view([t], [], NOW)
    assert isinstance(view, TodayView)
