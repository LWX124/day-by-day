"""due_nags 四策略边界测试。

验证：
- deadline 未到窗口不触发
- recurring 不因总时长触发（只看断签）
- one_shot 按 weight 阈值
- openended 月度且本月已 review 不重复
- 所有函数纯内存，不碰 DB
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from core.nag import NagCandidate, NagOccurrenceView, NagTaskView, due_nags
from core.schedule import ScheduleKind, Weight

NOW = datetime(2026, 8, 4, 18, 30, tzinfo=UTC)
TODAY = NOW.date()


def _task(
    tid: str = "t1",
    kind: ScheduleKind = ScheduleKind.ONE_SHOT,
    weight: Weight = Weight.M,
    status: str = "in_progress",
    due_at: datetime | None = None,
    last_activity_at: datetime | None = None,
    last_reviewed_at: datetime | None = None,
    nag_count: int = 0,
) -> NagTaskView:
    return NagTaskView(
        id=tid,
        schedule_kind=kind,
        weight=weight,
        status=status,
        due_at=due_at,
        last_activity_at=last_activity_at,
        last_reviewed_at=last_reviewed_at,
        nag_count=nag_count,
    )


def _occ(tid: str, d: date, status: str = "pending") -> NagOccurrenceView:
    return NagOccurrenceView(task_id=tid, occurrence_date=d, status=status)


def _ids(cands: list[NagCandidate]) -> set[str]:
    return {c.task_id for c in cands}


# ---- one_shot ----


def test_one_shot_idle_by_weight_threshold():
    """M 阈值 14 天，超过才触发。"""
    # 13 天：不触发
    t = _task(
        tid="t1",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.M,
        last_activity_at=NOW - timedelta(days=13),
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))
    # 15 天：触发
    t2 = _task(
        tid="t2",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.M,
        last_activity_at=NOW - timedelta(days=15),
    )
    assert "t2" in _ids(due_nags([t2], [], NOW))


def test_one_shot_s_threshold_is_7():
    """S 阈值 7 天。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.S,
        last_activity_at=NOW - timedelta(days=8),
    )
    assert "t1" in _ids(due_nags([t], [], NOW))


def test_one_shot_xl_threshold_is_30():
    """XL 阈值 30 天。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.XL,
        last_activity_at=NOW - timedelta(days=29),
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))
    t2 = _task(
        tid="t2",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.XL,
        last_activity_at=NOW - timedelta(days=31),
    )
    assert "t2" in _ids(due_nags([t2], [], NOW))


def test_one_shot_recent_activity_not_triggered():
    """有近期活动不触发。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.S,
        last_activity_at=NOW - timedelta(days=1),
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


def test_one_shot_never_active_triggered():
    """从未活动过视为 idle。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.S,
        last_activity_at=None,
    )
    assert "t1" in _ids(due_nags([t], [], NOW))


def test_one_shot_done_not_triggered():
    """done 状态不触发。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.S,
        status="done",
        last_activity_at=NOW - timedelta(days=100),
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


# ---- deadline ----


def test_deadline_not_in_window_not_triggered():
    """未到 lead_days 窗口不触发。M lead_days=2，due 在 10 天后。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.M,
        due_at=NOW + timedelta(days=10),
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


def test_deadline_in_window_triggered():
    """进入窗口触发。M lead_days=2，due 在 1 天后。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.M,
        due_at=NOW + timedelta(days=1),
    )
    assert "t1" in _ids(due_nags([t], [], NOW))


def test_deadline_due_today_triggered():
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.S,
        due_at=NOW + timedelta(hours=2),
    )
    cands = due_nags([t], [], NOW)
    assert "t1" in _ids(cands)
    assert any(c.reason == "deadline_due_today" for c in cands if c.task_id == "t1")


def test_deadline_overdue_triggered():
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.M,
        due_at=NOW - timedelta(days=3),
    )
    cands = due_nags([t], [], NOW)
    assert "t1" in _ids(cands)
    assert any(c.reason == "deadline_overdue" for c in cands if c.task_id == "t1")


def test_deadline_weight_affects_window():
    """S lead_days=1，due 在 2 天后 -> 不触发（S 窗口窄）。"""
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.S,
        due_at=NOW + timedelta(days=2),
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


def test_deadline_done_not_triggered():
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.M,
        status="done",
        due_at=NOW - timedelta(days=3),  # 逾期但已完成
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


# ---- recurring ----


def test_recurring_broken_streak_2_triggered():
    """连续断签 >= 2 触发。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING)
    occs = [
        _occ("t1", TODAY - timedelta(days=2), "pending"),
        _occ("t1", TODAY - timedelta(days=1), "pending"),
    ]
    assert "t1" in _ids(due_nags([t], occs, NOW))


def test_recurring_broken_streak_1_not_triggered():
    """断签 1 个不触发（< 2）。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING)
    occs = [_occ("t1", TODAY - timedelta(days=1), "pending")]
    assert "t1" not in _ids(due_nags([t], occs, NOW))


