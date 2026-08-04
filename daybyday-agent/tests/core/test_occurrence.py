"""ensure_occurrences_up_to 测试。

验证：
- 幂等：已存在的 occurrence 不重复输出
- 改 recur_rule 后未来重算、过去冻结
- sleep 一晚后补齐当日 occurrence
- 不碰 DB（纯内存数据）
"""

from __future__ import annotations

from datetime import date, timedelta

from core.occurrence import (
    OccurrenceToCreate,
    RecurringTaskView,
    ensure_occurrences_up_to,
)
from core.schedule import RecurTarget

TODAY = date(2026, 8, 4)


def _task(
    tid: str = "t1",
    rule: str = "FREQ=DAILY",
    target: RecurTarget | None = None,
    created_at: date = date(2026, 7, 1),
    existing: frozenset[date] | None = None,
) -> RecurringTaskView:
    return RecurringTaskView(
        id=tid,
        recur_rule=rule,
        recur_target=target,
        created_at=created_at,
        existing_dates=existing or frozenset(),
    )


def test_daily_backfill_creates_missing():
    """新建 daily recurring 任务，从未生成 occurrence，backfill 30 天应补齐。"""
    t = _task(existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=30)
    # created_at = 2026-07-01，窗口 [2026-07-05, 2026-08-04]，含两端
    # 从 created_at 每天一个，到 today
    expected_dates = []
    d = date(2026, 7, 5)  # 窗口起点
    # 但 created_at 是 7-01 < 窗口起点，所以从窗口起点开始
    while d <= TODAY:
        expected_dates.append(d)
        d += timedelta(days=1)
    assert {o.occurrence_date for o in out} == set(expected_dates)
    # 全部归属同一 task
    assert all(o.task_id == "t1" for o in out)


def test_daily_idempotent_existing_skipped():
    """已存在的 occurrence 不输出。"""
    # 已生成前 20 天
    existing = {TODAY - timedelta(days=i) for i in range(20)}
    t = _task(existing=frozenset(existing))
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=30)
    out_dates = {o.occurrence_date for o in out}
    assert out_dates.isdisjoint(existing)
    # 但补齐了窗口内其余日子
    start = TODAY - timedelta(days=30)
    expected = set()
    d = max(start, date(2026, 7, 1))
    while d <= TODAY:
        if d not in existing:
            expected.add(d)
        d += timedelta(days=1)
    assert out_dates == expected


def test_change_recur_rule_future_recomputed_past_frozen():
    """改 recur_rule 后：未来 occurrence 重算，过去冻结（已存在的不动）。

    场景：daily 任务，已存在过去 10 天的 occurrence。改成 WEEKLY 后，
    过去已存在的不被输出（冻结），未来的按 WEEKLY 算。
    """
    past_existing = {TODAY - timedelta(days=i) for i in range(1, 11)}  # 过去 10 天
    t = _task(
        rule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",  # 改成工作日
        existing=frozenset(past_existing),
        created_at=date(2026, 7, 1),
    )
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=30)
    out_dates = {o.occurrence_date for o in out}
    # 过去已存在的不输出（冻结）
    assert out_dates.isdisjoint(past_existing)
    # 今天（2026-08-04 是周二）应在 BYDAY 里，且未存在 -> 应输出
    assert TODAY.weekday() == 1  # 周二
    assert TODAY in out_dates


def test_daily_sleep_one_night_creates_today():
    """sleep 一晚后 ensure_occurrences 补齐当日 occurrence 且不重复。"""
    # 昨天已存在
    yesterday = TODAY - timedelta(days=1)
    t = _task(existing=frozenset({yesterday}))
    # 假装"昨晚"跑过一次，现在今天再跑
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=30)
    assert TODAY in {o.occurrence_date for o in out}
    # 昨天的不重复
    assert yesterday not in {o.occurrence_date for o in out}


def test_no_target_amount_when_recur_target_none():
    """无 recur_target 时 target_amount 为 None。"""
    t = _task(rule="FREQ=DAILY", target=None, existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=5)
    assert all(o.target_amount is None for o in out)


def test_target_amount_from_recur_target():
    """有 recur_target 时 target_amount 取其 amount。"""
    t = _task(rule="FREQ=DAILY", target=RecurTarget(amount=5, unit="页"), existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=5)
    assert all(o.target_amount == 5.0 for o in out)


def test_weekly_byday_only_matching_weekdays():
    """WEEKLY;BYDAY=MO 只在周一生成。"""
    # 2026-08-03 是周一
    monday = date(2026, 8, 3)
    assert monday.weekday() == 0
    t = _task(rule="FREQ=WEEKLY;BYDAY=MO", created_at=date(2026, 7, 1), existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=30)
    out_dates = {o.occurrence_date for o in out}
    # 全是周一
    assert all(d.weekday() == 0 for d in out_dates)
    # 含 8-03
    assert monday in out_dates


def test_created_at_before_window_start():
    """任务创建早于窗口起点，occurrence 从窗口起点开始算。"""
    t = _task(created_at=date(2026, 1, 1), existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=10)
    start = TODAY - timedelta(days=10)
    assert all(o.occurrence_date >= start for o in out)


def test_created_at_after_window_start():
    """任务创建晚于窗口起点，occurrence 从 created_at 开始算。"""
    created = TODAY - timedelta(days=3)
    t = _task(created_at=created, existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=30)
    out_dates = {o.occurrence_date for o in out}
    assert all(d >= created for d in out_dates)
    assert TODAY in out_dates


def test_interval_daily_step():
    """FREQ=DAILY;INTERVAL=2 隔天一个。"""
    t = _task(rule="FREQ=DAILY;INTERVAL=2", created_at=date(2026, 7, 5), existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=30)
    out_dates = sorted(o.occurrence_date for o in out)
    # 从 created_at（7-05）按 2 天步进
    expected = []
    d = date(2026, 7, 5)
    start = TODAY - timedelta(days=30)
    # 对齐到 >= start
    while d < start:
        d += timedelta(days=2)
    while d <= TODAY:
        expected.append(d)
        d += timedelta(days=2)
    assert out_dates == expected


def test_multiple_tasks():
    """多个任务混合，输出按 task 区分。"""
    t1 = _task(tid="t1", existing=frozenset())
    t2 = _task(tid="t2", rule="FREQ=WEEKLY;BYDAY=MO", existing=frozenset())
    out = ensure_occurrences_up_to([t1, t2], TODAY, backfill_days=7)
    t1_dates = {o.occurrence_date for o in out if o.task_id == "t1"}
    t2_dates = {o.occurrence_date for o in out if o.task_id == "t2"}
    assert TODAY in t1_dates
    # t2 只有周一
    assert all(d.weekday() == 0 for d in t2_dates)


def test_idempotent_repeated_calls():
    """多次调用同一输入结果一致。"""
    t = _task(existing=frozenset())
    out1 = ensure_occurrences_up_to([t], TODAY, backfill_days=10)
    out2 = ensure_occurrences_up_to([t], TODAY, backfill_days=10)
    assert out1 == out2


def test_occurrence_to_create_is_frozen_dataclass():
    """输出是 frozen dataclass，不可变。"""
    t = _task(existing=frozenset())
    out = ensure_occurrences_up_to([t], TODAY, backfill_days=3)
    assert len(out) > 0
    o = out[0]
    assert isinstance(o, OccurrenceToCreate)
    try:
        o.task_id = "x"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except AttributeError:
        pass
