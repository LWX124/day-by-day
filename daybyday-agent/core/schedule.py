"""Schedule 联合类型与非法组合校验。

四态：one_shot / deadline / recurring / openended。
非法组合在写入层拒绝（recurring 不许有 due 等），见 design.md §3.1。

本模块是纯函数域的一部分，不依赖任何外部。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ScheduleKind(StrEnum):
    ONE_SHOT = "one_shot"
    DEADLINE = "deadline"
    RECURRING = "recurring"
    OPENENDED = "openended"


class Weight(StrEnum):
    """任务重量，决定庆祝档位与 idle 阈值。"""

    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


@dataclass(frozen=True)
class RecurTarget:
    """Recurring 任务的每日目标量（如每天读 5 页）。"""

    amount: float
    unit: str


@dataclass(frozen=True)
class Schedule:
    """四态联合类型。各字段按 kind 取值，非法组合由 validate 拒绝。"""

    kind: ScheduleKind
    due_at: datetime | None = None  # 仅 deadline
    recur_rule: str | None = None  # 仅 recurring（RRULE 子集）
    recur_target: RecurTarget | None = None  # 仅 recurring

    def validate(self) -> None:
        """拒绝非法组合。调用方在写入层调用。

        各字段按 kind 独占（design.md §3.1 表）：due_at 仅 deadline，
        recur_rule/recur_target 仅 recurring，其余两态无独有字段。
        """
        if self.kind is ScheduleKind.DEADLINE and self.due_at is None:
            raise ValueError("deadline schedule 必须有 due_at")
        if self.kind is ScheduleKind.RECURRING and self.recur_rule is None:
            raise ValueError("recurring schedule 必须有 recur_rule")
        if self.kind is ScheduleKind.RECURRING and self.due_at is not None:
            raise ValueError("recurring schedule 不允许有 due_at")
        if self.kind is ScheduleKind.ONE_SHOT and self.due_at is not None:
            raise ValueError("one_shot schedule 不应有 due_at（用 deadline）")
        if self.kind is ScheduleKind.OPENENDED and self.due_at is not None:
            raise ValueError("openended schedule 不应有 due_at")
        # 独有字段不得跨 kind：非 recurring 不许带 recur_rule / recur_target。
        if self.kind is not ScheduleKind.RECURRING and self.recur_rule is not None:
            raise ValueError(f"{self.kind.value} schedule 不允许有 recur_rule")
        if self.kind is not ScheduleKind.RECURRING and self.recur_target is not None:
            raise ValueError(f"{self.kind.value} schedule 不允许有 recur_target")


def idle_threshold(weight: Weight) -> int:
    """OneShot 任务的 idle 阈值（天），按 Weight 递增。可配，这里给默认。"""
    return {Weight.S: 7, Weight.M: 14, Weight.L: 21, Weight.XL: 30}[weight]


def lead_days(weight: Weight) -> int:
    """Deadline 任务的提醒前置天数。"""
    return {Weight.S: 1, Weight.M: 2, Weight.L: 3, Weight.XL: 5}[weight]
