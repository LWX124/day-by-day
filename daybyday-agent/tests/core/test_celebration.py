"""Celebration Tier 测试。验证：Weight 基线、拖延加成、里程碑加成、逾期不降档、clamp。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.celebration import TaskForTier, celebration_tier
from core.schedule import Weight

NOW = datetime(2026, 8, 4, 18, 30, tzinfo=UTC)


def _task(weight: Weight, days_ago: int, due=None) -> TaskForTier:
    return TaskForTier(weight=weight, created_at=NOW - timedelta(days=days_ago), due_at=due)


def test_weight_baseline():
    assert celebration_tier(_task(Weight.S, days_ago=1), NOW) == 1
    assert celebration_tier(_task(Weight.M, days_ago=1), NOW) == 2
    assert celebration_tier(_task(Weight.L, days_ago=1), NOW) == 3
    assert celebration_tier(_task(Weight.XL, days_ago=1), NOW) == 4


def test_overdue_boost():
    """拖了超过 30 天才完成，+1 档。"""
    assert celebration_tier(_task(Weight.M, days_ago=31), NOW) == 3  # 2 + 1
    assert celebration_tier(_task(Weight.M, days_ago=29), NOW) == 2  # 不够 30 不加


def test_milestone_boost():
    assert celebration_tier(_task(Weight.S, days_ago=1), NOW, is_milestone=True) == 2  # 1 + 1


def test_xl_clamps_at_4():
    """XL + 拖延 + 里程碑仍 clamp 到 4。"""
    assert (
        celebration_tier(_task(Weight.XL, days_ago=60), NOW, is_milestone=True) == 4
    )  # 4 + 1 + 1 -> 4


def test_overdue_completion_not_downgraded():
    """逾期完成不比按时完成档位低。无 due 的 overdue boost 只看 created_at，不降档。"""
    # M 任务拖 40 天完成，得 3；按时（1 天）得 2。逾期完成反而更高，符合"情绪峰值"设计。
    assert celebration_tier(_task(Weight.M, days_ago=40), NOW) == 3
