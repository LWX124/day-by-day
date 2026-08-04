"""Celebration Tier 纯函数。

按 Weight 基线 + 拖延加成 + 里程碑加成算 1-4 档，见 design.md §5.3。
纯函数，不读系统时钟（now 作参数传入）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.schedule import Weight

MAX_TIER = 4
# 拖延超过这么多天才触发加成（"拖了一个月终于干掉"的情绪峰值）
OVERDUE_BOOST_DAYS = 30


@dataclass(frozen=True)
class TaskForTier:
    """celebration_tier 需要的任务视图。不直接依赖 store/agent，由调用方传入。"""

    weight: Weight
    created_at: datetime
    due_at: datetime | None


def celebration_tier(task: TaskForTier, now: datetime, is_milestone: bool = False) -> int:
    """算特效档位。逾期完成不降档（完成就该庆祝）。"""
    base = {Weight.S: 1, Weight.M: 2, Weight.L: 3, Weight.XL: 4}[task.weight]
    tier = base
    age_days = (now - task.created_at).days
    if age_days > OVERDUE_BOOST_DAYS:
        tier += 1
    if is_milestone:
        tier += 1
    return min(tier, MAX_TIER)
