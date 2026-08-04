"""Schedule 联合类型与校验测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.schedule import RecurTarget, Schedule, ScheduleKind, Weight, idle_threshold, lead_days


def test_one_shot_valid():
    s = Schedule(kind=ScheduleKind.ONE_SHOT)
    s.validate()  # 不抛


def test_deadline_requires_due():
    s = Schedule(kind=ScheduleKind.DEADLINE)
    with pytest.raises(ValueError, match="due_at"):
        s.validate()


def test_recurring_requires_rule():
    s = Schedule(kind=ScheduleKind.RECURRING)
    with pytest.raises(ValueError, match="recur_rule"):
        s.validate()


def test_recurring_rejects_due():
    s = Schedule(
        kind=ScheduleKind.RECURRING,
        recur_rule="FREQ=DAILY",
        recur_target=RecurTarget(amount=5, unit="页"),
        due_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="due_at"):
        s.validate()


def test_one_shot_rejects_due():
    s = Schedule(kind=ScheduleKind.ONE_SHOT, due_at=datetime(2026, 9, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="due_at"):
        s.validate()


def test_recurring_with_target_valid():
    s = Schedule(
        kind=ScheduleKind.RECURRING,
        recur_rule="FREQ=DAILY",
        recur_target=RecurTarget(amount=5, unit="页"),
    )
    s.validate()  # 不抛


def test_openended_valid():
    s = Schedule(kind=ScheduleKind.OPENENDED)
    s.validate()  # 不抛


def test_non_recurring_rejects_recur_rule():
    """recur_rule 是 recurring 独有字段，其余 kind 不许带。"""
    # one_shot / openended：直接带 recur_rule 应被拒。
    for kind in (ScheduleKind.ONE_SHOT, ScheduleKind.OPENENDED):
        s = Schedule(kind=kind, recur_rule="FREQ=DAILY")
        with pytest.raises(ValueError, match="recur_rule"):
            s.validate()
    # deadline：补齐 due_at 后带 recur_rule 也应被拒（否则先撞 due_at 缺失）。
    s = Schedule(
        kind=ScheduleKind.DEADLINE,
        due_at=datetime(2026, 9, 1, tzinfo=UTC),
        recur_rule="FREQ=DAILY",
    )
    with pytest.raises(ValueError, match="recur_rule"):
        s.validate()


def test_non_recurring_rejects_recur_target():
    """recur_target 是 recurring 独有字段。"""
    for kind in (ScheduleKind.ONE_SHOT, ScheduleKind.OPENENDED):
        s = Schedule(kind=kind, recur_target=RecurTarget(amount=5, unit="页"))
        with pytest.raises(ValueError, match="recur_target"):
            s.validate()


def test_idle_threshold_by_weight():
    assert idle_threshold(Weight.S) == 7
    assert idle_threshold(Weight.XL) == 30


def test_lead_days_by_weight():
    assert lead_days(Weight.S) == 1
    assert lead_days(Weight.XL) == 5