def test_recurring_done_breaks_streak():
    """中间有 done 则断签计数中断。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING)
    occs = [
        _occ("t1", TODAY - timedelta(days=3), "pending"),
        _occ("t1", TODAY - timedelta(days=2), "done"),  # 中断
        _occ("t1", TODAY - timedelta(days=1), "pending"),
    ]
    # 从最近往前数：1 个 pending -> 不触发
    assert "t1" not in _ids(due_nags([t], occs, NOW))


def test_recurring_skipped_breaks_streak():
    """skipped 也算中断（不算断签）。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING)
    occs = [
        _occ("t1", TODAY - timedelta(days=2), "skipped"),
        _occ("t1", TODAY - timedelta(days=1), "pending"),
    ]
    assert "t1" not in _ids(due_nags([t], occs, NOW))


def test_recurring_not_triggered_by_total_duration():
    """永不因总时长触发：即使任务创建很久，只要不断签就不催。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING)
    occs = [
        _occ("t1", TODAY - timedelta(days=100), "done"),
        _occ("t1", TODAY - timedelta(days=1), "done"),
    ]
    assert "t1" not in _ids(due_nags([t], occs, NOW))


def test_recurring_done_task_not_triggered():
    t = _task(tid="t1", kind=ScheduleKind.RECURRING, status="done")
    occs = [
        _occ("t1", TODAY - timedelta(days=2), "pending"),
        _occ("t1", TODAY - timedelta(days=1), "pending"),
    ]
    assert "t1" not in _ids(due_nags([t], occs, NOW))


def test_recurring_future_occurrence_not_counted():
    """未来的 occurrence 不计入断签（只数 <= today 的）。"""
    t = _task(tid="t1", kind=ScheduleKind.RECURRING)
    occs = [
        _occ("t1", TODAY + timedelta(days=1), "pending"),  # 未来
    ]
    assert "t1" not in _ids(due_nags([t], occs, NOW))


# ---- openended ----


def test_openended_never_reviewed_triggered():
    t = _task(tid="t1", kind=ScheduleKind.OPENENDED, last_reviewed_at=None)
    assert "t1" in _ids(due_nags([t], [], NOW))


def test_openended_review_over_30_days_triggered():
    t = _task(
        tid="t1",
        kind=ScheduleKind.OPENENDED,
        last_reviewed_at=NOW - timedelta(days=31),
    )
    assert "t1" in _ids(due_nags([t], [], NOW))


def test_openended_review_under_30_days_not_triggered():
    t = _task(
        tid="t1",
        kind=ScheduleKind.OPENENDED,
        last_reviewed_at=NOW - timedelta(days=29),
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


def test_openended_reviewed_this_month_not_triggered():
    """本月已 review 过不触发（即使 > 30 天，但同月）。

    构造：last_reviewed 在本月 1 号，今天是 8-04，差 3 天 -> 不触发。
    用更极端的：假设 today 是 8-31，last_review 是 8-01，差 30 天但同月 -> 不触发。
    """
    # 8 月 1 日 review 过，今天 8 月 4 日：同月不触发
    last_review = datetime(2026, 8, 1, tzinfo=UTC)
    t = _task(
        tid="t1",
        kind=ScheduleKind.OPENENDED,
        last_reviewed_at=last_review,
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


def test_openended_reviewed_last_month_over_30_days_triggered():
    """上月 review 过，距今 > 30 天 -> 触发。"""
    last_review = datetime(2026, 6, 1, tzinfo=UTC)  # 6-01，距今 > 60 天
    t = _task(
        tid="t1",
        kind=ScheduleKind.OPENENDED,
        last_reviewed_at=last_review,
    )
    assert "t1" in _ids(due_nags([t], [], NOW))


def test_openended_done_not_triggered():
    t = _task(
        tid="t1",
        kind=ScheduleKind.OPENENDED,
        status="done",
        last_reviewed_at=None,
    )
    assert "t1" not in _ids(due_nags([t], [], NOW))


# ---- 聚合 ----


def test_due_nags_aggregates_all_four_strategies():
    """四个策略同时有候选时全部输出。"""
    one_shot = _task(
        tid="os",
        kind=ScheduleKind.ONE_SHOT,
        weight=Weight.S,
        last_activity_at=NOW - timedelta(days=10),
    )
    deadline = _task(
        tid="dl",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.M,
        due_at=NOW + timedelta(days=1),
    )
    recurring = _task(tid="rc", kind=ScheduleKind.RECURRING)
    rec_occs = [
        _occ("rc", TODAY - timedelta(days=2), "pending"),
        _occ("rc", TODAY - timedelta(days=1), "pending"),
    ]
    openended = _task(tid="oe", kind=ScheduleKind.OPENENDED, last_reviewed_at=None)
    cands = due_nags([one_shot, deadline, recurring, openended], rec_occs, NOW)
    assert _ids(cands) == {"os", "dl", "rc", "oe"}


def test_due_nags_empty_input():
    assert due_nags([], [], NOW) == []


def test_due_nags_today_from_now():
    """today 缺省取 now 的日期。"""
    # due 在 8-05（明天），M lead_days=2 -> 进窗口
    t = _task(
        tid="t1",
        kind=ScheduleKind.DEADLINE,
        weight=Weight.M,
        due_at=datetime(2026, 8, 5, 12, tzinfo=UTC),
    )
    assert "t1" in _ids(due_nags([t], [], NOW))
